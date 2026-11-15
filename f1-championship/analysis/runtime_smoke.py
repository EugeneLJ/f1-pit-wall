#!/usr/bin/env python3
"""Real-provider smoke runs of the 2.2.0 runtime axes (direct API; not the Harbor task).

  scripts/py312 analysis/runtime_smoke.py --env-file <env> --matrix [--max-ticks 8] [--c5]
  scripts/py312 analysis/runtime_smoke.py --env-file <env> --engineers GEMINI_LITE_ENGINEERS --rival ADAPTIVE_LLM

The env file must define GEMINI_API_KEY (Chief and Engineers) and, for ADAPTIVE_LLM, VERDA_INFERENCE_API_KEY.
Keys are loaded into the process environment and never printed or written; every output is checked for
them before it is written. Each run writes <out>/<label>/{summary.json, journal.jsonl}.
--matrix runs CHIEF_ONLY/SCRIPTED, GEMINI_LITE/SCRIPTED, CHIEF_ONLY/ADAPTIVE_LLM, GEMINI_LITE/ADAPTIVE_LLM,
then CHIEF_ONLY/FIXED_REPLAY replaying the rival of the CHIEF_ONLY/ADAPTIVE_LLM run.
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
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall.integrated import providers as PR  # noqa: E402
from f1pitwall.integrated import runtime as R  # noqa: E402

SECRETS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "VERDA_INFERENCE_API_KEY")
SEED = 20261116  # fresh smoke seed, never used for any reported result


def load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")


def safe(text: str) -> str:
    for name in SECRETS:
        secret = os.environ.get(name)
        if secret and secret in text:
            raise SystemExit("refusing to write output containing a credential")
    return text


def check_models(spec: R.RuntimeSpec) -> dict:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep a reference while listing
    names = {m.name for m in client.models.list()}
    out = {"chief": f"models/{spec.chief_model}" in names}
    if spec.engineers == "GEMINI_LITE_ENGINEERS":
        out["engineers"] = f"models/{spec.engineer_model}" in names
    if spec.rival == "ADAPTIVE_LLM":
        listed = PR.OpenAICompatibleTransport().list_models(api_key=os.environ["VERDA_INFERENCE_API_KEY"])
        out["rival"] = spec.rival_model in listed
    missing = [k for k, ok in out.items() if not ok]
    if missing:
        raise SystemExit(f"model(s) not available, refusing to substitute: {missing}")
    return out


def run_one(spec: R.RuntimeSpec, out_root: Path, max_ticks: int, usd_limit: float) -> dict:
    out = out_root / spec.label().replace("|", "_")
    out.mkdir(parents=True, exist_ok=True)
    models = check_models(spec)
    guard = PR.CostGuard(usd_limit)
    started = time.time()
    result = R.run(spec, SEED, out, guard, max_ticks=max_ticks)
    journal = result.pop("journal")
    calls = [p for p in result["provenance"] if p["metadata"].get("requested_model")]
    summary = {k: v for k, v in result.items() if k != "provenance"}
    summary.update({"models_listed": models, "wall_seconds": round(time.time() - started, 1), "max_ticks": max_ticks,
                    "llm_calls": len(calls),
                    "returned_models": sorted({str(p["metadata"].get("returned_model")) for p in calls}),
                    "decision_types": sorted({e["decision_type"] for e in journal if e["kind"] == "resolved"}),
                    "provenance": [{k: p[k] for k in ("tick_id", "team", "status", "latency_ms")} |
                                   {"returned_model": p["metadata"].get("returned_model"),
                                    "error": p["metadata"].get("error")} for p in result["provenance"]]})
    (out / "journal.jsonl").write_text(safe("".join(json.dumps(e, sort_keys=True) + "\n" for e in journal)))
    (out / "summary.json").write_text(safe(json.dumps(summary, indent=1, sort_keys=True, default=str)))
    print(safe(json.dumps({"label": spec.label(), "replay": summary["replay"], "status": summary["provenance_status"],
                           "decision_types": summary["decision_types"], "returned_models": summary["returned_models"],
                           "cost_usd": summary["cost"].get("estimated_usd"), "seconds": summary["wall_seconds"]})),
          flush=True)
    return {"summary": summary, "journal_path": str(out / "journal.jsonl")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--out", default=str(HERE / "results" / "runtime_smoke"))
    parser.add_argument("--max-ticks", type=int, default=8)
    parser.add_argument("--usd-limit", type=float, default=5.0)
    parser.add_argument("--c5", action="store_true")
    parser.add_argument("--m2-m6-m7", action="store_true", help="also enable Kimi's M2, M6 and M7")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--engineers", default="CHIEF_ONLY", choices=R.ENGINEER_AXIS)
    parser.add_argument("--rival", default="SCRIPTED", choices=R.RIVAL_AXIS)
    parser.add_argument("--replay-journal")
    args = parser.parse_args()
    load_env(args.env_file)
    out_root = Path(args.out)
    feats = {k: args.m2_m6_m7 for k in ("m2_tendencies", "m6_compliance", "m7_weather")}
    if not args.matrix:
        run_one(R.RuntimeSpec(args.engineers, args.rival, c5_weekend=args.c5, replay_journal=args.replay_journal,
                              **feats),
                out_root, args.max_ticks, args.usd_limit)
        return
    adaptive = None
    for eng, rival in (("CHIEF_ONLY", "SCRIPTED"), ("GEMINI_LITE_ENGINEERS", "SCRIPTED"),
                       ("CHIEF_ONLY", "ADAPTIVE_LLM"), ("GEMINI_LITE_ENGINEERS", "ADAPTIVE_LLM")):
        done = run_one(R.RuntimeSpec(eng, rival, c5_weekend=args.c5, **feats), out_root, args.max_ticks, args.usd_limit)
        if (eng, rival) == ("CHIEF_ONLY", "ADAPTIVE_LLM"):
            adaptive = done["journal_path"]
    run_one(R.RuntimeSpec("CHIEF_ONLY", "FIXED_REPLAY", c5_weekend=args.c5, replay_journal=adaptive, **feats),
            out_root, args.max_ticks, args.usd_limit)


if __name__ == "__main__":
    main()
