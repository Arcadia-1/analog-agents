---
name: analog-decompose
description: >
  Architect Phase 1: decompose top-level analog spec into sub-block specs.
  Use when starting a new analog design to select architecture, allocate budgets,
  define sub-block specs, write testbenches, and create verification plans.
---

# analog-decompose

Architect Phase 1: architecture decomposition. Takes a top-level analog spec and
decomposes it into sub-block specs with budget allocation, testbenches, and
verification plans. This is the first design activity in the pipeline.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Top-level `spec.yml` | Working directory | yes |
| User constraints (architecture preference, area/power budget, etc.) | User | yes (can be empty) |
| Wiki consult results | `/analog-wiki consult` | no — used if `wiki/` has entries |
| Server name from `servers.yml` | Config | yes |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| `architecture.md` | `architect/architecture.md` | Architecture candidates, tradeoff analysis, selected architecture, block diagram |
| `budget.md` | `architect/budget.md` | Power/noise/timing budget allocation per sub-block |
| Sub-block `spec.yml` | `blocks/<name>/spec.yml` | Derived specs with derivation shown |
| Verification plans | `blocks/<name>/verification-plan.md` | What to verify, how, and pass/fail criteria per level |
| Testbench netlists | `blocks/<name>/testbench_<name>.scs` | Stimulus, load, bias, analysis statements per sub-block |

## Effort

Reference `shared-references/effort-contract.md` for the full effort contract.
Decomposition itself has no effort variation — the same thoroughness applies at
all effort levels. Effort affects downstream skills (behavioral validation,
iteration limits, review depth, etc.), not the architecture decomposition itself.

## Wiki Interaction

At the start of decomposition, if the `wiki/` directory contains entries, call:

    /analog-wiki consult <block-type>

This returns relevant topologies, sizing strategies, anti-patterns, and historical
project cases. Use these references to inform architecture selection and risk
assessment. Wiki consult is advisory — the architect makes the final decision.

No wiki writes happen during decomposition.

## Agent Template

Dispatch the architect agent using `prompts/architect-prompt.md`. Provide:

- Path to top-level `spec.yml`
- User constraints (architecture preference, area budget, power budget, etc.)
- Server: value of `role_mapping.architect` in `servers.yml` (or `default`)
- Wiki consult results (if available)

## Checklist Responsibility

The architect is responsible for setting the `checklists` field in each sub-block's
`spec.yml`. This field determines which pre-simulation checklists the verifier loads.

```yaml
# In blocks/<name>/spec.yml (set by architect):
checklists: [common, amplifier, folded-cascode, differential]
```

If the `checklists` field is absent, the verifier falls back to keyword matching
against the `block` field. Explicit assignment is preferred — see
`shared-references/checklist-schema.md` for the keyword-to-checklist mapping.

## Architecture Decomposition Rules

- **Every sub-block must have a clear, testable interface** — defined input/output signals with impedance/swing/timing specs
- **No circular dependencies** — block A's spec cannot depend on block B's implementation if B depends on A
- **Budget must close** — if individual block budgets don't sum to meet the top-level spec, the architecture is invalid. Iterate before proceeding.
- **Flag risks at block boundaries** — e.g., "comparator kickback will disturb DAC top plate — need isolation switch or timing guard"

## Spec Derivation Example (SAR ADC)

```
Top-level: 8-bit, 100MS/s, ENOB >= 7.5

Noise budget (thermal):
  Total kT/C noise < LSB/2 / 6.6sigma -> C_sample > 4kT / (V_LSB/6.6)^2
  Allocate: 70% to sampling cap, 20% to comparator, 10% to reference

Timing budget (100MS/s -> 10ns per conversion):
  Sampling phase: 3ns (30%)
  8 SAR cycles: 7ns -> 875ps per bit
    - DAC settling: 400ps
    - Comparator decision: 400ps
    - Logic delay: 75ps

Power budget (e.g., 2mW total):
  Comparator: 0.8mW (40%)
  DAC switching: 0.4mW (20%)
  SAR logic: 0.2mW (10%)
  Reference/bias: 0.6mW (30%)
```

Each sub-block `spec.yml` must show the derivation from top-level requirements,
not just state the number. The derivation is what makes the spec auditable.

## Testbench Writing Guidelines

The architect owns all testbenches. When writing testbenches, keep these common
pitfalls in mind — the verifier will check for them before simulating:

- **PSRR**: supply ripple must be applied with the input properly biased and output loaded; measure at the output, not an internal node
- **CMRR**: common-mode input must sweep while differential input is zero; watch for CMFB loop interaction
- **Phase margin**: loop must be broken at the correct point with correct replica loading; Middlebrook or STB analysis preferred over open-loop if feedback is complex
- **Noise**: check that the noise bandwidth and integration limits match the spec definition; spot noise vs integrated noise are different specs
- **Settling time**: input step must be realistic (not larger than linear range); measure to the correct accuracy band (e.g., 0.1% vs 1 LSB)
- **Power**: measure at steady state, not during startup transient

If the verifier rejects a testbench, fix the issue and resubmit. This is not a
design iteration — it is quality control on the architect's own work.

## Handoff Contract

Reference `shared-references/handoff-contracts.md` for the full handoff payload
requirements.

### Phase 1 Inputs (Top-level spec -> Architect)

| Field | Required |
|-------|----------|
| Top-level `spec.yml` path | yes |
| User constraints | yes (can be empty) |
| Server name from `servers.yml` | yes |

### Phase 1 Outputs (Architect returns)

| Artifact | Required |
|----------|----------|
| `architecture.md` with candidates, tradeoffs, selected architecture | yes |
| `budget.md` with power/noise/timing budgets that close | yes |
| `blocks/<name>/spec.yml` per sub-block with derived specs | yes |
| `blocks/<name>/verification-plan.md` per sub-block | yes |
| `blocks/<name>/testbench_<name>.scs` per sub-block | yes |

## Handoff Acceptance Criteria

Phase 1 is complete when:

- [ ] `architecture.md` documents candidates, tradeoffs, and selected architecture
- [ ] Every sub-block has `blocks/<name>/spec.yml` with derived specs and derivation shown
- [ ] Every sub-block has `blocks/<name>/verification-plan.md` defining what to verify and how
- [ ] `budget.md` shows power/noise/timing budgets close (sum meets top-level)
- [ ] Every sub-block `spec.yml` has the `checklists` field set
- [ ] No transistor-level design has been done (that is the designer's job)

## Scope

This skill covers Phase 1 only. Phase 2 (behavioral validation) is handled by
`/analog-behavioral`. Phase 3 (integration verification) is handled by
`/analog-integrate`.
