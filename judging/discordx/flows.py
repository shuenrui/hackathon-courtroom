import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..foreman import JUROR_DISPLAY, strip_scores

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class CaseFlow:
    """One case, start to finish: ping → thread → jury → Q&A clock → kick → verdict → mirror → reflect."""

    def __init__(self, transport, config, out_dir: str = "out", mock: bool = False):
        self.transport = transport
        self.config = config
        self.mock = mock
        self.out_dir = Path(out_dir)
        self.state_path = self.out_dir / "discord_state.json"
        self.state = self._load_state()
        self.answers: dict[int, list[str]] = {}
        self.clock_tasks: dict[int, asyncio.Task] = {}

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"completed": [], "active": []}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def is_locked(self, team_number: int) -> bool:
        return team_number in self.state["completed"] or team_number in self.state["active"]

    def record_answer(self, team_number: int, author: str, text: str) -> None:
        if team_number in self.answers:
            self.answers[team_number].append(f"{author}: {text}")

    async def handle_ping(self, team_number: int, participant_name: str, participant_id=None) -> None:
        if self.is_locked(team_number):
            await self.transport.post(
                "foreman", "submissions",
                f"Team {team_number} — your slot is already locked (single submission). "
                "The first entry stands; resubmissions are ignored.",
            )
            return

        self.state["active"].append(team_number)
        self._save_state()
        self.answers[team_number] = []

        handle = await self.transport.create_case_thread(team_number)
        if participant_id is not None:
            await self.transport.add_participant(handle, participant_id)

        await self.transport.post_to_thread(
            handle, "foreman",
            f"**Case T{team_number:02d} is open.** {participant_name}, the jury has been summoned. "
            "Reviews and questions land here shortly — when they do, your shared clock starts. "
            "Scores stay sealed throughout.",
        )
        await self.transport.post(
            "foreman", "live_feed",
            f"A new case is called — Team {team_number} steps before the bench. The jury is reading.",
        )

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
        for doc in entry.get("blind_scores", []):
            judge = doc.get("judge")
            if judge not in JUROR_DISPLAY:
                continue
            review = strip_scores((doc.get("review") or "").strip())
            if review:
                await self.transport.post_to_thread(handle, judge, f"**{JUROR_DISPLAY[judge]} — opening read:**\n{review}")
            questions = [strip_scores(q.strip()) for q in (doc.get("questions") or []) if q.strip()][:3]
            if questions:
                numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
                await self.transport.post_to_thread(
                    handle, judge, f"**Questions for Team {team_number}:**\n{numbered}"
                )

        dropped = entry.get("dropped_judges") or {}
        if dropped:
            await self._escalate(f"team {team_number}: dropped judges — {dropped}")

        await self.transport.post_to_thread(
            handle, "foreman",
            f"**Team {team_number} — the floor is yours.** The shared clock starts NOW: "
            f"{self.config.qna_minutes} minutes for answers and follow-ups, all in this thread. "
            "When it hits zero the phase freezes.",
        )

    async def _run_qna_clock(self, handle, team_number: int, participant_id) -> None:
        total_sec = self.config.qna_minutes * 60
        marks = sorted(set(self.config.countdown_marks_sec), reverse=True)
        elapsed = 0
        while elapsed < total_sec:
            step = 1
            next_mark = next((m for m in marks if total_sec - elapsed > m >= total_sec - elapsed - step), None)
            await asyncio.sleep(step)
            elapsed += step
            remaining = total_sec - elapsed
            if remaining in marks:
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

        await self.transport.post_to_thread(
            handle, "foreman",
            f"**Time.** The Q&A phase for Team {team_number} is frozen; answers are logged. "
            "The participant leaves the room — this thread is now the courtroom.",
        )
        if participant_id is not None:
            await self.transport.remove_participant(handle, participant_id)

    async def _close_case(self, handle, team_number: int) -> None:
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
        await self.transport.post_to_thread(
            handle, "foreman", f"Case T{team_number:02d} closed and sealed. The bench moves on."
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
