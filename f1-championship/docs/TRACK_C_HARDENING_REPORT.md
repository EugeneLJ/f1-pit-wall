# Track C failure-oriented benchmark hardening

## Outcome

Track C now separates observed behavior, equal-information reference behavior,
deterministic regret, sensitivity, and diagnostic attribution. The work remains an
independent synthetic evaluator. It does not change the shared race engine,
sidecar, verifier, or Track B.

## Mechanics audit

### Deterministic points versus expected regret

The existing evaluator produces one deterministic classification. Its point gap is
now exposed as `deterministic_points_regret`. `expected_points_regret` is explicitly
`null`; the old `expected_team_points_cost` remains only as a compatibility alias.
No stochastic expectation, confidence interval, or calibrated F1 probability is
claimed.

The same limitation applies to the shared-resource fixture: its values are declared
synthetic public expected-value inputs, not estimates learned from race data.

### Swap time loss

In the frozen one-step evaluator, swap loss depends on teammate gap, overtaking
difficulty, and rival proximity. It changes the attack-margin threshold and is
reported as elapsed loss; classification changes only when a pass/exposure
threshold is crossed. It is not a continuous vehicle-physics simulation.

The new sequential interface additionally applies exchange loss immediately to the
public gap ahead and gap behind. Each subsequent lap evolves those gaps using the
public pace relationships. Full engine integration still needs actual lap times,
dirty air, safe exchange locations, failed/delayed orders, and interactions with
pit stops and SC/VSC.

### Commitment time and deadline

`SequentialCoordinationEpisode` advances exactly one public lap at a time and
records:

- `ACTIVE`;
- `OBJECTIVE_FAILED_BEFORE_DEADLINE`;
- `OBJECTIVE_ACHIEVED`;
- `DEADLINE_EXPIRED`;
- `COMMITMENT_FULFILLED`;
- `COMMITMENT_VIOLATED_WHILE_BENEFICIAL_AND_FEASIBLE`;
- `RATIONALLY_RECONSIDERED`, with `rival_proximity` or
  `drivers_not_adjacent` as a reason;
- `CONDITION_LAPSED` when the attack objective was achieved.

The observation contains current state only. It contains no future event schedule,
seed, or future rival action.

### Reference limitation

The legacy reduced `fair_reference` enumerates four deterministic policies using
the complete current public scenario and known deterministic transition rules. It
does not consume a hidden future observation, but it effectively has a perfect
model of the synthetic transition. It is not a fair stochastic Track B reference.

After integration, the equal-information reference must act online from the same
observation history as the Chief, use only a public belief model for unobserved
future events and rival actions, and replan after each new observation. A
full-realization replay or hindsight tree must be labeled separately.

### Attribution boundary

A locally suboptimal decision means only that the selected policy loses points to
the equal-information reference. A partial-evidence integration hypothesis also
requires evidence that the action followed a driver-local recommendation and
ignored team-relevant public evidence. `build_failure_record` keeps these fields
separate and never infers the hypothesis from regret alone.

## Unselected synthetic design grid

The generator takes the Cartesian product of declared ranges for teammate gap,
relative pace, tyre-age advantage, gaps ahead/behind, rival closing pace, attack
window, and overtaking difficulty. It creates all 5,832 states before computing an
optimal action or failure label. These are reasonable synthetic ranges for stress
testing; their frequencies are **not estimates of real F1 prevalence**.

### Reference action distribution

| Reduced reference action | Count | Grid frequency |
|---|---:|---:|
| HOLD | 3,529 | 60.51% |
| SWAP | 1,170 | 20.06% |
| DEFENSIVE_BUFFER | 1,133 | 19.43% |

### Diagnostic occurrence

| Diagnostic | Count | Grid frequency |
|---|---:|---:|
| Near tie (top two deterministic point totals differ by at most one) | 3,692 | 63.31% |
| Individual gain / team loss | 1,133 | 19.43% |
| Ambiguous Engineer conflict (SWAP/HOLD differ by at most one point) | 4,662 | 79.94% |
| Give-back feasible after failed objective | 2,113 | 36.23% |
| Give-back unsafe after failed objective | 2,549 | 43.71% |
| Give-back benefits Driver A but is team-points neutral | 2,113 | 36.23% |
| Give-back strictly benefits Constructors' Points | 0 | 0% |

Across all non-reference actions there are 4,606 positive deterministic regrets.
Their magnitude is min 1, median 2, p95 3, max 3 points. Expected-regret
distribution is unavailable because this module has no stochastic outcome model.

The zero team-beneficial give-back count is a model limitation, not a result to
hide or tune away. The current reduced transition can restore individual order but
does not simulate enough post-give-back racing for a team-points gain to emerge.

## Counterfactual validity and sensitivity

The existing hand-authored pairs remain regression fixtures. The generator adds
unselected coverage rather than replacing them. Decision sensitivity perturbs six
public fields by ±10% one at a time and reports reference-action reversals. A
sensitive or near-tie choice can still be valid; it should be reported with weaker
attribution than a robust high-regret decision.

Every failure record contains:

1. observed action;
2. equal-information reference action;
3. deterministic points regret and unavailable expected regret;
4. local counterfactual sensitivity;
5. a diagnostic hypothesis, if warranted;
6. concrete evidence supporting that hypothesis.

Rejecting an Engineer, reconsidering a commitment, or choosing a different action
is not itself a failure.

## Engineer ablations

The five preserved conditions are No Engineer, Aligned, Conflicting,
Miscalibrated Confidence, and exact Recorded Replay. Neutral and persuasive
recommendation variants keep proposed action, evidence, and confidence identical,
isolating expression style. Information-value comparisons instead change which
truthful driver-local public fields are available while retaining the underlying
scenario and never fabricating false evidence.

## Exact shared-engine changes required after B4

1. Add `TEAM_ORDER` and `TEAM_ORDER_FOLLOW_UP` phases to the existing public phase
   machine and generic journal.
2. Represent team-order execution over real laps, including safe exchange
   locations, delay/failure, actual elapsed time, classification permutation, dirty
   air, and overtaking.
3. Persist commitment objective, deadline, status, feasibility, and reconsideration
   reason in team-local state and replay it in the trusted verifier.
4. Expose live gaps, observed relative pace, tyre state, rival proximity, and legal
   actions without future SC/VSC, weather, rival policy, or random draws.
5. Integrate team orders with pits, double stacking, SC/VSC neutralization, finish
   timing, driver points, and Constructors' Points.
6. Provide an online equal-information reference with the same public history and
   action timing; keep hindsight evaluation separate.
7. Add a public probabilistic outcome model or repeated seeded paired runs before
   reporting expected regret.

## Frontier blockers

- No Track B/shared-engine vehicle movement or trusted team-order replay.
- No calibrated or public stochastic outcome model, so expected regret is absent.
- No natural F1 scenario distribution; the grid frequencies are design coverage.
- No strict team-beneficial give-back case in the current reduced mechanics.
- No live model/provider harness, token/runtime logger, or two-team simultaneous
  action protocol yet.
- No evidence yet of any Frontier coordination failure.
