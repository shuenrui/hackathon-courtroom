#!/usr/bin/env python3
"""Event-day daemon: watches Discord for completed cases and feeds the
broadcast queue automatically.

Every poll: dump logs -> find case threads with a verdict -> run the
broadcast pipeline on any not yet processed. The player picks new cases
up on its own; nothing here needs a human during the stream.

Usage: python3 scripts/broadcast_watch.py [--interval 60]
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "out" / "discord_logs"
STATE_PATH = REPO / "out" / "broadcast_watch_state.json"
PLAYLIST = REPO / "broadcast" / "segments" / "playlist.json"
VERDICT_RE = re.compile(r"=== VERDICT T\d+")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"processed": [], "failed": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def queue_status() -> str:
    if PLAYLIST.exists():
        segs = json.loads(PLAYLIST.read_text()).get("segments", [])
        return " -> ".join(s.replace("case_T", "T").replace(".json", "") for s in segs) or "empty"
    return "empty"


def main() -> int:
    interval = 60
    if "--interval" in sys.argv:
        interval = int(sys.argv[sys.argv.index("--interval") + 1])
    state = load_state()
    print(f"[{stamp()}] broadcast watcher up — polling every {interval}s")
    print(f"[{stamp()}] queue: {queue_status()}")

    while True:
        try:
            subprocess.run(
                [sys.executable, "scripts/dump_discord_logs.py"],
                cwd=REPO, capture_output=True, timeout=120,
            )
            for log in sorted(LOG_DIR.glob("case-T*.log")):
                thread = log.stem
                if not VERDICT_RE.search(log.read_text()):
                    continue
                if thread in state["processed"] or thread in state["failed"]:
                    continue
                print(f"[{stamp()}] verdict detected: {thread} — processing")
                rc = subprocess.run(
                    [sys.executable, "scripts/broadcast_pipeline.py", thread],
                    cwd=REPO,
                ).returncode
                if rc == 0:
                    state["processed"].append(thread)
                    print(f"[{stamp()}] {thread} broadcast-ready — queue: {queue_status()}")
                else:
                    state["failed"].append(thread)
                    print(f"[{stamp()}] {thread} FAILED pipeline — needs a human", file=sys.stderr)
                save_state(state)
        except Exception as exc:
            print(f"[{stamp()}] poll error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
