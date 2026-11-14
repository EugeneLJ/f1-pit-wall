# C4 multi-agent coordination failure evaluation

## Scope and boundary

C4 consumes integrated B6/B7 journal v2 entries, Track C Engineer record chains,
trusted runner observations, and separately computed equal-information references.
It does not modify the authoritative engine, run a model, or manufacture a
counterfactual. `ACTUAL_MODEL` is distinct from `SCRIPTED_CONTROL`,
`SYNTHETIC_CONTROL`, and `RECORDED_REPLAY` in every bundle and report.

The implementation is `track_c/coordination_evaluation.py`. The input contract is
`track_c/schemas/coordination_evaluation_bundle.schema.json`; semantic and hash
validation is stricter than the structural JSON schema.

## Failure taxonomy and evidence gate

C4 can label:

- failure to integrate driver-local evidence;
- excessive reliance on an Engineer recommendation;
- unjustified rejection of a useful recommendation;
- a confidence-driven decision change without new evidence;
- a locally rational but team-suboptimal decision;
- failure to reconsider a commitment after circumstances change;
- unnecessary give-back or failure to give back when beneficial; and
- failure to adapt coordination to SC/VSC or rival actions.

These are diagnostic hypotheses until all of the following are present:

1. the exact hash-bound Chief observation, legal action set, Engineer records and
   chosen action;
2. an authoritative-engine reference using the same public inputs and action
   constraints;
3. no future realized event used as an input;
4. expected team-points regret with a finite interval whose lower bound exceeds
   the declared near-tie threshold; and
5. concrete evidence supporting the named hypothesis.

Recommendation disagreement, invalid/missing output, commitment status, provider
failure, timeout, illegal action, and replay failure remain diagnostics. They do
not become strategic failures by themselves. Decision regrets are descriptive;
the season or matched season pair is the sampling unit because decisions within a
race are correlated.

## Engineer information value

For every cited evidence path the analysis checks the actual Chief and Engineer
observation schemas and reports one of:

- `ENGINEER_LOCAL_NOT_IN_CHIEF_SCHEMA`;
- `PUBLIC_ALREADY_AVAILABLE_HIGHLIGHTED`;
- `UNATTRIBUTABLE_OR_SCHEMA_MISMATCH`; and
- a separate `REDUNDANT_ACROSS_REPORTS` flag.

A driver-local recommendation can conflict with the team objective, but that is
only established by the equal-information team-points reference. It is not inferred
from the Engineer identity or persuasive wording.

## Layer 1/2 and rival estimands

Layer 1 is Gemini Chief versus DeepSeek Chief with `CHIEF_ONLY`. Layer 2 changes
McLearn to Gemini Chief plus Gemini Lite Engineer A/B while keeping DeepSeek Chief
unchanged. `compare_layers` requires identical seed identifier, slot assignment,
and rival condition. Production analysis should use same-seed slot-swapped pairs.

`ADAPTIVE` and `FIXED_REPLAY` are different estimands and cannot be pooled. Fixed
replay isolates a response to one recorded rival trace; adaptive competition
measures the joint policies after both can react.

## Ablations

The bundle supports `CHIEF_ONLY`, `GEMINI_LITE_ENGINEERS`,
`RECORDED_RECOMMENDATIONS`, `CONFLICTING_LOCAL_RECOMMENDATIONS`,
`NOMINAL_CONFIDENCE_CONTROL`, and
`HIGH_SELF_REPORTED_CONFIDENCE_CONTROL` through the existing B6 configuration and
broker.

Information-value comparisons reuse the same engine trajectory where legally
possible and reveal only evidence already present in the recorded driver-local
observation. They never fabricate telemetry. Confidence comparisons must keep the
recommendation and factual evidence byte-equivalent while changing only the
self-reported confidence fields. `compare_confidence_controls` enforces that rule.
Prompt bytes, input/output tokens, latency and cost must also be reported: a longer
prompt or changed context is a potential confound.

## Reference contract

An `equal_information_reference` records:

- `reference_action`;
- expected team points for the chosen and reference actions;
- `regret_ci` with `low`, `mean`, and `high`;
- source label, normally `AUTHORITATIVE_ENGINE_PUBLIC_INPUT_ROLLOUT`;
- `uses_future_realization: false`; and
- sensitivity metadata including `near_tie_threshold_points`.

The reference must condition future SC/VSC draws on public history, apply the same
action limits, rival condition and continuation policy, and report Monte Carlo or
exact-enumeration uncertainty. A Chief's internal planner is stored separately as
an approximate model, never as the fair reference. B6's public-input rollout code
can produce candidate values, but C4 intentionally does not call it implicitly.

## Commitments

The report preserves objective, deadline, engine status, feasibility evidence,
reconsideration reason, driver benefit when available, and Constructors' Points
effect. `VIOLATED` means only that the journal recorded a violation. A failure label
requires evidence that give-back remained feasible and beneficial plus positive
team regret. `RECONSIDERED` likewise requires public-state evidence before it can be
called rational or irrational. No arbitrary commitment reward is added. The absence
of team-beneficial give-back cases is reported as coverage missing, not repaired by
tuning a fixture.

## Reproducible commands

Create a matched scripted sample without external calls:

```sh
PYTHONPATH=src:. UV_CACHE_DIR=/tmp/c4-uv-cache scripts/py312 \
  analysis/c4_scripted_sample.py --output-dir /tmp/c4-sample
```

Re-read and compare the bundles:

```sh
PYTHONPATH=src:. UV_CACHE_DIR=/tmp/c4-uv-cache scripts/py312 \
  analysis/c4_coordination_eval.py \
  /tmp/c4-sample/layer1.json /tmp/c4-sample/layer2.json \
  --output /tmp/c4-sample/rechecked.json
```

Run C4 tests:

```sh
PYTHONPATH=src:. UV_CACHE_DIR=/tmp/c4-uv-cache scripts/py312 \
  -m unittest devtests.test_c4_coordination_evaluation -v
```

## B7 integration

1. Run B7 through `integrated.match.run_season` with its observer enabled.
2. Keep each team's Engineer JSONL chain in the trusted record directory.
3. Call `build_bundle_from_run` with the runner result, captured observations,
   exact slot assignment, and verified record chains. Mark live output
   `ACTUAL_MODEL`; never relabel the scripted sample.
4. Produce public-input action values outside the live policy and attach them as
   equal-information references with their uncertainty and sensitivity metadata.
5. Run `summarize_bundle`, then aggregate by matched season/pair. Retain provider
   and tool errors as separate diagnostics.

Current limitation: B7 does not yet emit authoritative reference values or
counterfactual confidence intervals. C4 therefore reports `MISSING_REFERENCE` and
assigns no strategic failure until that evidence is attached. Information-value
classification is schema-level; causal value still requires matched outcomes.
