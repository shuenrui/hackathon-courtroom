#!/usr/bin/env python3
"""Placeholder TTS with Edge-TTS (free, unlimited) until ElevenLabs is upgraded.

Voice cast mirrors broadcast/elevenlabs_voices.json so swapping back to
ElevenLabs is a re-run of scripts/elevenlabs_synth.py (cached files are kept
unless --force is passed).

Usage: python3 scripts/edge_synth.py case_T02 [...]
"""
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "broadcast" / "sources"
AUDIO = SOURCES / "audio"

VOICES = {
    "foreman": "en-US-ChristopherNeural",
    "juror_one": "en-US-GuyNeural",
    "juror_two": "en-GB-SoniaNeural",
    "juror_three": "en-GB-RyanNeural",
    "team": "en-US-EricNeural",
}


async def synth_case(case: str, force: bool) -> int:
    src = SOURCES / f"{case}.json"
    if not src.exists():
        print(f"missing transcript: {src}", file=sys.stderr)
        return 1
    transcript = json.loads(src.read_text())
    AUDIO.mkdir(parents=True, exist_ok=True)
    made = 0
    for e in transcript["entries"]:
        if not e.get("tts"):
            continue
        voice = VOICES.get(e["speaker"])
        if not voice:
            continue
        out = AUDIO / f"{case}_{e['index']:03d}_edge.mp3"
        if e.get("audio") and (SOURCES / e["audio"]).exists() and not force:
            print(f"  [{e['index']:>2}] {e['speaker']:<12} cached {e['audio']}")
            continue
        try:
            await edge_tts.Communicate(e["text"], voice).save(str(out))
        except Exception as exc:
            print(f"  [{e['index']:>2}] {e['speaker']:<12} FAILED {exc.__class__.__name__}", file=sys.stderr)
            continue
        e["audio"] = f"audio/{out.name}"
        made += 1
        print(f"  [{e['index']:>2}] {e['speaker']:<12} {len(e['text']):>5} chars -> {out.name}")
    src.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
    print(f"{case}: {made} clips synthesized")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    cases = args or sorted(p.stem for p in SOURCES.glob("case_*.json"))
    for case in cases:
        asyncio.run(synth_case(case, force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
