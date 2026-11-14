# C5 Practice → Qualifying → Race planning prototype

## Status and scope

C5 is an executable, deterministic Track C prototype. It does not edit or call the
authoritative Track B race engine and does not change Harbor or its verifier. All
coefficients, latent conditions, measurements, grid times and expected-points
continuation are synthetic placeholders, not FIA measurements or historical F1
calibration.

The implementation is split into:

- `track_c/pre_race_planning.py`: session contract and transitions;
- `track_c/pre_race_evaluation.py`: equal-information counterfactuals;
- `track_c/schemas/pre_race_contract.schema.json`: machine-readable action/modifier schema;
- `track_c/fixtures/pre_race_scenarios.json`: agent-independent paired cases;
- `analysis/c5_pre_race_eval.py`: reproducible scenario report; and
- `devtests/test_c5_pre_race_planning.py`: isolation and reversal tests.

## Session contract

`PreRaceSession(PreRaceConfig, trusted_seed)` samples latent qualifying grip, tyre
degradation, both drivers' setup response, and every potential noisy test signal in
its constructor. Therefore action order or agent output cannot change the hidden
world. Only the trusted host retains the seed and latent values.

### Practice observation

```json
{
  "contract_version": 1,
  "model_version": "c5-synthetic-1",
  "stage": "PRACTICE",
  "track": {"archetype": "STREET", "data_status": "synthetic_placeholder_not_FIA_calibrated"},
  "remaining_testing_budget": 3,
  "performed_tests": [],
  "beliefs": {
    "qualifying_grip": {"probabilities": {"LOW": 0.333333, "NOMINAL": 0.333333, "HIGH": 0.333333}, "mean": 0, "stddev": 0.816497},
    "tyre_degradation": {"probabilities": {"LOW": 0.333333, "NOMINAL": 0.333333, "HIGH": 0.333333}, "mean": 0, "stddev": 0.816497},
    "driver_preference": {"driver_a": {}, "driver_b": {}}
  },
  "available_tests": [],
  "information_boundary": {
    "latent_conditions_visible": false,
    "unperformed_test_outcomes_visible": false,
    "future_race_events_visible": false
  }
}
```

Belief objects also carry `uncertainty_kind`. Available tests disclose their budget
cost, race-resource opportunity cost, and synthetic measurement accuracy.

Practice actions are exactly:

```json
{"type": "RUN_TEST", "test": "QUALIFYING_PACE_RUN"}
{"type": "RUN_TEST", "test": "LONG_RUN_DEGRADATION"}
{"type": "RUN_TEST", "test": "SETUP_COMPARISON", "driver": "driver_a"}
{"type": "END_PRACTICE"}
```

Budget costs are respectively 1, 2 and 1. The default budget is 3. Tests also add a
small public race-resource cost, so information is not free. Duplicate tests,
driver misuse and budget overruns are rejected atomically. Unperformed potential
signals never enter the observation or trace.

### Qualifying observation and action

The Qualifying observation contains the performed-test summary, posterior beliefs,
public track profile and published setup trade-offs. The only action is:

```json
{
  "type": "SELECT_SETUPS",
  "driver_a": "QUALIFYING_BIASED | BALANCED | RACE_BIASED",
  "driver_b": "QUALIFYING_BIASED | BALANCED | RACE_BIASED"
}
```

Setup changes qualifying time, race pace, tyre degradation and a small reliability
risk proxy. Track archetypes weight those trade-offs differently. Qualifying returns
a unique eight-car provisional grid and this integration DTO:

```json
{
  "schema_version": 1,
  "model_version": "c5-synthetic-1",
  "parc_ferme_locked": true,
  "driver_modifiers": {
    "driver_a": {
      "pace_seconds_per_lap": 0.0,
      "tyre_degradation_multiplier": 1.0,
      "reliability_risk_delta": 0.0,
      "selected_setup": "BALANCED"
    }
  },
  "practice_resource_cost": 0.0,
  "source_hash": "sha256",
  "integration_status": "NOT_APPLIED_TO_AUTHORITATIVE_ENGINE"
}
```

The DTO is intentionally marked unapplied. Track B must explicitly validate and
apply it before any claim that setup affects an authoritative race result.

## Evaluation and representative cases

The evaluator enumerates the complete synthetic latent distribution conditioned on
the public posterior. It never reads the session's realized hidden truth. It reports
all nine setup-pair values and an exact equal-information reference. Exact
enumeration is represented to C4 with a degenerate regret interval
`low == mean == high`; near ties remain unlabelled through the C4 sensitivity gate.

The fixture was selected by scanning seeds in ascending order before any agent
output. It includes:

- long-run evidence that changes the best setup;
- a long-run no-change control;
- qualifying-pace evidence that changes the best setup; and
- a qualifying-pace no-change control.

This supports exploration/exploitation, noisy-evidence misuse and qualifying/race
trade-off analysis. Existing C4/B6 mechanics remain the source for rival reversal,
driver-versus-team objectives, Conditional Swap and Give-back. C5 does not duplicate
those mechanics; a future combined journal should attach the pre-race trace before
the B6 race journal.

## Replay

Each transition records pre/post observation hashes, exact action and action hash.
`replay_metadata()` returns contract/model/config versions, public seed identifier,
trace and trace hash. Trusted replay needs the original protected seed plus action
sequence. The public seed identifier is insufficient to reconstruct hidden values.
The seed identifier exists only in trusted replay/report metadata and is not part of
the agent observation.

## Integration blockers

Track B owns all authoritative integration. It must add, in a versioned adapter:

1. provisional-grid validation and application before `start_prepared_race`;
2. an explicit mapping from `pace_seconds_per_lap` and tyre multiplier to supported
   engine parameters;
3. a decision whether synthetic reliability deltas are unsupported or mapped to a
   published failure model;
4. parc fermé enforcement and a defined pit-lane-start path for post-Qualifying
   changes; and
5. one trusted hash chain covering pre-race replay metadata and the race journal.

Until then, C5 results are standalone synthetic results, not B7 competition results.

## Additional scenario feasibility

### Retire versus Continue

Feasible after Track B exposes current damage/risk, expected remaining points and
component-conservation effects. The action must be irreversible and evaluated on
expected championship value, not a hand-coded retirement penalty. Not implemented.

### Upgrade budget and development timing

High research value but larger scope: it needs persistent budget, lead time,
mutually exclusive development paths, uncertain benefit and opportunity cost across
races. It should be a season-level transition module, not a one-race modifier. Not
implemented.

### Parc fermé and pit-lane starts

The prototype locks the selected setup in its DTO. Actual rule enforcement requires
Track B to define legal post-Qualifying changes, grid-to-pit-lane transformation and
race-start application. No pit-lane start is implemented.

## Commands

```sh
PYTHONPATH=src:. UV_CACHE_DIR=/tmp/c5-uv-cache scripts/py312 \
  -m unittest devtests.test_c5_pre_race_planning -v

PYTHONPATH=src:. UV_CACHE_DIR=/tmp/c5-uv-cache scripts/py312 \
  analysis/c5_pre_race_eval.py --output /tmp/c5-pre-race-report.json
```
