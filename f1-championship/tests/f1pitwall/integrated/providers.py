"""Provider-facing Chief contracts for live evaluation (B6-C). No live call happens in tests.

  GeminiChief     google-genai SDK (lazy import) - McLearn Racing Chief
  OpenAICompatibleChief  Verda Inference chat completions (stdlib HTTP) - Red Bool Racing Chief
  Engineers       Track C `GeminiEngineerProvider` (requested model gemini-3.5-flash-lite)

Every call records: requested model, the provider-returned model/revision, request id,
prompt template hash and prompt hash, sampling settings, token usage, latency, retries,
HTTP status, and an estimated cost from a dated, versioned price snapshot (never a live
price). Credentials are read from a per-team environment variable at call time and never
stored, logged or put in prompts. A model alias is not treated as an immutable version.
Responses are parsed as one JSON action and structurally validated; the session performs the
authoritative semantic validation. Invalid output is never repaired: the runner applies the
published fallback and the record says INVALID.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Protocol

DEFAULT_ENGINEER_MODEL = "gemini-3.5-flash-lite"
# Verda Inference id, confirmed on 2026-11-14: GET /v1/models with the Red Bool key lists exactly
# this id ("deepseek-flash" is not served). Still verified at startup by verify_model_available.
DEFAULT_REDBOOL_MODEL = "deepseek-4-1-flash-1017"
VERDA_BASE_URL = "https://inference.verda.com/v1"

PROMPT_TEMPLATE_VERSION = "chief-v1"
CHIEF_PROMPT = (
    "You are the Chief Strategist of {team} in an F1-style constructors' championship simulator. "
    "Maximize your team's constructors' points. You see only your team's observation. Reply with "
    "exactly one JSON object that follows observation.action_schema (no prose). In races include "
    "team_order, e.g. {{\"order\": \"RACE\"}}. You may list Engineer record hashes you used in "
    "consumed_reports.\nRULES_SUMMARY={rules}\nOBSERVATION={observation}"
)
RULES_SUMMARY = (
    "Pit actions STAY|PIT_SOFT|PIT_MEDIUM|PIT_HARD per car; two different compounds are required "
    "per race (+20 s otherwise); SC/VSC reduce pit loss and SC compresses gaps; team orders: RACE "
    "(none), HOLD, SWAP (exchange, may be delayed or fail), DEFENSIVE_BUFFER, and with an open "
    "commitment KEEP_ORDER or REQUEST_GIVE_BACK. Commitments carry no points penalty."
)


@dataclass(frozen=True)
class PriceSnapshot:
    """Dated per-million-token prices used only for estimates (reconcile with provider billing)."""
    date: str
    currency: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float = 0.0
    source: str = ""

    def estimate(self, usage: Dict[str, Any]) -> Optional[float]:
        inp, out = usage.get("input_tokens"), usage.get("output_tokens")
        if inp is None or out is None:
            return None
        cached = usage.get("cached_input_tokens") or 0
        return round((inp - cached) / 1e6 * self.input_per_mtok + cached / 1e6 * self.cached_input_per_mtok
                     + out / 1e6 * self.output_per_mtok, 8)


VERDA_DEEPSEEK_PRICE_2026_11_14 = PriceSnapshot("2026-11-14", "USD", 0.15, 0.60, 0.006,
                                                "docs/TRACK_C_VERDA_INFERENCE.md public price snapshot")


class ProviderError(RuntimeError):
    def __init__(self, kind: str, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(kind)
        self.kind, self.status, self.retry_after = kind, status, retry_after


class ChatTransport(Protocol):
    def complete(self, *, api_key: str, model: str, prompt: str, sampling: Dict[str, Any],
                 timeout_sec: float) -> Dict[str, Any]:
        """Return {'text', 'model', 'request_id', 'usage': {input_tokens, output_tokens, ...}, 'status'}."""


class OpenAICompatibleTransport:
    """POST {base}/chat/completions with a bearer key (stdlib only)."""

    def __init__(self, base_url: str = VERDA_BASE_URL, opener: Callable = urllib.request.urlopen) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = opener

    def list_models(self, *, api_key: str, timeout_sec: float = 20.0) -> list:
        request = urllib.request.Request(f"{self.base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
        with self.opener(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [m.get("id") for m in payload.get("data", [])]

    def complete(self, *, api_key, model, prompt, sampling, timeout_sec):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": sampling.get("max_output_tokens", 1024),
                "temperature": sampling.get("temperature", 0.0)}
        if sampling.get("reasoning_effort"):
            body["reasoning_effort"] = sampling["reasoning_effort"]
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {api_key}",
                                                  "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener(request, timeout=timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After") if exc.headers else None
            raise ProviderError("http_error", exc.code, float(retry) if retry else None) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("network_or_timeout") from exc
        usage = payload.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        return {"text": payload["choices"][0]["message"]["content"], "model": payload.get("model"),
                "request_id": payload.get("id"), "status": status,
                "usage": {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                          "cached_input_tokens": details.get("cached_tokens"),
                          "total_tokens": usage.get("total_tokens")},
                "service_tier": payload.get("service_tier")}


class GoogleChatTransport:
    """google-genai SDK adapter (lazy import; JSON output mode)."""

    def complete(self, *, api_key, model, prompt, sampling, timeout_sec):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderError("sdk_missing") from exc
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_sec * 1000)))
        config = types.GenerateContentConfig(response_mime_type="application/json",
                                             temperature=sampling.get("temperature", 0.0),
                                             max_output_tokens=sampling.get("max_output_tokens", 1024))
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        usage = getattr(response, "usage_metadata", None)
        return {"text": response.text, "model": getattr(response, "model_version", None),
                "request_id": getattr(response, "response_id", None), "status": 200,
                "usage": {"input_tokens": getattr(usage, "prompt_token_count", None),
                          "output_tokens": getattr(usage, "candidates_token_count", None),
                          "cached_input_tokens": getattr(usage, "cached_content_token_count", None),
                          "total_tokens": getattr(usage, "total_token_count", None)}}


@dataclass
class LLMChief:
    """A provider-backed Chief: observation -> (action, provenance)."""
    team: str
    provider: str
    model: str
    api_key_env: str
    transport: Any
    sampling: Dict[str, Any] = field(default_factory=lambda: {"temperature": 0.0, "max_output_tokens": 1024})
    timeout_sec: float = 60.0
    max_retries: int = 1
    wall_budget_sec: float = 120.0
    price: Optional[PriceSnapshot] = None
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        self.template_hash = hashlib.sha256((PROMPT_TEMPLATE_VERSION + CHIEF_PROMPT).encode()).hexdigest()

    def __call__(self, observation: Dict[str, Any]):
        if observation.get("team") != self.team:
            raise PermissionError("a Chief may only receive its own team's observation")
        api_key = os.environ.get(self.api_key_env)
        meta = {"provider": self.provider, "requested_model": self.model, "prompt_template": PROMPT_TEMPLATE_VERSION,
                "prompt_template_sha256": self.template_hash, "sampling": copy.deepcopy(self.sampling),
                "credential_env": self.api_key_env, "submitted_via": f"provider:{self.provider}"}
        if not api_key:
            raise ProviderError("missing_credential")
        prompt = CHIEF_PROMPT.format(team=self.team, rules=RULES_SUMMARY,
                                     observation=json.dumps(observation, sort_keys=True))
        meta["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        started, attempt = time.monotonic(), 0
        while True:
            try:
                response = self.transport.complete(api_key=api_key, model=self.model, prompt=prompt,
                                                   sampling=self.sampling, timeout_sec=self.timeout_sec)
                break
            except ProviderError as exc:
                retryable = exc.kind == "network_or_timeout" or (exc.status == 429) or (exc.status or 0) >= 500
                if exc.status in (400, 401, 402, 403, 404):
                    retryable = False  # balance, permission or model-not-enabled: never retry
                wait = exc.retry_after or 1.0
                if not retryable or attempt >= self.max_retries or \
                        time.monotonic() - started + wait > self.wall_budget_sec:
                    meta.update({"status": "PROVIDER_ERROR", "error": exc.kind, "http_status": exc.status,
                                 "retries": attempt, "latency_ms": round((time.monotonic() - started) * 1000, 3)})
                    exc.metadata = meta
                    raise
                attempt += 1
                self.sleep(wait)
        meta.update({"returned_model": response.get("model"), "request_id": response.get("request_id"),
                     "http_status": response.get("status"), "usage": response.get("usage", {}),
                     "service_tier": response.get("service_tier"), "retries": attempt,
                     "latency_ms": round((time.monotonic() - started) * 1000, 3)})
        meta["estimated_cost"] = None if self.price is None else {
            "amount": self.price.estimate(meta["usage"]), "currency": self.price.currency,
            "price_snapshot_date": self.price.date}
        action = parse_action(response.get("text"))
        meta["status"] = "VALID_JSON"
        return action, meta


def parse_action(text: Any) -> Dict[str, Any]:
    """Exactly one JSON object; code fences are not stripped (output is never repaired)."""
    if not isinstance(text, str):
        raise ValueError("provider returned no text")
    value = json.loads(text)
    if not isinstance(value, dict) or "type" not in value:
        raise ValueError("provider output is not an action object")
    return value


def gemini_chief(team: str, model: str, api_key_env: str = "GEMINI_API_KEY", transport: Any = None, **kw) -> LLMChief:
    return LLMChief(team, "google_genai", model, api_key_env, transport or GoogleChatTransport(), **kw)


def redbool_chief(team: str = "Red Bool Racing", model: str = DEFAULT_REDBOOL_MODEL,
                  api_key_env: str = "VERDA_INFERENCE_API_KEY", transport: Any = None, **kw) -> LLMChief:
    kw.setdefault("price", VERDA_DEEPSEEK_PRICE_2026_11_14)
    return LLMChief(team, "verda_openai_compatible", model, api_key_env,
                    transport or OpenAICompatibleTransport(), **kw)


def verify_model_available(transport: OpenAICompatibleTransport, model: str, api_key_env: str) -> Dict[str, Any]:
    """Startup check: fail explicitly if the requested id is not served (never substitute)."""
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ProviderError("missing_credential")
    models = transport.list_models(api_key=api_key)
    if model not in models:
        raise ProviderError(f"model_not_available:{model}")
    return {"model": model, "available": True, "listed_models": len(models)}


def assert_isolated(chiefs: Dict[str, LLMChief]) -> None:
    """Independent credentials and model isolation between competing teams."""
    envs = [c.api_key_env for c in chiefs.values()]
    if len(set(envs)) != len(envs):
        raise ValueError("competing teams must use independent credential variables")
    keys = [os.environ.get(e) for e in envs]
    if all(keys) and len(set(keys)) != len(keys):
        raise ValueError("competing teams must not share one API key")
    if len({id(c.transport) for c in chiefs.values()}) != len(chiefs):
        raise ValueError("competing teams must not share a transport/client")
    for label, chief in chiefs.items():
        if chief.team != label:
            raise ValueError("provider bound to the wrong team")
