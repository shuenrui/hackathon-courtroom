import json
from pathlib import Path

JUDGE_DISPLAY = {
    "juror_one": "The Builder",
    "juror_two": "The Skeptic",
    "juror_three": "The Futurist",
    "foreman": "The Foreman (meta)",
}


class ReflectionStore:
    """Knowledge ledger: reflections in (append-only JSON), distilled lessons out.

    files:
      knowledge/reflections/case_NN.md   human-readable record per case
      knowledge/reflections.json         machine ledger (this is what distillation reads)
      knowledge/lessons.md               capped, injected-into-prompts block
    """

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.refs_dir = self.base / "reflections"
        self.ledger_path = self.base / "reflections.json"
        self.lessons_path = self.base / "lessons.md"

    def _load_ledger(self) -> dict:
        if self.ledger_path.exists():
            try:
                return json.loads(self.ledger_path.read_text())
            except json.JSONDecodeError:
                pass
        return {"cases": {}}

    def add_case(self, team_number: int, reflections: list[dict]) -> None:
        ledger = self._load_ledger()
        case_key = f"{int(team_number):02d}"
        ledger["cases"][case_key] = {
            "team_number": int(team_number),
            "reflections": reflections,
        }
        self.base.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
        self._write_case_md(team_number, reflections)
        self.rebuild_lessons(ledger)

    def _write_case_md(self, team_number: int, reflections: list[dict]) -> None:
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# Case {team_number:02d} — Team {team_number}", ""]
        for ref in reflections:
            judge = ref.get("judge", "unknown")
            lines.append(f"## {JUDGE_DISPLAY.get(judge, judge)}")
            for note in ref.get("reflection", []):
                lines.append(f"- {note}")
            lines.append("")
        (self.refs_dir / f"case_{int(team_number):02d}.md").write_text("\n".join(lines))

    def rebuild_lessons(self, ledger: dict, capacity_per_lens: int = 4) -> str:
        """Deterministic v1 distillation: most recent reflections per lens, capped.

        Model-driven distillation is a later upgrade; this keeps prompts bounded
        and the process auditable today.
        """
        per_lens: dict[str, list[tuple[int, str]]] = {}
        for case_key in sorted(ledger.get("cases", {})):
            case = ledger["cases"][case_key]
            case_no = case.get("team_number", int(case_key))
            for ref in case.get("reflections", []):
                judge = ref.get("judge")
                if judge is None:
                    continue
                for note in ref.get("reflection", []):
                    per_lens.setdefault(judge, []).append((case_no, note))

        if not per_lens:
            self.lessons_path.write_text("")
            return ""

        lines = [
            "LESSONS LEARNED SO FAR — distilled from earlier cases. Use them to sharpen",
            "what you look for and what you ask. They never change the rubric anchors,",
            "and they never justify scoring outside the evidence bundle of THIS case.",
            "",
        ]
        for judge in ("juror_one", "juror_two", "juror_three", "foreman"):
            entries = per_lens.get(judge, [])
            if not entries:
                continue
            recent = entries[-capacity_per_lens:]
            lines.append(f"From {JUDGE_DISPLAY[judge]}:")
            for case_no, note in recent:
                lines.append(f"- (case {case_no:02d}) {note}")
            lines.append("")
        block = "\n".join(lines).rstrip() + "\n"
        self.lessons_path.write_text(block)
        return block

    def load_lessons(self) -> str:
        if self.lessons_path.exists():
            return self.lessons_path.read_text()
        ledger = self._load_ledger()
        if ledger.get("cases"):
            return self.rebuild_lessons(ledger)
        return ""
