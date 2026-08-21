#!/usr/bin/env bash
# Run on the LAPTOP: builds hackathon-migration.tar.gz for secure transfer to the Pi.
# Bundles everything git clone will NOT bring: .env, service-account.json, knowledge/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

for f in .env service-account.json knowledge; do
  [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

STAGE="$(mktemp -d)/migration"
mkdir -p "$STAGE"
cp .env "$STAGE/.env"
cp service-account.json "$STAGE/service-account.json"
cp -R knowledge "$STAGE/knowledge"

OUT="hackathon-migration.tar.gz"
tar czf "$OUT" -C "$(dirname "$STAGE")" migration
rm -rf "$(dirname "$STAGE")"
chmod 600 "$OUT"

echo "bundle ready: $(pwd)/$OUT"
echo "transfer securely (scp / AirDrop / encrypted), then on the Pi run: deploy/unbundle.sh <path-to-tarball>"
