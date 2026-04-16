---
name: analog-integrate
description: >
  Architect Phase 3: replace behavioral models with verified transistor netlists
  and run top-level integration verification. Use after all sub-blocks pass L2.
---

# analog-integrate

Architect Phase 3 -- integration verification. After all sub-blocks pass L2
transistor-level verification, this skill replaces behavioral models with verified
netlists one by one, runs top-level integration checks at each step, and produces
the final integration verifier-report.

## Effort Gating

Corner matrix follows the same table as `/analog-verify`
(see `shared-references/effort-contract.md`):

| Effort | Corner matrix |
|--------|--------------|
| **lite** | TT 27C only |
| **standard** | TT + SS/125C + FF/-40C |
| **intensive** | 5 corners (TT/SS/FF/SF/FS) |
| **exhaustive** | Full PVT + MC (if mismatch models available, else full PVT) |

Print at startup:

    [effort: <level>] corners=<N>

## Inputs

| Artifact | Source |
|----------|--------|
| All verified sub-block `.scs` netlists (L2 pass) | Designer/verifier loop output |
| All sub-block `verifier-report.md` | Verifier output |
| `architecture.md` | `/analog-decompose` output |
| Top-level `spec.yml` | Project root |
| `blocks/*/behavioral.va` | `/analog-behavioral` output (used as replacement baseline) |

See `shared-references/handoff-contracts.md` section "Verified sub-blocks -> Architect
(analog-integrate)" for the full handoff payload:

| Field | Required |
|-------|----------|
| All sub-block `.scs` netlists (L2 pass) | yes |
| All sub-block `verifier-report.md` | yes |
| Server name from `servers.yml` | yes |

## Outputs

| Artifact | Location |
|----------|----------|
| Integration `verifier-report.md` | `verifier-reports/integration/verifier-report.md` |

The report includes per-spec results (measured / target / margin) for every top-level
spec across all corners at the current effort level.

## Integration Procedure

### 1. Replace Behavioral Models One by One

For each sub-block, in dependency order (inputs before outputs):

1. Replace `blocks/<name>/behavioral.va` with the verified `blocks/<name>/circuit/<block>.scs`
   in the system-level testbench.
2. Keep all other sub-blocks as behavioral models during this step.
3. Run top-level specs and verify no regression.
4. If a regression appears, the responsible sub-block is the one just replaced --
   flag it immediately before proceeding.

This incremental approach isolates integration failures to specific sub-blocks.

### 2. Run Top-Level Specs at Each Replacement Step

At each step, simulate the top-level specs from `spec.yml`:
- Compare against targets with measured / target / margin reporting.
- Any FAIL at this stage means the replaced sub-block's transistor implementation
  does not match its behavioral contract -- investigate the interface.

### 3. Final All-Transistor Verification

After all behavioral models are replaced:

1. Run the complete top-level spec suite with all transistor-level netlists.
2. Run across the corner matrix determined by the current effort level.
3. Document all results in the integration `verifier-report.md`.

## Failure Routing

When integration verification fails:

1. **Identify the responsible sub-block or interface**:
   - If failure appeared at a specific replacement step, that sub-block is suspect.
   - If failure appears only in the all-transistor run, it is likely an interface
     mismatch between adjacent blocks.

2. **Send back to design loop**:
   - Revise the interface constraints or sub-block spec as needed.
   - Dispatch the affected sub-block's designer with updated constraints.
   - The designer/verifier loop re-runs for that sub-block only.

3. **Architectural failure**: if multiple sub-blocks fail or the failure is systemic
   (e.g., power budget blown), escalate to `/analog-decompose` for architecture revision.

## Sign-Off Gate

**L3 PVT verification is required before delivery.**

Before the design can be delivered or migrated to Virtuoso:

1. Dispatch verifier with `level: L3` on the fully integrated design.
2. All top-level specs must pass across all corners defined in `spec.yml`.
3. If any corner fails:
   - Performance issue: return to designer for the affected sub-block.
   - Architectural issue: return to `/analog-decompose`.

Do not proceed to Virtuoso migration until L3 passes.

## Virtuoso Migration

After L3 sign-off, dispatch the designer agent with a Virtuoso migration task:

1. **Input**: path to the verified integrated netlist.
2. **Action**: designer migrates the netlist to a Virtuoso cellview and runs LVS.
3. **Server**: use `role_mapping.designer` from `servers.yml` (designer has Virtuoso
   write access).

The designer uses the `virtuoso` skill for schematic entry and LVS verification.

## Handoff Acceptance Criteria

Phase 3 is complete when (from `prompts/architect-prompt.md`):

- [ ] All behavioral models replaced with transistor-level netlists
- [ ] Top-level specs verified with all-transistor integration testbench
- [ ] Integration `verifier-report.md` written with per-spec margins

## Lessons Learned

At project completion (after the sign-off gate passes), the architect reviews
`iteration-log.yml` and writes the `summary.lessons_learned` section. This is a
first-class activity, not an afterthought. Focus on insights that would change
future designs:

- Specs where behavioral model prediction diverged significantly from transistor-level
- Budget allocations that were too tight or too generous
- Verification conditions that were repeatedly flagged as incorrect
- Corner-specific surprises (e.g., "SS corner offset 3x worse than TT prediction")
- Optimizer usage patterns (which blocks needed it, which didn't)

At **exhaustive** effort, the architect also writes a retrospective narrative:
"What emerged that could not have been predicted?" This reflection captures tacit
knowledge that structured logs cannot.

These lessons are the most valuable output of the entire flow -- they make the next
project's architect smarter. At effort >= standard, consider pushing lessons to
`/analog-wiki` via `archive-project`.

## References

- `prompts/architect-prompt.md` -- Phase 3 section and Lessons Learned section
- `shared-references/handoff-contracts.md` -- handoff payload requirements
- `shared-references/effort-contract.md` -- corner matrix and effort dimensions
