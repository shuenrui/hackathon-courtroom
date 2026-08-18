import csv
import json
from pathlib import Path


class Blackboard:
    def load_intake(self, path: str) -> list[dict]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"intake file not found: {path}")
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text())
            if not isinstance(data, list):
                raise ValueError("intake JSON must be a list of submission objects")
            return data
        if p.suffix.lower() == ".csv":
            with p.open(newline="", encoding="utf-8") as fh:
                return [dict(row) for row in csv.DictReader(fh)]
        raise ValueError(f"unsupported intake format: {p.suffix}")

    def dedupe_first(self, rows: list[dict]) -> list[dict]:
        """Single submission policy: keep the FIRST form response per team number.

        Later entries are dropped entirely — a team's first submission locks their slot.
        """
        first: dict = {}
        order: list = []
        for row in rows:
            key = row.get("team_number")
            if key is None:
                continue
            try:
                key = int(key)
            except (TypeError, ValueError):
                continue
            row = dict(row)
            row["team_number"] = key
            if key not in first:
                order.append(key)
                first[key] = row
        return [first[key] for key in order]

    def ignored_resubmissions(self, rows: list[dict]) -> dict[int, int]:
        """Team numbers that submitted more than once, mapped to how many entries were dropped."""
        counts: dict[int, int] = {}
        seen: set[int] = set()
        for row in rows:
            key = row.get("team_number")
            if key is None:
                continue
            try:
                key = int(key)
            except (TypeError, ValueError):
                continue
            if key in seen:
                counts[key] = counts.get(key, 0) + 1
            else:
                seen.add(key)
        return counts

    def write_judging(self, results: list[dict], path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(results, indent=2, ensure_ascii=False))

    def write_shortlist(self, shortlist: dict, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(shortlist, indent=2, ensure_ascii=False))

    def write_scorecards(self, markdown: str, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(markdown)

    def write_report(self, report: dict, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False))


class SheetsBlackboard(Blackboard):
    def __init__(self):
        raise NotImplementedError(
            "Sheets adapter pending provisioning: service-account JSON + spreadsheet id. "
            "Tabs spec: specs/sheet-spec.md. The Judging Service is the sole writer."
        )
