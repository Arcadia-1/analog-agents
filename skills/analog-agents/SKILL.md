---
name: analog-agents
description: >
  AI-native analog frontend design collaboration. Invoke when designing an analog
  circuit block end-to-end: spec → netlist → simulation → tape-out. Dispatches
  designer and verifier agents with defined roles, convergence loop, and sign-off gate.
---

# analog-agents

Two-agent analog design framework. A **designer** produces the netlist; a **verifier**
checks it against specs via simulation. They iterate until all specs pass, then the
designer tapes out to Virtuoso.

## When to Use

Use this skill when:
- Starting a new analog circuit block from a spec sheet
- Iterating on an existing netlist that is failing specs
- Preparing a verified netlist for Virtuoso migration (tape-out)

Do NOT use for:
- Pure simulation tasks on an existing verified netlist → use `spectre` skill directly
- Verilog-A behavioral modeling → use `veriloga` skill
- Virtuoso schematic editing without a netlist → use `virtuoso` skill

## Required Input

Before invoking any agent, confirm these exist:

1. **`spec.yml`** in the working directory (see spec format below)
2. A starting netlist (`.scs`) OR agreement that designer will create one from scratch
3. `servers.yml` configured (copy from `config/servers.example.yml` and fill in)

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
spec.yml  ──►  designer agent
                   │
          ┌────────┴────────┐
          ▼                 ▼
    verifier agent    (designer documents rationale)
          │
          ▼
    all specs pass?
    ├── NO  → margin report → designer → revise → repeat
    └── YES
          │
    sign-off gate ──► L3 PVT required
          │
          ▼
    designer agent: tape-out → Virtuoso
```

## Dispatch Instructions

### Step 1 — Dispatch designer (first iteration or after spec failure)

Use the `designer-prompt.md` template. Provide:
- Path to `spec.yml`
- Path to current netlist (or "create from scratch")
- Margin report from last verifier run (empty on first iteration)
- Server: value of `role_mapping.designer` in `servers.yml` (or `default`)

### Step 2 — Dispatch verifier (after designer delivers netlist)

Use the `verifier-prompt.md` template. Provide:
- Path to `spec.yml`
- Path to netlist produced by designer
- Verification level: L1 (default), L2, or L3
- Server: value of `role_mapping.verifier` in `servers.yml` (or `default`)

### Step 3 — Convergence decision

Read the margin report returned by verifier.

- If any spec FAILS: dispatch designer again with the margin report. Increment iteration counter.
- If all specs PASS at L1/L2: proceed to sign-off check.
- **Maximum iterations:** warn user after 5 iterations without convergence. Do not loop indefinitely.

### Step 4 — Sign-off gate

Before tape-out, verifier MUST complete L3 PVT. If not yet run:
- Dispatch verifier with level: L3
- All specs must pass across all corners
- If any corner fails, return to designer

### Step 5 — Tape-out

Dispatch designer with tape-out instruction:
- Input: verified netlist path
- Action: migrate netlist to Virtuoso cellview + run LVS
- Server: `role_mapping.designer` (designer has Virtuoso write access)

## Verification Levels

| Level | When | Corners | Purpose |
|-------|------|---------|---------|
| **L1 Functional** | default, every iteration | TT 27°C nominal | Basic operating point check |
| **L2 Spec** | when L1 passes, before claiming convergence | TT 27°C nominal | All spec targets at typical |
| **L3 PVT** | mandatory before tape-out | Full corner matrix from spec.yml | Robustness across PVT |

## Output Artifacts

After a complete run, the working directory contains:

| File | Owner | Content |
|------|-------|---------|
| `<block>.scs` | designer | Final verified netlist |
| `rationale.md` | designer | Hand-calc sizing justification |
| `testbench_<block>.scs` | verifier | Testbench used for simulation |
| `sim-log.yml` | hook (auto) | Full simulation history with margins |
| `margin-report.md` | verifier | Latest margin summary (human-readable) |
