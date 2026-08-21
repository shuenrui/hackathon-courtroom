import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class ForemanVoice:
    """The Foreman speaks through a dedicated Hermes instance (one-shot, isolated home).

    Purely additive: when disabled, missing, slow, or wrong, the caller's template
    line is used instead. The case flow never blocks on the Foreman's voice.
    """

    def __init__(self, cfg: dict | None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False)) or os.environ.get("FOREMAN_VOICE") == "1"
        self.hermes_home = os.environ.get("FOREMAN_HERMES_HOME") or cfg.get("hermes_home", "")
        self.binary = cfg.get("binary", "hermes")
        self.timeout_sec = int(cfg.get("timeout_sec", 45))
        self.max_wait_sec = float(cfg.get("max_wait_sec", 15))

    def warm(self) -> None:
        """Fire a cheap one-shot so the first real voice call skips cold start."""
        if not self.enabled:
            return
        env = dict(os.environ)
        if self.hermes_home:
            env["HERMES_HOME"] = str(Path(self.hermes_home).expanduser())
        try:
            subprocess.run(
                [self.binary, "-z", "Reply with exactly: warm.", "--cli", "--safe-mode"],
                capture_output=True, text=True, timeout=self.timeout_sec,
                env=env, cwd=str(REPO_ROOT),
            )
            print("foreman voice: warm", flush=True)
        except Exception as exc:
            print(f"foreman voice: warm failed ({exc.__class__.__name__}) — templates until warm", flush=True)

    def speak(self, event: str, context: str) -> str | None:
        """Ask the Hermes Foreman for a line. Returns post-ready text or None."""
        if not self.enabled:
            return None
        prompt = (
            f"VOICE REQUEST event={event} context: {context}\n"
            "Write the line(s) to post. Plain text only, no fences, no preamble."
        )
        env = dict(os.environ)
        if self.hermes_home:
            env["HERMES_HOME"] = str(Path(self.hermes_home).expanduser())
        try:
            result = subprocess.run(
                [self.binary, "-z", prompt, "--cli", "--safe-mode"],
                capture_output=True, text=True, timeout=self.timeout_sec,
                env=env, cwd=str(REPO_ROOT),
            )
        except subprocess.TimeoutExpired:
            print(f"foreman voice: {event} timed out after {self.timeout_sec}s — using template", flush=True)
            return None
        except FileNotFoundError:
            print("foreman voice: hermes binary not found — using templates", flush=True)
            self.enabled = False
            return None
        except Exception as exc:
            print(f"foreman voice: {event} failed ({exc.__class__.__name__}) — using template", flush=True)
            return None

        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
            print(f"foreman voice: {event} hermes rc={result.returncode} {'| '.join(tail)} — using template", flush=True)
            return None

        text = self._clean(result.stdout)
        if not text:
            return None
        return text

    @staticmethod
    def _clean(raw: str) -> str:
        text = re.sub(r"", "", raw, flags=re.DOTALL)
        text = re.sub(r"```[a-z]*\n?", "", text)
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")):
                continue
            lines.append(stripped)
        text = "\n".join(lines).strip()
        return text[:800]
