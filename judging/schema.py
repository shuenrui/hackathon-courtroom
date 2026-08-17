import json
from pathlib import Path

from jsonschema import Draft202012Validator

CRITERIA_MAX = {
    "completeness": 20,
    "agent_mastery": 10,
    "problem_fit": 10,
    "solution_quality": 10,
    "novelty": 10,
}
CRITERIA = tuple(CRITERIA_MAX)
MAX_TOTAL = sum(CRITERIA_MAX.values())
TIEBREAK_ORDER = ("completeness", "problem_fit", "solution_quality", "novelty")


class ScoreValidationError(Exception):
    pass


class BlindScoreValidator:
    def __init__(self, schema_path: str | Path):
        schema = json.loads(Path(schema_path).read_text())
        self._validator = Draft202012Validator(schema)

    def validate(self, doc: dict, expected_judge: str | None = None) -> None:
        errors = sorted(self._validator.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            msgs = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:5])
            raise ScoreValidationError(f"schema violation: {msgs}")

        if expected_judge is not None and doc.get("judge") != expected_judge:
            raise ScoreValidationError(f"judge mismatch: expected {expected_judge}, got {doc.get('judge')}")

        if doc.get("round") != "blind":
            raise ScoreValidationError("round must be 'blind' for Round 1 scoring")

        if not isinstance(doc.get("team_number"), int) or isinstance(doc.get("team_number"), bool):
            raise ScoreValidationError("team_number must be an integer")

        computed = round(sum(doc["scores"][c] for c in CRITERIA), 2)
        if abs(computed - doc["total"]) > 0.05:
            raise ScoreValidationError(f"total {doc['total']} does not match sum of scores {computed}")

        if not doc.get("evidence"):
            raise ScoreValidationError("at least one evidence note is required")


def extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ScoreValidationError("no JSON object found in response")

    try:
        doc = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ScoreValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ScoreValidationError("response JSON is not an object")
    return doc
