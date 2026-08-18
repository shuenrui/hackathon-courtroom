import json

from .evidence import render_bundle_for_prompt, wrap_untrusted
from .schema import BlindScoreValidator, ScoreValidationError, extract_json
from .qwen_client import LLMError

JURORS = ("juror_one", "juror_two", "juror_three")

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


class DispatchResult:
    def __init__(self):
        self.scores: list[dict] = []
        self.dropped: dict[str, str] = {}

    @property
    def valid(self) -> bool:
        return len(self.scores) >= 2


def build_system_prompt(rubric: str, persona_prompt: str) -> str:
    return persona_prompt.strip() + "\n\n" + rubric.strip() + OUTPUT_CONTRACT_SUFFIX


def dispatch_to_panel(
    bundle: dict,
    client,
    rubric: str,
    juror_prompts: dict[str, str],
    validator: BlindScoreValidator,
    retries: int = 1,
) -> DispatchResult:
    result = DispatchResult()
    team_number = bundle.get("team_number")
    user_message = wrap_untrusted(render_bundle_for_prompt(bundle))

    for juror in JURORS:
        persona_prompt = juror_prompts.get(juror, "")
        if not persona_prompt:
            result.dropped[juror] = "missing_persona_prompt"
            continue

        system = build_system_prompt(rubric, persona_prompt)
        score_doc = None
        last_error = ""

        for attempt in range(retries + 1):
            try:
                raw = client.complete(system, user_message)
                doc = extract_json(raw)
                if doc.get("team_number") is None:
                    doc["team_number"] = team_number
                validator.validate(doc, expected_judge=juror)
                score_doc = doc
                break
            except ScoreValidationError as exc:
                last_error = f"validation: {exc}"
            except LLMError as exc:
                last_error = f"llm: {exc}"
            except Exception as exc:
                last_error = f"unexpected: {exc.__class__.__name__}: {exc}"

        if score_doc is not None:
            result.scores.append(score_doc)
        else:
            result.dropped[juror] = last_error

    return result


def serialize_dispatch(result: DispatchResult) -> dict:
    return {
        "valid_scores": len(result.scores),
        "dropped": result.dropped,
        "scores": result.scores,
    }
