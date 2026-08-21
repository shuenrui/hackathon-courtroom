# Orange Pi 5 Ultra — judging server setup

Target: dedicated, always-on judging box for 23 Aug. ARM64 Linux (Orange Pi OS /
Debian-based). Wired ethernet strongly recommended.

## 1. Base system

```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip curl
sudo timedatectl set-timezone Asia/Kuala_Lumpur
timedatectl status          # confirm NTP sync: "System clock synchronized: yes"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

Clock accuracy matters — the Q&A clock and all logs trust this machine's time.

## 2. Repo + Python deps

```bash
git clone https://github.com/shuenrui/hackathon-judging.git
cd hackathon-judging
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 3. Secrets + knowledge (from the laptop bundle)

`knowledge/` (jury memory + theme briefing), `.env`, and `service-account.json`
are gitignored — they arrive via the bundle:

```bash
# on the laptop first:  ./deploy/bundle.sh  → hackathon-migration.tar.gz
# transfer the tarball to the Pi (scp), then:
./deploy/unbundle.sh ~/hackathon-migration.tar.gz
```

## 4. Hermes + Foreman home

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
# reopen shell or: export PATH="$HOME/.local/bin:$PATH"
hermes --version

chmod +x foreman/setup.sh
./foreman/setup.sh minimax "$ZEN_API_KEY"     # key from .env (QWEN_API_KEY)
```

`setup.sh` creates `~/.hermes-foreman` and verifies the voice path with a live
one-shot. This is a fresh single-mission agent — nothing else runs on this home.

## 5. Enable the voice

In `config.json`: set `foreman_voice.enabled` to `true`.

## 6. Verification checklist (stop at first failure)

1. Sheets read:
   `.venv/bin/python -c "from judging.blackboard import SheetsBlackboard; import json; c=json.load(open('config.json'))['sheets']; print(len(SheetsBlackboard(c['credentials_path'], c['spreadsheet_id']).load_intake()))"`
2. Dry rehearsal (nothing sent): `.venv/bin/python -m judging.discordx.runner --dry-run --simulate-ping 1`
   — full case on the console; voice lines appear.
3. Mock rehearsal on live Discord: `.venv/bin/python -m judging.discordx.runner --mock`,
   ping the Foreman with a known team name; all four bots post; Judging Sheet gains
   a row. Delete the rehearsal row afterwards.
4. Only after 1–3 pass: install the service (below).

## 7. Run as a service

```bash
sudo cp deploy/judging.service /etc/systemd/system/judging.service
# edit User= and paths if your user/home differs from opi:/home/opi
sudo systemctl daemon-reload
sudo systemctl enable --now judging
journalctl -u judging -f
```

Auto-starts on boot, restarts on crash. Heartbeats land in #bot_health every 15 min.

## 8. Day-of

- Power + ethernet confirmed before 13:00; keep the laptop charged as cold failover.
- Watch: `journalctl -u judging -f`, #bot_health, #ops.
- Back up `out/` at 15:00 and 16:30: `tar czf out-$(date +%H%M).tar.gz out/` → copy off-box.
- If the box dies: run the same command on the laptop (see specs/hermes-foreman-install.md §8).

## 9. After the event

Rotate all four Discord bot tokens and the model API key; wipe rehearsal traces.
