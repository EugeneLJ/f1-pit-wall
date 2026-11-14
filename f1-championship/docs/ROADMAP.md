# F1 Championship benchmark — target requirements and roadmap

This is the agreed final scope. Each phase implements part of it. Anything not
yet implemented is listed in the gap table at the end, which is updated at
the close of every phase.

The benchmark measures **decision failures that happen even though the agent
has enough public information and legal options**. Evaluation integrity
(sealed simulator, trusted replay) is a separate concern that we, as the
benchmark authors, must defend. It is not one of the capabilities being measured.

## Default benchmark

- 8-race constructors' championship, 4 teams × 2 drivers, agent = Apex GP.
- The P0 Harbor boundary stays in place: the simulator sidecar holds the seed,
  state and journal; the agent container gets only the `f1ctl` client; a
  separate verifier replays the journal from the hidden seed.
- The legacy single-race task at the repository root stays frozen as a regression.

## Track A — Long-horizon strategy

- 8-race championship with persistent state
- Persistent component wear, replacement, and allocation of the shared spare pool
- Grid penalties and track-dependent opportunity costs
- Constructors' championship optimization (both cars count)
- Season-level driver prioritization

## Track B — Adaptive race strategy

- 13–18 meaningful decision points per race
- Tyre compound selection and degradation
- Safety Car / VSC responses
- Weather forecasts and changing conditions (causal, noisy forecasts)
- Rival pit strategies, undercut/overcut
- Shared pit crew and double-stacking constraints

## Track C — Multi-agent coordination

- Driver-specific Engineer A/B (smaller models) and a Chief Strategist (frontier model)
- Driver feedback grounded in the simulator (engineers report what the sim knows about their car)
- Conflicting recommendations and confidence calibration; claims must be checkable
- Team orders and driver prioritization
- Ablations: no engineer / aligned / conflicting / miscalibrated confidence

## Optional (add only if it strengthens long-horizon dependency or opportunity cost)

Practice, qualifying sessions, upgrades, budget management.

## Cross-cutting rules

- Same observation and action constraints for the agent and the fair reference planner;
  the full-hindsight oracle is a diagnostic upper bound only.
- No failure caused by missing information. Rules, state needed for decisions,
  and probability models are public. Exact future events and rivals' private state are not.
- All coefficients are synthetic placeholders, kept separate from code
  (`src/f1pitwall/fixtures/track_a_coefficients.json`) for later calibration.
- The report keeps these separate: raw points, fair-reference regret, hindsight gap,
  completion/integrity. The reward denominator is not final yet.
- Final scores come from a representative scenario generator, never from pairs selected to fail.
  Counterfactual and control pairs are diagnostics.

## Extension points kept open for Track B/C

- `decision_type` is an open phase machine. New phases (e.g. `ENGINEER_BRIEFING`,
  `TEAM_ORDER`) add schema entries without changing the journal format.
- The number of decision points per race comes from race configuration, not constants.
- Race events are a per-decision status channel. Weather and forecasts become
  additional observation fields driven by the same seeded, action-independent streams.
- Journal entries record `decision_type` + `action` + observation hashes generically.
  Engineer messages can be journaled as observation content.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| P0 | Sealed sidecar boundary, verifier replay | Done (`docs/P0_REPORT.md`) |
| P1-A | Track A mechanics + per-mechanic tests | Done (`docs/P1_REPORT.md`) |
| P1-B | Exact 3-race solver, fair reference, hindsight oracle | Done (`docs/P1_REPORT.md`) |
| P1-C | Counterfactual + control pairs, representative scenarios, policy gaps | Done (`docs/P1_REPORT.md`) |
| P1-D | 8-race fair reference (budgeted receding-horizon planner), horizon ablation 1/2/3/5/8, season-level pairs | Done (`docs/P1D_REPORT.md`); compound choice and frontier probe not started |
| Track B | Adaptive race strategy | B1 (compound choice, tyre model), B2 (track pit loss, shared crew, out-lap warm-up) B3 (14 decisions per race, about 6 meaningful) and B4 (SC/VSC durations, compression, adaptive replanning) done on `feature/track-b` (`docs/B1_REPORT.md`–`docs/B4_REPORT.md`); B5–B6 pending |
| Track C | Engineers / coordination | Not started |

## Gap table (current implementation vs final requirements)

Current table (end of P1-C): see the "Gap table" section of `docs/P1_REPORT.md`.
