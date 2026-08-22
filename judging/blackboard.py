import csv
import json
from pathlib import Path

from .foreman import strip_scores


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
    """Google Sheets blackboard via service account (gspread).

    Reads intake from the Form responses tab; writes the Judging and Shortlist tabs.
    Provisioning: `gspread` installed, service-account JSON on disk (never committed),
    the spreadsheet shared as editor with the service account email, and
    `sheets.credentials_path` + `sheets.spreadsheet_id` filled in config.json.
    Tab layout: specs/sheet-spec.md.
    """

    # Ordered substring rules matched against the lowercased header. Real Form titles
    # carry suffixes ("Problem Statement (Max 150 words)", "Demo Video (Youtube/...)"),
    # so we match on the distinctive core rather than exact titles. More specific first.
    FIELD_RULES = [
        ("video transcript", "video_transcript"),
        ("problem statement", "problem_statement"),
        ("demo video", "demo_video_url"),
        ("project url", "project_url"),
        ("project title", "project_title"),
        ("team name", "team_name"),
        ("team number", "team_number_raw"),
        ("team no", "team_number_raw"),
        ("github", "github_repo"),
        ("email", "captain_contact"),
        ("phone", "captain_phone"),
        ("track", "track"),
        ("solution", "solution"),
        ("timestamp", "submitted_at"),
    ]

    TAB_JUDGING = "Judging Sheet"
    TAB_SHORTLIST = "Shortlist"

    @classmethod
    def _match_field(cls, header) -> str | None:
        h = str(header).strip().lower()
        for needle, field in cls.FIELD_RULES:
            if needle in h:
                return field
        return None

    @staticmethod
    def _identity_key(row: dict) -> str:
        """Dedupe identity: an explicit team number if the form has one, else the team name."""
        raw = str(row.get("team_number_raw") or "").strip()
        if raw:
            return f"num:{raw.lower()}"
        return f"name:{str(row.get('team_name') or '').strip().lower()}"

    def __init__(
        self,
        credentials_path: str,
        spreadsheet_id: str,
        tab_name: str = "Form responses 1",
    ):
        try:
            import gspread
        except ImportError as exc:
            raise NotImplementedError("gspread not installed — run: pip install gspread") from exc
        if not credentials_path or not spreadsheet_id:
            raise NotImplementedError(
                "Sheets provisioning incomplete: set sheets.credentials_path and "
                "sheets.spreadsheet_id in config.json, and share the sheet with the "
                "service account email as editor."
            )
        self._client = gspread.service_account(filename=credentials_path)
        self._sheet = self._client.open_by_key(spreadsheet_id)
        self._tab_name = tab_name

    def _find_worksheet(self):
        target = self._tab_name.strip().lower()
        for ws in self._sheet.worksheets():
            if ws.title.strip().lower() == target:
                return ws
        return self._sheet.worksheet(self._tab_name)

    def load_intake(self, path: str | None = None) -> list[dict]:
        """Raw mapped rows, one per form response, in sheet order (chronological)."""
        records = self._find_worksheet().get_all_records()
        intake = []
        for record in records:
            mapped = {}
            for header, value in record.items():
                field = self._match_field(header)
                if field and value is not None and str(value).strip() != "":
                    mapped[field] = str(value).strip()
            if mapped.get("team_name") or mapped.get("team_number_raw"):
                intake.append(mapped)
        return intake

    def dedupe_first(self, rows: list[dict]) -> list[dict]:
        """Single submission policy keyed on team identity (team number if present, else
        team name). Sheet order is chronological, so first occurrence = first submission.
        Assigns a stable sequential team_number (1..N) in first-appearance order."""
        first: dict[str, dict] = {}
        order: list[str] = []
        for row in rows:
            key = self._identity_key(row)
            if key in ("num:", "name:") or key in first:
                continue
            order.append(key)
            first[key] = dict(row)
        results = []
        for i, key in enumerate(order, 1):
            row = first[key]
            row["team_number"] = i
            results.append(row)
        return results

    def ignored_resubmissions(self, rows: list[dict]) -> dict[str, int]:
        """Team identities that submitted more than once -> how many entries were dropped."""
        counts: dict[str, int] = {}
        seen: set[str] = set()
        for row in rows:
            key = self._identity_key(row)
            if key in ("num:", "name:"):
                continue
            if key in seen:
                counts[key] = counts.get(key, 0) + 1
            else:
                seen.add(key)
        return counts

    # --- write-back (service is the sole writer of these tabs) ---

    def write_judging(self, results: list[dict], path) -> None:
        super().write_judging(results, path)
        self._sync_tab(self.TAB_JUDGING, [self._judging_row(e) for e in results])

    def write_shortlist(self, shortlist: dict, path) -> None:
        super().write_shortlist(shortlist, path)
        rows = []
        for group, marker in (("shortlist", "shortlisted"), ("alternates", "alternate")):
            for e in shortlist.get(group, []):
                row = self._shortlist_row(e)
                row["status"] = marker
                rows.append(row)
        self._sync_tab(self.TAB_SHORTLIST, rows)

    @staticmethod
    def _judging_row(entry: dict) -> dict:
        averages = entry.get("averages", {})
        smoke = entry.get("url_smoke", {})
        juror_totals = {doc.get("judge"): doc.get("total") for doc in entry.get("blind_scores", [])}
        juror_comments = {
            doc.get("judge"): strip_scores((doc.get("review") or "").strip())
            for doc in entry.get("blind_scores", [])
        }
        questions = []
        for doc in entry.get("blind_scores", []):
            questions.extend(strip_scores(q.strip()) for q in (doc.get("questions") or []) if q.strip())
        return {
            "team_number": entry.get("team_number"),
            "team_name": entry.get("team_name", ""),
            "submitted_at": entry.get("submitted_at", ""),
            "project_url": entry.get("project_url", ""),
            "github_repo": entry.get("github_repo", ""),
            "demo_video_url": entry.get("demo_video_url", ""),
            "url_reachable": smoke.get("reachable"),
            "url_status": smoke.get("status_code", ""),
            "url_flags": ", ".join(smoke.get("flags", [])),
            "juror_one_total": juror_totals.get("juror_one", ""),
            "juror_two_total": juror_totals.get("juror_two", ""),
            "juror_three_total": juror_totals.get("juror_three", ""),
            "avg_completeness": averages.get("completeness", ""),
            "avg_agent_mastery": averages.get("agent_mastery", ""),
            "avg_problem_fit": averages.get("problem_fit", ""),
            "avg_solution_quality": averages.get("solution_quality", ""),
            "avg_novelty": averages.get("novelty", ""),
            "avg_total": averages.get("total", ""),
            "spread": entry.get("spread", ""),
            "contested": "yes" if entry.get("contested") else "",
            "rank": entry.get("rank", ""),
            "status": entry.get("status", ""),
            "flags": ", ".join(entry.get("flags", [])),
            "juror_one_comment": juror_comments.get("juror_one", ""),
            "juror_two_comment": juror_comments.get("juror_two", ""),
            "juror_three_comment": juror_comments.get("juror_three", ""),
            "questions_asked": " | ".join(questions),
            "deliberation_note": "",
        }

    @staticmethod
    def _shortlist_row(entry: dict) -> dict:
        return {
            "rank": entry.get("rank", ""),
            "team_number": entry.get("team_number"),
            "avg_total": entry.get("averages", {}).get("total", ""),
            "contested": "yes" if entry.get("contested") else "",
            "flags": ", ".join(entry.get("flags", [])),
            "spot_check": "",
            "override_reason": "",
        }

    def _sync_tab(self, tab_name: str, rows: list[dict]) -> None:
        """Clear + rewrite a service-owned tab. Best effort: a Sheets hiccup must not kill the run."""
        if not rows:
            return
        try:
            try:
                worksheet = self._sheet.worksheet(tab_name)
            except Exception:
                worksheet = self._sheet.add_worksheet(title=tab_name, rows=len(rows) + 1, cols=len(rows[0]))
            headers = list(rows[0].keys())
            values = [headers] + [[row.get(h, "") for h in headers] for row in rows]
            worksheet.clear()
            worksheet.update(values=values)
        except Exception as exc:
            print(f"warning: sheet tab '{tab_name}' sync failed ({exc.__class__.__name__}); local outputs unaffected", flush=True)
