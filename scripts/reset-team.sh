#!/usr/bin/env bash
# Flexibly remove a team's marking so they can be re-judged during the hack.
# Usage: ./scripts/reset-team.sh 1  (or 5, 12, etc.)
set -e
TEAM="${1:?usage: ./scripts/reset-team.sh <team_number>}"
"$(dirname "$0")/../.venv/bin/python" "$(dirname "$0")/reset_team.py" "$TEAM"
echo "Restarting living-agent judging service to pick up cleared state..."
sudo systemctl restart judging-agents
sleep 3
systemctl is-active judging-agents
journalctl -u judging-agents --no-pager -n 15
