# F1 Pit Wall — AfterQuery Hackathon: Codex Handoff

**Status:** Updated research and implementation handoff; **not yet an implemented or tested Harbor task**.  
**Date:** 2026-11-14  
**Time budget:** 48-hour hackathon.  
**Implementation language:** Prefer Python.  
**Primary user objective:** Ship a **judge-runnable Harbor task** that exposes *real* frontier-agent failures in F1 constructors' strategy, includes a demonstrably stronger reference, and writes a trustworthy scalar reward in [0, 1]. F1 is the domain, not the ultimate research contribution.  
**Priority of requirements:** Latest AfterQuery organizer announcement (mandatory Harbor layout, OpenCode, verifier path) > older proposal to expose an MCP service. If starter-kit guidance conflicts, validate with organizers before submission.

## 0. ORGANIZER UPDATE — REQUIRED STACK & SUBMISSION GATES (2026-11-14)

**Treat this section as the authoritative implementation contract.** The organizer explicitly says this is a research-heavy environment/evaluation challenge rather than a conventional app hackathon. The central deliverable is an agent task + scientific evidence of a meaningful performance gap; not an F1 dashboard.

### Non-negotiable required stack

- **Framework:** [Harbor](https://github.com/laude-institute/harbor) (currently redirects to [harbor-framework/harbor](https://github.com/harbor-framework/harbor)). Submission must be a **Harbor task**, not just a standalone Python simulator or MCP server.
- **Minimum task layout:** `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/` (notably `tests/test.sh`), and `solution/` (normally `solution/solve.sh`).
- **Harness for evaluation:** **OpenCode**, using e.g. `harbor run -p ./f1-pitwall -a opencode -m <provider/model>`. Use the actual model identifier/credentials supplied on-site, not a guessed model name.
- **Reward interface:** The verifier MUST write **one numeric scalar from 0 to 1** to **`/logs/verifier/reward.txt`**, always including valid failure paths. Partial credit is allowed. The agent must not be trusted to self-report the reward.
- **Mandatory evidence:** At least **one real Harbor agent run log including its score**. Demonstrate actual run logs/trace; do not replace them with a handcrafted transcript. Playthrough snippets in the demo are encouraged.
- **README:** Briefly answer **what the agent must do, why it is hard, how it is scored**, with the exact one-command run procedure and requirements.
- **Submission:** Finish and submit by the organizer deadline; exact deadline is **not present in this handoff**, so verify rather than inventing it.

**Important correction of earlier planning:** The latest organizer announcement explicitly specifies a **Harbor task** and **OpenCode harness** but does **not** state that every task must expose an MCP server. Earlier hackathon materials mention MCP connectivity. **Do not block implementation on an MCP server.** First achieve a working Harbor task via CLI/file-based agent interaction; add MCP only if official starter kit or mentors confirm it is required/beneficial.

### Required Harbor folder tree (target)

```text
f1-pitwall/
├── instruction.md               # Sole agent-facing task prompt; goals, legal actions, outputs
├── task.toml                   # Harbor metadata and agent/verifier resource/time limits
├── environment/
│   ├── Dockerfile              # Reproducible runtime image; pin dependencies
│   ├── ...                     # Public simulator CLI, practice data, public rules
│   └── ...                     # Frozen, redistributable calibration artifacts as permitted
├── tests/
│   ├── test.sh                 # Verifier entrypoint; ALWAYS writes /logs/verifier/reward.txt
│   ├── grade.py                # Trusted scoring implementation, replay/held-out episodes
│   └── ...                     # Verifier-only fixtures; not copied into agent image
├── solution/
│   └── solve.sh                # Executable reference/oracle solution used by Harbor
└── README.md                   # Human/judge docs and reproducible commands
```

**Scaffolding:** Prefer `harbor tasks init f1-pitwall` and inspect the generated `task.toml` for the *installed Harbor version* rather than copying potentially stale TOML config keys from third-party posts. The task must build and run offline at evaluation time; no runtime dependence on FastF1/OpenF1 API calls.

**Official references:** [Harbor repository](https://github.com/harbor-framework/harbor), [task structure and commands](https://github.com/harbor-framework/docs/blob/main/cli/tasks.mdx), [run CLI](https://github.com/harbor-framework/docs/blob/main/cli/run.mdx), [task creation guide](https://github.com/harbor-framework/docs/blob/main/guides/creating-tasks.mdx).

### What the organizer will actually rerun

1. A **reference** using the provided solution/policy (or `-a oracle` if compatible with their process).
2. **Three OpenCode/frontier-agent runs** against the same documented task family.
3. **Do-nothing** and **stop-early** baselines.
4. **15 minutes of reward-exploit probing**; any high-scoring shortcut that avoids real championship success is a severe issue.

**Acceptance gate:** `harbor run` has to complete from a clean checkout/container, save output artifacts and a valid `reward.txt`, and produce a repeatable score. A standalone `python simulator.py` demonstration is **not** a valid submission by itself.

## 1. Challenge and judging contract

AfterQuery asks teams to build an interactive environment with explicit observations, actions, goal, and verifiable rewards; run a frontier agent via the required **Harbor task + OpenCode** harness; demonstrate a stronger reproducible reference run; analyze actual failure modes and reward exploits.

Scoring:
- **Gap (30):** Reference scores consistently above frontier agent across repeated evaluation, with both reproducible.
- **Meaningful difficulty (30):** Failures arise from strategic decisions, not hidden necessary information, confusing tools, impossible timing or unfair setup.
- **Reward integrity (25):** Reward measures task completion; doing nothing/early stopping earns little or zero; exploitable shortcuts do not outperform genuine success.
- **Craft (15):** Working, realistic, reproducible environment with a one-command README evaluation.

Judges run: reference, 3 frontier-agent runs, do-nothing baseline, stop-early baseline; then investigate exploits for ~15 minutes. Ten-minute demo. A small model improving from experience is an optional tiebreaker.

**Critical:** Do not claim any gap until it has been experimentally shown. Avoid scripting unfair adversarial scenarios specifically to fool the agent. Same observation and action constraints for frontier and planning reference; no future information leakage.

## 2. Proposed concept and scope

**Working name:** F1 Pit Wall — Constructors' Championship Strategy Environment.

The agent operates an F1-like team with **two drivers** across a short **championship**. Goal: optimize the *team's* championship performance, rather than maximize one driver's race finishing position. The world features tyre degradation, pit timing, competitor reactions, weather changes/uncertainty, Safety Car (SC)/Virtual Safety Car (VSC), and strategic driver prioritization.

**Strong motivation:** A driver's individual success and the constructors' outcome can conflict. Race-level gains and season-level gains can conflict. SC, forecasts and opponent pit stops force adaptive contingent planning.

**Provisional MVP, adjustable after technical validation:**
- 4 teams, 2 drivers/team (8 drivers)
- 6 short races, ~20–30 laps/race
- ~4–6 meaningful strategy decision points per race; simulation advances internally between them
- Actions: pit/stay for each driver, compound selection, pace option, team order (only if justified by proximity/conditions)
- Events: SC/VSC, evolving weather + potentially misleading *forecasts*, rival pit strategy changes
- Championship: official-style constructors' points from both drivers, adapted consistently for 8-car field (document scoring rules explicitly)
- Optional later: component life, upgrade budgets, DNF hazard. **Do not block MVP on these.**

**Core failure hypotheses to test (not asserted results):**
1. **Multi-entity optimization / dynamic driver prioritization**: optimize both drivers' joint points instead of favoring a single star driver.
2. **Belief updating and contingent replanning**: respond rationally to forecast changes and SC opportunities.
3. **Long-horizon planning**: avoid locally attractive tyre/pit decisions that harm eventual race/championship standings.
4. **Opponent modeling**: react to rival undercut/overcut or pit behavior.

**Important subtlety:** Simply swapping P3 and P5 *between teammates* does not change constructors' points if nothing else changes. A team order matters only through downstream pace, overtaking, risk, traffic, and points taken from rivals. Avoid an artificial reward for issuing team orders.

**Implementation strategy:** Build a **minimal Harbor task first** (one short race, verified reward and oracle), then add two-driver interactions, rain/SC and short championship. Event-driven decision points are preferred over one expensive model call per lap. Simulator implementation is subordinate to Harbor compatibility.

## 3. Primary data sources (researched via Exa; not yet downloaded/tested here)

### FastF1 — first choice for race mechanics calibration
- GitHub: https://github.com/theOehrly/Fast-F1
- Docs: https://docs.fastf1.dev/
- Session API: https://docs.fastf1.dev/api_reference/session.html
- MIT-licensed Python *code*. **That is not automatically a license for the underlying F1 data.**
- Access: lap timing, sectors, tyre compound and tyre age, stint, pit in/out, positions, track status (including SC/VSC), race control messages, weather observations, results, telemetry. Fine-grained timing is broadly available from 2018 onward; earlier coverage differs.
- Useful columns in `session.laps`: `Driver`, `LapNumber`, `LapTime`, `Compound`, `TyreLife`, `Stint`, `PitInTime`, `PitOutTime`, `TrackStatus`, `Position`, `Team`, `IsAccurate`.
- Session members: `laps`, `weather_data`, `track_status`, `race_control_messages`, `results`, `total_laps`.

### OpenF1 — granular event/weather/opponent information
- Site: https://openf1.org/
- GitHub: https://github.com/br-g/openf1
- API: https://api.openf1.org/v1/
- Historical availability advertised from **2023 onward**; JSON/CSV. Endpoints include `laps`, `intervals`, `pit`, `stints`, `weather`, `race_control`, `position`, `car_data`, `drivers`, sessions/meetings, standings (see docs for exact endpoint availability).
- At review, website said free historical access without keys and rate limits **3 requests/sec and 30/min**; check current terms before heavy collection. Stated educational/personal/research/noncommercial emphasis; F1 trademark/data rights remain separate.
- Useful for reconstructing per-lap race gaps and event chronology. Avoid dependency on network at judging time.

### Jolpica-F1 — constructors' standings and historical season metadata
- GitHub: https://github.com/jolpica/jolpica-f1
- Example API base: https://api.jolpi.ca/ergast/f1/
- Apache-2.0 repository code; API has its own terms.
- Endpoints: seasons, races, drivers, constructors, race results, laps, pit stops, driver/constructor standings. Best for championship schema and benchmarking cross-race results, not detailed weather/tyre transitions.

### F1DB — downloadable local historical database
- GitHub: https://github.com/f1db/f1db
- CSV, JSON, SQLite, SQL releases; race/driver/constructor results, pit stops, standings. Data project licensed CC BY 4.0 (respect attribution).

### Consolidated dataset
- https://github.com/Arths17/f1-dataset
- Scripts joining Jolpica and FastF1, 2026-extended dataset. README claims code MIT / exported data CC0; validate provenance and original providers' terms independently.

## 4. Existing race strategy simulation code (review BEFORE choosing build-vs-reuse)

### A. TUMFTM/race-simulation — top candidate for environment/RL reference
- https://github.com/TUMFTM/race-simulation
- Python; LGPL-3.0; older Python 3.8 environment/dependencies.
- Includes lap-wise multicars simulator, tyre/fuel dynamics, stochastic influences/Monte Carlo, `racesim` and `racesim_basic`, and **DQN-based Virtual Strategy Engineer** training (`machine_learning_rl_training`).
- Pros: Actual simulator and RL reference with documented run instructions.
- Risks: Old dependencies, setup complexity, adaptation to two-driver championship/SC/weather needed. TEST import, sample run, runtime, license compatibility.

### B. rafaserrano0/race-strategy-lab — top candidate for calibrated probabilistic mechanics
- https://github.com/rafaserrano0/race-strategy-lab
- Python; MIT; created 2026; README describes 2022–2025 FastF1+Jolpica, 109,341 recorded laps total, race-only estimators, Monte Carlo simulator.
- Models: tyre degradation, fuel effect, pit loss, overtaking, SC/VSC probability, dirty air, lap noise, DNF.
- README reports holdout 2024 calibration and honest limitations.
- **Explicit gaps:** wet/dry transitions NOT modeled; red flags out of scope; no double-stack pit congestion. Simulation is not by itself a two-driver team season environment.
- Pros: potential simulator calibration and reference-rollout models; MIT.
- Risks: very new and small repo; inspect actual code and run tests, don't trust README alone.

### C. rohanovro/F1-Race-Strategy-System — SC strategy reference
- https://github.com/rohanovro/F1-Race-Strategy-System
- Python; README claims pit window/undercut strategies, tyre model, SC/VSC detection, Monte Carlo SC timing.
- **License not verified.** Treat as reading/reference only until verified.

### D. Kirthivaasan15/STRATOS — modular state/strategy/UI reference
- https://github.com/Kirthivaasan15/STRATOS
- Python; MIT; OpenF1 ingestion, state manager, tyre/pit/traffic models, SC model, Monte Carlo recommendation, Plotly dashboard.
- Verify real functionality and tests before reuse.

### E. vforvitorio/f1-stratlab — visual demo / multi-agent inspiration
- https://github.com/vforvitorio/f1-stratlab
- README describes 2D race replay with multiple specialist agents, strategy explanations, FastF1/OpenF1 data. Likely a large dependency surface and less suitable as core MVP.

**Recommendation:** First smoke-test TUMFTM and race-strategy-lab. Choose the cleanest small reusable kernel; otherwise implement a compact custom simulator using their documented equations and independently calibrated data (do not copy unlicensed code).

## 5. Example data extraction (not executed/validated yet)

```python
import fastf1
from pathlib import Path

Path("cache").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)
fastf1.Cache.enable_cache("cache")

session = fastf1.get_session(2024, "British Grand Prix", "R")
session.load(telemetry=False)

session.laps.to_csv("data/laps.csv", index=False)
session.weather_data.to_csv("data/weather.csv", index=False)
session.track_status.to_csv("data/track_status.csv", index=False)
session.race_control_messages.to_csv("data/race_control.csv", index=False)
session.results.to_csv("data/results.csv", index=False)
```

Suggested initial cases: 2024 British GP (changeable conditions), Canadian GP (mixed weather), São Paulo GP (heavy rain/red flag), Monaco GP (red flag). **Use these as calibration/event-pattern sources, not as a replay with hidden future knowledge.** For the minimal simulator, choose representative race/circuit parameters and randomized event seeds.

## 6. Important gaps and modelling cautions

1. **Historical observed weather is not historical forecast.** APIs show observed rainfall, track temperature, etc., but do not inherently provide the probabilistic predictions the pit wall received. Build a *causal, noisy forecast generator* conditioned on latent weather; ensure the forecast at time t only reveals data available at t. Compare against a reference that uses the SAME forecasts.
2. **Counterfactual outcomes are unobserved.** A historical race doesn't tell us the result of a pit stop that wasn't made. Agent-driven pit calls require a simulator with stochastic counterfactual transition rules.
3. **SC/VSC are not identical.** Model SC gap compression vs VSC slower pace with less compression; pit-loss reductions should be appropriately parametrized, not hard-coded universally.
4. **Two-car pit congestion:** If double-stacking, include shared pit crew/queue penalty only if it is explicitly modelled and exposed to agent.
5. **Pit strategy realism:** Track position, overtaking likelihood, tyre choice, compound rules, wet conditions and SC all interact. Simplify rules clearly and preserve consistency; explicit F1-like rules are acceptable.
6. **Drivers' relative contributions:** Team orders only affect future outcome if the simulator models consequential differences (pace/tyre/rival interactions). Prevent scoring team-order gestures without actual constructors gains.
7. **Randomness:** Fix seeds, localize data and calibrations, use common random numbers for reference-vs-agent comparison wherever practical. With different actions, event RNG should remain as comparable as possible.
8. **Reward gaming:** No positive reward for pit stops, lap-by-lap position spikes, unnecessary pacing, arbitrary planning calls, or voluntary terminal actions. No rewards for avoiding race progression.
9. **Data rights:** Distinguish source-code licenses from providers' underlying F1 data and trademark terms; cite sources and keep demo educational/appropriately attributed.
10. **Simulation validity:** Evaluate on held-out races/seeds, not only conditions used for calibration; sanity-test tyres, pit timing, SC, rain, overtaking, DNF, two-driver point totals.

## 7. Proposed Harbor-native F1 task contract (not a generic app)

### 7.1 Resolve the crucial agent-interaction choice early

The submitted environment must let the agent **make strategically meaningful F1 decisions** while the verifier independently scores actual race performance. Two valid designs exist, but select **one primary contract** after checking starter kit/mentor expectations:

**Option A — Sequential agent play via a container CLI (best match for 'agent plays F1'):**
- Agent receives `instruction.md`, executes `f1ctl observe`, `f1ctl rules`, and `f1ctl act '<json>'` from OpenCode's terminal tools.
- Each `act` commits a decision for **both drivers**, simulates forward to the next important decision point, and returns the new **causally available** observation.
- Environment keeps an action journal/transcript; the agent may not choose/reset hidden evaluation seeds, roll back turns, or query future events. No real-time wall-clock traps.
- On exit, verifier **independently reconstructs/replays** the submitted action sequence using trusted simulator code/fixtures. Do **not** score the agent's own JSON summary or easily rewritten in-container scoreboard.
- **Security note:** A writable action log can itself be edited retrospectively if future state becomes visible. To reduce hindsight exploits, restrict resets/preview tools, include action-step binding/integrity checks, and require verifier-authenticated transition checks. A private replay alone is not enough if the complete future can be learned by iterating the same seed. Consider Option B if this is hard to secure.

**Option B — Contingent strategy / policy submission (stronger integrity):**
- Agent writes `/workspace/submission/strategy.py` (or a minimal JSON policy DSL) implementing `choose_action(observation)` with clear input/output schema.
- Public CLI lets the agent test on **practice episodes** with no secret grading futures. Agent can use tools to inspect and experiment.
- After the agent finishes, `tests/grade.py` imports/executes the submitted policy in a controlled process and **interacts with the simulator sequentially** on fixed **hidden, held-out seeds**. Agent receives only current observations during those runs.
- This prevents editing logs after seeing the whole evaluation future and permits many clean seeded comparisons. However, OpenCode is partially **writing a policy** rather than making each live strategy call; discuss acceptability with organizers. Keep a demo playthrough to show real sequential decisions.

**Recommendation:** Choose A if the organizers expect terminal-based interactive play; choose B if exploit-resistance and unseen-scenario generalization are decisive. **Avoid an ambiguous hybrid where a transcript is graded on future knowledge or grading imports agent-modified simulator modules.** If a lightweight custom bridge is necessary, it must operate entirely inside the Harbor task and cannot replace the required structure.

### 7.2 Public information, private evaluator, and fair reference

Public, agent-visible (`instruction.md` and public code/data):
- Mechanics: compound performance, degradation, pit rules, SC/VSC differences, double-stack delays, team orders, season point scoring, allowed actions, invalid-action behavior.
- Current observations: race/lap, both drivers' tyres and ages, field positions/gaps, current weather/track, **uncertain forecast** and rival actions already observed, championship standings, future calendar/tracks if used.
- Legal action schema and sample usage; no trick instructions or impossibly tight response windows.

Never reveal before action: exact latent future rain/SC schedule, unobservable opponent decisions, evaluation-only random seeds (for held-out tests), or verifier answers. Same effective game information and action options for reference and frontier agent.

**Trust boundary:** Docker `environment/` is agent-exposed. Treat agent workspace files, telemetry reports and result claims as untrusted. `tests/` and authoritative grading logic should arrive **only for verification**, and scoring should reload original trusted simulator implementation and verify traces/policies. Verify the actual Harbor container-mount/security model and test an adversarial agent that edits local files. Use isolated verifier execution where supported if needed.

### 7.3 Minimal strategic observation/action specification

Observation example (draft schema; adapt to chosen interaction protocol):

```json
{
  "race_index": 2, "race_count": 6, "lap": 18, "laps_total": 30,
  "team_points_so_far": 32, "rival_points_so_far": 37,
  "weather_observed": "dry", "rain_probability_next_5_laps": 0.6,
  "track_status": "SC", "drivers": [
    {"id":"A","position":3,"compound":"MEDIUM","tyre_age":12,"gap_to_next":2.1},
    {"id":"B","position":5,"compound":"HARD","tyre_age":8,"gap_to_next":1.7}
  ],
  "legal_actions": {"A":["STAY","PIT_SOFT","PIT_MEDIUM","PIT_HARD","PIT_INTER"],
                    "B":["STAY","PIT_SOFT","PIT_MEDIUM","PIT_HARD","PIT_INTER"]}
}
```

Action example:

```json
{"A":{"pit":true,"compound":"INTER"},"B":{"pit":false},"team_order":"NONE"}
```

- Ensure legal actions are mechanically well-defined. In particular, make rain/tyre viability continuous enough for reasoning rather than an arbitrary hidden threshold.
- Define team orders only when cars are close enough and overtaking can affect **total** points; don't award intrinsic bonus for orders.
- A scenario may require only a handful of event-triggered decisions, keeping frontier-agent tokens/calls bounded and judges' 10-minute demo clear.

### 7.4 Reward verifier design — robust scalar 0..1

The verifier, **not the agent**, computes a numerical score and writes:

```text
/logs/verifier/reward.txt
```

Use a **task-aligned terminal metric** derived from both drivers' total constructors' points (and optionally relative to strongest rival). Avoid rewards for arbitrary pit commands, tool calls, position spikes, or early termination. Document the normalization exactly. One possible *design to validate* is:

```text
if invalid_or_incomplete:
    reward = 0.0
else:
    reward = clip((team_points - low_anchor) / (high_anchor - low_anchor), 0.0, 1.0)
```

`low_anchor` and `high_anchor` must be **fixed, publicly documented, defensible reference scales** (e.g. validated poor/high-quality season policies evaluated on the same task distribution), not dynamically chosen from a player's own run. Report **raw constructors' points, championship rank, margin vs rival, validity, and score** in a trusted grader side log. A score of 1 should correspond to genuinely excellent task performance and cannot be achieved by ending early or editing the report. If anchors lead to score saturation, revise them before the competition rather than hiding the issue. Check that oracle/high-performing reference scores as expected; don't make the metric circular by defining success only as agreeing with the oracle's actions.

**Required behaviors:**
- Always write a single finite numeric value in `[0.0, 1.0]` even on invalid output, timeouts, missing files or exceptions (except genuine infrastructure failure). Verify safe error handling.
- `stop_early`, missing actions / policy, and unfinished championship -> **0 or nearly 0** (explicit rule; don't permit artificial advantage from incomplete episodes).
- `do_nothing` policy -> demonstrably low reward; note that a single legal STAY call must not be punished automatically if sometimes optimal.
- No repeated claimable points, negative-time laps, infinite restarts, state tampering, score-file editing, action-log revision, future observations, invalid tyre changes, or pit spam exploits.
- Any stochastic effects must be controlled with seeds/paired scenarios; report both mean reward and uncertainty across repeated runs; don't use one lucky outcome as a gap.

**Minimal safe `tests/test.sh` *illustration*, not a tested file:**

```bash
#!/usr/bin/env bash
set -eu
mkdir -p /logs/verifier
printf '0\n' > /logs/verifier/reward.txt  # Safe default even if grader crashes
python3 /tests/grade.py || printf '0\n' > /logs/verifier/reward.txt
# Reject NaN, infinity, malformed and out-of-range scores.
python3 - <<'PY_CHECK'
from pathlib import Path
import math
p = Path('/logs/verifier/reward.txt')
try:
    score = float(p.read_text().strip())
    assert math.isfinite(score) and 0 <= score <= 1
except (ValueError, AssertionError, OSError):
    score = 0.0
p.write_text(f'{score:.8f}\n')
PY_CHECK
```

**Implementation instruction:** `grade.py` should independently calculate the reward, catch bad submissions in a well-defined error path, and write the exact file. Do not trust any user-authored `reward.txt` or scoring metadata. Tests live in `tests/`, and the Dockerfile must not `COPY tests/` or `solution/` into the agent's image.

### 7.5 Reference/oracle vs planning-reference distinction

- **Harbor oracle/reference artifact:** `solution/solve.sh` must genuinely solve the task (or install/generate a working strategy/policy) and be executable. Check `harbor run -p ./f1-pitwall -a oracle`, then inspect its real reward/log. Harbor's oracle is not, by itself, evidence that the *frontier agent* has a measured gap.
- **Strategy baseline/reference policy:** credible MPC/Monte Carlo planner or validated domain-rule policy using **the same observation/action constraints**. Measure its score against the frontier model across identical scenario distributions; avoid privileged latent weather or future SC event access.
- **Baselines:** `-a nop` can test the native no-op harness behavior when supported; separately implement a legal strategy that always stays out and an explicit early-quit case so the reward exploitation tests match the event structure.

## 8. How to run and validate (commands to put in README)

These are **template commands to execute after building the task**, not evidence of completed runs. Confirm available flags with `harbor run --help` against the pinned version.

```bash
# 1) Scaffold the Harbor task directory (only if not created)
harbor tasks init f1-pitwall

# 2) Validate the task structure and prompt
harbor tasks check ./f1-pitwall

# 3) Check the bundled reference solution and grader
harbor run -p ./f1-pitwall -a oracle

# 4) REQUIRED: run a real frontier model using OpenCode
harbor run -p ./f1-pitwall -a opencode -m <provider/model>

# 5) Do-nothing harness smoke test; inspect the produced score
harbor run -p ./f1-pitwall -a nop
```

Actual model execution requires the team's on-site provider credentials. Never commit API keys, secrets or real output artifacts containing credentials. **A command in README is not a substitute for the organizer-required saved agent run log.** Include the obtained trial/job logs with scalar reward and a trace excerpt sufficient to analyze what failed.

**README should show:** precise command and expected location/type of Harbor job logs; source/data attribution; version requirements; task objective; agent action schema; verifier rules; why the challenge is meaningful; runtime and deterministic seed selection; known limitations; one empirically observed failure mode; reproduction commands for oracle + three frontier trials + two baselines. Adjust commands after running the installed version, not based solely on docs.

## 9. Codex work order — updated with hard compliance gates

**P0 — Before any more simulator features: working Harbor vertical slice**

1. **Audit official Harbor and starter kit:** install/pin compatible Harbor + Docker, run CLI help, inspect `harbor tasks init` output, identify exact harness/verifier expectations and whether MCP is optional. Create a minimal task with an agent-visible prompt, Docker environment, executable solution and a scalar verifier; verify locally using `harbor run -a oracle`.
2. **Select evaluation contract:** Choose `f1ctl` sequential gameplay (A) or policy submission (B) and commit the protocol in `instruction.md`. Prove that one agent decision changes a race outcome and that verifier scoring is based on trusted replay/held-out simulation rather than writable local state.
3. **Smoke-test existing simulators:** clone/read TUMFTM and race-strategy-lab, check real code/licenses/dependencies; record in `REPO_AUDIT.md`. Favor a small clean kernel over porting a large UI/multi-agent app.
4. **Get minimal frozen data:** download one dry and one SC/rain-affected race using FastF1, inspect availability and right-to-redistribute, freeze processed public fixtures and version/hash them. No network in judgment path.

**P1 — Meaningful F1 task, not a fake puzzle**

5. Implement one race with **two cars per team**, tyre wear, PIT/STAY, rival rule policies and coupled finishing points. Test invariants/edge cases before expanding.
6. Add SC/VSC and rain/forecast changes with causal observations; model SC gap compression, reduced pit loss, tyre suitability and a plausible double-stack cost; write unit tests proving actions affect standings.
7. Add **short championship** (prefer 3 races first; expand to 4–6 only if repeated Harbor agent runs are cheap enough). Keep 3–5 strategic decision points per race, not token-expensive per-lap chat.
8. Implement transparent scoring and hidden/trusted evaluation. Unit-test genuine high-skill vs poor policy, missing/partial actions, repeated commands, mutations, resets, hindsight and early termination.

**P2 — Demonstrate measured agent failure and submit**

9. Build a reference planner using no privileged observations; `solution/solve.sh` should actually run that reference. Execute Harbor oracle and OpenCode, save at least **one real scored agent log immediately**, then rerun three frontier trials with fixed seeds/config and compare to baselines.
10. Inspect actual failure traces, select **one primary failure mode** (e.g. conflicting two-driver SC pit calls; weather belief updating), run ablations if time permits; if no repeatable gap, simplify/refine mechanics rather than inventing scores.
11. Run adversarial exploit checklist and ensure `/logs/verifier/reward.txt` remains valid. Finalize concise README and a 10-minute demo focused on observed mistakes, reward trust and reproducing results. Submit on time.

## 10. Required submission deliverables and acceptance checks

| Deliverable | Required proof / pass condition |
|---|---|
| Harbor task files | `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/test.sh`, `solution/solve.sh`, `README.md` all exist; scripts executable |
| Build and runtime | Clean container builds and agent sees required data/rules and CLI tools |
| Verifier | Writes **exactly one score in [0,1]** at `/logs/verifier/reward.txt`; no score for missing/incomplete solutions |
| Reference | Actual `harbor run -p ./f1-pitwall -a oracle` log + reference score; same information constraints as frontier |
| Frontier run | **At least one real `harbor run ... -a opencode -m ...` log with score** bundled; aim for three for judges' rerun |
| Baselines | Legal do-nothing policy and stop-early yield little/zero; scores logged |
| Research finding | One concrete, reproducible decision-related failure illustrated by an observation-action-outcome trace |
| Reward integrity | Tests for invalid commands, editing score, excessive pit actions, hidden futures, resets, random seed manipulation, incomplete sessions |
| Reproducibility | Fixed seeds + pinned packages + offline fixtures + one-command README; outputs documented |
| Rights / acknowledgements | Attribution and data-use note for FastF1, OpenF1, Jolpica, F1DB and reused code |

## 11. Unverified details / things NOT to claim yet

- No project repo has yet been cloned/installed/run for the source survey in the previous handoff.
- No F1 simulation or Harbor task has yet been implemented, built or evaluated in this handoff.
- No OpenCode model playthrough, Harbor reward log, or reference-vs-frontier performance gap has been produced yet.
- The correct interaction mode (live terminal action journal vs submitted contingent policy) needs starter-kit/mentor validation.
- Provider/model string, API credentials, exact deadline and local Harbor CLI config must come from the organizers/installed software.
- Historical observed weather is NOT a true historical forecast. Wet/dry transition models, two-driver team orders and double stacking remain extensions requiring implementation/testing.
- Code licenses and source-data permissions require separate review; do not redistribute live data simply because an API is accessible.

## 12. Direct instruction for Codex (copyable)

> Treat this document as a research handoff, not proof of implemented code. **Deliver a valid, reproducible Harbor task first**, with mandatory layout, Docker environment, `tests/test.sh` + trusted grader writing a numeric `[0,1]` score to `/logs/verifier/reward.txt`, and executable `solution/solve.sh`. Use OpenCode for a real scored run; keep its log. Prioritize a small F1 two-driver strategy decision problem with SC/rain that supports a demonstrably stronger honest reference and genuine reward-exploit tests. Do not assume MCP is mandatory; validate against organizers' starter kit. Investigate existing F1 source repos before reuse; preserve data and license provenance. Never report an experimental gap until measured. When resource/time constrained, simplify the F1 season instead of omitting Harbor compliance, verifiable reward, or actual agent run.
