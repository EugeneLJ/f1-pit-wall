#!/usr/bin/env python3
"""C8 Engineer-conflict paired probes (preregistered in analysis/results/c8/preregistration.json).

  select    freeze 40 unique race states from the three live 2.1.0 journals (no API)
  run       live calls, resumable: one Chief call per (state, condition); live Engineers once per state
  evaluate  local authoritative-engine scoring with common futures per state (no API)

Diagnostic only; not part of the official Frontier-Reference gap.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path[:0] = [str(TASK / "src"), str(TASK), str(HERE)]

import b21_decisions as B  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402

OUT = HERE / "results" / "c8"
RUNS = ("v21-gemini-01", "v21-gemini-02", "v21-gemini-03")
SELECTION_VERSION = "c8-selection-v1"
N_STATES = 40
CHIEF_MODEL = "gemini-3.8-flash"
ENGINEER_MODEL = "gemini-3.5-flash-lite"
SAMPLING = {"temperature": 0.0, "max_output_tokens": 8192}
CONDITIONS = ("CHIEF_ONLY", "CHIEF_ONLY_REPEAT", "GEMINI_LITE_ENGINEERS", "CONFLICTING_LOCAL_RECOMMENDATIONS",
              "NOMINAL_CONFIDENCE_CONTROL", "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL")
MOCK = ("CONFLICTING_LOCAL_RECOMMENDATIONS", "NOMINAL_CONFIDENCE_CONTROL", "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL")
SECRETS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "VERDA_INFERENCE_API_KEY")
SIGNIFICANT = 1.0
FUTURES = 16


def canon(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


# ---------------------------------------------------------------- states
def replay_states(run):
    """Exact replay of one live journal; yields (tick_id, observation, race_state) at race decisions."""
    journal = [json.loads(x) for x in (HERE / "results" / "reference_runs" / run / "evidence" / "journal.jsonl")
               .read_text().splitlines() if x]
    V.verify_chain(journal)
    seed = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
    session = S.IntegratedSession(B.config(), seed, clock=lambda: 0.0)
    for e in journal:
        if e["kind"] != "resolved":
            continue
        if session._obs_hash != e["obs_before_sha256"]:
            raise V.ReplayError(f"{run} {e['tick_id']}: observation differs from the live run")
        if session.decision_type == S.RACE_STRATEGY:
            yield e["tick_id"], session.observation("Apex"), copy.deepcopy(session.race_state)
        sub = e["submissions"]["Apex"]
        if sub["status"] == S.SUBMITTED:
            session.submit("Apex", session.tick_id, sub["action"])
        else:
            session.close_tick(session.tick_id, reason=sub["status"])


def load_states(selection):
    want = {p["observation_hash"]: p for p in selection["states"]}
    found = {}
    for run in RUNS:
        for tick, obs, race in replay_states(run):
            h = canon(obs)
            if h in want and h not in found:
                found[h] = (obs, race)
    missing = set(want) - set(found)
    if missing:
        raise SystemExit(f"{len(missing)} frozen states could not be rebuilt")
    return [(p, *found[p["observation_hash"]]) for p in selection["states"]]


def cmd_select(_args):
    unique = {}
    total = 0
    for run in RUNS:
        for tick, obs, _race in replay_states(run):
            total += 1
            unique.setdefault(canon(obs), {"run": run, "tick_id": tick})
    ranked = sorted(unique, key=lambda h: hashlib.sha256(f"{SELECTION_VERSION}|{h}".encode()).hexdigest())
    chosen = [{"state_id": f"c8s{i:02d}", "observation_hash": h, **unique[h]} for i, h in enumerate(ranked[:N_STATES])]
    out = {"schema_version": 1, "selection_version": SELECTION_VERSION, "race_decisions_replayed": total,
           "unique_states": len(unique), "states": chosen,
           "criteria": "rank unique observation hashes by sha256(c8-selection-v1|hash); first 40; no model output used"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "selection.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("race_decisions_replayed", "unique_states")} | {"selected": len(chosen)}))


# ---------------------------------------------------------------- reports
def report_entries(records):
    """Exactly how IntegratedSession places Engineer records in the Chief observation."""
    return [{"record_hash": r.get("record_hash"), "engineer_id": r["engineer_id"], "status": r["status"],
             "source": r["source"], "recommendation": copy.deepcopy(r.get("recommendation"))} for r in records]


def hashed(record):
    body = {k: v for k, v in record.items() if k not in ("record_hash", "previous_record_hash")}
    return {**body, "record_hash": canon(body)}


def mock_records(obs, condition):
    from track_c.engineer_runtime import EngineerRuntimeHarness
    return [hashed(r) for r in EngineerRuntimeHarness().collect(obs, condition)]


def with_reports(obs, records):
    out = copy.deepcopy(obs)
    if records:
        out["engineer_reports"] = report_entries(records)
    return out


# ---------------------------------------------------------------- live
def load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")


def safe(text):
    for name in SECRETS:
        secret = os.environ.get(name)
        if secret and secret in text:
            raise SystemExit("refusing to write output containing a credential")
    return text


def append(path, value):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(safe(json.dumps(value, sort_keys=True, default=str)) + "\n")


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x] if path.exists() else []


def cmd_run(args):
    from f1pitwall.integrated import providers as PR
    from track_c.engineer_runtime import GeminiEngineerProvider, EngineerRuntimeHarness
    from track_c.live_paired_probe import validate_live_action
    from google import genai
    load_env(args.env_file)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep a reference while listing
    names = {m.name for m in client.models.list()}
    for model in (CHIEF_MODEL, ENGINEER_MODEL):
        if f"models/{model}" not in names:
            raise SystemExit(f"{model} not listed; refusing to substitute")
    selection = json.loads((OUT / "selection.json").read_text())
    states = load_states(selection)[: args.max_states or None]
    guard = PR.CostGuard(args.usd_limit)
    chief = PR.GuardedChief(PR.gemini_chief("Apex", CHIEF_MODEL, "GEMINI_API_KEY", sampling=dict(SAMPLING),
                                            timeout_sec=120.0, max_retries=1,
                                            price=PR.GEMINI_38_FLASH_PRICE_2026_11_14),
                            guard, PR.GEMINI_38_FLASH_CEILING_PRICE)
    eng_path, rec_path = OUT / "engineer_records.jsonl", OUT / "chief_records.jsonl"
    engineers = {r["state_id"]: r for r in read_jsonl(eng_path)}
    done = {(r["state_id"], r["condition"]) for r in read_jsonl(rec_path)}
    calls = {"chief": 0, "engineer": 0}
    for spec, obs, _race in states:
        sid = spec["state_id"]
        if sid not in engineers:
            live = {eid: PR.GuardedEngineer(GeminiEngineerProvider(eid, model=ENGINEER_MODEL, retries=0), guard, "Apex")
                    for eid in ("engineer_a", "engineer_b")}
            recs = [hashed(r) for r in EngineerRuntimeHarness(live_providers=live).collect(obs, "GEMINI_LITE_ENGINEERS")]
            calls["engineer"] += 2
            engineers[sid] = {"state_id": sid, "records": recs}
            append(eng_path, engineers[sid])
        for cond in CONDITIONS:
            if (sid, cond) in done:
                continue
            if cond in ("CHIEF_ONLY", "CHIEF_ONLY_REPEAT"):
                recs = []
            elif cond == "GEMINI_LITE_ENGINEERS":
                recs = engineers[sid]["records"]
            else:
                recs = mock_records(obs, cond)
            probe = with_reports(obs, recs)
            row = {"state_id": sid, "condition": cond, "observation_hash": canon(probe),
                   "base_observation_hash": spec["observation_hash"],
                   "engineer_record_hashes": [r["record_hash"] for r in recs]}
            try:
                action, meta = chief(probe)
                ok, why = validate_live_action(action, probe)
                row.update({"action": action, "valid_action": ok, "invalid_reason": why})
            except PR.BudgetExceeded:
                print(json.dumps({"stopped": "budget", "calls": calls, "ceiling_usd": guard.ceiling_usd}))
                return
            except Exception as exc:  # recorded, never repaired
                meta = getattr(exc, "metadata", {})
                row.update({"action": None, "valid_action": False, "invalid_reason": f"{type(exc).__name__}"})
            calls["chief"] += 1
            row["meta"] = meta
            append(rec_path, row)
            done.add((sid, cond))
    print(json.dumps({"calls": calls, "ceiling_usd": round(guard.ceiling_usd, 4)}))


# ---------------------------------------------------------------- evaluate
def key_of(action):
    order = (action.get("team_order") or {}).get("order", "RACE")
    return f"{action['driver_a']}/{action['driver_b']}|{order}"


def score_state(args):
    sid, race, actions, futures, continuation, tag = args
    from f1pitwall import engine
    import b6_eval as E
    fut = E.futures_for(race, futures, f"{tag}|{sid}")
    legal = engine.legal_actions(race)
    cands = {f"{a}/{b}|RACE": {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}} for a in legal for b in legal}
    for act in actions:
        cands.setdefault(key_of(act), {"driver_a": act["driver_a"], "driver_b": act["driver_b"],
                                       "team_order": {k: v for k, v in act["team_order"].items() if v is not None}})
    q = {k: [E.expected_team_points(E.rollout(race, {"Apex": a}, {"Apex": continuation}, f), "Apex") for f in fut]
         for k, a in cands.items()}
    return sid, q


def regret(q, chosen):
    best = max((k for k in q if k.endswith("|RACE")), key=lambda k: st.mean(q[k]))
    return st.mean(q[best]) - st.mean(q[chosen]), best


def advice(records):
    """Per-driver advised pit action (None when the report is a priority claim or missing)."""
    out = {}
    for r in records:
        rec = r.get("recommendation") or {}
        p = rec.get("proposed_action") or {}
        drv = "driver_a" if r["engineer_id"] == "engineer_a" else "driver_b"
        out[drv] = p.get("choice") if p.get("type") == "RACE_STRATEGY" else None
    return out


def bootstrap(values, n=4000, seed=8):
    rng = random.Random(seed)
    means = sorted(st.mean(rng.choice(values) for _ in values) for _ in range(n))
    return [round(means[int(.025 * n)], 3), round(means[int(.975 * n) - 1], 3)]


def cmd_evaluate(args):
    selection = json.loads((OUT / "selection.json").read_text())
    states = {p["state_id"]: (p, obs, race) for p, obs, race in load_states(selection)}
    rows = read_jsonl(OUT / "chief_records.jsonl")
    eng = {r["state_id"]: r["records"] for r in read_jsonl(OUT / "engineer_records.jsonl")}
    by = {}
    for r in rows:
        if (r["state_id"], r["condition"]) in by:
            raise SystemExit("duplicate record")
        by[(r["state_id"], r["condition"])] = r
    sids = sorted({sid for sid, _ in by if all((sid, c) in by for c in CONDITIONS)})
    acts = {sid: [by[(sid, c)]["action"] for c in CONDITIONS if by[(sid, c)]["valid_action"]] for sid in sids}
    with mp.Pool(args.workers) as pool:
        q = dict(pool.map(score_state, [(sid, states[sid][2], acts[sid], FUTURES, "baseline", "c8") for sid in sids]))
    per = []
    for sid in sids:
        obs = states[sid][1]
        recs = {"GEMINI_LITE_ENGINEERS": eng.get(sid, [])} | {c: mock_records(obs, c) for c in MOCK}
        item = {"state_id": sid, "lap": obs["race_progress"]["lap"], "track_status": obs["race_progress"]["track_status"],
                "laps_remaining": obs["race_progress"]["laps_remaining"], "conditions": {}}
        for c in CONDITIONS:
            r = by[(sid, c)]
            cell = {"valid": r["valid_action"], "cited_reports": bool((r["action"] or {}).get("consumed_reports"))}
            if r["valid_action"]:
                cell["action"] = key_of(r["action"])
                cell["regret"], cell["reference"] = regret(q[sid], cell["action"])
                cell["regret"] = round(cell["regret"], 4)
            if c in recs:
                cell["advice"] = advice(recs[c])
            item["conditions"][c] = cell
        per.append(item)
    summary = {}
    base = "CHIEF_ONLY"
    for c in CONDITIONS:
        pairs = [(i["conditions"][base], i["conditions"][c]) for i in per
                 if i["conditions"][base]["valid"] and i["conditions"][c]["valid"]]
        diffs = [b["regret"] - a["regret"] for a, b in pairs]
        s = {"valid": sum(i["conditions"][c]["valid"] for i in per),
             "mean_regret": round(st.mean(i["conditions"][c]["regret"] for i in per if i["conditions"][c]["valid"]), 3),
             "action_change_vs_chief_only": round(st.mean(a["action"] != b["action"] for a, b in pairs), 3),
             "non_race_order_rate": round(st.mean(not i["conditions"][c]["action"].endswith("|RACE")
                                                  for i in per if i["conditions"][c]["valid"]), 3),
             "cited_reports_rate": round(st.mean(i["conditions"][c]["cited_reports"] for i in per), 3)}
        if c != base:
            s["paired_regret_diff_mean"] = round(st.mean(diffs), 3)
            s["paired_regret_diff_ci95"] = bootstrap(diffs)
        if c in recs:
            follow, follow_good, follow_bad, n_good, n_bad, harmful = 0, 0, 0, 0, 0, []
            n_adv = 0
            for i in per:
                cell, ref_cell = i["conditions"][c], i["conditions"][base]
                if not cell["valid"]:
                    continue
                chosen = cell["action"].split("|")[0].split("/")
                ref = cell["reference"].split("|")[0].split("/")
                for k, drv in enumerate(("driver_a", "driver_b")):
                    adv = cell["advice"].get(drv)
                    if adv is None:
                        continue
                    n_adv += 1
                    good = adv == ref[k]
                    n_good += good
                    n_bad += not good
                    if chosen[k] == adv:
                        follow += 1
                        follow_good += good
                        follow_bad += not good
                if ref_cell["valid"] and cell["action"] != ref_cell["action"] and \
                        cell["regret"] - ref_cell["regret"] > SIGNIFICANT and \
                        any(cell["advice"].get(d) == cell["action"].split("|")[0].split("/")[k]
                            for k, d in enumerate(("driver_a", "driver_b"))):
                    harmful.append(i["state_id"])
            s["advice_items"] = n_adv
            s["follow_rate"] = round(follow / n_adv, 3) if n_adv else None
            s["follow_rate_when_advice_matches_reference"] = round(follow_good / n_good, 3) if n_good else None
            s["follow_rate_when_advice_differs_from_reference"] = round(follow_bad / n_bad, 3) if n_bad else None
            s["harmful_following"] = harmful
        summary[c] = s
    # robustness for harmful-following cases
    robust = {}
    cases = sorted({(sid, c) for c in summary for sid in summary[c].get("harmful_following", [])})
    if cases:
        jobs = []
        for sid, c in cases:
            a = [by[(sid, base)]["action"], by[(sid, c)]["action"]]
            jobs += [(sid, states[sid][2], a, FUTURES * 3, "baseline", "c8x3"),
                     (sid, states[sid][2], a, FUTURES, "event_aware", "c8"),
                     (sid, states[sid][2], a, FUTURES, "long_stint", "c8")]
        with mp.Pool(args.workers) as pool:
            res = pool.map(score_state, jobs)
        for idx, (sid, c) in enumerate(cases):
            checks = {}
            for name, (_, qq) in zip(("futures_x3", "cont_event_aware", "cont_long_stint"), res[3 * idx: 3 * idx + 3]):
                ra, _ = regret(qq, key_of(by[(sid, base)]["action"]))
                rb, _ = regret(qq, key_of(by[(sid, c)]["action"]))
                checks[name] = round(rb - ra, 3)
            robust[f"{sid}:{c}"] = {"regret_rise": checks, "robust": all(v > SIGNIFICANT for v in checks.values())}
    calls = [r["meta"] for r in rows]
    eng_meta = [rec.get("runtime", {}) for recs in eng.values() for rec in recs]
    cost = sum(((m.get("estimated_cost") or {}).get("amount") or 0) for m in calls)
    eng_cost = sum((rt.get("estimated_cost_usd") or 0) for rt in eng_meta)
    out = {"schema_version": 1, "experiment": "C8_ENGINEER_CONFLICT_PAIRED_PROBES",
           "official_frontier_reference_gap": False, "states_complete": len(sids), "futures": FUTURES,
           "chief_calls": len(rows), "chief_returned_models": dict(Counter(m.get("returned_model") for m in calls)),
           "engineer_records": sum(len(v) for v in eng.values()),
           "engineer_record_status": dict(Counter(rec["status"] for recs in eng.values() for rec in recs)),
           "estimated_cost_usd": {"chief": round(cost, 4), "engineers": round(eng_cost, 4)},
           "summary": summary, "harmful_following_robustness": robust, "states": per}
    (OUT / "evaluation.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("states_complete", "chief_calls", "engineer_record_status",
                                          "estimated_cost_usd")} | {"summary": summary,
                                                                    "robust": robust}, indent=1))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    r = sub.add_parser("run")
    r.add_argument("--env-file", required=True)
    r.add_argument("--max-states", type=int, default=0)
    r.add_argument("--usd-limit", type=float, default=10.0)
    e = sub.add_parser("evaluate")
    e.add_argument("--workers", type=int, default=10)
    args = p.parse_args()
    {"select": cmd_select, "run": cmd_run, "evaluate": cmd_evaluate}[args.cmd](args)


if __name__ == "__main__":
    main()
