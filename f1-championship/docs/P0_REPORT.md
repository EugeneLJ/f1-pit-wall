# P0 report — sealed championship evaluation boundary

Date: 2026-11-14 · Harbor 0.26.0 · Docker 29.9.3 / Compose v5.7.0 (Verda)

Scope: evaluation boundary only. No frontier/API run was performed. Race
mechanics are unchanged from the legacy engine, so the scores below test the
boundary and the scoring pipeline. They are not strategy results.

## Harbor runs (Verda, `/root/f1-championship-p0/jobs/`)

| Job | Agent | Accepted decisions | Rejected (logged) | Complete | Intact | Apex pts | Reward |
|---|---|---:|---:|---|---|---:|---:|
| `p0-oracle-01` | oracle (heuristic, user `node`) | 32 | 0 | yes | yes | 177 | 0.24774775 |
| `p0-oracle-02` | oracle, after the final client fix | 32 | 0 | yes | yes | 177 | 0.24774775 |
| `p0-nop-01` | `nop` | 0 | 0 | no | yes | 0 | 0.0 |
| `p0-probe-complete-01` | adversarial probe as **root**, then finishes legitimately | 32 | 24 | yes | yes | 177 | 0.24774775 |
| `p0-probe-stop-01` | adversarial probe as root, deletes the socket, quits | 2 | 23 | no | yes | — | 0.0 |
| `p0-inspect-01` | oracle with 45 s delay, used to inspect live containers | 32 | 0 | yes | yes | 177 | 0.24774775 |

The same play always produced the same reward, 0.24774775, in all four runs that
finished. That includes the probe run, which sent 24 rejected and 8 malformed
requests along the way.
Normalization on the hidden seed: D (do-nothing) = 122, U = 344.

## Boundary checks and evidence

| Requirement | Result | Evidence |
|---|---|---|
| Seed hidden from agent | Pass | Hidden seed occurs 0 times in `docker save` of the agent image. The probe, running as root, found no `/opt/f1sim`, `/var/lib/f1sim` or `/evidence/f1sim`, no file mentioning `base_seed` or the journal (apart from its own source), and no simulator process |
| Shared volume = socket only | Pass | Probe listing of `/run/f1sim`: `["sim.sock"]`. Live `docker inspect`: sim `net=none`, and both containers mount only `f1sock → /run/f1sim` |
| No reset / rewind / seed | Pass | `reset`, `rewind`, `seed` → `unknown_command`. Extra fields → `malformed_request`. Restarting the server replays its journal and resumes at the same observation (unit test). A tampered private journal makes the server refuse to start |
| Duplicate / out-of-order rejected | Pass | Resending `d001` → `duplicate_decision`. `d999` → `out_of_order_decision`. 20 concurrent submissions of the same decision: exactly 1 accepted, 19 `duplicate_decision` |
| Per-request phase/action validation | Pass | A race action during the component phase → `invalid_action`, with no state change. Malformed JSON, binary input and missing ids are rejected. Requests over 16 KB are dropped (connection closed) |
| Agent file forgery ignored | Pass | The probe wrote `/logs/verifier/reward.txt` = 1.0, fake `/evidence/f1sim/*`, `/logs/artifacts/...` and `/app/submission/actions.json`. Reward was unchanged. The artifact manifest shows `/evidence/f1sim` collected with `service: "sim"`. The fake copy only landed in the agent's own `logs/artifacts`, which the verifier never reads |
| Verifiable evidence | Pass | The collect hook seals the session after the agent container stops. The verifier checks the manifest hash, entry count, hash chain and head hash, then replays every entry from the hidden seed. Unit tests: an edited journal, a fully re-sealed forged action, a forged rejection of a legal action, or a wrong seed each give reward 0 with `intact: false` |
| Stop-early / nop | Pass | 0.0 in both cases, with the report saying `complete: false, intact: true` |

Local tests: `devtests/` 25/25. Legacy `tests/` 35/35 (legacy files untouched).
`harbor lint f1-championship`: clean.

## Measured timing (oracle)

- Harbor trial wall clock: about 48–50 s with cached images (build, start, healthcheck, collect, verifier).
- Making all 32 decisions took 0.73 s. Mean gap between decisions 0.02 s. Worst server latency 6 ms.
- Frontier-run timing has not been measured. The agent time limit is set to 1800 s, a placeholder until P3.

## Constraints found in the current structure (to address in P1/P2)

1. **The component phase has no strategic effect.** With the fixture's total stress of 4.9, maximum wear reaches only 0.784 (ICE), below the 0.85 limit. Wear also never changes pace or retirement risk, so `USE` always dominates and `REPLACE` only burns spares or earns grid drops.
2. **Track values are ignored by the race engine.** `power_unit_stress` is used only for wear. `overtaking_difficulty` and `tyre_degradation` have no effect. Every round restarts from the same legacy grid and car paces, with only the event seed changing.
3. **Competitive balance is degenerate.** Orion scores 341 of a possible 344, so Apex's rank (2nd) and the title fight cannot change. The constructors' margin is therefore uninformative, and "team vs rival" objectives are meaningless until car paces vary.
4. **Normalization is compressed.** U = 344 can't be reached while Orion dominates, so a decent heuristic scores only 0.248. For P2 I suggest replacing U with a *hindsight optimum* computed on the same hidden seed with full future knowledge. That is a true upper bound, not achievable by fair play, and distinct from the reference planner. Reference-relative regret would be reported separately.
5. **The race decision space is small**: 3 PIT/STAY decisions, pit always fits MEDIUM, rivals follow fixed rules and ignore the championship. That's 64 action sequences per race. Gemini already solved the single-race version exactly.
6. **Observations can't support planning from public information.** Rival base pace and the traffic and tyre state needed to re-simulate aren't in the observation, so a fair planner (or agent) can't model outcomes from public data. P1 needs to expose what a pit wall would legitimately know.
7. **Events don't depend on the track.** SC/VSC odds are the same everywhere, and race seeds are `base_seed + index`, independent per round.
8. **Scaling cost.** The server deep-copies the session on every `act` (O(trace) per action). That's fine for 32 decisions, but it needs revisiting for the planned larger decision count and Engineer A/B coordination. Rejected-request logging is capped at 2000 entries (the excess is counted, not logged).
9. **Harbor specifics.** In no-network mode the agent container joins Harbor's egress-control network namespace, while the sim sidecar has `network_mode: none`. The verifier also receives the agent's own `/logs/artifacts`, which it ignores. The oracle runs as the image's default user unless `[agent].user` is set (the probe sets root). `harbor lint` needs the Docker CLI, which this Mac doesn't have, so lint runs on Verda.
10. **Self-sabotage is possible but harmless.** An agent running as root can delete or replace the socket. That only breaks its own session, which then scores 0 as incomplete. The collect hook never uses the socket.
11. **Engine copies.** The engine is edited in `src/f1pitwall` and synced into the sim and verifier images. P1 will intentionally diverge it from the legacy root engine, which stays frozen.
