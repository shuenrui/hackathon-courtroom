"""Living-agent brain: each judge is an opencode CLI instance with its own persona
and persistent session memory per case. External tools are denied for participant safety."""
import json
import re
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS = ("builder", "skeptic", "futurist", "foreman")


class AgentBrain:
    """One opencode-backed juror. Session per (agent, team) gives living memory across the case."""

    def __init__(self, agent: str, model: str | None = None, timeout: int = 240):
        assert agent in AGENTS, f"unknown agent {agent}"
        self.agent = agent
        self.model = model
        self.timeout = timeout
        self.sessions: dict[str, str] = {}  # team_key -> opencode session id

    def _session_for(self, team_key: str) -> str | None:
        """Find the persistent session created for this (agent, team)."""
        if team_key in self.sessions:
            return self.sessions[team_key]
        want = f"jury-{self.agent}-{team_key}"
        try:
            out = subprocess.run(
                ["opencode", "session", "list"], cwd=str(REPO_ROOT),
                capture_output=True, text=True, timeout=20,
            ).stdout
            for line in out.splitlines():
                m = re.match(r"^(ses_[A-Za-z0-9]+)\s+(.+?)\s{2,}", line)
                if m and m.group(2).strip() == want:
                    self.sessions[team_key] = m.group(1)
                    return m.group(1)
        except Exception:
            pass
        return None

    def say(self, team_key: str, message: str) -> str:
        """Send a message into this agent's persistent case session; returns its spoken reply."""
        session = self._session_for(team_key)
        cmd = ["opencode", "run", "--agent", self.agent]
        if self.model:
            cmd += ["-m", self.model]
        if session:
            cmd += ["-s", session]
        else:
            # New case session with a deterministic title we can find later
            cmd += ["--title", f"jury-{self.agent}-{team_key}"]
        cmd.append(message)

        result = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=self.timeout,
        )
        # Register the freshly created session
        if not session:
            self._session_for(team_key)

        # Spoken reply arrives on stdout; UI chrome + tool chatter go to stderr.
        ansi = re.compile(r"\x1b\[[0-9;]*m|\x1b\[0m")
        text = ansi.sub("", (result.stdout or "")).strip()
        if not text:
            text = self._clean(result.stderr or "")
        return text

    @staticmethod
    def _clean(raw: str) -> str:
        """Keep the spoken reply; drop opencode UI chrome and tool chatter."""
        raw = re.compile(r"\x1b\[[0-9;]*m|\x1b\[0m").sub("", raw)
        kept: list[str] = []
        for line in raw.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith(("> ", "$ ", "→ ", "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")):
                continue
            kept.append(line)
        text = "\n".join(kept).strip()
        # If a tool ran mid-reply, the final spoken block is usually the tail — keep last 1200 chars
        return text[-1200:] if len(text) > 1200 else text
