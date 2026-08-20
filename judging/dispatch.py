import json
from concurrent.futures import ThreadPoolExecutor

from .evidence import render_bundle_for_prompt, wrap_untrusted
from .schema import BlindScoreValidator, ScoreValidationError, extract_json
from .qwen_client import LLMError

JURORS = ("juror_one", "juror_two", "juror_three")
REFLECTORS = ("juror_one", "juror_two", "juror_three", "foreman")

REFLECTION_CONTRACT_SUFFIX = """

REFLECTION PASS — follow exactly:
The case is closed. Write your post-case reflection for the jury's knowledge ledger.
Respond with ONE JSON object and nothing else. No prose, no markdown fences. Schema:
{
  "judge": "<your id: juror_one, juror_two, juror_three, or foreman>",
  "team_number": <integer, the case number>,
  "reflection": [
    "<line 1: what separated or broke this build, or (foreman) what the panel dynamic revealed>",
    "<line 2: which question or move proved useful, which was wasted>",
    "<line 3 (optional): a transferable pattern worth carrying into future cases>",
    "<line 4 (optional)>
  ]
}
2-4 lines, specific and transferable — written for the NEXT case, not for the record.
Never include scores or numerics. This text is distilled into future judge prompts.
"""

OUTPUT_CONTRACT_SUFFIX = """

OUTPUT CONTRACT — follow exactly:
Respond with ONE JSON object and nothing else. No prose, no markdown fences. Schema:
{
  "judge": "<your juror id>",
  "team_number": <integer, copied from the submission>,
  "round": "blind",
  "scores": {
    "completeness": <0-20>,
    "agent_mastery": <0-10>,
    "problem_fit": <0-10>,
    "solution_quality": <0-10>,
    "novelty": <0-10>
  },
  "total": <sum of the five scores>,
  "flags": ["short machine-readable issues, e.g. url_unreachable"],
  "evidence": ["1-12 short factual notes citing what you observed in the evidence bundle"],
  "review": "<a short commentary the team will see in their channel — observations only. NEVER include a score, number, or ranking here>",
  "questions": ["<up to 3 questions for the team, phrased directly to them>"]
}
The review and questions are the only parts of your response that reach the team. Keep them
substantive and specific to THIS submission. Your scores never leave the courtroom.
"""


DELIBERATION_CONTRACT_SUFFIX = """

DELIBERATION PASS — follow exactly:
The team has left the room. Their answers are on the record, and you can now see all three
blind scores. Speak to the bench: say whether the answers changed your read, where you agree
or diverge with the other jurors, and what the record ultimately shows. If the panel is split,
address the split directly. Do NOT propose changing any score — blind scores are final.
Respond with ONE JSON object and nothing else. No prose, no markdown fences. Schema:
{"judge": "<your juror id>", "statement": "<2-4 sentences, in your persona's voice>"}
"""


class DispatchResult:
    def __init__(self):
        self.scores: list[dict] = []
        self.dropped: dict[str, str] = {}

    @property
    def valid(self) -> bool:
        return len(self.scores) >= 2


def build_system_prompt(rubric: str, persona_prompt: str, lessons: str = "") -> str:
    base = persona_prompt.strip() + "\n\n" + rubric.strip()
    if lessons.strip():
        base = base + "\n\n" + lessons.strip()
    return base + OUTPUT_CONTRACT_SUFFIX


def dispatch_to_panel(
    bundle: dict,
    client,
    rubric: str,
    juror_prompts: dict[str, str],
    validator: BlindScoreValidator,
    retries: int = 1,
    lessons: str = "",
    parallel: bool = True,
) -> DispatchResult:
    """Score one submission with the full panel.

    Judges run concurrently within a team (queue discipline: teams stay sequential,
    so the courtroom sees one case at a time). Result ordering is always the fixed
    JURORS order, regardless of which judge finishes first.
    """
    result = DispatchResult()
    team_number = bundle.get("team_number")
    user_message = wrap_untrusted(render_bundle_for_prompt(bundle))

    def score_juror(juror: str) -> tuple[str, dict | None, str]:
        persona_prompt = juror_prompts.get(juror, "")
        if not persona_prompt:
            return juror, None, "missing_persona_prompt"

        system = build_system_prompt(rubric, persona_prompt, lessons)
        last_error = ""
        for _attempt in range(retries + 1):
            try:
                raw = client.complete(system, user_message)
                doc = extract_json(raw)
                if isinstance(doc.get("judge"), str):
                    doc["judge"] = doc["judge"].strip().lower()
                if doc.get("team_number") is None:
                    doc["team_number"] = team_number
                validator.validate(doc, expected_judge=juror)
                return juror, doc, ""
            except ScoreValidationError as exc:
                last_error = f"validation: {exc}"
            except LLMError as exc:
                last_error = f"llm: {exc}"
            except Exception as exc:
                last_error = f"unexpected: {exc.__class__.__name__}: {exc}"
        return juror, None, last_error

    active = [juror for juror in JURORS if juror in juror_prompts]
    missing = [juror for juror in JURORS if juror not in juror_prompts]
    for juror in missing:
        result.dropped[juror] = "missing_persona_prompt"

    if parallel and len(active) > 1:
        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            outcomes = {juror: outcome for juror, outcome in zip(active, pool.map(score_juror, active))}
    else:
        outcomes = {juror: score_juror(juror) for juror in active}

    for juror in JURORS:
        if juror not in outcomes:
            continue
        _, score_doc, error = outcomes[juror]
        if score_doc is not None:
            result.scores.append(score_doc)
        else:
            result.dropped[juror] = error

    return result


def serialize_dispatch(result: DispatchResult) -> dict:
    return {
        "valid_scores": len(result.scores),
        "dropped": result.dropped,
        "scores": result.scores,
    }


def build_reflection_prompt(persona_prompt: str) -> str:
    return persona_prompt.strip() + REFLECTION_CONTRACT_SUFFIX


def dispatch_deliberations(
    case_record: str,
    client,
    prompts: dict[str, str],
    retries: int = 1,
) -> tuple[list[dict], dict[str, str]]:
    """Post-kick deliberation: each juror sees all blind scores + the team's answers
    and speaks to the bench. Scores stay final; this is the panel arguing the record."""
    docs: list[dict] = []
    dropped: dict[str, str] = {}
    user_message = wrap_untrusted(case_record)

    for judge in JURORS:
        persona_prompt = prompts.get(judge, "")
        if not persona_prompt:
            dropped[judge] = "missing_persona_prompt"
            continue

        system = persona_prompt.strip() + DELIBERATION_CONTRACT_SUFFIX
        doc = None
        last_error = ""
        for _attempt in range(retries + 1):
            try:
                raw = client.complete(system, user_message)
                parsed = extract_json(raw)
                statement = str(parsed.get("statement") or "").strip()
                if len(statement) < 20:
                    raise ValueError("statement too short")
                doc = {"judge": judge, "statement": statement[:1300]}
                break
            except Exception as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"

        if doc is not None:
            docs.append(doc)
        else:
            dropped[judge] = last_error

    return docs, dropped


def dispatch_reflections(
    case_summary: str,
    client,
    prompts: dict[str, str],
    retries: int = 1,
    team_number: int | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Run the reflection pass for one closed case. Returns (docs, dropped)."""
    from .schema import extract_json

    docs: list[dict] = []
    dropped: dict[str, str] = {}
    user_message = wrap_untrusted(case_summary)

    for judge in REFLECTORS:
        persona_prompt = prompts.get(judge, "")
        if not persona_prompt:
            dropped[judge] = "missing_persona_prompt"
            continue

        system = build_reflection_prompt(persona_prompt)
        doc = None
        last_error = ""
        for _attempt in range(retries + 1):
            try:
                raw = client.complete(system, user_message)
                parsed = extract_json(raw)
                if parsed.get("team_number") is None and team_number is not None:
                    parsed["team_number"] = team_number
                if parsed.get("judge") != judge:
                    parsed["judge"] = judge
                if not isinstance(parsed.get("reflection"), list) or not (
                    2 <= len(parsed["reflection"]) <= 4
                ):
                    raise ValueError("reflection must be 2-4 lines")
                doc = {
                    "judge": judge,
                    "team_number": int(parsed["team_number"]),
                    "reflection": [str(line)[:300] for line in parsed["reflection"]],
                }
                break
            except Exception as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"

        if doc is not None:
            docs.append(doc)
        else:
            dropped[judge] = last_error

    return docs, dropped
