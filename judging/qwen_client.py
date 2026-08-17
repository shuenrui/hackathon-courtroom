import hashlib
import json
import os

import requests


class LLMError(Exception):
    pass


class QwenClient:
    def __init__(self, base_url: str, api_key: str, model: str, timebox_sec: int = 300):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timebox = timebox_sec

    @classmethod
    def from_config(cls, qwen_cfg: dict, timebox_sec: int = 300) -> "QwenClient":
        api_key = os.environ.get(qwen_cfg.get("api_key_env", "QWEN_API_KEY"), "")
        if not api_key:
            raise LLMError(f"missing API key in env var {qwen_cfg.get('api_key_env')}")
        return cls(qwen_cfg["base_url"], api_key, qwen_cfg["model"], timebox_sec)

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timebox,
            )
        except requests.exceptions.RequestException as exc:
            raise LLMError(f"request failed: {exc.__class__.__name__}: {exc}") from exc

        if resp.status_code != 200:
            raise LLMError(f"API status {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected API response shape: {str(data)[:300]}") from exc


class MockQwenClient:
    PERSONA_BIAS = {
        "juror_one": {"completeness": 2, "novelty": -1, "problem_fit": 0},
        "juror_two": {"problem_fit": 2, "solution_quality": 1, "completeness": -1},
        "juror_three": {"agent_mastery": 2, "novelty": 2, "completeness": -1},
    }

    def complete(self, system: str, user: str) -> str:
        persona = "juror_one"
        for candidate in self.PERSONA_BIAS:
            marker = {"juror_one": "JUROR ONE", "juror_two": "JUROR TWO", "juror_three": "JUROR THREE"}[candidate]
            if marker in system.upper():
                persona = candidate
                break

        team_number = None
        try:
            start = user.find("{")
            end = user.rfind("}")
            doc = json.loads(user[start : end + 1])
            team_number = int(doc.get("team_number") or 0) or None
        except (ValueError, json.JSONDecodeError):
            pass
        if team_number is None:
            team_number = 1

        seed = hashlib.sha256(f"{persona}:{team_number}".encode()).digest()

        def roll(index: int, span: int) -> int:
            return seed[index] % span

        reachable = "true" in user.lower().split('"reachable":', 1)[-1][:10] if '"reachable"' in user else True
        url_penalty = 0 if reachable else 6

        scores = {
            "completeness": min(20, max(2, 11 + roll(0, 8) + self.PERSONA_BIAS[persona].get("completeness", 0) - url_penalty)),
            "agent_mastery": min(10, max(1, 4 + roll(1, 6) + self.PERSONA_BIAS[persona].get("agent_mastery", 0))),
            "problem_fit": min(10, max(1, 4 + roll(2, 6) + self.PERSONA_BIAS[persona].get("problem_fit", 0))),
            "solution_quality": min(10, max(1, 4 + roll(3, 6) + self.PERSONA_BIAS[persona].get("solution_quality", 0))),
            "novelty": min(10, max(1, 3 + roll(4, 6) + self.PERSONA_BIAS[persona].get("novelty", 0))),
        }
        if not reachable:
            scores["completeness"] = min(scores["completeness"], 4)
        total = sum(scores.values())

        flags = []
        if not reachable:
            flags.append("url_unreachable")

        doc = {
            "judge": persona,
            "team_number": team_number,
            "round": "blind",
            "scores": scores,
            "total": total,
            "flags": flags,
            "evidence": [
                f"Mock evidence ({persona}): problem statement assessed against rubric.",
                f"Mock evidence ({persona}): solution viability assessed against rubric.",
                f"Mock evidence ({persona}): URL smoke test result consumed from evidence bundle.",
            ],
        }
        return json.dumps(doc)
