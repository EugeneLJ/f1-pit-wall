# M6 Driver Objectives and Team-order Compliance

Status: independent opt-in foundation. The module is synthetic, provisional, API-free, and not integrated into the authoritative 2.1.0 engine.

## Implemented contract

`track_c/driver_objectives.py` computes public WDC standings, signed teammate gaps, races remaining, and public compliance probabilities for exactly `HOLD`, `KEEP_ORDER`, and `REQUEST_GIVE_BACK`. A caller supplies a deterministic random draw. A refusal returns `ORDER_DECLINED` and changes that segment's effective order to `RACE`; it never mutates race state itself.

The provisional fixture uses:

```text
lead_pressure = clamp(max(gap_to_teammate, 0) / 30, 0, 1)
late_pressure = 1 - min(races_remaining, 8) / 8
season_pressure = 0.25 + 0.75 * late_pressure
P(comply) = clamp(0.98 - 0.78 * lead_pressure * season_pressure, 0.20, 1.0)
```

Order adjustments are currently zero. These values are explicit synthetic placeholders, not FIA rules or empirically calibrated driver behaviour. Disabling M6 returns probability 1.0 and consumes no draw.

Agent-visible data contains only standings, teammate gaps, races remaining, supported-order probabilities, and the provisional-profile label. The supplied draw, seed, future events, and simulator-private state are absent. Individual WDC diagnostics remain separate from Constructors' points and reward.

## Offline demonstration

Run:

```bash
cd f1-championship
PYTHONPATH=src:. python3 analysis/m6_offline_demo.py
```

The fixture gives Apex A a 32-point teammate lead with one race remaining and requests a give-back. Its public probability plus the fixed private draw produces a reproducible refusal. The disabled control fully complies. This is a functional example, not evidence of Gemini or any other model failure.

## Required engine hooks (deferred)

1. At an order decision, publish standings and profiles derived from the current public championship state.
2. Identify the affected driver from authoritative order geometry. The exact `HOLD`/`KEEP_ORDER` affected-driver convention must be fixed before integration; `REQUEST_GIVE_BACK` should target the driver asked to return the place.
3. Supply one draw from a dedicated, replayable M6 random stream. Never serialize the draw into the agent observation.
4. Before the existing order planner, replace only a declined supported order with `RACE` for that segment and journal the returned public `ORDER_DECLINED` event. Pit actions and unrelated orders remain unchanged.
5. When M6 is off, bypass its random stream and preserve 2.1.0 behaviour. Replay must verify the deterministic outcome without exposing private randomness.

No authoritative engine, verifier, reward, Reference, or Constructors' scoring code is changed by this module.

## Unresolved contract choices

- Final compliance coefficients and any empirical calibration.
- Authoritative affected-driver semantics for `HOLD` and `KEEP_ORDER`.
- Whether supported order types should eventually have distinct adjustments.
- M6 seed-stream namespace and derivation in trusted replay.
- Commitment-journal consequences when `REQUEST_GIVE_BACK` is declined.

## Future C8 combination

The public profile can later accompany C8's `CONFLICTING_LOCAL_RECOMMENDATIONS`: each Engineer may make a driver-local recommendation using the same public WDC incentive, while the Chief sees both recommendations and the Constructors' objective. Recommendations must remain advisory and must not execute the order or alter compliance. That integration and any live-model evaluation are explicitly deferred.
