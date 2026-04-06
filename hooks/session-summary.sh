#!/usr/bin/env bash
# Stop hook — generates session-summary.md when the session ends
# Captures: what was done, current spec status, next steps
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SUMMARY_FILE="session-summary.md"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")

# --- Collect data ---

# Current spec.yml block name
BLOCK="unknown"
if [ -f "spec.yml" ]; then
  BLOCK=$(python3 -c "import yaml; print(yaml.safe_load(open('spec.yml')).get('block','unknown'))" 2>/dev/null || echo "unknown")
fi

# Latest sim-log entry
SIM_STATUS="No simulations recorded"
SIM_DETAIL=""
if [ -f "sim-log.yml" ]; then
  SIM_STATUS=$(python3 -c "
import yaml
log = yaml.safe_load(open('sim-log.yml')) or []
if log:
    last = log[-1]
    print(f\"{last.get('status','?')} — {last.get('netlist','?')} @ {last.get('corner','?')} (Level {last.get('level','?')})\")
else:
    print('No simulations recorded')
" 2>/dev/null || echo "Could not parse sim-log.yml")

  # Count iterations
  SIM_DETAIL=$(python3 -c "
import yaml
log = yaml.safe_load(open('sim-log.yml')) or []
total = len(log)
passes = sum(1 for e in log if e.get('status') == 'PASS')
fails = sum(1 for e in log if e.get('status') == 'FAIL')
print(f'{total} simulations: {passes} PASS, {fails} FAIL')
" 2>/dev/null || echo "")
fi

# Recent git commits (this session)
RECENT_COMMITS=$(git log --oneline -5 2>/dev/null || echo "No git history")

# Files modified
MODIFIED_FILES=$(git diff --name-only HEAD~5 HEAD 2>/dev/null | head -10 || echo "Could not determine")

# --- Write summary ---
cat > "$SUMMARY_FILE" << EOF
# Session Summary — ${BLOCK}

**Timestamp:** ${TIMESTAMP}

## Current Status

**Latest simulation:** ${SIM_STATUS}
${SIM_DETAIL:+**Overall:** ${SIM_DETAIL}}

## Recent Commits

\`\`\`
${RECENT_COMMITS}
\`\`\`

## Files Modified

\`\`\`
${MODIFIED_FILES}
\`\`\`

## Next Steps

<!-- Auto-generated. Edit manually if needed. -->
- [ ] Review margin-report.md for failing specs
- [ ] If all specs pass at L2: run L3 PVT verification
- [ ] If L3 passes: migrate to Virtuoso
EOF

echo "{\"additionalContext\": \"[analog-agents] Session summary written to ${SUMMARY_FILE}\"}"
