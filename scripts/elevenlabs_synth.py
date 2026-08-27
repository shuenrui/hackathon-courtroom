#!/usr/bin/env python3
"""Synthesize transcript audio with ElevenLabs.

Reads broadcast/sources/<case>.json transcripts, generates one MP3 per
tts-eligible entry using the voice map in broadcast/elevenlabs_voices.json,
and writes them to broadcast/sources/audio/. Reports character usage so we
stay aware of the free-plan quota (~10,000 chars/month).

Usage: python3 scripts/elevenlabs_synth.py [--force] [--speaker foreman] case_T01 [case_T14 ...]
       --force re-synthesizes every line, replacing cached/Edge clips.
       --speaker limits (re)synthesis to one speaker key.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "broadcast" / "sources"
AUDIO = SOURCES / "audio"
VOICES = REPO_ROOT / "broadcast" / "elevenlabs_voices.json"
API = "https://api.elevenlabs.io/v1/text-to-speech"


def load_key() -> str:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip()
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        sys.exit("missing ELEVENLABS_API_KEY in .env")
    return key


def apply_tempo(path: Path, speed: float) -> None:
    """Time-stretch an existing clip without pitch shift (ffmpeg atempo)."""
    tmp = path.with_name(path.name + ".orig.mp3")
    path.rename(tmp)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
         "-filter:a", f"atempo={speed}", str(path)],
        capture_output=True,
    )
    if proc.returncode != 0:
        tmp.replace(path)
        print(f"    atempo failed — kept original speed", file=sys.stderr)
    else:
        tmp.unlink()


def synth(session: requests.Session, voice_id: str, model_id: str, text: str, out: Path, speed: float = 1.0) -> bool:
    for attempt in range(3):
        r = session.post(
            f"{API}/{voice_id}",
            json={"text": text, "model_id": model_id},
            timeout=60,
        )
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            out.write_bytes(r.content)
            if speed != 1.0:
                apply_tempo(out, speed)
            return True
        detail = {}
        try:
            detail = r.json().get("detail", {})
        except Exception:
            pass
        print(f"    FAILED {r.status_code} {detail.get('code', '')} {detail.get('message', '')[:120]}", file=sys.stderr)
        return False
    return False


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    speaker = None
    if "--speaker" in argv:
        i = argv.index("--speaker")
        speaker = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if a != "--force"]
    cases = args or sorted(p.stem for p in SOURCES.glob("case_*.json"))
    key = load_key()
    vmap = json.loads(VOICES.read_text())
    model_id = vmap.get("model_id", "eleven_turbo_v2_5")
    session = requests.Session()
    session.headers.update({"xi-api-key": key})
    AUDIO.mkdir(parents=True, exist_ok=True)

    total_chars = 0
    for case in cases:
        path = SOURCES / f"{case}.json"
        if not path.exists():
            print(f"missing transcript: {path}", file=sys.stderr)
            continue
        transcript = json.loads(path.read_text())
        entries = [e for e in transcript["entries"] if e.get("tts") and (speaker is None or e["speaker"] == speaker)]
        print(f"{case}: {len(entries)} lines to voice")
        for e in entries:
            voice = vmap["voices"].get(e["speaker"], {})
            voice_id = voice.get("voice_id")
            if not voice_id:
                print(f"  [{e['index']:>2}] {e['speaker']}: no voice mapped, skipped")
                continue
            out = AUDIO / f"{case}_{e['index']:03d}.mp3"
            if e.get("audio") and out.exists() and not force:
                print(f"  [{e['index']:>2}] {voice.get('name', e['speaker']):<8} {len(e['text']):>5} chars -> {out.name} [cached]")
                continue
            chars = len(e["text"])
            ok = synth(session, voice_id, model_id, e["text"], out, speed=float(voice.get("speed", 1.0)))
            total_chars += chars if ok else 0
            status = "ok" if ok else "FAILED"
            print(f"  [{e['index']:>2}] {voice.get('name', e['speaker']):<8} {chars:>5} chars -> {out.name} [{status}]")
            e["audio"] = f"audio/{out.name}" if ok else None
        path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

    print(f"\nchars used this run: {total_chars:,} (creator plan: 126,161/month)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
