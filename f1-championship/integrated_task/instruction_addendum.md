
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
