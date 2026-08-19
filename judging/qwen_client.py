import hashlib
import json
import os

import requests


class LLMError(Exception):
    pass


class QwenClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        style: str = "openai",
        timebox_sec: int = 300,
        max_tokens: int = 4096,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._style = style
        self._timebox = timebox_sec
        self._max_tokens = max_tokens

    @classmethod
    def from_config(cls, qwen_cfg: dict, timebox_sec: int = 300) -> "QwenClient":
        api_key = os.environ.get(qwen_cfg.get("api_key_env", "QWEN_API_KEY"), "")
        if not api_key:
            raise LLMError(f"missing API key in env var {qwen_cfg.get('api_key_env')}")
        return cls(
            qwen_cfg["base_url"],
            api_key,
            qwen_cfg["model"],
            style=qwen_cfg.get("style", "openai"),
            timebox_sec=timebox_sec,
            max_tokens=qwen_cfg.get("max_tokens", 4096),
        )

    def complete(self, system: str, user: str) -> str:
        if self._style == "anthropic":
            return self._complete_anthropic(system, user)
        return self._complete_openai(system, user)

    def _complete_openai(self, system: str, user: str) -> str:
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

    def _complete_anthropic(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": self._max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        try:
            resp = requests.post(
                f"{self._base_url}/messages",
                headers=headers,
                json=payload,
                timeout=self._timebox,
            )
        except requests.exceptions.RequestException as exc:
            raise LLMError(f"request failed: {exc.__class__.__name__}: {exc}") from exc

        if resp.status_code != 200:
            raise LLMError(f"API status {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text:
            raise LLMError(f"empty text content in Anthropic response: {str(data)[:300]}")
        return text


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
            "review": self._review(persona, team_number, reachable),
            "questions": self._questions(persona, team_number, reachable),
        }
        return json.dumps(doc)

    def _review(self, persona: str, team_number: int, reachable: bool) -> str:
        if persona == "juror_one":
            return (
                f"Builder's read on Team {team_number}: the smoke test says the URL "
                f"is {'reachable' if reachable else 'unreachable'} and I anchor completeness "
                "around a solid 7/10 based on the observed signals."
            )
        if persona == "juror_two":
            return (
                f"Skeptic's read on Team {team_number}: the problem statement is specific "
                "but the go-to-market path reads thin; I want the team to defend the target user."
            )
        return (
            f"Futurist's read on Team {team_number}: the agent angle is interesting — "
            "I want to see how much autonomy was real versus scripted."
        )

    def _questions(self, persona: str, team_number: int, reachable: bool) -> list[str]:
        if persona == "juror_one":
            return [
                f"Team {team_number}: the edge case you describe — how do you handle input validation failures today?",
                "What part of the demo is staged versus fully autonomous?",
            ]
        if persona == "juror_two":
            return [
                f"Team {team_number}: who is the single user who would pay for this tomorrow?",
            ]
        return [
            f"Team {team_number}: which step of your pipeline did your agent improvise on that you had not scripted?",
        ]
