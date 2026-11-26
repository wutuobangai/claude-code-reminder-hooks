#!/usr/bin/env bash
# Standalone configurable reminder; MIT.
set -euo pipefail
HOOK_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HOOK_DIR/reminders.py" discussion
