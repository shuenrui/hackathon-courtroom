import asyncio
from datetime import datetime
from pathlib import Path

CHUNK = 1900


def chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK:
        return [text]
    parts = []
    rest = text
    while len(rest) > CHUNK:
        cut = rest.rfind("\n", 0, CHUNK)
        cut = cut if cut > CHUNK // 2 else CHUNK
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        parts.append(rest)
    return parts


class DryRunTransport:
    """Full rehearsal mode: every Discord action is printed and logged, nothing is sent.

    Simulates one participant ('SimulatedCaptain#0001') so the whole case flow —
    ping → thread → Q&A clock → kick → verdict → mirror — runs end to end offline.
    """

    SIM_PARTICIPANT = "SimulatedCaptain#0001"

    def __init__(self, config, log_path: str = "out/discord_dryrun.log"):
        self.config = config
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.log_path.open("a")
        self._threads: dict[int, dict] = {}

    def _log(self, identity: str, where: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] ({identity} → {where}) {text}"
        print(line, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()

    async def start(self) -> None:
        self._log("system", "dry-run", "transport up — all actions are simulated")

    async def close(self) -> None:
        self._fh.close()

    async def post(self, identity: str, channel_key: str, text: str) -> None:
        self._log(identity, f"#{channel_key}", text)

    async def create_case_thread(self, team_number: int) -> int:
        self._threads[team_number] = {"participants": [self.SIM_PARTICIPANT]}
        self._log("foreman", "#CASES", f"created thread case-T{team_number:02d}")
        return team_number

    async def add_participant(self, handle: int, user: str) -> None:
        self._log("foreman", f"case-T{handle:02d}", f"added {user} to thread")

    async def remove_participant(self, handle: int, user: str) -> None:
        self._log("foreman", f"case-T{handle:02d}", f"removed {user} from thread (Q&A clock at zero)")

    async def post_to_thread(self, handle: int, identity: str, text: str) -> None:
        self._log(identity, f"case-T{handle:02d}", text)

    def answers_seen(self, handle: int) -> list[str]:
        return [
            f"(simulated answer 1) We validate at the agent boundary and bounce bad fields to the operator queue.",
            f"(simulated answer 2) The staged part is only the login; everything after runs unscripted.",
        ]


class DiscordTransport:
    """Live transport: four discord.py clients (Foreman + 3 judges) in one process."""

    NICKNAMES = {
        "foreman": "The Foreman",
        "juror_one": "The Builder",
        "juror_two": "The Skeptic",
        "juror_three": "The Futurist",
    }

    def __init__(self, config):
        import discord

        self._discord = discord
        self.config = config
        self.clients: dict = {}
        self._ready = asyncio.Event()

        for identity in ("foreman", "juror_one", "juror_two", "juror_three"):
            intents = discord.Intents.default()
            intents.message_content = True
            intents.members = True
            self.clients[identity] = discord.Client(intents=intents)

        self.foreman = self.clients["foreman"]
        self._guild = None
        self._channel_cache: dict = {}

    async def start(self) -> None:
        for identity, client in self.clients.items():
            @client.event
            async def on_ready(_id=identity):
                print(f"{_id} connected as {self.clients[_id].user}", flush=True)
                if _id == "foreman":
                    self._guild = self.foreman.get_guild(int(self.config.guild_id))
                    if self._guild is None:
                        print(f"WARNING: guild {self.config.guild_id} not visible to the Foreman", flush=True)
                    self._ready.set()

        tasks = [client.start(self.config.tokens[identity]) for identity, client in self.clients.items()]
        self._gateway_tasks = [asyncio.create_task(t) for t in tasks]
        await asyncio.wait_for(self._ready.wait(), timeout=30)
        await self._set_nicknames()

    async def _set_nicknames(self) -> None:
        if self._guild is None:
            return
        for identity, nick in self.NICKNAMES.items():
            client = self.clients[identity]
            try:
                await client.wait_until_ready()
                member = self._guild.get_member(client.user.id)
                if member is not None and member.nick != nick:
                    await member.edit(nick=nick)
                    print(f"{identity} nickname set: {nick}", flush=True)
            except Exception as exc:
                print(f"nickname set failed for {identity}: {exc.__class__.__name__}", flush=True)

    async def close(self) -> None:
        for client in self.clients.values():
            try:
                await client.close()
            except Exception:
                pass

    def _channel(self, channel_key: str):
        if channel_key not in self._channel_cache:
            channel_id = int(self.config.channels[channel_key])
            channel = self.foreman.get_channel(channel_id)
            if channel is None:
                raise RuntimeError(f"channel '{channel_key}' ({channel_id}) not visible to the Foreman bot")
            self._channel_cache[channel_key] = channel
        return self._channel_cache[channel_key]

    async def post(self, identity: str, channel_key: str, text: str) -> None:
        client = self.clients[identity]
        await client.wait_until_ready()
        channel = self._channel(channel_key)
        for part in chunk_text(text):
            await channel.send(part)

    async def create_case_thread(self, team_number: int) -> object:
        cases = self._channel("cases")
        thread = await cases.create_thread(
            name=f"case-T{team_number:02d}",
            type=self._discord.ChannelType.private_thread,
            auto_archive_duration=1440,
            reason="hackathon case flow",
        )
        for identity in ("juror_one", "juror_two", "juror_three"):
            client = self.clients[identity]
            await client.wait_until_ready()
            me = self._guild.get_member(client.user.id) if self._guild else None
            if me is not None:
                try:
                    await thread.add_user(me)
                except Exception:
                    pass
        return thread

    async def add_participant(self, thread, user_id: int) -> None:
        member = self._guild.get_member(user_id) if self._guild else None
        if member is None and self._guild is not None:
            try:
                member = await self._guild.fetch_member(user_id)
            except Exception:
                return
        if member is not None:
            await thread.add_user(member)

    async def remove_participant(self, thread, user_id: int) -> None:
        member = self._guild.get_member(user_id) if self._guild else None
        if member is not None:
            try:
                await thread.remove_user(member)
            except Exception:
                pass

    async def post_to_thread(self, thread, identity: str, text: str) -> None:
        client = self.clients[identity]
        await client.wait_until_ready()
        live_thread = await client.fetch_channel(thread.id)
        for part in chunk_text(text):
            await live_thread.send(part)
