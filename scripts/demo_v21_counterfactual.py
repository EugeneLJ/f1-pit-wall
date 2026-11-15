#!/usr/bin/env python3
"""Counterfactual check of the demo's SC/VSC decisions, in a fresh interpreter (python3 -I).

Usage: python3 -I demo_v21_counterfactual.py <jobs.pickle> <futures>
<jobs.pickle> holds [(tick_id, race_state, action), ...]. Uses the repository's committed analysis code
(f1-championship/analysis/b21_decisions.py) with only the repository's own paths on sys.path, so no other
`f1pitwall` package already loaded in a caller can be picked up. Prints {tick_id: evaluation} as JSON.
"""

import json
import pickle
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1] / "f1-championship"


def main() -> int:
    jobs = pickle.loads(Path(sys.argv[1]).read_bytes())
    futures = int(sys.argv[2])
    sys.path[:0] = [str(TASK / "src"), str(TASK), str(TASK / "analysis")]
    import b21_decisions as B
    out = {tick: B.evaluate({"tick_id": tick, "race": race, "action": action}, futures) for tick, race, action in jobs}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
