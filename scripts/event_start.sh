#!/bin/sh
# Event-day startup: one command to arm the whole broadcast system.
# Safe to run repeatedly — it only starts what's not already running.
#
# Usage: ./scripts/event_start.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p out

echo "== hackathon broadcast: event startup =="

if curl -s -o /dev/null --max-time 8 https://hackathon-broadcast.host.impossibuild.ai/; then
  echo "[ok] internet reachable (public site up)"
else
  echo "[!!] NO INTERNET — cases can't be voiced or uploaded; screen fallback = localhost only"
fi

if lsof -nP -iTCP:8321 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ok] local server already on :8321"
else
  nohup python3 -m http.server 8321 --directory broadcast >> out/http_server.log 2>&1 &
  sleep 1
  echo "[ok] local server started on :8321"
fi

if pgrep -f broadcast_watch.py >/dev/null; then
  echo "[ok] watcher already running"
else
  nohup python3 -u scripts/broadcast_watch.py --interval 60 >> out/broadcast_watch.log 2>&1 &
  sleep 1
  echo "[ok] watcher started (60s poll)"
fi

if pgrep -x caffeinate >/dev/null; then
  echo "[ok] caffeinate already holding sleep"
else
  nohup caffeinate -dims >/dev/null 2>&1 &
  echo "[ok] caffeinate armed — laptop will not idle-sleep"
fi

echo ""
echo "Public screen:  https://hackathon-broadcast.host.impossibuild.ai"
echo "Local fallback: http://localhost:8321"
echo "Live log:       tail -f out/broadcast_watch.log"
