# 2.2.0 M2/M6/M7 integration candidate report

Base branch: `feature/v22-integrated-candidate` from the 2.1.0 reference at
`39e4d16`. The current WIP was preserved in an earlier local commit before further
integration. This report distinguishes implementation evidence from official Harbor
readiness and from model performance. `submission/2.1.0`, `feature/demo-ux`, and
main were not touched. **No model calls and no API costs.**

## Implementation status

| Module | Status | What is actually implemented |
|---|---|---|
| **M6 driver objectives** | **Implemented in the isolated candidate** | Official WDC standings/teammate gaps and public compliance probabilities; dynamic trailing/promoted-driver selection; deterministic per-car decision draws; `ORDER_DECLINED` public journal events and replay checks; decline means internal `RACE`, no Give Back attempt and unchanged commitments; later compliant Give Back can fulfil. |
| **M2 hidden rival tendencies** | **Implemented only for existing engine mechanics** | Private per-race assignments, conventional pit decisions, existing defence-buffer cost/margin effects, and conservative pass suppression. Actual behavior changes with no type identifier, seed, or type-assignment map in observations or final results. Full S1 is not complete. |
| **M7 weather/wet tyres** | **Implemented in the opt-in adapter** | Authoritative weather schedule, probabilistic public forecasts, `PIT_INTERMEDIATE`/`PIT_WET`, wet pace/degradation/warmup, action-dependent spin/retirement, neutralized-segment handling, retirement-safe pair/order geometry, and wet-use exemptions. Weather and PU DNFs are unioned in final classification. Legacy DNF/reward/classification derivation is unchanged. |
| **C5 Practice/Qualifying** | **Not started, by instruction** | Only readiness documentation is provided below. Nothing from the C5 implementation was imported or integrated. |

Every feature is behind an explicit flag in `IntegratedConfig`:
`m2_tendencies`, `m6_compliance`, and `m7_weather`. Any enabled feature requires
`benchmark_version="2.2.0"`. Legacy serialized configurations and config hashes do
not gain false-valued fields.

## Validation evidence

### Concrete behavioral checks

- **M6:** a forced McLearn A Give Back is declined with compliance probability
  **0.273125**, `give_back_attempts=0`, then fulfilled after a compliant retry.
  Requested orders remain sealed and in race actions; decline emits
  `ORDER_DECLINED`, not a fake `FULFILLED`/`BROKEN_WHILE_FEASIBLE`. Observations
  carry only public points, roles, gaps, horizon, and probabilities. Replay rejects
  resealed forged order events.
- **M2 Defender:** changing only the rival type adds the existing **0.35 s**
  public defence-buffer effect. **M2 Conservative:** a fast rival that would pass
  is blocked by its own existing pass margin instead of taking a preferred outcome.
  **Opportunist without M3:** exact no-change control—no bonus or fabricated attack.
- **M7 OFF/forced DRY:** first-step elapsed times and tyre ages are exactly equal
  to 2.1.0 in GREEN, SC and VSC. Wet actions fit intermediate/wet compounds and
  apply genuine tyre reset, warmup, pace, wear and risk. Public incident logs and
  final classification expose actual public resolutions only. Retirees stop further
  movement, exchange/geometry update and pit activity; final status is DNF with zero
  points.
- **Public boundaries:** copy/deep replay generates identical weather, forecasts,
  tyre state, incidents, observations, journals and standings. Mutating hidden future
  rain/wetness cannot change the current public forecast. Fast retirement guards
  prevent M2/M6 team orders and M7 cooperative geometry from reusing retired cars.
- **Reward consistency:** Constructors' points and driver points still come only
  from classification; no M2/M6/M7-specific points or WDC/decline penalty was added.
  The reward formula and verifier were not edited. A combined replay reports
  `McLearn Racing` 76, `Nova` 258, `Red Bool Racing` 115, and `Vertex` 192 on seed 21.

### Full-season replay results

All seven runs have 120 resolved ticks, eight races, exact replay, and matching
standings. No live model result is inferred from these scripted races.

| Module | Seed | Journal head hash | Objectives status |
|---|---:|---|---|
| M2 | 11 | `a48a34731c1a7b3981941677a745f04e0bb9cc0d20a0f5a80c7573e41af5cd86` | **PARTIAL** (limited to existing mechanics) |
| M2 | 12 | `b835205f6e75b0592949226e306ef7f2bbef4f5dc8c9377a7f023327d4e31903` | **PARTIAL** |
| M6 | 11 | `7acb6c6c54b68d8e328f498c3c115230a208e98d475ceb745d17a81da8cf7d42` | Implemented, exact replay |
| M6 | 12 | `8b0b65a1c2cd614a086c9e85b007faa41fef94e14fece5cc6a3d5f95599199c4` | Implemented, exact replay |
| M7 | 11 | `843243a3c2e900a2fc82981efa19d7e71ef533446d0d5679dc9a054371c1bddd` | Implemented opt-in, exact replay |
| M7 | 12 | `941ce65d5b6347114b15c13b81fb05142bba8ec37697a367fccb6edab129211a` | Implemented opt-in, exact replay |
| Combined | 21 | `878284b53138be29d53d2480f3d6e54ca83df53a930fdca615c10796b11cb9a8` | All three opt-ins replay exactly together |

Summary artifact: `analysis/results/v22_integration/smoke.json`, SHA-256
`f5a0bd681680f1138dca3671ba9a42d738e50c65f71fbb4ba6f627cad9be5b6e`.
The summary was generated from a single execution of seven seasons and takes
**2.323 seconds** in total. Resume mode validates that payload without recomputing
or overwriting it. Fixture hashes: M2
`3f2bb4f6df1eddbce3fa611f879988a783062f371a866c32dfcd10bd120cc4a3`, M6
`2243b8c75ba5e05adc89d45b9d86b46ba04b1221c9d6df4747a77808b8eaf7c1`, M7
`af671dfa920d41064aa5336947ab8f1d90b779b85c316097a615565dabea7706`.

### Commands actually run

```bash
cd f1-championship
/tmp/opencode/python-3.12.12/python/bin/python3.12 scripts/sync_engine.py

PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s devtests -p 'test_*.py'

PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s tests -p 'test_*.py'

PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  analysis/v22_integration_smoke.py \
  --output analysis/results/v22_integration/smoke.json
```

Focused regression groups passed **49 tests** for legacy/B8/M2/M6, then **22 tests**
for M7, fixed replay, config serialization, retirement safety and M2/M6 replay.
Two independent 11/12 smoke seasons plus one combined 21 season were checked. No
100-seed sweep, paid API, or Gemini evaluator was run.

**Final counts:** full devtest **261 passed in 110.606 seconds**; legacy **35 passed
in 1.456 seconds**. Boundary/layout checks confirm canonical, sidecar, verifier and
reference engine copies are byte-identical after synchronization.

## Chief/Engineer and rival compatibility

This is an integration-scope matrix, not Harbor certification.

| Chief.Engineer | Rival driver | Local reuse/test status |
|---|---|---|
| `CHIEF_ONLY` | `SCRIPTED` | Used by isolated replay/full-season policy tests. Works through the existing TWO_TEAM runner. |
| `CHIEF_ONLY` | `ADAPTIVE_LLM` | Structurally supported by existing runner/provider interfaces; **not run** because no paid live rival evaluation was performed. |
| `CHIEF_ONLY` | `FIXED_REPLAY` (diagnostic) | `ReplayPolicy` returns exact prior actions, deep copy, `FIXED_REPLAY` provenance, and refuses absent ticks. Dry replay mechanics reused. |
| `GEMINI_LITE_ENGINEERS` | `SCRIPTED` | Existing immutable recommendation store/broker can be reused, but this new M2/M7 artifact was **not validated under a live engineer provider**. |
| `GEMINI_LITE_ENGINEERS` | `ADAPTIVE_LLM` | **Not evaluated**; requires live provider execution, matched versioned models, secrets, and fresh integrity evidence. |
| `GEMINI_LITE_ENGINEERS` | `FIXED_REPLAY` (diagnostic) | No model called here. The rival replay behavior is reusable; any engineer behavior also needs its actual verified record provenance. Do not infer an engineer effect merely from replay. |

`P.scripted("baseline")` and `ReplayPolicy` deterministic seam work is reused rather
than reimplemented. The immutable Engineer broker and SECOND-team runner were not
rebuilt. Any future M7 forecast collection must enter the ordinary Chief
observation before the broker hash seal; old recorded recommendations should become
MISSING if weather changes the observation.

**Harbor readiness is NOT CLAIMED.** No Docker/Harbor/OpenCode job, Harbor
verifier integration, live Gemini Engineer call, or official reference-relative gap
was executed. An official candidate needs a new task/reference/grader version and a
fresh Harbor model validation; that does not happen on this branch.

## Remaining blockers and required verification

1. **Full M2/S1:** M1 pace modes and M3 proximity/attack resolution do not exist.
   Residual lap evidence, a resolved public defence model, and matched public-input
   type-conditioned values are needed before an S1 difficulty/Frontier claim.
   The implemented buffer/suppression subset must not be renamed to claim S1.
2. **M7 reference model:** `neutralisation_multiplier` remains an adapter for the
   existing SC/VSC process, not a new joint neutralization/weather rollout or a
   frontier reference. The dry-cliff example has no calibrated wet-cliff lifetime;
   no numeric calibrated wet lifetime is invented. Public forecast reports are noisy,
   not automatically calibrated posteriors.
3. **Live axes:** `GEMINI_LITE_ENGINEERS` and `ADAPTIVE_LLM` remain untested under
   real providers. No live credential was read or written for this work.
4. **Official verification:** replay is integrated-v2 trusted replay only, not an
   official 2.2.0 Harbor grader/task. Versioned observations, action validation,
   generated temporary job artifacts, and actual model costs must be revalidated in
   Harbor before a promotion decision.
5. **Scope:** no C5 was started, no red-flag model, no official reference policy
   change, no reward change, and no new official scenario-reversal result.

## C5 integration recommendation

Use **`feature/c5-practice-qualifying` at `9ff185e`** as authoritative C5 source,
not the older `8c4dfaf` pre-race handoff. Its sealed multi-team qualifying interface
is described in `C5_IMPLEMENTATION_REPORT.md` and validated separately. Do not merge
multiple older C5 instructions as additional mechanics.

When M2/M6/M7 are accepted for the next owner sprint, the remaining C5 connection
work is:

1. Add `PRACTICE(k=2)` and one `QUALIFYING` sealed phase per controlled team after
   components and before `RACE_STRATEGY`, retaining current pre-action observations
   and journal v2 normalization.
2. Carry C5 public practice history, estimates and qualifying choices inside the
   normal team observation; keep the frozen private `ParcFermeChoice` and RNG key
   out of observations, journals shown to Chiefs, and reference prompts.
3. Apply C5 setup pace once before M7 compound/wet pace, and C5 degradation factor
   once as a multiplier to the corresponding authoritative degradation path.
4. Preserve separate M2 type, M6 decision, C5 truth/noise, and M7 rain/incident RNG
   domains. Apply existing PU grid penalties after C5's **provisional** order with
   the existing `pu_rules.fia_grid`, then create the frozen setup choice for the
   engine's race start. Do not reimplement penalty logic via C5.
5. Require M2/M6/M7 replay equivalence tests before advertising a combined 2.2.0
   version. C5's existing pure functions are useful; they are not themselves a
   ready-made ChampionshipState/Phase/replay integration.
