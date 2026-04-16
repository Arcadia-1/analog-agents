# EDA Modes

analog-agents operates in two modes based on EDA tool availability.

## Detecting Mode

Check for `servers.yml` (or `config/servers.yml`). If present and reachable: **full mode**.
If absent or unreachable: **review mode**.

Users can also force a mode:
- In `config/effort.yml`: add `eda_mode: review` or `eda_mode: full`
- Command-line: `--eda-mode review`

## Full Mode (EDA available)

The complete loop: design -> simulate -> iterate -> sign-off -> Virtuoso migration.

All skills work at full capacity. `analog-verify` runs Spectre simulations.
`analog-integrate` does transistor-level integration verification.

## Review Mode (no EDA)

The design loop becomes: design -> cross-model review -> hand-calc validation -> iterate.

| Skill | Full Mode | Review Mode |
|-------|-----------|-------------|
| **analog-pipeline** | Full orchestration | Skips simulation steps, uses review as primary gate |
| **analog-decompose** | No change | No change |
| **analog-behavioral** | Runs Verilog-A simulation | Skips (no simulator). Architect validates architecture with hand calculations only |
| **analog-design** | Produces netlist + rationale | No change -- netlist is a text file, no EDA needed |
| **analog-verify** | Pre-sim review + Spectre simulation + margin report | **Review-only**: pre-sim checklist + hand-calc cross-validation + design equation audit. No simulation. Reports estimated specs from hand calculations, not measured values |
| **analog-integrate** | Replaces behavioral with transistor, runs integration sim | **Skipped**. Integration verification deferred to when EDA becomes available |
| **analog-review** | Optional quality gate | **Primary quality gate** -- effort auto-escalated: if review mode AND effort < intensive, treat as intensive |
| **analog-wiki** | No change | No change |

## Review-Mode Verify: What It Does

Without simulation, `analog-verify` in review mode:

1. Runs all applicable checklists (structural + estimate + semantic per effort)
2. Cross-validates designer's hand calculations:
   - DC gain: gm1 / (gds_n + gds_p) from sizing
   - UGBW: gm1 / (2*pi*CL)
   - Phase margin: estimate from pole locations
   - Headroom: stack Vdsat from supply to ground
   - Power: sum branch currents * VDD
3. Produces an **estimated margin report** (clearly marked as "ESTIMATED -- not simulated"):

| Spec | Estimated | Target | Margin | Confidence |
|------|-----------|--------|--------|------------|
| dc_gain | ~55 dB | >= 60 dB | -5 dB | low (hand-calc) |

4. Flags specs that CANNOT be estimated from hand calculations (e.g., settling time, PSRR)
5. Convergence decision based on estimated specs + cross-model review consensus

## Review-Mode Pipeline Flow

```
spec.yml
    |
    v
  /analog-decompose (unchanged)
    |
    v
  /analog-behavioral (SKIPPED -- no simulator)
    |
    v
  for each sub-block:
    /analog-design -> /analog-review (auto-escalated) -> /analog-verify (review-only)
    loop based on review feedback + estimated specs
    |
    v
  /analog-integrate (SKIPPED -- no simulator)
    |
    v
  deliverable: reviewed netlist + rationale + estimated specs
  (ready for simulation when EDA becomes available)
```

## Review-Mode Exclusive Skills

These skills work ONLY in review mode (or standalone) and do not require EDA:

| Skill | Purpose |
|-------|---------|
| `/analog-learn` | Step-by-step design teaching with physics explanations |
| `/analog-explore` | Architecture comparison, parameter sweeps, feasibility checks |
| `/analog-audit` | Comprehensive static audit of existing netlists |

These skills are always available regardless of mode, but they are especially
valuable in review mode where simulation is not an option.

## Deliverable in Review Mode

The output is a **review-verified design package**:
- Circuit netlist (.scs) -- ready to simulate
- rationale.md -- hand-calc justification for every parameter
- Cross-model review report -- independent audit from multiple LLMs
- Estimated margin report -- hand-calc spec estimates with confidence levels
- Checklist results -- all applicable checks passed

This package can be handed to someone WITH EDA to run through the simulation
loop (analog-verify full mode + analog-integrate) without re-doing the design.
