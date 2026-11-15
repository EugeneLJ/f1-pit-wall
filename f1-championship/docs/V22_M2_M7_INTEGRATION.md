# M2/M7 isolated integration contract (proposal, not official 2.2.0)

This document defines how the isolated `track_c/v22` modules can later be wired by
an engine owner. **Nothing on this branch activates 2.1.0, Harbor, C5, M1/M3/M4/M5/M6,
a reward, a verifier, or a reference policy.** The frozen demo UX and historical
journals are untouched.

## Opt-in configuration

```python
from track_c.v22 import V22Config
assert V22Config() == V22Config(m2_enabled=False, m7_enabled=False)
```

The immutable flags are descriptive and default-off. The authoritative owner must
call a module **only** if the corresponding 2.2.0 opt-in config field is true. When
false, it must not draw/append types/weather, change actions, or add observations;
the 2.1.0 path and journal must therefore run unchanged. A genuine owner-level
bit-identity test is required during integration, not claimed here.

Every fixture is marked `synthetic_only`. Hidden assignment/bias/seed/private-rain
state belongs to the owner's sealed/private context. `M7-disabled` and
`M2-disabled` projections never expose those values.

## M2 — hidden rival tendencies

### Owner flow per rival and race

1. Call `draw_tendency(race_seed, race_id, car)` once. Keep the result private and
   fixed for this race. Do not resample after action, observation, replay, or
   future evaluation. IDs are stable per car/race; identical types may be assigned
   to multiple cars.
2. Use `reaction(type, context)` only as a directive. Its context requires owner
   booleans `m3_active`, `defence_applicable`, and `attack_legal`, plus public
   `gap_ahead`/`lap_index`/`car`. The module does **not** calculate proximity,
   admit illegal actions, grant overtakes, or add pace modes. `DEFEND` precedence,
   `OPPORTUNIST` active attack, `CONSERVATIVE` no-attack above the threshold, and
   baseline fallback are exhaustively defined.
3. Resolve the directive and its race effects in the authoritative engine. Expose
   only a realized reaction and genuine lap residual after the public segment ends.
   A failed/cancelled intent is not an attack attempt.
4. Produce public event records with unique event IDs, context, resolved reaction,
   and lap residual. `public_projection(prior, events)` uses a joint reaction and
   residual likelihood; it returns causal evidence and a derived categorical
   posterior, not the actual assignment or privileged policy identifier.
5. For decisions, evaluate **every owner-declared legal action** through
   `expected_values(belief, values)`. For each action and each hypothetical type,
   supply finite `{mean, se}` under public information. The module computes the
   posterior mixture and outputs near-tie first, then uncertain if its declared
   uncertainty cannot clear the 0.5 threshold, then separated. Never replace that
   partial-posterior mixture with the live assignment.

### M2 boundary and required gap resolution

The full S1 meaning depends on **M1 and M3**, which this branch deliberately does
not implement. `m3_active` is an owner-supplied condition, not computed by M2.
Likewise, an actual defence and its public evidence must be defined by the owner;
without it, a `DEFEND` directive cannot defend anything. The current micro-support
validates deterministic behavior, posteriors, and generic legal-value comparison.
Claims of actual engine optimal-response changes must wait for owner-produced
rollouts on matching legal action sets. Synthetic action-value tests are explicitly
labelled, never sold as official engine utility.

### Public/private journal mapping

- Public: actual resolved reaction, public event ID/context/lap residual,
  likelihood version, history hash, and posterior derived by the analysis owner.
- Private: type assignment, RNG key, raw type/lap draw, hypothetical-type live
  match, rejected private directive, and any actual hidden future value.
- Replay: draw the same assignment once, regenerate directives/public events from
  sealed actions, and verify event IDs, observation hashes and replay outputs.
  Replay must reject duplicate or asymmetric evidence.

## M7 — weather and wet compounds

### Boundary order

Use the invariant order **observation → simultaneous actions → pit effects →
3 racing laps/events → next rain/wetness**. The rival's simultaneous choice becomes
visible only in the next observation, never before its resolution.

- `weather_schedule` generates the complete private Markov rain/wetness path on the
  owner side. Races have eight boundaries and 3 laps per boundary in the micro-race.
  Action order, skipping a stop, or evaluating another action cannot change it.
- `forecast` exposes only lead-reports from Markov means plus independently keyed
  Dirichlet report noise. The concentration multiplier is lead, so report variance
  shrinks as lead increases (the proposal's exact wording). These are noisy reports,
  **not automatically a calibrated true-weather posterior**. Reference value uses
  the public forecasts; at a final empty horizon it uses the observed current
  condition, never a fabricated future.
- `public_observation` exposes current observed condition, forecasts, public cars,
  and completed segment action/lap history. It does not expose seed, exact hidden
  wetness/path, bias assignments, incident draws, or future rival choices.
- `m7_legal_actions` is `STAY`, `PIT_SOFT/MEDIUM/HARD`, and
  `PIT_INTERMEDIATE/WET` independent of weather. Hiding legality would leak future
  conditions. Slicks may be legal but slow/risky; wet tyres can also be poor in dry.
- Pit first resets fresh tyres/age and incurs synthetic pit/warm-up cost. Each lap
  applies published offset/wetness degradation and keyed spin/retire incidents.
  Fitted tyres count as used **only after a raced lap**. An action branch and replay
  use the same exogenous incident keys; actual pit/action choices affect times,
  wear, risk and classification.
- Rival early/on-time/late wet switching uses its hidden local bias and actual
  wetness, never future rain. Its behavior is revealed only by the next boundary.
  Bias changes preferences, not tyre physics. Wet-to-dry switching is unbiased.

### Two-compound and neutralisation rules

`finish_penalty(compounds_raced)` applies wet-use exemption first, then requires two
distinct dry compounds. The micro-race retains the documented normal-finish **+20
seconds** from B1 rather than silently modifying an existing mechanic. Contract
language mentioning DQ/30 seconds for suspension is a **conflicting/unresolved
item**: no suspension/red-flag process exists here and no 30-second branch is
invented. The owner must resolve that future 2.2.0 sanction explicitly before
publishing it.

`neutralisation_multiplier` is only an adapter for the existing SC/VSC process.
It multiplies hazards by rain-state configuration and renormalizes/clips to a valid
simplex. This branch does not start a new SC/VSC/red-flag generator or use future
weather for a hazard decision. Grouping/heavy-rain details beyond that adapter are
owner work.

### Replay and public/private mapping

`replay(seed, action_history, race_id)` returns the private owner state, pre-action
public observations, and public classification. Replay verifies exact repeatability
of rain, wetness, forecasts, rival biases, incidents, pit/finish legality, outcomes,
and times. The authoritative integration must also hash and compare sealed
before/after observations/actions, detect altered actions/evidence, and never trust
claimed weather/results.

## Natural versus synthetic status

The eight-boundary, two-car micro-race is a **synthetic contract tool**, not a track,
driver, season, or official reward model. Natural-frequency counts mean rows from
predeclared seeds, not naturally occurring F1 events. The M2 decision-value objects
and M7 forecast heuristic are explicitly synthetic reference choices, not Gemini
policies, Rival M1 behavior, official points, or matched model runs.
