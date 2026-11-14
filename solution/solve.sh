#!/bin/bash
set -euo pipefail
mkdir -p /app/submission
cat > /app/submission/actions.json <<'JSON'
{"version":2,"actions":[{"driver_a":"PIT","driver_b":"STAY"},{"driver_a":"STAY","driver_b":"STAY"},{"driver_a":"STAY","driver_b":"PIT"}]}
JSON
