# Next steps (updated 2026-11-15)

**2.1.0 (current, branch `feature/reference-2.1.0`).** The reference port is done and runs in Harbor: oracle 289 / 0.782. One live Gemini run scored 279 / 0.742. On 20 paired script-replay seeds the reference leads by +9.05, almost entirely from race decisions. See `docs/REFERENCE_2_1_0_REPORT.md`. Open items:
1. [DONE] Decision-level analysis of `v21-gemini-01` (`analysis/b21_decisions.py`): 7 robust candidates, all missed stops. They are the 1.1.0 T1 (early SOFT stop) and T3/T4 (mid-race and SC stops) types; none involves components.
2. More live 2.1.0 runs, about $0.7 each. Needs a decision.
3. Only if the gap must grow: race-side reference strengthening. Staged: 2 smoke seeds, then 5 dev seeds.

---

# Earlier: next steps after `feature/afterquery-reference` (handoff, 2026-11-15)

Read `docs/REFERENCE_GAP_REPORT.md` first. State at handoff:

- `solution/reference.py` is the Harbor reference (`harbor run -p ./f1-championship -a oracle`): 286 points, reward 0.770 on the task seed; 271.8 mean on 100 seeds.
- Recorded 1.0.0 Gemini scripts on the same 100 seeds: 243.7–254.9.
- **Done:** all three fresh Gemini runs on 1.1.0 are collected (282 / 279 / 286 on the task seed, against the reference's 286; mean gap +3.7). Each script replays to its Harbor points exactly. Adapters for all three are in `analysis/results/reference_runs/v110-gemini-0N/policy.py`.
- **Open:** the 100-seed replay of the three scripts, a bounded reference improvement with dev and held-out seeds, and the 2.1.0 reference port.
- Nothing is pushed. `TEAM_HANDOFF.md` at the repository root is untracked and was left alone.

## To do, in order

1. **[DONE] Collect Gemini runs 02 and 03.** On Verda: `/root/f1-championship-ref/jobs/v110-gemini-0{2,3}/`; `v110-gemini-0N.ended` exists when a run is done. Copy `verifier/report.json`, `result.json`, `artifacts/evidence/f1sim/*` and the script (`scripts/py312 analysis/delegation.py <trajectory.json> <evidence_dir> <out_dir>`) into `analysis/results/reference_runs/v110-gemini-0N/`, as done for run 01. Do not commit `trajectory.json`. Do not print the env file or process command lines.
2. **[DONE, staged] Replay the new scripts.** The 100-seed run was replaced by the staged budget (`analysis/staged_eval.py`): on 20 paired seeds the gaps are +10.2 / +6.2 / +5.7. Old instruction for reference: Use `scripts/py312 analysis/reference_eval.py --add v110_gemini_01 v110_gemini_02 v110_gemini_03`: it merges into `reference_eval.json` on the same seeds without re-running the reference. Add each to `GEMINI` in `analysis/reference_eval.py` (run 01 already has an adapter: `analysis/results/reference_runs/v110-gemini-01/policy.py`, functions `decide_component` / `decide_strategy`; it has not been run yet). First check that the replay reproduces the Harbor points on the task seed (282 for run 01). Then `scripts/py312 analysis/reference_eval.py --seeds 100` (about 11 min on 10 cores).
3. **[DONE] Decide from that table.** The result is within a few points for two of the three scripts, so the reference needed strengthening. The bounded tests (16/64 futures, two-step, plan budget) gave no consistent gain on 5 dev seeds (REFERENCE_GAP_REPORT §3.3). Report the 1.1.0 gap as modest. **Next: the 2.1.0 port (`docs/REFERENCE_2_1_0_PORT.md`), staged (2 smoke seeds → 5 dev seeds).** Do not run 100 seeds without a final-validation reason. Original text:
   - New scripts stay 10+ points below 271.8: the gap holds; update §3 and blocker 2 of the report and the README table.
   - New scripts are within a few points: the reference is not strong enough for 1.1.0. Cheapest legitimate strengthening, untested: a stronger rollout continuation than `play.race_action`, or a two-step lookahead on the top few actions. 96 futures instead of 32 did not help.
4. **Push** the branch and name it in the README and video once 3 is settled.

## Do not

- Change mechanics, coefficients, seeds, the reward, `instruction.md` or `environment/` to widen the gap.
- Edit `solution/lib/f1pitwall` by hand: edit `src/f1pitwall` and run `scripts/sync_engine.py`.
- Run `rsync --delete` into `/root/f1-championship-ref/f1-championship` while a Harbor run uses it.
