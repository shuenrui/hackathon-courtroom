#!/usr/bin/env bash
# Provision the dedicated Foreman Hermes home on a new device.
#
# Usage:
#   ./foreman/setup.sh minimax <zen-api-key>
#   ./foreman/setup.sh qwen <aliyun-maas-api-key> [base-url]
#
# Creates $HERMES_HOME (default ~/.hermes-foreman) with SOUL.md, AGENTS.md,
# and a model config, then verifies the voice path with a one-shot call.
set -euo pipefail

PRESET="${1:?usage: setup.sh <minimax|qwen> <api-key> [base-url]}"
API_KEY="${2:?missing api key}"
FOREMAN_HOME="${HERMES_HOME:-$HOME/.hermes-foreman}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$PRESET" in
  minimax)
    MODEL="minimax-m3"
    BASE_URL="https://opencode.ai/zen/go/v1"
    ;;
  qwen)
    MODEL="qwen3.8-max-preview"
    BASE_URL="${3:-https://ws-728xa8i2fpjzxtr4.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1}"
    ;;
  *)
    echo "unknown preset: $PRESET (use minimax or qwen)" >&2
    exit 1
    ;;
esac

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes binary not found — install Hermes Agent first, then re-run." >&2
  exit 1
fi

mkdir -p "$FOREMAN_HOME"
cp "$SCRIPT_DIR/SOUL.md" "$FOREMAN_HOME/SOUL.md"
cp "$SCRIPT_DIR/AGENTS.md" "$FOREMAN_HOME/AGENTS.md"

cat > "$FOREMAN_HOME/config.yaml" <<EOF
model:
  default: $MODEL
  provider: custom
  base_url: $BASE_URL
  api_key: $API_KEY
  providers:
    custom:
      models: '["$MODEL"]'
agent:
  max_turns: 3
EOF
chmod 600 "$FOREMAN_HOME/config.yaml"

echo "foreman home: $FOREMAN_HOME (preset=$PRESET, model=$MODEL)"
echo "verifying voice path..."
HERMES_HOME="$FOREMAN_HOME" hermes -z "VOICE REQUEST event=heartbeat context: bench check at setup. Write the line." --cli --safe-mode
echo
echo "OK — now set foreman_voice.enabled=true (or FOREMAN_VOICE=1) in the judging repo."
