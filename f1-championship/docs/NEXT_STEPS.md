# Next steps after `feature/afterquery-reference` (handoff, 2026-11-15)

Read `docs/REFERENCE_GAP_REPORT.md` first. State at handoff:

- `solution/reference.py` is the Harbor reference (`harbor run -p ./f1-championship -a oracle`): 286 points, reward 0.770 on the task seed; 271.8 mean on 100 seeds.
- Recorded 1.0.0 Gemini scripts on the same 100 seeds: 243.7–254.9.
- **Done:** all three fresh Gemini runs on 1.1.0 are collected (282 / 279 / 286 on the task seed, against the reference's 286; mean gap +3.7). Each script replays to its Harbor points exactly. Adapters for all three are in `analysis/results/reference_runs/v110-gemini-0N/policy.py`.
- **Open:** the 100-seed replay of the three scripts, a bounded reference improvement with dev and held-out seeds, and the 2.1.0 reference port.
- Nothing is pushed. `TEAM_HANDOFF.md` at the repository root is untracked and was left alone.

## To do, in order

1. **[DONE] Collect Gemini runs 02 and 03.** On Verda: `/root/f1-championship-ref/jobs/v110-gemini-0{2,3}/`; `v110-gemini-0N.ended` exists when a run is done. Copy `verifier/report.json`, `result.json`, `artifacts/evidence/f1sim/*` and the script (`scripts/py312 analysis/delegation.py <trajectory.json> <evidence_dir> <out_dir>`) into `analysis/results/reference_runs/v110-gemini-0N/`, as done for run 01. Do not commit `trajectory.json`. Do not print the env file or process command lines.
2. **[RUNNING] Replay the new scripts on the 100 seeds.** Use `scripts/py312 analysis/reference_eval.py --add v110_gemini_01 v110_gemini_02 v110_gemini_03`: it merges into `reference_eval.json` on the same seeds without re-running the reference. Add each to `GEMINI` in `analysis/reference_eval.py` (run 01 already has an adapter: `analysis/results/reference_runs/v110-gemini-01/policy.py`, functions `decide_component` / `decide_strategy`; it has not been run yet). First check that the replay reproduces the Harbor points on the task seed (282 for run 01). Then `scripts/py312 analysis/reference_eval.py --seeds 100` (about 11 min on 10 cores).
3. **Decide from that table.**
   - New scripts stay 10+ points below 271.8: the gap holds; update §3 and blocker 2 of the report and the README table.
   - New scripts are within a few points: the reference is not strong enough for 1.1.0. Cheapest legitimate strengthening, untested: a stronger rollout continuation than `play.race_action`, or a two-step lookahead on the top few actions. 96 futures instead of 32 did not help.
4. **Push** the branch and name it in the README and video once 3 is settled.

## Do not

- Change mechanics, coefficients, seeds, the reward, `instruction.md` or `environment/` to widen the gap.
- Edit `solution/lib/f1pitwall` by hand: edit `src/f1pitwall` and run `scripts/sync_engine.py`.
- Run `rsync --delete` into `/root/f1-championship-ref/f1-championship` while a Harbor run uses it.
