#!/bin/bash
# Reference run for the integrated task: the public-information rollout reference (reference_v21.py).
# F1_SOLUTION=coordinator runs the published scripted coordinator policy instead.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "${F1_SOLUTION:-reference}" = "coordinator" ]; then
  exec python3 "$HERE/play_integrated.py"
fi
exec python3 "$HERE/reference_v21.py"
