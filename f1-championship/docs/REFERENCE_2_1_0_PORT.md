# Porting the public-observation reference to 2.1.0 (assessment; not implemented)

**Status.** No code was changed for this. Frozen B7 (`f9b47c4`) and B8 (`2d30e84`) commits are untouched, and C5 is not integrated.

**Target.** The 2.1.0 opt-in rules (`pu_rules.py`) in SOLO_COORDINATION, run as a generated Harbor task.

## What already exists

| Piece | Where | 2.1.0-ready? |
|---|---|---|
| Harbor task generator for SOLO_COORDINATION | `scripts/make_integrated_task.sh` + `integrated_task/` | Builds **2.0.1** only: `mode.json` has no version field |
| Sidecar / verifier | `integrated_server.py`, `grade_integrated.py` | Both build `C.solo_coordination(...)` without `with_version` |
| PU rules | `src/f1pitwall/pu_rules.py`, hooks in the transition and adapter | Yes (opt-in through coeffs) |
| Reference player | `solution/reference.py` | **1.1.0 only**: `ChampionshipSession` model, contract v1 actions, `engine.step` rollouts |

## Minimal changes (in order)

1. **Task generator (about 10 lines).**
   - `mode.json` gains `"benchmark_version": "2.1.0"`.
   - `integrated_server.py` and `grade_integrated.py` apply `C.with_version(cfg, mode["benchmark_version"])`.
   - The fallback D is computed in the same version.
   - `make_integrated_task.sh` takes the version as an argument.
2. **Reference model (about 60 lines).** Replace the internal `ChampionshipSession(base_seed=0)` with `IntegratedSession(C.with_version(C.solo_coordination(), "2.1.0"), 0)`. This is the same "rules as code, no seed" principle.
   - Synchronisation reads contract v2: `tick_id` instead of `decision_id`, and `race_progress.drivers` with names. The classification already uses public names.
   - The same 0.002 s check applies.
3. **Component planner (about 30 lines).** Run `SeasonPlanner` with `pu_rules.with_fia_pu_rules(coef.DEFAULT)` so plan values include the 2.1.0 penalties and the B2.5.4b grid automatically.
   - `_repair` must respect stock: use `available_component_actions` and `pu_rules.check_team_stock`.
   - Bundling and timing need **multi-element moves**: add "replace these k elements at race r" and "move the bundle to race r+1" next to the single-replacement moves. The B8 evaluation shows both matter.
4. **Race rollouts (about 40 lines).**
   - Step the integrated race with `integrated.race.step(race, {"Apex": {…, "team_order": {"order": "RACE"}}})` instead of `engine.step`. With RACE this is bit-identical to 1.1.0, so the value function is unchanged.
   - Emit `team_order` in actions.
   - Optional, a second step: add SWAP / HOLD / DEFENSIVE_BUFFER as candidates only when `exchange_feasibility` says executable. In B6/B8, RACE was best in 74–75% of executable states, so the expected gain is small.
5. **Engineer reports.** The reference ignores them and may leave `consumed_reports` empty. The sidecar's offline Engineers stay as in 2.0.1.
6. **Tests.**
   - Replay and resync with 0 fallbacks on 2 smoke seeds, then 5 dev seeds.
   - Information-boundary test: two seeds give identical actions while their observations agree.
   - Stock conservation.
   - Harbor `lint` / `oracle` / `nop` on the generated 2.1.0 task.

## Evaluation plan (staged budget)

1. **Smoke, 2 dev seeds.** The reference completes all 8 races with 0 fallbacks; record the runtime.
2. **Dev, 5 paired seeds.** Compare the reference against the 2.1.0 public baseline and against the reference without multi-element moves.
3. **Frontier comparison.** Only then, Gemini on the generated 2.1.0 Harbor task, starting with 1 run. This needs a separate decision, because it costs about $0.67 per run.

## Risks

- **No frontier evidence on 2.1.0 yet.** A gap there is unknown.
- **Natural decision states are often near ties.** Under natural histories most replacement choices are near ties (B8: 43 of 55), so the PU decisions may add little difficulty unless the season produces repeat replacements.
- **The integrated task is generated, not static.** Judges need one extra command.
