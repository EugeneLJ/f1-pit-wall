#!/usr/bin/env python3
"""Copy the canonical f1pitwall package into the sim image, the verifier image and the
reference solution.

Docker build contexts cannot reach outside their directory, so the sidecar and
the verifier each need a copy. `src/f1pitwall` is the only place to edit;
devtests/test_sync.py fails if any copy drifts.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
SOURCE = TASK / "src" / "f1pitwall"
# solution/lib is the reference player's model of the published rules (never in the agent image).
TARGETS = (TASK / "environment" / "sim" / "f1pitwall", TASK / "tests" / "f1pitwall",
           TASK / "solution" / "lib" / "f1pitwall")


def files(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def main() -> int:
    for target in TARGETS:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("__pycache__"))
        print(f"synced {target.relative_to(TASK)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
