# F1 Pit Wall: sequential constructors strategy

You are the Chief Strategist for **Apex GP**, which has two drivers, A and B.
Manage both cars through three remaining decision points and maximize their
combined constructors' points.

At each decision, observe the current state and submit one `PIT` or `STAY`
choice for each driver:

```bash
f1ctl rules
f1ctl observe
f1ctl act '{"driver_a":"PIT","driver_b":"STAY"}'
```

After `act`, the race advances four laps. Tyre age, elapsed time, track position
and pit consequences persist into the next observation. Repeat `observe` and
`act` until all three decisions are complete. Future GREEN/VSC/SC events are
seeded but hidden until their decision point.

Important mechanics:

- `PIT` changes that driver to a new MEDIUM tyre.
- Pit loss depends on the currently observed GREEN/VSC/SC status.
- If both Apex cars pit together, Driver B queues behind Driver A and receives
  the documented double-stack delay.
- The objective is total points from both cars, not either driver's individual
  finishing position.
- There is no future-outcome preview command. All formulas and legitimate rules
  are available through `f1ctl rules`.

Each action must contain exactly:

```json
{"driver_a":"PIT|STAY","driver_b":"PIT|STAY"}
```

The CLI writes `/app/submission/actions.json`. Missing, malformed, edited with
extra fields, or incomplete three-decision submissions receive zero. Do not
write a score: an isolated verifier independently replays the action sequence.
