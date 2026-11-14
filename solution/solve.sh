#!/bin/bash
set -euo pipefail
mkdir -p /app/submission
printf '%s\n' '{"driver_a":"PIT","driver_b":"STAY"}' > /app/submission/action.json
