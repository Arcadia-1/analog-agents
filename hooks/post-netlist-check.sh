#!/usr/bin/env bash
# PostToolUse hook — fires after Write/Edit on .scs/.sp/.net files
# Runs spectre -check for syntax validation (if spectre is available)
set -euo pipefail

FILE="${TOOL_INPUT_FILE_PATH:-}"

# Only act on netlist files
[[ "$FILE" =~ \.(scs|sp|net)$ ]] || exit 0

# Skip if file doesn't exist (was deleted)
[ -f "$FILE" ] || exit 0

# Try spectre -check for syntax validation
if command -v spectre &>/dev/null; then
  RESULT=$(spectre -check "$FILE" 2>&1) || true
  if echo "$RESULT" | grep -qi "error"; then
    echo "{\"additionalContext\": \"[analog-agents] Netlist syntax error in ${FILE}:\\n$(echo "$RESULT" | grep -i error | head -5 | sed 's/"/\\\\"/g')\"}"
  else
    echo "{\"additionalContext\": \"[analog-agents] Netlist syntax check passed: ${FILE}\"}"
  fi
else
  # No local spectre — try remote via virtuoso-bridge
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

  if [ -f "${REPO_ROOT}/servers.yml" ] || [ -f "${REPO_ROOT}/config/servers.yml" ]; then
    # Remote check available but we don't run it automatically (too slow for a hook)
    # Just remind the user
    echo "{\"additionalContext\": \"[analog-agents] Netlist written: ${FILE}. Run spectre -check or use the spectre skill to validate syntax before simulation.\"}"
  fi
fi
