"""Entry point: python3 -m judging.agents.runner [--mock]

Four living opencode agents on Discord. Foreman listens for pings in #submissions,
jurors speak when their turn comes; team replies are recorded and agents react.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

from ..discordx.transport import DiscordTransport
from ..discordx.config import DiscordConfig
from .court import AgentCourt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


async def run(args) -> int:
    try:
        config = DiscordConfig.load(args.config, require_tokens=True)
    except Exception as exc:
        print(f"not provisioned: {exc}", file=sys.stderr)
        return 2

    from ..blackboard import Blackboard, SheetsBlackboard
    if config.intake == "sheet":
        cfg = __import__("json").loads((REPO_ROOT / "config.json").read_text())["sheets"]
        board = SheetsBlackboard(cfg["credentials_path"], cfg["spreadsheet_id"])
        rows = board.load_intake()
    else:
        board = Blackboard()
        rows = board.load_intake(config.intake)
    by_name: dict[str, int] = {}
    by_number: dict[int, str] = {}
    # dedupe_first assigns stable sequential team_number (1..N) — raw load_intake does NOT
    for row in board.dedupe_first(rows):
        num = row.get("team_number")
        name = str(row.get("team_name") or "").strip()
        if num is None:
            continue
        by_number[num] = name
        if name:
            by_name[name.lower()] = num

    def reload():
        """Re-read the sheet so post-startup submissions resolve (non-destructive)."""
        nonlocal by_name, by_number
        try:
            rows = board.load_intake()
            new_by_name, new_by_number = {}, {}
            for row in board.dedupe_first(rows):
                num, name = row.get("team_number"), str(row.get("team_name") or "").strip()
                if num is None:
                    continue
                new_by_number[num] = name
                if name:
                    new_by_name[name.lower()] = num
            by_name, by_number = new_by_name, new_by_number
        except Exception as exc:
            print(f"resolver refresh failed: {exc.__class__.__name__}", flush=True)

    def resolve(text: str) -> int | None:
        def _cached(t: str) -> int | None:
            m = re.search(r"\bteam\s*#?\s*(\d+)\b", t, re.I)
            if m and int(m.group(1)) in by_number:
                return int(m.group(1))
            low = t.lower()
            best, bnum = "", None
            for name, num in by_name.items():
                if name in low and len(name) > len(best):
                    best, bnum = name, num
            return bnum

        num = _cached(text)
        if num is not None:
            return num
        # Miss -> maybe the team submitted after startup; refresh from the sheet and retry once.
        reload()
        print(f"[submissions] resolver refreshed: {len(by_number)} teams", flush=True)
        return _cached(text)

    print(f"team resolver loaded: {len(by_number)} teams from intake '{config.intake}': {by_number}", flush=True)
    transport = DiscordTransport(config)
    court = AgentCourt(transport, config, out_dir=args.out, mock=args.mock)
    foreman = transport.foreman
    discord_mod = transport._discord
    submissions_id = int(config.channels["submissions"])
    cases_id = int(config.channels["cases"])
    active: set[int] = set()
    case_lock = asyncio.Lock()

    @foreman.event
    async def on_message(message):
        if message.author.bot:
            return
        # Team replies inside case threads -> record for the courtroom + agent context
        ch = message.channel
        if isinstance(ch, discord_mod.Thread) and ch.parent is not None and ch.parent.id == cases_id:
            m = re.match(r"case-T(\d+)", ch.name)
            if m:
                team = int(m.group(1))
                court.record_answer(team, message.author.display_name, message.content)
            return
        # Ping in #submissions starts a case
        if message.channel.id == submissions_id and foreman.user in message.mentions:
            team = await asyncio.to_thread(resolve, message.content)
            if team is None:
                await message.channel.send("I could not match a team — include your team name (as submitted) or `Team 12`, and mention me.")
                return
            if team in active:
                await message.channel.send(f"{by_number.get(team, f'Team {team}')} — your case is already in flight.")
                return
            active.add(team)
            try:
                async with case_lock:
                    print(f"[submissions] {message.author}: team={team} — opening case", flush=True)
                    thread = await transport.create_case_thread(team)
                    await court.run_case(thread, team, str(message.author), message.author.id)
            finally:
                active.discard(team)

    async def heartbeat():
        while True:
            try:
                await transport.post("foreman", "bot_health", "heartbeat — agent courtroom up")
            except Exception:
                pass
            await asyncio.sleep(config.heartbeat_minutes * 60)

    hb = asyncio.create_task(heartbeat())
    await transport.start()
    print("agent courtroom up — Foreman listening in #submissions", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        hb.cancel()
        await transport.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="judging.agents")
    p.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    p.add_argument("--out", default=str(REPO_ROOT / "out"))
    p.add_argument("--intake", default=None)
    p.add_argument("--mock", action="store_true")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
