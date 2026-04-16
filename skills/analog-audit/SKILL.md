---
name: analog-audit
description: >
  Audit analog circuit netlists for correctness, quality, and risks.
  Supports both pre-layout (schematic) and post-layout (extracted) netlists.
  Post-layout mode filters massive parasitic netlists before auditing.
  Works without EDA. TRIGGER on: "audit", "review netlist", "check this circuit",
  "design review", "pre-layout", "post-layout", "post-sim", "extracted netlist".
---

# analog-audit

Static audit service for analog circuit netlists. Supports two modes:

- **Pre-layout audit** — clean schematic-level netlist (hundreds to thousands of lines)
- **Post-layout audit** — extracted netlist with parasitics (tens of thousands to millions of lines)

No EDA required for either mode.

## Detecting Audit Type

Auto-detect from netlist characteristics:
- Lines > 50,000 OR parasitic R+C count > 10x active device count → **post-layout**
- Otherwise → **pre-layout**

User can force: `/analog-audit pre <netlist>` or `/analog-audit post <netlist>`

## Pre-Layout Audit

For schematic-level netlists. This is the standard audit flow.

### Process

```
Input: <block>.scs (schematic netlist)
    |
    v
  1. Topology identification
     Parse structure: diff pairs, mirrors, cascodes, CMFB, etc.
     Classify topology.
    |
    v
  2. Checklist execution
     Auto-detect applicable checklists from topology.
     Run all checks per effort level.
    |
    v
  3. Hand-calculation audit
     Extract .param values, re-derive specs from first principles.
     Compare against rationale.md and spec.yml if available.
    |
    v
  4. Anti-pattern scan
     Match topology against wiki/anti-patterns/.
    |
    v
  5. Cross-model review (effort >= standard)
     Send to configured reviewers per review-protocol.md.
    |
    v
  6. Pre-layout audit report
     verifier-reports/audit-pre-layout.md
```

### Pre-Layout Report Format

```markdown
# Pre-Layout Audit — <netlist> — <date>

## Circuit Summary
- **Topology**: folded-cascode fully-differential OTA
- **Devices**: 14 MOSFETs, 2 resistors, 1 capacitor
- **Supply**: 0.9V
- **Estimated power**: 324uW

## Checklist Results
| Check | Severity | Result | Detail |
|-------|----------|--------|--------|
| ...   | ...      | ...    | ...    |

## Hand-Calculation Audit
| Spec | Estimated | Target | Status | Confidence |
|------|-----------|--------|--------|------------|
| ...  | ...       | ...    | ...    | ...        |

## Anti-Pattern Scan
- [anti-001] Diode-Load CMFB: NOT affected
- [anti-002] Vcm=VDD/2: NOT affected

## Cross-Model Review
(divergence analysis from /analog-review)

## Risk Summary
1. [CRITICAL] ...
2. [WARNING] ...

## Recommendations
...
```

## Post-Layout Audit

For extracted netlists with parasitics. These netlists are typically 100K-10M+ lines.
They CANNOT be audited directly — they must be filtered first.

### Process

```
Input: <block>_extracted.scs (post-layout netlist, possibly millions of lines)
    |
    v
  1. Statistics scan
     Run: python3 tools/postlayout_filter.py stats <netlist>
     Report: total lines, device counts, parasitic R/C counts.
     Confirm this is indeed a post-layout netlist.
    |
    v
  2. Skeleton extraction
     Run: python3 tools/postlayout_filter.py extract <netlist> --threshold <cap_thresh>
     Produces: <block>_filtered.scs — active devices + significant parasitics only.
     Typically reduces 500K lines to 2-5K lines.
    |
    v
  3. Pre-vs-post comparison (if pre-layout netlist available)
     Run: python3 tools/postlayout_filter.py compare <pre>.scs <post>.scs
     Produces: device count diff, top parasitic caps, impact assessment.
    |
    v
  4. Filtered netlist audit
     Run standard audit flow (checklist + hand-calc) on the FILTERED netlist.
     Active device sizing should match pre-layout (if not, flag).
    |
    v
  5. Parasitic impact assessment
     Analyze significant parasitics:
     - Which high-impedance nodes have large parasitic caps?
       (These directly reduce gain and bandwidth)
     - Which signal paths have significant parasitic R?
       (These add noise and IR drop)
     - Are there unexpected coupling caps between sensitive nodes?
       (e.g., clock-to-analog coupling, input-to-output coupling)
     - Total added capacitance at each critical node vs original CL.
    |
    v
  6. Post-layout audit report
     verifier-reports/audit-post-layout.md
```

### Filtering Parameters

Default thresholds (adjustable):
- **Capacitor threshold**: 1fF — keep caps >= 1fF, discard smaller
- **Resistor threshold**: 1Mohm — keep R <= 1M (low-R paths matter for IR drop)

For advanced filtering:
- `--threshold 10f` — stricter, only keep significant caps (faster audit, less detail)
- `--threshold 0.1f` — looser, keep more parasitics (slower but more thorough)

### Post-Layout Report Format

```markdown
# Post-Layout Audit — <netlist> — <date>

## Netlist Statistics
- **Original**: 523,847 lines
- **Filtered**: 3,241 lines (0.6% of original)
- **Active devices**: 14 MOSFETs (matches pre-layout)
- **Parasitic caps**: 187,432 total, 847 significant (>= 1fF)
- **Parasitic resistors**: 203,561 total, 1,204 significant (<= 1Mohm)
- **Total parasitic capacitance**: 2.3 pF

## Pre-Layout vs Post-Layout Comparison
(if pre-layout netlist provided)

| Type | Pre-Layout | Post-Layout | Delta |
|------|-----------|-------------|-------|
| MOSFET | 14 | 14 | 0 |
| Resistor | 2 | 203,563 | +203,561 parasitic |
| Capacitor | 1 | 187,433 | +187,432 parasitic |

## Top Parasitic Capacitors
| Rank | Nodes | Value | Impact |
|------|-------|-------|--------|
| 1 | VOUTP — VSS | 340 fF | Adds to output load, reduces UGBW |
| 2 | VOUTN — VSS | 335 fF | Symmetric, expected |
| 3 | net_fold — VSS | 120 fF | On high-Z fold node, reduces gain |
| ...

## Parasitic Impact on Specs
| Spec | Pre-Layout Est. | Post-Layout Est. | Degradation | Severity |
|------|----------------|------------------|-------------|----------|
| UGBW | 500 MHz | ~380 MHz | -24% | WARNING |
| DC gain | 62 dB | ~58 dB | -4 dB | WARNING |
| Phase margin | 65 deg | ~60 deg | -5 deg | OK (still meeting) |
| Settling | 2 ns | ~3.2 ns | +60% | CRITICAL |

## Coupling Analysis
- VINP — VOUTP: 2.3 fF coupling cap (may affect PSRR)
- CLK — net_analog: 0.8 fF (monitor for clock feedthrough)

## Active Device Verification
All 14 MOSFETs match pre-layout sizing (W, L, nf, multi).
No unexpected devices added or removed.

## Checklist Results (on filtered netlist)
(same format as pre-layout)

## Risk Summary
1. [CRITICAL] Settling time degraded 60% — parasitic cap at output nodes
2. [WARNING] UGBW reduced 24% — may fail spec at SS corner
3. [INFO] 2.3fF input-output coupling — verify PSRR impact

## Recommendations
1. Add shielding between VINP and VOUTP routing
2. Minimize routing over fold nodes (net_fold has 120fF parasitic)
3. Re-simulate post-layout to confirm margin estimates
```

## Subcommands

| Command | Description |
|---------|-------------|
| `/analog-audit <netlist>` | Auto-detect pre/post layout, run appropriate audit |
| `/analog-audit pre <netlist>` | Force pre-layout audit |
| `/analog-audit post <netlist>` | Force post-layout audit |
| `/analog-audit post <netlist> --pre <pre_netlist>` | Post-layout audit with pre-layout comparison |
| `/analog-audit stats <netlist>` | Quick statistics only (no full audit) |

## Effort Interaction

| Effort | Pre-Layout | Post-Layout |
|--------|-----------|-------------|
| lite | Checklist (structural) + topology ID | Stats + skeleton extract only |
| standard | Full checklist + hand-calc | Stats + extract + filtered audit |
| intensive | + 2-model cross-review | + pre-vs-post comparison + parasitic impact |
| exhaustive | + full cross-review + wiki scan | + coupling analysis + all cross-review |

## Standalone Usage

Fully standalone. Does not require analog-pipeline or prior design activity.

```
Use the analog-audit skill to review circuit/ota.scs
Use the analog-audit skill to audit post-layout extracted_ota.scs --pre circuit/ota.scs
```
