# 2.2.0 scenario contract: rival interaction, stewarding, intra-team rivalry, weather (proposal v1)

**Status.** Proposal only. Nothing here is implemented. 2.2.0 is a new **opt-in** version layered on
2.1.0, like 2.1.0 on 2.0.1. It is planned for after submission, together with C5
(`docs/C5_INTERFACE_CONTRACT.md`).

**Invariants**
- Benchmarks 1.1.0, 2.0.1 and 2.1.0 stay byte-for-byte reproducible.
- With every 2.2.0 module switched off, a 2.2.0 race equals 2.1.0 bit for bit. A test is required.
- B7/B8 mechanics and frozen journals replay unchanged.
- Every coefficient is **synthetic** unless a fixture cites a verified source.
- Scenarios are inspired by real races but must not reproduce a specific race (drivers, teams,
  laps, results). Track names stay synthetic.
- No coefficient may be tuned to make a model fail. Each module ships with a public-input
  reference policy, and its natural frequency is measured before any frontier run.

## 0. Scope and coverage map

| ID | Situation | Coverage in 2.1.0 | This contract adds |
|---|---|---|---|
| S1 | Our leader, a rival on fresher tyres closing, a third-team car between: build a gap to the buffer car, or let it stay close (tow / overtake-mode window) so it defends against the chaser | none | M1 pace mode, M2 rival driver types, M3 proximity advantage |
| S2 | Low-overtaking track, a car backing up a train to protect a pit window; pass off track and accept a penalty, or wait | partial (overtaking difficulty, two-compound rule) | M1 (rival slow-pace), M4 stewarding, off-track pass action |
| S3 | A1-B1-B2-A2: A1 pits and rejoins behind B2. Use B2 to hold A1 (helps B1's overcut, costs B2 against A2), or let each car race | partial (own-car orders, C6 undercut/overcut probes) | M5 cross-team hold-up order |
| S4 | Dominant car, constructors' title likely; drivers' WDC rivalry costs team points | partial (SWAP, commitments, C8 conflicting Engineers) | M6 driver objectives and order compliance |
| S5 | VSC; the leading rival stays out: extend or take the cheap stop | **covered** (SC/VSC process, queue, C6 SC_VSC_OPPORTUNISTIC) | nothing new; S5 is the control family |
| S6 | Weather change; a rival switches to intermediates or wets, or stays out | none | M7 weather and wet compounds |

## M1. Pace mode (gap control)

**Action.** Per driver per segment, alongside the pit choice:
`pace: PUSH | NORMAL | MANAGE | TARGET_GAP`, where `TARGET_GAP` takes `{target: car_id, gap_sec: float}`.

**Engine contract**
- Pace mode adds a per-lap time offset and a tyre-degradation multiplier, from a public fixture.
  - PUSH: faster, higher wear.
  - MANAGE: slower, lower wear.
- `TARGET_GAP` is resolved by the engine within the car's pace envelope; it can never be faster than PUSH.
- With `pace` omitted, or every car on NORMAL, the race is bit-identical to 2.1.0.
- Rival cars use the published rule extended with a published pace rule (M2 decides the variant).

**Observation adds**
- the published pace table;
- current gaps ahead and behind for every car (already partly public);
- each own car's tyre-life estimate under each pace mode.

## M2. Rival driver types (hidden, inferable)

Each rival car has a hidden behaviour type drawn per race from a **published prior**:
- `DEFENDER`: defends against cars behind and does not attack the car ahead while defending.
- `OPPORTUNIST`: attacks the car ahead whenever the M3 advantage is active.
- `CONSERVATIVE`: no attack while the gap is above a published threshold.

**Rules**
- The type is never observed directly.
- Public evidence: past attack attempts and the pace modes inferred from public lap times
  (a published noisy signal).
- The reference uses the posterior from the public history only, so S1 is a decision under
  partial observability, not a lookup.
- Types draw from a seeded stream keyed by (race seed, car), independent of actions, so replay is exact.

## M3. Proximity advantage (tow / overtake-mode window)

- When a car is within the published threshold (default 1.0 s) of the car ahead at a segment
  boundary, it gains a published overtake-probability bonus in the M1/engine overtaking step.
  It also gains a small pace bonus on that segment.
- This is a synthetic abstraction of the 2026 manual-override / proximity rules, not an
  aerodynamic model. The fixture states which regulation it abstracts and that all values are synthetic.
- S1 is the trade-off. Letting the buffer car sit inside the window helps it defend against
  the chaser (if it is a `DEFENDER`), but gives it the bonus to attack us (if it is an `OPPORTUNIST`).

## M4. Stewarding model (verified against FIA 2026 documents)

**Sources** (checked 2026-11-15):
- FIA 2026 F1 Regulations, Section B Sporting, Issue 07 (2026-06-25):
  - B1.8.5 (unnecessarily slow or erratic driving);
  - B1.8.6 (leaving the track, lasting advantage, give-back at Race Director discretion);
  - B4.1.1 (impeding);
  - B1.9.5 (penalty list incl. 5 reprimands -> 10 grid places, suspension).
- 2026 F1 Penalty Guidelines v01.
- 2026 F1 Driving Standards Guidelines (section F, giving back a lasting advantage).

| Offence (race) | Published guideline | Penalty points | 2.2.0 model |
|---|---|---|---|
| Leaving the track and gaining a lasting advantage | 10 s baseline, up to drive-through; 5 s with mitigating circumstances | 0 | `OFF_TRACK_PASS` action; the engine offers a public **give-back window** first. If not returned: 10 s with p_base, 5 s with p_mitigating, drive-through with p_severe (published, synthetic probabilities) |
| Defending car leaves the track and keeps the position | generally must concede the position | 0 | same mechanism for a defending car |
| Driving unnecessarily slowly, sporting advantage | 5 s / 10 s | 0 | rival slow-pace (M1 MANAGE below a published floor) is investigated with a published probability; penalty 5 s or 10 s |
| Impeding with apparent intent | five grid places | 3 | not available as an action in 2.2.0 (no deliberate-impeding action is offered) |

**Escalation** (tracked per driver across the season in championship state)
- 12 penalty points -> suspension from the next event, then minus 12 points (Penalty Guidelines note 4–5).
- 5 reprimands (4 driving) -> 10 grid places (B1.9.5f).
- 2.2.0 offers no action that carries penalty points, so a ban cannot arise from these
  scenarios. The ledger exists for correctness and a test asserts it.

**Time penalties are served** as in B1.9.6: added at a pit stop or to the race time. The engine
uses one documented rule and tests it.

**Determinism.** Stewarding draws come from a seeded stream keyed by (race seed, car, incident
index), independent of other actions.

## M5. Cross-team hold-up order (S3)

**Team order** `HOLD_UP: {holder: own_car, target: rival_car, until_lap: int}`.
- Legal only when the holder is directly ahead of the target, within a published gap, with no
  pit planned this segment.
- **Engine:** the holder runs the published `HOLD_UP` pace (slower than NORMAL, cost shown in
  the observation). The target's overtake probability drops by the track's defend factor.
  The holder loses time to the cars behind it, including its own position battle (S3: B2 against A2).
- The holder's pace must stay above the M4 slow-driving floor, so `HOLD_UP` is legal racing,
  not deliberate impeding.
- **Feasibility** is published the same way as for SWAP: gap, rear gap, adjacency, blocking reasons.

## M6. Driver objectives and order compliance (S4)

**Championship state adds**
- drivers' standings;
- per driver, a published **compliance profile**: the probability of obeying HOLD / KEEP_ORDER /
  REQUEST_GIVE_BACK. It is a function of the public WDC gap to the teammate and of races remaining.

**Engine**
- When a team order binds a driver, compliance is drawn from a seeded stream.
- A non-complying driver races `RACE` for that segment. The outcome is journaled as
  `ORDER_DECLINED`, never hidden.
- Default profile: full compliance, so 2.2.0 with M6 off equals 2.1.0.

**Objective**
- The score stays **team points**: the constructors' objective is unchanged.
- An optional, separately reported diagnostic gives the WDC outcome for each driver. It is never
  mixed into the reward.

**Evaluation hook.** C8's `CONFLICTING_LOCAL_RECOMMENDATIONS` Engineers become the natural
pressure channel. Each Engineer argues for its own driver's WDC, and the Chief decides.

## M7. Weather and wet compounds (S6)

**State**
- A hidden rain process per race: a published Markov model over DRY / DAMP / WET with segment
  transition probabilities.
- A **public forecast**: noisy probabilities per future segment, with noise that shrinks with lead time.
- Track wetness evolves from rain intensity and drying.

**Compounds**
- `INTERMEDIATE` and `WET` join SOFT/MEDIUM/HARD.
- Lap time is a published function of compound × wetness, so crossover points exist and are public.
- A slick on a wet track pays a large published penalty plus a published off/spin probability (retirement risk).
- Two-compound rule (verified, Section B Issue 07, B6.3.6): a driver who used intermediate or
  wet-weather tyres in the race is exempt from using two dry specifications. Otherwise
  non-compliance means disqualification (30 s if the race is suspended and not restarted).
  2.2.0 applies the exemption and keeps the existing two-compound rule.

**Rival behaviour.** Rivals switch using the published crossover rule, with an M2-style hidden
early/late bias. A rival's switch is therefore a public signal about wetness, and following it
is a real decision.

**Neutralisation.** Heavy rain raises SC/VSC hazard through a published multiplier on the
existing SC/VSC process.

## Reference policies and evaluation

**Reference**
- The 2.1.0 reference (authoritative-engine public-input rollout) is extended with:
  - a joint action space (pit × pace × order) pruned by a published dominance rule;
  - M2 posterior sampling and M7 forecast sampling in its futures.
- It keeps its labelled model-access advantage.

**Natural-frequency study before any frontier run.** For each family S1–S6:
- how often the decision arises;
- how often the reference preference is separated (C7 precedence: NEAR_TIE first);
- reversal rates under rival-type and weather variants.

A family that never produces separated decisions is reported as such and not enlarged by tuning.

**Seed budget:** staged policy unchanged (smoke 1–2, dev 5 paired, intermediate 10–20, final up
to 100 held-out only with a stated reason).

**Analysis**
- Failure classes follow C4/C6 rules: regret > 1.0 and > 2 SE, robust under 3× futures and
  alternative continuations.
- Classes are descriptive, not causal.

## Journal, replay, verifier

- New actions and draws are ordinary journal v2 entries:
  - pace;
  - off-track pass and give-back;
  - stewarding outcomes;
  - HOLD_UP;
  - compliance draws;
  - weather state.
- All draws are recomputed from seeded streams on replay. The verifier needs no new trust assumption.
- Hidden types, the true rain path and stewarding draws never appear in observations. A
  recursive leakage test is required.

## Delivery order and ownership

| Step | Content | Notes |
|---|---|---|
| 1 | M1 pace mode + bit-identity test | smallest engine change; S1–S3 depend on it |
| 2 | M4 stewarding + M5 HOLD_UP | S2, S3 |
| 3 | M2 rival types + M3 proximity | S1; partial observability |
| 4 | M6 compliance | S4; pairs with C8 |
| 5 | M7 weather | S6; the largest change, may become its own version if it grows |
| 6 | C5 practice/qualifying | per its own contract |

- The engine owner edits `src/f1pitwall/**` and syncs with `scripts/sync_engine.py`.
- Track C contributes pure functions and fixtures in `track_c/` as in C5.
- Each step lands behind a flag, with tests, before the next starts.

## Not decided

- Exact pace-table values and the S2 investigation probability.
- Whether M2 types persist across a season (proposal: per race).
- Whether M6 compliance also covers SWAP give-back (proposal: yes, via REQUEST_GIVE_BACK).
- Whether M7 adds a red-flag process (proposal: no in 2.2.0).
- Whether the Harbor instruction gains a 2.2.0 addendum like 2.1.0 (proposal: yes, rules only, no strategy hints).
