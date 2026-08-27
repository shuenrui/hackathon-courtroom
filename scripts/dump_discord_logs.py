#!/usr/bin/env python3
"""Download Discord message logs directly from the Discord API.

Pulls every case thread (active + archived, public + private) under #CASES,
plus recent history of #submissions, using the Foreman bot token. Output:
out/discord_logs/<thread-name>.log and out/discord_logs/submissions.log.

Usage: python3 scripts/dump_discord_logs.py [--channel CHANNEL_ID name:lines ...]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
API = "https://discord.com/api/v10"


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bot {token}"})
    return s


def get(session: requests.Session, path: str, **params):
    for attempt in range(5):
        r = session.get(API + path, params=params, timeout=30)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", "1"))
            print(f"  rate limited, waiting {wait}s", flush=True)
            time.sleep(wait + 0.2)
            continue
        if r.status_code >= 500 and attempt < 4:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"failed after retries: {path}")


def fmt_ts(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S")


def fetch_messages(session: requests.Session, channel_id: str) -> list[dict]:
    messages: list[dict] = []
    before = None
    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        batch = get(session, f"/channels/{channel_id}/messages", **params)
        if not batch:
            break
        messages.extend(batch)
        if len(batch) < 100:
            break
        before = batch[-1]["id"]
    messages.sort(key=lambda m: int(m["id"]))
    return messages


def render(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        author = m.get("author", {}).get("username", "?")
        ts = fmt_ts(m.get("timestamp") or m.get("created_at"))
        content = (m.get("content") or "").strip()
        kind = m.get("type", 0)
        if kind in (1, 2, 3):
            content = f"(thread event type={kind}) {content}"
        if not content and m.get("attachments"):
            content = " ".join(a.get("url", "") for a in m["attachments"])
        if not content and m.get("embeds"):
            content = f"[embed] {m['embeds'][0].get('title', '')}"
        if content:
            lines.append(f"[{ts}] {author}: {content}")
    return "\n".join(lines) + "\n"


def thread_created(t: dict) -> str:
    ts = t.get("created_at") or (t.get("thread_metadata") or {}).get("create_timestamp")
    return fmt_ts(ts) if ts else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO_ROOT / "out" / "discord_logs"))
    parser.add_argument("--submissions-limit", type=int, default=300)
    args = parser.parse_args()

    load_env()
    cfg = json.loads((REPO_ROOT / "config.json").read_text())["discord"]
    token = os.environ.get(cfg["token_env"]["foreman"])
    if not token:
        print("missing foreman token in .env", file=sys.stderr)
        return 2

    session = make_session(token)
    guild_id = cfg["guild_id"]
    cases_id = cfg["channels"]["cases"]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    threads: dict[str, dict] = {}
    active = get(session, f"/guilds/{guild_id}/threads/active").get("threads", [])
    for t in active:
        if t.get("parent_id") == cases_id:
            threads[t["id"]] = t
    for kind in ("public", "private"):
        try:
            archived = get(session, f"/channels/{cases_id}/threads/archived/{kind}").get("threads", [])
        except requests.HTTPError as exc:
            print(f"  archived {kind}: {exc}", file=sys.stderr)
            archived = []
        for t in archived:
            threads[t["id"]] = t

    print(f"found {len(threads)} case threads under #CASES", flush=True)
    used: set[str] = set()
    by_name: dict[str, list] = {}
    for tid, t in threads.items():
        by_name.setdefault(t["name"], []).append(t)
    ordered = []
    for name in sorted(by_name):
        group = sorted(by_name[name], key=lambda t: t.get("created_at") or "", reverse=True)
        ordered.append(group[0])
        ordered.extend(group[1:])
    for t in ordered:
        tid = t["id"]
        messages = fetch_messages(session, tid)
        name = t["name"]
        if name in used:
            name = f"{name}_{tid}"
        used.add(name)
        path = out_dir / f"{name}.log"
        header = f"# {t['name']} (thread {tid}, created {thread_created(t)}, {len(messages)} messages)\n"
        path.write_text(header + render(messages))
        print(f"  {t['name']}: {len(messages)} messages -> {path.name}", flush=True)

    subs = fetch_messages(session, cfg["channels"]["submissions"])
    subs = subs[-args.submissions_limit:]
    (out_dir / "submissions.log").write_text(render(subs))
    print(f"  #submissions: last {len(subs)} messages -> submissions.log", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
