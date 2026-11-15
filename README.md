# F1 Championship Strategist

**Can AI win the championship, not just the race?**

> **Verified submission · Benchmark 2.1.0 · [Watch the demo video](https://youtu.be/A9vm8M3uLek) · [Try the demo](#try-it-yourself) · [Research extensions](#what-comes-next-22)**

Imagine managing a Formula 1-inspired racing team. You have **two drivers, eight races, 120 decisions, and one goal: score as many championship points as possible**. Every choice affects something else. A tyre change may win time now but sacrifice track position; using an ageing power-unit component may preserve a spare for a more important race; helping one driver may hurt the other.

**F1 Championship Strategist** is an interactive benchmark for testing whether AI agents can make good decisions across an entire season—not merely finish a single race.

**[One-command recorded demo](#try-it-yourself)** · **[Verified results](#what-happened-when-we-tested-gemini)** · **[Integrity checks](#can-the-agent-cheat)** · **[Technical documentation](f1-championship/README.md)**

<!-- Optional: insert the existing genuine demo screenshot here after selecting a verified path. -->

## The championship, explained

A *Constructors' Championship* rewards the **combined results of both drivers on a team**. The agent acts as Chief Strategist for fictional team **Apex GP**. Six other cars follow fixed, published rules in the submitted version.

| | Verified 2.1.0 task |
|---|---|
| Season | 8 simulated races |
| Cars managed | 2 |
| Sequential decision points | 120 |
| Decisions | Power-unit use/replacement, pit timing and tyre compound, team orders |
| Goal | Maximise combined Constructors' Championship points |
| Opponents | Fixed-rule rivals, **not** rival language-model agents |
| Evaluation | Harbor + OpenCode, sealed simulator and independent verifier |

Three racing concepts worth knowing:

- **Pit stop:** a car enters the pit lane for fresh tyres. New tyres may improve pace, but the stop costs time and track position.
- **Safety Car (SC) / Virtual Safety Car (VSC):** the field slows after an incident. Stopping during these periods can cost less time than stopping during normal racing.
- **Starting-grid penalty:** a car may have to start further back after exceeding its power-unit component allocation. Some resources therefore matter across many races.

The AI reads the current state and the published rules, then selects an action. It cannot see future random events, rewind a mistake, or ask the simulator to reveal the outcome of an unchosen strategy.

## Why these decisions are genuinely hard

### 1. Winning this race versus protecting the season

An ageing power-unit component might still be usable today. Replacing it early may reduce a reliability risk, but it also consumes a limited allocation and can create a later grid penalty. A one-race optimiser can miss the cost of using resources before they are really needed.

**Capability tested:** long-horizon planning, limited-resource allocation, and reasoning about future consequences.

### 2. The right pit stop depends on what you *don't* know

A Safety Car makes stopping cheaper, but not automatically better. The decision depends on tyre age, remaining laps, traffic, the other car's strategy and what might happen next. The rules and probabilities are public; the actual future is not.

**Capability tested:** planning and updating decisions under uncertainty.

### 3. Two individually sensible actions can be a poor team decision

Both cars may want fresh tyres at once, but the team has one pit crew. The second car can lose time in a **double stack**. Likewise, an order to swap positions can benefit one driver without helping the team's total score.

**Capability tested:** joint optimisation with shared resources and competing objectives.

### 4. A good result is not proof of a good decision

In a recorded Race 7 Safety Car situation, Gemini stayed out while the reference pitted. **Both ultimately scored 33 points in that race.** A public-information counterfactual nonetheless estimated about **3.9 points of decision regret** for Gemini's choice in the illustrated run. That is **an expected, model-based decision difference—not 3.9 realised points lost in Race 7**.

**Capability tested:** distinguishing decision quality from a lucky outcome, without confusing counterfactual estimates with observed scores.

## Try it yourself

The repository includes a self-contained HTML report with an eight-race points chart, race cards, decision examples, provenance and verification checks.

**Instant replay of a genuine, recorded Harbor run:**

```bash
scripts/demo.sh recorded
```

**Fresh Gemini/OpenCode season:**

```bash
F1_ENV_FILE=/secure/path/to/gemini.env scripts/demo.sh live
```

The live mode requires Docker, Docker Compose, Harbor 0.26.0 and a valid `GEMINI_API_KEY` in the environment file. The recorded mode re-verifies historical evidence; it does **not** make a fresh model call, and needs only Bash and [uv](https://docs.astral.sh/uv/) (Python 3.12)—no Docker, Harbor or API key. On headless servers the report path is printed; use `F1_OPEN=0` to disable auto-opening. A failed live run is never silently replaced with recorded results.

See [complete setup and evidence paths](f1-championship/README.md).

## What happened when we tested Gemini?

We compared **Gemini 3.8 Flash**, operating through OpenCode in genuine Harbor runs, against a strong **public-information reference**. The reference evaluates choices using the published simulator rules; it is a useful benchmark, **not** a proof of optimality and not an equally resource-constrained language model.

| Player | Constructors' points | Normalised reward | Instruction |
|---|---:|---:|---|
| **Public-information reference** | **289** | **0.7817** | r1; reproduced under r2 |
| Gemini run 1 | 279 | 0.7421 | r1 |
| Gemini run 2 | 256 | 0.6508 | r1 |
| Gemini run 3 | 276 | 0.7302 | r1 |
| Gemini separate run | 279 | 0.7421 | **r2** |

The reference led each of the **three r1 Gemini runs** by **10, 33 and 13 points**—an **18.7-point mean gap**. The r2 run is reported separately, not pooled into that mean. An additional genuine live demo execution also scored 279 points (reward 0.7421).

Gemini completed the championship and performed competitively. The finding is narrower and more interesting: **a capable AI agent can finish successfully while overlooking consequential strategic options.** On a single seed and three r1 model trials, this is descriptive evidence, not a significance claim or a universal ranking of models. Replays of model-written scripts on additional seeds are **not** fresh model runs.

The full run inventory, seed handling, reference method and decision-level counterfactuals are in [the technical README](f1-championship/README.md) and [reference report](f1-championship/docs/REFERENCE_2_1_0_REPORT.md).

## Can the agent cheat?

A useful benchmark must be difficult to exploit, not just difficult to play.

```text
OpenCode + Gemini (agent container)
     │  f1ctl rules / observe / act
     ▼
Sealed simulator sidecar (hidden state, no network)
     │  hash-chained journal + manifest
     ▼
Isolated verifier
     │  check evidence + replay all decisions
     ▼
Verified season points and reward
```

The agent does not control the official journal or reward. The verifier independently replays every decision, reconstructs observations and checks the evidence.

| Integrity probe | Observed result |
|---|---|
| Do nothing | Reward **0** |
| Stop after boundary-attack attempts | Reward **0** (incomplete season) |
| Attempt attacks, then finish with a simple honest policy | **229 points, reward 0.5437**—the honest policy's own result |
| Six journal/manifest tampering cases | **6/6 rejected**, reward 0 |
| Reproduce the reference on a clean host | **289 points**, matching the original journal |

This is not a claim that every possible exploit has been ruled out. It is a reproducible set of tests for the specific evaluation boundary. See the [submission checklist](f1-championship/docs/SUBMISSION_CHECKLIST.md).

## Reproduce the verified benchmark

The submitted configuration is **2.1.0 · `SOLO_COORDINATION` · `CHIEF_ONLY` · fixed-rule rivals**. It contains **no Gemini Engineers, DeepSeek rival, practice/qualifying or weather expansion**.

From a checkout of `submission/2.1.0`, after installing [the prerequisites](f1-championship/README.md):

```bash
f1-championship/scripts/run_v21.sh oracle
f1-championship/scripts/run_v21.sh nop
f1-championship/scripts/run_v21.sh probe-stop
f1-championship/scripts/run_v21.sh probe-complete
# Fresh frontier run (API key required):
GEMINI_ENV_FILE=/secure/path/to/gemini.env f1-championship/scripts/run_v21.sh opencode
```

The legacy single-race files at the repository root are retained for regression and historical comparison. The verified eight-race submission, its builder, evidence and detailed documentation are under [`f1-championship/`](f1-championship/README.md).

## What comes next: 2.2

The next step is to make the world—and the organisation making decisions inside it—more complex. Picture fictional teams **McLearn Racing** and **Red Bool Racing**, with drivers, race engineers and rivals who may have different priorities.

| Experimental extension | New strategic question |
|---|---|
| **Practice & Qualifying (C5)** | What is worth learning with limited practice laps, and which setup should carry into the race? |
| **Rival tendencies (M2)** | Can an agent infer a rival's defensive behaviour from observations rather than hidden labels? |
| **Driver objectives (M6)** | Will a driver obey a team order that hurts their personal championship position? |
| **Weather & wet tyres (M7)** | Should a team pit for rain that may not arrive? |
| **Engineer advice / adaptive rivals** | Can multiple AI decision-makers improve teamwork—or make the wrong choice more confidently? |

These extensions have been developed and tested in **separate experimental branches**. They are **work in progress**, not features or results of the submitted 2.1.0 benchmark. Combining them and validating a new full-season Frontier–Reference comparison is a separate milestone. See the experimental `feature/v22-integrated-candidate` and `feature/c5-integration` branches for their respective validation records.

## Gemini API Challenge: when a racing team becomes a team of AI agents

A further experiment gave the Chief Strategist two AI Race Engineers:

- **Gemini 3.8 Flash:** Chief, responsible for the final team decision.
- **Two Gemini 3.5 Flash-Lite Engineers:** driver-specific advice, passed through a structured broker.

Across **40 evaluated states**, real Engineer advice changed the Chief's decision in **5**. The preregistered C8 diagnostic did **not** establish that Engineers improve average decision quality. In one illustrative state, the Chief switched from HARD to MEDIUM following advice; a counterfactual estimated **4.5–5.1 additional points of regret**. This is a specific case, not a demonstrated average causal effect.

**Research question:** *Does adding more AI agents produce better strategy, or does it introduce new ways for a team to disagree and make mistakes?*

These Gemini API diagnostics are **separate from the official Chief-only 2.1.0 Harbor results**. [Read the C8 experiment](f1-championship/docs/C8_ENGINEER_CONFLICT_RESULTS.md).

## References & further reading

Research background for interactive agent evaluation, consequential multi-step tasks and AI teamwork:

1. Liu et al. (2024). [*AgentBench: Evaluating LLMs as Agents*](https://arxiv.org/abs/2308.03688). ICLR 2024.
2. Yao et al. (2024). [*τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*](https://arxiv.org/abs/2406.12045).
3. Xu et al. (2025). [*TheAgentCompany: Benchmarking LLM Agents on Consequential Real World Tasks*](https://arxiv.org/abs/2412.14161). NeurIPS 2025.
4. Cemri et al. (2025). [*Why Do Multi-Agent LLM Systems Fail?*](https://arxiv.org/abs/2503.13657). NeurIPS 2025.
5. [FIA Formula One Regulations](https://www.fia.com/regulations) — motorsport rules background; the championship uses **synthetic** cars, races and performance parameters, with selected power-unit rules scaled from 2026 regulations.

*F1 Championship Strategist is a fictional, motorsport-inspired research benchmark, not affiliated with Formula 1, its teams or the FIA. McLearn Racing and Red Bool Racing are fictional names.*
