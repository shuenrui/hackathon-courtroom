import json
import os
from dataclasses import dataclass, field
from pathlib import Path

IDENTITIES = ("foreman", "juror_one", "juror_two", "juror_three")
CHANNEL_KEYS = ("submissions", "cases", "live_feed", "announcements", "ops", "bot_health")


class DiscordNotProvisioned(Exception):
    pass


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class DiscordConfig:
    guild_id: str
    channels: dict
    tokens: dict
    intake: str
    qna_minutes: int
    heartbeat_minutes: int
    countdown_marks_sec: list = field(default_factory=lambda: [180, 60, 10])

    @classmethod
    def load(cls, config_path: str, require_tokens: bool = True) -> "DiscordConfig":
        load_dotenv(Path(config_path).resolve().parent / ".env")
        cfg = json.loads(Path(config_path).read_text()).get("discord", {})
        if not cfg:
            raise DiscordNotProvisioned("no 'discord' block in config.json")

        channels = cfg.get("channels", {})
        missing_channels = [k for k in CHANNEL_KEYS if not channels.get(k)]
        if missing_channels:
            raise DiscordNotProvisioned(
                f"discord.channels missing: {', '.join(missing_channels)} — "
                "create the six channels and put their IDs in config.json"
            )

        token_env = cfg.get("token_env", {})
        tokens = {}
        missing_tokens = []
        for identity in IDENTITIES:
            env_var = token_env.get(identity, f"DISCORD_TOKEN_{identity.upper()}")
            value = os.environ.get(env_var, "")
            if value:
                tokens[identity] = value
            else:
                missing_tokens.append(f"{identity} (env {env_var})")
        if require_tokens and missing_tokens:
            raise DiscordNotProvisioned("missing bot tokens: " + "; ".join(missing_tokens))

        if require_tokens and not cfg.get("guild_id"):
            raise DiscordNotProvisioned("discord.guild_id is empty in config.json")

        return cls(
            guild_id=cfg.get("guild_id", ""),
            channels=channels,
            tokens=tokens,
            intake=cfg.get("intake", "sheet"),
            qna_minutes=cfg.get("qna_minutes", 7),
            heartbeat_minutes=cfg.get("heartbeat_minutes", 15),
            countdown_marks_sec=cfg.get("countdown_marks_sec", [180, 60, 10]),
        )
