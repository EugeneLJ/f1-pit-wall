#!/usr/bin/env python3
"""B5-P1 audit: does the engine's SC/VSC process match its published model?

Exact quantities come from a dynamic program over the published Markov process
(state = GREEN-eligible | cooldown k | inside an event with r segments left); the engine's
seeded schedules (`engine.neutralization_schedule`) are compared against them with 95% CIs.
Usage: scripts/py312 analysis/b5_event_audit.py [--races 100000]
Writes analysis/results/b5_event_audit.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402


def exact(model, n):
    """Per-decision occupancy P(status_i = X), expected starts per race, duration law."""
    # state: ("G",) eligible, ("C", k) cooldown with k green segments still forced, ("E", X, r) inside X with r more segments
    dist = {("G",): 1.0}
    occupancy = []
    starts = defaultdict(float)
    for _ in range(n):
        occ = defaultdict(float)
        nxt = defaultdict(float)
        for state, p in dist.items():
            if state[0] == "E":
                _, status, r = state
                occ[status] += p
                if r > 0:
                    nxt[("E", status, r - 1)] += p
                else:
                    nxt[("C", model["cooldown"]) if model["cooldown"] else ("G",)] += p
                continue
            if state[0] == "C":
                occ["GREEN"] += p
                k = state[1] - 1
                nxt[("C", k) if k > 0 else ("G",)] += p
                continue
            p_sc, p_vsc = model["start"]["SC"], model["start"]["VSC"]
            occ["GREEN"] += p * (1 - p_sc - p_vsc)
            nxt[("G",)] += p * (1 - p_sc - p_vsc)
            for status, ps in (("SC", p_sc), ("VSC", p_vsc)):
                starts[status] += p * ps
                occ[status] += p * ps
                for d, pd in model["duration"][status].items():
                    if d - 1 > 0:
                        nxt[("E", status, d - 2)] += p * ps * pd
                    else:
                        nxt[("C", model["cooldown"]) if model["cooldown"] else ("G",)] += p * ps * pd
        occupancy.append(dict(occ))
        dist = nxt
    return occupancy, dict(starts)


def episodes(schedule):
    out, i = [], 0
    while i < len(schedule):
        if schedule[i] == "GREEN":
            i += 1
            continue
        j = i
        while j < len(schedule) and schedule[j] == schedule[i]:
            j += 1
        out.append((schedule[i], j - i, i))
        i = j
    return out


def ci(p, n):
    se = math.sqrt(max(p * (1 - p), 1e-12) / n)
    return p - 1.96 * se, p + 1.96 * se


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--races", type=int, default=100_000)
    args = parser.parse_args()
    model = coef.race_format(coef.DEFAULT)["neutralization"]
    n = len(coef.race_format(coef.DEFAULT)["decision_laps"])
    occupancy, starts = exact(model, n)
    schedules = [engine.neutralization_schedule(seed, n, model) for seed in range(args.races)]

    rows = []
    sim_occ = [Counter(s[i] for s in schedules) for i in range(n)]
    worst_occ = 0.0
    for i in range(n):
        for status in ("SC", "VSC"):
            p = sim_occ[i][status] / args.races
            lo, hi = ci(p, args.races)
            q = occupancy[i].get(status, 0.0)
            worst_occ = max(worst_occ, abs(p - q) / max(math.sqrt(q * (1 - q) / args.races), 1e-12))
            rows.append({"decision": i + 1, "status": status, "exact": q, "simulated": p, "ci95": [lo, hi],
                         "inside_ci": lo <= q <= hi})
    sim_starts = Counter(e[0] for s in schedules for e in episodes(s))
    per_race = {status: {"exact": starts[status], "simulated": sim_starts[status] / args.races} for status in ("SC", "VSC")}
    durations = {}
    for status in ("SC", "VSC"):
        # Condition on episodes that started early enough for every possible duration to fit in the race;
        # "ended before the race did" would select short episodes (length-biased censoring).
        longest = max(model["duration"][status])
        c = Counter(d for s in schedules for st, d, start in episodes(s) if st == status and start + longest < n)
        total = sum(c.values())
        durations[status] = {d: {"model": p, "simulated": c[d] / total, "ci95": ci(c[d] / total, total)}
                             for d, p in model["duration"][status].items()} | {"n_uncensored": total}
    # conditional continuation after k segments (published hazard) vs simulated
    hazard = {}
    for status in ("SC", "VSC"):
        table = model["duration"][status]
        for k in sorted(table)[:-1]:
            exact_cont = sum(p for d, p in table.items() if d > k) / sum(p for d, p in table.items() if d >= k)
            num = den = 0
            for s in schedules:
                for st, d, start in episodes(s):
                    if st == status and d >= k and start + k < n:
                        den += 1
                        num += d > k
            hazard[f"{status} continues after {k}"] = {"exact": exact_cont, "simulated": num / den, "n": den,
                                                     "ci95": ci(num / den, den)}
    cooldown_ok = all(s2 - (s1 + d1) >= model["cooldown"] for s in schedules
                      for (_, d1, s1), (_, _, s2) in zip(episodes(s), episodes(s)[1:]))
    out = {"races": args.races, "decisions_per_race": n, "model": {k: v for k, v in model.items()},
           "occupancy": rows, "occupancy_max_abs_z": worst_occ,
           "occupancy_inside_ci_share": sum(r["inside_ci"] for r in rows) / len(rows),
           "starts_per_race": per_race, "durations": durations, "continuation": hazard,
           "cooldown_respected_in_all": cooldown_ok,
           "races_with_any_sc": sum(any(x == "SC" for x in s) for s in schedules) / args.races,
           "races_with_any_vsc": sum(any(x == "VSC" for x in s) for s in schedules) / args.races}
    (HERE / "results" / "b5_event_audit.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("starts_per_race", "occupancy_max_abs_z", "occupancy_inside_ci_share",
                                         "cooldown_respected_in_all", "races_with_any_sc", "races_with_any_vsc")}, indent=1))
    for status, table in durations.items():
        print(status, {d: (round(v["model"], 3), round(v["simulated"], 4)) for d, v in table.items() if d != "n_uncensored"},
              "n", table["n_uncensored"])
    for k, v in hazard.items():
        print(k, round(v["exact"], 4), round(v["simulated"], 4), "n", v["n"])


if __name__ == "__main__":
    from _runtime import require_runtime_python
    require_runtime_python()
    main()
