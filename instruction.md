# F1 Pit Wall: one-call constructors strategy

You control **Apex GP**, which has two drivers, A and B. One decision remains in
a short, deterministic race. Choose `PIT` or `STAY` for each driver to maximize
the team's combined constructors' points.

Work in `/app`. The supported interface is:

```bash
f1ctl observe
f1ctl rules
f1ctl preview '{"driver_a":"PIT","driver_b":"STAY"}'
f1ctl act '{"driver_a":"PIT","driver_b":"STAY"}'
```

`observe` and `rules` disclose the complete public model. `preview` is a
practice calculation and does not submit anything. `act` validates the action
and writes `/app/submission/action.json`. Submit exactly once; the last valid
contents of that file are your answer.

The required JSON schema is:

```json
{"driver_a":"PIT","driver_b":"STAY"}
```

Both values must be exactly `PIT` or `STAY`. Missing, malformed, or incomplete
submissions receive zero reward. Do not write a score or result file: the
verifier independently replays the submitted choices with trusted code.

The reward is Apex GP's combined constructors' points divided by the maximum
points attainable in this scenario. It is clipped to `[0, 1]`.
