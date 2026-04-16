---
name: analog-audit
description: >
  Audit an existing analog circuit netlist for correctness, quality, and risks.
  Works without EDA — pure static analysis with checklists, hand calculations,
  and cross-model review. Use when reviewing someone else's design, checking a
  legacy netlist, or doing design review before tapeout.
  TRIGGER on: "audit", "review netlist", "check this circuit", "design review",
  "is this netlist correct", "review this .scs".
---

# analog-audit

Static audit service for analog circuit netlists. No EDA required.
Combines checklists, hand-calculation verification, cross-model review,
and wiki anti-pattern matching into a comprehensive audit report.

## When to Use

- Reviewing a colleague's netlist before simulation
- Checking a legacy design for known issues
- Pre-tapeout design review without re-running all sims
- Understanding an unfamiliar netlist's quality and risks

## Input

Minimum: a .scs netlist file.

Optional (improve audit quality):
- `rationale.md` — designer's sizing justification
- `spec.yml` — target specifications
- `verifier-reports/` — existing simulation results to cross-check

## Audit Process

```
Input netlist
    |
    v
  1. Topology identification
     Parse structure, identify: diff pairs, mirrors, cascodes, CMFB, etc.
     Classify: "This is a folded-cascode fully-differential OTA with resistive CMFB"
    |
    v
  2. Checklist execution
     Auto-detect applicable checklists from topology identification
     Run all checks at full depth (all methods: structural + estimate + semantic)
     Flag every issue with severity
    |
    v
  3. Hand-calculation audit
     Extract all .param values
     Re-derive key specs from first principles:
       - DC gain, UGBW, phase margin, noise, power, headroom, output swing
     Compare against rationale.md (if provided) — flag discrepancies
     Compare against spec.yml (if provided) — flag potential violations
    |
    v
  4. Anti-pattern scan
     Match topology against wiki/anti-patterns/
     For each match: explain the risk and check if this netlist is affected
    |
    v
  5. Cross-model review
     Send to configured reviewers (per effort level)
     Collect divergence analysis
    |
    v
  6. Audit report
     verifier-reports/audit-report.md
```

## Audit Report Format

```markdown
# Circuit Audit — <netlist> — <date>

## Circuit Summary
- **Topology**: folded-cascode fully-differential OTA
- **Process**: 28nm (inferred from model includes)
- **Devices**: 14 MOSFETs, 2 resistors, 1 capacitor
- **Supply**: 0.9V
- **Estimated power**: 360uA × 0.9V = 324uW

## Checklist Results
Checklists applied: common, amplifier, folded-cascode, differential

| Check | Severity | Result | Detail |
|-------|----------|--------|--------|
| floating_nodes | error | PASS | |
| bulk_connections | error | PASS | |
| mirror_ratio_vs_comment | error | FAIL | M3/M4 ratio 4:1 but comment says 5:1 |
| input_pair_type_vs_vcm | error | PASS | PMOS input, Vcm=0.2V, headroom OK |
| cmfb_polarity | error | PASS | Negative feedback confirmed |
| ...  | | | |

**Result: 1 ERROR, 2 WARNINGS out of 23 checks**

## Hand-Calculation Audit

| Spec | Estimated | Spec Target | Status | Notes |
|------|-----------|-------------|--------|-------|
| DC gain | ~58 dB | >= 60 dB | MARGINAL | gm1=1.2mS, Rout~950k |
| UGBW | ~190 MHz | >= 200 MHz | MARGINAL | gm1/CL, CL=1pF |
| Phase margin | ~65 deg | >= 60 deg | OK | Single dominant pole |
| Power | 324 uW | <= 500 uW | OK | 360uA total |
| Output swing | ±350 mV | >= ±300 mV | OK | 4×Vdsat headroom |

## Anti-Pattern Scan
- [anti-001] **Diode-Load CMFB**: NOT affected — uses mirror-load CMFB
- [anti-002] **Vcm=VDD/2 with PMOS**: NOT affected — Vcm=0.2V

## Cross-Model Review
(Full divergence analysis from /analog-review)

## Risk Summary
1. **CRITICAL**: Mirror ratio mismatch (M3/M4) — likely wrong current, affects all specs
2. **WARNING**: DC gain and UGBW are marginal — no margin for PVT variation
3. **INFO**: Design appears functional but optimistic at typical corner

## Recommendations
1. Fix M3/M4 mirror ratio (change W from 4u to 5u, or update comment)
2. Increase gm1 by ~10% (widen M1/M2 or increase Ibias) for gain/BW margin
3. Recommend Spectre verification before tapeout — hand-calc estimates are ±15%
```

## Effort Interaction

| Effort | Audit depth |
|--------|------------|
| lite | Checklist (structural only) + topology identification |
| standard | Full checklist + hand-calc audit |
| intensive | Full checklist + hand-calc + 2-model cross-review |
| exhaustive | Everything + full cross-model review + wiki anti-pattern scan |

## Standalone Usage

This skill is fully standalone. It does not require analog-pipeline or any
prior design activity. Just point it at a netlist:

```
Use the analog-audit skill to review circuit/ota.scs
```

If spec.yml exists in the same directory, it will be used automatically.
If rationale.md exists, it will be cross-checked.

## Wiki Interaction

- Reads `wiki/anti-patterns/` for anti-pattern scan
- On completion: if a new anti-pattern is discovered, suggest adding it to wiki
