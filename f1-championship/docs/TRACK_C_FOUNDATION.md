# Track C: Independent Engineer Coordination Foundation

This module is an engine-independent evaluation boundary for two driver-local race
engineers and a team-level Chief Strategist. All numeric recommendation benefits
and confidence values in the deterministic mock provider are synthetic fixtures,
not calibrated predictions.

## Information and authority boundaries

- Engineer A receives only Driver A's public race state, public track data, legal
  actions, and public rival classification entries.
- Engineer B receives the equivalent Driver B view.
- Neither view contains the teammate state, hidden seed, scheduled future events,
  simulator internals, or privileged oracle information.
- Recommendations are advisory immutable data. They cannot call the race engine or
  alter Championship state.
- The Chief observes both recommendations, records acceptance or rejection, and is
  the only actor whose final `RACE_STRATEGY` action may reach an execution callback.

The initial deterministic conditions are:

1. `NO_ENGINEER`: no recommendations are supplied.
2. `ALIGNED`: both engineers recommend the same local action.
3. `CONFLICTING`: the two locally motivated actions differ.
4. `MISCALIBRATED_CONFIDENCE`: conflicting recommendations use a deliberately
   overconfident fixture label and confidence value.
5. `REPLAY`: both reports must come from exact observation-hash recordings; no
   mock report is generated when a recording is absent.

These conditions test coordination behavior; they do not establish that any
recommendation is globally optimal. Exact public observations can be associated
with recorded recommendations and replayed by content hash.

## Provider integration after B4

The provider protocol accepts an already-redacted engineer observation and returns
a validated recommendation. A later model-backed provider should additionally
record model/version, prompt template version, raw output, normalized output,
latency, and execution settings. Engineer A/B calls can run in parallel because
neither owns mutable simulator state. Recorded reports must be reusable without
another model call.

After Track B B4 is stable, integration should:

1. Build both engineer observations from the same public Chief observation at an
   eligible `RACE_STRATEGY` decision point.
2. Keep event schedules, future status changes, seeds, and sidecar-private state
   outside this boundary.
3. Add an engineer-briefing/coordination trace entry before the Chief's existing
   action trace, including report hashes and acceptance decisions.
4. Submit only the Chief's validated final action through the existing Championship
   contract and adapter. Reports must never be accepted as simulator actions.
5. Define experiment conditions in public evaluation configuration without making
   future race information available to any provider.

No changes to the public race engine, legacy verifier, or Harbor sidecar are made by
this foundation.

## Driver position swap and conditional give-back

The fixture and validation schema reserve a future `TEAM_ORDER` action with `HOLD`,
`SWAP`, `RACE`, or `DEFEND`, an explicitly favored driver, and an optional
`IF_NO_POSITION_GAIN` give-back deadline. This is contract design only; it does not
move cars or affect performance.

Safe engine integration will require:

- a real team-order decision point and engine-side legal-action validation;
- an atomic two-car reorder that preserves a complete, unique classification;
- feasibility rules based on public gaps, track position, and track status;
- explicit time/pace consequences rather than a hard-coded finishing result;
- persistent conditional give-back state, deadline evaluation, and cancellation;
- defined interactions with pit stops, SC/VSC neutralization, overtaking, and race
  completion;
- observation, journal, deterministic replay, and verifier coverage for every
  accepted or rejected order.

Until those capabilities exist, `TEAM_ORDER` actions must remain fixture-only and
must not be sent to the race engine.

The executable reduced mechanics, fair-reference counterfactuals, and research
claim boundaries are specified in `TRACK_C_RESEARCH_DESIGN.md`.
