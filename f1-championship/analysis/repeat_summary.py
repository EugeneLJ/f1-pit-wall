#!/usr/bin/env python3
"""Aggregate repeated frontier runs: outcome, delegation, strategy, and decision losses.

Input: a JSON list of runs, each {"name", "dir", "seed", "started", "ended"} where dir holds
report.json, result.json (or job result stats), delegation/ (analysis/delegation.py), trace_base.json
(analysis/frontier_trace.py) and confirm.json (analysis/confirm_candidates.py).
Usage: python3 analysis/repeat_summary.py <runs.json> <out.json>
"""

from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def secs(a, b):
    return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()


def run_summary(run):
    d = Path(run["dir"])
    report, result = load(d / "report.json"), load(d / "result.json")
    deleg, trace, confirm = load(d / "deleg" / "delegation.json"), load(d / "trace_base.json"), load(d / "confirm.json")
    agent = result.get("agent_result") or result.get("stats") or {}
    perf = report["performance"]
    standings = sorted(perf["team_points"].items(), key=lambda kv: -kv[1])
    manual = set(deleg["manual_decision_ids"])
    assisted = set(deleg.get("script_assisted_manual_ids", []))
    confirmed = {(c["race_index"], c["decision"]) for c in confirm if c["confirmed"]}
    candidates = {(c["race_index"], c["decision"]) for c in confirm}
    decisions = []
    for x in trace["decisions"]:
        did = f"d{x['seq']:03d}"
        source = "assisted" if did in assisted else "manual" if did in manual else "automated"
        decisions.append({**x, "id": did, "source": source,
                          "confirmed": (x["race_index"], x["decision"]) in confirmed,
                          "candidate": (x["race_index"], x["decision"]) in candidates})
    races = []
    for r in trace["races"]:
        stops = [a for x in r["decisions"] for a in x["action"].split("/") if a != "STAY"]
        neutral = [(x["lap"], x["status"], x["action"]) for x in r["decisions"] if x["status"] != "GREEN"]
        cls = {e["driver"]: e["position"] for e in (r.get("classification") or []) if e["driver"].startswith("Apex")}
        races.append({"race": r["race_index"] + 1, "track": r["track"]["archetype"], "points": r.get("apex_points"),
                      "apex_positions": cls, "replacements": r["replacements"], "stops": len(stops),
                      "compounds_fitted": sorted(set(s.replace("PIT_", "") for s in stops)),
                      "sc_vsc_decisions": neutral})
    by = lambda pred: [x for x in decisions if pred(x)]  # noqa: E731
    def loss_stats(sel):
        return {"n": len(sel), "mean_loss_baseline_cont": st.mean(x["loss_vs_best"] for x in sel) if sel else None,
                "candidates": sum(x["candidate"] for x in sel), "confirmed": sum(x["confirmed"] for x in sel)}
    return {
        "name": run["name"], "seed_label": run.get("seed_label"), "points": perf["apex_constructors_points"],
        "rank": [t for t, _ in standings].index("Apex") + 1, "standings": standings, "reward": report["reward"],
        "complete": report["completion"]["complete"], "accepted": report["completion"]["accepted_decisions"],
        "rejected": report["integrity"].get("rejected_requests_logged", 0), "intact": report["integrity"]["intact"],
        "wall_clock_sec": secs(run["started"], run["ended"]) if run.get("started") else None,
        "tokens": {k: agent.get(k) for k in ("n_input_tokens", "n_cache_tokens", "n_output_tokens", "cost_usd")},
        "agent_steps": deleg["agent_steps"],
        "delegation": {"manual": len(manual) - len(assisted), "script_assisted": len(assisted),
                       "automated": deleg["automated_decisions"],
                       "automation_started_at": deleg["automation_started_at_decision"],
                       "scripts": {k: {kk: v[kk] for kk in ("versions", "edits", "runs", "lines", "acts_on_simulator")}
                                   for k, v in deleg["scripts"].items()}},
        "races": races,
        "losses": {"manual_or_assisted": loss_stats(by(lambda x: x["source"] != "automated")),
                   "automated": loss_stats(by(lambda x: x["source"] == "automated")),
                   "in_race": loss_stats(by(lambda x: x["category"] == "in_race")),
                   "replanning": loss_stats(by(lambda x: x["category"] == "replanning"))},
        "confirmed_failures": [{k: c[k] for k in ("race_index", "decision", "lap", "status", "category", "agent", "best",
                                                  "loss_baseline_continuation", "loss_own_continuation", "se_own_continuation")}
                               | {"source": next(x["source"] for x in decisions
                                                 if (x["race_index"], x["decision"]) == (c["race_index"], c["decision"]))}
                               for c in confirm if c["confirmed"]],
        "track_a_expected": trace["track_a_expected_points_with_baseline_race_play"]["agent_components"]["total"],
    }


def main(runs_path, out_path):
    runs = [run_summary(r) for r in load(runs_path)]
    def spread(key):
        vals = [r[key] for r in runs]
        return {"mean": st.mean(vals), "sd": st.pstdev(vals), "min": min(vals), "max": max(vals)}
    out = {"runs": runs, "aggregate": {"points": spread("points"), "reward": spread("reward"),
                                       "wall_clock_sec": spread("wall_clock_sec"),
                                       "cost_usd": {"total": sum(r["tokens"]["cost_usd"] or 0 for r in runs)}}}
    Path(out_path).write_text(json.dumps(out, indent=1, default=str))
    for r in runs:
        print(r["name"], r["points"], f"P{r['rank']}", round(r["reward"], 4), r["delegation"]["manual"],
              r["delegation"]["script_assisted"], r["delegation"]["automated"], r["delegation"]["automation_started_at"],
              round(r["wall_clock_sec"]), r["tokens"]["cost_usd"], r["losses"]["manual_or_assisted"], r["losses"]["automated"])
    print(json.dumps(out["aggregate"], indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
