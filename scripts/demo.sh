#!/usr/bin/env bash
# F1 Championship Strategist — 2.1.0 submission demo.
#
#   LIVE      F1_ENV_FILE=<file with GEMINI_API_KEY=...> scripts/demo.sh live
#             Builds the 2.1.0 task with f1-championship/scripts/run_v21.sh, runs a FRESH Harbor +
#             OpenCode Gemini season (about 10 min), then verifies it and writes report.html.
#             If the run fails, the report says so; recorded evidence is never substituted.
#   RECORDED  scripts/demo.sh recorded [run]      (default run: v21-gemini-01)
#             Verifies and renders a committed genuine 2.1.0 Harbor run
#             (f1-championship/analysis/results/reference_runs/<run>), labelled as a replay.
#
# Both modes compare against the committed Reference run (v21-oracle-01) on the same benchmark,
# mode and seed. Output: jobs/demo-<mode>-<UTC stamp>/report.html (override with F1_OUTPUT_DIR).
# The report opens in the default browser when one is available (macOS `open`, Linux `xdg-open` with a
# display); set F1_OPEN=0 to only print its path.
# Optional: F1_MODEL (default gemini/gemini-3.8-flash), F1_REFERENCE (a committed run, or none),
# F1_HARBOR_BIN (default harbor).
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_SRC="$ROOT/f1-championship"
PY="$TASK_SRC/scripts/py312"            # Python 3.12 through uv, the same version as the images
MODE="${1:-}"
OUTPUT_ROOT="${F1_OUTPUT_DIR:-$ROOT/jobs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REFERENCE="${F1_REFERENCE:-v21-oracle-01}"

usage() { sed -n '2,17p' "$0" >&2; exit 2; }

open_report() {  # $1 = report path; never fails the demo
    [[ "${F1_OPEN:-1}" == "0" || ! -f "$1" ]] && return 0
    if [[ "$(uname)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
        open "$1" >/dev/null 2>&1 && echo "Opened the report in your browser."
    elif [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 & echo "Opened the report in your browser."
    else
        echo "No desktop browser here; open the report path above (or copy the run directory to a machine with a browser)."
    fi
}
[[ "$MODE" == "live" || "$MODE" == "recorded" ]] || usage
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
    echo "ERROR: Python 3.12 is required (f1-championship/scripts/py312 uses uv: https://docs.astral.sh/uv/)" >&2
    exit 2
fi
RUN_DIR="$OUTPUT_ROOT/demo-$MODE-$STAMP"
mkdir -p "$RUN_DIR" || exit 2
echo "F1 Championship Strategist — benchmark 2.1.0 demo ($MODE)"
echo "Run directory: $RUN_DIR"

if [[ "$MODE" == "recorded" ]]; then
    RUN="${2:-v21-gemini-01}"
    echo "Recorded replay of committed Harbor run: $RUN (not a live execution)"
    "$PY" "$ROOT/scripts/demo.py" finalize --mode recorded --run "$RUN" --run-dir "$RUN_DIR" --reference "$REFERENCE"
    STATUS=$?
    open_report "$RUN_DIR/report.html"
    exit $STATUS
fi

# ---------------------------------------------------------------- LIVE
HARBOR_BIN="${F1_HARBOR_BIN:-harbor}"
MODEL="${F1_MODEL:-gemini/gemini-3.8-flash}"
ENV_FILE="${F1_ENV_FILE:-${GEMINI_ENV_FILE:-}}"
LOG="$RUN_DIR/harbor.log"
: > "$LOG"
ERROR=""
if ! command -v "$HARBOR_BIN" >/dev/null 2>&1; then ERROR="Harbor not found ($HARBOR_BIN); install with: uv tool install harbor==0.26.0"
elif ! docker info >/dev/null 2>&1; then ERROR="Docker is not available"
elif [[ -z "$ENV_FILE" || ! -r "$ENV_FILE" ]]; then ERROR="set F1_ENV_FILE to a readable file containing GEMINI_API_KEY=... (the key is never printed or copied)"
fi
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HARBOR_VERSION="$("$HARBOR_BIN" --version 2>/dev/null | tail -1)"
"$PY" - "$RUN_DIR/run.json" "$MODEL" "$STARTED" "$HARBOR_VERSION" <<'PY'
import json, sys
out, model, started, harbor = sys.argv[1:]
json.dump({"schema_version": 2, "mode": "live", "agent": "opencode", "model": model, "started_at": started,
           "harbor_version": harbor or "unavailable", "credential": "env file (value never recorded)"},
          open(out, "w"), indent=2)
PY
HARBOR_EXIT=0
if [[ -n "$ERROR" ]]; then
    echo "ERROR: $ERROR" | tee -a "$LOG" >&2
    HARBOR_EXIT=2
else
    echo "Starting a fresh Harbor + OpenCode season with $MODEL (about 10 minutes)."
    echo "Status below is Harbor's own output; the sealed simulator exposes no progress until it is verified."
    F1_BUILD_DIR="$RUN_DIR/build" GEMINI_ENV_FILE="$ENV_FILE" F1_MODEL="$MODEL" F1_HARBOR_BIN="$HARBOR_BIN" \
        "$TASK_SRC/scripts/run_v21.sh" opencode -o "$RUN_DIR/harbor-output" --job-name live 2>&1 | tee -a "$LOG"
    HARBOR_EXIT=${PIPESTATUS[0]}
    echo "Harbor exit code: $HARBOR_EXIT" | tee -a "$LOG"
fi
if [[ ! -d "$RUN_DIR/build/task" ]]; then
    # Preflight failed before the task was built: build it so the report can still be rendered (as FAILED).
    "$TASK_SRC/scripts/make_integrated_task.sh" "$RUN_DIR/build/task" CHIEF_ONLY 2.1.0 >/dev/null
fi
"$PY" "$ROOT/scripts/demo.py" finalize --mode live --run-dir "$RUN_DIR" --task "$RUN_DIR/build/task" \
    --harbor-exit-code "$HARBOR_EXIT" --reference "$REFERENCE"
STATUS=$?
open_report "$RUN_DIR/report.html"
exit $STATUS
