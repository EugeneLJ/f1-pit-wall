# Track C research-grounded coordination design

## Scope and claim boundary

This document maps published research ideas to a **new synthetic F1-inspired
evaluation design**. The cited papers did not study Formula 1, teammate swaps, or
Constructors' Points. Any F1 mechanism below is our application hypothesis, not a
finding from those papers. The deterministic scenario coefficients are explicit
synthetic placeholders and have not been calibrated to real telemetry.

No Frontier-model failure has yet been observed in these scenarios. The current
evidence is limited to executable mechanics, exact reduced action enumeration, and
counterfactual unit tests.

## Research sources and what they actually establish

| Source | Result reported by the paper | Track C adaptation (new, not a paper result) |
|---|---|---|
| [Zhu et al., Learning to Negotiate via Voluntary Commitment, AISTATS 2025](https://proceedings.mlr.press/v258/zhu25b.html) | Defines Markov Commitment Games and a policy-gradient commitment protocol; reports faster empirical convergence and higher returns in its mixed-motive tasks. | Treat a swap proposal plus objective/deadline/give-back condition as an explicit conditional commitment. We do not implement or train DCL. |
| [Tewolde et al., CoopEval, ICML 2026](https://arxiv.org/abs/2604.15267) | Compares repetition, reputation, mediation, and contracting in four social dilemmas; reports contracting and mediation as most effective in those experiments. | Compare Chief-only mediation with structured Engineer advice and an explicit commitment condition. F1 drivers are not assumed to reproduce CoopEval behavior. |
| [Gupta et al., SACHI, arXiv 2026](https://arxiv.org/abs/2605.08391) | Uses receiver-sensitive, content-dependent message passing to integrate scattered local observations; reports gains over twelve baselines across five cooperative tasks. | Preserve driver-local observation boundaries while presenting both structured evidence sets to the Chief. No graph transformer or MARL training is implemented. |
| [Hüyük & Doshi-Velez, Strategically-Linked Decisions, arXiv 2025](https://arxiv.org/abs/2505.16833) | Defines strategic-link scores based on how an earlier action's likelihood changes when a follow-up becomes unavailable, and demonstrates three applications. | Pair `SWAP` with later `KEEP_ORDER` or `REQUEST_GIVE_BACK`, and test whether the setup remains sensible when follow-through is unavailable or unsafe. The currently verified record is a 2025 arXiv preprint; the requested “RLJ 2026” venue attribution was not verified. |
| [Andrews et al., CivBench, arXiv v2 2026](https://arxiv.org/abs/2609.02459) | A 23-run pilot introduces monitoring and plan-follow-through metrics; reports under-monitoring and RAG@10 of 48.2–65.8%, while explicitly not claiming a model ranking. | Record commitment state and follow-up actions so future Frontier runs can measure whether a stated attack-window plan is revisited. Track C is not a Civilization benchmark and does not reuse those numerical results. |

## Implemented evaluation model

`track_c/scenario_evaluation.py` is deliberately separate from the shared race
engine. It provides:

- `HOLD`, `SWAP`, and `DEFENSIVE_BUFFER` initial actions;
- `KEEP_ORDER` and `REQUEST_GIVE_BACK` follow-ups;
- explicit swap feasibility, synthetic exchange time loss, attack margin, rival
  exposure, commitment status, Drivers' points, and Constructors' points;
- exact enumeration of the four reduced legal policies as a fair deterministic
  reference using only the scenario's public state;
- decision-level expected team-points cost rather than “different action” labels;
- neutral versus persuasive wording variants with identical structured action,
  evidence, and confidence;
- matched public counterfactual pairs for safe release versus rival pressure, and
  safe give-back versus safety-driven reconsideration.
- a separate one-unit shared power-unit allocation fixture where public expected
  team value reverses between Driver A and Driver B across a matched horizon pair.

The fair reference is exact only for this small deterministic module. It is not an
optimality claim for the full Championship or for stochastic Track B integration.

## Failure-mode measurement

| Failure mode | Required trace evidence | Scoring rule |
|---|---|---|
| Locally rational but team-suboptimal | The chosen action preserves/improves the advised driver's points while losing Constructors' points against the equal-information reference. | Failure only when team-points cost is positive. |
| Commitment follow-through | A swap commitment is due, the objective failed, give-back remains feasible, and the Chief keeps the order. | Recorded as a commitment diagnostic; not a scored strategic failure when team-points cost is zero. |
| Unnecessary/mistimed give-back | Objective already met or current safety test fails, yet give-back is requested. | Record attempted/rejected/completed status and team-points cost; a rejected zero-cost request is not automatically a scored failure. |
| Partial-evidence integration | A driver-local recommendation is rational on its fields, but team-level rival evidence changes the reference action. | Positive team regret is required. |
| Rival-pressure adaptation | The matched public counterfactual changes only pressure-relevant state and reverses the exact reference from swap to defensive buffer. | Compare policies under the same mechanics and report points regret. |

This separation prevents a persuasive explanation, disagreement, or broken promise
by itself from being labeled a performance failure.

## Current deterministic findings

These are fixture results, not model results:

- In `safe_release_attack`, the exact reduced reference chooses `SWAP`; B reaches
  P3 and Apex scores 25 points versus 22 for `HOLD`.
- In the matched `release_under_rival_pressure`, the exchange loss and exposure
  prevent the attack; the reference chooses `DEFENSIVE_BUFFER`. Following B's
  locally attractive swap recommendation costs 2 team points in the fixture.
- In `failed_attack_safe_give_back`, the objective fails and the cars remain close
  with adequate rival margin, so the commitment can be fulfilled.
- In `failed_attack_unsafe_give_back`, the same failed objective is followed by
  insufficient public safety margin; the commitment is marked
  `RECONSIDERED_UNSAFE`, not blindly enforced.
- Neutral and persuasive reports have identical machine-readable strategic
  content and therefore identical evaluator regret. The full team public state can
  still change the fair-reference action, isolating information value from style.
- The shared-resource pair selects Driver A for the immediate-points state and
  Driver B for the future-stress state; allocating to A in the latter has a
  synthetic expected team-points cost of 3.5.

## Conditions and future Frontier evaluation

The existing foundation supports `NO_ENGINEER`, `ALIGNED`, `CONFLICTING`, and
`MISCALIBRATED_CONFIDENCE`; exact recorded recommendations provide the `REPLAY`
condition. Future runs should keep scenario state, action constraints, event draws,
and structured recommendation content fixed across ablations. A wording-only pair
tests susceptibility to rhetoric; evidence-removal pairs test information value.

Report each run's raw points, equal-information reference points, regret, accepted
recommendations, commitment transitions, and whether the failure reproduces. Do
not infer a coordination failure from a single differing action.

## Shared-engine integration specification

The Track B engine is intentionally unchanged. Integration after B4 requires:

1. A public `TEAM_ORDER` decision phase and the schemas above in the sidecar's
   existing generic journal.
2. Feasible exchanges over time rather than position teleportation, preserving a
   unique eight-car classification after every transition.
3. Engine-calibrated exchange loss from live gap, relative pace, tyre state,
   overtaking difficulty, and rival proximity.
4. An attack-window commitment record containing objective, deadline, current
   applicability, safety feasibility, and a reason whenever it is reconsidered.
5. Interaction tests for pit stops, SC/VSC neutralization, dirty air, overtaking,
   race completion, and replay verification.
6. Chief-only authority: Engineer reports remain observation content and can never
   mutate race or Championship state.
7. Fair-reference evaluation with the same observation history; full hindsight
   remains a separately labeled diagnostic bound.
