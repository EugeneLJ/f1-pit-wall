# Track C Engineer runtime foundation

## Scope

This runtime connects driver-local observations to advisory Engineer providers,
validates structured output, records tamper-evident provenance, and supports exact
replay. It does not call a Chief model, modify race state, or integrate with the
Harbor sidecar.

## Verified model identifiers

Checked against official provider documentation on 2026-11-14:

- Default Gemini Engineer: `gemini-3.5-flash-lite`. Google lists it as stable,
  low-latency, and structured-output capable. `gemini-3.1-flash-lite` remains
  available but has an announced 2027-05-07 shutdown; 3.5 is its recommended
  replacement.
- Future DeepSeek rival through Verda Inference: request ID
  `deepseek-4-1-flash-1017`. Track C does not implement that rival adapter yet.

Sources:

- <https://ai.google.dev/gemini-api/docs/models>
- <https://ai.google.dev/gemini-api/docs/structured-output>
- <https://ai.google.dev/gemini-api/docs/deprecations>
- <https://docs.verda.com/inference/models/deepseek-4-1-flash-1017/>
- <https://docs.verda.com/inference/quickstart/>

Provider aliases can change. Every live record therefore stores the requested
model ID and returned model revision.

## Modes and failure handling

- `MockRuntimeProvider`: deterministic evidence-grounded test provider.
- `GeminiEngineerProvider`: opt-in live provider using the optional official
  `google-genai` SDK.
- `ImmutableRecommendationStore.replay`: exact observation-hash replay.
- `MISSING`: configured condition has no provider or report.
- `INVALID`: provider, JSON, identity, evidence, or schema validation failed.

Invalid or missing output remains invalid or missing. It is never rewritten into a
valid recommendation. Replay raises when no exact valid record exists.

Live mode reads `GOOGLE_API_KEY` first and then `GEMINI_API_KEY`, matching Google's
documented precedence. Keys are not constructor fields, prompts, records, errors,
or traces. Recursive secret-name redaction runs before persistence.

## Recommendation contract

Each recommendation contains Engineer and driver identity, proposed action,
evidence, local benefit with unit and basis, confidence explicitly labeled
`self_reported`, reasoning summary, and exact observation SHA-256. Evidence paths
must exist in the supplied observation and quote the observed value exactly.
Structured output constrains syntax; semantic validation remains mandatory.

## Observation boundary

The formatter reuses the driver-local projection. It includes the assigned driver's
tyre, component condition, relative pace, current public conditions, public rivals,
legal actions, public team instructions, and only commitments addressed to that
driver. It excludes teammate telemetry, the other Engineer's reasoning, seeds,
future events, simulator internals, and rival private plans.

## Records and replay

Records are append-only through the store API and hash chained. Each entry contains
source, status, observation hash, recommendation, requested model/revision, prompt
hash, sampling settings, token usage, latency, retries, and cost when supplied.
File edits are detected on read. This is tamper-evident, not an OS immutable-file
guarantee; sidecar integration must add trusted filesystem ownership.

## Engineer-usage metrics

The runtime independently records availability, delivery, explicit reference,
action match/difference, and evaluator-supplied outcome/regret. Action agreement
does not prove consumption. A delivered report without an explicit report-hash
reference is `not_observed_do_not_infer_ignored`.

## Evaluation conditions

The harness supports Chief-only, Gemini Lite Engineers, exact recorded reports,
conflicting local recommendations, nominal confidence, and high self-reported
confidence. “Nominal” is not claimed to be calibrated; calibration requires
held-out outcome data. No condition fabricates false telemetry.

## Runtime and cost report

No real API request was made. The local environment had neither the optional
`google-genai` package nor a configured Gemini environment key, so connectivity was
unavailable. Mock/fake-transport tests verify token, latency, retry,
model-revision, and cost fields without network use.

The adapter does not embed mutable prices. `estimated_cost_usd` remains null unless
a transport supplies it. Later evaluation should compute cost from recorded token
counts and a versioned pricing snapshot, avoiding application of a current price to
a historical replay.

The future rival's Verda credential and billing procedure is documented in
`TRACK_C_VERDA_INFERENCE.md`. No Verda key or paid request was used here.
