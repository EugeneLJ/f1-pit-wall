#!/bin/bash
# Reference run: the public-information rollout player (reference.py), through f1ctl like an agent.
# F1_SOLUTION=baseline runs the simple public heuristic (play.py) instead.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "${F1_SOLUTION:-reference}" = "baseline" ]; then
  exec python3 "$HERE/play.py"
fi
exec python3 "$HERE/reference.py"
