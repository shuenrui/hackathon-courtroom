import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..foreman import JUROR_DISPLAY, strip_scores
from ..voice import ForemanVoice

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TeamResolver:
    """Resolve a ping to a team number: explicit 'Team N' or a known team name from intake."""

    def __init__(self, config):
        self._by_name: dict[str, int] = {}
        self._by_number: dict[int, str] = {}
        self._config = config
        self._load()

    def _load(self) -> None:
        from ..blackboard import Blackboard, SheetsBlackboard

        self._by_name = {}
        self._by_number = {}
        if self._config.intake == "sheet":
            cfg = json.loads((REPO_ROOT / "config.json").read_text())["sheets"]
            board = SheetsBlackboard(cfg["credentials_path"], cfg["spreadsheet_id"])
            rows = board.load_intake()
        else:
            board = Blackboard()
            rows = board.load_intake(self._config.intake)
        for row in board.dedupe_first(rows):
            num = row.get("team_number")
            if num is None:
                continue
            name = str(row.get("team_name") or "").strip()
            self._by_number[num] = name
            if name:
                self._by_name[name.lower()] = num

    def __len__(self) -> int:
        return len(self._by_number)

    def resolve(self, text: str) -> int | None:
        """Resolve a ping to a team number. Refreshes from the sheet on a miss so
        teams that submitted after startup are picked up on their first ping."""
        num = self._resolve_cached(text)
        if num is None:
            try:
                self._load()
            except Exception as exc:
                print(f"resolver refresh failed: {exc.__class__.__name__}", flush=True)
            num = self._resolve_cached(text)
        return num

    def _resolve_cached(self, text: str) -> int | None:
        match = re.search(r"\bteam\s*#?\s*(\d+)\b", text, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            if num in self._by_number:
                return num
        lower = text.lower()
        best_name, best_num = "", None
        for name, num in self._by_name.items():
            if name in lower and len(name) > len(best_name):
                best_name, best_num = name, num
        return best_num

    def label(self, team_number: int) -> str:
        name = self._by_number.get(team_number, "")
        return f"Team {team_number} — {name}" if name else f"Team {team_number}"


class CaseFlow:
    """One case, start to finish: ping → thread → jury → Q&A clock → kick → verdict → mirror → reflect."""

    def __init__(self, transport, config, out_dir: str = "out", mock: bool = False, resolver=None):
        self.transport = transport
        self.config = config
        self.mock = mock
        self.resolver = resolver
        self.out_dir = Path(out_dir)
        self.state_path = self.out_dir / "discord_state.json"
        self.state = self._load_state()
        self.answers: dict[int, list[str]] = {}
        self.clock_tasks: dict[int, asyncio.Task] = {}
        self.deadlines: dict[int, float] = {}
        self.voice = self._load_voice()

    @staticmethod
    def _load_voice() -> ForemanVoice:
        try:
            cfg = json.loads((REPO_ROOT / "config.json").read_text()).get("foreman_voice")
        except Exception:
            cfg = None
        return ForemanVoice(cfg)

    async def _voiced(self, event: str, template: str, context: str) -> str:
        """Ask the Hermes Foreman for a line; fall back to the template. Never blocks
        the case flow longer than max_wait_sec and never leaks a score."""
        if not self.voice.enabled:
            return template
        try:
            voiced = await asyncio.wait_for(
                asyncio.to_thread(self.voice.speak, event, context),
                timeout=self.voice.max_wait_sec,
            )
        except asyncio.TimeoutError:
            print(f"foreman voice: {event} over max_wait — using template", flush=True)
            return template
        except Exception as exc:
            print(f"foreman voice: {event} error ({exc.__class__.__name__}) — using template", flush=True)
            return template
        return voiced or template

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"completed": [], "active": []}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def is_locked(self, team_number: int) -> bool:
        return team_number in self.state["completed"] or team_number in self.state["active"]

    def _label(self, team_number: int) -> str:
        if self.resolver is not None:
            return self.resolver.label(team_number)
        return f"Team {team_number}"

    def record_answer(self, team_number: int, author: str, text: str) -> None:
        if team_number in self.answers:
            self.answers[team_number].append(f"{author}: {text}")

    async def handle_ping(self, team_number: int, participant_name: str, participant_id=None) -> None:
        if self.is_locked(team_number):
            await self.transport.post(
                "foreman", "submissions",
                f"{self._label(team_number)} — your slot is already locked (single submission). "
                "The first entry stands; resubmissions are ignored.",
            )
            return

        self.state["active"].append(team_number)
        self._save_state()
        self.answers[team_number] = []

        handle = await self.transport.create_case_thread(team_number)
        if participant_id is not None:
            await self.transport.add_participant(handle, participant_id)

        open_line = await self._voiced(
            "case_open",
            f"Welcome to the bench, {self._label(team_number)} — {participant_name}! You have 10 minutes. "
            "I'm The Foreman, with me are three AI judges: The Builder (checks if your demo actually works), "
            "The Skeptic (checks if your problem is real and viable), and The Futurist (checks if your agent really improvises). "
            "Rules: Reply in this thread to the bot that asked you, answer as much as you can, it's okay to say 'not built yet.' "
            "The shared clock starts at the first question and freezes at 10:00. Now, The Builder will start.",
            f"team '{self._label(team_number)}', case T{team_number:02d}, participant {participant_name}, thread just opened, jury summoned, "
            "10-minute shared clock, judges: Builder (completeness), Skeptic (problem fit/viability), Futurist (agent mastery/novelty), "
            "rules: reply in thread to the bot that asked, answer as much as you can, clock starts at first question",
        )
        await self.transport.post_to_thread(handle, "foreman", open_line)
        feed_line = await self._voiced(
            "live_feed_case",
            f"A new case is called — {self._label(team_number)} steps before the bench. The jury is reading.",
            f"new case called: {self._label(team_number)}",
        )
        await self.transport.post("foreman", "live_feed", feed_line)

        entry = await self._run_jury(team_number, handle)
        if entry is None:
            self.state["active"].remove(team_number)
            self._save_state()
            return

        await self._post_jury_output(handle, team_number, entry)
        await self._run_qna_clock(handle, team_number, participant_id)
        await self._close_case(handle, team_number)

    async def _run_jury(self, team_number: int, handle) -> dict | None:
        await self.transport.post_to_thread(
            handle, "foreman", "The panel is reading the submission — blind marking in progress."
        )
        intake = self.config.intake
        cmd = [
            sys.executable, "-m", "judging.service", "summon",
            "--intake", intake, "--team", str(team_number),
            "--out", str(self.out_dir),
        ]
        if self.mock:
            cmd += ["--mock", "--skip-network"]
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            await self._escalate(f"team {team_number}: judging service timed out (15 min)")
            return None
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
            await self._escalate(f"team {team_number}: judging service failed — {' | '.join(tail)}")
            return None

        judging_path = self.out_dir / "judging.json"
        if not judging_path.exists():
            await self._escalate(f"team {team_number}: no judging output produced")
            return None
        entries = json.loads(judging_path.read_text())
        entry = next((e for e in entries if e.get("team_number") == team_number), None)
        if entry is None:
            await self._escalate(f"team {team_number}: missing from judging output")
        return entry

    async def _post_jury_output(self, handle, team_number: int, entry: dict) -> None:
        # Sequential: one judge at a time, not a bombardment. Foreman introduces each judge,
        # team answers, Foreman checks for follow-up before moving to next judge, then summary.
        juror_order = ["juror_one", "juror_two", "juror_three"]
        for idx, judge in enumerate(juror_order):
            deadline = self.deadlines.get(team_number)
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                break
            # For judges after the first, wait for team's reply to previous judge before introducing next judge
            # The "Thanks, Team. Next judge is ..." handoff comes *after* the team has replied to the previous judge
            if idx > 0:
                # This handoff was already posted at the end of previous iteration's wait, so for idx>0 we just post the next judge's questions
                # The "Thanks, Team" for this judge was posted after previous judge's answer - no need to post again here
                pass
            doc = next((d for d in entry.get("blind_scores", []) if d.get("judge") == judge), None)
            if doc is None or judge not in JUROR_DISPLAY:
                continue
            # For the first judge, the 10-minute intro has already been posted; now post this judge's questions.
            # For subsequent judges, the "Thanks" handoff will be posted at the *end* of previous judge's wait (see below)
            review = strip_scores((doc.get("review") or "").strip())
            if review:
                await self.transport.post_to_thread(handle, judge, f"**{JUROR_DISPLAY[judge]} — opening read:**\n{review}")
            questions = [strip_scores(q.strip()) for q in (doc.get("questions") or []) if q.strip()][:3]
            if questions:
                numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
                await self.transport.post_to_thread(
                    handle, judge, f"**Questions for {self._label(team_number)} from {JUROR_DISPLAY[judge]}:**\n{numbered}"
                )
                if team_number not in self.deadlines:
                    self.deadlines[team_number] = asyncio.get_running_loop().time() + self.config.qna_minutes * 60
            # Foreman hands the floor for this judge's questions (only for first judge, subsequent handoffs are after previous answer)
            if idx == 0:
                floor_intro = await self._voiced(
                    "floor_yours",
                    f"{self._label(team_number)} — the floor is yours for {JUROR_DISPLAY[judge]}'s questions. "
                    f"Reply to {JUROR_DISPLAY[judge]} in this thread. You have {self.config.qna_minutes} minutes total for all three judges — answer as much as you can.",
                    f"{self._label(team_number)}, {JUROR_DISPLAY[judge]} questions posted, floor yours for this judge, {self.config.qna_minutes}-min total",
                )
                await self.transport.post_to_thread(handle, "foreman", floor_intro)
            # Wait for participant reply before moving to next judge - with 2-min reminder
            # For dry-run (qna_minutes <1, compressed 0.1 min = 6s), use short waits so test stays fast
            is_dry = self.config.qna_minutes < 1
            wait_before_next = 12 if not is_dry else 1.5
            reminder_after = 120 if not is_dry else 2  # 2 minutes real, 2 seconds dry
            before_len = len(self.answers.get(team_number, []))
            # Flexible follow-up: wait for team reply, and if they ask this judge a direct question, let the judge reply (conversational, not fixed)
            # In dry-run, answers are simulated at the end, so just use a fixed short pause and skip reminder
            if is_dry:
                await asyncio.sleep(wait_before_next)
            else:
                elapsed = 0
                reminder_sent = False
                # Keep a snapshot of answers to detect new ones that mention this judge
                last_seen = before_len
                while elapsed < wait_before_next:
                    deadline = self.deadlines.get(team_number)
                    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(1)
                    elapsed += 1
                    cur_len = len(self.answers.get(team_number, []))
                    if cur_len > last_seen:
                        # New answer(s) arrived - check if any mention this judge (flexible reply)
                        new_msgs = self.answers[team_number][last_seen:cur_len]
                        last_seen = cur_len
                        # Detect if team asked this judge directly (name mention or question to this judge)
                        judge_names = [JUROR_DISPLAY[judge].lower(), judge.replace("_"," "), "builder" if judge=="juror_one" else "skeptic" if judge=="juror_two" else "futurist"]
                        asked_this_judge = any(any(n in msg.lower() for n in judge_names) and ("?" in msg or "what" in msg.lower() or "how" in msg.lower()) for msg in new_msgs)
                        if asked_this_judge:
                            # Let this judge reply conversationally to the team's follow-up (Qwen follow-up if live, template if mock/timeout)
                            follow_q = new_msgs[-1].split(":",1)[-1].strip()[:400]
                            reply = await self._judge_followup(judge, team_number, follow_q)
                            if reply:
                                await self.transport.post_to_thread(handle, judge, reply)
                                # Give team a beat to read the reply before Foreman moves on
                                await asyncio.sleep(1)
                                # Reset timer so team can reply to the follow-up
                                elapsed = 0
                                before_len = cur_len
                                continue
                        # Regular answer (not a direct question to this judge) - brief beat then continue to check
                        await asyncio.sleep(1)
                        break
                    if not reminder_sent and elapsed >= reminder_after and cur_len == before_len:
                        next_judge = JUROR_DISPLAY[juror_order[idx + 1]] if idx + 1 < len(juror_order) else "the panel"
                        nudge = await self._voiced(
                            "follow_up_check",
                            f"Hey, hello — Team {team_number}, are you there? Please reply to {JUROR_DISPLAY[judge]} before we move on to {next_judge} — we have a few more questions to go and the clock is running. Even a short 'not built yet' helps.",
                            f"nudge team {team_number} to answer {JUROR_DISPLAY[judge]} before {next_judge}, {elapsed}s silent",
                        )
                        await self.transport.post_to_thread(handle, "foreman", nudge)
                        reminder_sent = True
            deadline = self.deadlines.get(team_number)
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                break
            # Check if this judge has a follow-up before moving on
            follow_line = await self._voiced(
                "follow_up_check",
                f"{JUROR_DISPLAY[judge]}, any follow-up on what you just asked before we move to the next judge?",
                f"check {JUROR_DISPLAY[judge]} for follow-up on team {team_number}",
            )
            await self.transport.post_to_thread(handle, "foreman", follow_line)
            await asyncio.sleep(0.5 if is_dry else 3)
            # Handoff to next judge comes *after* the team has had a chance to reply to this judge
            if idx + 1 < len(juror_order):
                next_judge = juror_order[idx + 1]
                handoff = await self._voiced(
                    "follow_up_check",
                    f"Thanks, Team — {JUROR_DISPLAY[next_judge]} is next. Take a breath, then share your next answer in this thread when you're ready.",
                    f"handoff to {JUROR_DISPLAY[next_judge]} after {JUROR_DISPLAY[judge]} for {self._label(team_number)}",
                )
                await self.transport.post_to_thread(handle, "foreman", handoff)
                # Give a brief beat before the next judge's questions appear
                await asyncio.sleep(0.5 if is_dry else 1)

        dropped = entry.get("dropped_judges") or {}
        if dropped:
            await self._escalate(f"team {team_number}: dropped judges — {dropped}")

        deadline = self.deadlines.get(team_number)
        if deadline is None or asyncio.get_running_loop().time() < deadline:
            await self._post_jury_summary(handle, team_number)

    async def _judge_followup(self, judge: str, team_number: int, team_question: str) -> str | None:
        """Let a specific judge reply conversationally to a team's direct follow-up question. Uses Qwen if live, mock template if --mock or on error."""
        if self.mock:
            # Mock follow-up: conversational, not fixed
            persona = JUROR_DISPLAY.get(judge, judge)
            return f"{persona} here — good catch. On '{team_question[:80]}...', my take: that's the gap I was probing - tell me what you actually did on that edge, not what you plan to. One sentence on what happened when you hit it?"
        try:
            # Live follow-up via Qwen: construct a focused prompt for this juror
            import json as _json
            from pathlib import Path as _Path
            from ..qwen_client import QwenClient
            cfg = _json.loads((_Path(__file__).resolve().parent.parent.parent / "config.json").read_text())["qwen"]
            client = QwenClient.from_config(cfg, timebox_sec=30)
            system = _Path(f"prompts/{judge}.md").read_text() if _Path(f"prompts/{judge}.md").exists() else f"You are {judge}."
            # Keep it conversational and short, as per new Team-facing voice
            system += "\n\nFollow-up instruction: The team just asked you directly. Reply conversationally in 1-2 sentences, rational and relevant to *this* team's bundle, no scores, no generic encouragement. Answer their question directly and point at the evidence."
            user = _json.dumps({"team_number": team_number, "team_question": team_question, "follow_up": True}, ensure_ascii=False)
            raw = await asyncio.to_thread(client.complete, system, user)
            # Try to extract a conversational reply - if Qwen returns JSON, pull review/questions, else use raw text
            try:
                data = _json.loads(raw)
                # Prefer review + questions if present, else use raw
                if isinstance(data, dict) and "review" in data:
                    return data["review"][:800]
                if isinstance(data, dict) and "questions" in data and data["questions"]:
                    return str(data["questions"][0])[:800]
            except _json.JSONDecodeError:
                pass
            return raw.strip()[:800] if raw.strip() else None
        except Exception as exc:
            print(f"follow-up for {judge} failed ({exc.__class__.__name__}) — using template", flush=True)
            return None

    async def _post_jury_summary(self, handle, team_number: int) -> None:
        summary_line = await self._voiced(
            "summary",
            f"Summarize what the bench heard from {self._label(team_number)} across Builder, Skeptic, Futurist and the team's answers — 2-3 sentences, warm, procedural, no scores, note what was clarified.",
            f"summary of {self._label(team_number)} hearing: Builder/Skeptic/Futurist plus answers",
        )
        await self.transport.post_to_thread(handle, "foreman", summary_line)

    async def _run_qna_clock(self, handle, team_number: int, participant_id) -> None:
        total_sec = self.config.qna_minutes * 60
        marks = sorted(set(self.config.countdown_marks_sec), reverse=True)
        loop = asyncio.get_running_loop()
        deadline = self.deadlines.get(team_number, loop.time() + total_sec)
        announced: set[int] = set()
        while loop.time() < deadline:
            await asyncio.sleep(min(1, deadline - loop.time()))
            remaining = max(0, int(round(deadline - loop.time())))
            if remaining in marks and remaining not in announced:
                announced.add(remaining)
                mm, ss = divmod(int(remaining), 60)
                label = f"{mm}:{ss:02d}" if mm else f"{ss} seconds"
                await self.transport.post_to_thread(
                    handle, "foreman", f"Clock check — {label} remaining."
                )

        if not self.answers[team_number] and hasattr(self.transport, "answers_seen"):
            self.answers[team_number] = self.transport.answers_seen(handle)

        answers_path = self.out_dir / "answers" / f"team_{team_number:02d}.txt"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text("\n".join(self.answers[team_number]) + "\n")

        time_line = await self._voiced(
            "time_called",
            f"**Time.** The Q&A phase for {self._label(team_number)} is frozen; answers are logged. "
            "The participant leaves the room — this thread is now the courtroom.",
            f"{self._label(team_number)}, Q&A clock hit zero, phase frozen, participant leaves, thread becomes courtroom",
        )
        await self.transport.post_to_thread(handle, "foreman", time_line)
        if participant_id is not None:
            await self.transport.remove_participant(handle, participant_id)
        self.deadlines.pop(team_number, None)

    async def _close_case(self, handle, team_number: int) -> None:
        await self._run_deliberation(handle, team_number)

        verdict_path = self.out_dir / "foreman" / f"case_{team_number:02d}_verdict.md"
        mirror_path = self.out_dir / "foreman" / f"case_{team_number:02d}_mirror.md"

        if verdict_path.exists():
            await self.transport.post_to_thread(handle, "foreman", verdict_path.read_text().strip())
        if mirror_path.exists():
            await self.transport.post("foreman", "live_feed", mirror_path.read_text().strip())

        reflect = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable, "-m", "judging.service", "reflect",
                "--team", str(team_number),
                "--answers", str(self.out_dir / "answers" / f"team_{team_number:02d}.txt"),
                "--out", str(self.out_dir),
            ] + (["--mock"] if self.mock else []),
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
        )
        if reflect.returncode != 0:
            await self._escalate(f"team {team_number}: reflection pass failed")

        self.state["active"].remove(team_number)
        self.state["completed"].append(team_number)
        self._save_state()
        seal_line = await self._voiced(
            "case_sealed",
            f"Case T{team_number:02d} closed and sealed. The bench moves on.",
            f"case T{team_number:02d} ({self._label(team_number)}) closed and sealed",
        )
        await self.transport.post_to_thread(handle, "foreman", seal_line)

    async def _run_deliberation(self, handle, team_number: int) -> None:
        delib_line = await self._voiced(
            "deliberation_open",
            "The participant has left. **The court deliberates.** All blind scores are now on the bench.",
            f"{self._label(team_number)}, participant has left, all blind scores on the bench, panel speaks",
        )
        await self.transport.post_to_thread(handle, "foreman", delib_line)
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable, "-m", "judging.service", "deliberate",
                "--team", str(team_number),
                "--answers", str(self.out_dir / "answers" / f"team_{team_number:02d}.txt"),
                "--out", str(self.out_dir),
            ] + (["--mock"] if self.mock else []),
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
        )
        delib_path = self.out_dir / "foreman" / f"case_{team_number:02d}_deliberation.json"
        if result.returncode != 0 or not delib_path.exists():
            await self._escalate(f"team {team_number}: deliberation pass failed")
            return
        for doc in json.loads(delib_path.read_text()):
            judge = doc.get("judge")
            statement = (doc.get("statement") or "").strip()
            if judge in JUROR_DISPLAY and statement:
                await self.transport.post_to_thread(
                    handle, judge, f"**{JUROR_DISPLAY[judge]}:** {statement}"
                )

    async def _escalate(self, message: str) -> None:
        await self.transport.post("foreman", "ops", f"⚠️ {message} — @Shuen Rui")

    async def heartbeat_loop(self) -> None:
        interval = self.config.heartbeat_minutes * 60
        while True:
            stamp = datetime.now().strftime("%H:%M")
            active = self.state.get("active", [])
            status = f"heartbeat {stamp} — foreman up, judges up"
            if active:
                status += f", cases in flight: {active}"
            await self.transport.post("foreman", "bot_health", status)
            await asyncio.sleep(interval)
