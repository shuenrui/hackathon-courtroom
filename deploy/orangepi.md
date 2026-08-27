# Orange Pi 5 Ultra — judging server setup

Target: dedicated, always-on judging box for 23 Aug. ARM64 Linux. Wired ethernet
strongly recommended.

## 1. Base system

```bash
# Debian / Orange Pi OS
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip curl ffmpeg chromium nodejs
# Arch Linux ARM alternative
sudo pacman -Syu --needed git python python-pip curl ffmpeg chromium nodejs
sudo timedatectl set-timezone Asia/Kuala_Lumpur
timedatectl status          # confirm NTP sync: "System clock synchronized: yes"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

Clock accuracy matters — the Q&A clock and all logs trust this machine's time.

## 2. Repo + Python deps

```bash
git clone https://github.com/shuenrui/hackathon-courtroom.git
cd hackathon-courtroom
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
curl -fsSL https://opencode.ai/install | bash
opencode --version
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
set -a; source .env; set +a
./foreman/setup.sh minimax "$QWEN_API_KEY"
```

`setup.sh` creates `~/.hermes-foreman` and verifies the voice path with a live
one-shot. This is a fresh single-mission agent — nothing else runs on this home.

## 5. Enable the voice

In `config.json`: set `foreman_voice.enabled` to `true`.

## 6. Verification checklist (stop at first failure)

1. Sheets read:
   `.venv/bin/python -c "from judging.blackboard import SheetsBlackboard; import json; c=json.load(open('config.json'))['sheets']; print(len(SheetsBlackboard(c['credentials_path'], c['spreadsheet_id']).load_intake()))"`
2. Pipeline stress test (nothing sent): `.venv/bin/python tests/stress_test.py`.
3. Production-path rehearsal on live Discord: `.venv/bin/python -m judging.agents.runner --mock`,
   ping the Foreman with a known rehearsal team; all four bots post through OpenCode.
   Stop the foreground process and delete rehearsal artifacts afterwards.
4. OpenCode agent config: `opencode models opencode-go` includes `opencode-go/minimax-m3`.
5. Only after 1–4 pass: install the services below.

## 7. Run as a service

```bash
sudo cp deploy/judging-agents.service /etc/systemd/system/judging-agents.service
sudo cp deploy/transcribe-watcher.service /etc/systemd/system/transcribe-watcher.service
# Edit User= and /home/oem paths in both units if this machine uses another account.
sudo systemctl daemon-reload
sudo systemctl enable --now judging-agents transcribe-watcher
journalctl -u judging-agents -f
```

Both services auto-start on boot and restart on crashes. The transcript watcher is
optional and never blocks a case. Heartbeats land in #bot_health every 15 min.

## 8. Day-of

- Power + ethernet confirmed before 13:00; keep the laptop charged as cold failover.
- Watch: `journalctl -u judging-agents -f`, `journalctl -u transcribe-watcher -f`, #bot_health, #ops.
- Back up `out/` at 15:00 and 16:30: `tar czf out-$(date +%H%M).tar.gz out/` → copy off-box.
- If the box dies: run the same command on the laptop (see specs/hermes-foreman-install.md §8).

## 9. After the event

Rotate all four Discord bot tokens and the model API key; wipe rehearsal traces.
