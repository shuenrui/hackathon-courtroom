#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/../.venv/bin/python" "$(dirname "$0")/browse.py" "$@"
