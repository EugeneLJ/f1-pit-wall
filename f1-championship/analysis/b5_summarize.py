#!/usr/bin/env python3
"""B5-P1: summarise b5_event_eval.json, b5_reversals.json and b5_rival_eval.json.

Uncertainty: paired differences are averaged over the paths of each race-start state, and the 95%
interval is a t-interval across states (states are the independent units; paths inside a state
share scenario and history). Natural paths estimate the published event process; event paths are
conditioned on >= 1 SC/VSC and are reported separately (never pooled into a population mean).
Usage: scripts/py312 analysis/b5_summarize.py   -> analysis/results/b5_summary.json
"""

from __future__ import annotations

import gzip
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
T95 = 1.994  # t(0.975, ~70 df); the state count is printed with every interval


def load(name):
    """Raw results are stored gzipped (name.json.gz); a plain name.json takes precedence."""
    path = RES / name
    if path.exists():
        return json.loads(path.read_text())
    gz = path.with_name(name + ".gz")
    return json.loads(gzip.decompress(gz.read_bytes())) if gz.exists() else None


def ci(values):
    values = list(values)
    if len(values) < 2:
        return {"mean": values[0] if values else None, "lo": None, "hi": None, "n": len(values)}
    m, se = st.mean(values), st.stdev(values) / math.sqrt(len(values))
    return {"mean": round(m, 3), "lo": round(m - T95 * se, 3), "hi": round(m + T95 * se, 3), "n": len(values)}


def by_state(rows, kinds):
    table = defaultdict(lambda: defaultdict(list))  # state -> policy -> [points per path]
    for r in rows:
        if r["kind"] in kinds:
            table[(r["scenario"], r["race_index"])][r["policy"]].append((r["path"], r["points"]))
    return {s: {p: [v for _, v in sorted(vals)] for p, vals in pol.items()} for s, pol in table.items()}


def paired(states, a, b):
    return ci(st.mean(x - y for x, y in zip(pol[a], pol[b])) for pol in states.values() if a in pol and b in pol)


def per_path(states, a, b):
    return [x - y for pol in states.values() if a in pol and b in pol for x, y in zip(pol[a], pol[b])]


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 3) if values else None


def event_summary(data):
    rows, out = data["rows"], {}
    policies = sorted({r["policy"] for r in rows})
    contrasts = {"anticipation (prob_aware - green_only)": ("prob_aware", "green_only"),
                 "persistence (reactive - green_only)": ("reactive", "green_only"),
                 "full - green_only": ("full", "green_only"), "full - reactive": ("full", "reactive"),
                 "duration law (full - prob_aware)": ("full", "prob_aware"),
                 "misspecified long (full - full_long)": ("full", "full_long"),
                 "hindsight gap (clairvoyant - full)": ("clairvoyant", "full"),
                 "full - baseline": ("full", "baseline")}
    contrasts.update({f"full - {g}": ("full", g) for g in ("r0", "r1", "r2", "r3")})
    for label, kinds in (("natural", {"natural"}), ("event", {"event"})):
        states = by_state(rows, kinds)
        out[label] = {"states": len(states), "paths": sum(1 for r in rows if r["kind"] in kinds and r["policy"] == "full"),
                      "mean_points": {p: ci(st.mean(pol[p]) for pol in states.values() if p in pol) for p in policies},
                      "contrasts": {k: paired(states, a, b) for k, (a, b) in contrasts.items()},
                      "per_path_regret_vs_full": {p: {"p10": pct(per_path(states, "full", p), .1),
                                                      "p50": pct(per_path(states, "full", p), .5),
                                                      "p90": pct(per_path(states, "full", p), .9),
                                                      "share_gt_1pt": round(st.mean(d > 1.0 for d in per_path(states, "full", p)), 3)}
                                                  for p in policies if p != "full"}}
    dec = data["decisions"]
    out["decisions"] = {}
    for name in sorted({d["policy"] for d in dec}):
        ds = [d for d in dec if d["policy"] == name]
        ev = [d for d in ds if d["status"] != "GREEN"]
        sig = [d for d in ds if d["loss_vs_full"] > 1.0 and d["loss_vs_full"] > 2 * d["se"]]
        out["decisions"][name] = {
            "analysed": len(ds), "event_decisions": len(ev),
            "full_differs_from_green_only": {"SC/VSC": round(st.mean(d["full_differs_from_green"] for d in ev), 3) if ev else None,
                                             "GREEN": round(st.mean(d["full_differs_from_green"] for d in ds if d["status"] == "GREEN"), 3)},
            "action_equals_full": round(st.mean(d["action"] == d["full"] for d in ds), 3),
            "near_tie_share": round(st.mean(abs(d["loss_vs_full"]) < 0.25 for d in ds), 3),
            "significant_loss_share": round(len(sig) / len(ds), 3),
            "loss_vs_full": {"mean": round(st.mean(d["loss_vs_full"] for d in ds), 3),
                             "p90": pct([d["loss_vs_full"] for d in ds], .9),
                             "event_mean": round(st.mean(d["loss_vs_full"] for d in ev), 3) if ev else None},
            "categories": dict(Counter(d.get("category") for d in sig if d.get("category"))),
            "significant_by_status": dict(Counter(d["status"] for d in sig)),
        }
    return out


def reversal_summary(states):
    out = {"states": len(states)}
    green = [s for s in states if s["status"] == "GREEN"]
    sc1 = [s for s in states if s["status"] == "SC" and s["segments_so_far"] == 1]
    neut = [s for s in states if s["status"] in ("SC", "VSC")]
    late = [s for s in states if s["lap"] >= 33]

    def stops(a):
        return sum(x != "STAY" for x in a.split("/"))
    out["green"] = {"n": len(green),
                    "mixture_pits": sum(stops(s["best_mixture"]) > 0 for s in green),
                    "no_event_best_differs_from_mixture": sum(s["best_no_event"] != s["best_mixture"] for s in green),
                    "stay_due_to_event_risk": sum(s["stay_due_to_event_risk"] for s in green),
                    "sc_next_best_differs_from_no_event": sum(s["best_sc_next"] != s["best_no_event"] for s in green),
                    "regret_of_no_event_choice_mean": round(st.mean(s["regret_of_no_event_choice"][0] for s in green), 3) if green else None}
    out["sc_first_segment"] = {"n": len(sc1), "mixture_pits": sum(stops(s["best_mixture"]) > 0 for s in sc1),
                               "duration_reversal": sum(s["duration_reversal"] for s in sc1),
                               "best_by_duration_pattern": dict(Counter(
                                   "|".join(str(stops(s["best_by_sc_duration"][d])) for d in ("1", "2", "3"))
                                   if isinstance(next(iter(s["best_by_sc_duration"])), str) else
                                   "|".join(str(stops(s["best_by_sc_duration"][d])) for d in (1, 2, 3)) for s in sc1))}
    out["type_flip"] = {"n": len(neut), "reversal": sum(s["type_reversal"] for s in neut),
                        "SC_states": sum(s["status"] == "SC" for s in neut)}
    out["late"] = {"n": len(late), "mixture_pits": sum(stops(s["best_mixture"]) > 0 for s in late),
                   "pit_clear_gain_gt_1": sum(stops(s["best_mixture"]) > 0 and s["mixture_gain_over_stay"] > 1 for s in late)}
    return out


def rival_summary(data):
    rows = data["rows"]
    out = {"policies": {}, "decision_level": {}}
    table = defaultdict(dict)
    for r in rows:
        table[(r["scenario"], r["race_index"], r["path"])][(r["variant"], r["policy"])] = r["points"]
    variants = data["variants"]
    for policy in sorted({r["policy"] for r in rows}):
        out["policies"][policy] = {}
        for v in variants:
            vals = [t[(v, policy)] for t in table.values() if (v, policy) in t]
            if not vals:
                continue
            entry = {"mean": round(st.mean(vals), 3)}
            if policy != "full_known":  # clustered by race-start state, like the event contrasts
                per_state = defaultdict(list)
                for (scen, race, _), t in table.items():
                    if (v, policy) in t:
                        per_state[(scen, race)].append(t[(v, "full_known")] - t[(v, policy)])
                entry["regret_vs_full_known"] = ci(st.mean(x) for x in per_state.values())
            out["policies"][policy][v] = entry
    rev = data["reversals"]
    for v in variants[1:]:
        out["decision_level"][v] = {"best_differs_from_public": round(st.mean(r["best"][v] != r["best"]["public"] for r in rev), 3),
                                    "SC/VSC": round(st.mean(r["best"][v] != r["best"]["public"] for r in rev if r["status"] != "GREEN"), 3)}
    out["decision_states"] = len(rev)
    return out


def main():
    summary = {}
    event, reversals, rivals = load("b5_event_eval.json"), load("b5_reversals.json"), load("b5_rival_eval.json")
    if event:
        summary["event_eval"] = event_summary(event)
    if reversals:
        summary["reversals"] = reversal_summary(reversals["states"])
    if rivals:
        summary["rivals"] = rival_summary(rivals)
    (RES / "b5_summary.json").write_text(json.dumps(summary, indent=1))
    json.dump(summary, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
