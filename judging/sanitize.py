import re

INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.I), "direct-override"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I), "direct-override"),
    (re.compile(r"you\s+are\s+now\b", re.I), "role-hijack"),
    (re.compile(r"act\s+as\s+(if\s+you\s+are|a)\s+(judge|juror|foreman)", re.I), "role-hijack"),
    (re.compile(r"^\s*system\s*:", re.I | re.M), "fake-system"),
    (re.compile(r"^\s*(new|revised)\s+instructions?\s*:", re.I | re.M), "fake-system"),
    (re.compile(r"(give|award|score)\s+(us|our\s+team)\s+(a\s+)?(full|maximum|max|top|highest)\s+(score|marks?|points?)", re.I), "score-solicitation"),
    (re.compile(r"as\s+the\s+(judge|juror|foreman)\s*,?\s*you\s+(must|should|will)", re.I), "role-hijack"),
    (re.compile(r"do\s+not\s+(penalize|flag|report)", re.I), "judgement-interference"),
    (re.compile(r"\[\s*(system|inst)\s*\]", re.I), "fake-system"),
]

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, max_chars: int) -> tuple[str, list[str]]:
    flags: list[str] = []
    if not isinstance(text, str):
        return "", ["non-string-field"]

    cleaned = CONTROL_CHARS.sub("", text)

    for pattern, label in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            flags.append(f"injection-signal:{label}")
            cleaned = pattern.sub(f"[blocked:{label}]", cleaned)

    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        flags.append("truncated")
        cleaned = cleaned[:max_chars]

    return cleaned, flags


def sanitize_submission(submission: dict, limits: dict) -> tuple[dict, list[str]]:
    all_flags: list[str] = []

    problem, p_flags = sanitize_text(
        submission.get("problem_statement", ""), limits.get("problem_max_chars", 2400)
    )
    solution, s_flags = sanitize_text(
        submission.get("solution", ""), limits.get("solution_max_chars", 4000)
    )

    all_flags.extend(f"problem:{f}" for f in p_flags)
    all_flags.extend(f"solution:{f}" for f in s_flags)

    sanitized = dict(submission)
    sanitized["problem_statement"] = problem
    sanitized["solution"] = solution
    return sanitized, all_flags
