from pathlib import Path

from .foreman import JUROR_DISPLAY, strip_scores

FOREMAN_NAME = "The Foreman"
FOREMAN_EMOJI = "🏛️"
JUROR_EMOJI = {
    "juror_one": "🔨",
    "juror_two": "🔍",
    "juror_three": "🔮",
}


class MockChannel:
    """Minimal channel abstraction: post() records messages, render() emits markdown.

    The live Discord transport will implement the same post() surface; the transcript
    format is the contract we want to SEE during the event.
    """

    def __init__(self, name: str):
        self.name = name
        self.messages: list[dict] = []

    def post(self, author: str, text: str) -> None:
        self.messages.append({"author": author, "text": text})

    def render(self) -> str:
        lines = [f"# {self.name}", ""]
        for i, message in enumerate(self.messages, 1):
            lines.append(f"**[{i}] {message['author']}**")
            lines.append(message["text"])
            lines.append("")
        return "\n".join(lines)


def _review_for(doc: dict, persona: str) -> str:
    text = (doc.get("review") or "").strip()
    if text:
        return strip_scores(text)
    notes = doc.get("evidence") or []
    return strip_scores(notes[0]) if notes else "The judge reviewed the submission on the evidence bundle."


def _questions_for(doc: dict) -> list[str]:
    questions = [q.strip() for q in (doc.get("questions") or []) if isinstance(q, str) and q.strip()]
    return [strip_scores(q) for q in questions[:3]]


def _juror_identity(persona: str) -> str:
    return f"{JUROR_DISPLAY.get(persona, persona)} {JUROR_EMOJI.get(persona, '')}".strip()


def render_jury_dialog(entry: dict, channel: MockChannel, foreman_name: str = FOREMAN_NAME) -> None:
    team_number = entry["team_number"]
    channel.post(
        f"{foreman_name} {FOREMAN_EMOJI}",
        f"The jury has been summoned for **Team {team_number}**. "
        "The panel is reading the submission now — scores stay sealed; this review is open.",
    )
    for doc in entry.get("blind_scores", []):
        persona = doc.get("judge")
        identity = _juror_identity(persona)
        channel.post(identity, _review_for(doc, persona))
        questions = _questions_for(doc)
        if questions:
            numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
            channel.post(identity, f"**Questions for Team {team_number}:**\n{numbered}")
    channel.post(
        f"{foreman_name} {FOREMAN_EMOJI}",
        f"**Team {team_number} — the floor is yours.** The jury has questions for you. "
        "Reply in this channel within 10 minutes; clarification closes at 16:15 sharp.",
    )


def render_answer_phase(entry: dict, answers: list[str], channel: MockChannel, foreman_name: str = FOREMAN_NAME) -> None:
    team_number = entry["team_number"]
    if answers:
        channel.post(f"Team {team_number}", "\n".join(f"- {a}" for a in answers))
    else:
        channel.post(f"Team {team_number}", "*(no answers submitted before the window closed)*")
    channel.post(
        f"{foreman_name} {FOREMAN_EMOJI}",
        f"Answers logged for Team {team_number} and relayed to the panel. "
        "Any score revision from here is cited against these answers and logged.",
    )


def write_dialog(entry: dict, out_dir) -> Path:
    base = Path(out_dir) / "dialog"
    base.mkdir(parents=True, exist_ok=True)
    channel = MockChannel(f"team-channel — Team {entry['team_number']:02d}")
    render_jury_dialog(entry, channel)
    path = base / f"team_{entry['team_number']:02d}.md"
    path.write_text(channel.render())
    return path


def append_answer_phase(entry: dict, answers: list[str], out_dir) -> Path:
    base = Path(out_dir) / "dialog"
    channel = MockChannel(f"team-channel — Team {entry['team_number']:02d}")
    render_answer_phase(entry, answers, channel)
    path = base / f"team_{entry['team_number']:02d}.md"
    with path.open("a") as fh:
        fh.write("\n---\n\n" + channel.render())
    return path
