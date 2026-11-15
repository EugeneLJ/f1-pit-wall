# Clean-host reproduction log (2026-11-15)

## Purpose

Follow the README "Reproduce" section on a host that had never run this project, and check
that a judge needs no undocumented step.

## Host

- A fresh Verda VM: Ubuntu 26.04.1 LTS, kernel 7.0.0-43, 16 vCPU.
- **Preinstalled:** Docker 29.9.3, Docker Compose v5.7.0, git, curl, python3.
- **Not present beforehand:** uv, Harbor, the repository, any API key.

## Steps, exactly as in the README

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv 0.13.8
uv tool install harbor==0.26.0                     # harbor 0.26.0
git clone --branch submission/2.1.0 https://github.com/EugeneLJ/f1-pit-wall.git && cd f1-pit-wall
# checkout: 1f55492d07d47ac3aec7b21f28247c8f7093371f (public HTTPS, no credentials)
f1-championship/scripts/run_v21.sh oracle         -o /root/judge/jobs --job-name clean-oracle
f1-championship/scripts/run_v21.sh nop            -o /root/judge/jobs --job-name clean-nop
f1-championship/scripts/run_v21.sh probe-stop     -o /root/judge/jobs --job-name clean-probe-stop
f1-championship/scripts/run_v21.sh probe-complete -o /root/judge/jobs --job-name clean-probe-complete
```

**Manual steps needed beyond these:** none. The first `oracle` run includes the image builds.

## Results

Artifacts are in `analysis/results/reproduction/clean-host-2026-11-15/<mode>/`.

| Mode | Wall time | Version | Complete | Intact | Points | Reward | Matches the Verda run |
|---|---:|---|---|---|---:|---:|---|
| oracle | 138 s (incl. image build) | 2.1.0 | yes (120 ticks) | yes | 289 | 0.7817 | yes: 289 / 0.7817 |
| nop | 48 s | 2.1.0 | no (0 ticks) | yes | 0 | 0.0 | yes |
| probe-stop | 49 s | 2.1.0 | no (2 ticks) | yes | 0 | 0.0 | yes |
| probe-complete | 49 s | 2.1.0 | yes (120 ticks) | yes | 229 | 0.5437 | yes: 229 / 0.5437 |

**Consistency checks** (run on the clean host over the captured files):
- For all four modes, `reward.txt` equals `report.json.reward`.
- For all four modes, the manifest `journal_sha256`, `journal_entries` and `head_hash` match the
  captured `journal.jsonl`.
- **The clean-host oracle journal is identical to the committed Verda oracle run**
  (`reference_runs/v21-oracle-01`) on every one of the 120 ticks: tick ids, the observation hashes
  before and after, and the action hashes. Only the wall-clock fields differ. The reference and
  simulator are therefore deterministic across hosts.

## Not covered on the clean host

- **A Frontier (`opencode`) run.** It needs a Gemini API key on the host, and no key was copied
  to the clean host. The fresh OpenCode season on the current task (instruction r2) ran on the
  main Verda host from the same commit and the same wrapper: `reference_runs/v21r2-gemini-01`.
- **The `opencode` image build.** The agent image is the same one the oracle build uses, so it
  was built here; only the model call itself was not exercised.
