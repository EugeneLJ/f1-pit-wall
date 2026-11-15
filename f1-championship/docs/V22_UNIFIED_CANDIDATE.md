# Unified 2.2.0 candidate: C5 + M2 + M6 + M7 + runtime axes (experimental)

**Branch:** `feature/v22-unified-candidate`.

**Inputs**
- Opus C5 integration and runtime axes: `feature/c5-integration` at `dbf9aeb` (C5 `65aecc1`; runtime `23cfa09`, `dbf9aeb`).
- Kimi M2/M6/M7: `feature/v22-integrated-candidate` at `06be24c`.

**Untouched:** `main`, `submission/2.1.0` and every 2.1.0 score. No 2.1.0 number is reused for 2.2.0.

**Feature flags.** Each is independently selectable and off by default:
- `c5_weekend`, `m2_tendencies`, `m6_compliance`, `m7_weather` in `IntegratedConfig`;
- runtime axes `engineers` (CHIEF_ONLY | GEMINI_LITE_ENGINEERS) and `rival` (SCRIPTED | ADAPTIVE_LLM | FIXED_REPLAY) in `integrated/runtime.py`.

## 1. Integration compatibility matrix

| Area | C5 + runtime | M2/M6/M7 | Result in the unified branch |
|---|---|---|---|
| Phases / decision ids | `PRACTICE` ×2 and `QUALIFYING` before each race (144 ticks); ids stay `tNNN` | unchanged phases (120 ticks) | composes; 144 ticks when C5 is on |
| Practice/Qualifying → race | `_start_race(weekend)`: qualifying grid, then PU penalties; per-car pace and degradation | M7 weather creation and M2 tendency draw at race start | both now run in `_start_race`, i.e. after qualifying (git placed Kimi's hooks there; verified) |
| C5 setups × M7 timing | per-car `deg_factor` read by `engine._segment_time` | `weather._segment` reimplemented timing with the global factor only | **conflict, fixed:** M7 dry-compound timing now multiplies by the car's C5 factor. Wet/intermediate unchanged (C5 v1 setups are dry-only). Tested. |
| M2 tendencies, public history | not affected; rivals keep C5's neutral setup | hidden per-race type for uncontrolled cars | composes; the M2 map is created after qualifying; not in observations (tested) |
| M6 WDC / orders / compliance | not affected | public standings and compliance in observations | composes (tested: `m6_driver_objectives` present) |
| Config API | `c5_weekend`, `with_c5_weekend` | `m2/m6/m7` flags, `with_features` | textual conflicts resolved; `with_c5_weekend` now keeps the other flags; application order irrelevant (tested) |
| Sidecar / verifier / rules | `c5_weekend` from `mode.json`; `weekend` rules | `with_features(mode)`; M2/M6/M7 rules | `with_features` then `with_c5_weekend`; all rule sections published (tested) |
| Task builder | `F1_C5_WEEKEND=1` | `features off\|m2_m6_m7` | compose; the no-C5 2.2.0 build is byte-for-byte Kimi's |
| Engineer broker / DeepSeek | `runtime.py` reuses `EngineerBroker`, `GuardedChief`, `two_team`, `ReplayPolicy` | none | `RuntimeSpec` also carries the M2/M6/M7 flags |
| Journal / replay / reward | v2 entries for the new phases; `verify.replay` unchanged | small `verify.py` change | full-season replay exact with all four flags (tested); reward formula unchanged (D is the 2.2.0 fallback season of the same configuration) |
| Session deep copy | – | M6 keeps a module reference on the session | analysis clones share module references (`c5_counterfactual.clone`); the simulator is unchanged |

## 2. Tests

| Suite | Result |
|---|---|
| Full devtests (Opus + Kimi suites, including `test_v22_m2/m6/m7_integration`, `test_v22_harbor_validation`, `test_c5_integration`, `test_runtime_axes`, `test_v22_unified`) | 310 + 7 unified, all OK |
| Root tests (legacy, schema, demo) | 51 OK |
| `test_v22_unified.py` | all four flags kept and order-independent; 144-tick unified season deterministic and replayable; every extension live; C5 factor under M7; all-off 2.2.0 == 2.1.0; runtime spec × all axes; Harbor build + sidecar + rules see all flags |

## 3. Strategic effects (counterfactual; no model calls)

`analysis/c5_counterfactual.py --unified`, task seed, 32 public futures. All 9 qualifying setup pairs at
each race's qualifying, with earlier races identical. The configuration is C5+M2+M6+M7.

| Race | C5 only: best pair, gain vs control | Unified (C5+M2+M6+M7): best pair, gain vs control |
|---|---|---|
| 1 mixed | high_downforce/balanced, +0.34 | **low_drag/low_drag**, +1.30 ± 0.28 |
| 2 street | high_downforce/low_drag, +0.84 | high_downforce/high_downforce, +0.28 ± 0.24 |
| 3 high_speed | high_downforce/high_downforce, +6.03 | high_downforce/high_downforce, +3.74 ± 0.45 |
| 4 high_degradation | high_downforce/high_downforce, +8.40 | **balanced/balanced** (control best) |
| 5 wet_prone | high_downforce/high_downforce, +8.57 | **low_drag/low_drag**, +1.99 ± 0.27 |
| 6 street | high_downforce/low_drag, +4.85 | high_downforce/low_drag, +3.34 ± 0.40 |
| 7 high_speed | high_downforce/balanced, +0.37 | **low_drag/balanced**, +1.16 ± 0.17 |
| 8 mixed | high_downforce/high_downforce, +2.10 | **balanced/balanced** (control best) |

**Reading**
- Weather and rival tendencies change which setup is best in 5 of 8 races.
- The setup choice still matters in races 3 and 6: +3.3 to +3.7 points, more than 8 SE.
- These are counterfactual estimates with a model-access advantage, not frontier results.

## 4. Harbor evaluations (labelled by enabled features)

### 4a. Kimi candidate alone: M2+M6+M7, no C5

- **Build:** `06be24c`, CHIEF_ONLY, scripted rivals, task seed, task checksum `90706aae…`.
- **Who ran it:** an independent subagent on Verda, from a fresh clone, with no code changes.
- **Evidence:** `analysis/results/v22_harbor/kimi-m2m6m7-06be24c/`.

| Run | Points | Reward | Complete / intact |
|---|---:|---:|---|
| Gemini 3.8 Flash, OpenCode (fresh Harbor run) | 223 | 0.5141 | yes / yes, 0 rejected; used PIT_INTERMEDIATE 15× and PIT_WET 10× |
| oracle (`reference_v21.py`) | 196 | 0.4056 | yes / yes. **Not a 2.2.0 reference:** it fell back to the scripted baseline after race 1 ("tyre state differs from the observation"; 115 of 120 decisions) and never uses wet tyres |
| nop | 0 | 0 | no / yes |
| stop-early | not run | – | the probe builder is not on that branch |

D (same-seed fallback) = 95, U = 344. **Gemini − oracle must not be read as a frontier–reference gap.**

### 4b. Unified candidate: C5+M2+M6+M7, CHIEF_ONLY, scripted rivals

**Build:** `F1_C5_WEEKEND=1 make_integrated_task.sh … CHIEF_ONLY 2.2.0 m2_m6_m7`, from this branch.
- `mode.json`: `{"benchmark_version": "2.2.0", "c5_weekend": true, "engineers": "CHIEF_ONLY", "m2_tendencies": true, "m6_compliance": true, "m7_weather": true}`.
- Task seed. `harbor lint` OK.
- Evidence: `analysis/results/v22_harbor/unified-c5-m2-m6-m7/`.

| Run | Points | Reward | Complete / intact |
|---|---:|---:|---|
| Gemini 3.8 Flash, OpenCode (fresh Harbor run) | GEMINI_P | GEMINI_R | GEMINI_C |
| oracle (scripted coordinator + C5 smoke policy; **not a reference**) | 186 | 0.3655 | yes (144 ticks) / yes, 0 rejected |
| nop | 0 | 0 | no / yes |
| stop-early probe (attacks as root, 1 decision, quits) | 0 | 0 | no (1 tick) / yes, 4 rejected requests logged |

D (same-seed fallback, 2.2.0 unified) = 95, U = 344.

## 5. Live provider checks of the runtime axes on the unified configuration

RESULTS_5

## 6. Remaining blockers for a 2.2.0 benchmark

1. **There is no public-information 2.2.0 reference.**
   - `reference_v21.py` does not model weather, rival tendencies, compliance or the weekend. On 2.2.0
     it falls back to the scripted baseline.
   - The C5 oracle is a scripted smoke policy.
   - A rollout reference over public forecasts, tendency posteriors and practice estimates is required
     before any 2.2.0 gap can be claimed.
2. **Stop-early and exploit probes for 2.2.0.** The integrated probe builder exists on this branch. Its
   honest-finish mode uses the 2.1.0 baseline policy, which has no weekend or weather handling.
3. **Evaluation breadth.** One seed and one Gemini run per configuration so far. The staged seed budget
   and script replays still have to be run.
4. **The M7 × C5 rule is a choice, not a finding.** The C5 factor applies to dry compounds only; it
   should be reviewed with Kimi.
