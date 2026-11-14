#!/usr/bin/env python3
"""B6-C minimal paid connectivity smoke test (separately labelled; not an evaluation).

Exactly two inference calls, on a real integrated observation (TWO_TEAM_COMPETITION, layer 1,
first RACE_STRATEGY tick):
  1. Red Bool Chief  - Verda Inference, deepseek-4-1-flash-1017 (OpenAI-compatible)
  2. Engineer A      - Google, gemini-3.5-flash-lite (Track C GeminiEngineerProvider)
Plus one free GET /v1/models availability check. Keys are read from an env file into this
process only; they are never printed, logged, passed on a command line or written to the
output. The Chief action is validated by submitting it to the session.

Usage (Verda): uv run --no-project --python 3.12 --with google-genai python analysis/b6_smoke.py \
                 --env-file /root/.config/f1-pit-wall.env
Writes analysis/results/b6_smoke.json
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
from f1pitwall.integrated import providers as PR  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")


def deepseek_call(session, obs_rb):
    transport = PR.OpenAICompatibleTransport()
    try:  # 0. availability (free)
        availability = PR.verify_model_available(transport, PR.DEFAULT_REDBOOL_MODEL, "VERDA_INFERENCE_API_KEY")
    except PR.ProviderError as exc:
        availability = {"error": str(exc)}
    # 1. Red Bool Chief (DeepSeek)
    chief = PR.redbool_chief(transport=transport, timeout_sec=120.0, max_retries=0,
                             sampling={"temperature": 0.0, "max_output_tokens": 1024})
    record = {"provider": "verda_openai_compatible", "requested_model": PR.DEFAULT_REDBOOL_MODEL}
    try:
        action, meta = chief(obs_rb)
        record.update(meta)
        record["action"] = action
        try:
            receipt = session.submit("Red Bool Racing", obs_rb["tick_id"], action, submitted_via="provider:smoke")
            record["session_validation"] = {"accepted": True, "action_sha256": receipt["action_sha256"]}
        except S.TickError as exc:
            record["session_validation"] = {"accepted": False, "error": str(exc)}
    except Exception as exc:
        record.update(getattr(exc, "metadata", {}))
        record["status"] = "FAILED"
        record["error"] = f"{type(exc).__name__}: {getattr(exc, 'kind', exc)}"[:300]
    return availability, record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--gemini-retry", action="store_true",
                        help="only re-run the Gemini Engineer call and add it to the existing results")
    args = parser.parse_args()
    load_env(Path(args.env_file))
    out = {"label": "B6-C paid connectivity smoke test (2 inference calls)", "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    session = S.IntegratedSession(C.two_team(1), base_seed=20261114)
    for label in session.teams:  # component phase: published fallback (no model call)
        session.submit(label, session.tick_id, session.fallback_action(label))
    obs_rb = session.observation("Red Bool Racing")
    obs_mc = session.observation("McLearn Racing")
    out["observation"] = {"tick_id": obs_rb["tick_id"], "decision_type": obs_rb["decision_type"],
                          "bytes_red_bool": len(json.dumps(obs_rb))}

    if args.gemini_retry:
        path = HERE / "results" / "b6_smoke.json"
        out = json.loads(path.read_text())
        out["gemini_engineer_attempt1"] = out.pop("gemini_engineer")
        out["label"] = "B6-C paid connectivity smoke test (DeepSeek 1 call; Gemini 1 failed call + 1 retry after fix)"
        out["gemini_retry_date_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    else:
        out["deepseek_availability"], out["deepseek_chief"] = deepseek_call(session, obs_rb)

    # 2. Engineer A (Gemini Flash-Lite) on McLearn's driver-local view
    from track_c.engineer_runtime import (DEFAULT_GEMINI_ENGINEER_MODEL, GeminiEngineerProvider,
                                          format_runtime_observation, run_provider_safely)
    local = format_runtime_observation(obs_mc, "engineer_a")
    provider = GeminiEngineerProvider("engineer_a", model=DEFAULT_GEMINI_ENGINEER_MODEL, retries=0)
    eng = run_provider_safely(provider, local, source="LIVE_MODEL")
    out["gemini_engineer"] = {"requested_model": DEFAULT_GEMINI_ENGINEER_MODEL, "status": eng["status"],
                              "source": eng["source"], "error": eng["error"], "runtime": eng["runtime"],
                              "recommendation": eng["recommendation"]}
    usage = (eng["runtime"] or {}).get("usage") or {}
    out["gemini_engineer"]["estimated_cost"] = None  # no dated Gemini price snapshot in repo; tokens recorded

    text = json.dumps(out, indent=1, sort_keys=True, default=str)
    for name in ("VERDA_INFERENCE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        secret = os.environ.get(name)
        if secret and secret in text:
            raise SystemExit("refusing to write output containing a credential")
    (HERE / "results" / "b6_smoke.json").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
