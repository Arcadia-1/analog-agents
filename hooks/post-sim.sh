#!/usr/bin/env bash
# PostToolUse hook — fires after Bash calls matching spectre|virtuoso-bridge
# Finds the most recent PSF output directory and runs spec check.
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

python3 "${SCRIPT_DIR}/post_sim_check.py" "${PSF_DIR}" "${SPEC_YML}" "${SIM_LOG}"
