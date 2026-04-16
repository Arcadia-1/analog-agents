---
name: analog-pipeline
description: >
  MANDATORY — MUST load this skill when the user mentions: OTA, ADC, PLL, comparator,
  bandgap, LDO, amplifier, opamp, or any analog/mixed-signal IC design task.
  Full analog design pipeline: spec -> architecture -> design -> verify -> deliver.
  Orchestrates analog-decompose, analog-behavioral, analog-design, analog-review,
  analog-verify, analog-integrate, and analog-wiki skills.
---

# analog-pipeline

Lightweight orchestrator for the full analog design pipeline. Sequences skill
invocations, manages global state, and maintains `iteration-log.yml`. Does NOT
dispatch agents directly, run simulations, or write netlists — only decides
"which skill next" and "record what happened."

## When to Use

Use this skill when:
- Starting a new analog circuit block from a top-level spec
- Designing a complex block that requires sub-block decomposition (ADC, PLL, etc.)
- Iterating on an existing netlist that is failing specs
- Preparing a verified netlist for Virtuoso migration

Do NOT use for:
- Verilog-A behavioral modeling only — use `veriloga` skill
- Virtuoso schematic editing without a netlist — use `virtuoso` skill

All circuit simulation and performance verification in this workflow are owned by
the **verifier** agent, including simulation of existing netlists.

## Required Input

Before invoking any agent, confirm these exist:

1. **`spec.yml`** in the working directory (see spec format below) — OR use functional defaults
2. `servers.yml` configured (copy from `config/servers.example.yml` and fill in)

### No spec.yml? Use functional defaults

If `spec.yml` is missing or the user just wants the circuit to "work", do NOT block
on creating a detailed spec. Instead, auto-generate a minimal `spec.yml` with
**L1 functional defaults** for that block type:

| Block type | Functional defaults |
|------------|-------------------|
| Amplifier/OTA | All transistors in saturation (region <= 2), positive DC gain, output CM near target |
| Comparator | Correct polarity output, resolves within the evaluation window, and reports input-referred offset when measurable |
| ADC | Correct digital codes for ramp input |
| Oscillator | Oscillation at roughly target frequency |
| Any block | DC operating point converges, no rail-stuck nodes, current balance at fold/mirror nodes |

The auto-generated spec uses the process nominal supply (e.g., 0.9V for 28nm, 1.1V for
65nm, 1.8V for 180nm) and only L1 functional checks. The orchestrator proceeds
immediately — no user confirmation needed for functional defaults.

When the user later provides quantitative targets (gain >= 60dB, UGBW >= 500MHz, etc.),
upgrade to a full `spec.yml` with L2/L3 specs.

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

## Effort

Read `shared-references/effort-contract.md` for the full effort contract.

At startup, read the active effort level using the three-layer priority:

1. Command-line `--effort`
2. Project config `config/effort.yml` (with optional per-block overrides)
3. Default: `standard`

Print the active effort level and parameters at startup:

    [effort: intensive] corners=5, max_iter=5, reviewers=2, wiki=lesson+strategy

## The Workflow

```
top-level spec.yml
        |
        +--------------------------------------+
        v                                      v
  librarian (background, optional)   architect agent (Phase 1)
  +-- select architecture, tradeoff analysis
  +-- decompose into sub-blocks
  +-- derive sub-block specs (budget allocation)
  +-- output: architecture.md + budget.md + blocks/*/spec.yml
        |
        v
  architect agent (Phase 2)
  +-- build Verilog-A behavioral model per sub-block
  +-- system-level behavioral simulation
  +-- verify top-level specs met at behavioral level
        |
        v
  +---------------------------------------------+
  |  For each sub-block:                        |
  |                                             |
  |    designer agent --> verifier agent         |
  |         ^                   |               |
  |         +------ FAIL -------+               |
  |                                             |
  |    (max iterations per effort level)        |
  +---------------------------------------------+
        |
        v
  architect agent (Phase 3)
  +-- replace behavioral models with verified netlists
  +-- integration testbench: top-level specs
  +-- output: integration verifier-report.md
        |
        v
  sign-off gate --> L3 PVT required
        |
        v
  designer agent: migrate to Virtuoso
```

## Orchestration Flow

The pipeline sequences the following skill invocations:

1. **`/analog-wiki consult`** — if `wiki/` directory has entries, consult for architecture references and known anti-patterns
2. **`/analog-decompose`** — architect Phase 1: decompose top-level spec into sub-block specs, write testbenches, create verification plans
3. **User gate** — confirm architecture with user before proceeding. User may override architecture choice.
4. **`/analog-behavioral`** — architect Phase 2: behavioral validation (effort >= standard; skipped at lite)
5. **For each sub-block**: `/analog-design` -> `/analog-review` (effort >= standard; skipped at lite) -> `/analog-verify`, loop until convergence or iteration limit
6. **`/analog-integrate`** — architect Phase 3: replace behavioral models with verified netlists, run integration verification
7. **L3 sign-off** — verifier must complete L3 PVT on the integrated design; all specs must pass across all corners
8. **`/analog-wiki archive-project`** — extract cases from iteration-log.yml, prompt architect for narrative.md (effort >= standard)
9. **Reflection narrative** — architect writes retrospective: "what emerged that could not have been predicted?" (effort = exhaustive only)

## Agent Dispatch Rules

**All agents must be dispatched in the background (`run_in_background: true`).**
The orchestrator never blocks on an agent. This enables two modes:

### 1. Parallel sub-block dispatch

When multiple sub-blocks are independent, dispatch their designer (or verifier)
agents simultaneously in a single message with multiple Agent tool calls:

```
Sub-blocks A, B, C are independent ->
  dispatch designer-A, designer-B, designer-C in one message, all background
  -> as each completes, dispatch its verifier in background
  -> as each verifier completes, architect reviews
```

### 2. Non-blocking sequential dispatch

Even for a single sub-block, dispatch in background so the orchestrator can:
- Prepare the next sub-block's spec while the current one is being designed
- Discuss with the user while simulation runs
- Review iteration-log.yml or update documentation

The orchestrator is notified automatically when a background agent completes —
do not poll or sleep.

Operational exception: the orchestrator MAY inspect remote Spectre job state at any time
for observability and debugging, for example with `virtuoso-bridge sim-jobs` (and
`virtuoso-bridge sim-cancel <id>` if a stuck job must be terminated). This is only for
simulation job monitoring; it must not replace agent-completion notifications or become
the primary synchronization mechanism between agents.

### Verifier dispatch rule

**CRITICAL: When dispatching a verifier, always include this instruction in the prompt:**
"You are a verifier. Do NOT modify any .scs netlist files. Only run simulations and
report results. If the circuit doesn't work, report the failure — do not fix it."

The orchestrator must NOT run simulations directly — always dispatch a verifier agent.

## Verification Levels

| Level | When | Corners | Purpose |
|-------|------|---------|---------|
| **L1 Functional** | default, every iteration | TT 27C nominal | Does the circuit perform its basic function? |
| **L2 Performance** | when L1 passes, before claiming convergence | TT 27C nominal | Do all specs meet targets at typical? |
| **L3 Robustness** | mandatory before delivery | Full corner matrix from spec.yml | Do specs hold across all PVT corners? |

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
        verification_redo: false
        results:
          - spec: offset
            target: "< 1mV"
            measured: 0.8mV
            margin: +0.2mV
            status: pass
        outcome: fail

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
```

### Who Writes What

| Field | Written by |
|-------|-----------|
| `iterations[].designer_changes` | orchestrator, from designer's `rationale.md` diff |
| `iterations[].optimizer_used/config` | orchestrator, from designer's report |
| `iterations[].verification_redo` | orchestrator, when verifier rejects pre-simulation |
| `iterations[].results` | orchestrator, from verifier's `verifier-report.md` |
| `summary.lessons_learned` | architect, at project completion |

The orchestrator appends to `iteration-log.yml` after every handoff. Agents read it
for context but do not modify past entries.

## Project Directory Structure

Each project (or sub-block in a multi-block system) follows this layout.
Agent outputs are organized by owner — each agent writes only to its own area.

```
<project>/
+-- spec.yml                          # architect: top-level or sub-block spec
+-- servers.yml                       # config: simulation server connection
+-- iteration-log.yml                 # orchestrator: full iteration history
|
+-- architect/                        # architect output
|   +-- architecture.md               # topology selection, block diagram, interfaces
|   +-- budget.md                     # power/noise/timing budget allocation
|   +-- verification-plan.md          # what to verify and how (per level)
|   +-- behavioral.va                 # Verilog-A behavioral model (if applicable)
|
+-- circuit/                          # designer output
|   +-- <block>.scs                   # transistor-level netlist (primary)
|   +-- <block>_open_cmfb.scs         # variant with exposed CMFB node (debug)
|   +-- rationale.md                  # sizing justification, change log per iteration
|
+-- testbench/                        # architect output (stimulus + analysis setup)
|   +-- tb_<block>_dcop.scs           # DC operating point
|   +-- tb_<block>_ac.scs             # AC frequency response
|   +-- tb_<block>_tran.scs           # transient step response
|   +-- tb_<block>_stb.scs            # stability (loop gain / phase margin)
|
+-- verifier-reports/                 # verifier output
|   +-- L1-functional/
|   |   +-- dc-op-point.md
|   |   +-- <date>_<description>.md
|   +-- L2-performance/
|       +-- <date>_<description>.md
|
+-- librarian/                        # librarian output (optional)
|   +-- survey-report.md
|   +-- library-index.md
|
+-- sim_raw/                          # simulation output (auto, gitignored)
+-- plots/                            # generated plots (auto)
```

## Simple Blocks (Single Sub-block)

For simple blocks that don't need decomposition (e.g., a standalone comparator or bias
circuit), the architect phase can be lightweight:
- Phase 1: document the topology choice and key design equations in `architecture.md`
- Phase 2: skip behavioral modeling if the block is simple enough
- Phase 3: skip integration (there's only one block)

The orchestrator may skip architect entirely for trivial blocks if the user agrees.

## Related Skills

| Skill | Purpose |
|-------|---------|
| `/analog-decompose` | Architect Phase 1: decompose top-level spec into sub-block specs |
| `/analog-behavioral` | Architect Phase 2: behavioral validation with Verilog-A models |
| `/analog-design` | Designer: transistor-level netlist for one sub-block |
| `/analog-review` | Cross-model circuit audit with divergence analysis |
| `/analog-verify` | Verifier: pre-sim review + Spectre simulation |
| `/analog-integrate` | Architect Phase 3: integration verification |
| `/analog-wiki` | Knowledge graph: consult, add, archive design knowledge |
