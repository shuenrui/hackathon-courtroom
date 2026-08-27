#!/usr/bin/env python3
"""Process one judged Discord case into a broadcast-ready segment.

Steps: fresh Discord logs -> transcript -> voice (ElevenLabs first, Edge-TTS
fallback for anything missed) -> segment -> appended to the playlist in
completion order. Idempotent: cached audio is never re-synthesized.

Usage: python3 scripts/broadcast_pipeline.py case-T03
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "out" / "discord_logs"
SOURCES = REPO / "broadcast" / "sources"
PLAYLIST = REPO / "broadcast" / "segments" / "playlist.json"
VERDICT_RE = re.compile(r"=== VERDICT T\d+")


def run(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=REPO).returncode


def has_scores(text: str) -> bool:
    return bool(re.search(r"panel total|/ ?60|spread \d|\d+ ?/ ?60", text, re.I))


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("case-T"):
        sys.exit("usage: broadcast_pipeline.py case-T03")
    thread = sys.argv[1]
    case = thread.replace("-", "_")

    print(f"[1/6] dumping discord logs")
    if run([sys.executable, "scripts/dump_discord_logs.py"]) != 0:
        sys.exit("log dump failed")
    log = LOG_DIR / f"{thread}.log"
    if not log.exists():
        sys.exit(f"no discord log for {thread}")
    if not VERDICT_RE.search(log.read_text()):
        sys.exit(f"{thread} has no verdict yet — nothing to broadcast")

    print(f"[2/6] building transcript")
    if run([sys.executable, "scripts/discord_log_to_transcript.py", str(log)]) != 0:
        sys.exit("transcript failed")

    print(f"[3/6] arming foreman narration (score lines stay silent)")
    tpath = SOURCES / f"{case}.json"
    transcript = json.loads(tpath.read_text())
    for e in transcript["entries"]:
        if e["speaker"] == "foreman":
            e["tts"] = not has_scores(e["text"])
    tpath.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

    print(f"[4/6] voicing (elevenlabs -> edge fallback)")
    run([sys.executable, "scripts/elevenlabs_synth.py", case])
    missing = sum(
        1 for e in json.loads(tpath.read_text())["entries"]
        if e.get("tts") and not e.get("audio")
    )
    if missing:
        print(f"    {missing} lines missed elevenlabs — falling back to edge-tts")
        run([sys.executable, "scripts/edge_synth.py", case])

    print(f"[5/6] building segment + playlist")
    order = []
    if PLAYLIST.exists():
        order = json.loads(PLAYLIST.read_text()).get("segments", [])
    order = [f for f in order if f != f"{case}.json"] + [f"{case}.json"]
    if run([sys.executable, "scripts/build_segments.py", *[f.replace(".json", "") for f in order]]) != 0:
        sys.exit("segment build failed")

    print(f"[6/6] uploading to public site")
    if run([sys.executable, "scripts/broadcast_upload.py", case]) != 0:
        print(f"WARNING — {case} is broadcast-ready LOCALLY but the public upload failed.", file=sys.stderr)
        print(f"Fix, then re-run: python3 scripts/broadcast_upload.py {case}", file=sys.stderr)

    print(f"READY — {case} appended to broadcast queue (position {len(order)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
