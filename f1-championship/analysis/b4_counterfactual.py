#!/usr/bin/env python3
"""B4 analysis: does an SC/VSC change the value of replanning?

Fair in-race reference ("replan"): at every decision, score all joint legal actions by
playing them now and the public baseline afterwards over FUTURES public futures drawn from
the published SC/VSC model conditioned only on statuses observed so far; take the best.
It never reads the true future. One-step lookahead: an approximate reference, not optimal.

For each race start state (24 calendars x races 1, 4, 7, public-rule history):
  no_event   : every decision GREEN
  SC@k, VSC@k: the same race with a 2-segment SC or a 1-segment VSC starting at decision k
  random_j   : representative paths drawn from the public model (public seed)
Policies evaluated on each fixed path (exact retirement expectation at the finish):
  replan       the fair reference reacting to observations
  no_replan    the reference's own no-event plan replayed open-loop (ignores the event)
  sc_reactive  the no-event plan, but both cars stop at the first SC/VSC decision
               (compound by laps remaining, two-compound aware) -- a "always pit under SC" rule
  baseline     the public heuristic
Usage: python3 analysis/b4_counterfactual.py [--scenarios 24] [--workers 10]
Writes analysis/results/b4_counterfactual.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import track_a_solver as ts  # noqa: E402
from f1pitwall import engine  # noqa: E402

RACE_INDICES = (0, 3, 6)
EVENT_DECISIONS = (2, 4, 6, 8, 10, 12)
FUTURES = 32
RANDOM_PATHS = 4
REPLAN_THRESHOLD = 0.5


def rollout_action(node, futures=FUTURES):
    legal = engine.legal_actions(node)
    paths = ts.public_futures(node, futures, "rollout")
    best, best_value = None, float("-inf")
    for a in legal:
        for b in legal:
            action = {"driver_a": a, "driver_b": b}
            total = 0.0
            for future in paths:
                child = ts._copy_race(node)
                engine.step(child, action)
                child["events"][child["step"]:] = future
                while child["step"] < len(child["events"]):
                    engine.step(child, ts.baseline_race_action(engine.observation(child)))
                total += ts.expected_apex_points_at_finish(child)
            if total > best_value + 1e-9:
                best, best_value = action, total
    return best


def play(race, events, policy):
    node = ts._copy_race(race)
    node["events"] = list(events)
    actions = []
    while node["step"] < len(node["events"]):
        action = policy(node)
        actions.append(f"{action['driver_a']}/{action['driver_b']}")
        engine.step(node, action)
    return ts.expected_apex_points_at_finish(node), actions


def replay(plan):
    def policy(node):
        a, b = plan[node["step"]].split("/")
        return {"driver_a": a, "driver_b": b}
    return policy


def sc_reactive(plan):
    """No-event plan, but at the first SC/VSC decision both cars stop (rule-aware compound)."""
    import sys as _s
    _s.path.insert(0, str(HERE.parent / "solution"))
    from play import _pit_choice
    state = {"fired": False}

    def policy(node):
        if node["events"][node["step"]] != "GREEN" and not state["fired"]:
            state["fired"] = True
            race = engine.observation(node)
            legal = race["legal_actions"]
            return {"driver_a": _pit_choice(race, "driver_a", legal), "driver_b": _pit_choice(race, "driver_b", legal)}
        a, b = plan[node["step"]].split("/")
        return {"driver_a": a, "driver_b": b}
    return policy


def race_job(args):
    from f1pitwall import coefficients as coef
    from f1pitwall.championship import new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    spec, index = args
    coeffs = coef.DEFAULT
    solver = ts.Solver(coeffs)
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coeffs))
    for _ in range(index):
        state = ts.after_race(ts.prepare(state, solver.choose(state, "rival_rule"), coeffs), coeffs)
    race = ts.prepared_race_state(ts.prepare(state, solver.choose(state, "rival_rule"), coeffs), coeffs)
    n = len(race["events"])
    started = time.time()
    no_event = ["GREEN"] * n
    v_ne, plan = play(race, no_event, rollout_action)
    paths = {"no_event": no_event}
    for k in EVENT_DECISIONS:
        sc = list(no_event)
        sc[k - 1:k + 1] = ["SC", "SC"]
        paths[f"SC@{k}"] = sc[:n]
        vsc = list(no_event)
        vsc[k - 1] = "VSC"
        paths[f"VSC@{k}"] = vsc
    for j, path in enumerate(ts.crn_event_paths(race, RANDOM_PATHS)):
        paths[f"random_{j}"] = path
    rows = {}
    for label, events in paths.items():
        if label == "no_event":
            v_replan, a_replan = v_ne, plan
        else:
            v_replan, a_replan = play(race, events, rollout_action)
        v_open, _ = play(race, events, replay(plan))
        v_react, _ = play(race, events, sc_reactive(plan))
        v_base, a_base = play(race, events, lambda node: ts.baseline_race_action(engine.observation(node)))
        first_event = next((i for i, e in enumerate(events) if e != "GREEN"), None)
        after = range(first_event, n) if first_event is not None else range(0)
        changed = sum(a_replan[i] != plan[i] for i in after)
        rows[label] = {"events": events, "replan": v_replan, "no_replan": v_open, "sc_reactive": v_react,
                       "baseline": v_base, "first_event": first_event,
                       "changed_after_event": changed, "decisions_after_event": len(after),
                       "replan_actions": a_replan, "baseline_actions": a_base}
    return {"scenario": spec["id"], "race_index": index, "plan_no_event": plan, "paths": rows,
            "seconds": round(time.time() - started, 1)}


def summarize(results):
    lines = []
    rows = [(r, label, row) for r in results for label, row in r["paths"].items()]
    def stats(values):
        values = list(values)
        return f"{st.mean(values):.2f} / {st.median(values):.2f} / {max(values):.2f}" if values else "-"
    groups = [("SC (2 segments) at a fixed decision", lambda l: l.startswith("SC@")),
              ("VSC (1 segment) at a fixed decision", lambda l: l.startswith("VSC@")),
              ("Representative public paths (with ≥1 event)", lambda l: l.startswith("random")),
              ("No-event baseline", lambda l: l == "no_event")]
    lines += ["| Scenario type | Paths | Replan − no-replan: mean / median / max | Replanning-required (> 0.5 pt) | "
              "No-change controls (plan unchanged after event) | Share of post-event decisions where the reference changes its plan |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, pick in groups:
        sel = [row for _, label, row in rows if pick(label) and (row["first_event"] is not None or label == "no_event")]
        if not sel:
            continue
        gain = [row["replan"] - row["no_replan"] for row in sel]
        req = sum(g > REPLAN_THRESHOLD for g in gain)
        nochange = sum(row["changed_after_event"] == 0 for row in sel if row["first_event"] is not None)
        share = (sum(row["changed_after_event"] for row in sel) / max(1, sum(row["decisions_after_event"] for row in sel)))
        lines.append(f"| {name} | {len(sel)} | {stats(gain)} | {req}/{len(sel)} | {nochange}/{len(sel)} | {share:.2f} |")
    lines.append("")
    ev = [row for _, label, row in rows if row["first_event"] is not None]
    required = [row for row in ev if row["replan"] - row["no_replan"] > REPLAN_THRESHOLD]
    control = [row for row in ev if row["replan"] - row["no_replan"] <= REPLAN_THRESHOLD]
    lines += ["| Regret measure (event paths) | n | mean / median / max |", "|---|---:|---:|",
              f"| Failure to respond: replan − no-replan, replanning-required paths | {len(required)} | "
              f"{stats(r['replan'] - r['no_replan'] for r in required)} |",
              f"| Unnecessary change: replan − always-pit-under-SC, no-change paths | {len(control)} | "
              f"{stats(r['replan'] - r['sc_reactive'] for r in control)} |",
              f"| Always-pit-under-SC − no-replan, all event paths | {len(ev)} | "
              f"{stats(r['sc_reactive'] - r['no_replan'] for r in ev)} |",
              f"| Always-pit-under-SC worse than no-replan | {sum(r['sc_reactive'] < r['no_replan'] - 1e-9 for r in ev)}/{len(ev)} | |",
              f"| Replan − baseline heuristic, all paths | {len(rows)} | {stats(row['replan'] - row['baseline'] for _, _, row in rows)} |"]
    return "\n".join(lines)


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    started = time.time()
    with mp.Pool(args.workers) as pool:
        results = pool.map(race_job, [(s, i) for s in specs for i in RACE_INDICES])
    out = {"futures": FUTURES, "results": results, "wall_seconds": round(time.time() - started, 1)}
    (HERE / "results" / "b4_counterfactual.json").write_text(json.dumps(out, indent=1))
    print(f"wall {out['wall_seconds']}s")
    print(summarize(results))


if __name__ == "__main__":
    main()
