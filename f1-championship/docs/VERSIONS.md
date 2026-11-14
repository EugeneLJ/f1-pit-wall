# Benchmark versions

The version is `f1pitwall.version.BENCHMARK_VERSION`. It appears in:
- `f1ctl rules` → `benchmark_version`
- the sidecar `ping` reply and the evidence `manifest.json` → `benchmark_version`
- the verifier report → `benchmark_version`, plus `evidence.evidence_benchmark_version` for the version that produced the evidence
- `task.toml` → `[task].version`

Results are comparable only within one version.

## 1.1.0 — interface clarification (2026-11-14)

**Agent-visible change (in `f1ctl rules` only):**

| Field | 1.0.0 | 1.1.0 |
|---|---|---|
| `race_rules_track_a.published_base_pace` | Keyed by engine-internal identifiers (`Rival 1`…`Rival 6`, `Apex A`, `Apex B`). Observations name the same cars `Orion A`, `Nova B`, …, and the mapping between the two was not published. | Keyed by the observation names (`Apex A`, `Apex B`, `Orion A`, `Orion B`, `Nova A`, `Nova B`, `Vertex A`, `Vertex B`). **The values are identical.** |
| `race_rules_track_a.driver_identifiers` | — | New. `engine_internal_to_public` mapping, plus the team → driver list |
| `benchmark_version` (top level of rules) | — | New. `"1.1.0"` |
| `contract` (description string) | `"f1-championship sequential decisions, P0 mechanics"` | `"f1-championship sequential decisions (Track A + Track B race strategy)"` |

**Not agent-visible:**
- **Evidence and verifier:** `manifest.json`, the verifier report and the `ping` reply gain `benchmark_version`. The sidecar `server_version` string becomes the benchmark version (it was `"b4-1"`).
- **`task.toml`:** `[task].version` 0.1.0 → 1.1.0.
- **Analysis runtime pin (local reproducibility only):**
  - `.python-version` = 3.12 and `scripts/py312` (runs analysis on Python 3.12 via uv).
  - Every replay and analysis entry point refuses other interpreters unless `F1_ALLOW_ANY_PYTHON=1` is set.
  - The reason: the sidecar and verifier images run Python 3.12.12. Python 3.12 changed float `sum()` to compensated summation, so on Python 3.9 the r2 journal from 1.0.0 fails its hash check at entry 11.
  - This changes nothing inside the images.

**Unchanged:**
- Mechanics, coefficients, event model, action space and legal actions
- Observations; no observation field changed
- `instruction.md`, the reward formula (`p0-provisional`), the journal format, and the hidden-seed handling

`devtests/test_version_interface.py` checks:
- **Observations:** a full season of observations contains no internal identifiers.
- **Rules:** internal identifiers appear only in the mapping table, and the published paces equal the engine's.
- **Historical replay:** the four 1.0.0 runs replay intact and regrade to their original rewards on Python 3.12.

**Why this is not a simplification.**
- **Before:** the information was already public in 1.0.0, under names the observations did not use. One agent (run r3) mapped two cars the wrong way round.
- **After:** the same information is stated unambiguously.
- **Unchanged:** the strategic problem is the same, and no hidden state, seed or future event is exposed.

## 1.0.0 — B4 task (commit `ebbabce`, sidecar `server_version` `"b4-1"`)

The four Gemini runs r0–r3 were evaluated on this version. Their rewards, trajectories and reports are kept as historical results:
- `docs/B4_REPORT.md`
- `docs/FRONTIER_REPEAT_REPORT.md`
- `analysis/results/rep_runs/` (evidence journals included)
- the Harbor job directories on Verda

| Run | Reward (1.0.0) |
|---|---:|
| r0 | 0.69841270 |
| r1 | 0.70384615 |
| r2 | 0.63076923 |
| r3 | 0.68846154 |

Earlier development states (P0–B3) had no benchmark version; use the git tags and commits named in their reports.
