#!/usr/bin/env python3
"""B8: held-out evaluation of the rival-strategy-reversal and swap/give-back scenario families,
reusing the B6 jobs unchanged (analysis/b6_eval.py) on fresh seeds never used in B6 (300-311).
Usage: scripts/py312 analysis/b8_families.py [--seeds 12] [--futures 12]  -> results/b8_families_heldout.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import b6_eval as E  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--futures", type=int, default=12)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    seeds = list(range(300, 300 + args.seeds))
    with mp.Pool(args.workers) as pool:
        br = [r for part in pool.map(E.best_response_job, [(s, args.futures) for s in seeds]) for r in part]
        ov = [r for part in pool.map(E.order_value_job, [(s, args.futures) for s in seeds]) for r in part]
    rivals = [r for r in E.RIVALS if r != "baseline"]
    best_response = {v: {"best_action_changes": round(st.mean(s["best"][v] != s["best"]["baseline"] for s in br), 3),
                         "mean_loss_if_assume_baseline": round(st.mean(s["loss_if_assume_baseline_rival"][v] for s in br), 3),
                         "share_loss_gt_0_5": round(st.mean(s["loss_if_assume_baseline_rival"][v] > 0.5 for s in br), 3),
                         "no_change_states": sum(1 for s in br if s["best"][v] == s["best"]["baseline"])}
                     for v in rivals}
    best_order = Counter(max(s["values"], key=lambda k: (s["values"][k], k == "RACE")) for s in ov)
    gaps = {o: [s["values"][o] - s["values"]["RACE"] for s in ov] for o in ("HOLD", "SWAP", "DEFENSIVE_BUFFER")}
    gb = [s["give_back"] for s in ov if s["give_back"]]
    gdiff = [g["team_points"]["REQUEST_GIVE_BACK"] - g["team_points"]["KEEP_ORDER"] for g in gb]
    out = {"seeds": seeds, "futures": args.futures, "states_best_response": len(br), "states_orders": len(ov),
           "best_response": best_response,
           "team_orders": {"best_order_counts": dict(best_order),
                           "vs_RACE": {o: {"mean": round(st.mean(v), 3), "share_gt_0_25": round(st.mean(x > 0.25 for x in v), 3),
                                           "share_lt_minus_0_25": round(st.mean(x < -0.25 for x in v), 3),
                                           "near_tie_share": round(st.mean(abs(x) <= 0.25 for x in v), 3)}
                                       for o, v in gaps.items()} if ov else {}},
           "give_back": {"states": len(gb), "mean_team_points_gain": round(st.mean(gdiff), 3) if gdiff else None,
                         "share_gt_0_25": round(st.mean(x > 0.25 for x in gdiff), 3) if gdiff else None,
                         "share_lt_minus_0_25": round(st.mean(x < -0.25 for x in gdiff), 3) if gdiff else None,
                         "max": round(max(gdiff), 3) if gdiff else None,
                         "driver_mean_position": [g["driver_mean_position"] for g in gb][:10]}}
    (HERE / "results" / "b8_families_heldout.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "give_back"} | {"give_back": {k: v for k, v in out["give_back"].items() if k != "driver_mean_position"}}, indent=1))


if __name__ == "__main__":
    main()
