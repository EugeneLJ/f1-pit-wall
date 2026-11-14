#!/usr/bin/env python3
"""Summarize analysis/results/track_a_p1d.json into Markdown (stdout)."""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ("always_use", "rival_rule", "greedy", "mpc:2", "mpc:3", "exact3", "mpc:5", "mpc:8")
NAMES = {"always_use": "Always USE", "rival_rule": "Replacement rule (wear ≥ 0.65)", "greedy": "Greedy (H=1)",
         "mpc:2": "Planner H=2", "mpc:3": "Planner H=3", "exact3": "Exact 3-race DP, receding",
         "mpc:5": "Planner H=5", "mpc:8": "Planner H=8 (reference)"}
REF = "mpc:8"


def stats(values):
    values = list(values)
    return {"mean": st.mean(values), "median": st.median(values), "max": max(values), "min": min(values)}


def fmt(s):
    return f"{s['mean']:.2f} / {s['median']:.2f} / {s['max']:.2f}"


def allocation(path):
    reps = [(step["race"], r) for step in path for r in step["replacements"]]
    drops = [(step["race"], d, n) for step in path for d, n in step["grid_drops"].items() if n]
    return {"replacements": len(reps), "first_replacement_race": (min(r for r, _ in reps) + 1) if reps else None,
            "early_replacements": sum(1 for r, _ in reps if r < 4), "penalty_races": len({r for r, _, _ in drops}),
            "grid_places": sum(n for *_, n in drops),
            "by_driver": {d: sum(1 for _, x in reps if x.startswith(d)) for d in ("Apex A", "Apex B")}}


def main(path=HERE / "results" / "track_a_p1d.json"):
    data = json.loads(Path(path).read_text())
    main_runs = {(r["scenario"], r["policy"]): r for r in data["seasons"] if r["variant"] == "main"}
    ids = sorted({s for s, _ in main_runs})
    ref = {i: main_runs[(i, REF)] for i in ids}
    out = [f"Scenarios: {len(ids)}; budget per decision: {data['budget']['race_evaluations_per_decision']} race "
           f"evaluations and {data['budget']['plan_evaluation_cap']} plan rollouts; wall time {data['wall_seconds']:.0f}s", ""]

    out += ["### Full-season expected Apex points (exact expectation of each executed policy)", "",
            "| Policy | Mean pts | Regret vs H=8 reference: mean / median / max | Scenarios regret > 1 pt | Better than reference | Race evals per decision (mean) | Seconds per season (mean) |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for policy in ORDER:
        runs = [main_runs[(i, policy)] for i in ids]
        regrets = [ref[i]["expected_points"] - main_runs[(i, policy)]["expected_points"] for i in ids]
        evals = [step["search"]["evaluations"] for r in runs for step in r["path"] if "search" in step]
        out.append(f"| {NAMES[policy]} | {st.mean(r['expected_points'] for r in runs):.2f} | {fmt(stats(regrets))} | "
                   f"{sum(x > 1 for x in regrets)}/{len(ids)} | {sum(x < -1e-6 for x in regrets)}/{len(ids)} | "
                   f"{(st.mean(evals) if evals else 0):.0f} | {st.mean(r['seconds'] for r in runs):.1f} |")
    out.append("")

    sens = {r["scenario"]: r for r in data["seasons"] if r["variant"] == "budget_x2"}
    if sens:
        diffs = [sens[i]["expected_points"] - ref[i]["expected_points"] for i in sens]
        out += [f"Budget sensitivity (H=8 with 2× budget, {len(diffs)} scenarios): Δ points mean {st.mean(diffs):+.3f}, "
                f"max {max(diffs):+.3f}.", ""]
    h3 = [main_runs[(i, "exact3")]["expected_points"] - main_runs[(i, "mpc:3")]["expected_points"] for i in ids]
    out += [f"Search quality at H=3 (exact receding DP minus budgeted search): mean {st.mean(h3):+.3f}, "
            f"max {max(h3):+.3f}, min {min(h3):+.3f}.", ""]

    out += ["### Early (races 1–4) vs late (races 5–8) expected points relative to the reference", "",
            "| Policy | Early Δ mean (median) | Late Δ mean (median) | Scenarios ahead early but behind overall |",
            "|---|---:|---:|---:|"]
    for policy in ORDER:
        early, late, flip = [], [], 0
        for i in ids:
            p, r = main_runs[(i, policy)]["path"], ref[i]["path"]
            e = sum(a["expected_points"] - b["expected_points"] for a, b in zip(p[:4], r[:4]))
            l = sum(a["expected_points"] - b["expected_points"] for a, b in zip(p[4:], r[4:]))  # noqa: E741
            early.append(e)
            late.append(l)
            flip += e > 0.1 and e + l < -0.1
        out.append(f"| {NAMES[policy]} | {st.mean(early):+.2f} ({st.median(early):+.2f}) | "
                   f"{st.mean(late):+.2f} ({st.median(late):+.2f}) | {flip}/{len(ids)} |")
    out.append("")

    out += ["### Component allocation and replacement timing (means over scenarios)", "",
            "| Policy | Replacements | First replacement race | Replacements in races 1–4 | Races with a grid drop | Grid places taken | A / B replacements |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for policy in ORDER:
        allocs = [allocation(main_runs[(i, policy)]["path"]) for i in ids]
        firsts = [a["first_replacement_race"] for a in allocs if a["first_replacement_race"]]
        out.append(f"| {NAMES[policy]} | {st.mean(a['replacements'] for a in allocs):.2f} | "
                   f"{(st.mean(firsts) if firsts else float('nan')):.2f} | {st.mean(a['early_replacements'] for a in allocs):.2f} | "
                   f"{st.mean(a['penalty_races'] for a in allocs):.2f} | {st.mean(a['grid_places'] for a in allocs):.2f} | "
                   f"{st.mean(a['by_driver']['Apex A'] for a in allocs):.2f} / {st.mean(a['by_driver']['Apex B'] for a in allocs):.2f} |")
    out.append("")

    out += ["### Seed spread (realized points on 40 shared seeds per scenario; same seeds for every policy)", "",
            "| Policy | Mean realized | Paired diff vs reference: mean (sd across seeds, mean over scenarios) | Seeds where policy beats reference |",
            "|---|---:|---:|---:|"]
    for policy in ORDER:
        means, sds, wins, total = [], [], 0, 0
        for i in ids:
            pr = main_runs[(i, policy)]["realized"]
            rr = ref[i]["realized"]
            diffs = [sum(pr[s]) - sum(rr[s]) for s in rr]
            means.append(st.mean(sum(pr[s]) for s in pr))
            sds.append(st.pstdev(diffs))
            wins += sum(d > 0 for d in diffs)
            total += len(diffs)
        diff_mean = st.mean(st.mean(sum(main_runs[(i, policy)]["realized"][s]) - sum(ref[i]["realized"][s])
                                    for s in ref[i]["realized"]) for i in ids)
        out.append(f"| {NAMES[policy]} | {st.mean(means):.2f} | {diff_mean:+.2f} ({st.mean(sds):.2f}) | {wins}/{total} |")
    out.append("")

    per_scen = sorted(((ref[i]["expected_points"] - main_runs[(i, "greedy")]["expected_points"], i) for i in ids))
    out += ["### Per-scenario regret (expected points)", "",
            "| Scenario | Reference pts | Greedy regret | H=3 regret | Replacement-rule regret | Always-USE regret |",
            "|---|---:|---:|---:|---:|---:|"]
    for i in ids:
        r = ref[i]["expected_points"]
        out.append(f"| {i} | {r:.2f} | " + " | ".join(
            f"{r - main_runs[(i, p)]['expected_points']:.2f}" for p in ("greedy", "mpc:3", "rival_rule", "always_use")) + " |")
    out.append("")

    variants = {(r["scenario"], r["variant"]): r for r in data["seasons"] if r["variant"] not in ("main", "budget_x2")}
    cross = {(r["scenario"], r["variant"]): r for r in data["cross"]}
    pair_ids = sorted({s for s, v in variants if v == "late_high_speed"})
    if pair_ids:
        def early(r):
            return [step["option"] for step in r["path"][:3]]
        dec = sum(early(variants[(i, "late_high_speed")]) != early(variants[(i, "late_street")]) for i in pair_ids)
        ctl = sum(early(variants[(i, "control")]) != early(main_runs[(i, REF)]) for i in pair_ids)
        def loss(world, other):
            return [variants[(i, world)]["expected_points"] - cross[(i, f"cross:{world}<-{other}")]["expected_points"]
                    for i in pair_ids]
        hs, stt = loss("late_high_speed", "late_street"), loss("late_street", "late_high_speed")
        ct = [variants[(i, "control")]["expected_points"] - cross[(i, "cross:control<-main")]["expected_points"]
              for i in pair_ids]
        g = [variants[(i, w)]["expected_points"] - variants[(i, f"{w}:greedy")]["expected_points"]
             for i in pair_ids for w in ("late_high_speed", "late_street")]
        out += ["### Do races 6–8 change races 1–3? (same races 1–5; races 6–8 swapped)", "",
                "| Test | Reference's race 1–3 decisions differ | Loss from playing the other world's race 1–3 decisions (mean / median / max) |",
                "|---|---:|---:|",
                f"| Decision pair, high-speed world | {dec}/{len(pair_ids)} | {fmt(stats(hs))} |",
                f"| Decision pair, street world | (same pairs) | {fmt(stats(stt))} |",
                f"| Control (±0.03 jitter of races 6–8) | {ctl}/{len(pair_ids)} | {fmt(stats(ct))} |",
                f"| Greedy regret inside the pair worlds | — | {fmt(stats(g))} |", ""]
        out += ["| Scenario | High-speed world races 1–3 | Street world races 1–3 |", "|---|---|---|"]
        for i in pair_ids:
            a, b = early(variants[(i, "late_high_speed")]), early(variants[(i, "late_street")])
            if a != b:
                out.append(f"| {i} | {' → '.join(a)} | {' → '.join(b)} |")
        out.append("")

    if data.get("hindsight"):
        out += ["### Privileged hindsight (budgeted open-loop search with realized events; a lower bound on the true hindsight optimum)", "",
                "| Scenario | Seed | Hindsight lower bound | Reference realized | Greedy realized |", "|---|---:|---:|---:|---:|"]
        for h in data["hindsight"]:
            i, s = h["scenario"], str(h["seed"])
            rr = ref[i]["realized"].get(s)
            gr = main_runs[(i, "greedy")]["realized"].get(s)
            out.append(f"| {i} | {s} | {h['hindsight_lower_bound']:.0f} | "
                       f"{sum(rr) if rr else '—'} | {sum(gr) if gr else '—'} |")
        out.append("")

    median_case = per_scen[len(per_scen) // 2][1]
    worst_case = per_scen[-1][1]
    for label, case in (("median", median_case), ("worst", worst_case)):
        g, r = main_runs[(case, "greedy")]["path"], ref[case]["path"]
        out += [f"### Failure trace — {label} greedy-regret scenario {case}", "",
                "| Race | Track | Greedy replaces | Greedy drops | Greedy E[pts] | Reference replaces | Reference drops | Reference E[pts] |",
                "|---:|---|---|---|---:|---|---|---:|"]
        for a, b in zip(g, r):
            drop = lambda s: ", ".join(f"{d[-1]}:{n}" for d, n in s["grid_drops"].items() if n) or "—"  # noqa: E731
            out.append(f"| {a['race'] + 1} | {a['archetype']} | {', '.join(x.replace('Apex ', '') for x in a['replacements']) or '—'} | "
                       f"{drop(a)} | {a['expected_points']:.2f} | {', '.join(x.replace('Apex ', '') for x in b['replacements']) or '—'} | "
                       f"{drop(b)} | {b['expected_points']:.2f} |")
        out += [f"| | **Total** | | | **{sum(s['expected_points'] for s in g):.2f}** | | | **{sum(s['expected_points'] for s in r):.2f}** |", ""]
    print("\n".join(out))


if __name__ == "__main__":
    main(*sys.argv[1:])
