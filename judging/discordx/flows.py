import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..foreman import JUROR_DISPLAY, strip_scores

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

        await self.transport.post_to_thread(
            handle, "foreman",
            f"**Case T{team_number:02d} is open.** {participant_name}, the jury has been summoned. "
            "Reviews and questions land here shortly — when they do, your shared clock starts. "
            "Scores stay sealed throughout.",
        )
        await self.transport.post(
            "foreman", "live_feed",
            f"A new case is called — {self._label(team_number)} steps before the bench. The jury is reading.",
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
                    handle, judge, f"**Questions for {self._label(team_number)}:**\n{numbered}"
                )

        dropped = entry.get("dropped_judges") or {}
        if dropped:
            await self._escalate(f"team {team_number}: dropped judges — {dropped}")

        await self.transport.post_to_thread(
            handle, "foreman",
            f"**{self._label(team_number)} — the floor is yours.** The shared clock starts NOW: "
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
            f"**Time.** The Q&A phase for {self._label(team_number)} is frozen; answers are logged. "
            "The participant leaves the room — this thread is now the courtroom.",
        )
        if participant_id is not None:
            await self.transport.remove_participant(handle, participant_id)

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
        await self.transport.post_to_thread(
            handle, "foreman", f"Case T{team_number:02d} closed and sealed. The bench moves on."
        )

    async def _run_deliberation(self, handle, team_number: int) -> None:
        await self.transport.post_to_thread(
            handle, "foreman",
            "The participant has left. **The court deliberates.** All blind scores are now on the bench.",
        )
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
