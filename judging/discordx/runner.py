import argparse
import asyncio
import re
import sys
from pathlib import Path

from .config import DiscordConfig, DiscordNotProvisioned
from .flows import CaseFlow
from .transport import DryRunTransport, DiscordTransport

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEAM_PATTERN = re.compile(r"team\s*#?\s*(\d+)", re.IGNORECASE)


def parse_team(text: str) -> int | None:
    match = TEAM_PATTERN.search(text)
    return int(match.group(1)) if match else None


async def run_dry_run(args) -> int:
    config = DiscordConfig.load(args.config, require_tokens=False)
    config.intake = args.intake or str(REPO_ROOT / "tests" / "dummy_submissions.json")
    if not args.real_clock:
        config.qna_minutes = 0.1
        config.countdown_marks_sec = [4, 2]
        config.heartbeat_minutes = 1 / 60
    transport = DryRunTransport(config)
    flow = CaseFlow(transport, config, out_dir=args.out, mock=True)

    await transport.start()
    heartbeat = asyncio.create_task(flow.heartbeat_loop())

    team = args.simulate_ping
    await transport.post(
        "team", "submissions",
        f"Team {team}, done submitting @Foreman (simulated ping)",
    )
    await flow.handle_ping(team, DryRunTransport.SIM_PARTICIPANT)

    heartbeat.cancel()
    await transport.close()
    print(f"\ndry run complete — full log at {transport.log_path}")
    return 0


async def run_live(args) -> int:
    try:
        config = DiscordConfig.load(args.config, require_tokens=True)
    except DiscordNotProvisioned as exc:
        print(f"not provisioned: {exc}", file=sys.stderr)
        return 2
    if args.intake:
        config.intake = args.intake

    transport = DiscordTransport(config)
    flow = CaseFlow(transport, config, out_dir=args.out, mock=args.mock)
    discord_mod = transport._discord
    foreman = transport.foreman

    submissions_id = int(config.channels["submissions"])
    cases_id = int(config.channels["cases"])

    @foreman.event
    async def on_message(message):
        if message.author.bot:
            return

        if message.channel.id == submissions_id and foreman.user in message.mentions:
            team = parse_team(message.content)
            if team is None:
                await message.channel.send(
                    "I could not read a team number — format: `Team 12, done submitting @Foreman`."
                )
                return
            asyncio.create_task(flow.handle_ping(team, str(message.author), message.author.id))
            return

        channel = message.channel
        if isinstance(channel, discord_mod.Thread) and channel.parent is not None and channel.parent.id == cases_id:
            match = re.match(r"case-T(\d+)", channel.name)
            if match:
                flow.record_answer(int(match.group(1)), str(message.author), message.content)

    await transport.start()
    print("live transport up — listening for pings in #submissions", flush=True)
    heartbeat = asyncio.create_task(flow.heartbeat_loop())
    try:
        await asyncio.Event().wait()
    finally:
        heartbeat.cancel()
        await transport.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="judging.discordx", description="Discord transport for the hackathon case flow")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.json"))
    parser.add_argument("--out", default=str(REPO_ROOT / "out"))
    parser.add_argument("--intake", default=None, help="override intake source ('sheet' or a file path)")
    parser.add_argument("--dry-run", action="store_true", help="simulate everything, send nothing")
    parser.add_argument("--mock", action="store_true", help="live Discord, but mock jurors (no API key needed) — rehearsal mode")
    parser.add_argument("--real-clock", action="store_true", help="dry-run with the real 7-minute clock (default: compressed)")
    parser.add_argument("--simulate-ping", type=int, default=1, help="team number for the simulated ping (dry-run)")
    args = parser.parse_args()

    if args.dry_run:
        return asyncio.run(run_dry_run(args))
    return asyncio.run(run_live(args))


if __name__ == "__main__":
    sys.exit(main())
