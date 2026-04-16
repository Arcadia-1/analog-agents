---
name: analog-evolve
description: >
  Self-evolution engine for analog-agents. Reviews completed design sessions to
  extract lessons, discover new anti-patterns, propose checklist additions, and
  refine agent prompts. Run after design convergence or project completion.
  TRIGGER on: "evolve", "what did we learn", "improve skills", "meta-review",
  "self-improve", or automatically at end of analog-pipeline.
---

# analog-evolve

Self-evolution engine. Reviews completed design sessions and improves
analog-agents' knowledge base, checklists, and prompts.

Inspired by the principle: every design session should make the next one smarter.

## When to Use

- After a sub-block converges (auto-suggested by analog-pipeline)
- After a project completes
- After a design fails and is abandoned (failure teaches more than success)
- Manually: `/analog-evolve review` to review the current session

## Evolution Dimensions

### 1. Wiki Enrichment — "What did we learn?"

Review `iteration-log.yml` and the design trajectory. For each sub-block:

**Extract lessons automatically:**
- Parameter changes that fixed a failing spec → candidate `strategy` entry
  - "Increasing L from 60n to 120n on mirror M3/M4 fixed the 15% current mismatch"
  - → `wiki/strategies/longer-l-for-mirror-matching.yml`

- Corner surprises (spec passed at TT, failed at SS/FF) → candidate `corner-lesson`
  - "Comparator offset 3x worse at SS/125C vs TT/27C"
  - → `wiki/corner-lessons/ss-corner-offset-blowup.yml`

- Design traps encountered during iteration → candidate `anti-pattern`
  - "CMFB on lower cascode device gave weak CM loop gain"
  - → `wiki/anti-patterns/cmfb-on-lower-cascode.yml`

- Successful topology + sizing for a block type → candidate `block-case`
  - Archive the converged design as a reference case

**Confidence escalation:**
- New entries start as `confidence: unverified`
- If a similar lesson is discovered in a second project, escalate to `verified`
- If a lesson contradicts a later finding, add `contradicts` edge

**Process:**
1. Read `iteration-log.yml` (full trajectory)
2. Read all `verifier-reports/` (what failed, what passed, what was marginal)
3. Read `circuit/rationale.md` (designer's reasoning)
4. Read cross-model review reports (if any)
5. For each potential entry:
   a. Check if a similar entry already exists in wiki (search by tags)
   b. If exists: update with new evidence, escalate confidence, add `validated` edge
   c. If new: create entry with `confidence: unverified`, add `derived_from` edge to project
6. Present proposed entries to user for approval before writing

### 2. Checklist Evolution — "What should we check next time?"

Analyze the design session for issues that SHOULD have been caught by a checklist
but weren't:

**Detection patterns:**
- Verifier pre-sim rejection that doesn't match any existing checklist item
  → propose new checklist entry
- Issue discovered only after 2+ iterations that could have been caught structurally
  → propose new checklist entry with `effort: lite`
- Cross-model reviewer flagged a risk not in any checklist
  → propose new checklist entry

**Process:**
1. Read all verifier rejection reports
2. For each rejection, check if it matches an existing checklist entry
3. Unmatched rejections → draft new checklist entries with full 7-field schema
4. Read cross-model review reports for topology risks flagged
5. Cross-check against `checklists/*.yml`
6. Present proposed entries to user, specify which checklist file they belong in

**Example output:**
```markdown
## Proposed Checklist Addition

**File:** checklists/folded-cascode.yml

```yaml
cmfb_control_device_sizing:
  description: "CMFB-controlled device must be wide enough for regulation authority"
  method: semantic
  severity: warn
  effort: standard
  auto_checkable: false
  references: [anti-003]
  how: >
    The CMFB-controlled device (usually upper PMOS in cascode load) acts as
    a variable current source. Its gate is set by the CMFB loop, not by fixed
    bias. Size it wide enough that CMFB can regulate across the full output CM
    range. Applying a fixed gm/Id target (e.g., gm/Id=10) can make it too
    narrow, starving load current and collapsing output CM.
```

**Reason:** This issue caused 2 extra iterations on the OTA sub-block.
The verifier rejected the netlist twice for output CM stuck at rail,
which was traced to undersized M7 (CMFB-controlled PMOS).
```

### 3. Prompt Refinement — "How should we instruct better?"

Analyze failure patterns across sessions to identify where agent prompts
could be improved:

**Detection patterns:**
- Designer repeatedly makes the same sizing mistake across projects
  → add a warning to `prompts/designer-prompt.md`
- Architect consistently underestimates noise budget
  → add a calibration note to `prompts/architect-prompt.md`
- Verifier misses a class of testbench errors
  → add to verifier's pre-sim review checklist in `prompts/verifier-prompt.md`

**Process:**
1. Review the session's failure trajectory
2. Identify root causes: was it a sizing error? testbench error? architecture error?
3. For each root cause, check if the relevant prompt already warns about it
4. If not: draft a specific addition to the prompt (exact text, exact location)
5. Present proposed prompt changes to user for approval

**Important:** prompt changes are PROPOSED, never auto-applied. The user
reviews and merges. This prevents prompt drift from accumulating noise.

### 4. Design Memory — "Remember this user's preferences"

Track user-specific design preferences that should persist across sessions:

- Preferred topologies ("always try folded cascode first for OTAs")
- Process-specific tricks ("in 28nm, use ulvt for input pair, lvt for everything else")
- Naming conventions ("use net_vbp for PMOS bias, net_vbn for NMOS bias")
- Effort preferences ("always use intensive for comparators")
- Review preferences ("skip qwen, it gives too many false positives on this process")

Storage: `wiki/user-preferences.yml` (gitignored with projects/)

```yaml
# user-preferences.yml — auto-discovered, user-confirmed
preferences:
  - category: topology
    rule: "Prefer folded cascode for single-stage OTA"
    discovered: 2026-04-16
    confirmed: true

  - category: process
    rule: "28nm: ulvt for input pair, lvt for mirrors and cascodes"
    discovered: 2026-04-16
    confirmed: true

  - category: effort
    rule: "Always use intensive effort for comparator blocks"
    discovered: 2026-04-16
    confirmed: false  # proposed, not yet confirmed
```

## Subcommands

| Command | Description |
|---------|-------------|
| `/analog-evolve review` | Review current session, propose all improvements |
| `/analog-evolve wiki` | Wiki enrichment only |
| `/analog-evolve checklist` | Checklist evolution only |
| `/analog-evolve prompts` | Prompt refinement only |
| `/analog-evolve preferences` | Extract user preferences only |
| `/analog-evolve status` | Show evolution history (what was proposed, accepted, rejected) |

## Integration with Pipeline

`analog-pipeline` auto-triggers `/analog-evolve review` at two points:
1. After each sub-block converges (lightweight: wiki + checklist only)
2. After project completion (full: all 4 dimensions)

Effort interaction:
| Effort | Evolution behavior |
|--------|-------------------|
| lite | Skipped |
| standard | Wiki enrichment only (lessons + anti-patterns) |
| intensive | Wiki + checklist evolution |
| exhaustive | All 4 dimensions + full narrative |

## Tool Backend

All evolution analysis is powered by `tools/evolve_engine.py`:

| Subcommand | Tool invocation |
|-----------|-----------------|
| `/analog-evolve review` | `python3 tools/evolve_engine.py review --project-dir . --wiki-dir wiki --checklists-dir checklists` |
| `/analog-evolve wiki` | `python3 tools/evolve_engine.py wiki --project-dir . --wiki-dir wiki` |
| `/analog-evolve checklist` | `python3 tools/evolve_engine.py checklist --project-dir . --checklists-dir checklists` |
| `/analog-evolve preferences` | `python3 tools/evolve_engine.py preferences --project-dir . --wiki-dir wiki` |
| `/analog-evolve status` | `python3 tools/evolve_engine.py status --wiki-dir wiki` |

The tool reads design artifacts (iteration-log.yml, verifier-reports/, rationale.md),
analyzes patterns, and outputs proposals in markdown. The skill (this SKILL.md)
provides the context and judgment for interpreting proposals and deciding what to accept.

## Principles

1. **Propose, never auto-apply.** All changes are presented to the user first.
   The only exception is `confidence` escalation on existing wiki entries
   (low-risk, evidence-based).

2. **Evidence-based.** Every proposal includes the specific design event that
   triggered it (iteration number, failing spec, measured value).

3. **Convergent, not divergent.** Evolution should make the system more precise,
   not more verbose. If a checklist already has 20 items for a topology, think
   twice before adding a 21st. Merge or refine existing items instead.

4. **Failure teaches more than success.** Pay more attention to failed iterations,
   abandoned designs, and escalation events than to smooth convergence.

5. **Cross-session learning.** When `/analog-wiki consult` returns entries with
   `confidence: unverified`, the current session's results can validate or
   invalidate them. This is how single-project observations become verified knowledge.
