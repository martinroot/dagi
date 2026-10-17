#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'EOF'
Run explicit Python selectors and an optional focused Node UI test in parallel.

Usage:
  bash scripts/test-focused.sh [--python PATH] [--node-pattern REGEX] SELECTOR...

Examples:
  bash scripts/test-focused.sh \
    --node-pattern 'file update renderer shows bounded diffs' \
    tests/test_core_tools.py::test_write_file_returns_bounded_unified_diff_for_small_text_update

  bash scripts/test-focused.sh tests/test_core_tools.py::test_read_file_returns_structured_path_size_line_count_and_truncation

This is a fast red/green loop, not the issue-closure gate. Before closing an issue,
run the full pytest suite, the full Node UI suite, and the package build.
EOF
}

python_bin="${DAGI_TEST_PYTHON:-.venv/bin/python}"
node_bin="${DAGI_TEST_NODE:-node}"
node_pattern=""
selectors=()

while (($#)); do
  case "$1" in
    --python)
      if (($# < 2)); then echo "--python requires an executable path" >&2; exit 2; fi
      python_bin="$2"
      shift 2
      ;;
    --node-pattern)
      if (($# < 2)); then echo "--node-pattern requires a test-name pattern" >&2; exit 2; fi
      node_pattern="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      selectors+=("$@")
      break
      ;;
    *)
      selectors+=("$1")
      shift
      ;;
  esac
done

if ((${#selectors[@]} == 0)) && [[ -z "$node_pattern" ]]; then
  usage >&2
  exit 2
fi

pids=()
labels=()

if ((${#selectors[@]})); then
  if [[ ! -x "$python_bin" ]]; then
    echo "Python test runner is not executable: $python_bin (override with --python or DAGI_TEST_PYTHON)" >&2
    exit 2
  fi
  echo "[focused-tests] pytest selectors: ${selectors[*]}" >&2
  "$python_bin" -m pytest "${selectors[@]}" -q --tb=short &
  pids+=("$!")
  labels+=("pytest")
fi

if [[ -n "$node_pattern" ]]; then
  if ! command -v "$node_bin" >/dev/null 2>&1; then
    echo "Node test runner not found: $node_bin (override with DAGI_TEST_NODE)" >&2
    exit 2
  fi
  echo "[focused-tests] Node UI pattern: $node_pattern" >&2
  "$node_bin" --test --test-name-pattern="$node_pattern" tests/test_core_web_ui.js &
  pids+=("$!")
  labels+=("Node UI")
fi

status=0
for index in "${!pids[@]}"; do
  if wait "${pids[$index]}"; then
    echo "[focused-tests] ${labels[$index]} passed" >&2
  else
    result=$?
    echo "[focused-tests] ${labels[$index]} failed (exit $result)" >&2
    status=1
  fi
done
exit "$status"
