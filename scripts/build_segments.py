#!/usr/bin/env python3
"""Build player-ready broadcast segments from Discord-sourced transcripts.

Converts broadcast/sources/<case>.json (+ ElevenLabs audio) into the segment
bundles the player consumes (broadcast/segments/), then writes playlist.json.
Entries without audio (score-bearing verdict lines, unvoiced) are dropped —
they must never reach the stream.

Usage: python3 scripts/build_segments.py [case_T01 ...]
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "broadcast" / "sources"
SEGMENTS = REPO_ROOT / "broadcast" / "segments"

META = {
    "case_T01": {
        "team_name": "Rehearsal Raya",
        "one_liner": "UndiBot — a first-time voter finds their polling station from an IC number, cutting through SPR portal language.",
        "demo_video": None,
    },
    "case_T14": {
        "team_name": "Machine Not Learning",
        "one_liner": "CareNav — three agents over the pre-claim journey: guidance, claim-risk scoring, plan recommendations.",
        "demo_video": None,
    },
    "case_T02": {
        "team_name": "Loop",
        "one_liner": "Loop turns a clinic's follow-up protocol into a running agent — check-in, triage, and escalation in the language of MOH clinical guidelines.",
        "demo_video": "https://www.youtube.com/watch?v=SA5eYjdijvI",
    },
}

KIND_FALLBACK = {"review": "review", "question": "question", "answer": "answer", "foreman": "foreman"}

_SHEET_CACHE: dict | None = None


def sheet_teams() -> dict:
    """Team metadata with service-stable numbering.

    Numbers come from the Judging Sheet (assigned by the judging service,
    never shifts). One-liners are joined from the intake form by team name —
    NEVER by form position, which shifts when rows are deleted.
    """
    global _SHEET_CACHE
    if _SHEET_CACHE is not None:
        return _SHEET_CACHE
    _SHEET_CACHE = {}
    try:
        sys.path.insert(0, str(REPO_ROOT))
        import gspread
        cfg = json.loads((REPO_ROOT / "config.json").read_text())["sheets"]
        gc = gspread.service_account(cfg["credentials_path"])
        ss = gc.open_by_key(cfg["spreadsheet_id"])

        solutions: dict[str, str] = {}
        for row in ss.worksheet("Form responses 1").get_all_records():
            name = str(row.get("Team Name") or "").strip().lower()
            sol = str(row.get("Solution") or "").strip().replace("\n", " ")
            if name and sol:
                solutions.setdefault(name, sol)

        for row in ss.worksheet("Judging Sheet").get_all_records():
            try:
                num = int(str(row.get("team_number")).strip())
            except (TypeError, ValueError):
                continue
            name = str(row.get("team_name") or "").strip()
            sol = solutions.get(name.lower(), "")
            one_liner = sol[:180].rsplit(" ", 1)[0] + ("…" if len(sol) > 180 else "")
            _SHEET_CACHE[num] = {
                "team_name": name,
                "one_liner": one_liner,
                "demo_video": row.get("demo_video_url") or None,
            }
    except Exception as exc:
        print(f"sheet lookup unavailable ({exc.__class__.__name__}) — using META only", file=sys.stderr)
    return _SHEET_CACHE


def has_scores(text: str) -> bool:
    return bool(re.search(r"panel total|/ ?60|spread \d|\d+ ?/ ?60", text, re.I))


def build(case: str) -> dict | None:
    src = SOURCES / f"{case}.json"
    if not src.exists():
        print(f"missing transcript: {src}", file=sys.stderr)
        return None
    transcript = json.loads(src.read_text())
    match = re.search(r"T(\d+)", case)
    team_number = int(match.group(1)) if match else 0
    meta = dict(sheet_teams().get(team_number, {}))
    for k, v in META.get(case, {}).items():
        if v is not None:
            meta[k] = v

    lines = []
    sealed = False
    for e in transcript["entries"]:
        if e["speaker"] == "foreman" and has_scores(e["text"]):
            if not sealed:
                lines.append({
                    "speaker": "foreman",
                    "kind": "sealed",
                    "text": "",
                    "audio": None,
                    "ts": e.get("ts"),
                })
                sealed = True
            continue
        audio = e.get("audio")
        if not audio or not (SOURCES / audio).exists():
            continue
        lines.append({
            "speaker": e["speaker"],
            "kind": KIND_FALLBACK.get(e.get("kind"), "answer"),
            "text": e["text"],
            "audio": f"sources/{audio}",
            "ts": e.get("ts"),
        })
    if not lines:
        return None

    return {
        "case_id": case,
        "team_number": team_number,
        "team_name": meta.get("team_name", f"Team {team_number}"),
        "one_liner": meta.get("one_liner", ""),
        "demo_video": meta.get("demo_video"),
        "lines": lines,
    }


def main() -> int:
    cases = sys.argv[1:] or sorted(p.stem for p in SOURCES.glob("case_*.json"))
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    playlist_files = []
    for case in cases:
        bundle = build(case)
        if bundle is None:
            print(f"{case}: no voiced lines, skipped")
            continue
        out = SEGMENTS / f"{case}.json"
        out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
        playlist_files.append(f"{case}.json")
        print(f"{case}: {len(bundle['lines'])} lines -> {out.relative_to(REPO_ROOT)}")

    playlist = {"event": "Build with AI Agents", "segments": playlist_files}
    (SEGMENTS / "playlist.json").write_text(json.dumps(playlist, indent=2))
    print(f"playlist: {len(playlist_files)} segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
