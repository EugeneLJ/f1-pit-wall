

## Additional 2.2.0 rules (opt-in flags)

This generated task has the exact M2/M6/M7 via `mode.json`. Existing component and
race decision shapes, sealed decision ids and the constructors' objective are unchanged.

- **M2 constructed-context:** Rival tendencies are assigned once per race from a
  published prior, but are not shown. You may infer only from publicly observable
  pits, pace/lap evidence and reactions. Never request or assume a type identity.
- **M6 compliance:** public WDC standings and teammate points determine a public
  compliance probability per relevant team order. A refusal emits `ORDER_DECLINED`
  publicly after the order resolves. The seeded draw is hidden. A refused give-back
  becomes `RACE` for that segment; its commitment is not fulfilled or refunded.
- **M7 weather:** the observation exposes observed rain state and the seeded
  Dirichlet forecast distributions, not hidden future rain/wetness or incident draws.
  Wet-state forecasts shrink in variance with lead by construction and are
  probabilistic reports, not realized future weather.

Both drivers may also choose `PIT_INTERMEDIATE` and `PIT_WET` during `RACE_STRATEGY`.
Current compound/weather state and time, tyre-wear/risk and two-car queue semantics
continue to determine legal physical outcomes. Wet running conditions can make
another tyre better or can make sitting out or delaying the stop preferable; never
use unseen future weather for that decision. Intermediate/wet counts apply only once
actually raced and exempt the car from the distinct-dry-compound requirement.
