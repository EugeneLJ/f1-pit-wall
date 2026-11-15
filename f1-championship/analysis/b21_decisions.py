#!/usr/bin/env python3
"""Decision-level analysis of the live 2.1.0 Gemini run (v21-gemini-01). No model call.

1. Replays the live journal v2 exactly from the task seed (trusted analysis side).
2. At every race decision: all 16 joint pit actions (team order RACE) plus Gemini's own action are
   rolled out with the authoritative engine over K public SC/VSC futures (published model,
   conditioned on the observed history); afterwards the team continues with the published baseline
   rule. Value = exact expected Apex points at the finish over the published retirement
   probabilities. The reference therefore has a MODEL-ACCESS ADVANTAGE (it executes the exact rules).
3. Candidate strategic failure: regret > 1.0 point AND > 2 standard errors (paired over futures).
   Each candidate is classified from the action pattern and context; classifications are
   descriptive, not causal.
4. Robustness: every candidate is re-scored with 3x the futures and with two other continuation
   rules (event_aware, long_stint); a candidate counts as robust only if it stays a candidate in all.
Usage: scripts/py312 analysis/b21_decisions.py [--futures 16] [--workers 10]
Writes analysis/results/reference_runs/v21-gemini-01/decisions.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(HERE))
import b6_eval as E  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402

RUN = HERE / "results" / "reference_runs" / "v21-gemini-01"  # overridden by --run
SLOT = "Apex"
SIGNIFICANT = 1.0


def config():
    return C.with_version(C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "harbor_agent"}), "2.1.0")


def states():
    journal = [json.loads(x) for x in (RUN / "evidence" / "journal.jsonl").read_text().splitlines() if x]
    seed = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
    V.verify_chain(journal)
    session = S.IntegratedSession(config(), seed, clock=lambda: 0.0)
    out = []
    for e in journal:
        if e["kind"] != "resolved":
            continue
        if session._obs_hash != e["obs_before_sha256"]:
            raise V.ReplayError(f"{e['tick_id']}: observation differs from the live run")
        if session.decision_type == S.RACE_STRATEGY:
            obs = session.observation("Apex")
            out.append({"tick_id": e["tick_id"], "race_index": session.state.race_index,
                        "race_name": session.state.calendar[session.state.race_index].name,
                        "race": copy.deepcopy(session.race_state), "action": e["submissions"]["Apex"]["action"],
                        "status_code": e["submissions"]["Apex"]["status"],
                        "drivers": obs["race_progress"]["drivers"], "laps_remaining": obs["race_progress"]["laps_remaining"],
                        "neutralization": obs["race_progress"].get("neutralization")})
        sub = e["submissions"]["Apex"]
        if sub["status"] == S.SUBMITTED:
            session.submit("Apex", session.tick_id, sub["action"])
        else:
            session.close_tick(session.tick_id, reason=sub["status"])
    return out, session.state.team_points["Apex"]


def evaluate(item, futures, continuation="baseline", tag="b21"):
    race = item["race"]
    fut = E.futures_for(race, futures, f"{tag}|{item['tick_id']}")
    legal = engine.legal_actions(race)
    chosen = item["action"]
    chosen_key = f"{chosen['driver_a']}/{chosen['driver_b']}|{chosen['team_order']['order']}"
    cands = {f"{a}/{b}|RACE": {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}} for a in legal for b in legal}
    cands.setdefault(chosen_key, {"driver_a": chosen["driver_a"], "driver_b": chosen["driver_b"],
                                  "team_order": {k: v for k, v in chosen["team_order"].items() if v is not None}})
    q = {k: [E.expected_team_points(E.rollout(race, {SLOT: a}, {SLOT: continuation}, f), SLOT) for f in fut]
         for k, a in cands.items()}
    best = max(q, key=lambda k: st.mean(q[k]))
    diff = [x - y for x, y in zip(q[best], q[chosen_key])]
    se = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
    return {"chosen": chosen_key, "reference": best, "regret": round(st.mean(diff), 4), "se": round(se, 4),
            "q_chosen": round(st.mean(q[chosen_key]), 3), "q_reference": round(st.mean(q[best]), 3),
            "q_stay_stay": round(st.mean(q["STAY/STAY|RACE"]), 3)}


def classify(item, ev):
    """Descriptive pattern of the difference between Gemini's action and the reference action."""
    c_pits = ev["chosen"].split("|")[0].split("/")
    r_pits = ev["reference"].split("|")[0].split("/")
    status = item["race"]["events"][item["race"]["step"]]
    labels = []
    for k, (c, r) in zip(("driver_a", "driver_b"), zip(c_pits, r_pits)):
        car = item["drivers"][k]
        if c == "STAY" and r != "STAY":
            labels.append(f"missed_stop:{k}")
        elif c != "STAY" and r == "STAY":
            labels.append(f"unneeded_stop:{k}")
        elif c != r:
            labels.append(f"compound:{k}:{c}->{r}")
    if all(p != "STAY" for p in c_pits):
        labels.append("double_stack_chosen")
    if status != "GREEN":
        labels.append(f"event:{status}")
    if ev["chosen"].split("|")[1] != "RACE":
        labels.append(f"team_order:{ev['chosen'].split('|')[1]}")
    if item["laps_remaining"] <= 9:
        labels.append("late_race")
    return labels or ["same_pit_pattern"]


def _set_run(path):
    global RUN
    RUN = Path(path)


def job(args):
    item, futures = args
    ev = evaluate(item, futures)
    return item["tick_id"], ev


def robust_job(args):
    item, futures = args
    return item["tick_id"], {"futures_x3": evaluate(item, futures * 3, tag="b21x3"),
                             "cont_event_aware": evaluate(item, futures, "event_aware"),
                             "cont_long_stint": evaluate(item, futures, "long_stint")}


def main():
    sys.path.insert(0, str(HERE))
    from _runtime import require_runtime_python
    require_runtime_python()
    parser = argparse.ArgumentParser()
    parser.add_argument("--futures", type=int, default=16)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--run", default="v21-gemini-01")
    args = parser.parse_args()
    global RUN
    RUN = HERE / "results" / "reference_runs" / args.run
    items, points = states()
    by_tick = {i["tick_id"]: i for i in items}
    with mp.Pool(args.workers, initializer=_set_run, initargs=(str(RUN),)) as pool:
        evals = dict(pool.map(job, [(i, args.futures) for i in items], chunksize=2))
        cands = [t for t, ev in evals.items() if ev["regret"] > SIGNIFICANT and ev["regret"] > 2 * ev["se"]]
        robust = dict(pool.map(robust_job, [(by_tick[t], args.futures) for t in cands], chunksize=1))
    rows = []
    for t, ev in evals.items():
        item = by_tick[t]
        row = {"tick_id": t, "race_index": item["race_index"], "race": item["race_name"],
               "decision": item["race"]["step"] + 1, "lap": engine._decision_laps(item["race"])[item["race"]["step"]],
               "status": item["race"]["events"][item["race"]["step"]], "laps_remaining": item["laps_remaining"],
               "cars": {k: {kk: v[kk] for kk in ("position", "compound", "tyre_age", "compounds_used")}
                        for k, v in item["drivers"].items()}, **ev}
        if t in robust:
            checks = robust[t]
            row["candidate"] = True
            row["labels"] = classify(item, ev)
            row["robustness"] = {k: {"regret": v["regret"], "se": v["se"], "reference": v["reference"]} for k, v in checks.items()}
            row["robust"] = all(v["regret"] > SIGNIFICANT and v["regret"] > 2 * v["se"] for v in checks.values())
        rows.append(row)
    rows.sort(key=lambda r: r["tick_id"])
    cand_rows = [r for r in rows if r.get("candidate")]
    per_race = Counter()
    for r in rows:
        per_race[r["race_index"]] += r["regret"]
    summary = {"live_points": points, "race_decisions": len(rows), "futures": args.futures,
               "reference": "authoritative-engine public-input rollout, baseline continuation (model-access advantage)",
               "same_as_reference": round(st.mean(r["chosen"] == r["reference"] for r in rows), 3),
               "near_tie_share": round(st.mean(abs(r["regret"]) < 0.25 for r in rows), 3),
               "sum_regret": round(sum(r["regret"] for r in rows), 2),
               "candidates": len(cand_rows), "robust_candidates": sum(1 for r in cand_rows if r["robust"]),
               "regret_by_race": {k: round(v, 2) for k, v in sorted(per_race.items())},
               "candidate_labels": dict(Counter(l.split(":")[0] for r in cand_rows for l in r["labels"])),
               "robust_labels": dict(Counter(l.split(":")[0] for r in cand_rows if r["robust"] for l in r["labels"])),
               "robust_regret_sum": round(sum(r["regret"] for r in cand_rows if r["robust"]), 2)}
    (RUN / "decisions.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
