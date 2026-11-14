# Future two-team competition contract

This specification is for integration after Track B B4. It does not authorize live
model calls or shared-engine changes in Track C.

## Competition layers

- McLearn Racing: Gemini Chief Strategist.
- Red Bool Racing: DeepSeek 4.1 Flash 1017 Chief Strategist.
- Layer 1: Gemini Chief versus DeepSeek Chief, without Engineers.
- Layer 2: Gemini Chief plus Engineer A/B versus DeepSeek Chief.

Exact provider identifiers and immutable model revisions must be resolved and
logged at execution time; product names alone are insufficient.

As checked on 2026-11-14, the intended request identifiers are
`gemini-3.5-flash-lite` for the Engineer adapter and
`deepseek-4-1-flash-1017` through Verda Inference for the future rival.
Availability, service status, and the account-currency price must be checked again
at run time. See `TRACK_C_VERDA_INFERENCE.md` for credential and billing details.

## Observation boundaries

Each team receives its own drivers' public telemetry, tyre state, observed pace,
component/resource state, legal actions, public classification, and observable
rival actions. A team cannot read the rival's prompts, recommendations, private
beliefs, intended future actions, provider outputs, or commitment journal. Neither
team sees seeds, future events, future weather, RNG state, or simulator-private
state.

Engineer A/B receive only their assigned driver's permitted local view and public
rival evidence. Their recommendations are visible only to their own Chief. The
Chief alone can submit a simulator action; Engineer output is observation content
and never an executable command.

## Simultaneous decisions

For a shared decision tick, the sidecar emits immutable team-local observations
from one pre-action state and accepts one sealed Chief action per team. Neither team
can observe the other's same-tick action before submission. The engine validates
both, records both, and applies a deterministic conflict-resolution order defined
in public rules. Missing/invalid actions use a predeclared fallback rather than
revealing the rival action and reopening the tick.

## Commitments and journals

Each team has a private commitment journal containing proposal, objective,
deadline, status, feasibility observations, follow-up actions, and reconsideration
reasons. The trusted verifier can replay both journals. Publicly observable vehicle
behavior remains public, but the rival's private promise or reasoning does not.

## Paired evaluation

- Same-seed pairs swap model/team slots and reuse action-independent event draws.
- Fixed-rival replay holds the rival action trace fixed to isolate one Chief's
  response; actions that become illegal are reported rather than silently changed.
- Adaptive-rival evaluation reruns both policies from the same pre-action state and
  reports strategic interaction variance separately.
- Fixed replay and adaptive results must not be pooled as if they measured the same
  estimand.

## Run provenance

Log team and role, provider, exact model/version, prompt/template hash, tool schema
version, temperature and sampling settings, context/token limits, compute budget,
wall-clock budget, input/output tokens, latency per call, retries, normalized and
raw outputs, scenario/config hash, seed identifier available only to trusted
infrastructure, code commit, and container image digest. Engineer calls should run
in parallel when their observations are independent, while preserving deterministic
report ordering in the Chief observation.

## B5-P1 integration boundary and likely conflicts

- B5-P1 must expose public SC/VSC status and observable rival actions without
  exposing the future event schedule. The runtime formatter can project those
  fields only after the public observation schema is stable.
- Track C currently validates `RACE_STRATEGY` recommendations with `PIT/STAY`.
  Compound choice and B5 rival-response actions require additive schema versions;
  they must not be silently coerced into PIT/STAY.
- Sidecar integration needs a trusted private directory for hash-chained records.
  It must not place provider raw output, keys, or private Engineer reasoning in the
  agent-writable/shared volume.
- Parallel Engineer calls must receive one immutable observation snapshot and be
  joined in deterministic Engineer A/B order before the Chief decision.
- The Chief trace needs explicit report IDs or hashes if consumption is to be
  observable. Mere action agreement is insufficient evidence that a report was
  read.
- Track B's action deadline must define timeout behavior for missing or invalid
  reports. The runtime returns an explicit status and never fabricates a fallback.
