#!/bin/bash
set -uo pipefail

mkdir -p /logs/verifier
printf '0.00000000\n' > /logs/verifier/reward.txt
python3 /tests/grade_integrated.py || true

python3 - <<'PY'
import math
from pathlib import Path
path = Path("/logs/verifier/reward.txt")
try:
    value = float(path.read_text(encoding="utf-8").strip())
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("reward outside [0, 1]")
except Exception:
    value = 0.0
path.write_text(f"{value:.8f}\n", encoding="utf-8")
PY
