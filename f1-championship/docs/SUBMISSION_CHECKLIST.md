# Submission checklist and evidence inventory (2.1.0)

**What is submitted**
- Branch: `submission/2.1.0` on `https://github.com/EugeneLJ/f1-pit-wall`.
- Supported mode: benchmark `2.1.0`, `SOLO_COORDINATION` / `CHIEF_ONLY`, rivals on fixed published
  rules, instruction r2.
- Only this mode's Harbor results form the Frontier–Reference claim. 1.1.0 and the B7/C7/C8
  diagnostics are reported separately and never pooled.

## Checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Submission pushed; `main` = submission | PASS | `main` fast-forwarded from `972f5ca` to the submission commit on 2026-11-15 with approval (no history rewrite); `submission/2.1.0` is identical |
| 2 | Harbor task builds with one command | PASS | `scripts/run_v21.sh` |
| 3 | Instruction states 2.1.0, CHIEF_ONLY, fixed-rule rivals, and promises no Engineers or adaptive rivals | PASS | `integrated_task/instruction_2_1_0_chief_only.md` (r2) |
| 4 | The evaluated instruction is preserved and rebuildable | PASS | `integrated_task/evaluated/instruction_2_1_0_r1.md`, sha256 `f6697c53…`; `F1_INSTRUCTION_REVISION=r1` rebuilds the evaluated task byte for byte |
| 5 | r2 changes no simulator, action, observation, reward or verifier file | PASS | an r1 build and an r2 build differ only in `instruction.md` (`diff -rq`) |
| 6 | Reference oracle (Harbor) | PASS | 289 / 0.7817: `reference_runs/v21-oracle-01` |
| 7 | Three fresh Frontier Harbor runs (r1) | PASS | 279 / 256 / 276: `v21-gemini-01..03` |
| 8 | Fresh Frontier Harbor smoke run on r2 | PASS | `v21r2-gemini-01`: 279 / 0.7421, complete, intact, 0 rejected; 110/120 actions identical to `v21-gemini-01` |
| 9 | Do-nothing = 0 | PASS | `v21-nop-01` |
| 10 | Stop-early = 0 | PASS | `v21-probe-stop-01` |
| 11 | Exploit probe refused; honest finish scores only the heuristic | PASS | `v21-probe-complete-01` (229 / 0.5437) |
| 12 | Tampered evidence gets reward 0 | PASS | `v21-gemini-01/tamper_regrade.json` (6 of 6) |
| 13 | Clean-host reproduction: oracle, nop, probes, from a public clone, no manual steps | PASS | `docs/REPRODUCTION_LOG.md`; the oracle journal is identical tick by tick to `v21-oracle-01` |
| 14 | Clean-host Frontier run | BLOCKED | needs an API key on the clean host; not copied. The r2 OpenCode run used the main host, the same commit and the same wrapper (#8). |
| 15 | Devtests | PASS | 234 tests, `scripts/py312 -m unittest discover -s devtests` |
| 16 | Secrets and trajectories absent from commits | PASS | scans for `AIza` / `Bearer <token>` matched only documentation text; no `trajectory.json` committed |
| 17 | Replays and counterfactuals labelled as such | PASS | README §4; `docs/DEMO_HANDOFF.md` §4 |
| 18 | No unfinished M2/M6/M7/C5 work advertised as part of the task | PASS | README §1 "Not in this task", §7 "Planned" |
| 19 | Demo entry point for 2.1.0 | PASS | `scripts/demo.sh recorded` / `live`; a real LIVE run through it passed all 10 checks (279 / 0.7421; `analysis/results/demo/live-20261115T061229Z/`); 16 offline demo tests (`tests/test_demo_ux.py`) |
| 20 | Video script | PASS | `docs/VIDEO_SCRIPT.md`; the demo report (`docs/demo/*.jpg`) can be recorded directly |
| 21 | Submission platform's required target (`main` or a branch/commit URL) | PASS | either works: `main` now holds the submission, and the commit permalink below is immutable |

## Evidence inventory

All paths are relative to `f1-championship/`.
- **Mode for every row:** 2.1.0, SOLO_COORDINATION / CHIEF_ONLY.
- **Seed for every row:** the task seed, `tests/hidden_seed.json`.
- **Scoring for every row:** the isolated Harbor verifier, scalar `b6-integrated-p0`.

| Claim | Path | Run type | Model / agent | Instruction | Harbor task checksum |
|---|---|---|---|---|---|
| Reference 289 / 0.7817 | `analysis/results/reference_runs/v21-oracle-01/` | Harbor run (Verda) | oracle, `reference_v21.py` | r1 | `e94d82c1…` |
| Reference reproduced on a clean host | `analysis/results/reproduction/clean-host-2026-11-15/oracle/` | Harbor run (clean host) | oracle | r2 | `a008cb00…` |
| Gemini 279 / 256 / 276 | `analysis/results/reference_runs/v21-gemini-0{1,2,3}/` | Harbor run, fresh | OpenCode 1.19.5, gemini/gemini-3.8-flash | r1 | `e94d82c1…` (all three) |
| Gemini on r2: 279 / 0.7421 | `analysis/results/reference_runs/v21r2-gemini-01/` | Harbor run, fresh (main Verda host) | same | r2 | `a008cb00…` (same task as the clean-host oracle) |
| Do nothing 0 | `analysis/results/reference_runs/v21-nop-01/` and `reproduction/…/nop/` | Harbor run | nop | r1 / r2 | `e94d82c1…` / in file |
| Stop early 0 | `analysis/results/reference_runs/v21-probe-stop-01/` and `reproduction/…/probe-stop/` | Harbor run | probe (root) | r2 | in file |
| Exploit probe 229 / 0.5437 | `analysis/results/reference_runs/v21-probe-complete-01/` and `reproduction/…/probe-complete/` | Harbor run | probe, then baseline heuristic | r2 | in file |
| Tamper regrade | `analysis/results/reference_runs/v21-gemini-01/tamper_regrade.json` | local verifier run | — | — | — |
| Script-replay gaps +9.05 / +32.05 / +8.55 | `analysis/results/reference21_2.1.0_inter20*.json` | **script replay**, 20 paired seeds | Gemini-written scripts | — | — |
| Race vs component attribution | `docs/REFERENCE_2_1_0_REPORT.md` §4 | script replay hybrids | — | — | — |
| Robust failures (`t095`, early SOFT) | `analysis/results/reference_runs/v21-gemini-0N/decisions.json` | **counterfactual** on the live journals | — | r1 | — |
| C8 Engineer study | `analysis/results/c8/evaluation.json` | diagnostic, direct API | Gemini 3.8 Flash + 3.5 Flash-Lite | — | — |

## Links (pin to the final commit)

- **Repository (default branch `main` = submission):** `https://github.com/EugeneLJ/f1-pit-wall`
- **Branch:** `https://github.com/EugeneLJ/f1-pit-wall/tree/submission/2.1.0`
- **Exact commit:** `https://github.com/EugeneLJ/f1-pit-wall/tree/<final SHA>`. The final SHA is
  reported with the push; use the commit URL if the platform wants an immutable target.
- **README:** `https://github.com/EugeneLJ/f1-pit-wall/blob/<final SHA>/f1-championship/README.md`

## Recorded, not blocking

- **Instruction r1** says "benchmark 2.0.1" and describes Engineers. It is kept only as historical
  evidence.
- **`f1ctl rules` → `engineers.note`** still describes the Engineer mechanism of other modes. It is
  simulator code and was left unchanged; its `condition` field reads `CHIEF_ONLY`, and r2 explains
  this.
- **Engine module docstrings** say "benchmark 2.0.0" (the version that introduced them). They live
  in the image sources and were left unchanged.
- **Harbor API cost** per Frontier run was not recorded.
