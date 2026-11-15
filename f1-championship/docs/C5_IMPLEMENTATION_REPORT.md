# C5 implementation report — Practice → Qualifying → Race setup

**Status:** isolated Track C v1 module, based on `39e4d16`
(`origin/feature/reference-2.1.0`). **No shared-engine or Harbor integration is
present.** Existing benchmarks 1.1.0, 2.0.1, and 2.1.0 are untouched. No API,
Harbor, or paid model calls were made, and no env files or credentials were read.

## What was built

New package `track_c/c5/`:

- `model.py`: fixture loading/provenance checks, setup/metric validation, and
  recursive public-data secrecy checks.
- `core.py`: public weekend state, practice transactions, Gaussian posterior
  estimates, keyed truth/noise draws, qualifying, public observations, and frozen
  parc-fermé race modifiers.
- `reference.py`: bounded public-only practice-information allocation and
  qualifying setup evaluation for later analysis, not a reward or reference policy.
- `__init__.py`: the delivered public API:
  `simulate_practice`, `qualifying`, `race_modifiers`, `initial_public_state`,
  `public_observation`, `load_model`, `make_parc_ferme_choice`,
  `practice_reference`, `qualifying_reference`, and `reference_decision`.

New fixture: `track_c/fixtures/c5_setups.json`, with the required setup options,
priors, noise model, lap budgets, per-archetype references, and explicit synthetic
provenance. New helpers and regressions are under `devtests/`.
`docs/C5_INTERFACE_CONTRACT.md` retains the original contract and adds explicit
**Contract amendments** rather than silently changing it.

## Decided defaults and behavior

| Item | v1 decision |
|---|---|
| Practice sessions | **2**, numbered 1 and 2 |
| Budget | **24 laps per controlled driver per weekend**, across all programs/setup choices |
| Programs | `SETUP_TEST`: long-run pace only; `QUALI_SIM`: one-lap pace only; `LONG_RUN`: degradation multiplier only |
| Measurement model | Independent zero-mean Gaussian observation noise; Gaussian precision-weighted prior/history updates |
| Estimate confidence | `ci95 = ci95_z / sqrt(posterior_precision)`, where prior precision plus observed-lap precision forms the denominator |
| Hidden effects | Team/weekend/setup/metric shared within a team; both drivers add evidence to the same estimate |
| Lap indexes | Absolute within each driver's weekend, retained between sessions; zero-lap idling is legal |
| Qualifying | `ONE_RUN` or best-of-`TWO_RUN`; exact `(time, car ID)` ordering; noise keyed per car/run |
| Rivals | Neutral `balanced` default and no practice information |
| Qualifying grid | Provisional only; C5 does **not** calculate or apply grid penalties |
| Race setup | Frozen private `ParcFermeChoice`; additive pace offsets and multiplicative degradation factors supplied only to the engine owner |
| Neutral guard | `race_modifiers(None) == {}`; `balanced` gives exactly `0.0` seconds/lap and `1.0` factor per selected car |
| Resources | No PU-wear/inventory modifications; no tyre-set allocation in v1 |
| Sprints | Not included |

A practice transaction returns `{measurements, state}`. The next public state is a
fresh JSON value containing public batch summaries, exact budgets/lap indexes,
ordered two-session history, estimates, and phase. Validation recalculates this
accounting and posterior state from history. Invalid programs, setups, lap counts,
duplicate measurements, duplicate team/seat ownership, extra team cars, malformed
actions, stale counters, and over-budget actions are rejected without mutating
inputs.

## Keyed determinism and secrecy

Practice observation draws use SHA-256 over an ordered key containing the private
`rng_key`, domain, weekend, team, driver, session, setup, metric, and absolute lap
index. Qualifying uses a separate domain and car/run index; hidden truth uses its
own domain and no driver/action metric history. Two independent 64-bit digest
segments feed a Box–Muller transform. There is no process-global RNG or reliance on
Python's randomized `hash()`.

Consequently repeated calls are byte-identical, unrelated drivers/teams/actions do
not consume another stream, sequential sessions do not reuse lap keys, and trusted
replay can recompute any value from the same seed/action history. Only sampled batch
means and public SD/error estimates leave the module. Priors, intervals, and noise
models are public; hidden effects, the key, and normal draws are not emitted.
Public observers reject secret-shaped fields recursively.

Parc-fermé setup selection is a frozen dataclass of car/setup tuples plus a private
key omitted from `repr`. The raw mutable public qualifying action is not accepted
by `race_modifiers`. Owners must preserve that envelope privately, not place it in
journal observations or reports.

## Coefficient provenance

**Every coefficient is labelled synthetic.** No value is a fitted circuit
coefficient, an official 2026 parameter, or a coefficient chosen to make a model
fail. No verified public-source coefficient is claimed (`sources: []`).

- `balanced`: zero qualifying/race pace offsets and degradation factor 1.
- `low_drag`: prior qualifying mean −0.42 s (SD 0.08), long-run +0.005 s/lap
  (SD 0.06), degradation ×1.25 (SD 0.035).
- `high_downforce`: +0.30 s (SD 0.10), long-run −0.025 s/lap (SD 0.07),
  degradation ×0.78 (SD 0.045).
- Practice SD per lap: 0.18 s long-run pace, 0.08 s qualifying pace, and 0.03 for
  degradation. Qualifying contributes 0.06 s/run. These are synthetic uncertainty
  coefficients, not calibrated sensor error.
- Base reference degradation-time losses by archetype are synthetic:
  mixed 0.050, street 0.062, high-speed 0.045, high-degradation 0.070, and
  wet-prone 0.058 seconds/lap.
- The reference heuristic uses a synthetic 42-lap horizon, F1-like point examples,
  and two synthetic points per externally calculated grid-loss place. It is not a
  reward formula or official 2.2.0 scoring contract.

The fixture naturally produces a qualifying/race reversal without a test-only
special case: in the eight-car public field, Apex A moves from provisional P3 with
`balanced` to P1 with `low_drag`, while its estimated race points are lower under
the long-run/degradation model. The regression tests both model evaluation and a
seeded provisional grid rather than injecting a winning test outcome.

## Public-input reference

`practice_reference` greedily selects the bounded batch with the highest marginal
published Gaussian variance reduction, weighted by public race-horizon relevance.
It does not peek at keyed truth or future draws and emits a legal PRACTICE action.
`qualifying_reference` evaluates every setup using posterior public means, neutral
rivals, provisional position, and estimated points minus explicit synthetic grid
loss, then chooses deterministically with setup ID tie-breaking. It returns a legal
QUALIFYING action. This is a **small heuristic decision reference**, not an optimal
planner, calibrated points predictor, existing reference-policy modification, or
causal model evaluation.

## Test list and exact results

New `devtests/test_c5_practice.py` and `test_c5_qualifying_race.py` cover:

- exact replay, non-mutation/output isolation, and per-domain key stability;
- driver/teammate/team/action independence and absolute cross-session lap streams;
- deterministic multi-team qualifying, complete permutations, `(time, ID)` order,
  and best-of-two aggregation;
- no recursive secret fields or giant seed-like integers in public documents;
- rejection of injected hidden state and private raw parc-fermé actions;
- CI monotonicity over **64 independent keys**, published precision/sample error,
  and long-run-versus-pace information separation;
- exact/zero budgets, nonnegative conservation, invalid programs/setups/laps/actions,
  history/counter tampering, duplicate measurements, and third-session rejection;
- duplicate team/seat identities and extra same-team cars;
- frozen parc-fermé, neutral/no-C5 identity guards, and model-versioned archetypes;
- natural grid-versus-race reversal, explicit reference grid loss, and legal
  reference actions.

Final commands:

```bash
cd f1-championship
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s devtests -p 'test_c5_*.py' -v

PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s devtests -p 'test_*.py'

cd ..
PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s tests -p 'test_*.py'
```

Results:

```text
C5 targeted: Ran 26 tests in 0.179s — OK
Full devtests: Ran 260 tests in 101.278s — OK
Legacy suite: Ran 35 tests in 1.702s — OK
Final failures: none
```

Two review-discovered history/ownership issues and one fixture-unwrapping issue
were corrected before these final runs: teammate measurement replacement, extra
same-team cars, and qualifying noise SD normalization.

## Exact engine-owner wiring for opt-in 2.2.0

These steps are intentionally **not** implemented on this branch:

1. Add an opt-in 2.2.0 configuration. Initialize `initial_public_state` from public
   team/weekend/car/base-pace data after `COMPONENT_DECISION`; derive and retain
   the team's secret but reproducible RNG key only in trusted state. Require no C5
   setup (or `None`) for all prior-version configurations.
2. Extend the existing phase machine, per controlled team, to
   `COMPONENT_DECISION → PRACTICE(1) → PRACTICE(2) → QUALIFYING → RACE_STRATEGY`.
   Use existing sealed simultaneous submissions and validate the existing action
   shapes plus C5's exact-field/lap rules. Preserve driver/team/season IDs needed
   for keyed replay.
3. Return `public_observation(public_state)` for the phase. Journal each
   PRACTICE/QUALIFYING action as a normal v2 entry with the sealed action and
   before/after observation hashes. Use the resulting public `state` to carry
   history, not hidden truth or RNG state; exclude the private RNG key, true draws,
   and `ParcFermeChoice` from every observation/export.
4. At qualifying, collect all controlled teams' actions into the supported
   `team → QUALIFYING action` map. Invoke `qualifying`, retain only its provisional
   `order` and `times`, and do not apply grid penalties in Track C.
5. Apply penalties afterward in the engine owner: `pu_rules.fia_grid` under 2.1.0+
   or its existing legacy rule. Create a frozen private parc-fermé envelope from
   the sealed setup choices and derive `race_modifiers` only there. Map the setup
   config into race configuration, adding pace seconds/lap and multiplying the
   existing degradation multiplier.
6. Trusted replay must reconstruct each phase/action from the same private seed,
   recompute keyed lap/run streams, reject malformed or duplicated evidence, and
   recompute all observation hashes and final race standings exactly. The verifier
   needs no new trust assumption; it must not trust a measurement or score claimed
   by the agent.
7. Add integration tests proving no-C5 configurations are byte-identical to the
   corresponding 2.0.1/2.1.0 run and neutral-setup configs are neutral across the
   entire race. This branch supplies only the pure identity guards and leaves that
   bit-level engine test to the owner, as required by the no-shared-engine boundary.

## Known limitations

- Measurements are compact synthetic batch estimates, not physical tyre/track or
  per-lap telemetry. The Gaussian prior and update are modelling choices, not
  calibrated posterior truth.
- Setup true effects are team/weekend shared; per-driver setup learning,
  weather/setup interactions, sprint formats, and tyre-set inventory are outside v1.
- C5 does not evaluate official reward, actual finishing position, SC/VSC, pit
  strategy, or race points. Provisional times are not penalized grids, and heuristic
  reference grid-loss points are not the engine's penalty algorithm or score.
- The reference's deterministic posterior-mean ranking is optional later-eval
  tooling; it is not necessarily information-optimal and has not been compared to a
  live Chief/model.
- Reproducibility relies on trusted integration retaining the same secret key and
  exact ordered key parts for this contract version. Any renamed version/domain
  requires explicit migration/versioning.
- No engine integration, official 2.2.0 schema, reward, verifier, Strong Reference,
  live model run, or paid calibration was performed.
