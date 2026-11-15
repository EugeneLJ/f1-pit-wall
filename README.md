# F1 Championship Strategist 2.2

**What happens when an AI must run the entire racing weekend—and deal with its own team and its rivals?**

> **Experimental development branch · Not the verified 2.1.0 submission · [Implementation status](#what-is-actually-implemented-and-tested) · [Gemini collaboration study](#gemini-api-challenge-can-a-team-of-ai-agents-work-together)**

Our [verified 2.1.0 benchmark](https://github.com/EugeneLJ/f1-pit-wall/tree/submission/2.1.0) asks a Chief Strategist to manage two cars across eight races. **Version 2.2.0** extends the questions: What is worth learning before race day? How much can a strategist trust a weather forecast? What if its drivers and rivals have their own objectives? Can an AI Chief make better choices with two AI Engineers offering advice?

**The objective stays simple: maximise championship points for the team. The decisions become more complicated.**

**Status note:** C5 and M2/M6/M7 have been implemented and tested in **separate integration branches**. An all-features unified Harbor/OpenCode Frontier evaluation has **not** been verified in the source material used for this README. Each validation result below names its own configuration.

## Meet the paddock

### McLearn Racing — two drivers, one team objective

The Chief Strategist wants the largest possible **Constructors' Championship** score: combined points from two drivers. But a driver may prefer to protect their own position in the **Drivers' Championship**. A request to yield a position could be best for the team and unacceptable to the driver.

### Red Bool Racing — a rival that changes the calculation

An opponent who usually defends, one who avoids risky overtakes and one controlled by another AI strategist can each require different responses. In experimental two-team modes, a rival Chief may be powered by **DeepSeek through Verda** instead of a fixed policy.

*These are fictional team identities for the expanded scenario narrative. The supported teams and agent control settings depend on the selected configuration; do not infer that every illustrative interaction is active in one completed Harbor benchmark.*

## How a championship weekend works

In the C5-enabled configuration, the season adds three decisions per race—**two practice programmes and a qualifying decision**—before race strategy. The season grows from **120 to 144 decision points**.

```text
POWER-UNIT DECISIONS
        ↓
PRACTICE 1 ── What should we test?
        ↓
PRACTICE 2 ── What is still worth learning?
        ↓
QUALIFYING ── Which setup and run plan?
        ↓
RACE ── Pit, stay out, coordinate both drivers
        ↓
CHAMPIONSHIP ── Carry points and resources forward
        ↓
Next race ...
```

**Practice is not free information.** Each driver has a limited practice-lap budget. Qualifying simulations, setup tests and long-run tests reveal different noisy information. Spending laps on one reduces the opportunity to learn something else.

**Qualifying is not the finish line.** A setup that earns a better starting position can alter long-run pace and tyre degradation after the race begins. Power-unit grid penalties still apply after qualifying order is established.

**The race is affected by what came before.** Pit strategy must work with the selected setup, race position, remaining resources and the observed conditions.

The C5 implementation currently models dry-weekend setup effects. Its interaction with M7 weather must be explicitly resolved and tested before the combined mode can be called validated.

## Six decisions that make 2.2 challenging

The following situations explain **what each mechanic tests**. They are illustrative decision problems, not six claimed live-model failures.

### A. The practice dilemma — what is worth knowing?

McLearn has only a limited number of laps. It can investigate qualifying pace, long-run pace or tyre degradation, but it cannot thoroughly test everything. Measurements contain noise, so one fast observed lap is not necessarily a reliable answer.

**Why it's hard:** the strategist must choose **which information to acquire**, not just which action to take afterward. A poor experiment can make all later decisions worse.

**Evaluates:** information gathering, uncertainty management, and planning across phases. **Mechanic:** C5.

### B. Fast on Saturday, slow on Sunday

McLearn can choose a setup that helps qualifying but is less attractive over a race distance. Qualifying position matters, yet the race lasts far longer than one flying lap.

**Why it's hard:** optimising one stage can hurt a later stage, and grid penalties further change the value of qualifying position.

**Evaluates:** multi-stage trade-offs and the opportunity cost of local optimisation. **Mechanic:** C5.

### C. The opponent who might defend

Red Bool has defended several recent positions. Is that a real tendency, or just a coincidence of the situations it faced? The strategist sees behaviour, not a private tendency label.

**Why it's hard:** incorrect assumptions about a rival can make a pass attempt, defensive response or alternate pit strategy unattractive.

**Evaluates:** opponent inference from partial observations. **Mechanic:** M2. **Scope:** the current implementation uses existing defence and pass-suppression physics, not the full planned pace-mode and proximity/attack-resolution system.

### D. The driver who says no

McLearn's Chief asks a leading driver to give a position back. The driver also has individual championship interests. The Chief can see a published probability of compliance, but cannot know the private random outcome before giving the order.

**Why it's hard:** the team's preferred instruction is not necessarily the action another participant will follow. The strategy must account for refusal and possible recovery.

**Evaluates:** conflicting incentives and coordination under uncertain compliance. **Mechanic:** M6.

### E. Rain is coming. Maybe.

A public forecast predicts wetter conditions, but the track remains dry. Pitting for intermediate or wet tyres now could help if rain arrives soon, and hurt if it does not. Waiting has the opposite trade-off.

**Why it's hard:** current observations and forecasts are useful but do not reveal future weather. Tyres, wear, pace and incident risks interact.

**Evaluates:** sequential decision-making with uncertain forecasts. **Mechanic:** M7. **Scope:** seeded synthetic weather, not a calibrated real-world meteorological model.

### F. Two Engineers, three strategies

Engineer A recommends one tyre; Engineer B wants to protect the other driver. The Chief may have its own plan. Advice can be confident, detailed and still make the final decision worse.

**Why it's hard:** the Chief must integrate local recommendations into a **shared** team objective without confusing confidence or authority with correctness.

**Evaluates:** multi-agent advice, disagreement and decision arbitration. **Mode:** optional Gemini Chief + Gemini Flash-Lite Engineers; live diagnostic evidence is separate from the combined 2.2.0 benchmark.

## From a single AI to an AI racing organisation

```text
        Gemini Chief Strategist
          (final decisions)
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
  Engineer A            Engineer B
 Gemini Flash-Lite     Gemini Flash-Lite
   Driver A view         Driver B view
      └──────────┬──────────┘
                 ▼
           Team decisions
                 │
                 ▼
         Trusted simulator
                 │
                 ▼
         Rival-team policy
       scripted / adaptive AI
```

The runtime design supports distinct **Chief-only versus Engineer-assisted** and **scripted versus adaptive rival** conditions. The purpose of these switches is to ask whether a performance change comes from better advice, changed opponent behaviour, or other mechanics. A provider connectivity smoke test is **not** evidence that the full combined benchmark works end to end.

## What is actually implemented and tested?

| Component | Verified scope | Not yet established |
|---|---|---|
| **C5 practice + qualifying** | Separate integration branch; 144-decision exact replay; **274 devtests, 51 root tests**; real Harbor **scripted oracle smoke: 266 points / 0.6905**, no-op 0 | Strong public-information reference; fresh Gemini Frontier gap; C5 × M7 combined behaviour |
| **M2/M6/M7** | Separate integrated candidate; **263 devtests, 35 legacy tests**, full-season exact replays, combined M2+M6+M7 seed 21; all-off parity with 2.1.0 | Genuine Docker/Harbor Gemini run of that candidate; complete M1/M3-related rival interactions |
| **2.2.0 local generated task** | Completion, 120 ticks, intact evidence, local grader reward **0.40562249**, **zero model calls** | An official Harbor/Frontier result; this value is **not** a Gemini score |
| **Engineer/rival runtime** | Existing B6/B7 components; additional runtime configuration and provider smokes in progress | Complete mode matrix on a single unified 2.2.0 task |
| **Unified C5 + M2 + M6 + M7** | Integration targeted as the next milestone | Full cross-feature replay, weather/setup agreement, genuine Harbor Frontier–Reference comparison |

**Interpretation matters:** the C5 **oracle smoke** uses a fixed practice/qualifying policy and is **not** a strong 2.2.0 reference. The M2/M6/M7 local task reward is a no-model packaging test. These results must not be compared directly with the official 2.1.0 289-point reference or Gemini scores.

### Where to inspect the work

- [`feature/c5-integration`](https://github.com/EugeneLJ/f1-pit-wall/tree/feature/c5-integration): C5 weekend integration and Harbor smoke evidence. See [`C5_INTEGRATION.md`](https://github.com/EugeneLJ/f1-pit-wall/blob/feature/c5-integration/f1-championship/docs/C5_INTEGRATION.md).
- [`feature/v22-integrated-candidate`](https://github.com/EugeneLJ/f1-pit-wall/tree/feature/v22-integrated-candidate): independent M2/M6/M7 integrated candidate. See [`V22_HARBOR_READINESS.md`](https://github.com/EugeneLJ/f1-pit-wall/blob/feature/v22-integrated-candidate/f1-championship/docs/V22_HARBOR_READINESS.md).
- [`submission/2.1.0`](https://github.com/EugeneLJ/f1-pit-wall/tree/submission/2.1.0): verified public benchmark and genuine Gemini results.

## Run an experimental configuration

The commands below run **separate branches**, not the unfinished all-features integration.

**C5 Harbor smoke** — from the `feature/c5-integration` checkout, on a machine with Docker and Harbor:

```bash
F1_C5_WEEKEND=1 f1-championship/scripts/make_integrated_task.sh /tmp/c5task CHIEF_ONLY 2.2.0
harbor run -p /tmp/c5task -a oracle
harbor run -p /tmp/c5task -a nop
```

**M2/M6/M7 task verification** — from the `feature/v22-integrated-candidate` checkout:

```bash
cd f1-championship
scripts/validate_v22_task.py --dest /tmp/f1-v22-verified --output /tmp/f1-v22-evidence
```

The second command is an **offline task/verifier validation**, not an actual Harbor/OpenCode model evaluation. For a complete, validated model run today, start with [benchmark 2.1.0](https://github.com/EugeneLJ/f1-pit-wall/tree/submission/2.1.0).

## Integrity first, even when the game gets harder

The principle remains unchanged: **a strategy earns points by finishing the simulated championship, not by rewriting its score**. The trusted simulator controls hidden state, an authenticated journal records actions, and a separate verifier replays them independently.

New features require new checks: practice/qualifying actions must be replayable, forecast observations must not leak future weather, private rival tendencies must stay private, and team-order compliance must be reproducible from the trusted seed.

Version 2.1.0 has published no-op, stop-early, tamper and clean-host results. **Those tests cannot automatically be treated as passed for every 2.2.0 mode.**

## Next milestones

1. Merge C5 and M2/M6/M7 with independent opt-in flags, without changing the verified 2.1.0 submission.
2. Specify and test **practice setup × weather** interactions and the remaining M2 rival mechanics.
3. Integrate and validate Chief-only/Engineer-assisted and scripted/adaptive-rival execution modes.
4. Implement a **new public-information reference** capable of choosing practice, qualifying, race and weather actions on the same information available to the agent.
5. Run genuine complete-season Harbor/OpenCode Gemini trials, matched reference trials, and no-op, stop-early and tamper checks for clearly named configurations.
6. Study where decisions reverse, when advice helps or hurts, and whether apparent improvements hold across seeds.

**Research aim:** explain *which kinds of strategic reasoning fail, under which observable conditions*, rather than manufacture impressive-looking point gaps.

## Gemini API Challenge: can a team of AI agents work together?

The project uses **Gemini 3.8 Flash** as a Chief Strategist and **two Gemini 3.5 Flash-Lite** models as driver-specific Engineers in a separate, controlled diagnostic. The Chief receives their recommendations but remains responsible for the final action.

The **C8 study** evaluated **40 states across six Chief conditions (240 genuine Chief calls)**. Real Engineer advice changed the Chief's decision in **5/40 states**. The study did **not** establish an average improvement from adding Engineers. In one illustrative case, the Chief moved from HARD to MEDIUM after Engineer advice, and the estimated decision regret increased **4.5–5.1 points** under the tested counterfactuals.

The finding is not that AI Engineers always harm strategy. It is that **adding more models changes the information and incentives around a decision—and the final choice still needs scrutiny**.

This result comes from **separate Gemini API diagnostics**, not a completed unified 2.2.0 Harbor run. See the [C8 evaluation report](https://github.com/EugeneLJ/f1-pit-wall/blob/submission/2.1.0/f1-championship/docs/C8_ENGINEER_CONFLICT_RESULTS.md).

## References & further reading

1. Liu et al. (2024). [*AgentBench: Evaluating LLMs as Agents*](https://arxiv.org/abs/2308.03688). ICLR 2024.
2. Yao et al. (2024). [*τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*](https://arxiv.org/abs/2406.12045).
3. Xu et al. (2025). [*TheAgentCompany: Benchmarking LLM Agents on Consequential Real World Tasks*](https://arxiv.org/abs/2412.14161). NeurIPS 2025.
4. Cemri et al. (2025). [*Why Do Multi-Agent LLM Systems Fail?*](https://arxiv.org/abs/2503.13657). NeurIPS 2025.
5. [FIA Formula One Regulations](https://www.fia.com/regulations) — motorsport context. The benchmark has **fictional** teams, synthetic races and coefficients, and scaled rules; it is not an official F1 simulator.

*F1 Championship Strategist, McLearn Racing and Red Bool Racing are fictional research/game concepts, not affiliated with Formula 1, the FIA or real F1 teams.*
