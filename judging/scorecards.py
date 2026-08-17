from .schema import CRITERIA

CRITERIA_LABELS = {
    "completeness": "Prototype completeness (20)",
    "agent_mastery": "Agent mastery (10)",
    "problem_fit": "Problem fit (10)",
    "solution_quality": "Solution quality & viability (10)",
    "novelty": "Novelty / wow factor (10)",
}

EVENT_TITLE = "Devin x Claw Collective x Qwen Hackathon — 23 August 2026"


def split_scorecards(results: list[dict]) -> dict:
    sections = {}
    ranked = sorted(results, key=lambda e: e.get("rank", 10**6))
    for entry in ranked:
        team_number = entry["team_number"]
        blocks = [
            f"Hi {entry.get('captain_contact') or 'captain'}, here is "
            f"{entry.get('team_name') or f'Team {team_number}'}'s (Team {team_number}) scorecard "
            f"from the Devin x Claw Collective x Qwen Hackathon preliminary round, 23 August 2026.",
            "",
            f"Result: {entry.get('status', 'scored')} - rank {entry.get('rank', '-')} of {len(ranked)}.",
            "",
            "Panel averages (three-judge panel, scored out of 60):",
        ]
        averages = entry.get("averages", {})
        for criterion in CRITERIA:
            blocks.append(f"- {CRITERIA_LABELS[criterion]}: {averages.get(criterion, '-')}")
        blocks.append(f"- Total: {averages.get('total', '-')} / 60")
        blocks.append("")
        if entry.get("evidence_notes"):
            blocks.append("What the panel cited:")
            for note in entry["evidence_notes"][:8]:
                blocks.append(f"- {note}")
            blocks.append("")
        blocks.append("Thanks for building with us. See you at the next OpenClaw KL event.")
        sections[team_number] = "\n".join(blocks)
    return sections


def compile_scorecards(results: list[dict]) -> str:
    lines = [
        f"# Private scorecards — {EVENT_TITLE}",
        "",
        "Compiled by the Judging Service. One section per team; send each section to that team's captain only.",
        "",
        "---",
    ]

    ranked = sorted(results, key=lambda e: e.get("rank", 10**6))
    for entry in ranked:
        team_number = entry["team_number"]
        team_name = entry.get("team_name") or f"Team {team_number}"
        captain = entry.get("captain_contact") or "(no captain contact on record)"
        averages = entry.get("averages", {})

        lines.append("")
        lines.append(f"## {team_name} (Team {team_number})")
        lines.append(f"Captain contact: {captain}")
        lines.append(f"Status: {entry.get('status', 'scored')} · Rank: {entry.get('rank', '-')} · Total: {averages.get('total', '-')} / 60")
        if entry.get("contested"):
            lines.append("(Case was contested — juror spread >= 10 or near the cutoff.)")
        lines.append("")
        lines.append("Panel averages:")
        for criterion in CRITERIA:
            lines.append(f"- {CRITERIA_LABELS[criterion]}: {averages.get(criterion, '-')}")
        lines.append("")

        feedback = entry.get("feedback")
        if feedback:
            lines.append("Panel feedback:")
            lines.append(feedback)
            lines.append("")

        evidence_lines = entry.get("evidence_notes", [])
        if evidence_lines:
            lines.append("Evidence notes cited by the panel:")
            for note in evidence_lines[:12]:
                lines.append(f"- {note}")
            lines.append("")

        flags = entry.get("flags", [])
        if flags:
            lines.append(f"Flags: {', '.join(flags)}")
            lines.append("")

        lines.append("---")

    return "\n".join(lines) + "\n"
