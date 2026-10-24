#!/usr/bin/env bash
set -euo pipefail
NAWA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$NAWA_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TZ="${TZ:-Asia/Riyadh}"
exec /usr/bin/python3 -m nawa "$@"
