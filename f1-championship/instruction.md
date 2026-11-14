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

2. `RACE_STRATEGY` — 14 sequential decisions per race (a 45-lap race, one decision
   every 3 laps from lap 3 to lap 42). For each driver choose
   `STAY`, `PIT_SOFT`, `PIT_MEDIUM` or `PIT_HARD` (a pit stop fits the named
   compound):

   ```json
   {"type":"RACE_STRATEGY","driver_a":"PIT_HARD","driver_b":"STAY"}
   ```

   Softer compounds are faster but degrade faster; every compound falls off a
   cliff once it is older than its published life. Each car must race on at least
   two different compounds (the starting compound counts) or it receives a time
   penalty at the finish. Pit-lane loss depends on the track and is lower under
   VSC and SC. Apex has one pit crew: if both cars pit at the same decision, the car
   that arrives second on the road waits for the first. New tyres are slower on
   their first lap (more so for harder compounds). The observation shows this
   track's pit losses and which car would be serviced first.

Safety Car (SC) and Virtual Safety Car (VSC) periods are seeded and hidden until
they happen. Their start probabilities and duration distribution are published in
every race observation (`event_model`), together with the current status and how
many segments it has lasted so far. Under SC the field closes up and nobody
overtakes; under VSC everyone slows equally. Stops are cheaper under both, but a
stop still costs track position.
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
