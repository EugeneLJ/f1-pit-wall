# C5 integration contract — Practice → Qualifying → Race (proposal v1, B8)

**Status.** Owner of the shared engine: the integration branch. Track C develops C5 in `track_c/` only and **must not edit** `src/f1pitwall/**`. C5 is integrated after its interface and tests are stable, behind a new opt-in version (proposed **2.2.0**). **Nothing in this document is implemented in the shared engine yet.**

## Phase machine (per race, per controlled team; sealed simultaneous ticks as in 2.0.1)

```
COMPONENT_DECISION → PRACTICE (k ticks) → QUALIFYING (1 tick) → RACE_STRATEGY (14 ticks) → next race
```

- `decision_type` values `PRACTICE` and `QUALIFYING` are added to contract v2.
- Old phases are unchanged.
- Journal v2 already stores `decision_type` generically.

## PRACTICE

**Observation adds** `practice`:
- `{session_index, sessions_total, laps_budget_remaining, known_setup_estimates: {setup_id: {mean, ci95, laps_observed}}, tyre_wear_estimates: {...}}`;
- the published noise model (the observation-noise SD per lap and how it shrinks with laps).

**Action:** `{"type":"PRACTICE", "driver_a": {"program": "SETUP_TEST|LONG_RUN|QUALI_SIM", "setup_id": str, "laps": int}, "driver_b": {...}}`.

**Engine contract:**
- A program consumes laps from a per-weekend budget.
- It returns noisy, seeded (action-independent noise stream) measurements of the true setup pace effect and tyre wear.
- More laps on one setup means a smaller CI. This is the information-gathering choice.
- The true effects come from the hidden per-race draw. Only the published prior and the measurements are public.

**Required trade-off:** laps spent on long runs (tyre information) are not available for setup comparison.

## QUALIFYING

**Observation adds:**
- `qualifying.setup_options` with the practice estimates;
- the parc-fermé rule: the setup chosen here is fixed for the race (synthetic unless verified).

**Action:** `{"type":"QUALIFYING", "driver_a": {"setup_id": str, "run_plan": "ONE_RUN|TWO_RUN"}, "driver_b": {...}}`.

**Engine contract:**
- Qualifying time = base pace + true setup one-lap effect + seeded noise.
- The provisional grid is the qualifying order.
- **The same setup has a different race effect** (one-lap vs long-run pace and tyre degradation multiplier). That creates the grid-versus-race trade-off.

**Penalties after qualifying.** Grid penalties are applied **after** the provisional grid, using `pu_rules.fia_grid(qualifying_order, penalties)` (B2.5.4b) under 2.1.0+, or the legacy drop rule under 2.0.1.

## RACE setup modifiers

`race_config` gains `setup: {car: {pace_offset_sec_per_lap, deg_multiplier_factor}}`, which C5 computes from the qualifying choice.
- The engine applies them **additively** to the published pace and degradation.
- With no C5 config the race is bit-identical to 2.0.1/2.1.0 (a test will be required).

## Championship transition and persistent resources

- **Practice laps** do not affect PU wear: wear stays action-independent, as in Track A.
- **Tyre sets:** if C5 adds tyre-set allocations, they are a new per-driver resource in `resource_inventory` (`tyre_sets:SOFT`, …), with conservation tests.

## Journal and replay

- Each PRACTICE/QUALIFYING tick is a normal v2 resolved entry.
- Measurement noise must come from a seeded stream keyed by (race seed, team, driver, session, setup, lap index), so replay recomputes identical observations.
- The verifier needs no new trust assumptions.

## What C5 must deliver before integration

1. A pure function `c5.simulate_practice(public_state, action, rng_key) -> measurements`.
2. A pure function `c5.qualifying(public_state, actions, rng_key) -> order, times`.
3. A pure function `c5.race_modifiers(choice) -> setup config`.
4. A fixture with every coefficient marked synthetic, or verified with a source.
5. Tests for: determinism; no leakage of the true effects; the information value of practice (more laps give a smaller CI); the qualifying/race reversal (a setup better for the grid but worse for the race exists naturally); conservation.

The engine owner then wires the phases, the observations and the journal.

## Not decided

- Number of practice sessions and the lap budget.
- Whether rivals run practice (proposal: rivals use the published default setup, no information).
- Whether sprint formats are included (proposal: no).
