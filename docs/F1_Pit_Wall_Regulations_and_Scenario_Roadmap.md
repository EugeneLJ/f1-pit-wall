# F1 Pit Wall: FIA Rules, 2026 Calibration, and Strategic Scenario Roadmap

**Purpose:** Design notes for a realistic, auditable F1-inspired agent benchmark that exposes *decision-making failure modes*, rather than making an agent fail through arbitrary difficulty or hidden rules.

**Status:** Proposal and implementation roadmap, not a statement that the features below have been implemented. Regulatory details must be checked against the exact, versioned FIA documents used for the selected 2026 event or benchmark ruleset.

## 1. Benchmark objective and existing architecture

The benchmark evaluates a frontier **Chief Strategist** managing an **eight-race Constructors' Championship**. It is intended to identify and reproduce failures in:

- **Track A — Long-horizon strategy:** allocating limited components and other resources across races, accepting short-term losses to improve the season outcome.
- **Track B — Adaptive race strategy:** choosing pit stops and tyre compounds, responding to changing conditions, and revising plans when rivals act unexpectedly.
- **Track C — Multi-agent coordination:** reconciling recommendations from driver-specific Race Engineers A and B while optimizing the team's combined Constructors' Points.

The game is executed through a **Harbor sidecar simulator**. The agent can use a limited command client, but should not be able to read hidden events or seeds, reset the world, alter simulator logs, or modify the verifier's outcome. Public rules and observations must be sufficient for defensible strategic choices; a fair reference policy receives the same information and action opportunities.

The benchmark should distinguish **action legality**, **strategic decision quality**, **adaptation to new information**, **coordination quality**, **completion**, and **evaluation integrity**. A lower score alone is not evidence of any particular failure mode.

### Current development context

At the time of this design discussion, Track A's existing implementation had already demonstrated a gap between greedy component allocation and a season-aware reference. Track B had been expanded to a longer sequence of in-race decisions and tyre strategies; SC/VSC-driven replanning and Frontier-agent probes were next in the roadmap. The proposals below extend that work rather than replace it. Newly proposed regulations and scenarios are **not** assumed to be implemented.

## 2. Use FIA documents as a versioned source of truth

### Recommendation

**Translate official regulations into explicit, testable simulator rules.** Do not rely on an LLM having implicitly memorized a regulation, and do not use retrieval from regulatory documents as an unverified substitute for game logic.

Use a source hierarchy:

| Source | Purpose | Implementation treatment |
|---|---|---|
| FIA Sporting Regulations | Component allowances, grid penalties, parc fermé, race procedure, permitted actions | Deterministic rule engine with explicit effective dates |
| FIA Technical / Power Unit Regulations | Component taxonomy and technical restrictions | Structured component and compliance definitions |
| FIA Financial Regulations | Spending and resource constraints | Budget rules, if the development module is added |
| FIA stewards' decisions, event documents, starting-grid notices | Real applications, exceptions, and interpretation examples | Regression cases and manually reviewed examples |
| Historical race timing / telemetry-derived data | Pit loss, passing patterns, pace and degradation relationships | Calibration data, not normative rules |
| Synthetic coefficients | Unobserved reliability, strategic response, development effects | Explicit assumptions with uncertainty ranges |

Maintain a machine-readable rule manifest (`regulations_year`, `document_title`, `revision`, `effective_date`, `article`, `implementation_rule`, `test_case`). Store public rules separately from hidden runtime state.

### Primary official entry points

- [FIA Regulations](https://www.fia.com/regulations)
- [FIA Formula One regulations and event documents](https://www.fia.com/documents/fia-f1-regulations)
- [FIA Formula One World Championship](https://www.fia.com/championship/world-championships/fia-formula-one-world-championship)

**Verification required before coding:** Confirm the precise 2026 component allocation by type, the penalty assigned to first and subsequent excess allocations, the grid-order rules for large accumulated penalties, whether and how penalties are carried over, exceptions, and the relevant versions of parc fermé and pit-lane-start rules. Do not hardcode numbers from secondary summaries without checking the effective FIA Sporting Regulations and event decisions.

## 3. The first-year-2026 simulation problem

The 2026 regulations introduce a major technical discontinuity. A model calibrated on pre-2026 race results should not simply assume that 2025 absolute pace, tyre effects, power-unit reliability, or energy usage persist unchanged.

Use a layered approach:

1. **Transfer stable structure.** Track geometry, pit-lane loss components, race distance, and some safety-car or traffic relationships provide useful priors, with event-specific changes checked.
2. **Recalibrate regime-dependent behavior.** Tyre degradation, compound performance, vehicle/track compatibility, outright pace, energy deployment, and power-unit reliability should use 2026 evidence where available.
3. **Represent limited data honestly.** For quantities that cannot be estimated reliably, provide documented synthetic distributions or uncertainty intervals rather than claiming authentic 2026 performance.
4. **Respect information timing.** A strategist operating at Race 2 should not be given results or calibrated knowledge that only became available at Race 7. Distinguish *simulator truth*, *publicly observable signals*, and *agent estimates*.
5. **Test sensitivity.** Verify whether policy rankings persist across plausible coefficient ranges. Report fragility rather than tuning a single parameter set to create a desired failure.

Historical results are useful for **offline calibration and structural validation**, but they are not the ground-truth answer to counterfactual strategy choices in a newly regulated season.

## 4. Proposed strategic scenario families

### A1. Multi-component power-unit allocation and penalty stacking — **highest priority**

A power unit comprises separately tracked components (e.g., ICE, turbocharger, energy store, control electronics and relevant hybrid components). Each has its own permitted allocation, use history, degradation, replacement eligibility and applicable grid penalties.

**Strategic alternatives:**

- **Concentrate replacements:** Replace several over-limit components at one event; accept a severe starting-grid loss in one race in exchange for fresher parts in later races.
- **Distribute replacements:** Replace different components at separate events; preserve some points potential each weekend but face penalties in multiple races.

The *nominal* sum of penalty positions and the *actual* competitive effect are different. Large penalties may place a driver at the back under the applicable grid-order rules, and an unused portion of nominal grid positions should not automatically become a debt in later races. The new component allocations and their later performance effects, however, persist.

**Simulation requirements:**

- Individual component inventory, allocation history, wear, and replacement thresholds.
- Driver-specific regulatory allocations **separate from** the team's physical spare stock.
- Correct penalties for each component and the combined penalty applied under the versioned rule set.
- Race-grid construction that remains a valid permutation, including penalties incurred by other teams.
- Nonlinear wear-related pace/reliability effects under documented, plausible assumptions.
- Replacing now vs later must affect expected Constructors' Points through an actual race mechanism, not only a bookkeeping field.

**Failure mode:** The agent evaluates replacements one component at a time, spends scarce allocations too early, or misunderstands the non-additive effect of stacking penalties in one event.

**Evaluation:** Compare concentration and distribution policies on representative calendar samples; assess regret under an equal-information reference. Include conditions where each approach is preferable and near-tie controls.

**Eight-race realism note:** An eight-race benchmark should not necessarily start with all regulatory component allocations unused. A plausible *mid-season eight-race window*, with documented initial component use and wear, can create relevant decisions without falsifying full-season FIA limits.

### A2. Choosing the track at which to take a penalty — **highest priority**

Replacement value depends on the circuit and the team's vehicle characteristics, not merely the number of grid places lost.

Potential tensions:

- A difficult-to-overtake street circuit makes recovery from a grid penalty harder, but a car that is poorly matched to that circuit may have less expected points to sacrifice.
- A high-speed circuit may allow recovery through overtaking, but it may also be an unusually valuable points opportunity for a team with strong straight-line performance.
- Later race order, tyre demands, component stress and championship standings alter the opportunity cost.

**Failure mode:** The agent always takes penalties on the hardest-to-overtake track, or always takes them where overtaking is easiest, ignoring track-specific expected points and future options.

**Controlled test:** Hold current state constant and vary plausible later calendar conditions; evaluate whether the decision's expected value changes. Include no-reversal controls and quantify *points lost by choosing the wrong policy*, not merely the number of different actions.

### B1. Rival pit-stop count and strategic response — **high priority**

Rival strategy should not be limited to a one-lap undercut or overcut. A rival might shift between two-stop and three-stop strategies, creating a choice between **responding** and **staying committed to the original plan**.

Useful mechanics:

- Rival pit-stop counts emerge from their policy and observable race state rather than a fixed scripted answer.
- Tyre compounds, degradation, pit loss, traffic and remaining laps determine whether an extra stop pays off.
- The Chief sees observable rival actions and timing, not the rival's hidden future intentions.
- SC/VSC state can change the relative value of two- and three-stop strategies.

**Failure mode:** The Chief imitates an unexpected rival stop reflexively, or refuses to replan when evidence strongly favors changing strategy.

**Case-study note:** Any specific 2026 Grand Prix anecdote (including a claimed Hamilton Barcelona win or exact stop count) must be independently checked against official classification and tyre-strategy data before being cited in a public README. The benchmark concept does not depend on that example being accurate.

### C1. Asymmetric roles for two drivers — **high priority**

When the team's drivers start far apart, the Chief may choose between:

- **Independent optimization:** Maximize each driver's own expected finishing points.
- **Coordinated strategy:** Use the trailing car's legitimate pace, tyre and track position to influence competitors' pit-exit traffic, preserve the leading car's race position, or provide a strategically useful long first stint.

The simulation must enforce legal racing behavior. Do **not** reward unsafe or prohibited obstruction. Tow/slipstream benefits should occur only under plausible track proximity and race conditions, not as a guaranteed benefit for a lapped teammate.

**Failure mode:** Engineer A and Engineer B each give locally rational, conflicting recommendations; the Chief prioritizes one driver without checking whether the team's total expected points improve.

**Evaluation:** Compare Chief alone, aligned advice, conflicting advice, and miscalibrated-confidence advice, with evidence visible for each recommendation. Separate the effect of advice from the underlying race mechanics.

### A3. Development budget and driver-specific upgrades — **later extension**

F1 development is constrained by spending rules, technical requirements, testing/development resources, manufacturing lead times and relevant homologation restrictions—not simply a universal cap on the number of upgrades.

Possible choices:

- Improve the car's weakness for Driver B versus reinforce the traits Driver A exploits best.
- Deploy an upgrade early for more races of benefit versus wait for greater confidence or strategically favorable timing.
- Balance expected points, installation risk, testing time and remaining budget.

**Caution:** Do not assume rivals instantly copy an upgrade, or that power-unit updates freely benefit all competitors. Such effects require a defensible, separately documented mechanism; power-unit development is subject to its own regulations.

**Failure mode:** Misallocation of a shared development resource to the locally strongest driver, without considering total Constructors' benefit or lead times.

### A4/B2. Finish for marginal points or retire to preserve components — **later extension**

At the edge of the points, the Chief may evaluate the chance of scoring a point against the additional wear and reliability exposure caused by completing the remaining laps.

**Important distinctions:** A voluntary strategic retirement does not erase existing wear or create a fresh component. A car that must stop for safety or regulatory reasons is not making a discretionary strategy choice.

**Failure mode:** Overvaluing marginal current points or overvaluing future component preservation. Assess expected outcomes and hard safety constraints separately.

### B3. Parc fermé configuration change versus pit-lane start — **later extension**

After a disappointing qualifying result, the team could consider changing regulated setup parameters, accepting the applicable pit-lane-start consequence when the rules require it, in exchange for potentially better race pace.

**Requirements:** Model qualifying performance, the setup/race-pace trade-off, the permitted modifications and applicable procedural penalties under the specific FIA regulations. A generic "free setup reset for pit-lane start" is not sufficient.

**Failure mode:** The agent ignores the opportunity cost of starting from the pit lane, or refuses a beneficial configuration change because the penalty is immediately salient.

## 5. Cross-cutting benchmark design requirements

### Fair, diagnostic scenarios

- Generate plausible scenarios using public rules and independent parameter ranges **before** looking at the Frontier agent's failures.
- Use *counterfactual pairs*: same early conditions, with a controlled change to the later calendar, event outcome or rival strategy.
- Include **decision-reversal**, **no-change**, and **near-tie** cases. Do not cherry-pick only examples that make a specific agent look bad.
- Validate candidate scenarios with a fair planning reference; use exhaustive search only for appropriately reduced problems and label approximate full-season policies correctly.
- Record both final Constructors' Points and decision-level opportunity costs. A valid move or a different move is not automatically a mistake.
- Distinguish the fair-reference gap from a **privileged full-hindsight** bound; the latter uses information unavailable to the agent and is diagnostic, not proof of avoidable regret.

### Information boundaries

Publish the exact game rules and modeled transition relationships; expose legitimate live observations (e.g., track traits, tyre history, observed competitor pace and published component allocations). Keep RNG state, future event outcomes and confidential simulator state outside the agent container. Provide the fair reference the same information it could observe at each point.

### Scoring and reporting

Keep independent fields for action validity, completion, integrity, raw Constructors' Points, race-level and season-level regret, adaptation after event changes, and cross-driver coordination. Treat the scalar Harbor reward as a reporting interface, not a substitute for those diagnostics.

## 6. Prioritization and implementation order

| Priority | Proposal | Track | Reason |
|---|---|---|---|
| 1 | Multi-component quotas and stacked penalties | A | Strong, realistic long-horizon resource decisions |
| 2 | Track-dependent penalty opportunity cost | A | Reuses existing track/car performance model |
| 3 | Rival two-stop/three-stop response | B | Tests strategy revision after observable rival action |
| 4 | Asymmetric two-driver cooperation | C | Creates measurable local-versus-global objectives |
| 5 | Qualifying/parc fermé trade-offs | B | Adds a distinct pre-race decision layer |
| 6 | Voluntary finish/retire trade-off | A/B | Connects immediate points to future component wear |
| 7 | Driver-specific upgrade allocation and timing | A extension | Potentially valuable but significantly harder to calibrate |

**Recommended development sequence:**

1. Finish and validate the current **B4 SC/VSC replanning** implementation.
2. Conduct an **initial Frontier-agent probe** with the existing benchmark before changing several mechanics at once; save traces and limitations.
3. Introduce **A1 + A2** (multi-component penalties and track-dependent penalty timing) as a controlled Track A enhancement and compare with the preserved baseline.
4. Add **B1** (rival stop-count adaptation) with counterfactual tests.
5. Introduce **C1** (Engineer A/B advice and coordinated driver roles) with no-engineer/aligned/conflicting controls.
6. Consider qualifying, retirement and development modules only if they create new, distinguishable strategic failure modes at an acceptable verification and calibration cost.

Retain the eight-race Championship as the core task. Avoid reducing meaningful event-driven decisions merely to save API calls; optimize wall-clock time and parallelism separately. Preserve the legacy single-race task as a regression baseline and maintain the Harbor sidecar security boundary throughout.

## 7. Questions to resolve before implementation

1. Which precise FIA 2026 regulation revision applies to each proposed event? What are the authoritative component counts and all relevant penalty/grid-order edge cases?
2. Should the eight races represent an entire synthetic mini-season, or a mid-season window within the real regulatory season? What is the initial component allocation history?
3. How should other teams' component replacements and penalties affect actual grid construction?
4. Which 2026-derived parameters can be estimated from observed events, and which must remain synthetic with uncertainty intervals?
5. Can natural, representative scenarios produce genuinely different preferred penalty-stacking or penalty-timing strategies, rather than differences engineered by parameter tuning?
6. Which proposed upgrade and pit-lane-start decisions are allowed by the selected regulations and can be scored without speculative mechanisms?
7. How will each new feature change the fair-reference plan, and how will its effect be isolated from Tracks B and C?

## 8. Next deliverables

- **Regulation matrix:** FIA clause / effective revision / structured rule / implementation test / evidence link.
- **Track A scenario specification:** component-specific allocations, stacked penalties, driver-specific inventories, race/grid state transition, and representative concentration-versus-distribution cases.
- **Calibration notebook or script:** prior versus 2026-dependent coefficients, source provenance and sensitivity analyses.
- **Counterfactual evaluation suite:** reversal and control pairs, equal-information reference, and opportunity-cost measurements.
- **Updated roadmap and benchmark documentation:** explicit separation between implemented behavior, proposed behavior and empirically observed agent failures.

---

*These notes summarize proposed directions from the project discussion. Specific FIA rule counts, penalty articles and real-race anecdotes should be verified from versioned primary sources before public claims or simulator rule implementation.*
