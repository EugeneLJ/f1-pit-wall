# 120-second video script (submission 2.1.0)

**Rules**
- Every number on screen comes from a committed artifact (paths in `docs/SUBMISSION_CHECKLIST.md`).
- Recorded segments carry the on-screen label **"Recorded Harbor run — <job>, <UTC date>"**.
- Analysis segments carry **"Counterfactual (engine rollout on public inputs)"** or **"Script
  replay — not a model run"**.
- No simulated progress bars, and no live claim for anything that was recorded.

**Time split:** about 95 s on the main benchmark (gap, difficulty, integrity) and about 20 s on the
Gemini diagnostic. The demo UI is built separately (`docs/DEMO_HANDOFF.md`).

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:12 | Terminal: `f1-championship/scripts/run_v21.sh oracle` starting. The task build line shows `2.1.0`, then Harbor brings up the `main` and `sim` containers. Label: Recorded Harbor run (clean host). | "F1 Pit Wall: run a two-car team through an eight-race championship. The simulator sits in a sealed container with no network. The agent sees only public state through one tool, `f1ctl`." |
| 0:12–0:30 | `f1ctl observe` at a race decision, with `track_status`, tyre ages, `legal_actions`, `team_orders`, `event_model` and the PU `replace_cost_if_only_replacement` highlighted. | "A hundred and twenty decisions: when to pit and onto which tyre, how to react to safety cars, team orders, and power-unit replacements under FIA-2026-based allocation and grid-penalty rules. Rivals follow fixed, published rules." |
| 0:30–0:50 | Side by side: `v21-oracle-01/verifier_report.json` (289 points, 0.7817) and the three Gemini reports (279, 256, 276). Label: Recorded Harbor runs, same hidden seed, 2.1.0 Chief-only. | "On the same seed, a public-information reference scores 289. Three fresh OpenCode runs of Gemini 3.8 Flash score 279, 256 and 276. The reference wins every run, by 10 to 33 points." |
| 0:50–1:12 | Failure `t095`: race 7, lap 12, Safety Car, 33 laps left; car A on HARD tyres 4 laps old, in P8. Gemini: `STAY/STAY`. Reference: `PIT_HARD/STAY`. Regret 3.9 / 1.6 / 3.9 points. Label: Counterfactual (engine rollout on public inputs). | "Here the safety car makes a stop cheap. The reference takes it for car A. Gemini stays out in all three runs and gives up expected points. It also never takes the early soft-tyre stop. These failures survive every robustness check, and they are race decisions. The power-unit rules account for only half a point." |
| 1:12–1:35 | `v21-nop-01` reward 0; `v21-probe-stop-01` reward 0; `v21-probe-complete-01/agent_probe_results.json` scrolling the refused attacks; `tamper_regrade.json` with six forgeries at reward 0. | "Doing nothing scores zero, and so does quitting early. Boundary attacks run as root — reset, seed reads, stale or duplicate decisions, forged files — are refused or ignored. Forged evidence — even with the hash chain recomputed — fails replay from the hidden seed and scores zero." |
| 1:35–1:55 | C8 state `c8s28`: Engineer A recommends MEDIUM at confidence 0.85, and the Chief switches HARD to MEDIUM, losing 4.5–5.1 points. Label: Diagnostic — direct Gemini API, not the Harbor task. | "As a separate Gemini study, a Chief with two Flash-Lite Engineers on driver-local views. Concrete advice can pull the Chief off its own correct choice; bare priority claims are ignored." |
| 1:55–2:00 | README "Run (judges: start here)" block and the commit SHA | "One command reproduces the reference. Every number links to a committed artifact." |

**Recording notes**
- Record the 0:00–0:12 segment from the clean-host reproduction (`docs/REPRODUCTION_LOG.md`) and
  show its real job name.
- If the r2 Gemini smoke run is shown, label it "instruction r2". It is a separate condition from
  the three r1 runs.
