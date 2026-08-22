"""Agent courtroom: four living opencode agents (Foreman + 3 jurors) in one Discord process.

Flow (same as the runbook, but every spoken line comes from a living agent with
session memory and tool access — it can read the repo, curl URLs, react to the thread):

  ping -> Foreman intro -> Builder asks -> team replies (Builder may follow up,
  team may ask Builder directly) -> handoff -> Skeptic -> ... -> Futurist ->
  Foreman summary -> time -> deterministic scoring/deliberation/verdict.
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

from ..discordx.transport import DiscordTransport
from ..discordx.config import DiscordConfig
from ..agents.brain import AgentBrain

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JUROR_AGENTS = [("juror_one", "builder"), ("juror_two", "skeptic"), ("juror_three", "futurist")]


class AgentCourt:
    def __init__(self, transport: DiscordTransport, config, out_dir="out", mock=False):
        self.t = transport
        self.config = config
        self.out = Path(out_dir)
        self.mock = mock
        self.brains = {name: AgentBrain(name) for _, name in JUROR_AGENTS}
        self.brains["foreman"] = AgentBrain("foreman")
        self.answers: dict[int, list[str]] = {}

    # ---------- context helpers ----------
    async def _history_text(self, thread, limit=25) -> str:
        try:
            msgs = await self.t.fetch_thread_history(thread, limit=limit)
            return "\n".join(f"{m['author']}: {m['text']}" for m in msgs if m["text"])
        except Exception as exc:
            print(f"history fetch failed: {exc.__class__.__name__}", flush=True)
            return "(thread history unavailable)"

    def _bundle_text(self, team_number: int) -> str:
        p = self.out / "judging.json"
        if not p.exists():
            return "(no evidence bundle yet)"
        try:
            entries = json.loads(p.read_text())
            e = next((x for x in entries if x.get("team_number") == team_number), None)
            if not e:
                return "(no evidence bundle for this team)"
            smoke = e.get("url_smoke") or {}
            lines = [
                f"team: {e.get('team_name')}",
                f"problem: {e.get('problem_statement','')[:400]}",
                f"project_url: {e.get('project_url')} (smoke: reachable={smoke.get('reachable')}, status={smoke.get('status_code')}, flags={smoke.get('flags')})",
                f"github_repo: {e.get('github_repo')}",
                f"demo_video_url: {e.get('demo_video_url') or '(none)'}",
                "key evidence notes:",
            ]
            for note in (e.get("evidence_notes") or [])[:6]:
                lines.append(f"- {note}")
            return "\n".join(lines)
        except Exception as exc:
            return f"(bundle parse error: {exc.__class__.__name__})"

    # ---------- foreman ----------
    async def foreman_say(self, thread, team_key: str, instruction: str) -> None:
        history = await self._history_text(thread)
        msg = (
            f"{instruction}\n\n"
            f"--- Recent thread ---\n{history[-2500:]}\n"
            "Write ONLY the line(s) to post now. Plain conversational text."
        )
        reply = await asyncio.to_thread(self.brains["foreman"].say, team_key, msg)
        if reply:
            await self.t.post_to_thread(thread, "foreman", reply)

    # ---------- jurors ----------
    async def juror_turn(self, thread, judge_id: str, agent: str, team_number: int, team_key: str) -> None:
        text = await self._juror_generate(judge_id, agent, team_number, team_key)
        if text:
            await self.t.post_to_thread(thread, judge_id, text)

    async def _juror_generate(self, judge_id: str, agent: str, team_number: int, team_key: str) -> str | None:
        bundle = self._bundle_text(team_number)
        history = await self._history_text(self.current_thread)
        msg = (
            f"It is YOUR turn to speak in the case thread. You are {agent}, questioning "
            f"{self._label(team_number)}.\n\n--- Evidence bundle ---\n{bundle}\n\n"
            f"--- Thread so far ---\n{history[-3000:]}\n\n"
            "Style: SHORT Discord chat, like a person typing. React to their submission in one casual line, then ask ONE simple question. "
            "2-3 sentences max total unless a question genuinely needs more. No lists, no labels, no essays. No scores. Write ONLY what you post."
        )
        reply = await asyncio.to_thread(self.brains[agent].say, team_key, msg)
        return reply or None

    async def _settle(self, team_number: int, settle_secs: int = 25) -> None:
        """Wait for message bursts to finish: teams often answer Q1 and Q2 in separate messages."""
        is_dry = self.config.qna_minutes < 1
        quiet = 4 if is_dry else settle_secs
        last = len(self.answers.get(team_number, []))
        while True:
            await asyncio.sleep(3 if not is_dry else 1)
            cur = len(self.answers.get(team_number, []))
            if cur != last:
                last = cur
                continue
            # no new messages for `quiet` seconds -> settled
            await asyncio.sleep(quiet - (3 if not is_dry else 1))
            if len(self.answers.get(team_number, [])) == last:
                return

    async def juror_followup_check(self, thread, judge_id: str, agent: str, team_number: int, team_key: str, display: str) -> bool:
        """Ask the CURRENT JUDGE whether their questions were covered. Judge either presses
        ONE follow-up (posted as them) or yields. Returns True if they posted a follow-up."""
        history = await self._history_text(thread)
        msg = (
            f"The team just answered your questions ({display} speaking). Review the thread below.\n\n"
            f"--- Thread ---\n{history[-2500:]}\n\n"
            "Decide:\n"
            "- If something important went unanswered or was vague, ask ONE short casual follow-up (1-2 sentences, human tone).\n"
            "- If you're satisfied, reply with exactly: NO_FOLLOW_UP\n"
            "No scores. Write ONLY your post."
        )
        reply = await asyncio.to_thread(self.brains[agent].say, team_key, msg)
        reply = (reply or "").strip()
        if not reply or "NO_FOLLOW_UP" in reply.upper():
            return False
        await self.t.post_to_thread(thread, judge_id, reply)
        return True

    async def juror_reply(self, thread, judge_id: str, agent: str, team_number: int, team_key: str, team_question: str) -> None:
        msg = (
            f"The team asked you directly in the thread: \"{team_question[:400]}\"\n"
            "Reply conversationally in 1-2 sentences. Ground it in their bundle and what you've seen. No scores. Write ONLY your reply."
        )
        reply = await asyncio.to_thread(self.brains[agent].say, team_key, msg)
        if reply:
            await self.t.post_to_thread(thread, judge_id, reply)

    # ---------- wait for team ----------
    async def wait_for_team(self, thread, team_number: int, current_judge_display: str, next_judge_display: str | None) -> bool:
        """Wait until the team posts something. Nudge after 2 min. Returns True if they replied."""
        import time as _time
        before = len(self.answers.get(team_number, []))
        elapsed = 0
        nudged = False
        while True:
            remaining = getattr(self, "deadline", None)
            if remaining is not None and _time.monotonic() >= remaining:
                return False
            await asyncio.sleep(2)
            elapsed += 2
            cur = len(self.answers.get(team_number, []))
            if cur > before:
                return True
            if not nudged and elapsed >= 120:
                nxt = f" before we move on to {next_judge_display}" if next_judge_display else ""
                await self.foreman_say(
                    thread, f"team_{team_number}",
                    f"The team has been silent for ~2 minutes. Write ONE warm nudge line asking them to reply to {current_judge_display}{nxt} — mention the clock is running and 'not built yet' is an acceptable answer.",
                )
                nudged = True
        return False

    def _label(self, n: int) -> str:
        return f"Team {n}"

    # ---------- main case flow ----------
    async def run_case(self, thread, team_number: int, participant_name: str, participant_id=None) -> None:
        import time as _time
        self.deadline = _time.monotonic() + self.config.qna_minutes * 60
        team_key = f"team_{team_number}"
        if participant_id is not None:
            await self.t.add_participant(thread, participant_id)

        # 1. Foreman intro (living)
        await self.foreman_say(
            thread, team_key,
            f"A new case is opening for {self._label(team_number)} (participant {participant_name}). "
            "Write your full courtroom introduction: welcome them, tell them they have a 7-minute shared clock, "
            "introduce the three judges by name and lens (Builder = does the demo actually work; Skeptic = is the problem real and viable; "
            "Futurist = does the agent truly improvise), state the rules (reply in this thread to the bot that asked you; answer as much as you can; "
            "'not built yet' is fine), say scores stay sealed, and announce that The Builder will begin.",
        )
        await self.t.post("foreman", "live_feed", f"A new case is called — {self._label(team_number)} steps before the bench.")

        # 2. Blind scoring happens deterministically in background (sheet + verdict need it)
        entry = await self._score_background(team_number)

        # 3. Sequential juror turns (settle window + judge-driven follow-ups + parallel handoff)
        import time as _time
        DISPLAY = {"juror_one": "The Builder", "juror_two": "The Skeptic", "juror_three": "The Futurist"}
        self.current_thread = thread
        next_gen = None
        for i, (judge_id, agent) in enumerate(JUROR_AGENTS):
            display = DISPLAY[judge_id]
            if i == 0:
                await self.juror_turn(thread, judge_id, agent, team_number, team_key)
            elif next_gen is not None:
                text = await next_gen
                if text:
                    await self.t.post_to_thread(thread, judge_id, text)
                next_gen = None
            else:
                await self.juror_turn(thread, judge_id, agent, team_number, team_key)

            replied = await self.wait_for_team(
                thread, team_number, display,
                next_judge_display=(DISPLAY[JUROR_AGENTS[i + 1][0]] if i + 1 < len(JUROR_AGENTS) else None),
            )
            # Settle burst answers (multi-message replies), then let THE JUDGE decide follow-ups (max 2 rounds)
            for _ in range(2):
                if not replied:
                    break
                await self._settle(team_number)
                has_fu = await self.juror_followup_check(thread, judge_id, agent, team_number, team_key, display)
                if not has_fu:
                    break
                replied = await self.wait_for_team(thread, team_number, display, None)

            if i + 1 < len(JUROR_AGENTS):
                nxt_jid, nxt_agent = JUROR_AGENTS[i + 1]
                nxt_display = DISPLAY[nxt_jid]
                # Parallelize: Foreman handoff and next judge's question generation overlap (~halves the gap)
                handoff_t = asyncio.create_task(self.foreman_say(
                    thread, team_key,
                    f"The team has finished answering {display}. Write ONE short warm handoff line thanking the team and inviting {nxt_display} to take the floor. Vary your wording — never repeat a previous handoff verbatim.",
                ))
                next_gen_task = asyncio.create_task(self._juror_generate(nxt_jid, nxt_agent, team_number, team_key))
                await handoff_t
                next_gen = next_gen_task

        # 4. Summary + time
        await self.foreman_say(
            thread, team_key,
            "All three judges have questioned the team. Write a 2-3 sentence summary of what the bench heard (no scores), then thank the team and tell them they may step out while the court deliberates.",
        )
        answers_path = self.out / "answers" / f"team_{team_number:02d}.txt"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text("\n".join(self.answers.get(team_number, [])) + "\n")
        if participant_id is not None:
            await self.t.remove_participant(thread, participant_id)

        # 5. Deterministic deliberation + verdict artifacts
        await self._deliberate(thread, team_number)
        verdict_path = self.out / "foreman" / f"case_{team_number:02d}_verdict.md"
        mirror_path = self.out / "foreman" / f"case_{team_number:02d}_mirror.md"
        if verdict_path.exists():
            await self.t.post_to_thread(thread, "foreman", verdict_path.read_text().strip())
        if mirror_path.exists():
            await self.t.post("foreman", "live_feed", mirror_path.read_text().strip())
        await self.foreman_say(thread, team_key, f"Case T{team_number:02d} is sealed. Write ONE short ceremonial close line.")

    # ---------- deterministic plumbing (unchanged from runbook) ----------
    async def _score_background(self, team_number: int) -> dict | None:
        cmd = [sys.executable, "-m", "judging.service", "summon", "--intake", self.config.intake,
               "--team", str(team_number), "--out", str(self.out)]
        if self.mock:
            cmd += ["--mock", "--skip-network"]
        try:
            r = await asyncio.to_thread(subprocess.run, cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            await self._escalate(f"team {team_number}: scoring timed out")
            return None
        if r.returncode != 0:
            await self._escalate(f"team {team_number}: scoring failed")
            return None
        p = self.out / "judging.json"
        if not p.exists():
            return None
        entries = json.loads(p.read_text())
        return next((e for e in entries if e.get("team_number") == team_number), None)

    async def _deliberate(self, thread, team_number: int) -> None:
        cmd = [sys.executable, "-m", "judging.service", "deliberate", "--team", str(team_number),
               "--answers", str(self.out / "answers" / f"team_{team_number:02d}.txt"), "--out", str(self.out)]
        r = await asyncio.to_thread(subprocess.run, cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
        # Post each judge's deliberation statement to the thread (the visible courtroom discussion)
        delib_path = self.out / "foreman" / f"case_{team_number:02d}_deliberation.json"
        if r.returncode == 0 and delib_path.exists():
            display = {"juror_one": "The Builder", "juror_two": "The Skeptic", "juror_three": "The Futurist"}
            for doc in json.loads(delib_path.read_text()):
                jid = doc.get("judge")
                stmt = (doc.get("statement") or "").strip()
                if jid in display and stmt:
                    await self.t.post_to_thread(thread, jid, stmt)
                    await asyncio.sleep(1)

    async def _escalate(self, message: str) -> None:
        await self.t.post("foreman", "ops", f"⚠️ {message} — @Shuen Rui")
