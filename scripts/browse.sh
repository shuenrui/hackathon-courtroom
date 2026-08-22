#!/usr/bin/env bash
# Render a URL with headless Chromium (handles JavaScript SPAs that curl can't).
# Usage: scripts/browse.sh <url> [text-only]
set -euo pipefail
URL="${1:?usage: browse.sh <url> [--text]}"
MODE="${2:-}"
OUT=$(timeout 45 chromium --headless=new --no-sandbox --disable-gpu \
  --virtual-time-budget=8000 --dump-dom "$URL" 2>/dev/null)
if [ "$MODE" == "--text" ] || [ "$MODE" == "--text-only" ]; then
  # strip tags -> readable text
  echo "$OUT" | sed -e 's/<script[^>]*>[^<]*<\/script>//g' -e 's/<style[^>]*>[^<]*<\/style>//g' \
    | sed -e 's/<[^>]*>/ /g' | tr -s ' \n' ' \n' | head -c 6000
else
  echo "$OUT" | head -c 12000
fi
