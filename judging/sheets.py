class SheetsNotProvisioned(Exception):
    pass


class SheetsBlackboard:
    TAB_INTAKE = "Intake"
    TAB_JUDGING = "Judging"
    TAB_SHORTLIST = "Shortlist"

    def __init__(self, credentials_path: str, spreadsheet_id: str):
        try:
            import gspread
        except ImportError as exc:
            raise SheetsNotProvisioned(
                "gspread not installed — run: pip install gspread. "
                "Then share the spreadsheet with the service account."
            ) from exc

        if not credentials_path or not spreadsheet_id:
            raise SheetsNotProvisioned(
                "Sheets backend not provisioned: config needs sheets.credentials_path "
                "(service-account JSON) and sheets.spreadsheet_id. Tab layout: specs/sheet-spec.md"
            )

        self._client = gspread.service_account(filename=credentials_path)
        self._sheet = self._client.open_by_key(spreadsheet_id)

    def read_intake(self) -> list[dict]:
        worksheet = self._sheet.worksheet(self.TAB_INTAKE)
        return worksheet.get_all_records()

    def write_judging(self, rows: list[dict]) -> None:
        self._write_tab(self.TAB_JUDGING, rows)

    def write_shortlist(self, rows: list[dict]) -> None:
        self._write_tab(self.TAB_SHORTLIST, rows)

    def _write_tab(self, tab: str, rows: list[dict]) -> None:
        if not rows:
            return
        worksheet = self._sheet.worksheet(tab)
        headers = list(rows[0].keys())
        values = [headers] + [[row.get(h, "") for h in headers] for row in rows]
        worksheet.clear()
        worksheet.update(values=values, range_name=f"A1")

    def append_note(self, tab: str, row: dict) -> None:
        worksheet = self._sheet.worksheet(tab)
        worksheet.append_row(list(row.values()))
