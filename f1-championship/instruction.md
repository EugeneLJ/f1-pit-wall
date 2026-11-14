# F1 Pit Wall: constructors' championship

You are the Chief Strategist for **Apex GP** (drivers **Apex A** and **Apex B**)
in an eight-race constructors' championship against Orion, Nova and Vertex.
Maximize Apex's total constructors' points over the whole season.

The championship runs in a separate simulator. You interact with it only through
the `f1ctl` command:

```bash
f1ctl rules                     # all public rules and formulas
f1ctl observe                   # current observation, including decision_id
f1ctl act <decision_id> '<json>'  # submit the action for the current decision
```

Every observation has a `decision_type` and a `decision_id` (e.g. `d001`).
`act` must echo the current `decision_id`. Re-sending an old id is rejected as a
duplicate and a future id as out of order. Rejected requests never change the
championship. There is no reset, rewind, preview, or seed command; the season
runs exactly once.

Each race has two phases:

1. `COMPONENT_DECISION` — before the race, choose `USE` or `REPLACE` for every
   power-unit component of both Apex drivers (legal choices are listed in the
   observation):

   ```json
   {"type":"COMPONENT_DECISION","decisions":[
     {"driver":"Apex A","component":"ICE","action":"USE"}, ...one per driver/component...]}
   ```

2. `RACE_STRATEGY` — three sequential decisions per race, one `PIT` or `STAY`
   for each driver:

   ```json
   {"type":"RACE_STRATEGY","driver_a":"PIT","driver_b":"STAY"}
   ```

Future track status (GREEN/VSC/SC) is seeded and hidden until its decision.
Points from both Apex cars count; the objective is the team's season total,
not either driver's result.

Season rules that carry over from race to race (exact formulas and
coefficients are in `f1ctl rules` under `track_a_model`):

- Component wear grows after every race with the track's `power_unit_stress`,
  regardless of what happens in the race. Worn components make the car slower and
  raise its retirement probability; a component above the wear limit cannot be used.
- Apex has a small pool of free replacement units shared by both drivers. A
  replacement without a free unit costs that driver grid places for that race.
- Tracks differ in power-unit stress, overtaking difficulty, tyre degradation,
  and each team's published pace profile. The full remaining calendar is public.
- Each observation shows both Apex cars' current projections, the cost of a
  replacement, and rivals' public component usage and published pace.
- Retirements and track status come from seeded draws that do not depend on
  your actions. Keep acting until `decision_type` is
`CHAMPIONSHIP_COMPLETE`. An unfinished championship scores zero.

Scoring is done by an isolated verifier that replays the simulator's own
sealed record. Files you write cannot affect the score.
