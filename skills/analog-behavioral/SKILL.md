---
name: analog-behavioral
description: >
  Architect Phase 2: build Verilog-A behavioral models and validate system architecture.
  Use after analog-decompose to verify top-level specs are achievable before transistor design.
---

# analog-behavioral

Architect Phase 2 -- behavioral validation. After `/analog-decompose` produces the
architecture and sub-block specs, this skill builds Verilog-A behavioral models for
each sub-block, runs system-level simulation, and confirms the top-level specs are
achievable before committing to transistor-level design.

## Effort Gating

Read effort level per `shared-references/effort-contract.md`. Print at startup:

    [effort: <level>] behavioral=<mode>

| Effort | Behavioral validation |
|--------|----------------------|
| **lite** | Skip entirely -- return immediately with "skipped by effort level" |
| **standard** | Quick check: key specs only (e.g., gain, bandwidth for amplifier; ENOB for ADC) |
| **intensive** | Full: all top-level specs verified at behavioral level |
| **exhaustive** | Full + sensitivity sweep (vary each sub-block parameter +/-10%, report spec degradation) |

## Inputs

| Artifact | Source |
|----------|--------|
| `architecture.md` | `/analog-decompose` output |
| `blocks/*/spec.yml` | `/analog-decompose` output (one per sub-block) |
| Top-level `spec.yml` | Project root |

All inputs are required. Do not proceed if `architecture.md` or any sub-block
`spec.yml` is missing.

## Outputs

| Artifact | Location |
|----------|----------|
| Verilog-A behavioral model per sub-block | `blocks/<name>/behavioral.va` |
| System-level testbench | `testbench_system.scs` (or equivalent) |
| Behavioral simulation results | Documented in console output with quantified margins |

## Procedure

### 1. Build Verilog-A Behavioral Models

For each sub-block defined in `architecture.md`:

1. Read `blocks/<name>/spec.yml` to understand the sub-block's interface and specs.
2. Use the `veriloga` skill to write `blocks/<name>/behavioral.va`.
3. The model must capture key non-idealities relevant to system performance:
   - **Amplifier/OTA**: finite gain, bandwidth, slew rate, output swing limits
   - **Comparator**: offset, decision delay, metastability region
   - **DAC**: INL/DNL, settling time, glitch energy
   - **ADC sub-blocks**: quantization, sampling jitter
   - **Oscillator**: phase noise, frequency pulling
4. Use the `evas-sim` skill to verify each behavioral model individually against
   its sub-block spec before system integration.

### 2. System-Level Behavioral Simulation

1. Create a system-level testbench that instantiates all behavioral models together
   according to the connectivity in `architecture.md`.
2. Use the `evas-sim` skill to run system-level simulation:
   - For ADC: FFT-based ENOB/SNDR measurement
   - For PLL: lock time, phase noise, loop stability
   - For amplifier chains: end-to-end gain, bandwidth, noise
   - For data converters: full signal-chain INL/DNL
3. Compare results against top-level `spec.yml` targets.
4. Document results with measured value, target, and margin for every spec.

### 3. Sensitivity Sweep (exhaustive only)

At exhaustive effort, sweep each sub-block's key parameters +/-10% and report:
- Which top-level specs degrade and by how much
- Which sub-blocks are the tightest bottleneck
- Recommended margin allocation adjustments for `budget.md`

## Gate: Behavioral Validation Must Pass

If behavioral simulation fails any top-level spec:

1. Identify which sub-block(s) or budget allocation caused the failure.
2. Return to `/analog-decompose` to revise the architecture or budget.
3. Do NOT proceed to transistor-level design with a broken architecture.

This gate prevents wasting design effort on an architecture that cannot meet spec.

## Handoff Acceptance Criteria

Phase 2 is complete when (from `prompts/architect-prompt.md`):

- [ ] Every sub-block has `blocks/<name>/behavioral.va` that passes individual test
- [ ] System-level behavioral simulation meets top-level specs
- [ ] Results documented with quantified margins

## Reference

See `prompts/architect-prompt.md` Phase 2 section for the full architect prompt
covering behavioral model requirements and system-level testbench construction.
