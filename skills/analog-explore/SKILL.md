---
name: analog-explore
description: >
  Explore analog design space without simulation. Compare topologies, sweep
  parameters with hand calculations, find theoretical limits and Pareto tradeoffs.
  Use for architecture selection, initial sizing, or understanding design space
  before committing to EDA time. TRIGGER on: "compare topologies", "explore",
  "design space", "what are my options", "tradeoff analysis", "Pareto".
---

# analog-explore

Design space exploration through hand calculations. No EDA required.
Rapidly evaluate architectures, sweep parameters, and map tradeoff surfaces
before committing simulation time.

## When to Use

- Choosing between architectures before detailed design
- Understanding theoretical limits of a topology
- Quick parameter sensitivity analysis
- Generating initial sizing for multiple candidates
- Estimating feasibility of a spec before starting design

## Capabilities

### Architecture Comparison

Compare 2-4 candidate topologies for a given spec:

```
/analog-explore compare --spec spec.yml --topologies "folded-cascode, telescopic, two-stage-miller"
```

For each topology, estimate from hand calculations:
- Achievable gain (intrinsic gain × number of gain stages)
- Bandwidth (gm/CL for single-stage, GBW for multi-stage)
- Power (minimum current for gm requirement × VDD)
- Output swing (VDD minus Vdsat stack)
- Noise (input-referred: 8kT/(3gm) × noise factor)
- Area (rough: proportional to total W×L)

Output: comparison table + recommendation with reasoning.

```markdown
## Architecture Comparison — OTA for 60dB gain, 500MHz UGBW

| Metric | Folded Cascode | Telescopic | Two-Stage Miller |
|--------|---------------|------------|-----------------|
| Gain   | ~55-70 dB     | ~60-80 dB  | ~70-90 dB       |
| UGBW   | gm1/CL        | gm1/CL     | gm1/Cc          |
| Power  | 2× (folded)   | 1× (base)  | 2× (two stages) |
| Swing  | VDD - 4Vdsat  | VDD - 4Vdsat| VDD - 2Vdsat   |
| Noise  | moderate      | best       | moderate         |
| Risk   | CMFB needed   | limited Vcm| compensation     |

Recommendation: Folded cascode. 60dB is achievable in single stage with cascode,
avoids compensation complexity of two-stage, and handles flexible Vcm.
Telescopic has better noise but Vcm range is too restrictive for this application.
```

### Parameter Sweep (Hand-Calc)

Sweep a design parameter and estimate its effect on all specs:

```
/analog-explore sweep --param "W_input:1u,2u,4u,8u,16u" --spec spec.yml --topology folded-cascode
```

For each value, calculate: gm, gm/Id, gain contribution, bandwidth impact,
noise contribution, power, headroom.

Output: sweep table showing tradeoff surface.

```markdown
## Parameter Sweep — W_input (folded cascode, Id_tail=200uA)

| W_input | gm/Id | gm (mS) | Gain (dB) | UGBW (MHz) | Noise (nV/rtHz) | Headroom |
|---------|-------|---------|-----------|------------|-----------------|----------|
| 1u      | 8     | 0.8     | 48        | 127        | 5.6             | OK       |
| 2u      | 11    | 1.1     | 52        | 175        | 4.8             | OK       |
| 4u      | 15    | 1.5     | 55        | 239        | 4.1             | OK       |
| 8u      | 19    | 1.9     | 57        | 302        | 3.6             | tight    |
| 16u     | 23    | 2.3     | 58        | 366        | 3.3             | FAIL     |

Observation: W=4u-8u is the sweet spot. Beyond 8u, gm/Id enters weak inversion
(>20), headroom collapses, and gain improvement diminishes.
```

### Feasibility Check

Quick spec feasibility without full design:

```
/analog-explore feasibility --spec spec.yml
```

For each spec, estimate the minimum resource (current, area, bandwidth) needed:
- Gain: how many gain stages? What intrinsic gain per stage?
- Bandwidth: minimum gm for target UGBW? Minimum current for that gm?
- Noise: minimum gm (and thus current) for noise floor?
- Power: sum of minimum currents × VDD
- Settling: minimum UGBW for settling spec?

Flag impossible specs: "60dB gain AND 2GHz UGBW in 180nm with 0.5mW — NOT FEASIBLE.
Gain requires cascode (limits speed), UGBW requires high gm (requires high current)."

Output: feasibility report with go/no-go per spec and minimum resource estimates.

### Sensitivity Analysis

Which parameter has the biggest impact on which spec?

```
/analog-explore sensitivity --netlist circuit/ota.scs --spec spec.yml
```

Perturb each .param by ±20%, re-derive all specs from hand calculations.
Output: sensitivity matrix.

```markdown
| Param  | dc_gain | ugbw  | phase_margin | noise | power |
|--------|---------|-------|-------------|-------|-------|
| W1     | +0.3    | +0.5  | -0.1        | -0.4  | 0     |
| L1     | +0.8    | -0.6  | +0.2        | +0.1  | 0     |
| Ibias  | +0.1    | +0.5  | +0.3        | -0.5  | +1.0  |
| Cc     | 0       | -0.3  | +0.9        | 0     | 0     |

(Normalized elasticity: +1.0 means +20% param → +20% spec)
```

## Wiki Interaction

- Calls `/analog-wiki consult` for topology reference data
- Writes `strategy` entries when a sweep reveals non-obvious tradeoffs
- Writes `corner-lesson` entries when feasibility check reveals process-dependent limits

## Effort Interaction

Not effort-gated. Exploration is always available.

## Output

All outputs go to `explore/` directory:
- `explore/comparison-<date>.md` — architecture comparison
- `explore/sweep-<param>-<date>.md` — parameter sweep
- `explore/feasibility-<date>.md` — spec feasibility report
- `explore/sensitivity-<date>.md` — sensitivity matrix
