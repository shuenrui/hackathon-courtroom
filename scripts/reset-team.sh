#!/usr/bin/env bash
# Flexibly remove a team's marking so they can be re-judged during the hack.
# Usage: ./scripts/reset-team.sh 1  (or 5, 12, etc.)
set -e
TEAM="${1:?usage: ./scripts/reset-team.sh <team_number>}"
python3 "$(dirname "$0")/reset_team.py" "$TEAM"
echo "Restarting judging service to pick up cleared state..."
sudo systemctl restart judging
sleep 3
systemctl is-active judging
journalctl -u judging --no-pager -n 15 | tail -n 15
