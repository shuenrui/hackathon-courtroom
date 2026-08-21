# Hermes Foreman — new-device install runbook

Moves the full judging stack (transport + jury + Foreman voice) to a dedicated
always-on device. The laptop stays as cold failover: everything still runs there.

**Primary target: Orange Pi 5 Ultra (ARM64 Linux) — use `deploy/orangepi.md`**,
which has the device-specific commands, systemd unit, and bundle transfer flow.
This runbook is the generic/failover version.

Note: `knowledge/` and `out/` are gitignored. A fresh clone needs the migration
bundle (`deploy/bundle.sh` on the source machine → `deploy/unbundle.sh` on the
target) or the jury starts without its theme briefing and accumulated lessons.

## 0. Prerequisites

- Device is physically at the venue, on venue power + internet, and stays awake
  (macOS: `caffeinate -s` or Energy Saver "never sleep"; Linux: `systemd-inhibit`).
- Outbound HTTPS works: Discord, Google Sheets, and the model gateway
  (`opencode.ai` for minimax preset, Aliyun MaaS for qwen preset).
- Python 3.11+, git, curl.

## 1. Install Hermes Agent

Follow the official install for the device OS (NousResearch/hermes-agent).
Verify: `hermes --version`.

## 2. Clone the repo

```bash
git clone <repo-url> hackathon-judging && cd hackathon-judging
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Provision the Foreman home

```bash
chmod +x foreman/setup.sh
./foreman/setup.sh minimax "$ZEN_API_KEY"      # or: qwen "$ALIYUN_KEY"
```

Creates `~/.hermes-foreman` (SOUL.md, AGENTS.md, config.yaml) and verifies the
voice path with a live one-shot. Keep this home separate from any other Hermes
instance on the device — the Foreman is its own mission.

## 4. Secrets (secure copy from the laptop — never paste into chat)

- `.env` — `DISCORD_TOKEN_FOREMAN`, `DISCORD_TOKEN_JUROR_ONE/TWO/THREE`, `QWEN_API_KEY`
- `service-account.json` — Google service account key

Both are gitignored; transfer via AirDrop/encrypted archive/1Password, `chmod 600`.

## 5. Enable the voice

In `config.json` set `foreman_voice.enabled: true` and confirm `hermes_home`
points at `~/.hermes-foreman`. (Or leave it false and export `FOREMAN_VOICE=1`
for a rehearsal only.)

## 6. Verification checklist (in order, stop at first failure)

1. `hermes --version` and the setup.sh one-shot already passed.
2. Sheets read: `python3 -c "from judging.blackboard import SheetsBlackboard; import json; c=json.load(open('config.json'))['sheets']; print(len(SheetsBlackboard(c['credentials_path'], c['spreadsheet_id']).load_intake()))"`
   — prints the current submission count.
3. Dry rehearsal (nothing sent): `python3 -m judging.discordx.runner --dry-run --simulate-ping 1`
   — full case completes on the console log; voice lines appear if enabled.
4. Mock rehearsal on live Discord: `python3 -m judging.discordx.runner --mock`
   then ping the Foreman from a test account with a known team name. All four
   bots post; Judging Sheet gains a row; clean up the rehearsal row afterwards.
5. Only after 1–4 pass: `python3 -m judging.discordx.runner` (real jury).

## 7. Day-of operation

```bash
caffeinate -s python3 -m judging.discordx.runner
```

- Watch `#bot_health` heartbeats (every 15 min) and the process stdout.
- Escalations land in `#ops` with `@Shuen Rui`.
- `out/` is the single source of truth; back it up (zip to cloud) at 15:00 and 16:30.

## 8. Failover

If the device dies mid-event: start the same command on the laptop. State lives
in `out/` and the sheet — copy the latest `out/` from the device if reachable,
otherwise the sheet + Discord history are sufficient to resume. Voice falls back
to templates automatically when Hermes is unavailable; nothing else changes.

## 9. After the event

- Rotate all four Discord bot tokens and the model API key (they passed through
  working sessions).
- Wipe rehearsal traces (form rows, Judging Sheet rows, Discord threads) before
  any reuse.
