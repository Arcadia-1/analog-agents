# Handoff Contracts

Every agent handoff must include the required payload. An incomplete handoff
is not a valid handoff — do not dispatch the next agent until all items are present.

## Top-level spec -> Architect (analog-decompose)

| Field | Required |
|-------|----------|
| Top-level `spec.yml` path | yes |
| User constraints | yes (can be empty) |
| Server name from `servers.yml` | yes |

Architect returns: `architecture.md` + `budget.md` + sub-block `spec.yml` files + `verification-plan.md` per sub-block + testbench netlists

## Architect -> Designer (analog-design, per sub-block)

| Field | Required |
|-------|----------|
| Sub-block `spec.yml` path | yes |
| Behavioral model `.va` path | yes |
| Interface constraints from `architecture.md` | yes |
| Netlist path or "create from scratch" | yes |
| `verifier-report.md` from last verifier run | yes (empty on first iteration) |
| Server name from `servers.yml` | yes |

Designer returns: `<block>.scs` + `rationale.md`

## Circuit + Testbench -> Verifier (analog-verify)

| Field | Required |
|-------|----------|
| `<block>.scs` path (designer's circuit) | yes |
| `testbench_<block>.scs` path (architect's testbench) | yes |
| Sub-block `spec.yml` path | yes |
| `verification-plan.md` path | yes |
| Verification level (L1 / L2 / L3) | yes |
| Server name from `servers.yml` | yes |

Verifier first reviews both files. Rejection routes to designer (circuit) or architect (testbench). If approved, runs simulation and returns `verifier-report.md`.

## Verifier FAIL -> Designer (loop)

Feedback must be actionable:
- Which spec, which corner, measured value, target, shortfall
- Suggested cause (e.g., "compensation cap too small")

Designer response must update `rationale.md` explaining what changed and why.

## 3x FAIL escalation -> Architect

Escalate with:
- All 3 verifier reports showing trajectory
- Designer's rationale explaining what was attempted
- Architect decides: revise sub-block spec, change topology, or escalate to user

## Verified sub-blocks -> Architect (analog-integrate)

| Field | Required |
|-------|----------|
| All sub-block `.scs` netlists (L2 pass) | yes |
| All sub-block `verifier-report.md` | yes |
| Server name from `servers.yml` | yes |

Architect returns: integration `verifier-report.md` with top-level specs
