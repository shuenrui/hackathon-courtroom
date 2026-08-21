#!/usr/bin/env bash
# Run on the PI from the repo root: unpacks the migration bundle into place.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TARBALL="${1:?usage: deploy/unbundle.sh <path-to-hackathon-migration.tar.gz>}"

STAGE="$(mktemp -d)"
tar xzf "$TARBALL" -C "$STAGE"
cp "$STAGE/migration/.env" .env
cp "$STAGE/migration/service-account.json" service-account.json
cp -R "$STAGE/migration/knowledge" knowledge
rm -rf "$STAGE"
chmod 600 .env service-account.json

echo "unbundled: .env, service-account.json, knowledge/"
