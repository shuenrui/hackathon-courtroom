import re

JUROR_DISPLAY = {
    "juror_one": "The Builder",
    "juror_two": "The Skeptic",
    "juror_three": "The Futurist",
}

CRITERIA_DISPLAY = {
    "completeness": "prototype completeness",
    "agent_mastery": "agent mastery",
    "problem_fit": "problem fit",
    "solution_quality": "solution quality",
    "novelty": "novelty",
}

_SCORE_LEAK = re.compile(
    r"\b\d{1,2}(?:\.\d+)?\s*(?:/|out of)\s*(?:60|20|10)\b"
    r"|\b(?:total|score|scored|spread)\s+\d{1,2}(?:\.\d+)?\b"
    r"|\b\d{1,2}\.\d\b",
    re.I,
)


def strip_scores(text: str) -> str:
    return _SCORE_LEAK.sub("[score held back]", text)


def build_case_header(entry: dict) -> str:
    team_number = entry["team_number"]
    contested = "CONTESTED" if entry.get("contested") else "standard"
    lines = [
        f"=== CASE T{team_number:02d} [{contested}] ===",
        f"Team {team_number} — blind first-pass scores (courtroom only):",
        "",
        f"{'criterion':<20} {'one':>6} {'two':>6} {'three':>6} {'avg':>6}",
    ]
    for criterion in CRITERIA_DISPLAY:
        row = [CRITERIA_DISPLAY[criterion]]
        for doc in entry.get("blind_scores", []):
            row.append(f"{doc['scores'].get(criterion, '-'):>6}")
        while len(row) < 4:
            row.append(f"{'-':>6}")
        row.append(f"{entry.get('averages', {}).get(criterion, '-'):>6}")
        lines.append("{:<20} {:>6} {:>6} {:>6} {:>6}".format(*row))
    lines.append("")
    totals = [str(doc["total"]) for doc in entry.get("blind_scores", [])]
    lines.append(f"Totals: {' / '.join(totals)} | panel total {entry.get('averages', {}).get('total', '-')} | spread {entry.get('spread', '-')}")
    if entry.get("flags"):
        lines.append(f"Flags: {', '.join(entry['flags'])}")
    return "\n".join(lines)


def _direction(judge_value, panel_value) -> str:
    try:
        judge_value = float(judge_value)
        panel_value = float(panel_value)
    except (TypeError, ValueError):
        return "weighed"
    if judge_value >= panel_value + 0.5:
        return "argued above panel consensus on"
    if judge_value <= panel_value - 0.5:
        return "argued below panel consensus on"
    return "aligned with the panel on"


def build_mirror_case(entry: dict) -> str:
    team_number = entry["team_number"]
    lines = [
        f"--- Case T{team_number:02d} ---",
    ]
    if entry.get("contested"):
        lines.append("This case is contested — the panel is dividing sharply.")
    averages = entry.get("averages", {})
    for doc in entry.get("blind_scores", []):
        persona = JUROR_DISPLAY.get(doc.get("judge"), doc.get("judge"))
        notes = doc.get("evidence", [])
        stance = None
        for criterion in CRITERIA_DISPLAY:
            direction = _direction(doc["scores"].get(criterion), averages.get(criterion))
            if "above" in direction or "below" in direction:
                stance = f"{persona} {direction} {CRITERIA_DISPLAY[criterion]}."
                break
        if stance is None:
            stance = f"{persona} weighed the evidence evenly."
        lines.append(stance)
        if notes:
            first = strip_scores(str(notes[0]))
            lines.append(f"    {persona} cites: {first}")
    lines.append("")
    lines.append("Verdict follows in the courtroom.")
    return strip_scores("\n".join(lines))


def build_verdict_line(entry: dict) -> str:
    team_number = entry["team_number"]
    return (
        f"=== VERDICT T{team_number:02d} === "
        f"panel total {entry.get('averages', {}).get('total', '-')} / 60, "
        f"spread {entry.get('spread', '-')}, "
        f"{'contested' if entry.get('contested') else 'clean'}."
    )


def build_shortlist_announcement(shortlist: list[dict], alternates: list[dict]) -> str:
    lines = [
        "=== TOP SIX — Round 1 prelims ===",
        "Congratulations to our finalists:",
        "",
    ]
    for entry in shortlist:
        name = entry.get("team_name") or f"Team {entry['team_number']}"
        lines.append(f"  - {name} (Team {entry['team_number']})")
    lines.append("")
    if alternates:
        lines.append("On standby as alternates:")
        for entry in alternates:
            name = entry.get("team_name") or f"Team {entry['team_number']}"
            lines.append(f"  - {name} (Team {entry['team_number']})")
        lines.append("")
    lines.append("Round 2 begins now: five-minute pitch, three-minute Q&A. Final scores stay private until the winners are crowned.")
    return strip_scores("\n".join(lines))


def build_brief(results: list[dict], shortlist: dict) -> str:
    """Cold-start brief: everything a fresh Foreman session needs to resume."""
    contested = [e["team_number"] for e in results if e.get("contested")]
    flagged = [(e["team_number"], ", ".join(e.get("flags", []))) for e in results if e.get("flags")]
    dropped = [(e["team_number"], e.get("dropped_judges")) for e in results if e.get("dropped_judges")]
    short = [e["team_number"] for e in shortlist.get("shortlist", [])]
    alternates = [e["team_number"] for e in shortlist.get("alternates", [])]

    lines = [
        "# Foreman brief — regenerated on every pipeline run",
        "",
        f"Cases scored: {len(results)}",
        f"Contested: {contested if contested else 'none'}",
        f"Flags for Shuen Rui: {flagged if flagged else 'clean'}",
        f"Dropped judges: {dropped if dropped else 'none'}",
        f"Current shortlist projection: {short if short else '—'} (+ alternates {alternates if alternates else '—'})",
        "",
        "Milestones: 16:15 clarifications close · 16:30 shortlist lock + spot-check · 16:45 top-six announcement",
        "",
        "Case table:",
    ]
    for e in results:
        mark = "CONTESTED" if e.get("contested") else "clean"
        lines.append(f"  rank {e['rank']:>2} — Team {e['team_number']:>2} [{mark}]")
    lines.append("")
    lines.append("Restore routine: read this brief, then out/dialog/ transcripts, then knowledge/lessons.md. Resume mid-state; never start cold.")
    return strip_scores("\n".join(lines))


def write_foreman_artifacts(results: list[dict], shortlist: dict, out_dir) -> None:
    from pathlib import Path

    base = Path(out_dir) / "foreman"
    base.mkdir(parents=True, exist_ok=True)

    for entry in results:
        team = entry["team_number"]
        (base / f"case_{team:02d}_courtroom.md").write_text(build_case_header(entry))
        (base / f"case_{team:02d}_mirror.md").write_text(build_mirror_case(entry))
        (base / f"case_{team:02d}_verdict.md").write_text(build_verdict_line(entry))

    (base / "brief.md").write_text(build_brief(results, shortlist))
    (base / "announcement_shortlist.md").write_text(
        build_shortlist_announcement(shortlist["shortlist"], shortlist["alternates"])
    )
