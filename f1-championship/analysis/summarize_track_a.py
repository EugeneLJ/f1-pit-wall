#!/usr/bin/env python3
"""Summarize analysis/results/track_a_p1.json into Markdown tables (stdout)."""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICIES = ("always_use", "rival_rule", "greedy")


def mean(values):
    values = list(values)
    return st.mean(values) if values else float("nan")


def main(path=HERE / "results" / "track_a_p1.json"):
    data = json.loads(Path(path).read_text())
    evals = data["evals"]
    default = {e["scenario"]: e for e in evals if e["tag"] == "default"}
    ids = sorted(default)
    lines = [f"Scenarios: {len(ids)} (generator seed {data['generator_seed']}); wall time {data['wall_seconds']:.0f}s", ""]

    lines += ["### Reduced-season (final 3 races) exact expected Apex points, default coefficients", "",
              "| Policy | Mean expected pts | Mean regret vs fair optimum | Scenarios with regret > 1 pt | Max regret |",
              "|---|---:|---:|---:|---:|"]
    lines.append(f"| fair optimum (DP) | {mean(default[i]['optimal'] for i in ids):.2f} | 0 | - | - |")
    for policy in POLICIES:
        regrets = [default[i]["optimal"] - default[i]["policies"][policy]["value"] for i in ids]
        lines.append(f"| {policy} | {mean(default[i]['policies'][policy]['value'] for i in ids):.2f} | "
                     f"{mean(regrets):.2f} | {sum(r > 1 for r in regrets)}/{len(ids)} | {max(regrets):.2f} |")
    lines.append("")

    lines += ["### First-race decision per scenario (optimal vs greedy)", "",
              "| Scenario | Early habit | Optimal first | Greedy first | Greedy regret |", "|---|---|---|---|---:|"]
    habits = {s["id"]: s["early_habit"] for s in data["scenarios"]}
    for i in ids:
        e = default[i]
        lines.append(f"| {i} | {habits[i]} | {e['optimal_first']} | {e['policies']['greedy']['first']} | "
                     f"{e['optimal'] - e['policies']['greedy']['value']:.2f} |")
    lines.append("")

    lines += ["### Mechanic ablations (levels b and c)", "",
              "Each row switches one mechanic off and re-solves every scenario (history regenerated under the same rules).", "",
              "| Mechanic off | Δ optimum (pts) | Greedy regret on → off | Always-USE regret on → off | Rival-rule regret on → off | Optimal first decision changes |",
              "|---|---:|---:|---:|---:|---:|"]
    by_mech = defaultdict(dict)
    for e in evals:
        if e["tag"] == "ablation":
            by_mech[e["mechanic"]][e["scenario"]] = e
    for mech in sorted(by_mech):
        rows = by_mech[mech]
        common = [i for i in ids if i in rows]
        reg = lambda src, i, p: src[i]["optimal"] - src[i]["policies"][p]["value"]  # noqa: E731
        cells = [f"{mean(reg(default, i, p) for i in common):.2f} → {mean(reg(rows, i, p) for i in common):.2f}"
                 for p in ("greedy", "always_use", "rival_rule")]
        changed = sum(rows[i]["optimal_first"] != default[i]["optimal_first"] for i in common)
        lines.append(f"| {mech} | {mean(rows[i]['optimal'] - default[i]['optimal'] for i in common):+.2f} | "
                     + " | ".join(cells) + f" | {changed}/{len(common)} |")
    lines.append("")

    variants = defaultdict(dict)
    for e in evals:
        if e["tag"] in ("late_high_speed", "late_street", "control_b"):
            variants[e["tag"]][e["scenario"].rsplit("-", 1)[0]] = e
    hs, stt, cb = variants["late_high_speed"], variants["late_street"], variants["control_b"]
    common = [i for i in ids if i in hs and i in stt and i in cb]
    dec = sum(hs[i]["optimal_first"] != stt[i]["optimal_first"] for i in common)
    ctl = sum(cb[i]["optimal_first"] != default[i]["optimal_first"] for i in common)
    lines += ["### Counterfactual pairs (same history and next race; only races 7-8 differ)", "",
              "| Pair | Scenarios where optimal race-6 decision differs | Mean |Δ optimum| |", "|---|---:|---:|",
              f"| decision pair: late high-speed ×2 vs late street ×2 | {dec}/{len(common)} | "
              f"{mean(abs(hs[i]['optimal'] - stt[i]['optimal']) for i in common):.2f} |",
              f"| control pair: original late races vs ±0.03 jitter | {ctl}/{len(common)} | "
              f"{mean(abs(cb[i]['optimal'] - default[i]['optimal']) for i in common):.2f} |", ""]
    lines += ["| Scenario | Optimal first (late high-speed) | Optimal first (late street) | Greedy first (both) |",
              "|---|---|---|---|"]
    for i in common:
        if hs[i]["optimal_first"] != stt[i]["optimal_first"]:
            lines.append(f"| {i} | {hs[i]['optimal_first']} | {stt[i]['optimal_first']} | "
                         f"{hs[i]['policies']['greedy']['first']} / {stt[i]['policies']['greedy']['first']} |")
    lines.append("")

    lines += ["### Hindsight diagnostic (realized points on fixed seeds)", "",
              "| Scenario | Seed | Hindsight bound | Fair optimum (realized) | Greedy | Always-USE | Rival rule |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for h in sorted(data["hindsight"], key=lambda x: (x["scenario"], x["seed"])):
        r = h["realized"]
        lines.append(f"| {h['scenario']} | {h['seed']} | {h['hindsight']:.0f} | {r['optimal']} | {r['greedy']} | "
                     f"{r['always_use']} | {r['rival_rule']} |")
    gaps = [h["hindsight"] - h["realized"]["optimal"] for h in data["hindsight"]]
    lines += ["", f"Mean hindsight gap of the fair optimum: {mean(gaps):.2f} pts (n={len(gaps)}).", ""]

    lines += ["### Solver vs live engine (Monte Carlo through the same seeded draws)", "",
              "| Scenario | Policy | Exact expectation | MC mean ± s.e. (n) |", "|---|---|---:|---:|"]
    for m in data["monte_carlo"]:
        for policy in ("optimal", "greedy"):
            v = m[policy]
            lines.append(f"| {m['scenario']} | {policy} | {v['exact']:.2f} | {v['mc_mean']:.2f} ± {v['mc_se']:.2f} ({v['n']}) |")
    lines.append("")

    grid = data.get("penalty_cost_grid", [])
    if grid:
        lines += ["### Expected cost of a 4-place ICE grid drop (pts), stress 0.5", "",
                  "| Archetype | Driver | d=0.1 | 0.3 | 0.5 | 0.7 | 0.9 |", "|---|---|---:|---:|---:|---:|---:|"]
        rows = defaultdict(dict)
        for g in grid:
            rows[g["archetype"]][g["difficulty"]] = g
        for arch in sorted(rows):
            for driver in ("Apex A", "Apex B"):
                lines.append(f"| {arch} | {driver} | " + " | ".join(
                    f"{rows[arch][d][driver]:.2f}" for d in sorted(rows[arch])) + " |")
        lines.append("")
    print("\n".join(lines))


if __name__ == "__main__":
    main(*sys.argv[1:])
