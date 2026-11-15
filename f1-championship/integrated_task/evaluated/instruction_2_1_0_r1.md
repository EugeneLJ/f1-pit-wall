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

## Integrated mode (benchmark 2.0.1, SOLO_COORDINATION)

This version adds team orders, conditional commitments and two race engineers.
Everything above still applies; decision ids look like `t001`.

Every `RACE_STRATEGY` action must also carry a `team_order`:

```json
{"type":"RACE_STRATEGY","driver_a":"STAY","driver_b":"PIT_HARD",
 "team_order":{"order":"RACE"}, "consumed_reports":["<record_hash>", "..."]}
```

- `RACE` — no instruction. `HOLD` — the car behind may not pass its teammate this segment.
- `SWAP` — the car ahead lifts so its teammate can pass. The exchange takes race time, works
  only under GREEN, when neither car pits and the two cars are adjacent and close; it can be
  delayed, it can fail, and a close rival behind can profit. Optional commitment:
  `{"objective":"PASS_CAR_AHEAD","deadline_lap":<lap>,"give_back_if":"OBJECTIVE_NOT_MET"}`.
- `DEFENSIVE_BUFFER` — the car behind defends against the next car at a time cost.
- With an open commitment: `KEEP_ORDER` or `REQUEST_GIVE_BACK`. When it falls due these are
  the only legal orders. Breaking a commitment carries no penalty; only the racing counts.

`observation.team_orders` lists the legal orders, whether an exchange is currently executable
and safe, and your commitment's status and history. Exact mechanics: `f1ctl rules` → `team_orders`.

`observation.engineer_reports` holds advice from Engineer A and Engineer B. Each engineer sees
only its own driver and public rivals, so the two can disagree; confidence values are
self-reported, not calibrated. Reports never act on their own: only your action counts.
`consumed_reports` (optional) lists the record hashes you actually used.

## Power-unit rules (benchmark 2.1.0) — these replace the "small pool of free replacement units" rule above

- **Allocation per driver.** Each driver may use 2 units of each element type (ICE, turbo, energy_store) this season without penalty. The starting units count.
- **Team stock.** A `REPLACE` fits a new unit from the team's stock, `resource_inventory["stock:<type>"]`. Both drivers share it and it is never refilled. An element may keep running above the wear limit, with the published pace and reliability cost. A `REPLACE` is legal only while stock is left.
- **Grid penalties.** Each unit beyond a driver's allocation costs grid places at the race where it is first used: 4 places for the first extra unit of a type, 2 for each later one.
  - Places from several replacements at the same race add up.
  - A driver with more than 5 places starts behind all other cars, in qualifying order.
  - Otherwise the driver drops that many places from the qualifying position.
- **Where to look.** `controlled_drivers.*.components.*.replace_cost_if_only_replacement` shows each element's allocation, the units used, the places it would cost and the stock left.
- **Exact rules.** `f1ctl rules` → `power_unit_rules` has the rule text. It also says which parts follow the FIA 2026 sporting regulations and which are scaled for an 8-race, 8-car season.
