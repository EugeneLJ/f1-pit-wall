#!/bin/bash
# P0 oracle: a simple legal heuristic that plays through f1ctl like an agent.
# Not the reference planner (that is P2).
set -euo pipefail
python3 "$(dirname "$0")/play.py"
