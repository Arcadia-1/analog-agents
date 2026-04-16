# CMFB & Common-Mode Reference — Fully Differential Amplifiers

## Input Common-Mode vs Output Common-Mode

Fully differential OTA has TWO independent common-mode voltages:

- **Vcm_in** (input CM): set by the previous stage or external bias. Determines input pair headroom.
- **Vcm_out** (output CM): set by CMFB. Can be different from Vcm_in.

### Input pair type determines valid Vcm_in range

| Input type | Valid Vcm_in | Why |
|-----------|-------------|-----|
| **PMOS** | **Low** (near VSS) | Vsg = net_tail - Vcm_in. Low Vcm → large Vsg → tail has headroom at VDD side |
| **NMOS** | **High** (near VDD) | Vgs = Vcm_in - net_tail. High Vcm → large Vgs → tail has headroom at VSS side |

### Headroom calculation (do this BEFORE choosing Vcm_in)

**PMOS input example** (VDD = 0.9V):
```
Vcm_in = 0.2V
|Vsg_M1| ≈ 0.4V → net_tail = 0.2 + 0.4 = 0.6V
|Vds_tail| = VDD - net_tail = 0.9 - 0.6 = 0.3V ✓ (enough headroom)
```

**Wrong: Vcm_in = 0.45V** (VDD/2):
```
net_tail = 0.45 + 0.4 = 0.85V
|Vds_tail| = 0.9 - 0.85 = 0.05V ❌ (tail in triode!)
```

### Output CM is independent

Vcm_out is set by CMFB, typically at VDD/2 for maximum output swing. It does NOT need
to equal Vcm_in. The CMFB adjusts the load transistor bias to achieve the target Vcm_out
regardless of Vcm_in.

## Why CMFB

Fully differential OTA has no inherent mechanism to set the output common-mode voltage.
Without CMFB, the output CM drifts to a rail. CMFB closes a negative feedback loop
around the output CM to hold it at a reference value.

## CMFB Topologies

### 1. Resistive sensing + mirror-load error amp (recommended baseline)

```
VOUTP ──[R]──┬── net_cm_sense ──[Mcm1]──┐
VOUTN ──[R]──┘                           ├── net_cmfb → PMOS load gate
                    Vcm_ref ────[Mcm2]──┘
```

- **Pros**: simple, continuous-time, robust startup
- **Cons**: R loads the output (reduces gain if R too small), R noise
- **Sizing**: R ≥ 10× Rout of OTA to avoid gain degradation. Typically 100k–500k.
- **Error amp**: use mirror-load (NOT diode-load, see trap below)

### 2. Dual cross-coupled differential pairs (no resistor)

Two diff pairs sense VOUTP and VOUTN directly against Vcm_ref.
Drains summed through shared current mirror load.

- **Pros**: no resistor loading, no R noise
- **Cons**: limited linear range, can saturate at large output swings
- **When to use**: when output swing is moderate and R loading is unacceptable

### 3. Switched-capacitor CMFB (SC-CMFB)

Capacitors sample output CM, compare with reference via charge redistribution.

- **Pros**: no DC loading, high precision, natural for SC circuits
- **Cons**: needs clock, charge injection, clock feedthrough
- **When to use**: switched-cap applications (SAR ADC, pipeline ADC, S/H)
- **Simulation**: CANNOT use AC analysis. Must use transient only.

### 4. Partial CMFB (bias split)

Split PMOS load into fixed-bias (50%) + CMFB-controlled (50%).

- **Pros**: better CM stability (lower CM loop gain), reliable startup
- **Cons**: CM regulation slower (half the control authority)
- **When to use**: complex topologies where CM oscillation is a concern, or startup problems
- **Note**: total gds unchanged if total W is same, so DM gain is NOT affected

## CMFB Error Amplifier Variants

| Type | CM Gain | Speed | Mirror pole? | Notes |
|------|---------|-------|-------------|-------|
| Mirror-load diff pair | High | Moderate | Yes | Standard, recommended |
| Diode-load diff pair | Low | Fast | No | **TRAP: kills DM gain if output directly drives high-Z node** |
| Single-stage inverter | High gm | Fast | No | Eats headroom |
| Folded | Wide input range | Slow | Possibly | Overkill for most CMFB |

### Diode-load CMFB Trap

If the CMFB error amp uses diode-connected loads and its output directly connects
to the main OTA's PMOS load gate (a high-impedance node), the diode converts that
node to low impedance → PMOS load becomes diode-connected → DM gain collapses.

Measured: 23 dB → 2.6 dB with diode-load CMFB on a 5T FD OTA.

**Fix**: use mirror-load, or buffer/AC-couple the diode-load output before connecting
to the main signal path.

## CMFB Polarity Check

Before connecting CMFB, verify negative feedback polarity:

1. Assume Vcm_out increases
2. Trace through CMFB: does net_cmfb change to REDUCE Vcm_out?
   - For PMOS load: net_cmfb should RISE → |Vsg| decreases → less PMOS current → output drops ✓
3. If polarity is wrong, swap Mcm1/Mcm2 gate connections

## CM Loop Stability

The CMFB loop has its own gain, bandwidth, and phase margin. Must verify separately:

- Use STB analysis with probe at net_cmfb (break CM loop)
- CM phase margin target: ≥ 45°
- If CM oscillation: reduce CMFB gain (e.g., switch to partial CMFB or diode-load)

## CMFB and PSRR/CMRR Simulation

In ideal simulation (no mismatch), fully differential output perfectly cancels CM/supply
perturbation → PSRR/CMRR shows -600 dB (numerical floor). This is meaningless.

**Must use Monte Carlo / dcmatch** for meaningful PSRR/CMRR on fully differential OTAs.
