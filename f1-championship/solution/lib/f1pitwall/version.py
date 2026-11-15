"""Benchmark version of the f1-championship task.

Bump this whenever agent-visible information (instruction, observations, `f1ctl rules`),
mechanics, the action space or scoring change. Results are only comparable within a version.
"""

BENCHMARK_VERSION = "1.1.0"

# Interpreter used by the sim sidecar and verifier images (python:3.12.12-slim-bookworm).
# Replays and analyses must use the same minor version to be bit-exact (Python 3.12 changed
# float sum() to compensated summation, which can change rounding of replayed observations).
RUNTIME_PYTHON = (3, 12)

VERSION_HISTORY = {
    "1.0.0": ("B4 task (commit ebbabce, sidecar SERVER_VERSION 'b4-1'): the four Gemini runs r0-r3 "
              "were evaluated on this version."),
    "1.1.0": ("Interface clarification only: `f1ctl rules` publishes base paces under the driver names "
              "used in observations and states the internal-identifier mapping explicitly; a "
              "benchmark_version field is added to rules, evidence manifest and verifier report. "
              "Mechanics, event model, action space, observations and scoring unchanged."),
}
