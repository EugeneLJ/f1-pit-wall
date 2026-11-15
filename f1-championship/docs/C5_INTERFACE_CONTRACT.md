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

## Contract amendments

The isolated Track C v1 implementation keeps the action shapes above and makes these
lower-level choices explicit. These amendments do not change the shared engine or a
published benchmark.

1. **Defaults.** There are exactly two one-based practice sessions and a **24-lap
   weekend budget per controlled driver**, shared across all programs/setup options.
   Zero-lap actions are legal because both drivers are required in each action.
   Actions cannot consume PU wear or inventory, and v1 adds no tyre-set resource.
   Rivals use the neutral `balanced` setup with no practice information. Sprints are
   not included.
2. **Programs and estimates.** `SETUP_TEST` measures long-run setup pace,
   `QUALI_SIM` measures one-lap setup pace with its published independent noise
   level, and `LONG_RUN` measures only the tyre-degradation multiplier. Thus a lap
   spent on tyre information is not a setup-pace comparison lap. Hidden effects are
   shared within one team/weekend; both drivers contribute evidence. Public
   `known_setup_estimates` is nested by setup and pace metric, each with
   `{mean, ci95, laps_observed}`; `ci95` is the half-width. `tyre_wear_estimates`
   uses the same shape. Gaussian precision weighting combines prior observations
   with each batch's published per-lap observation SD.
3. **State transition.** `initial_public_state` constructs a fresh practice state.
   `simulate_practice` returns `{measurements, state}` rather than relying on caller
   mutation: `state` is the next fresh public state, including absolute lap indices,
   history, accounting, and phase. All measurements and public observation fields
   are JSON serializable and exclude keys/noise values.
4. **Qualifying.** `TWO_RUN` returns the minimum of two independently keyed runs;
   `(time, public_car_id)` breaks exact ties. A direct team action is accepted, and a
   `team → QUALIFYING action` map supports sealed simultaneous controlled teams.
   Missing teams are neutral rivals. The output has only `order` and `times`; grid
   penalties and `pu_rules.fia_grid` are intentionally not reimplemented.
5. **Parc fermé.** Trusted infrastructure uses `make_parc_ferme_choice` to produce a
   frozen, private `ParcFermeChoice` containing the secret key and car→setup tuples.
   `race_modifiers` requires this envelope, not a mutable public action, and exposes
   only the computed setup config to the engine owner. `race_modifiers(None)` returns
   `{}` to represent no C5 config; the neutral setup returns exactly zero pace offset
   and factor 1.0 for each selected car. Race arithmetic remains additive for pace
   and multiplicative for degradation.

The C5 reference is a public-prior/practice-estimate heuristic only. It uses marginal
Gaussian variance reduction for practice allocation and posterior-mean provisional
positions/expected F1-point values for qualifying. It is not a reward policy,
reference planner change, or causal estimate of true race points.
