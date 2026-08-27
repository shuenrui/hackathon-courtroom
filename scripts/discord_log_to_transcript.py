#!/usr/bin/env python3
"""Convert downloaded Discord logs into TTS-ready transcripts.

Reads out/discord_logs/*.log, writes broadcast/sources/<name>.json:
one entry per utterance with a stable speaker id, display name, timestamp,
kind, and cleaned text — the manifest handed to ElevenLabs (one entry ->
one voice -> one mp3).

Safety: deliberation lines are tagged kind="deliberation" and marked
tts=false by default — they reference scores and must never be voiced
on stream. The duplicate second pass (re-posted verdicts) is deduped.

Usage: python3 scripts/discord_log_to_transcript.py [logfile ...]
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "out" / "discord_logs"
OUT_DIR = REPO_ROOT / "broadcast" / "sources"

SPEAKER_IDS = {
    "Vegapunk (The Foreman)": "foreman",
    "Pythagoras (The Builder)": "juror_one",
    "Atlas (The Skeptic)": "juror_two",
    "Edison (The Futurist)": "juror_three",
}
DISPLAY = {
    "foreman": "The Foreman",
    "juror_one": "The Builder",
    "juror_two": "The Skeptic",
    "juror_three": "The Futurist",
    "team": "The Team",
}

LINE_RE = re.compile(r"^\[(?P<ts>[\d\- :]+)\] (?P<author>.+?): (?P<text>.*)$")


def clean(text: str) -> str:
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"(?<!\w)\*(?!\s)", "", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def classify(speaker: str, text: str, phase: str) -> str:
    if speaker == "foreman":
        return "foreman"
    if phase == "deliberation":
        return "deliberation"
    if speaker == "team":
        return "answer"
    if text.startswith("Questions for") or "\n1." in text or text.lstrip().startswith("1."):
        return "question"
    return "review"


def parse_log(path: Path) -> dict:
    lines = path.read_text().splitlines()
    header = lines[0] if lines and lines[0].startswith("#") else ""
    entries: list[dict] = []
    phase = "qa"
    seen_verdicts: set[str] = set()
    current: dict | None = None

    def flush():
        nonlocal current
        if current and current["text"].strip():
            current["kind"] = classify(current["speaker"], current["text"], phase)
            current["tts"] = current["kind"] not in ("deliberation", "foreman")
            entries.append(current)
        current = None

    for raw in lines[1:]:
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            if current is not None:
                current["text"] += "\n" + raw
            continue
        ts, author, text = m.group("ts"), m.group("author").strip(), m.group("text")
        if "(thread event" in text:
            continue
        flush()
        speaker = SPEAKER_IDS.get(author, "team")
        low = text.lower()
        if speaker == "foreman" and (
            "court deliberates" in low or "participant has left" in low or "step out" in low
        ):
            phase = "deliberation"
        if speaker == "foreman" and "VERDICT" in text:
            key = re.sub(r"\s+", " ", text)
            if key in seen_verdicts:
                continue
            seen_verdicts.add(key)
        current = {
            "speaker": speaker,
            "name": DISPLAY.get(speaker, author),
            "ts": ts,
            "text": clean(text),
        }
    flush()

    for i, e in enumerate(entries, 1):
        e_index = {"index": i}
        e_index.update(e)
        entries[i - 1] = e_index

    match = re.search(r"created ([\d\- :]+)", header)
    return {
        "source": path.name,
        "thread_created": match.group(1) if match else None,
        "entries": entries,
    }


def main() -> int:
    logs = [Path(a) for a in sys.argv[1:]] or sorted(LOG_DIR.glob("case-*.log"))
    if not logs:
        print(f"no logs found in {LOG_DIR} — run scripts/dump_discord_logs.py first", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for log in logs:
        transcript = parse_log(log)
        stem = log.stem.replace("-", "_")
        out_path = OUT_DIR / f"{stem}.json"

        if out_path.exists():
            try:
                prev = json.loads(out_path.read_text())
                prev_audio = {
                    (e["speaker"], e["text"]): e["audio"]
                    for e in prev.get("entries", []) if e.get("audio")
                }
                for e in transcript["entries"]:
                    audio = prev_audio.get((e["speaker"], e["text"]))
                    if audio:
                        e["audio"] = audio
            except (json.JSONDecodeError, KeyError):
                pass

        out_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

        counts: dict[str, int] = {}
        for e in transcript["entries"]:
            counts[e["speaker"]] = counts.get(e["speaker"], 0) + 1
        voiced = sum(1 for e in transcript["entries"] if e["tts"])
        print(f"{log.name}: {len(transcript['entries'])} lines -> {out_path.relative_to(REPO_ROOT)}")
        for speaker in ("foreman", "juror_one", "juror_two", "juror_three", "team"):
            if counts.get(speaker):
                print(f"    {DISPLAY[speaker]:<12} {counts[speaker]:>2} lines")
        print(f"    tts-eligible: {voiced} (deliberation + foreman excluded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
