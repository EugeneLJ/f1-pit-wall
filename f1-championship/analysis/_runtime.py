"""Guard: replays and analyses must run on the image interpreter (Python 3.12).

Python 3.12 changed float sum() to compensated summation, so an older interpreter can
produce slightly different replayed observations (and fail journal hash checks).
Override only for exploratory work: F1_ALLOW_ANY_PYTHON=1.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from f1pitwall.version import RUNTIME_PYTHON  # noqa: E402


def require_runtime_python() -> None:
    if tuple(sys.version_info[:2]) == tuple(RUNTIME_PYTHON) or os.environ.get("F1_ALLOW_ANY_PYTHON") == "1":
        return
    wanted = ".".join(map(str, RUNTIME_PYTHON))
    raise SystemExit(f"This tool replays the simulator and must run on Python {wanted} (found "
                     f"{sys.version.split()[0]}). Use scripts/py312, or set F1_ALLOW_ANY_PYTHON=1 "
                     f"for non-authoritative exploration.")
