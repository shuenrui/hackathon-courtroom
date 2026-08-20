#!/usr/bin/env python3
"""Segment prep: judging results -> playable broadcast bundles (JSON + TTS audio).

Run from the repo root:
    python3 broadcast/prepare.py --judging out/judging.json --answers-dir broadcast/sample_data/answers

Requires: pip install edge-tts (audio generation needs internet at prep time only).
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from judging.foreman import strip_scores

BROADCAST_DIR = Path(__file__).resolve().parent
SEGMENTS_DIR = BROADCAST_DIR / "segments"
AUDIO_DIR = SEGMENTS_DIR / "audio"
MEDIA_DIR = BROADCAST_DIR / "media"

VOICES = {
    "juror_one": "en-US-GuyNeural",
    "juror_two": "en-GB-SoniaNeural",
    "juror_three": "en-AU-NatashaNeural",
    "team": "en-GB-RyanNeural",
}

JUDGE_ORDER = ("juror_one", "juror_two", "juror_three")


def clean(text: str) -> str:
    text = strip_scores(text)
    text = re.sub(r"\*\*", "", text)
    return " ".join(text.split())


def build_lines(entry: dict, answers: list[str]) -> list[dict]:
    team_number = entry["team_number"]
    lines: list[dict] = []
    docs = sorted(
        entry.get("blind_scores", []),
        key=lambda d: JUDGE_ORDER.index(d.get("judge")) if d.get("judge") in JUDGE_ORDER else 99,
    )
    for doc in docs:
        judge = doc.get("judge")
        if judge not in JUDGE_ORDER:
            continue
        review = clean(doc.get("review") or "")
        if review:
            lines.append({"speaker": judge, "kind": "review", "text": review})
        for question in (doc.get("questions") or [])[:2]:
            question = clean(question)
            if question:
                lines.append({"speaker": judge, "kind": "question", "text": question})
    if answers:
        for answer in answers:
            answer = clean(answer)
            if answer:
                lines.append({"speaker": "team", "kind": "answer", "text": f"Team {team_number}: {answer}"})
    return lines


async def synth_one(text: str, voice: str, path: Path, semaphore: asyncio.Semaphore) -> bool:
    import edge_tts

    async with semaphore:
        try:
            await edge_tts.Communicate(text, voice).save(str(path))
            return True
        except Exception as exc:
            print(f"  tts failed ({path.name}): {exc.__class__.__name__}", file=sys.stderr)
            return False


async def synth_lines(lines: list[dict], case_id: str) -> None:
    semaphore = asyncio.Semaphore(4)
    tasks = []
    for index, line in enumerate(lines, 1):
        voice = VOICES.get(line["speaker"], VOICES["team"])
        rel = f"audio/{case_id}_{index:03d}.mp3"
        tasks.append(synth_one(line["text"], voice, SEGMENTS_DIR / rel, semaphore))
        line["audio"] = rel
    results = await asyncio.gather(*tasks)
    for line, ok in zip(lines, results):
        if not ok:
            line.pop("audio", None)


def load_answers(answers_dir: Path | None, team_number: int) -> list[str]:
    if not answers_dir:
        return []
    path = answers_dir / f"team_{team_number:02d}.txt"
    if not path.exists():
        return []
    return [line.strip(" -\n") for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare broadcast segment bundles")
    parser.add_argument("--judging", default=str(REPO_ROOT / "out" / "judging.json"))
    parser.add_argument("--answers-dir", default=None)
    parser.add_argument("--teams", default=None, help="comma-separated team numbers, in show order (default: all, ranked)")
    parser.add_argument("--event", default="Build with AI Agents")
    parser.add_argument("--no-tts", action="store_true", help="skip audio generation (timing falls back to estimates)")
    args = parser.parse_args()

    judging_path = Path(args.judging)
    if not judging_path.exists():
        print(f"judging results not found: {judging_path} — run the pipeline first", file=sys.stderr)
        return 2
    results = json.loads(judging_path.read_text())

    if args.teams:
        wanted = [int(t) for t in args.teams.split(",")]
        by_number = {e["team_number"]: e for e in results}
        featured = [by_number[t] for t in wanted if t in by_number]
        missing = [t for t in wanted if t not in by_number]
        if missing:
            print(f"warning: teams not in judging results: {missing}", file=sys.stderr)
    else:
        featured = results

    answers_dir = Path(args.answers_dir) if args.answers_dir else None
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    playlist_files = []
    for entry in featured:
        team_number = entry["team_number"]
        case_id = f"case_{team_number:02d}"
        lines = build_lines(entry, load_answers(answers_dir, team_number))
        if not lines:
            print(f"team {team_number}: no dialogue lines, skipped", file=sys.stderr)
            continue

        print(f"team {team_number:>3} | {len(lines)} lines", flush=True)
        if not args.no_tts:
            asyncio.run(synth_lines(lines, case_id))

        demo_video = MEDIA_DIR / f"demo_{team_number:02d}.mp4"
        bundle = {
            "case_id": case_id,
            "team_number": team_number,
            "team_name": entry.get("team_name") or f"Team {team_number}",
            "one_liner": (clean(entry.get("problem_statement") or "") or "")[:160],
            "demo_video": f"media/{demo_video.name}" if demo_video.exists() else None,
            "lines": lines,
        }
        (SEGMENTS_DIR / f"{case_id}.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
        playlist_files.append(f"{case_id}.json")

    playlist = {"event": args.event, "segments": playlist_files}
    (SEGMENTS_DIR / "playlist.json").write_text(json.dumps(playlist, indent=2, ensure_ascii=False))
    print(f"\nprepared {len(playlist_files)} segments -> {SEGMENTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
