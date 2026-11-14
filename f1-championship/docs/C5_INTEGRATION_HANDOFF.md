# C5 integration handoff for Track B

## Source and timing

- Source branch: `feature/practice-qualifying-evaluation`
- Base commit: `d4b1ac3`
- C5 implementation commit: `59de259`
- Integration must wait until B7 is frozen and B8 penalty changes are stable.

C5 is a standalone synthetic Practice/Qualifying environment. It is not connected
to the authoritative Championship engine, does not alter Harbor, and does not
produce an authoritative Championship reward.

## Required integration sequence

1. Add Practice and Qualifying as versioned decision phases in the integrated
   Championship session.
2. Apply the provisional Qualifying grid before existing grid penalties. Validate
   that the final grid remains a complete, unique eight-car permutation.
3. Map driver-specific race-pace and tyre-degradation modifiers only to engine
   parameters with an explicit, reviewed meaning. Unsupported fields must remain
   unapplied and visible as such.
4. Define and publish how Practice resource costs change actual race or persistent
   Championship outcomes.
5. Preserve parc fermé locking. Add pit-lane starts only behind an independently
   tested rule and grid transformation.
6. Extend the trusted journal and replay over Practice and Qualifying observations,
   actions, grids, modifier hashes and application status.
7. Keep the reward based on actual Constructors' Points. The C5 synthetic
   expected-points proxy is analysis-only and must never enter scoring.
8. Run an eight-race Practice → Qualifying → Race season and verify deterministic
   replay from the protected seed.
9. Re-run the unchanged benchmark 2.0.1 configuration and demonstrate identical
   observations, journal and results.
10. Recompute information value, action reversals and regret using actual
    Championship continuations with the same public information available to the
    decision maker.

## Interface to consume

The contract is defined by:

- `track_c/pre_race_planning.py`
- `track_c/pre_race_evaluation.py`
- `track_c/schemas/pre_race_contract.schema.json`
- `docs/C5_PRE_RACE_PLANNING.md`

The Qualifying result contains `provisional_grid` and a
`race_setup_modifier`. The standalone modifier deliberately contains:

```json
{"integration_status": "NOT_APPLIED_TO_AUTHORITATIVE_ENGINE"}
```

Track B must change that status only after validating and applying the corresponding
field. It must not silently discard or approximate an unsupported field.

## Minimum integration tests

- hidden truth, protected seed and unperformed test signals never enter an agent
  observation;
- identical seed and action sequence reproduce all three phases and the journal;
- Qualifying grid is applied before penalties and both transformations are audited;
- setup selection changes supported engine state and can change actual outcomes;
- unsupported modifiers cannot affect results or be reported as applied;
- parc fermé rejects an illegal post-Qualifying setup change atomically;
- eight races complete with persistent state intact;
- trusted replay rejects modified observations, actions, grid or modifier hashes;
- actual Constructors' Points remain the sole reward basis; and
- the original 2.0.1 test suite and fixed trajectories remain unchanged.

## Safety stop

If a modifier cannot be mapped without inventing an unvalidated mechanic, or if
the 2.0.1 compatibility condition fails, keep C5 standalone. Report the missing
mapping and sensitivity requirement instead of merging a partially applied scoring
system.

## Suggested Git workflow after B7/B8 freeze

Start from the frozen integration branch and cherry-pick only the standalone C5
commit:

```sh
git cherry-pick 59de259
```

Resolve integration in a new Track B branch. Do not develop the adapter directly
on the live-evaluation or stable integration branch.
