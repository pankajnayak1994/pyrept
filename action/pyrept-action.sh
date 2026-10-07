#!/usr/bin/env bash
# Runs the steps of the pyrept GitHub Action (action.yml). Kept as a script so it
# can be tested locally: every input arrives as a PYREPT_INPUT_* variable.
set -euo pipefail

report="${PYREPT_INPUT_REPORT:-report.json}"
python_bin="${PYREPT_PYTHON:-}"

if [ -z "$python_bin" ]; then
  base="$(command -v python3 || command -v python || true)"
  if [ -z "$base" ]; then
    echo "::error::pyrept needs Python on the runner; add actions/setup-python before this action." >&2
    exit 2
  fi
  # A virtual environment: runner images mark the system Python as externally managed (PEP 668).
  venv="${RUNNER_TEMP:-/tmp}/pyrept-venv"
  "$base" -m venv "$venv"
  if [ -x "$venv/bin/python" ]; then python_bin="$venv/bin/python"; else python_bin="$venv/Scripts/python.exe"; fi
  spec="pyrept"
  if [ -n "${PYREPT_INPUT_VERSION:-}" ]; then spec="pyrept==${PYREPT_INPUT_VERSION}"; fi
  "$python_bin" -m pip install --quiet --disable-pip-version-check "$spec"
fi
pyrept() { "$python_bin" -m pyrept "$@"; }

gate_args=()
[ "${PYREPT_INPUT_FAIL_ON_FAILURE:-false}" = "true" ] && gate_args+=(--fail-on-failure)
[ "${PYREPT_INPUT_IGNORE_KNOWN_FAILURES:-false}" = "true" ] && gate_args+=(--ignore-known-failures)
[ -n "${PYREPT_INPUT_FAIL_UNDER:-}" ] && gate_args+=(--fail-under "$PYREPT_INPUT_FAIL_UNDER")
url_args=()
[ -n "${PYREPT_INPUT_REPORT_URL:-}" ] && url_args+=(--report-url "$PYREPT_INPUT_REPORT_URL")

# 1. Optionally convert another tool's report (JUnit XML, Cucumber, Playwright, TRX, ...).
if [ -n "${PYREPT_INPUT_CONVERT_FROM:-}" ]; then
  if [ -z "${PYREPT_INPUT_CONVERT_INPUTS:-}" ]; then
    echo "::error::convert-from needs convert-inputs (files or glob patterns)." >&2
    exit 2
  fi
  html="${PYREPT_INPUT_HTML:-$(dirname "$report")/report.html}"
  convert_args=(convert --from "$PYREPT_INPUT_CONVERT_FROM" --html "$html" --json "$report")
  [ -n "${PYREPT_INPUT_BASELINE:-}" ] && convert_args+=(--baseline "$PYREPT_INPUT_BASELINE")
  [ -n "${PYREPT_INPUT_TITLE:-}" ] && convert_args+=(--title "$PYREPT_INPUT_TITLE")
  [ -n "${PYREPT_INPUT_JUNIT:-}" ] && convert_args+=(--junit "$PYREPT_INPUT_JUNIT")
  # Word splitting and globbing of the inputs are intended: "reports/*.xml build/*.xml".
  shopt -s nullglob
  # shellcheck disable=SC2206
  inputs=($PYREPT_INPUT_CONVERT_INPUTS)
  shopt -u nullglob
  if [ "${#inputs[@]}" -eq 0 ]; then
    echo "::error::no files match convert-inputs: $PYREPT_INPUT_CONVERT_INPUTS" >&2
    exit 2
  fi
  pyrept "${convert_args[@]}" "${inputs[@]}"
fi

if [ ! -f "$report" ]; then
  echo "::error::pyrept report not found: $report (run your tests with pyrept first, or use convert-from)." >&2
  exit 2
fi

# 2. Markdown summary: job summary, PR comment body, outputs.
summary_file="${RUNNER_TEMP:-/tmp}/pyrept-summary.md"
summary_args=(summary "$report" --markdown "$summary_file")
[ "${PYREPT_INPUT_JOB_SUMMARY:-true}" = "true" ] && summary_args+=(--github-summary)
[ "${PYREPT_INPUT_NOTIFY:-false}" = "true" ] && summary_args+=(--notify)
set +e
pyrept "${summary_args[@]}" ${url_args[@]+"${url_args[@]}"} ${gate_args[@]+"${gate_args[@]}"}
status=$?
set -e
if [ "$status" -eq 2 ]; then
  exit 2
fi

"$python_bin" - "$report" "$summary_file" "$status" <<'PY' >> "${GITHUB_OUTPUT:-/dev/null}"
import json, sys
report, summary_file, status = sys.argv[1], sys.argv[2], sys.argv[3]
with open(report, encoding='utf-8-sig') as fh:
    data = json.load(fh)
s = data.get('test_summary') or {}
cmp = data.get('comparison') or {}
print('total=%s' % s.get('total', 0))
print('passed=%s' % s.get('passed', 0))
print('failed=%s' % s.get('failed', 0))
print('errors=%s' % s.get('error', 0))
print('skipped=%s' % s.get('skipped', 0))
print('pass-rate=%s' % s.get('percentage', 0))
print('new-failures=%s' % len(cmp.get('new_failures') or []))
print('summary-file=%s' % summary_file)
print('gate-status=%s' % status)
PY
echo "pyrept: summary written to $summary_file (gate status $status)"
