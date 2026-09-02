#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENDORED_INSTALLER="$SCRIPT_DIR/../.agents/skills/scripts/install_ctf_tools.sh"

mode=""
dry_run=false
for argument in "$@"; do
  case "$argument" in
    --dry-run) dry_run=true ;;
    --force) ;;
    python|apt|brew|gems|go|manual|all|--verify)
      if [[ -n "$mode" ]]; then
        echo "Multiple installer modes are not allowed: $mode and $argument" >&2
        exit 2
      fi
      mode="$argument"
      ;;
    *)
      echo "Unknown installer argument: $argument" >&2
      exit 2
      ;;
  esac
done
mode="${mode:-all}"

vendored_output="$(mktemp "${TMPDIR:-/tmp}/lee-ctf-installer.XXXXXX")"
trap 'rm -f -- "$vendored_output"' EXIT
set +e
bash "$VENDORED_INSTALLER" "$@" 2>&1 | tee "$vendored_output"
vendored_status=${PIPESTATUS[0]}
set -e

if [[ "$dry_run" == false && ( "$mode" == "python" || "$mode" == "all" ) ]]; then
  ctf_venv="${CTF_VENV:-$HOME/.ctf-tools/venv}"
  if [[ -x "$ctf_venv/bin/python" ]]; then
    "$ctf_venv/bin/python" -m pip install -r "$SCRIPT_DIR/ctf-python-compat.txt"
  fi
fi

if [[ "$mode" == "python" && "$vendored_status" -ne 0 ]]; then
  bash "$VENDORED_INSTALLER" python
  exit $?
fi

if [[ "$mode" == "all" && "$vendored_status" -ne 0 ]]; then
  mapfile -t failed_packages < <(sed -n 's/^   - //p' "$vendored_output")
  only_unavailable_sagemath=true
  if (( ${#failed_packages[@]} == 0 )); then
    only_unavailable_sagemath=false
  fi
  for package in "${failed_packages[@]}"; do
    if [[ "$package" != "apt:sagemath" ]]; then
      only_unavailable_sagemath=false
    fi
  done
  if [[ "$only_unavailable_sagemath" == true ]]; then
    echo "WARNING: vendored all-mode could not install SageMath; validating the required 58-item baseline." >&2
    set +e
    verify_output="$(bash "$VENDORED_INSTALLER" --verify 2>&1)"
    verify_status=$?
    set -e
    printf '%s\n' "$verify_output"
    if [[ "$verify_status" -eq 0 ]] && grep -Eq '^Missing: 0 tools/modules\r?$' <<<"$verify_output"; then
      echo "WARNING: continuing with the complete baseline; SageMath remains challenge-local/on demand." >&2
      exit 0
    fi
  fi
fi

exit "$vendored_status"
