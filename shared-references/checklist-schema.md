# Checklist Schema

## Field Specification

Every checklist entry has 7 fields:

```yaml
<check_name>:
  description: "One-line description"
  method: structural | estimate | semantic
  severity: error | warn
  effort: lite | standard | intensive | exhaustive
  auto_checkable: true | false
  references: []
  how: >
    Procedure description
```

### Fields

- **description**: One sentence. What this check catches.
- **method**: How the check is performed.
  - `structural` — parseable from netlist text (connections, ratios, sizing)
  - `estimate` — computable from netlist + process assumptions (Vth~0.3V, Vdsat~0.1V)
  - `semantic` — requires design-intent reasoning (feedback polarity, compensation strategy)
- **severity**: What happens on failure.
  - `error` — blocks simulation (verifier must reject)
  - `warn` — flags concern, simulation proceeds
- **effort**: Minimum effort level that triggers this check. `lite` = always runs.
- **auto_checkable**: Metadata flag. `true` if a script could verify this programmatically. No automated engine exists yet — this is for future tooling.
- **references**: List of wiki entry IDs related to this check. Populated incrementally as the wiki grows. Empty list `[]` is valid.
- **how**: Step-by-step procedure for performing the check.

## Checklist Loading

### Explicit (preferred)

Architect sets the `checklists` field in each sub-block's `spec.yml`:

```yaml
checklists: [common, amplifier, folded-cascode, differential]
```

Verifier loads `checklists/<name>.yml` for each listed name.

### Fallback: Keyword Matching

If `checklists` field is absent, match the `block` field against this table:

| Keyword in block name | Checklists loaded |
|-----------------------|-------------------|
| ota, opamp, amplifier, gain | common, amplifier |
| folded, cascode (+ amplifier match) | common, amplifier, folded-cascode |
| differential, fully-differential | common, differential |
| comparator, strongarm, latch | common, comparator |
| mirror, bias, current-source | common, current-mirror |
| bandgap, reference | common, bandgap |
| pll, vco, oscillator | common, pll |
| adc, sar, pipeline, sigma-delta | common, adc |
| ldo, regulator | common, ldo |

`common.yml` is always loaded.

## Execution Modes

### Guided Mode (effort lite / standard)

Execute checklist items sequentially. Check each item, report result.
Appropriate for unfamiliar topologies.

### Expert Mode (effort intensive / exhaustive)

1. Agent performs holistic circuit review first — forms own assessment
2. THEN uses checklist as retrospective validation: "did my review miss
   anything on this list?"
3. Order: whole-first, parts-second

This preserves integrated understanding (Polanyi: decomposing into
subsidiary particulars destroys focal awareness of the whole).
