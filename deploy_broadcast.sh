#!/bin/sh
# Deploy the hackathon broadcast site to ifhost.
# https://hackathon-broadcast.host.impossibuild.ai
#
# Full push of the static broadcast tree. Use for:
#   - initial deploy
#   - recovery after a VM wipe
#   - shipping player/CSS changes
# Per-case incremental uploads are handled by scripts/broadcast_upload.py.
#
# Usage: ./deploy_broadcast.sh   (run from anywhere)
set -e
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"

APP=hackathon-broadcast
URL=https://hackathon-broadcast.host.impossibuild.ai

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

echo "-> Staging broadcast files (playlist-driven)..."
cp broadcast/index.html broadcast/styles.css broadcast/app.js "$STAGE"/
cp -R broadcast/assets "$STAGE"/assets
python3 - "$STAGE" <<'EOF'
import json, shutil, sys
from pathlib import Path
stage = Path(sys.argv[1])
b = Path("broadcast")
(stage / "segments").mkdir(exist_ok=True)
(stage / "sources" / "audio").mkdir(parents=True, exist_ok=True)
playlist = json.loads((b / "segments" / "playlist.json").read_text())
shutil.copy(b / "segments" / "playlist.json", stage / "segments" / "playlist.json")
n_audio = 0
for f in playlist["segments"]:
    seg_path = b / "segments" / f
    shutil.copy(seg_path, stage / "segments" / f)
    for line in json.loads(seg_path.read_text())["lines"]:
        rel = line.get("audio")
        if rel and (b / rel).exists():
            shutil.copy(b / rel, stage / "sources" / "audio" / Path(rel).name)
            n_audio += 1
print(f"   staged {len(playlist['segments'])} segments + {n_audio} audio clips")
EOF

echo "-> Pushing to ifhost..."
ifhost machines push --app "$APP" "$STAGE" --to /app --yes-replace

echo "-> Fixing permissions..."
ifhost machines exec --app "$APP" -- sh -c "chmod -R a+rX /app" >/dev/null

echo "-> Ensuring nginx is running..."
ifhost machines write broadcast_host/nginx.conf --to /etc/nginx/conf.d/broadcast.conf --app "$APP" >/dev/null
ifhost machines exec --app "$APP" -- sh -c "kill -0 \$(cat /run/nginx.pid) 2>/dev/null && /usr/sbin/nginx -s reload || /usr/sbin/nginx" >/dev/null

echo "-> Verifying..."
curl -sS -o /dev/null -w "hackathon-broadcast -> HTTP %{http_code}\n" --max-time 30 "$URL/"
echo "Done. Live at $URL"
