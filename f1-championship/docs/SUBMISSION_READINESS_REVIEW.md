# F1 Pit Wall — Submission readiness review

**Date:** 2026-11-15.
**Scope:** read-only review. No code, tests, Harbor runs, paid calls, merges or history changes
were made for it. The document was written into the working tree of `feature/c8-engineer-conflict`
and is not committed.
**Evidence base:** `git fetch` of `origin` on 2026-11-15, branch contents read with `git show`,
plus read-only listings of the Verda host `95.133.252.166`. Every number below comes from a
repository artifact or a Verda job directory named next to it. "Unknown" means no evidence was found.
**Judging contract used:** `docs/HANDOFF.md` §1 (Gap 30, Meaningful difficulty 30, Reward
integrity 25, Craft 15).
- Judges run: the reference, 3 frontier-agent runs, a do-nothing baseline and a stop-early
  baseline, then investigate exploits for about 15 minutes.

## Status update (same day, after P0 work on `submission/2.1.0`)

| P0 | Status | Evidence |
|---|---|---|
| P0-1 submission branch | **Prepared, decision pending.** `submission/2.1.0` = `feature/reference-2.1.0` + C8 (fast-forward) + the P0 changes below; `main` untouched | this branch |
| P0-2 README judge path | **Done.** README leads with 2.1.0, its mode, in/out-of-Harbor scope, five judge commands with expected values; 1.1.0 is a comparison section | `README.md`, root `README.md` |
| P0-3 stop-early, exploit, tamper on 2.1.0 | **Done.** Stop-early reward 0 (2 ticks, intact); attacks-then-baseline 229 pts / 0.5437 with every attack refused; tamper regrade: 6 forgeries → reward 0, untouched evidence → 279 / 0.7421 identical to Harbor | `reference_runs/v21-probe-stop-01`, `v21-probe-complete-01`, `v21-gemini-01/tamper_regrade.json`; `scripts/make_integrated_probe_task.sh`, `probes/probe_integrated.py`, `analysis/v21_tamper_regrade.py` |
| P0-4 oracle and nop artifacts | **Done.** Committed from the Verda job directories (secret scan clean, no trajectories) | `reference_runs/v21-oracle-01`, `v21-nop-01` |
| P0-5 stale statements | **Done** for S1–S4 and S8. Module docstrings saying "benchmark 2.0.0" are left: they sit in files built into the sim and verifier images, and changing them would change the images the runs used | `docs/REFERENCE_2_1_0_REPORT.md`, `scripts/make_integrated_task.sh` |
| P0-6 one command | **Done.** `scripts/run_v21.sh oracle|nop|opencode|probe-stop|probe-complete`; the two probe runs above were produced through it on Verda | `scripts/run_v21.sh` |

**Still open:**
- P1-5, the clean-host rehearsal: the wrapper has run only on the Verda host that already had Harbor.
- P1-1, the instruction mismatch: disclosed in the README (option A).
- P1-2, the demo-ux port.
- P1-3, the held-out validation.

---

## 1. Executive assessment

**Not submission-ready today, but close.** The scientific core of 2.1.0 is in place and verified:
- a public-information reference: Harbor 289 points, reward 0.7817;
- three fresh Harbor/OpenCode Gemini 3.8 Flash runs: 279, 256 and 276, all complete and intact;
- a do-nothing baseline: 0;
- decision-level failure analysis with robustness checks.

What blocks submission is **packaging, not science**:

1. **The judge path still leads to 1.1.0.** The candidate branch's README headline, status line and
   "Run (judges: start here)" commands all target the 1.1.0 task. 2.1.0 needs a generation step
   (`make_integrated_task.sh`) and has only an oracle command.
2. **No stop-early or exploit evidence on 2.1.0.** The judges' stop-early baseline and the
   exploit probe exist only for 1.1.0: `make_probe_task.sh` copies the 1.1.0 task. 2.1.0 has
   oracle and nop runs only.
3. **The 2.1.0 oracle and nop runs are not committed.** They exist on Verda
   (`/root/f1-championship-v21/jobs/v21-oracle-01`, `v21-nop-01`; rewards 0.7817 and 0.0). The
   repository holds only the report text.
4. **Stale or contradictory statements** in the evidence documents (§5.2).
5. **No one-command 2.1.0 evaluation.** `feature/demo-ux` targets the 1.1.0 journal format and,
   by code inspection, does not support 2.1.0 (§2D).
6. **The submission branch is not decided.** `origin/main` (972f5ca) is the pre-Track-B project
   state, so a judge cloning the default branch would not see the submission.

None of these needs new mechanics or paid model calls. Items 2 and 3 need Harbor runs on Verda
with the oracle-style agent only (no API key).

**Recommendation:** submit **2.1.0** in Harbor mode `SOLO_COORDINATION / CHIEF_ONLY`. Present
1.1.0 as the comparison version, and B7/C7/C8 as clearly labelled diagnostic studies. Do not
promote any 2.2.0 module before submission (§7).

---

## 2. Version capability matrix

**Key**
- **Impl:** code exists on a pushed branch.
- **Integ:** wired into the shared engine or session for that version.
- **Test:** covered by devtests on that branch.
- **Harbor:** reachable by an agent in that version's Harbor task.
- **Eval:** evaluated with a real frontier model.
- **—:** not applicable.
- **No:** absent.
- **Unknown:** not evidenced.

| Capability | 1.1.0 | 2.0.1 | 2.1.0 (candidate) | 2.2.0 (planned) |
|---|---|---|---|---|
| Pit / compound decisions, 14 per race × 8 races | Impl, Integ, Test, Harbor, Eval | same engine; RACE order is bit-identical to 1.1.0 (test `test_race_order_is_bit_identical_to_1_1_0`) | Impl, Integ, Test, Harbor, Eval (3 Harbor runs) | unchanged |
| SC/VSC process, queue, SC gap compression | Impl, Integ, Test, Harbor, Eval | same | same | M7 would add weather-linked hazard (planned) |
| Two-compound rule | Harbor | same | same | wet exemption (B6.3.6, verified text) planned |
| Legacy component wear and shared free pool | Harbor, Eval | same | superseded; pool is 0 under 2.1.0 | — |
| FIA-2026-based PU allocation, stock, cumulative penalties, grid formation | No | No | Impl, Integ, Test (`test_b8_pu_rules.py`, `test_reference_v21.py`), Harbor, Eval | — |
| Team orders (HOLD, SWAP, DEFENSIVE_BUFFER) and commitments | No | Impl, Integ, Test | Harbor (legal in the observation); used by Gemini: 1–7 orders per run, one completed SWAP | M5 HOLD_UP planned |
| Engineer reports (mock / Flash-Lite) | No | Impl, Integ, Test; live in B7 Layer 2 (direct API) | **not in the Harbor task** (CHIEF_ONLY); C8 used 2.1.0 states over the direct API | M6 planned |
| Two-team competition, DeepSeek rival | No | Impl, Test; B7 live, outside Harbor (`match.run_season`) | 2.1.0 two-team test exists (`test_two_team_season_under_2_1_0`); no live 2.1.0 two-team run | M2 planned |
| Public-information reference in Harbor | `solution/reference.py`, Harbor 286 / 0.770 | Unknown (no Harbor run found) | `integrated_task/solution/reference_v21.py`, Harbor 289 / 0.7817 | not built |
| Fresh frontier Harbor runs | Gemini 3.8 Flash ×3 (`v110-gemini-01..03`), plus 4 runs on 1.0.0 | none | Gemini 3.8 Flash ×3 (`v21-gemini-01..03`) | none |
| Do-nothing baseline (Harbor) | `ref-nop-01` (committed) | — | `v21-nop-01`: 0.0 (Verda only, not committed) | — |
| Stop-early baseline and exploit probe (Harbor) | `ref-probe-stop-01` (0.0), `ref-probe-complete-01` (committed) | — | **No** (builder is 1.1.0-only) | — |
| One-command demo (`feature/demo-ux`) | targets this format (journal v1 `accepted` entries) | No | **No** by code inspection (§2D); not executed | — |
| C5 practice / qualifying | — | — | — | Track C module on `feature/c5-practice-qualifying` (9ff185e): Impl and Test in isolation (260 devtests pass); not integrated. A second, earlier prototype exists on `feature/practice-qualifying-evaluation` (8c4dfaf) |
| M2 rival tendencies, M7 weather | — | — | — | **not committed**: untracked files only, in `/root/f1-pit-wall-demo` on Verda (`track_c/v22/rival_tendencies.py`, `weather.py`, `common.py`, 792 lines, plus fixtures `v22_m2.json`, `v22_m7.json`); no tests found; the branch `feature/v22-m2-m7-implementation` exists only locally on Verda, at 4dc5d4b |
| M1, M3–M6 | — | — | — | contract only (`feature/v22-scenario-contract`, 4dc5d4b) |

**Branches verified on `origin`:**
- **reference-2.1.0:** 39e4d16.
- **c8-engineer-conflict:** 6b684f2 (on top of 39e4d16).
- **demo-ux:** 36ec2ad. It is based on 2d30e84 (B8) and has never merged the 2.1.0 work.
- **c5-practice-qualifying:** 9ff185e.
- **v22-scenario-contract:** 4dc5d4b.
- **afterquery-reference:** 0012b95, an ancestor of reference-2.1.0.
- **main:** 972f5ca.
- **Not on `origin`:** `feature/v22-m2-m7-implementation`, and `feature/kimi-evaluation-support`
  (ae949c0, local on Verda only).

---

## 3. Rubric assessment

### A. The Gap (30)

**What the evidence supports**

| Claim | Supported? | Evidence |
|---|---|---|
| On the 2.1.0 task seed, the reference beats each of 3 fresh Gemini Harbor runs | **Yes**: 289 vs 279 / 256 / 276; gaps +10 / +33 / +13; mean +18.7 | `reference_runs/v21-gemini-0N/verifier_report.json` (P, D = 92, U = 344); oracle report on Verda (`v21-oracle-01`, P = 289, reward 0.7817) |
| The runs are real Harbor + OpenCode with the named model | **Yes** | `harbor_result.json`: `agent.name = opencode`, `model_name = gemini/gemini-3.8-flash`, task `EugeneLJ/f1-championship-integrated`, trial names recorded |
| The reference is reproducible and fast | **Partly**. The Harbor run shows 61 s of play and 113 s wall; staged replays show 61–100 s per season. A second oracle repetition on a clean host is not evidenced. | REFERENCE_2_1_0_REPORT §3–4 |
| The gap generalises across seeds | **Only for the scripts Gemini wrote**, replayed on 20 paired seeds: +9.05 (15/20), +32.05 (20/20), +8.55 (15/20) | `reference21_2.1.0_inter20.json` and the run-specific variants |
| Independent model runs across seeds | **No.** Only the task seed has fresh runs. Script replays are not new model runs. | the report states this |
| The 2.1.0 PU mechanics cause the larger gap compared with 1.1.0 | **No.** The component contribution is +0.55 in all three runs; the larger mean is driven by run 02. | REFERENCE_2_1_0_REPORT §4–5 |
| Statistical significance | **Not claimable** with n = 3 runs | — |

**Strengths**
- The reference wins every live run and is ahead on most replayed seeds.
- The fallback anchor D is the same published policy for all runs.
- Provenance is clean: journals, manifests and adapters are committed, with no trajectories.

**Risks**
- The gap range is wide (+10 to +33). Two of three runs are near the 1.1.0 range.
- The reference has a model-access advantage: it executes the published rules exactly. It is
  disclosed, but judges may discount it.
- The README's top-level table still leads with 1.1.0.

### B. Meaningful difficulty (30)

**Actual frontier failures** (live 2.1.0 Harbor runs, scored by a counterfactual engine
reference; `decisions.json` per run):
- **Early SOFT stop never taken:** robust in all three runs.
- **Missed stop under the race-7 SC (t095):** robust in all three runs (+3.9 / +1.6 / +3.9).
- **Mid-race missed stops:** robust in all runs (5 / 10 / 4 decisions).
- **Run 02:** unneeded MEDIUM→MEDIUM stops.
- **Run 03:** a VSC double stack onto MEDIUM.
- **Components:** no robust candidate involves them in any run.

**Reference counterfactuals.** All the regret figures above are counterfactual values computed
by the authoritative engine on public inputs. They are not outcomes of alternative real races.

**Synthetic probes** (not the official gap):
- **C7** (2.0.1 two-team states, 16 calls): 3 of 3 separated reversals were not followed, but the
  Chief chose STAY/STAY in 15 of 16 calls. A general stay bias cannot be told apart from a
  rival-specific failure (`docs/C7_LIVE_EXPANSION_RESULTS.md`).
- **C8** (40 fixed 2.1.0 states, direct API): live Engineers shifted mean regret by +0.21
  [−0.00, +0.49]. One robust harm, c8s28 (HARD→MEDIUM, 4.5–5.1 points), not separated at the
  state level (`docs/C8_ENGINEER_CONFLICT_RESULTS.md`).

**Mechanics present in Harbor 2.1.0:** pit, compound, SC/VSC, PU allocation, stock, penalties,
team orders and commitments.
**Mechanics not present in Harbor 2.1.0:**
- Engineers (CHIEF_ONLY);
- an adaptive rival (rivals follow the published rule);
- weather;
- practice and qualifying.

**Interface risk found** (instruction and mode mismatch; see P1-1):
- The integrated instruction addendum says "This version adds … two race engineers" and describes
  `engineer_reports`, but the 2.1.0 task is CHIEF_ONLY and its observations contain no reports.
- The addendum heading says "benchmark 2.0.1".
- Evidence that it did not mislead the runs: Gemini scripts 01 and 02 read `engineer_reports`
  defensively (`obs.get('engineer_reports', [])`) and all runs completed with 0 rejected actions.
  It is still an inaccuracy a judge could flag.

**Strengths**
- The failures are strategic (timing and neutralisation), recur across runs and survive
  robustness checks.
- Hidden information is limited to future random events. A test checks there is no seed or
  future in observations.

**Risks**
- The 2.1.0 headline mechanic (PU rules) is not where models fail (+0.55).
- Advertising PU complexity as the difficulty source would be unsupported.

### C. Reward integrity (25)

| Safeguard | 1.1.0 | 2.1.0 | Evidence |
|---|---|---|---|
| Reward formula and normalisation; version check | verified | verified: clip((P−D)/(U−D)), 0 unless complete and intact; the verifier rejects evidence of another version | `integrated_task/tests/grade_integrated.py`; reports show D = 92, U = 344 |
| Do-nothing | 0 (Harbor) | 0 (Harbor, `v21-nop-01`, Verda only) | job dirs |
| Stop-early (incomplete season gets 0) | Harbor `ref-probe-stop-01` = 0 | **code path only** (`require_complete`; reward 0 if not complete); **no Harbor run** | — |
| Exploit probe (boundary attacks as root, then an honest finish) | Harbor `ref-probe-complete-01` | **not run** | — |
| Partial-completion incentive | points only accumulate, and incomplete = 0 | same logic | verifier code |
| Invalid actions | rejected and journaled; replay must reject them too | sidecar rejects; 0 rejected in the 3 live runs; invalid-action test in `test_b6_integration.py::test_timeout_and_invalid_actions` | — |
| Hash chain and full replay | verified | verifier replays from the seed; tamper tests exist for 2.0.x seasons and Engineer records (`test_full_seasons_replay_and_detect_tampering`, `test_sidecar_restart_seal_and_grade`). The sidecar test builds the **2.0.1** task, not 2.1.0. | devtests |
| Hidden-state isolation | Harbor probe verified | same sidecar boundary (copied task); observation leakage test; reference seed-blindness test (`test_reference_is_seed_blind_and_syncs`) | — |

**Integrity work still required before submission** (P0-3): run the 2.1.0 stop-early baseline,
the exploit-probe-then-finish run and a tampered-journal regrade on the generated 2.1.0 task.

**Disclosure item:** `tests/hidden_seed.json` is committed in the public repository; this is by
design for verifier replay. The agent container cannot read it. A judge may still ask, so the
README should point to `make_seed_variant.sh`.

### D. Craft (15)

**What works**
- Pinned images: `node:22.22.0-bookworm-slim` with `opencode-ai@1.19.5`;
  `python:3.12.12-slim-bookworm` for the sim and the verifier.
- The sim container runs with no network.
- `harbor lint` passes for both tasks.
- Agent timeout is 3600 s; a reference season takes about 2 minutes.

**Gaps**
1. **No single command for 2.1.0.** It takes two commands (generate, then run), the generator
   needs host `python3`, and its header comment still says "benchmark 2.0.0".
2. **The README targets 1.1.0.** Header: "Benchmark version 1.1.0", "Status: Track B through B4".
   Judge commands 1–5 are 1.1.0-only.
3. **`feature/demo-ux` does not support 2.1.0** (code inspection; not executed):
   - `scripts/demo.py::check_evidence` counts `kind == "accepted"` entries and compares them with
     `completion.accepted_decisions`. Integrated journals use `resolved` entries, and the
     integrated report has `resolved_ticks`, so a 2.1.0 run would fail this check.
   - `derive_race_summary` imports the v1 `journal.replay`.
   - Its default benchmark path is the 1.1.0 task.
   - It is based on B8 (2d30e84) and would need a merge with reference-2.1.0.
   - Its labelling discipline is good: it refuses a gap without a matched, verified reference
     (`test_missing_and_invalid_matched_reference_never_produces_a_gap`), and fresh runs go to a
     new directory.
4. **External requirements for frontier runs:** Gemini API key, allowed agent host
   `generativelanguage.googleapis.com`, about 8–10 minutes per run. The cost of the Harbor runs
   is **unknown** (no usage log found).

**Can an independent judge reproduce the core result today?**
- The oracle and nop: yes, if they find the 2.1.0 generation command in the README.
- The stop-early baseline: no.
- The demo: no.
- A fresh-host reproduction has never been tried. The 16-CPU host `86.38.182.132` is clean and
  suitable for that test.

---

## 4. Gemini API secondary challenge

**Beyond ordinary model calls (verified)**
- Gemini 3.8 Flash as Chief and Gemini 3.5 Flash-Lite as **two Engineers, each with a
  driver-local observation** (`track_c/engineer_runtime.py::format_runtime_observation`).
- Structured output: `response_schema` per observation schema.
- A trusted broker: records are hash-chained in an immutable store
  (`integrated/engineers.py::EngineerBroker`), the Chief cites hashes through `consumed_reports`,
  and replay re-supplies exact records.
- Per-call provenance: requested and returned model, request id, prompt hash, usage including
  thinking tokens, dated price snapshot.
- Model substitution is refused (`verify_model_available`); cost ceilings use `CostGuard`.
- Experimental conditions: aligned, conflicting, high-confidence, recorded.

**Compelling findings**
- **C8 is a clean paired design:** preregistered and committed before calls (0f5ba2d), same state,
  only the reports differ, a repeat control as the noise floor, and common random numbers.
  240/240 valid Chief calls, 80/80 valid Engineer records, USD 2.04.
- **c8s28:** the Chief kept its own pit decision but adopted the Engineer's compound (HARD→MEDIUM).
  It stays above 1.0 under 48 futures and two continuations (4.47 / 5.11 / 5.11).
- **The Chief ignored pure priority claims** (no extra team orders, unchanged regret). Advice
  without a concrete action did not move it.

**Must be qualified**
- +0.21 [−0.00, +0.49] is not separated from zero. It rests on 40 states with one call each and
  only one robust harmful case.
- c8s12 is within the Chief's own repeat noise (the repeat made the same change).
- B7 (Gemini 304 vs DeepSeek 143, and Layer 2 237 vs 175) is one season per layer outside Harbor.
  It is not a Frontier–Reference gap, and its Engineer effect is confounded by trajectory
  divergence.
- **Engineers are not in the Harbor submission mode.** The secondary-challenge evidence comes
  from direct-API runners. Say so explicitly.

---

## 5. Evidence inventory

### 5.1 Claim → artifact

| Claim | Artifact (path) | Branch @ commit | Version / mode | Provenance | Status | Reproducible | README / demo |
|---|---|---|---|---|---|---|---|
| Reference 289, reward 0.7817 | Verda `/root/f1-championship-v21/jobs/v21-oracle-01/…/verifier/report.json`; text in `docs/REFERENCE_2_1_0_REPORT.md` | report @ 39e4d16; **artifact not committed** | 2.1.0 SOLO_COORDINATION CHIEF_ONLY | Harbor oracle | verified on Verda | yes (`harbor run -a oracle`) | yes, after committing the artifact |
| Do-nothing 0.0 | Verda `jobs/v21-nop-01` | not committed | 2.1.0 | Harbor nop | verified on Verda | yes | yes, after committing |
| Gemini 279 / 256 / 276 (0.742 / 0.651 / 0.730) | `analysis/results/reference_runs/v21-gemini-0{1,2,3}/verifier_report.json`, `harbor_result.json`, `evidence/` | reference-2.1.0 @ ad0a91e / 39e4d16 | 2.1.0 | Harbor + OpenCode 1.19.5, gemini/gemini-3.8-flash | verified | the score of each run, by verifier replay of its journal; a new run gives a new sample | yes |
| Mean task-seed gap +18.7 | derived from the above: (10 + 33 + 13) / 3 | — | 2.1.0 | — | verified arithmetic | — | yes, with n = 3 stated |
| 20-seed script gaps +9.05 / +32.05 / +8.55 | `analysis/results/reference21_2.1.0_inter20*.json`, `analysis/reference21_eval.py` | reference-2.1.0 | 2.1.0 | **script replay**, not model runs | verified | yes (local, cached) | yes, labelled "script replay" |
| Gap is in race decisions (+8.0 / +27.1 / +7.9; components +0.55) | report §4, cached attribution | reference-2.1.0 | 2.1.0 | replay hybrids | verified | yes | yes |
| Robust recurring failures (early SOFT, race-7 SC, mid-race) | `reference_runs/v21-gemini-0N/decisions.json`, `analysis/b21_decisions.py` | reference-2.1.0 | 2.1.0 | live journal + counterfactual reference | verified | yes | yes; t095 is a good demo case |
| 1.1.0 comparison (286 vs 282 / 279 / 286) | `reference_runs/v110-gemini-0N`, `ref-oracle-01` | reference-2.1.0 | 1.1.0 | Harbor | verified | yes | yes, as the comparison version |
| C7 3× FAILURE_TO_ADAPT with stay bias | `analysis/results/c7/live_evaluation_expansion.json` | reference-2.1.0 @ 39e4d16 | 2.0.1 two-team states, outside Harbor | direct Gemini API | verified, diagnostic | yes (records committed) | only as a labelled diagnostic |
| C8 results | `analysis/results/c8/evaluation.json`, `docs/C8_ENGINEER_CONFLICT_RESULTS.md` | c8-engineer-conflict @ 6b684f2 | 2.1.0 states, direct API | Gemini 3.8 Flash + 3.5 Flash-Lite | verified, diagnostic | evaluation yes; live calls are samples | the Gemini section only |
| B7 Gemini vs DeepSeek | `docs/B7_P0_REPORT.md`, `analysis/results/b7/` | championship-integration @ f9b47c4 (ancestor) | 2.0.1 two-team, outside Harbor | direct API | verified, diagnostic | partly | the Gemini section only, never as the gap |
| Integrity: tamper → reward 0 | `devtests/test_b6_sidecar.py` | reference-2.1.0 | **2.0.1** task build | local subprocess | verified for 2.0.1 only | yes | not for 2.1.0 until P0-3 |
| C5 module | `track_c/c5/`, `docs/C5_IMPLEMENTATION_REPORT.md` | c5-practice-qualifying @ 9ff185e | isolated | Track C | tested in isolation | yes | future work only |

### 5.2 Stale, contradictory or unsupported statements

| # | Where | Problem |
|---|---|---|
| S1 | `docs/REFERENCE_2_1_0_REPORT.md` §4 | "The only live 2.1.0 model run is `v21-gemini-01`." This is stale: three exist. |
| S2 | `f1-championship/README.md` header | "Benchmark version 1.1.0", "Status: Track B through B4". Inconsistent with a 2.1.0 submission. |
| S3 | README "Run (judges: start here)" | Every command targets 1.1.0. Commands 4–5 (stop-early, exploit) have no 2.1.0 equivalent. |
| S4 | `scripts/make_integrated_task.sh` comment | "(benchmark 2.0.0)"; the default version is 2.0.1. |
| S5 | `integrated_task/instruction_addendum.md` | Heading "benchmark 2.0.1", and it describes two Engineers, while the 2.1.0 Harbor task is CHIEF_ONLY (see P1-1). This file is part of the task as run, so changing it changes the task. |
| S6 | Prompt for this review | Refers to `feature/v22-m2-m7-implementation` as a branch. It is not on `origin`; the work is uncommitted on Verda. |
| S7 | Two C5 implementations | `feature/c5-practice-qualifying` (Track C module, 9ff185e) and `feature/practice-qualifying-evaluation` (pre-race prototype, 8c4dfaf). Which one is canonical is not decided. |
| S8 | Harbor frontier-run cost | Not recorded anywhere. Do not state a cost per Harbor run. |

**Mode check.** The Harbor 2.1.0 task advertises and contains:
- pit and compound decisions;
- SC/VSC;
- PU rules;
- team orders and commitments.

It does **not** contain Engineers, an adaptive rival, weather or practice and qualifying. The
README and demo must not imply that it does.

---

## 6. Blocking issues (P0)

### P0-1 Decide the submission branch and make it what judges land on
- **Why:** Craft, and every criterion, depends on judges evaluating the intended version.
  Today `main` (972f5ca) is the pre-Track-B state.
- **Done when:** one branch is named as the submission (recommended: a submission branch cut from
  `feature/reference-2.1.0`, adding only P0 docs and evidence). It is the branch linked in the
  submission; or `main` is updated by the owner, which this review does not do.
- **Owner:** user (decision); Opus (preparation).
- **Depends on:** nothing.
- **Verify:** a fresh `git clone` of the submitted ref shows the 2.1.0 README first.

### P0-2 Make the README a 2.1.0 judge path
- **Why:** Craft (one-command evaluation), Gap and Integrity (judges must run reference, frontier,
  nop and stop-early).
- **Done when:** the top of the README states benchmark 2.1.0, its mode and what is in and out of
  Harbor. It gives exact commands for:
  - generating the task, or a checked-in generated task;
  - the oracle, three frontier runs, nop, stop-early and the exploit probe;
  - where reward and report land, with expected values.
  1.1.0 moves to a comparison section, and every replay number is labelled.
- **Owner:** Opus.
- **Depends on:** P0-1, P0-3 (for the stop-early and probe commands), P0-4.
- **Verify:** on the clean host `86.38.182.132` (Docker + Harbor 0.26 installed, no API key),
  follow the README literally. The oracle gives 289 / 0.7817 and nop gives 0.

### P0-3 Stop-early, exploit-probe and tamper evidence on 2.1.0
- **Why:** Reward integrity (25). The judging contract names the stop-early baseline explicitly,
  and judges will probe exploits.
- **Done when:**
  - a probe-task builder for the integrated task exists, mirroring `make_probe_task.sh` (a new
    script; the reward and verifier stay unchanged);
  - Harbor runs on 2.1.0 give: stop-early reward 0 with integrity reported; probe-then-finish
    reward ≤ the honest heuristic with evidence intact and every boundary attack refused;
  - a tampered-journal regrade of a 2.1.0 run gives `intact: false` and reward 0.
- **Owner:** Opus.
- **Depends on:** nothing (no API).
- **Verify:** three Harbor jobs plus one local regrade, artifacts committed next to the other runs.

### P0-4 Commit the 2.1.0 oracle and nop artifacts
- **Why:** Gap and Integrity claims must point to committed evidence, not report text.
- **Done when:** `reference_runs/v21-oracle-01/` and `v21-nop-01/` hold `verifier_report.json`,
  `harbor_result.json` and the evidence. A secret scan (`AIza`, `Bearer`) is clean, with no
  trajectories.
- **Owner:** Opus.
- **Depends on:** nothing.
- **Verify:** the committed reports show 2.1.0 with P = 289 (reward 0.7817) and P = 0 / reward 0.

### P0-5 Correct stale statements S1–S4 and S8
- **Why:** contradictions in evidence cost credibility across all criteria.
- **Done when:** S1–S4 are corrected in documentation and comments only, and no document states a
  Harbor run cost.
- **Owner:** Opus.
- **Depends on:** P0-2.
- **Verify:** `git grep` for the stale strings returns nothing on the submission branch.

### P0-6 A one-command 2.1.0 evaluation
- **Why:** Craft criterion, which names a "one-command README evaluation".
- **Done when:** one documented command produces a 2.1.0 Harbor run with reward and report, for
  example `scripts/run_2_1_0.sh oracle|opencode|nop` wrapping generation plus `harbor run`, or a
  checked-in generated task directory. A demo page is optional (P1-2).
- **Owner:** Opus (wrapper); Kimi (if it is folded into demo-ux).
- **Depends on:** P0-1.
- **Verify:** on the clean host, a single command gives the oracle result.

---

## 7. High-value improvements (P1) and options (P2)

### P1-1 Resolve the instruction and mode mismatch (S5)
- **Why:** Meaningful difficulty requires no confusing interface. Today the task describes
  Engineers that are absent.
- **Option A (no task change):** disclose it in the README, quoting the evidence that the three
  runs were unaffected (defensive reads, 0 rejected actions).
- **Option B:** fix the addendum as task 2.1.1 (instruction only). The submitted runs would then be
  on a different task, which needs 3 fresh Gemini runs plus oracle, nop and probes.
- **Recommendation:** A, unless there is time and budget for B's full re-run.
- **Owner:** user (decision); Opus.
- **Verify:** for A, a README statement plus run evidence; for B, the full P0-3 set plus 3 runs on 2.1.1.

### P1-2 Port `feature/demo-ux` to 2.1.0
- **Why:** Craft and the video. It is the most legible way to show a fresh, verified run.
- **Done when:**
  - merged onto the submission branch;
  - its evidence check handles journal v2 (`resolved` entries, `resolved_ticks`);
  - the race summary uses the integrated replay (`f1pitwall.integrated.verify`);
  - its tests cover a committed 2.1.0 run (for example `v21-gemini-01`);
  - its existing refusal to show a gap without a matched, verified reference is kept.
- **Owner:** Kimi.
- **Depends on:** P0-1, P0-4.
- **Verify:** run its renderer on `v21-gemini-01` and `v21-oracle-01`. It must show 279 vs 289
  with both "verified" and the run labelled as recorded.

### P1-3 Final held-out reference validation (CPU only)
- **Why:** Gap. The 20-seed replay is the broadest current evidence. The staged policy allows a
  final frozen check of up to 100 held-out seeds with a stated reason.
- **Stated reason:** the final frozen benchmark claim for the submission.
- **Done when:** the reference and the three Gemini scripts are replayed on ≤ 80 held-out seeds
  that were never used before. The report states that these are script replays and gives a
  per-seed table.
- **Owner:** Opus, on `86.38.182.132`.
- **Depends on:** a frozen submission commit.
- **Verify:** the cached output reproduces from cache, and seed sets are disjoint from all earlier ones.

### P1-4 Gemini secondary-challenge section in the README
- **Why:** the secondary challenge.
- **Done when:** a short section covers the architecture (Chief, two driver-local Engineers,
  broker, provenance) and the C8 headline with its intervals, c8s28, and the null conflict result.
  It states explicitly that the Engineers are not in the Harbor mode, and treats B7 as diagnostic.
- **Owner:** Opus.
- **Verify:** every number is traceable to `evaluation.json` or `B7_P0_REPORT.md`.

### P1-5 Clean-host reproduction rehearsal
- **Why:** Craft. It is the only direct test of "no undocumented manual setup".
- **Done when:** on `86.38.182.132`, starting from a fresh clone, Docker, Harbor and the README
  steps reproduce oracle, nop, stop-early and probe. Every manual step needed is added to the README.
- **Owner:** Opus.
- **Depends on:** P0-2, P0-3.
- **Verify:** a log of commands and results committed as `docs/REPRODUCTION_LOG.md`.

### P1-6 Seed disclosure
- Add one README line saying why `tests/hidden_seed.json` is public and how
  `make_seed_variant.sh` gives judges a private seed.
- **Owner:** Opus.

### P2 options
- Commit the M2/M7 work on Verda to a real branch, with tests (owner: Kimi or whoever wrote it).
- Reconcile the two C5 branches (S7).
- More fresh Gemini runs on 2.1.0. Each one is a new sample; it does not tighten anything until
  n ≥ 5. Needs a budget decision.
- A second frontier model in Harbor, for breadth; it is not needed for the rubric.

---

## 8. 2.1.0 vs 2.2.0

| Candidate | Verified status | Integration burden | Expected value before submission |
|---|---|---|---|
| C5 practice / qualifying | isolated Track C module, tests pass; not wired; two competing implementations | new phases in session, sidecar, observations and journal; reference extension; Harbor instruction; re-run everything | Low. A new decision type, but the reference, fairness study and frontier runs would all have to start from zero. |
| M2 hidden rival tendencies | uncommitted, untested files on Verda | engine overtaking and attack logic, posterior in the reference, leakage tests | Low now. It needs M1/M3 to matter, and is the core of S1. |
| M6 WDC goals and disobedience | contract only | compliance draws, standings, journal entries | Low. It also changes the meaning of team orders already used by Gemini. |
| M7 weather and wet tyres | uncommitted, untested files on Verda | the largest change: compounds, lap-time model, SC hazard, forecast, reference | Low before submission; possibly the highest value after it. |

**Recommendation: submit 2.1.0.** More mechanics would not raise the score on the current
evidence: the existing 2.1.0 mechanic (PU rules) did not create a gap, and difficulty comes from
the race decisions, which 2.1.0 already has.

**Objective promotion gates for any 2.2.0 module.** All must pass:
1. It is wired behind an opt-in flag. With the module off, results are bit-identical to 2.1.0,
   and frozen B7 and 2.1.0 journals replay exactly.
2. A public-input reference exists for the new decisions, with a seed-blindness test.
3. A natural-frequency study (C7 precedence) shows that separated decisions arise in the new
   family without tuning.
4. Harbor: lint, oracle, nop, stop-early and exploit probe all pass on the new version.
5. At least 3 fresh frontier Harbor runs, with the reference ahead on the task seed in every run,
   and script replays on ≥ 20 paired seeds.
6. A failure analysis shows at least one robust failure that involves the new mechanic, not only
   the pre-existing race decisions.

Until gates 1–6 pass, 2.2.0 is future work in the submission.

---

## 9. Demo storyboard (120 s)

**Time split:** about 95 s on the AfterQuery story (Gap, difficulty, integrity) and about 25 s on
the Gemini secondary challenge. The rubric weight is on the first.

**Labelling:**
- Any recorded segment carries an on-screen "Recorded Harbor run (trial name, date)" label.
- Any replay segment carries "Script replay — not a model run".
- No simulated progress bars, and no number that is not in an artifact.

| Time | Visual (real artifacts) | Narration |
|---|---|---|
| 0–12 s | Terminal: `harbor run` of the 2.1.0 task with `-a oracle` (recorded, sped up and labelled), then the sim container starting with no network | Eight-race constructors' championship, two cars, a sealed simulator; the agent sees only public state. |
| 12–30 s | `f1ctl observe` JSON at a race decision: tyre ages, SC status, legal actions, team orders, PU allocation | Every lap window is a strategic choice: pit, compound, team order, power-unit replacement under FIA-2026-based rules. |
| 30–50 s | Verifier `report.json` side by side: reference 289 / 0.7817 and Gemini run 02 256 / 0.651 (`v21-gemini-02`), then a line listing all three runs, 279 / 256 / 276 | Fresh OpenCode runs of Gemini 3.8 Flash on the same seed: the reference wins every run, +10 to +33 points. |
| 50–75 s | Failure case t095, race 7 Safety Car: Gemini's action against the reference's, with the counterfactual regret labelled as computed by the engine | Under the safety car, the cheap stop is missed in all three runs. Gemini also never takes the early soft-tyre stop. These failures survive every robustness check. |
| 75–92 s | Integrity: nop gives 0; stop-early gives 0; the probe's refused attacks and its reward; tamper gives `intact: false` (needs P0-3) | Doing nothing or quitting earns zero; tampering is caught by full replay from the hidden seed. |
| 92–112 s | C8: c8s28. Engineer A recommends MEDIUM at confidence 0.85; the Chief switches from HARD to MEDIUM; −4.5 to −5.1 expected points. Labelled "Diagnostic, direct Gemini API, not in the Harbor task". | Secondary challenge: a Gemini Chief with two Flash-Lite Engineers on driver-local views. Concrete advice can pull the Chief off its own correct choice, while pure priority claims are ignored. |
| 112–120 s | README "one command" block and the repository URL | One command reproduces the reference; every number shown links to a committed artifact. |

---

## 10. Task allocation

| Owner | Next tasks |
|---|---|
| **User** | P0-1 branch decision; P1-1 option A or B; budget decision on more Gemini runs (P2); final video recording |
| **Opus** (this agent) | P0-2 README; P0-3 2.1.0 probe and tamper runs on Verda (no API key needed); P0-4 artifact import; P0-5 stale fixes; P0-6 one-command wrapper; P1-3 held-out validation on the 16-CPU host; P1-4 Gemini section; P1-5 clean-host rehearsal |
| **Kimi** | P1-2 port demo-ux to 2.1.0 and journal v2 on top of the submission branch; commit or abandon the Verda M2/M7 work on a pushed branch (P2) |
| **Codex / remaining API capacity** | Nothing is required. If budget allows, the only valuable paid work is P1-1 option B (3 fresh 2.1.1 runs) or more 2.1.0 runs (P2). No other paid calls before submission. |

---

## 11. Final submission checklist

| # | Item | Status |
|---|---|---|
| 1 | Submission branch chosen and linked | **Pending** (P0-1) |
| 2 | README leads with 2.1.0, mode, in-Harbor vs diagnostic scope | **Fail** (S2, S3) |
| 3 | `harbor lint` on the 2.1.0 task | Pass (report §3) |
| 4 | Reference oracle on 2.1.0 (289 / 0.7817) | Pass on Verda; **artifact not committed** (P0-4) |
| 5 | Three fresh frontier Harbor runs, committed with provenance | Pass |
| 6 | Do-nothing baseline on 2.1.0 = 0 | Pass on Verda; **artifact not committed** |
| 7 | Stop-early baseline on 2.1.0 = 0 | **Fail** (not run; P0-3) |
| 8 | Exploit probe on 2.1.0 | **Fail** (not run; P0-3) |
| 9 | Tamper → `intact: false`, reward 0 on 2.1.0 | **Pending** (tested for 2.0.1 only) |
| 10 | Script replays labelled as such everywhere | Pass in the reports; recheck the README after P0-2 |
| 11 | No significance claims from n = 3 or 40 states | Pass |
| 12 | PU mechanics not presented as the gap's source | Pass in the reports; recheck the README |
| 13 | Engineers, adaptive rival and weather not implied to be in the Harbor task | **Pending** (README rewrite) |
| 14 | Instruction and mode mismatch resolved or disclosed | **Pending** (P1-1) |
| 15 | One-command 2.1.0 evaluation | **Fail** (P0-6) |
| 16 | Clean-host reproduction log | **Pending** (P1-5) |
| 17 | Stale statements S1–S4 fixed | **Fail** (P0-5) |
| 18 | Secret scan clean, no trajectories committed | Pass for the committed runs (0 trajectory files on reference-2.1.0); repeat for new artifacts |
| 19 | 1.1.0 still reproducible (oracle 0.7698) | Pass (`v21-v110-oracle-01`) |
| 20 | Demo storyboard uses only verified, labelled artifacts | Pending; depends on P0-3 for the integrity segment |
