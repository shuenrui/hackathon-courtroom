import hashlib
import json
from pathlib import Path


def row_hash(row: dict) -> str:
    canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class RunState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = {"teams": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self.data = {"teams": {}}

    def needs_scoring(self, row: dict) -> bool:
        key = str(row.get("team_number"))
        record = self.data["teams"].get(key)
        if record is None:
            return True
        return record.get("row_hash") != row_hash(row)

    def mark_scored(self, row: dict) -> None:
        key = str(row.get("team_number"))
        self.data["teams"][key] = {"row_hash": row_hash(row)}

    def previous_results(self) -> list[dict]:
        return self.data.get("previous_results", [])

    def save(self, results: list[dict]) -> None:
        self.data["previous_results"] = results
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
