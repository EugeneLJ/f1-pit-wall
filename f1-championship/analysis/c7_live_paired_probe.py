#!/usr/bin/env python3
"""Run/resume the frozen C7 Gemini paired-probe experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall.integrated import providers as PR  # noqa: E402
from track_c.live_paired_probe import (  # noqa: E402
    canonical_hash, exact_prompt, live_observation, validate_live_action,
)

MODEL = "gemini-3.8-flash"
SAMPLING = {"temperature": 0.0, "max_output_tokens": 8192}
TEAM = "Apex"
API_KEY_ENV = "GEMINI_API_KEY"


def load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")


def safe_json(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    secret = os.environ.get(API_KEY_ENV)
    if secret and secret in text:
        raise RuntimeError("refusing to persist a credential")
    return text


def append_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(safe_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_model(api_key):
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai SDK is unavailable") from exc
    names = [model.name for model in genai.Client(api_key=api_key).models.list()]
    requested = f"models/{MODEL}"
    return {"requested_model": MODEL, "listed": requested in names, "listed_model_count": len(names)}


def call_one(transport, api_key, pair_id, condition, source_observation):
    observation = live_observation(source_observation, TEAM)
    prompt = exact_prompt(observation, TEAM)
    source_hash = canonical_hash(source_observation)
    started = time.monotonic()
    attempt = 0
    while True:
        try:
            response = transport.complete(api_key=api_key, model=MODEL, prompt=prompt,
                                          sampling=SAMPLING, timeout_sec=120.0)
            break
        except PR.ProviderError as exc:
            retryable = exc.kind == "network_or_timeout" or exc.status == 429 or (exc.status or 0) >= 500
            if not retryable or attempt >= 1:
                raise
            attempt += 1
            time.sleep(exc.retry_after or 1.0)
    response_text = response.get("text")
    action, parse_error = None, None
    try:
        action = PR.parse_action(response_text)
    except (ValueError, json.JSONDecodeError) as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    valid, validation_error = (validate_live_action(action, observation) if action is not None
                               else (False, parse_error or "missing response"))
    usage = response.get("usage") or {}
    return {
        "schema_version": 1,
        "pair_id": pair_id,
        "condition": condition,
        "source_observation_hash": source_hash,
        "live_observation_hash": canonical_hash(observation),
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_template": PR.PROMPT_TEMPLATE_VERSION,
        "prompt_template_sha256": hashlib.sha256((PR.PROMPT_TEMPLATE_VERSION + PR.CHIEF_PROMPT).encode()).hexdigest(),
        "requested_model": MODEL,
        "returned_model": response.get("model"),
        "request_id": response.get("request_id"),
        "sampling": dict(SAMPLING),
        "usage": usage,
        "estimated_cost": {
            "amount_usd": PR.GEMINI_38_FLASH_PRICE_2026_11_14.estimate(usage),
            "price_snapshot_date": PR.GEMINI_38_FLASH_PRICE_2026_11_14.date,
            "source": PR.GEMINI_38_FLASH_PRICE_2026_11_14.source,
        },
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "retries": attempt,
        "http_status": response.get("status"),
        "response_text": response_text,
        "response_sha256": hashlib.sha256((response_text or "").encode()).hexdigest(),
        "action": action,
        "valid_action": valid,
        "status": "VALID_ACTION" if valid else "INVALID_ACTION",
        "error": validation_error,
        "credential_env": API_KEY_ENV,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-pairs", type=int)
    parser.add_argument("--require-valid-smoke", action="store_true")
    args = parser.parse_args()
    load_env(args.env_file)
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise SystemExit(f"missing {API_KEY_ENV}")
    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    source_bytes = Path(args.source).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != selection["source_sha256"]:
        raise SystemExit("frozen C6 source hash mismatch")
    artifact = json.loads(source_bytes)
    source_rows = {row["pair"]["pair_id"]: row for row in artifact["targeted_probes"]}
    selected = selection["pairs"][:args.max_pairs] if args.max_pairs else selection["pairs"]
    output = Path(args.output)
    existing = []
    if output.exists():
        existing = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line]
    done = {(record["pair_id"], record["condition"]) for record in existing}
    model_check = verify_model(api_key)
    if not model_check["listed"]:
        raise SystemExit("requested Gemini model is not listed; refusing substitution")
    transport = PR.GoogleChatTransport()
    new_records = []
    for item in selected:
        row = source_rows[item["pair_id"]]
        evidence = row["pair"]["public_evidence_diff"]
        for condition, prefix in (("a", "baseline"), ("b", "altered")):
            if (item["pair_id"], condition) in done:
                continue
            observation = evidence[f"{prefix}_public_observation"]
            if canonical_hash(observation) != item[f"{prefix}_observation_hash"]:
                raise SystemExit("selection observation hash mismatch")
            record = call_one(transport, api_key, item["pair_id"], condition, observation)
            if not record["returned_model"] or not record["request_id"]:
                raise SystemExit("provider provenance missing; stopping")
            append_record(output, record)
            new_records.append(record)
            if args.require_valid_smoke and not record["valid_action"]:
                raise SystemExit("smoke response did not pass public action validation")
    summary = {"model_check": model_check, "new_calls": len(new_records),
               "total_records": len(existing) + len(new_records),
               "valid_new": sum(record["valid_action"] for record in new_records),
               "estimated_cost_new_usd": round(sum((record["estimated_cost"]["amount_usd"] or 0)
                                                    for record in new_records), 8)}
    print(safe_json(summary))


if __name__ == "__main__":
    main()
