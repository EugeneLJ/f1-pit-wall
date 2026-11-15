# Runtime axes for the 2.2.0 candidate

`src/f1pitwall/integrated/runtime.py` puts two independent runtime axes behind one `RuntimeSpec`.

**Scope:** this is the trusted direct-API runner (the B7 path), not the Harbor task. It is not part
of the validated 2.1.0 submission.

| Axis | Values | Built from (existing code, reused) |
|---|---|---|
| `engineers` | `CHIEF_ONLY` · `GEMINI_LITE_ENGINEERS` | engineer condition in `IntegratedConfig`; `EngineerBroker` (hash-chained record store, exact replay) with live `track_c.engineer_runtime.GeminiEngineerProvider` (`gemini-3.5-flash-lite`) behind `GuardedEngineer` / `CostGuard` |
| `rival` | `SCRIPTED` | `SOLO_COORDINATION`: all other teams follow the published rule |
| | `ADAPTIVE_LLM` | `TWO_TEAM_COMPETITION`, `rival_condition=ADAPTIVE`: a DeepSeek Chief (`providers.redbool_chief`, Verda, `deepseek-4-1-flash-1017`) runs the second team live; `assert_isolated` refuses shared credentials |
| | `FIXED_REPLAY` (diagnostics) | `TWO_TEAM_COMPETITION`, `rival_condition=FIXED_REPLAY`: `match.ReplayPolicy` replays the second team's actions from a recorded journal. An action that has become illegal falls back; it is reported, never altered. |
| `c5_weekend` (optional) | on / off | the C5 practice/qualifying weekend; it composes with every combination |

**Every combination runs through `match.run_season`:**
- sealed simultaneous ticks;
- the published fallback on any provider error, timeout or illegal action;
- a clean abort on the cost ceiling or tick limit.

Each run is then checked by `verify.replay`, with Engineer records re-supplied by
`EngineerBroker.replaying`. The Chief is `gemini-3.8-flash` (`providers.gemini_chief`) unless a
policy is injected.

```python
from f1pitwall.integrated import runtime as R, providers as PR
spec = R.RuntimeSpec(engineers="GEMINI_LITE_ENGINEERS", rival="ADAPTIVE_LLM", c5_weekend=True)
result = R.run(spec, base_seed, out_dir, PR.CostGuard(5.0))           # full season, verified by replay
result = R.run(spec, base_seed, out_dir, PR.CostGuard(5.0), max_ticks=8)  # smoke
```

**Smoke runs with real providers:**

```bash
scripts/py312 analysis/runtime_smoke.py --env-file <file with GEMINI_API_KEY and VERDA_INFERENCE_API_KEY> \
  --matrix --c5 --max-ticks 8
```

- **Before:** the script checks that every requested model is listed by its provider and refuses to
  substitute one.
- **Output:** `<out>/<label>/{summary.json, journal.jsonl}`, checked for credentials before writing.
- **Keys:** read from environment variable names only.

**Tests:** `devtests/test_runtime_axes.py` (7, fake providers) covers:
- the configuration matrix;
- a full 144-tick C5 season that replays exactly;
- live-Engineer records delivered on race ticks only;
- the adaptive rival and credential isolation;
- a fixed replay of a recorded rival;
- provider failure → fallback;
- the tick limit.

## Interface notes for M2/M6/M7

- `runtime.build_config` is the only place that maps the axes to `IntegratedConfig`. When the M2/M6/M7
  flags are merged, add them as further `RuntimeSpec` fields passed through to the config.
- **Open choice: M2 hidden rival tendencies and `ADAPTIVE_LLM` both change how rivals behave.**
  - M2 applies to the uncontrolled (scripted) teams.
  - Under `ADAPTIVE_LLM` the second team is controlled by DeepSeek. M2 should still apply only to the
    remaining uncontrolled teams.
  - Kimi's config already refuses `m2_tendencies` together with `rival_policy_variant`. The same rule
    should be checked for the uncontrolled set.
- M6 compliance acts on the controlled team's orders, so it is independent of the rival axis.

## Results

**Real-provider smoke (Verda, 2026-11-15, seed 20261116, benchmark 2.2.0 with C5 on, first 8 ticks).**
Every run covered COMPONENT_DECISION, PRACTICE, QUALIFYING and RACE_STRATEGY.

| Run (engineers · rival · features) | Calls | Returned models | Submitted / fallback | Replay | Est. USD |
|---|---:|---|---|---|---:|
| CHIEF_ONLY · SCRIPTED · C5 | 8 | gemini-3.8-flash | 8 / 0 | exact, 8 ticks | 0.078 |
| GEMINI_LITE_ENGINEERS · SCRIPTED · C5 | 8 Chief + Engineers | gemini-3.8-flash; Engineer records in `engineers/apex` | 8 / 0 | exact, with the Engineer store replayed | 0.074 |
| CHIEF_ONLY · ADAPTIVE_LLM · C5 | 16 | gemini-3.8-flash, deepseek-4-1-flash-1017 | 8 / 0 per team | exact | 0.076 |
| GEMINI_LITE_ENGINEERS · ADAPTIVE_LLM · C5 | 16 Chief + Engineers | gemini-3.8-flash, deepseek-4-1-flash-1017 | 8 / 0 per team | exact | 0.085 |
| CHIEF_ONLY · FIXED_REPLAY · C5 (rival replayed from the ADAPTIVE_LLM run) | 8 | gemini-3.8-flash | 8 / 0 per team | exact | 0.066 |

These are provider and plumbing smoke checks, not benchmark evaluations: 8 ticks, one seed, no M2/M6/M7.
Evidence: `analysis/results/runtime_smoke/<label>/{summary.json, journal.jsonl, engineers/}`.
