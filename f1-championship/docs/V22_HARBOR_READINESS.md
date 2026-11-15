# 2.2.0 integrated-candidate verification and Harbor readiness

Branch: `feature/v22-integrated-candidate`, based on reference baseline `39e4d16`
and integrated at `c28807e`. All work remains isolated from `submission/2.1.0`, its
README/verifier/reference, main, `feature/demo-ux`, and C5.

## Exact validation status

| Area | Result |
|---|---|
| Full devtest regression | **263 passed in 119.999 seconds** |
| Legacy regression | **35 passed** |
| M2/M6/M7 focused suites | **27 passed** |
| M2-only full seasons | Exact replay on seeds 1 and 2 |
| M6-only full seasons | Exact replay on seeds 1 and 2 |
| M7-only full seasons | Exact replay on seeds 11 and 12 |
| Combined M2+M6+M7 session | Exact replay, 120 resolved ticks / 8 races on seed 21 |
| All flags OFF | Full 2.1.0 behavior reproduced; same journals, accepted actions, observations, standings and hash `ed105fda2de9e388ee37c614f29b0baff80d09a2a6d3a1289b9b3f5f05ebae26` |
| Generated 2.2.0 task | `task.toml`, mode flags, public rules and output artifacts verified; oracle/export/grader completed with `complete=true`, `intact=true`, 120 decisions, and reward `0.40562248995983935` |
| Model/API calls and cost | **0**, not credentialed |
| Actual Docker/Harbor/OpenCode execution | **Not performed here** |

`c28807e`'s main integration report remains: `docs/V22_INTEGRATION_CANDIDATE_REPORT.md`.
This document covers the subsequent separate-task packaging and validation only; it
is not an evaluation of Gemini or an official Frontier–Reference gap.

## Meaningful effects actually measured

- **M2 Defender:** existing buffer effect is **+0.35 s** on rival elapsed time, not
  a hidden label effect. Conservative intent prevents a faster pass while honoring
  the engine margin rather than teleporting positions.
- **M6 Give Back:** McLearn A declines with public compliance probability
  **0.273125**, attempts/refunds remain zero, and a subsequent compliant request
  fulfils. No WDC-derived points are added. Public probability, not raw draw, is exposed.
- **M7 dry/OFF parity:** first step elapsed times and tyre ages are exactly the same
  under GREEN, SC, and VSC. Wet pits reset compound/age and correctly apply warmup,
  pace, wear, weather risk and incident logs. Retired drivers cannot re-enter pit or
  team-processing; their last classification is DNF with zero points.
- **M6 tampering tests:** resealed fake M6 order events are rejected.
- **M7 future privacy:** changing private future rain/wetness leaves the current
  public forecast unchanged. Rival type IDs, hidden assignments and private schedule
  objects are not in agent observations.
- **Replay:** every generated journal replays from its seed/config to identical
  observations, actions, weather fields, results, points and head hashes. Legacy,
  sidecar, verifier and reference copies are synchronized by
  `scripts/sync_engine.py`; `devtests.test_boundary.LayoutTests` is clean.

No normalization was independently invented: `b6-integrated-p0` remains
`clip((P - D) / (U - D), 0, 1)`, with the existing same-seed fallback and the
43×race theoretical maximum. M2/M6/M7 type/compliance/weather effects may change
outcomes through normal race dynamics, not score overrides.

## Reproducible generated-task verification

The task is created independently of submission/2.1.0:

```bash
cd f1-championship
scripts/make_integrated_task.sh /tmp/your-scratch/f1-v22 MOCK_ENGINEERS 2.2.0 m2_m6_m7
scripts/validate_v22_task.py \
  --dest /tmp/your-scratch/f1-v22-verified \
  --output /tmp/your-scratch/evidence
```

The destination builder deletes its own target directory; only use a dedicated
scratch path. `MOCK_ENGINEERS` provides an offline engineer condition. No live
`GEMINI_LITE_ENGINEERS` or `ADAPTIVE_LLM` call was used. If using an alternative
legacy version, pass `off` for features. For the broad candidate its default is
`m2_m6_m7`; legacy defaults remain disabled.

Latest fresh-report path in this workspace:

```text
f1-championship/analysis/results/v22_task_evidence/oracle-report.json
f1-championship/analysis/results/v22_task_evidence/oracle-manifest.json
f1-championship/analysis/results/v22_task_evidence/summary.json
```

Verified values:

- `completion.complete: true`
- `completion.races_completed: 8`
- `completion.resolved_ticks: 120`
- `integrity.intact: true`
- `benchmark_version: 2.2.0`
- `reward: 0.40562248995983935`
- `model_calls: 0`
- `actual_harbor_run: false`
- journal v2, 120 sealed entries
- one hashed Engineer store under `engineers/apex/engineer_records.jsonl`

Hashes:

```text
oracle-report.json:    bb3d2167f879e70f05616e1f8e419cf95ace385eaac50011583625344a7f5a32
oracle-manifest.json:  0c5d24db39e3315d0c672a750a57b61c2c2d2576793eb0d76c5fb8ba9e00bccb
summary.json:          25a1f19c922508c52c9f9485432634fe2f22e4b7d25085c60e2a51fa8fd4a328
engineer record file:  d7a98eadcd1cb1064591ba04b010a1085c777745c8bd3337064010d3dd11072c
```

`validate_v22_task.py --resume` revalidates these files without regenerating or
overwriting them; it returned the same `bb3d2167…a7f5a32` hash.

## Harbor readiness and blockers

**Exact Harbor readiness is still pending.** I now have a buildable separate task,
mode configuration and grader that replay with M2/M6/M7 opt-in flags when explicitly
requested. I do **not** have a Docker/Harbor execution to report.

Before any promotion, the owner must perform all of the following:

1. Run `harbor lint <task-dir>` and a genuine Harbor + OpenCode evaluation with a
   configured credential and model. Observe that forecast schema and action rules
   stay 2.2.0 rather than switching to the 2.1.0 submission branch.
2. Repeat actual model tests of `GEMINI_LITE_ENGINEERS` and `ADAPTIVE_LLM`; this work
   validates configuration/replay only, not a complete runtime combination matrix.
   Controller engineer records must be generated before observation hashing and
   preserved for replay. `ADAPTIVE` and `FIXED_REPLAY` remain separate estimands.
3. Finish the remaining S1 contract: M1 pace modes, M3 proximity/attack resolution
   and actual attack/defence outcome evidence. Current M2 is a valid subset using
   existing defence/suppression physics, not complete full-scenario S1 support.
4. Verify a new reference/planner against wet forecasts and other scenario conditions
   explicitly. `neutralisation_multiplier` is only an adapter for existing process
   control, not a new joint weather/SC reference. Do not present the synthetic
   forecast as an exact calibrated real-world probability model.
5. Keep the reward and v2 observation/journal/replay contract versioned separately
   from the frozen 2.1.0 candidate. No Path<foo> autorewrite, Reference21 reference
   upgrade, C5 Practice/Qualifying integration, or demo modification is attempted in
   this sprint.

The actual generated task report and resume tool are independent of any frozen 2.1.0
artifact and should not be confused with an official fresh model trial or a final
official version change.
