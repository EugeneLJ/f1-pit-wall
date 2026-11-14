# B8 report — Strategic scenario expansion sprint (three-hour timebox)

**Branch:** `feature/strategic-scenarios-b8`, created from the verified B7 commit `f9b47c4`.

**New opt-in version: 2.1.0.** It is 2.0.1 plus FIA-2026-based power-unit rules. 1.1.0, 2.0.0 and 2.0.1 are unchanged and reproducible:
- the full regression suite passes;
- the Harbor 1.1.0 oracle journal is identical to `v110-oracle-01` (§9).

No paid model call was made in B8.

## 0. B7 frozen

| Item | Value |
|---|---|
| B7 commit | `f9b47c4` on `feature/championship-integration` (pushed). It contains the 2.0.1 fix `59ea435` and the C4 merge `d4b1ac3`. |
| Configuration | TWO_TEAM_COMPETITION 2.0.1, seed 20261115 (seed id `da8723e6b2d39810`), McLearn = slot Apex, Red Bool = slot Orion, ADAPTIVE |
| Models | `gemini-3.8-flash` (returned the same), `gemini-3.5-flash-lite` (Engineers), `deepseek-4-1-flash-1017` (returned the same) |
| Layer 1 journal sha256 / head | `e8391273…1ea7` / `4695e2db…e47a` |
| Layer 2 journal sha256 / head | `a060baca…fa06` / `5a5251c3…b9d5` |
| Frozen locations | `analysis/results/b7/` (full hashes in `docs/B7_P0_REPORT.md` §9), and the C4 evidence in `c4_report.json` and `layer*/c4_bundle.json.gz` |

**Frozen evaluation set** (unchanged in B8; nothing was retuned):
- Red Bool's VSC→SOFT double stacks: 5 in Layer 1, inferior under all 12 event/rival assumptions, regret ≥ 4.5 points;
- the 9 Layer 1 decisions that are C4-confirmed.

## 1. Audit of the existing component rules (before any change)

- **Wear and stock (2.0.1).** Three elements per driver (ICE, turbo, energy_store) with deterministic wear. A shared pool of **4 free units per team**. A replacement without a free unit costs a fixed per-component drop (ICE 4, turbo 2, ES 2).
- **Grid (2.0.1).** Grid drops are applied sequentially as "N places from the qualifying slot". There is no back-of-grid rule and no carry-over.
- **Fidelity.** None of this is FIA: it was a synthetic Track A placeholder.

**Verified against the FIA 2026 F1 Regulations, Section B, Issue 07 (2026-06-25)**, text extracted from the official PDF:

| Article | Content |
|---|---|
| B8.2.2 | Per driver per championship: 3 ICE, 3 TC, 3 EXH, 2 ES, 2 PU-CE, 2 MGU-K, 5 PU-ANC |
| B8.2.3 | Plus one of each element in 2026 |
| B8.2.7 | The allocation is per driver; a replacement driver is deemed the original driver |
| B8.2.8 | The first additional element of a type costs **10** grid places, the next ones **5**, cumulative. Of several identical elements introduced at one event, only the last may be reused without penalty. |
| B2.5.4b | **≤15** cumulative places: temporary slot = qualifying position + penalty. On ties the slower driver keeps the slot and the others go ahead; unpenalised drivers fill the free slots in qualifying order, and penalised drivers move up into the gaps. **>15** places: behind all classified drivers, in qualifying order. |

## 2. Priority A — Multi-component penalty bundling (implemented, opt-in 2.1.0)

**Files:** `src/f1pitwall/pu_rules.py` and `fixtures/pu_rules_fia2026.json`, with small dispatch hooks in `championship_transition.py` and `championship_adapter.py` that are inert unless `coeffs["pu_rules"] == "fia2026_scaled"`. 2.1.0 is enabled by `config.with_version(cfg, "2.1.0")`.

The five concerns are separate:

| Concern | Implementation | Status |
|---|---|---|
| Regulatory allocation | Per driver and element type, counted from `replacements` (`elements_used = 1 + replacements`) | Rule verified. 8-race scaling is **synthetic**: allocation = 1 + ⌈(real − 1) × 8/24⌉, giving 2 / 2 / 2. |
| Team physical stock | `resource_inventory[team]["stock:<type>"]`; REPLACE is legal only with stock; a joint per-team check runs per event; without stock an over-limit element runs on | **Synthetic** logistics (3 per type per team) |
| Replacement decision | Unchanged action space: USE/REPLACE per element; rivals use the published threshold rule, stock-aware | Unchanged |
| Penalty calculation | B8.2.8, first / subsequent / cumulative; places **scaled by 8/22** to the 8-car field (10→4, 5→2) | Rule verified; scaling **synthetic** |
| Grid application | `fia_grid`: B2.5.4b temporary slots, fill, then back of grid above the threshold (15→5 scaled) | Algorithm verified; threshold scaling **synthetic** |

**Not modelled:**
- exhaust, PU-CE, MGU-K and ancillary parts;
- rotation of used elements in a pool (a replaced element is retired), so the same-event last-element rule is moot.

**Evaluation** (`analysis/b8_penalties.py`):

**Plans for the decision driver:**
- `BUNDLE_NOW`: replace all components with wear ≥ 0.45 now.
- `DISTRIBUTE`: the most worn now, then one per race.
- `DEFER_BUNDLE`: all at the next race.
- `NO_CHANGE`: only forced changes.

**Value.** Expected Apex constructors' points over the remaining season. Each value is exact over the published retirement probabilities and averaged over 8 SC/VSC schedules from the published process (independent analysis seeds). All cars use the public baseline race rule. The 95% intervals are paired across schedules.

**Generators**, declared before any evaluation:
- (a) `natural`: the published-rule history until an Apex driver has ≥ 2 worn components.
- (b) `synthetic`: coverage, **not F1 incidence**. Mid-season states with prior usage drawn from 1–2 elements per type and wear from U(0.35, 0.85).
- (c) a **held-out** synthetic set (calendars 100–139), never used during development.

| Set | Decision states | Best plan: BUNDLE / DISTRIBUTE / DEFER / NO_CHANGE | Bundle clearly better | Distribute clearly better | Near tie (\|Δ\| < 1 point) |
|---|---:|---|---:|---:|---:|
| natural (60 calendars) | 55 | 41 / 6 / 8 / 0 | 17 | 1 | 43 |
| synthetic (60) | 52 | 30 / 11 / 11 / 0 | 22 | 9 | 14 |
| held-out synthetic (40) | 38 | 26 / 2 / 10 / 0 | 27 | 1 | 6 |

**Representative cases (synthetic set):**
- **Bundling better (S26).** Three elements at the allocation limit. Bundling = 12 places, so back of grid once. Distributing = 4 places in each of three races. Bundling gains **+15.0 [12.3, 17.7]** points.
- **Distributing better (S54).** ES is still within allocation (free) and the turbo is over it. Distributing takes the free ES now and defers the turbo's 4-place penalty to an easy-overtaking track (high_speed, 0.22). It gains **6.5 [4.5, 8.6]** points over bundling at a street track (0.94).
- **No-change control.** `NO_CHANGE` is never best. The mean gain of bundling over no change is +10.4 points (synthetic), from the wear-driven pace and reliability loss.

**Natural incidence.** Under natural histories the first replacement of each type is within allocation and carries no penalty. So the bundle/distribute choice is mostly a near tie (43 / 55). Penalty trade-offs need prior usage, which an 8-race wear model rarely produces. That is why the synthetic coverage set exists, and it is labelled as such.

## 3. Priority B — Circuit-specific penalty timing (implemented through the race model)

- **No per-track multiplier.** The cost of a grid drop comes from the race engine itself: overtaking difficulty in the pass margin, team-track pace fit, tyre degradation, the baseline strategy, retirements, and the remaining calendar.
- **Matched pairs.** Every decision state is paired with the same state where races i and i+1 are swapped. A **reversal** means the preference between `BUNDLE_NOW` and `DEFER_BUNDLE` flips, with both intervals clear of 0.

| Set | Reversals | Clear no-change controls | Unclear | corr(Δ difficulty now−next, value of NOW) | Pairs where a harder current track lowers the NOW value |
|---|---:|---:|---:|---:|---:|
| natural | 1 | 25 | 29 | −0.23 | 70% |
| synthetic | 1 | 21 | 30 | −0.25 | 73% |
| held-out synthetic | 5 | 12 | 21 | −0.56 | 72% |

**Reversal example (held-out S109).** ICE at the allocation limit, a 4-place penalty.

| Order of the next two races | NOW − DEFER (points) |
|---|---:|
| Street (difficulty 0.87), then high_degradation (0.41) | **−6.0 [−8.3, −3.8]** |
| Swapped: high_degradation first | **+9.4 [8.2, 10.7]** |

**Control (S115).** Two high_degradation tracks (0.445 / 0.449): +4.9 vs +4.1. No reversal.

**Evidence of circuit dependence.** The preference is predicted by the overtaking difficulty of the two circuits, not by a scenario label. Swapping only the race order flips it.

**Reference.** A legitimate multi-race reference with the same public information: published process, independent schedules, exact retirement expectation. Its limitation is that the race strategy is fixed to the baseline rule; it is not a full season optimisation.

## 4. The other three priority families (reused mechanics; held-out evaluation `b8_families.py`, seeds 300–311)

### Rival strategy reversal (B5/B6 rival variants and two-team engine)

On 384 held-out states, changing only Red Bool's pit rule changes McLearn's best response in:

| Rival rule | Best action changes | Mean loss if the baseline rival is assumed | Loss > 0.5 points | No-change controls |
|---|---:|---:|---:|---:|
| `conservative_2stop` | 16.7% | 0.11 | 6.5% | 320 |
| `long_stint` | 13.5% | 0.12 | 8.3% | 332 |
| `undercut` | 10.4% | 0.07 | 4.7% | 344 |
| `event_aware` | 7.8% | 0.04 | 2.6% | 354 |
| `opportunistic` | 4.7% | 0.02 | 0.5% | 366 |

These are consistent with B6 (7.7–15.4%), which supports the earlier result.

### Conditional swap and give-back (B6 engine)

**Team orders**, on 133 held-out states where an exchange was executable:

| Best order | States |
|---|---:|
| RACE | 100 |
| DEFENSIVE_BUFFER | 17 |
| SWAP | 13 |
| HOLD | 3 |

| Order | Mean vs RACE (points) | Near ties |
|---|---:|---:|
| SWAP | −0.11 | 72% |
| DEFENSIVE_BUFFER | −0.10 | 78% |
| HOLD | −0.71 | 81% |

**Give-back after a forced swap:** 14 states, mean **−0.42** team points, **none positive** (max 0.0). B6's single +5.2 state therefore stays unconfirmed, and **no team-points-beneficial give-back** emerged, matching Track C. Driver positions are recorded separately (`driver_mean_position`). No gain was fabricated.

### Individual vs team objective (Track C Engineers, C4)

On the live B7 Layer 2 data, C4 confirms 10 decisions labelled `EXCESSIVE_RELIANCE_ON_ENGINEER_RECOMMENDATIONS`. In each, the Chief's pit choice for a driver equals that driver's Engineer proposal and has positive team regret, with a CI above 1 point. There is one `UNJUSTIFIED_REJECTION`.

Engineer disagreement alone is never labelled a failure. All the cited evidence was public (`PUBLIC_ALREADY_AVAILABLE_HIGHLIGHTED`). This family has no new scripted generator in B8 (§7).

## 5. Evaluation-design summary

| Family | Generation | Frequency | Legal actions | Reference | Reversals / controls / near ties | Regret CI |
|---|---|---|---|---|---|---|
| A1 bundling | natural, synthetic and held-out generators (§2) | 92% / 87% / 95% acceptance | 4 replacement plans | multi-race public-process rollout | bundle clearly better 17 / 22 / 27, distribute 1 / 9 / 1, near ties 43 / 14 / 6 (natural / synthetic / held-out) | paired 95% |
| A2 timing | order-swapped pairs | all decision states | NOW vs DEFER | same | reversals 1 / 1 / 5; clear no-change controls 25 / 21 / 12 | paired 95% |
| Rival reversal | B6 sampler, held-out seeds | 4 decisions per race | 16 joint pit actions | rollout with the rival rule known | 4.7–16.7% / 320–366 no-change | mean loss reported |
| Swap / give-back | executable exchange states | ~8% of decisions | RACE, HOLD, SWAP, BUFFER; KEEP or GIVE_BACK | rollout | near-tie shares 72–81% | means and shares |
| Individual vs team | live B7 Layer 2 | 112 decisions | 16 + Engineer reports | public rollout + C4 gate | C4-confirmed 10 / 1 | CI lower bound above 1 point |

**Acceptance rates are not F1 incidence.** No case was selected on any model's behaviour. Held-out sets were used only for the final runs.

## 6. Practice / Qualifying (C5)

**Contract proposed in `docs/C5_INTERFACE_CONTRACT.md`:**
- the phases, observations and actions;
- information acquisition with noise shrinking in laps;
- the one-lap vs race-pace setup trade-off;
- penalties applied after qualifying via `fia_grid`;
- persistent resources and journal/replay requirements.

It also specifies the pure functions C5 must deliver.

**Status: not integrated.** C5 is not available on any fetched branch, and the shared engine has not changed for it. No PRACTICE/QUALIFYING mechanics are claimed.

## 7. Additional scenarios: feasibility only (none implemented)

| Scenario | Feasibility |
|---|---|
| Retire vs continue to save components | Needs per-lap wear accrual tied to distance raced (wear is per race today) and an in-race RETIRE action. Moderate; changes the wear model, so it would need a new version. |
| Upgrade budget and timing | `development_units` already exist in the inventory, unused. Needs a pace-gain model and a spend action. Moderate. |
| Parc fermé and pit-lane start | Depends on C5 setups. A pit-lane start is a grid placement rule, which is easy once C5 exists. |

## 8. Compatibility and integrity (tests)

| Check | Result |
|---|---|
| `scripts/py312 -m unittest discover -s devtests -p 'test_*.py'` | **204 tests OK**, including the new `test_b8_pu_rules.py` (8 tests) and C4's tests |
| Default rules untouched | No `pu_rules` key by default; legacy replacement cost and inventory are unchanged; the 2.0.1 two-team season has no stock fields and replays |
| FIA fixture | Equals the verified text (10/5/15). The declared scalings are recomputed by code and match. |
| Grid construction | Worked examples, including back-of-grid ordering, ties and slots beyond the field. 2,000 random penalty sets: always a permutation; unpenalised keep their order; back-of-grid drivers last in qualifying order. |
| Inventory conservation | Stock = 3 − replacements per team and type over a full 2.1.0 season; never negative |
| 2.1.0 full season | 8 races complete, journal replays exactly, team points = sum of driver points, observations report 2.1.0, no seed/event/draw leakage |
| 2.0.1 vs 2.1.0, same seeds (4 seeds, scripted) | Identical points: the scripted Chiefs never replace and the rivals' first replacements are within allocation. Journals differ only through the version field. All replay exactly. |
| Harbor (Verda) | 1.1.0 task: lint OK; `b8-oracle-01` 0.5873 and `b8-nop-01` 0. **The oracle journal is identical to `v110-oracle-01`** (observation hashes and actions). Integrated SOLO_COORDINATION task: lint OK; `b8i-oracle-01` 0.5873. |

**Reproduce:**
```
scripts/py312 -m unittest discover -s devtests -p 'test_*.py'
scripts/py312 analysis/b8_penalties.py --calendars 60 --futures 8 --generator synthetic
scripts/py312 analysis/b8_penalties.py --calendars 60 --futures 8 --generator natural
scripts/py312 analysis/b8_penalties.py --calendars 40 --futures 8 --generator synthetic --offset 100
scripts/py312 analysis/b8_families.py --seeds 12 --futures 12
```

**Results:** `analysis/results/b8_penalties_{synthetic,natural,synthetic_heldout_100}.json` and `b8_families_heldout.json`.

## 9. Commits

All B8 commits are on `feature/strategic-scenarios-b8`, branched from B7 `f9b47c4`, and pushed to origin. `main` and `feature/championship-integration` are untouched by B8.

| Commit | Content |
|---|---|
| `c88177a` | Opt-in 2.1.0 PU rules, engine hooks, tests |
| (this commit) | B8 evaluations (`b8_penalties.py`, `b8_families.py`), results, this report, the C5 contract, VERSIONS and ROADMAP |

## 10. Unresolved blockers and research limitations

1. **Scaling.** Allocation, places and stock are synthetically scaled to an 8-race, 8-car championship. Only three element types are modelled, and there is no pool rotation, so real-world fidelity is limited to the rule **structure**.
2. **References.** They use fixed baseline race strategies. The penalty references value plans, not jointly optimised race strategy; values are lower bounds and continuation-dependent.
3. **Low reversal counts.** 1 reversal in each development set and 5 in held-out. The timing effect is real but not frequent; correlation is the stronger evidence.
4. **No model has been evaluated on 2.1.0.** That needs a separate decision, as the task requires.
5. **C5 is not integrated** (contract only).
6. **The Individual vs Team family** has live evidence (B7 Layer 2), but no scripted generator yet.
7. **Two-team play is still outside Harbor** (B6/B7 limitation).
