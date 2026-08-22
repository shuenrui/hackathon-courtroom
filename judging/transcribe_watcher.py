"""Fill blank Form-response transcripts from short YouTube demos."""
import json
import os
import sys
import time
from pathlib import Path

from judging.transcribe import transcribe_youtube

REPO_ROOT = Path(__file__).resolve().parent.parent

def _post_submissions(text: str) -> bool:
    """Post a Foreman line to #submissions (best-effort, never kills the watcher)."""
    try:
        import requests
        from judging.discordx.config import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        cfg = json.loads((REPO_ROOT / "config.json").read_text())["discord"]
        token = os.environ.get("DISCORD_TOKEN_FOREMAN", "")
        if not token:
            return False
        response = requests.post(
            f"https://discord.com/api/v10/channels/{cfg['channels']['submissions']}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"content": text},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"discord post failed: {e}")
        return False

# Track which teams we've already nudged for this run
_nudged_wait = set()
_nudged_ready = set()
_nudged_failed = set()
_failures: dict[int, int] = {}
_retry_after: dict[int, float] = {}

def run_once():
    from judging.blackboard import SheetsBlackboard
    cfg = json.loads((REPO_ROOT / "config.json").read_text())["sheets"]
    credentials = Path(cfg["credentials_path"])
    if not credentials.is_absolute():
        credentials = REPO_ROOT / credentials
    b = SheetsBlackboard(str(credentials), cfg["spreadsheet_id"])
    ws = b._sheet.worksheet("Form responses 1")
    headers = ws.row_values(1)
    # Find video_transcript column (case-insensitive)
    vt_col = None
    for i, h in enumerate(headers, 1):
        if h.strip().lower() == "video transcript":
            vt_col = i
            break
    if vt_col is None:
        print("video_transcript column not found, headers:", headers)
        return
    # Find demo_video_url column
    dv_col = None
    for i, h in enumerate(headers, 1):
        if "demo video" in h.lower():
            dv_col = i
            break
    if dv_col is None:
        print("demo video column not found")
        return
    rows = ws.get_all_values()
    # rows[0] is header, rows[1:] are data
    for idx, row in enumerate(rows[1:], 2):  # 1-indexed rows, idx is sheet row number
        demo_url = row[dv_col-1] if len(row) >= dv_col else ""
        transcript = row[vt_col-1] if len(row) >= vt_col else ""
        team_name = row[2] if len(row) > 2 else f"row{idx}"
        # Discord handle for tagging (column B)
        discord_handle = row[1] if len(row) > 1 else ""
        retryable_failure = transcript.strip().startswith("(transcribe failed:")
        if demo_url and (not transcript.strip() or retryable_failure) and time.monotonic() >= _retry_after.get(idx, 0):
            if team_name not in _nudged_wait:
                tag = discord_handle if discord_handle else team_name
                if _post_submissions(f"{tag} — thanks for submitting! Your video is being transcribed in the background. You can start now without it, or wait for the ready message if you want the transcript included as evidence."):
                    _nudged_wait.add(team_name)
            print(f"Transcribing {team_name} ({demo_url}) at row {idx}...")
            try:
                text = transcribe_youtube(demo_url)
                if not text:
                    text = "(transcript empty - no speech detected)"
                # Truncate to fit Sheets cell (50k limit, but keep reasonable)
                text = text[:8000]
                ws.update_cell(idx, vt_col, text)
                _failures.pop(idx, None)
                _retry_after.pop(idx, None)
                print(f"  -> wrote {len(text)} chars to row {idx} col {vt_col}")
                if team_name not in _nudged_ready:
                    tag = discord_handle if discord_handle else team_name
                    if _post_submissions(f"{tag} — your video is transcribed and your bundle is ready. Mention Vegapunk with your team name when you're ready to take the bench (10-minute clock)."):
                        _nudged_ready.add(team_name)
            except Exception as e:
                print(f"  -> failed for {team_name}: {e.__class__.__name__}: {e}")
                attempts = _failures.get(idx, 0) + 1
                _failures[idx] = attempts
                delay = min(60 * (2 ** (attempts - 1)), 900)
                _retry_after[idx] = time.monotonic() + delay
                if team_name not in _nudged_failed:
                    tag = discord_handle if discord_handle else team_name
                    if _post_submissions(f"{tag} — I couldn't transcribe that video yet, but your submission is ready and you can start without it. I'll keep retrying in the background."):
                        _nudged_failed.add(team_name)

if __name__ == "__main__":
    # Run once if called directly, or loop if --loop
    if "--loop" in sys.argv:
        print("transcribe watcher looping every 30s...")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"watcher error: {e}")
            time.sleep(30)
    else:
        run_once()
