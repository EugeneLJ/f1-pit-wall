# C5 integration: practice and qualifying in the championship (opt-in 2.2.0 candidate)

**Branch:** `feature/c5-integration`, from `submission/2.1.0` (24cee88), with the isolated C5 module merged
from `feature/c5-practice-qualifying` (9ff185e).

**Untouched:**
- `main` and `submission/2.1.0`;
- every committed Harbor run and score;
- Kimi's branches.

**Scope:** the 2.1.0 benchmark is unchanged. All new behaviour is behind
`IntegratedConfig.c5_weekend`, which requires benchmark version `2.2.0`.

## 1. What was integrated

The C5 module (`track_c/c5`) is used unchanged. Its contract (`docs/C5_INTERFACE_CONTRACT.md`)
assigns seven wiring steps to the engine owner, and all seven are implemented.

| Contract step | Where |
|---|---|
| 1. Opt-in configuration; initial public state after `COMPONENT_DECISION`; private key only in trusted state | `config.py` (`SCENARIO_VERSION`, `c5_weekend`, `with_c5_weekend`); `integrated/weekend.py` (`Weekend.begin`, `weekend_key`) |
| 2. Phase machine `COMPONENT_DECISION → PRACTICE(1) → PRACTICE(2) → QUALIFYING → RACE_STRATEGY` with sealed simultaneous submissions | `session.py` hooks; `Weekend.validate` / `resolve` |
| 3. Public observation per phase; v2 journal entries; no key, truth or parc-fermé envelope in observations | `Weekend.observation`; the journal is the unchanged v2 format |
| 4. All controlled teams' qualifying actions → `qualifying`, keeping only order and times | `Weekend.resolve` (team → action map) |
| 5. Penalties afterwards in the engine; frozen parc-fermé → `race_modifiers` → race config | `championship_adapter.race_config(weekend=…)`; the 2.1.0 `fia_grid` still applies after the qualifying grid |
| 6. Trusted replay recomputes every phase from the seed | `verify.replay` unchanged: it re-submits the journal; the weekend is deterministic |
| 7. No-C5 configurations identical; neutral setups neutral | tests below |

**Engine and adapter additions**, all inert unless the weekend input is given:
- `race_config(..., weekend)` takes the qualifying grid and adds per-car long-run pace offsets.
- `engine.new_state` accepts an optional `car_deg_factor`, and `_segment_time` multiplies a car's
  degradation by it (default 1.0).
- `step()` is not modified.

## 2. Behaviour

**Per race** (144 decisions per season instead of 120):
1. **PRACTICE × 2.**
   - Each driver has 24 laps per weekend.
   - Programs: `QUALI_SIM` measures the qualifying offset, `SETUP_TEST` the long-run pace offset,
     `LONG_RUN` the degradation factor.
   - Measurements are the hidden true effect plus published noise.
   - **The trade-off:** laps spent on one program or setup are not available for another.
2. **QUALIFYING.**
   - Each car picks a setup and `ONE_RUN` or `TWO_RUN`.
   - Time = public base pace + true qualifying offset + per-run noise.
   - The order is the provisional grid; 2.1.0 power-unit grid penalties are applied after it.
3. **RACE.**
   - Parc fermé: each car's true long-run pace offset is added to its race pace, and its true
     degradation factor multiplies its tyre degradation, for all 14 decisions.
   - Rivals use the neutral `balanced` setup, whose effect is exactly zero.
4. **Championship.** Race points accumulate as before; setups do not carry between races.

**Public vs hidden information**

| Public (in observations or `f1ctl rules`) | Hidden (trusted session only) |
|---|---|
| setup priors, noise model, lap budgets | the per-race key (sha256 of the seed and race index) |
| own practice measurements and posterior estimates | true setup effects |
| qualifying order and times; own frozen setups | the parc-fermé envelope; per-car race modifiers |

A test scans observations for the key, the true effects and the field names (`rng_key`, `seed`,
`deg_factor`).

**Fallback**: no practice laps; `balanced` with `ONE_RUN`. The reward's anchor D is that fallback
season under 2.2.0.

## 3. Strategic relevance (controlled counterfactual)

`analysis/c5_counterfactual.py` → `analysis/results/c5/counterfactual.json`. No model calls.

**Method**
- Task seed, 2.2.0 with C5.
- Earlier races are identical (neutral weekend, published baseline race policy).
- The race under test uses one fixed public practice plan.
- At qualifying, all 9 setup pairs are evaluated (`TWO_RUN`). The race starts from that grid with
  those setups and is rolled out by the authoritative engine over 32 public SC/VSC futures with a
  fixed continuation policy for every car. Value = exact expected Apex points.
- **Control:** `balanced/balanced`.

| Race | Archetype | Control | Best pair (car A / car B) | Best − control (± SE) | Spread best − worst |
|---|---|---:|---|---:|---:|
| 1 | mixed | 28.15 | high_downforce / balanced | +0.34 ± 0.18 | 7.24 |
| 2 | street | 38.88 | high_downforce / **low_drag** | +0.84 ± 0.47 | 10.98 |
| 3 | high_speed | 24.24 | high_downforce / high_downforce | +6.03 ± 0.58 | 12.41 |
| 4 | high_degradation | 31.29 | high_downforce / high_downforce | +8.40 ± 0.88 | 20.61 |
| 5 | wet_prone | 24.82 | high_downforce / high_downforce | +8.57 ± 0.83 | 11.87 |
| 6 | street | 33.47 | high_downforce / **low_drag** | +4.85 ± 0.87 | 10.48 |
| 7 | high_speed | 17.14 | high_downforce / balanced | +0.37 ± 0.18 | 4.58 |
| 8 | mixed | 16.83 | high_downforce / high_downforce | +2.10 ± 0.27 | 7.21 |

**Reading**
- **Measurable consequence.** Legal qualifying choices move expected race points by 4.6–20.6 points
  per race. The best choice beats the no-information control by 6–9 points (6–10 SE) in races 3–5.
- **Decision reversal.** On the street tracks (races 2 and 6), car B's best setup is `low_drag`. It
  qualifies P1 instead of P4 with `high_downforce`, and grid position dominates where overtaking is
  hard: race 6 gives 38.31 against 34.49. On high-degradation, wet-prone and high-speed tracks the
  same car's best setup is `high_downforce`, where lower degradation dominates.
  - Race 6's reversal holds under a second continuation policy (event_aware).
  - Race 2's reversal does not; it is a near tie there (+0.84 ± 0.47).
- **No-change controls.**
  - Races 1 and 7 are near ties against the control (+0.3 ± 0.2): the choice barely matters there.
  - Identical submissions replay to identical journals (tested).
- **What the agent knew:**
  - the published priors, for example `low_drag` qualifying −0.42 ± 0.16 s (95%) and degradation
    ×1.25; `high_downforce` +0.30 s and ×0.78;
  - its own practice estimates, for example after 8 `QUALI_SIM` laps the `low_drag` offset is
    known to ±0.05 s;
  - the public base pace of every car and the overtaking difficulty of each track.
  - It did not know the true per-weekend effects, for example race 6: `low_drag` −0.42 s, ×1.22;
    `high_downforce` +0.21 s, ×0.86.
- **The C5 reference heuristic is weak.** It is a small public-input heuristic, not the 2.2.0
  reference. It loses 3.6 points in race 4 and 4.5 in race 2 against the best pair. Under this
  practice plan it made the same choice with and without practice. A 2.2.0 reference must evaluate
  setups by engine rollout, as this analysis does.

**Limitations**
- One seed.
- A fixed race continuation policy.
- The race under test assumes the same practice plan for every option.

## 4. Tests

| Suite | Result |
|---|---|
| `devtests/test_c5_integration.py` (14): flag rules; committed 2.1.0 Harbor journals replay (289, 279); 2.2.0 without C5 plays exactly like 2.1.0; engine without `car_deg_factor` unchanged; phase machine (144 ticks); determinism and exact replay; tampered practice/qualifying action fails replay; qualifying order = race grid and setups = race pace/degradation; neutral weekend has no race effect; hidden information absent; invalid actions rejected without state change; timeout fallback replays; two-team weekend | OK |
| C5 module tests (26, from the isolated branch) | OK |
| Full devtests | 274 OK |
| Root tests (legacy, schema, demo) | 51 OK |
| 2.1.0 build | `make_integrated_task.sh … CHIEF_ONLY 2.1.0` still produces instruction sha256 `5ad46b10…` and no C5 files |

**Image sources on this branch.** `scripts/sync_engine.py` copies the engine into the image
directories. A task built from this branch therefore has different image bytes, even with C5 off,
than the verified 2.1.0 task on `main`. The behaviour is the same, but the 2.1.0 submission must
keep being built from `main`.

## 5. Experimental Harbor task

```bash
F1_C5_WEEKEND=1 f1-championship/scripts/make_integrated_task.sh /tmp/c5task CHIEF_ONLY 2.2.0
harbor run -p /tmp/c5task -a oracle
```

**What the build contains:**
- `mode.json` with `"c5_weekend": true`, which the sidecar and verifier both read;
- `f1ctl rules` → `weekend`;
- the C5 instruction prepended to 2.1.0 r2;
- `track_c/c5` in both images.

**The oracle is a scripted smoke policy, not a reference.** It is the coordinator race policy plus
a fixed practice and qualifying rule.

**Harbor smoke on Verda (2026-11-15, Harbor 0.26.0):**
- **oracle:** 266 points, reward 0.6905. Complete (144 ticks, 8 races), intact, 0 rejected.
- **nop:** reward 0. Season unfinished, intact.
- **D:** the fallback season under 2.2.0 scores 92.
- **Evidence:** `analysis/results/c5/harbor-smoke/{c5-oracle,c5-nop}`.

## 6. Interface for merging with M2/M6/M7 (`feature/v22-integrated-candidate`)

**Shared design.** Both use `SCENARIO_VERSION = "2.2.0"`, `OPT_IN_VERSIONS = (FIA_PU_VERSION,
SCENARIO_VERSION)` and boolean feature flags that default off. Under 2.2.0 both keep the 2.1.0 PU
rules (`benchmark_version in ("2.1.0", "2.2.0")`).

| Area | C5 | M2/M6/M7 | Expected conflict |
|---|---|---|---|
| `config.py` | adds `c5_weekend`, `with_c5_weekend`; threads the flag through `as_dict`, `swapped`, `from_dict`, `with_version` | adds `m2_tendencies`, `m6_compliance`, `m7_weather` in the same places | **textual only**: same lines; merge by listing all four flags. Validation is independent. |
| `session.py` | new phases `PRACTICE`, `QUALIFYING`; `_apply_components` defers `_start_race(weekend)`; hooks in `_validate`, `fallback_action`, `_resolve`, `_build_observation` | M2 tendency init per race, M6 order resolution in the race step, weather observation | **small**: both touch `__init__` and `_apply_components`; M2's `_initialize_m2` must run after the race starts, so in `_start_race`. No shared logic. |
| `engine.py` | `new_state` (`car_deg_factor`) and one line in `_segment_time` | `new_state` (`v22_weather`), `step()`, `legal_actions`, observation | **none expected**: different hunks. M7's `weather.segment_time` should keep calling `_segment_time`, so the per-car factor still applies under weather. |
| `championship_adapter.py` | `race_config` / `start_prepared_race(weekend=…)` | not modified | none |
| `verify.py` | not modified | small change | none |
| observations | `weekend`, `weekend_result`, `action_schema` for the new phases | `weather`, compliance events | none (different keys) |
| journal | normal v2 entries for the new phases | v2 entries | none |
| reference policy | none yet (the C5 heuristic is weak) | none | both need a 2.2.0 rollout reference |

**Open interaction to decide:** M7 weather and C5 setups.
- C5 setups are dry-only in v1.
- Recommendation: under weather, a car's C5 degradation factor applies to dry compounds only, or C5
  is disabled when M7 is on until that is specified.
- No code depends on this yet.

## 7. Implemented and not implemented

| Implemented | Not implemented |
|---|---|
| opt-in 2.2.0 weekend in solo and two-team modes; deterministic, replayable, sealed | a 2.2.0 public-input reference (rollout-based) and its Harbor oracle |
| qualifying grid + PU penalties; per-car pace and degradation from parc-fermé setups | tyre-set allocations, sprint formats, setup carry-over, weather interaction |
| public rules, observations, fallback; experimental Harbor build | frontier evaluation on 2.2.0; natural-frequency study over many seeds |
| counterfactual on 8 races, one seed | a merge with M2/M6/M7 |

## 8. Requirements for a 2.2.0 Harbor benchmark

1. A rollout-based public-input reference covering practice, qualifying and the race, checked for
   seed-blindness.
2. A natural-frequency study over ≥ 20 seeds: how often setup choices are separated and how often
   they reverse.
3. Harbor oracle, nop, stop-early and exploit probe on the 2.2.0 task. Built from the merged 2.2.0
   candidate, not from this branch alone.
4. At least 3 fresh frontier runs and 20-seed script replays, as for 2.1.0.
5. An agreed M7 × C5 interaction rule (§6).
