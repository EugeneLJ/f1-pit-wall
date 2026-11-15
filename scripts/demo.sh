#!/usr/bin/env bash
# Fresh Harbor + OpenCode championship run, verified artifact capture, and static report.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 0 ]]; then
    echo "Usage: $0 (configure with F1_* environment variables; see README.md)" >&2
    exit 2
fi

BENCHMARK_PATH="${F1_BENCHMARK_PATH:-$ROOT/f1-championship}"
if [[ "$BENCHMARK_PATH" != /* ]]; then
    BENCHMARK_PATH="$ROOT/$BENCHMARK_PATH"
fi
OUTPUT_ROOT="${F1_OUTPUT_DIR:-$ROOT/jobs}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
HARBOR_BIN="${F1_HARBOR_BIN:-harbor}"
MODEL="${F1_MODEL:-gemini/gemini-3.8-flash}"
API_KEY_NAME="${F1_API_KEY_NAME:-GEMINI_API_KEY}"
ENV_FILE="${F1_ENV_FILE:-}"
AGENT_HOST="${F1_AGENT_HOST-generativelanguage.googleapis.com}"
JOB_NAME="${F1_JOB_NAME:-opencode}"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$OUTPUT_ROOT/demo-$RUN_STAMP-$$"
REPORT_PATH="$RUN_DIR/report.html"
HARBOR_LOG="$RUN_DIR/harbor.log"

# Python 3.12 is required only for the optional canonical per-race replay. The
# rest of the renderer is stdlib-only and also works on older Python 3 versions.
PYTHON_BIN="${F1_PYTHON:-python3}"
if [[ -z "${F1_PYTHON:-}" ]] && command -v python3 >/dev/null 2>&1; then
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
        if [[ -x "$BENCHMARK_PATH/scripts/py312" ]] && \
            "$BENCHMARK_PATH/scripts/py312" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
            PYTHON_BIN="$BENCHMARK_PATH/scripts/py312"
        fi
    fi
fi

if ! mkdir -p -- "$OUTPUT_ROOT" || ! mkdir -- "$RUN_DIR"; then
    echo "Cannot create fresh demo output directory: $RUN_DIR" >&2
    exit 2
fi
: > "$HARBOR_LOG"
printf 'Run directory: %s\n' "$RUN_DIR"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HARBOR_VERSION="unavailable"
if command -v "$HARBOR_BIN" >/dev/null 2>&1; then
    VERSION_OUTPUT="$("$HARBOR_BIN" --version 2>&1)"
    if [[ -n "$VERSION_OUTPUT" ]]; then
        HARBOR_VERSION="$VERSION_OUTPUT"
    fi
fi

# Record configuration only. No environment dump, credential value, or seed is
# included in run.json or the HTML report.
if command -v "$PYTHON_BIN" >/dev/null 2>&1 || [[ -x "$PYTHON_BIN" ]]; then
    "$PYTHON_BIN" - "$RUN_DIR/run.json" "$RUN_STAMP-$$" "$MODEL" "$API_KEY_NAME" "$ENV_FILE" "$BENCHMARK_PATH" "$STARTED_AT" "$HARBOR_VERSION" <<'PY'
import json
import sys
from pathlib import Path
(
    output, run_id, model, credential_name, env_file, benchmark,
    started_at, harbor_version,
) = sys.argv[1:]
Path(output).write_text(json.dumps({
    "schema_version": 1,
    "run_id": run_id,
    "agent": "opencode",
    "model": model,
    "credential_env": credential_name,
    "credential_source": "environment" if not env_file else "Harbor env file",
    "benchmark_path": benchmark,
    "started_at": started_at,
    "harbor_version": harbor_version,
    "harbor_log": "harbor.log",
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
    METADATA_STATUS=$?
else
    echo "Python interpreter not found: $PYTHON_BIN" >&2
    exit 2
fi
if [[ $METADATA_STATUS -ne 0 ]]; then
    echo "Could not write run metadata" >&2
    exit "$METADATA_STATUS"
fi

HARBOR_EXIT=0
PREFLIGHT_ERROR=""
if [[ ! -d "$BENCHMARK_PATH" ]]; then
    PREFLIGHT_ERROR="Benchmark path is not a directory: $BENCHMARK_PATH"
    HARBOR_EXIT=2
elif ! command -v "$HARBOR_BIN" >/dev/null 2>&1; then
    PREFLIGHT_ERROR="Harbor executable not found: $HARBOR_BIN"
    HARBOR_EXIT=127
elif [[ -z "$MODEL" ]]; then
    PREFLIGHT_ERROR="F1_MODEL must not be empty"
    HARBOR_EXIT=2
elif [[ ! "$API_KEY_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    PREFLIGHT_ERROR="F1_API_KEY_NAME must be an environment variable name"
    HARBOR_EXIT=2
elif [[ -n "$ENV_FILE" && ! -r "$ENV_FILE" ]]; then
    PREFLIGHT_ERROR="Credential env file is not readable: $ENV_FILE"
    HARBOR_EXIT=2
elif [[ -z "$ENV_FILE" && -z "${!API_KEY_NAME:-}" ]]; then
    PREFLIGHT_ERROR="Set $API_KEY_NAME in the environment or provide F1_ENV_FILE (the key value is never printed)"
    HARBOR_EXIT=2
fi

if [[ -n "$PREFLIGHT_ERROR" ]]; then
    printf 'ERROR: %s\n' "$PREFLIGHT_ERROR" | tee -a "$HARBOR_LOG" >&2
else
    printf 'Running Harbor lint and a fresh OpenCode trial with model %s\n' "$MODEL" | tee -a "$HARBOR_LOG"
    "$HARBOR_BIN" lint "$BENCHMARK_PATH" 2>&1 | tee -a "$HARBOR_LOG"
    LINT_EXIT=${PIPESTATUS[0]}
    if [[ $LINT_EXIT -ne 0 ]]; then
        HARBOR_EXIT=$LINT_EXIT
        printf 'Harbor lint failed with exit %d; no trial was launched.\n' "$LINT_EXIT" | tee -a "$HARBOR_LOG" >&2
    else
        COMMAND=(
            "$HARBOR_BIN" run
            -p "$BENCHMARK_PATH"
            -a opencode
            -m "$MODEL"
            --api-key-name "$API_KEY_NAME"
            -o "$RUN_DIR/harbor-output"
            --job-name "$JOB_NAME"
        )
        if [[ -n "$ENV_FILE" ]]; then
            COMMAND+=(--env-file "$ENV_FILE")
        fi
        if [[ -n "$AGENT_HOST" ]]; then
            COMMAND+=(--allow-agent-host "$AGENT_HOST")
        fi
        "${COMMAND[@]}" 2>&1 | tee -a "$HARBOR_LOG"
        HARBOR_EXIT=${PIPESTATUS[0]}
        printf 'Harbor run exit code: %d\n' "$HARBOR_EXIT" | tee -a "$HARBOR_LOG"
    fi
fi

if [[ -t 1 ]]; then
    DEFAULT_DELAY="0.12"
else
    DEFAULT_DELAY="0"
fi
FINALIZE=(
    "$PYTHON_BIN" "$ROOT/scripts/demo.py" finalize
    --run-dir "$RUN_DIR"
    --benchmark-path "$BENCHMARK_PATH"
    --harbor-exit-code "$HARBOR_EXIT"
    --output "$REPORT_PATH"
    --tty "${F1_PROGRESS:-auto}"
    --replay-delay "${F1_REPLAY_DELAY:-$DEFAULT_DELAY}"
)
[[ -n "${F1_REFERENCE_REPORT:-}" ]] && FINALIZE+=(--reference-report "$F1_REFERENCE_REPORT")
[[ -n "${F1_REFERENCE_EVIDENCE:-}" ]] && FINALIZE+=(--reference-evidence "$F1_REFERENCE_EVIDENCE")
[[ -n "${F1_REFERENCE_SEED:-}" ]] && FINALIZE+=(--reference-seed "$F1_REFERENCE_SEED")
[[ -n "${F1_FRONTIER_SEED_PATH:-}" ]] && FINALIZE+=(--seed-path "$F1_FRONTIER_SEED_PATH")
[[ -n "${F1_FAILURE_EVIDENCE:-}" ]] && FINALIZE+=(--failure-evidence "$F1_FAILURE_EVIDENCE")

"${FINALIZE[@]}"
FINALIZE_EXIT=$?
if [[ $HARBOR_EXIT -ne 0 ]]; then
    exit "$HARBOR_EXIT"
fi
exit "$FINALIZE_EXIT"
