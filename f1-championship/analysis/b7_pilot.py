#!/usr/bin/env python3
"""B7-P0 live pilot: McLearn (Gemini Chief [+ Gemini Lite Engineers]) vs Red Bool (DeepSeek Chief)
on the unchanged 2.0.0 integrated championship. Run on Verda (credentials live there).

  --verify   free model listings only (Gemini models.list, Verda GET /v1/models)
  --probe    one live call per adapter and decision phase, each validated by a throwaway session
  --layer N  one full eight-race season (1: no Engineers, 2: McLearn Engineer A/B live)

Fixed, logged settings (identical for both Chiefs): prompt template chief-v1, temperature 0.0,
max_output_tokens 8192, timeout 120 s, at most 1 retry (429/5xx/network only), no tools.
A shared cost guard charges every call at a conservative ceiling price and aborts the season
cleanly (no partial tick) at --usd-limit. Keys are read from the env file into this process
only and are never printed, logged or written.

Usage: uv run --no-project --python 3.12 --with google-genai python analysis/b7_pilot.py \
         --env-file /root/.config/f1-pit-wall.env --out analysis/results/b7 [--verify|--probe|--layer 1]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK))

from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import match as M  # noqa: E402
from f1pitwall.integrated import providers as PR  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402

GEMINI_CHIEF_MODEL = "gemini-3.8-flash"
ENGINEER_MODEL = "gemini-3.5-flash-lite"
DEEPSEEK_MODEL = PR.DEFAULT_REDBOOL_MODEL
SEED = 20261115  # fresh pilot seed (never used before); same seed and slots for both layers
SAMPLING = {"temperature": 0.0, "max_output_tokens": 8192}
SECRETS = ("VERDA_INFERENCE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")


def safe_dump(value) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    for name in SECRETS:
        secret = os.environ.get(name)
        if secret and secret in text:
            raise SystemExit("refusing to write output containing a credential")
    return text


def verify_models():
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep a reference while listing
    names = [m.name for m in client.models.list()]
    verda = PR.OpenAICompatibleTransport().list_models(api_key=os.environ["VERDA_INFERENCE_API_KEY"])
    out = {"gemini_listed": sorted(n for n in names if "gemini" in n),
           "gemini_chief": {"requested": GEMINI_CHIEF_MODEL, "listed": f"models/{GEMINI_CHIEF_MODEL}" in names},
           "gemini_engineer": {"requested": ENGINEER_MODEL, "listed": f"models/{ENGINEER_MODEL}" in names},
           "deepseek_chief": {"requested": DEEPSEEK_MODEL, "listed": DEEPSEEK_MODEL in verda, "verda_models": verda}}
    missing = [k for k in ("gemini_chief", "gemini_engineer", "deepseek_chief") if not out[k]["listed"]]
    if missing:
        raise SystemExit(f"model(s) not available, refusing to substitute: {missing}")
    return out


def chiefs(guard):
    gem = PR.gemini_chief("McLearn Racing", GEMINI_CHIEF_MODEL, "GEMINI_API_KEY", sampling=dict(SAMPLING),
                          timeout_sec=120.0, max_retries=1, price=PR.GEMINI_38_FLASH_PRICE_2026_11_14)
    ds = PR.redbool_chief(sampling=dict(SAMPLING), timeout_sec=120.0, max_retries=1)
    PR.assert_isolated({"McLearn Racing": gem, "Red Bool Racing": ds})
    return {"McLearn Racing": PR.GuardedChief(gem, guard, PR.GEMINI_38_FLASH_CEILING_PRICE),
            "Red Bool Racing": PR.GuardedChief(ds, guard, PR.VERDA_DEEPSEEK_PRICE_2026_11_14)}


def engineers(guard):
    from track_c.engineer_runtime import GeminiEngineerProvider
    return {"McLearn Racing": {eid: PR.GuardedEngineer(GeminiEngineerProvider(eid, model=ENGINEER_MODEL, retries=0),
                                                       guard, "McLearn Racing")
                               for eid in ("engineer_a", "engineer_b")}}


def probe(out_dir, guard):
    """One call per adapter and phase on real observations; each action is validated by a session."""
    results = {}
    cfg = C.two_team(2, mclearn_engineers="GEMINI_LITE_ENGINEERS")
    broker = EngineerBroker(out_dir / "probe_engineers", live_providers=engineers(guard))
    session = S.IntegratedSession(cfg, SEED, engineer_broker=broker)
    pol = chiefs(guard)
    for phase in ("COMPONENT_DECISION", "RACE_STRATEGY"):
        tick = session.tick_id
        for label in ("McLearn Racing", "Red Bool Racing"):
            obs = session.observation(label)
            assert obs["decision_type"] == phase
            entry = {"team": label, "phase": phase}
            try:
                action, meta = pol[label](obs)
                entry.update({"action": action, "returned_model": meta.get("returned_model"),
                              "usage": meta.get("usage"), "latency_ms": meta.get("latency_ms"),
                              "status": meta.get("status")})
                try:
                    session.submit(label, tick, action, submitted_via=meta["submitted_via"])
                    entry["legal"] = True
                except S.TickError as exc:
                    entry.update({"legal": False, "error": str(exc)})
                    session.submit(label, tick, session.fallback_action(label))
            except Exception as exc:
                entry.update({"legal": False, "error": f"{type(exc).__name__}: {getattr(exc, 'kind', exc)}",
                              "meta": {k: v for k, v in getattr(exc, "metadata", {}).items() if k != "raw_text"},
                              "raw_text": getattr(exc, "metadata", {}).get("raw_text")})
                session.submit(label, tick, session.fallback_action(label))
            results[f"{label}:{phase}"] = entry
    reports = session.observation("McLearn Racing").get("engineer_reports", [])
    records = [json.loads(x) for x in (out_dir / "probe_engineers" / "mclearn_racing" / "engineer_records.jsonl")
               .read_text().splitlines()]
    results["engineers"] = [{"engineer_id": r["engineer_id"], "status": r["status"], "error": r["error"],
                             "error_detail": (r["runtime"] or {}).get("error_detail"),
                             "observation_hash_matches": bool(r["recommendation"]) and
                             r["recommendation"]["observation_hash"] == r["observation_hash"],
                             "model_revision": (r["runtime"] or {}).get("model_revision"),
                             "usage": (r["runtime"] or {}).get("usage"),
                             "proposed_action": (r["recommendation"] or {}).get("proposed_action")} for r in records]
    results["engineer_reports_in_chief_observation"] = len(reports)
    return results


def season(layer, out_dir, guard):
    layer_dir = out_dir / f"layer{layer}"
    layer_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ticks.jsonl", "journal.jsonl"):
        (layer_dir / name).write_text("")
    cfg = C.two_team(layer, mclearn_chief={"provider": "google_genai", "model": GEMINI_CHIEF_MODEL},
                     redbool_chief={"provider": "verda_openai_compatible", "model": DEEPSEEK_MODEL},
                     mclearn_engineers="GEMINI_LITE_ENGINEERS" if layer == 2 else None)
    broker = EngineerBroker(layer_dir / "engineers", live_providers=engineers(guard)) if layer == 2 else None

    def observer(event):
        with (layer_dir / "ticks.jsonl").open("a") as fh:
            fh.write(safe_dump({k: event[k] for k in ("tick_id", "observations", "provenance")}) + "\n")
        with (layer_dir / "journal.jsonl").open("a") as fh:
            for entry in event["journal_entries"]:
                fh.write(safe_dump(entry) + "\n")
        (layer_dir / "progress.json").write_text(safe_dump({"tick_id": event["tick_id"], "cost": guard.summary(),
                                                            "time": time.time()}))

    started = time.time()
    result = M.run_season(cfg, SEED, chiefs(guard), engineer_broker=broker, timeout_sec=180.0,
                          observer=observer, abort_on=(PR.BudgetExceeded,))
    replay_broker = EngineerBroker.replaying(layer_dir / "engineers") if layer == 2 else None
    try:
        replayed = V.replay(cfg, SEED, result["journal"], engineer_broker=replay_broker,
                            require_complete=result["complete"])
        replay = {"ok": replayed["standings"] == result["standings"], "resolved_ticks": replayed["resolved_ticks"]}
    except Exception as exc:
        replay = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    summary = {"layer": layer, "config": result["config"], "config_hash": result["config_hash"],
               "seed_id": result["base_seed_id"], "complete": result["complete"], "aborted": result["aborted"],
               "standings": result["standings"], "race_results": result["race_results"], "replay": replay,
               "cost": guard.summary(), "wall_seconds": round(time.time() - started, 1),
               "settings": {"sampling": SAMPLING, "timeout_sec": 120.0, "max_retries": 1, "tools": "none (direct API)"}}
    (layer_dir / "summary.json").write_text(safe_dump(summary))
    (layer_dir / "DONE").write_text("1")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--out", default=str(HERE / "results" / "b7"))
    parser.add_argument("--usd-limit", type=float, default=5.0)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--probe", action="store_true")
    group.add_argument("--layer", type=int, choices=(1, 2))
    args = parser.parse_args()
    load_env(args.env_file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    guard = PR.CostGuard(args.usd_limit)
    if args.verify:
        result = verify_models()
        (out_dir / "models.json").write_text(safe_dump(result))
    elif args.probe:
        verify_models()
        result = probe(out_dir, guard)
        result["cost"] = guard.summary()
        (out_dir / "probe.json").write_text(safe_dump(result))
    else:
        verify_models()
        result = season(args.layer, out_dir, guard)
    print(safe_dump(result)[:6000])


if __name__ == "__main__":
    main()
