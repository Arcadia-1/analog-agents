#!/usr/bin/env bash
# PostToolUse hook — fires after Write/Edit on .scs/.sp/.net files
# 1. Runs spectre -check for syntax validation (if spectre is available)
# 2. Records .param changes to iteration-log.yml
set -euo pipefail

FILE="${TOOL_INPUT_FILE_PATH:-}"

# Only act on netlist files
[[ "$FILE" =~ \.(scs|sp|net)$ ]] || exit 0

# Skip if file doesn't exist (was deleted)
[ -f "$FILE" ] || exit 0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- 1. Syntax check ---

if command -v spectre &>/dev/null; then
  RESULT=$(spectre -check "$FILE" 2>&1) || true
  if echo "$RESULT" | grep -qi "error"; then
    SYNTAX_MSG="[analog-agents] Netlist syntax error in ${FILE}:\\n$(echo "$RESULT" | grep -i error | head -5 | sed 's/"/\\\\"/g')"
  else
    SYNTAX_MSG="[analog-agents] Netlist syntax check passed: ${FILE}"
  fi
else
  if [ -f "${REPO_ROOT}/servers.yml" ] || [ -f "${REPO_ROOT}/config/servers.yml" ]; then
    SYNTAX_MSG="[analog-agents] Netlist written: ${FILE}. Run spectre -check or use the spectre skill to validate syntax before simulation."
  else
    SYNTAX_MSG=""
  fi
fi

# --- 2. Record param changes to iteration-log.yml ---

LOG_FILE="${REPO_ROOT}/iteration-log.yml"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BLOCK_NAME="$(basename "$(dirname "$FILE")")"
FILE_BASENAME="$(basename "$FILE")"

# Use git diff to detect .param / parameters line changes
PARAM_DIFF=""
if command -v git &>/dev/null && git -C "$(dirname "$FILE")" rev-parse --git-dir &>/dev/null 2>&1; then
  # Diff staged or unstaged changes for this file
  PARAM_DIFF=$(git diff HEAD -- "$FILE" 2>/dev/null | grep -E '^[-+].*(parameters |\.param )' | grep -v '^[-+][-+][-+]' || true)
fi

if [ -n "$PARAM_DIFF" ]; then
  # Extract removed (-) and added (+) param lines
  OLD_PARAMS=$(echo "$PARAM_DIFF" | grep '^-' | sed 's/^-//' | head -20)
  NEW_PARAMS=$(echo "$PARAM_DIFF" | grep '^+' | sed 's/^+//' | head -20)

  # Append change record to iteration-log
  {
    echo ""
    echo "# --- netlist change recorded by hook ---"
    echo "- timestamp: \"${TIMESTAMP}\""
    echo "  file: \"${FILE_BASENAME}\""
    echo "  block: \"${BLOCK_NAME}\""
    echo "  param_removed:"
    if [ -n "$OLD_PARAMS" ]; then
      echo "$OLD_PARAMS" | while IFS= read -r line; do
        echo "    - \"$(echo "$line" | sed 's/"/\\"/g')\""
      done
    else
      echo "    []"
    fi
    echo "  param_added:"
    if [ -n "$NEW_PARAMS" ]; then
      echo "$NEW_PARAMS" | while IFS= read -r line; do
        echo "    - \"$(echo "$line" | sed 's/"/\\"/g')\""
      done
    else
      echo "    []"
    fi
  } >> "$LOG_FILE"

  CHANGE_MSG="[analog-agents] Param changes in ${FILE_BASENAME} recorded to iteration-log.yml"
else
  CHANGE_MSG=""
fi

# --- Output combined message ---

MSG=""
[ -n "$SYNTAX_MSG" ] && MSG="$SYNTAX_MSG"
[ -n "$CHANGE_MSG" ] && MSG="${MSG:+${MSG}\\n}${CHANGE_MSG}"

if [ -n "$MSG" ]; then
  echo "{\"additionalContext\": \"${MSG}\"}"
fi
