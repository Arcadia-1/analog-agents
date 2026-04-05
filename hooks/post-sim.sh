#!/usr/bin/env bash
# PostToolUse hook — fires after Bash calls matching spectre|virtuoso-bridge
# 1. Finds the most recent PSF output directory and runs spec check
# 2. Runs designer's custom per-block hook if present
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SPEC_YML="${REPO_ROOT}/spec.yml"
SIM_LOG="${REPO_ROOT}/sim-log.yml"

# Find the most recently modified .raw or psf directory
PSF_DIR=$(find "${REPO_ROOT}" -maxdepth 4 -type d \( -name "*.raw" -o -name "psf" \) \
  2>/dev/null | xargs ls -td 2>/dev/null | head -1)

if [ -z "${PSF_DIR}" ]; then
  exit 0  # No PSF output found, nothing to check
fi

# --- 1. Standard spec check (always runs) ---
python3 "${SCRIPT_DIR}/post_sim_check.py" "${PSF_DIR}" "${SPEC_YML}" "${SIM_LOG}"

# --- 2. Designer's custom per-block hook (if present) ---
# Look for post-sim-hook.py in any blocks/<name>/ directory that matches the PSF path
for BLOCK_DIR in "${REPO_ROOT}"/blocks/*/; do
  [ -d "$BLOCK_DIR" ] || continue
  BLOCK_NAME="$(basename "$BLOCK_DIR")"

  # Only run if this simulation is for this block (PSF path contains block name)
  if echo "${PSF_DIR}" | grep -q "${BLOCK_NAME}"; then
    CUSTOM_HOOK="${BLOCK_DIR}/post-sim-hook.py"
    if [ -f "$CUSTOM_HOOK" ]; then
      # Pass same args as standard check + block dir
      python3 "$CUSTOM_HOOK" "${PSF_DIR}" "${SPEC_YML}" "${SIM_LOG}" "${BLOCK_DIR}" || true
    fi
    break
  fi
done
