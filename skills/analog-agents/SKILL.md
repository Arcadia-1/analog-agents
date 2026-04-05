---
name: analog-agents
description: >
  AI-native analog frontend design collaboration. Invoke when designing an analog
  circuit block end-to-end: spec → architecture → netlist → simulation → tape-out.
  Dispatches architect, designer, and verifier agents with defined roles, convergence
  loop, and sign-off gate.
---

# analog-agents

Three-agent analog design framework. An **architect** decomposes the system and validates
the architecture with behavioral models; a **designer** produces transistor-level netlists;
a **verifier** checks them against specs via simulation. They iterate until all specs pass,
then the designer tapes out to Virtuoso.

## When to Use

Use this skill when:
- Starting a new analog circuit block from a top-level spec
- Designing a complex block that requires sub-block decomposition (ADC, PLL, etc.)
- Iterating on an existing netlist that is failing specs
- Preparing a verified netlist for Virtuoso migration (tape-out)

Do NOT use for:
- Pure simulation tasks on an existing verified netlist → use `spectre` skill directly
- Verilog-A behavioral modeling only → use `veriloga` skill
- Virtuoso schematic editing without a netlist → use `virtuoso` skill

## Required Input

Before invoking any agent, confirm these exist:

1. **`spec.yml`** in the working directory (see spec format below)
2. `servers.yml` configured (copy from `config/servers.example.yml` and fill in)

If `spec.yml` is missing, ask the user to define it first. Do not proceed without specs.

## Spec Sheet Format

```yaml
block: <circuit-block-name>
version: 1.0
process: <pdk-name>
supply: <nominal-supply-voltage>

specs:
  <spec_name>: { min: <value>, unit: <unit> }   # lower bound
  <spec_name>: { max: <value>, unit: <unit> }   # upper bound

corners:                        # required for L3 PVT only
  - { name: tt_27c, process: tt, voltage: 1.8, temp: 27 }
  - { name: ss_125c, process: ss, voltage: 1.62, temp: 125 }
```

## Server Configuration

Read `servers.yml`. Use `role_mapping` if present. If absent, use `default` for all roles.
Each agent prompt specifies which role it is — resolve the server from role_mapping at dispatch time.

## The Workflow

```
top-level spec.yml
        │
        ▼
  architect agent (Phase 1)
  ├── select architecture, tradeoff analysis
  ├── decompose into sub-blocks
  ├── derive sub-block specs (budget allocation)
  └── output: architecture.md + budget.md + blocks/*/spec.yml
        │
        ▼
  architect agent (Phase 2)
  ├── build Verilog-A behavioral model per sub-block
  ├── system-level behavioral simulation
  └── verify top-level specs met at behavioral level
        │
        ▼
  ┌─────────────────────────────────────────┐
  │  For each sub-block:                    │
  │                                         │
  │    designer agent ──► verifier agent    │
  │         ▲                   │           │
  │         └───── FAIL ────────┘           │
  │                                         │
  │    (max 3 iterations per sub-block)     │
  └─────────────────────────────────────────┘
        │
        ▼
  architect agent (Phase 3)
  ├── replace behavioral models with verified netlists
  ├── integration testbench: top-level specs
  └── output: integration margin-report.md
        │
        ▼
  sign-off gate ──► L3 PVT required
        │
        ▼
  designer agent: tape-out → Virtuoso
```

## Dispatch Instructions

### Step 0 — Dispatch architect (Phase 1: decomposition)

Use the `architect-prompt.md` template. Provide:
- Path to top-level `spec.yml`
- User constraints (architecture preference, area/power budget, etc.)
- Server: value of `role_mapping.architect` in `servers.yml` (or `default`)

Architect returns: `architecture.md`, `budget.md`, sub-block `spec.yml` files.

**Gate**: Review architecture with user before proceeding. User may override architecture choice.

### Step 0.5 — Dispatch architect (Phase 2: behavioral validation)

After architecture is approved, dispatch architect again to:
- Build Verilog-A behavioral models for each sub-block
- Run system-level behavioral simulation
- Confirm top-level specs are achievable

**Gate**: If behavioral simulation fails top-level specs, architect must revise architecture
or budget allocation. Do not proceed to transistor-level design with a broken architecture.

### Step 1 — Dispatch designer (per sub-block)

Use the `designer-prompt.md` template. Provide:
- Path to sub-block `spec.yml` (from `blocks/<name>/spec.yml`)
- Behavioral model `.va` as reference
- Interface constraints from `architecture.md`
- Path to current netlist (or "create from scratch")
- Margin report from last verifier run (empty on first iteration)
- Server: value of `role_mapping.designer` in `servers.yml` (or `default`)

### Step 2 — Dispatch verifier (per sub-block)

Use the `verifier-prompt.md` template. Provide:
- Path to sub-block `spec.yml`
- Path to netlist produced by designer
- Verification level: L1 (default), L2, or L3
- Server: value of `role_mapping.verifier` in `servers.yml` (or `default`)

### Step 3 — Convergence decision (per sub-block)

After the verifier returns a margin report, dispatch the **architect to review** before
making any pass/fail decision. The architect follows a two-step review:

**Step 3a — Architect audits verification conditions**

Architect checks every spec's testbench setup, stimulus, and measurement method against
the verification plan. If any condition is wrong (e.g., PSRR measured without proper
supply modulation, CMRR with incorrect stimulus):
- Architect flags the issue and sends the verifier back to redo with corrections
- This is a **verification redo**, NOT a design iteration — do not increment the designer loop counter

**Step 3b — Architect evaluates results**

Only after verification conditions are confirmed correct:
- If any spec FAILS: architect forwards the margin report to designer with actionable feedback. Increment iteration counter.
- If all specs PASS at L1/L2: mark sub-block as converged.
- **Maximum iterations: 3 per sub-block.** If specs still fail after 3 designer→verifier loops,
  architect decides: revise sub-block spec, change topology, or escalate to user.

### Step 4 — Dispatch architect (Phase 3: integration)

After all sub-blocks converge at L2, dispatch architect for integration:
- Replace behavioral models with verified transistor-level netlists
- Run top-level integration testbench
- Verify all top-level specs

If integration fails: architect identifies which sub-block or interface is the cause,
revises constraints, and sends the affected sub-block back to designer→verifier loop.

### Step 5 — Sign-off gate

Before tape-out, verifier MUST complete L3 PVT on the integrated design:
- Dispatch verifier with level: L3
- All specs must pass across all corners
- If any corner fails, return to designer (or architect if it's architectural)

### Step 6 — Tape-out

Dispatch designer with tape-out instruction:
- Input: verified integrated netlist path
- Action: migrate netlist to Virtuoso cellview + run LVS
- Server: `role_mapping.designer` (designer has Virtuoso write access)

## Simple Blocks (Single Sub-block)

For simple blocks that don't need decomposition (e.g., a standalone comparator or bias
circuit), the architect phase can be lightweight:
- Phase 1: document the topology choice and key design equations in `architecture.md`
- Phase 2: skip behavioral modeling if the block is simple enough
- Phase 3: skip integration (there's only one block)

The orchestrator may skip architect entirely for trivial blocks if the user agrees.

## Verification Levels

| Level | When | Corners | Purpose |
|-------|------|---------|---------|
| **L1 Functional** | default, every iteration | TT 27°C nominal | Does the circuit perform its basic function? |
| **L2 Performance** | when L1 passes, before claiming convergence | TT 27°C nominal | Do all specs meet targets at typical? |
| **L3 Robustness** | mandatory before tape-out | Full corner matrix from spec.yml | Do specs hold across all PVT corners? |

### L1 — Functional Verification

L1 answers: **"Does this circuit do what it's supposed to do at all?"**

This is NOT just a DC operating point check. L1 includes whatever analyses are needed
to confirm basic functionality:

- **ADC**: give it an input signal → does it produce correct digital output codes?
- **Comparator**: positive input > negative → output high; reverse → output low?
- **Bootstrap switch**: clock arrives → does the sampled voltage track the input?
- **Amplifier**: AC gain is positive and reasonable? Transient output follows input?
- **PLL/oscillator**: does it oscillate at roughly the right frequency?

L1 always includes `.op` (to check operating regions), but also `.tran` and/or `.ac`
as needed to confirm the block's fundamental function works.

The architect defines the L1 functional checks in `verification-plan.md`.

## Handoff Contracts

Every agent handoff must include the required payload. An incomplete handoff is not a
valid handoff — do not dispatch the next agent until all items are present.

### Top-level spec → Architect

| Field | Required |
|-------|----------|
| Top-level `spec.yml` path | ✓ |
| User constraints | ✓ (can be empty) |
| Server name from `servers.yml` | ✓ |

Architect must return: `architecture.md` + `budget.md` + sub-block `spec.yml` files + `verification-plan.md` per sub-block

### Architect → Designer (per sub-block)

| Field | Required |
|-------|----------|
| Sub-block `spec.yml` path | ✓ |
| Behavioral model `.va` path | ✓ |
| Interface constraints from `architecture.md` | ✓ |
| Netlist path or "create from scratch" | ✓ |
| `margin-report.md` from last verifier run | ✓ (empty on first iteration) |
| Server name from `servers.yml` | ✓ |

Designer must return: `<block>.scs` + `rationale.md`

### Netlist → Verifier

| Field | Required |
|-------|----------|
| `<block>.scs` path | ✓ |
| Sub-block `spec.yml` path | ✓ |
| `verification-plan.md` path | ✓ |
| Verification level (L1 / L2 / L3) | ✓ |
| Server name from `servers.yml` | ✓ |

Verifier must return: `margin-report.md` with quantified margins per spec per corner

### Verifier FAIL → Designer (loop)

Verifier feedback must be actionable — not just "phase_margin failed" but:
- Which spec, which corner, measured value, target, shortfall
- Suggested cause (e.g., "compensation cap too small")

Designer response must update `rationale.md` explaining what changed and why.

### 3× FAIL escalation → Architect

If a sub-block fails 3 iterations, escalate to architect with:
- All 3 margin reports showing the trajectory
- Designer's rationale explaining what was attempted
- Architect decides: revise sub-block spec, change topology, or escalate to user

### Verified sub-blocks → Architect (integration)

| Field | Required |
|-------|----------|
| All sub-block `.scs` netlists (L2 pass) | ✓ |
| All sub-block `margin-report.md` | ✓ |
| Server name from `servers.yml` | ✓ |

Architect must return: integration `margin-report.md` with top-level specs

## Iteration Log

The orchestrator maintains `iteration-log.yml` at the project root. Every agent handoff
appends an entry. This log is the single source of truth for what happened during the
design process.

### Format

```yaml
project: <top-level block name>
started: <ISO timestamp>
architecture: <selected architecture>

blocks:
  <block-name>:
    iterations:
      - iteration: 1
        timestamp: <ISO>
        designer_changes:
          - param: W1
            from: null       # first iteration
            to: 10u
            reason: "gm/Id = 15 target for noise spec"
        optimizer_used: false
        verification_level: L1
        verification_redo: false    # architect didn't flag condition errors
        results:
          - spec: offset
            target: "< 1mV"
            measured: 0.8mV
            margin: +0.2mV
            status: pass
          - spec: delay
            target: "< 500ps"
            measured: 620ps
            margin: -120ps
            status: fail
        outcome: fail          # at least one spec failed

      - iteration: 2
        timestamp: <ISO>
        designer_changes:
          - param: W_input_pair
            from: 10u
            to: 6u
            reason: "reduce Cgs to recover 120ps delay, accept slight noise increase"
        optimizer_used: false
        verification_level: L2
        verification_redo: true
        verification_redo_reason: "PSRR testbench missing supply decoupling — architect flagged"
        results:
          - spec: offset
            target: "< 1mV"
            measured: 1.1mV
            margin: -0.1mV
            status: fail
          - spec: delay
            target: "< 500ps"
            measured: 480ps
            margin: +20ps
            status: pass
        outcome: fail

      - iteration: 3
        timestamp: <ISO>
        designer_changes:
          - param: W_input_pair
            from: 6u
            to: 8u
            reason: "optimizer found Pareto optimum balancing offset vs delay"
          - param: Ibias
            from: 50u
            to: 65u
            reason: "optimizer co-optimized with W_input_pair"
        optimizer_used: true
        optimizer_config:
          params_swept: [W_input_pair, Ibias, L_load]
          iterations: 40
          best_cost: 0.02
        verification_level: L2
        verification_redo: false
        results:
          - spec: offset
            target: "< 1mV"
            measured: 0.7mV
            margin: +0.3mV
            status: pass
          - spec: delay
            target: "< 500ps"
            measured: 450ps
            margin: +50ps
            status: pass
        outcome: pass

    total_iterations: 3
    total_verification_redos: 1
    optimizer_invocations: 1
    converged: true
    final_level: L2

summary:
  total_blocks: 4
  total_iterations: 11
  total_verification_redos: 2
  optimizer_invocations: 1
  escalations_to_user: 0
  lessons_learned:
    - "comparator offset at SS corner was 2.8x worse than TT — budget 3x margin next time"
    - "PSRR testbench consistently missing supply decoupling — add to verification-plan template"
```

### Who Writes What

| Field | Written by |
|-------|-----------|
| `iterations[].designer_changes` | orchestrator, from designer's `rationale.md` diff |
| `iterations[].optimizer_used/config` | orchestrator, from designer's report |
| `iterations[].verification_redo` | orchestrator, when architect flags condition error |
| `iterations[].results` | orchestrator, from verifier's `margin-report.md` |
| `summary.lessons_learned` | architect, at project completion |

The orchestrator appends to `iteration-log.yml` after every handoff. Agents read it
for context but do not modify past entries.

## Output Artifacts

After a complete run, the working directory contains:

| File | Owner | Content |
|------|-------|---------|
| `architecture.md` | architect | Architecture selection, block diagram, interfaces |
| `budget.md` | architect | Power/noise/timing budget allocation |
| `iteration-log.yml` | orchestrator | Full iteration history with parameters, results, lessons |
| `blocks/<name>/spec.yml` | architect | Per-sub-block derived specs |
| `blocks/<name>/verification-plan.md` | architect | What to verify and how |
| `blocks/<name>/behavioral.va` | architect | Verilog-A behavioral model |
| `blocks/<name>/<name>.scs` | designer | Verified transistor-level netlist |
| `blocks/<name>/rationale.md` | designer | Sizing justification |
| `blocks/<name>/trend.png` | designer | Optimization trend plot (designer writes the script) |
| `blocks/<name>/margin-report.md` | verifier | Latest margin summary |
| `testbench_system.scs` | architect | System-level integration testbench |
| `sim-log.yml` | hook (auto) | Full simulation history with margins |
