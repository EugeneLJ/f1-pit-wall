# EXPERIMENTAL benchmark 2.2.0 — C5 practice and qualifying weekend

This experimental task is benchmark **2.2.0** with the C5 weekend enabled. Everything in the 2.1.0
instruction below applies, with these additions (the 2.1.0 heading below refers to the rules it shares).

**Weekend phases.** Before each race's 14 race decisions there are now four decisions:
`COMPONENT_DECISION` → `PRACTICE` (session 1) → `PRACTICE` (session 2) → `QUALIFYING` → `RACE_STRATEGY`.
A season therefore has 144 decisions. Exact rules: `f1ctl rules` → `weekend`.

- **Setups.** `balanced` (neutral), `low_drag` and `high_downforce`. Each non-default setup has a hidden true
  effect for this weekend on qualifying pace, long-run race pace and tyre degradation, drawn once from the
  published prior in `f1ctl rules` → `weekend.setups`.
- **PRACTICE.** Each driver has 24 laps for the whole weekend. Per session and driver choose a program and setup:
  `QUALI_SIM` measures the qualifying pace offset, `SETUP_TEST` the long-run pace offset, `LONG_RUN` the
  degradation factor. Measurements are the true effect plus published noise; more laps narrow the estimate.
  `observation.weekend` shows the current estimates (mean, 95% interval, laps) and every measurement so far.

  ```json
  {"type":"PRACTICE","driver_a":{"program":"QUALI_SIM","setup_id":"low_drag","laps":6},
   "driver_b":{"program":"LONG_RUN","setup_id":"high_downforce","laps":6}}
  ```
- **QUALIFYING.** Choose a setup and `ONE_RUN` or `TWO_RUN` (best of two) per car. Qualifying time = published
  base pace + the setup's true qualifying offset + per-run noise. The order is the provisional grid; power-unit
  grid penalties are applied after it. **Parc fermé:** each car races with its qualifying setup, whose true
  long-run pace offset and degradation factor apply to that car for the whole race.

  ```json
  {"type":"QUALIFYING","driver_a":{"setup_id":"high_downforce","run_plan":"TWO_RUN"},
   "driver_b":{"setup_id":"low_drag","run_plan":"ONE_RUN"}}
  ```
- **Fallback** if a weekend decision is missing: no practice laps; the default setup with one qualifying run.
- During the race, `observation.weekend_result` shows the qualifying order and times and your frozen setups.

---

