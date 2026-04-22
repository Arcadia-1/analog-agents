---
name: analog-netlist-crawl
description: >
  Crawl and analyze post-layout parasitic netlists without running SPICE.
  Answers "what's the effective resistance from node A to node B across
  this massive R mesh?", "inside the VREFN mesh, which device pins are
  electrically farthest apart?", "which nets have the worst coupling?",
  "where does settling bottleneck?" — by parsing the netlist, building
  a sparse graph, and solving the resistance Laplacian / summing the
  capacitance network. Format-agnostic: Calibre xRC mr_pp (.pex.netlist),
  Spectre flat, Spectre with subckt + include chain (.pex / .pxi splits),
  and Cadence calibreview bundles all produce identical kernel output.
  TRIGGER whenever the user shares a post-layout / extracted / parasitic
  netlist and asks about symmetry, parasitic C, parasitic R, coupling,
  driving-point resistance, within-net R distribution, pin-to-pin R,
  SAR CDAC analysis, comparator input impedance — even if they don't
  say "post-layout". Also trigger on filenames ending in .pex.netlist,
  .pxi, or mentions of xRC, Calibre extraction, RCC mode, extracted
  subckt. Do NOT re-grep the netlist by hand — this skill has a
  validated streaming parser (adapters/), sparse-Laplacian solvers
  (kernels/r_network.py with cached LU factorization), and a codified
  interpretation workflow.
---

# analog-netlist-crawl

Parse any of the common post-layout netlist formats into a single
in-memory IR, then run format-agnostic kernels on it.  **Format and
math are decoupled**: adapters handle syntax, kernels handle
electricity, reports are pure composition.

## Architecture

Three single-job CLIs, all **pure netlist analysis / manipulation**.
No simulation — running Spectre lives in the separate `spectre` skill.

```
scripts/
├── scan.py                 ANALYZE   post-layout .scs → §1-§8 diagnostic report
├── prescribe.py            EXTRACT   post-layout .scs → R+Cc prescription JSON
├── inject.py               MODIFY    schematic .scs + rc_model.json → modified .scs
├── ir.py                   Circuit / Device / is_power / canonicalize
├── adapters/
│   ├── __init__.py         detect_format + parse_netlist dispatcher
│   ├── _util.py            parse_si (shared SI-prefix parser)
│   ├── mrpp.py             Calibre mr_pp syntax
│   └── spectre.py          Spectre (flat + subckt + include + helper-flatten)
├── kernels/
│   ├── r_network.py        effective_resistance, resistance_matrix,
│   │                       within_net_pin_r, net_prescription,
│   │                       batch_prescription (multi-net, dedup
│   │                       inter-net Cc), per_net_r_sum
│   ├── cg.py               per_net_cg_sum
│   └── cc.py               per_pair_cc_sum
├── report.py               §Within-net / §R-matrix / §1–§3 / §6 / §7 / §8
├── fixtures/               hand-crafted tests with closed-form answers
├── test_all.py             adapter × format × kernel regression matrix
└── md_to_pdf.py            interpretation.md → PDF (YaHei for CJK)
```

**Three CLIs, three files, three jobs.**  Each reads files, writes
files.  Compose via shell — and pair with the `spectre` skill when
you need to validate the prescription by simulation.

**The Circuit IR** (`ir.py`) is three edge lists + device list + alias
map + metadata.  `Circuit.canonical(node)` folds subnode names to their
logical net via `alias` (explicit, from adapter) then falls back to
rule-based `canonicalize()` for Calibre naming conventions:

| Input node name | Canonical |
|---|---|
| `SETN_94966` | `SETN` (mrpp subnode suffix) |
| `N_VREFN_XI18_35\/XC1_1_minus` | `VREFN` (spectre hierarchical) |
| `c_18125_p` | *(unchanged — anonymous mesh subnode, no parent)* |
| `5719` | *(unchanged — helper-subckt local node, needs explicit alias)* |

## Supported input formats

| Format | Example | Status |
|---|---|---|
| Calibre mr_pp self-contained | `LR_REF_BUFF_FULL.pex.netlist` (1 file) | ✅ |
| Spectre flat | `input.scs` from calibreview export | ✅ |
| Spectre + subckt + include | main `.pex.netlist` + `.pex` + `.pxi` | ✅ |
| Helper-subckt flattening | `subckt PM_X` pre-declared, `x_PM_X` instantiated inside DUT | ✅ |
| HSPICE DSPF / SPEF | — | ⏳ not implemented; open an issue with a sample |

Auto-detection (`detect_format`) sniffs ~200 non-comment lines for
leading `mr_pp` / `mgc_` → mrpp, or `simulator lang=spectre` / `subckt`
→ spectre.

## CLI usage

```bash
# Simplest form — produces §1–§8 report on stdout.
python scripts/scan.py <netlist-file>

# Headline engineering view for a buffer / reference-rail DUT:
python scripts/scan.py example_artifacts/LR_REF_BUFF_FULL/calibre_pex_spectre/LR_REF_BUFF_FULL.pex.netlist \
    --dut LR_REF_BUFF_FULL \
    --within-net "VREFN,SETP,SETN,VREFOUT,VREFH" \
    --within-net-max-pins 30 \
    --within-net-top-pairs 10 \
    --top 20 \
    --min-coupling 1f \
    -o output/netlist-crawl/LR_REF_BUFF_FULL/report.txt
```

### Flags

| Flag | Purpose |
|---|---|
| `--dut NAME` | force the DUT subckt (else: biggest auto-picked) |
| `--format mrpp\|spectre` | force format (else: auto-detect) |
| `--within-net NET1,NET2,...` | **pin-to-pin R distribution inside each named canonical net** — the buffer-analysis headline.  For each net, finds every device pin landing on it, then solves effective R between sampled pins via the parasitic R mesh. |
| `--within-net-max-pins N` | cap sampled pins per net (default 40 → 780 pair solves) |
| `--within-net-top-pairs N` | top-K largest-R pairs shown per net (default 10) |
| `--rmatrix NODES\|ports` | pairwise R-matrix between listed nodes (or DUT ports).  For pure-parasitic extracts, port-to-port is usually +inf (no direct wire link); `--within-net` is the more useful view. |
| `--trace "LABEL:a,b->c,d"` | driving-point R row in §8; nodes within a side are shorted together. Repeatable. |
| `--top N` | rank length for §1 / §2 / §3 (default 25) |
| `--min-coupling 1f` | ignore Cc pairs below this SI-typed threshold |
| `--drilldown N` | §6 shows devices on top-N Cg-heavy nets |
| `--mismatch` | enable §4 P/N auto-pair check (opt-in; false-flags on designs where P/N isn't a real diff pair) |
| `--no-cache` | skip the pickle parse cache (force re-parse) |
| `-o FILE` | write to file instead of stdout |

### Performance

First run on the 63 MB `LR_REF_BUFF_FULL.pex.netlist` takes ~25 s
(8 s parse + ~16 s for 5-net within-net analysis).  The parsed Circuit
is pickle-cached under the system temp dir keyed by
`(abspath, mtime, size)` — subsequent runs on the same file drop to
~16 s (cache hit in ~0.5 s).

Within-net analysis builds the R-edge adjacency **once** per run and
shares it across every requested net, avoiding the O(E) rebuild that
used to dominate.  Each net's solve uses sparse LU factorization
(`scipy.sparse.linalg.splu`) **factored once** on the net's connected
component, then batched forward/back substitution over all sampled
pin RHS vectors — the fast dense-matrix-solve path inside SuperLU.

## prescribe.py — post-layout → R+Cc prescription JSON

The **core goal** of this skill: given a post-layout netlist, output
what R and C components to add to the schematic so that pre-simulation
reproduces post-layout small-signal behaviour (UGB, phase margin).

```bash
python scripts/prescribe.py <post_layout.scs> \
    --dut L4_OTA1_STAGE1 \
    --nets "V1P,V1N,VINP,VINN,VOUTP,VOUTN" \
    -o rc_model.json
```

For each requested net the tool computes:

1. **`r_eff`** — cluster-short DC driving-point R between all MOS D/S
   drivers and all G loads, via sparse-Laplacian Schur-complement.
2. **Position map p(node) ∈ [0, 1]** — one extra Laplacian solve with
   loads pinned at V=0, 1 A distributed at drivers; `p = 1 −
   V(node)/V(drivers_mean)` places every subnode on the driver→load
   axis (p = 0 at driver, p = 1 at load).
3. **π-split Cc** — each external Cc edge's internal endpoint has a
   position p.  The edge contributes `val·(1−p)` to the driver-side
   bucket (`cc_driver_side`) and `val·p` to the load-side bucket
   (`cc_load_side`).  Grouped by the resolved canonical of the other
   endpoint.
4. **4-channel inter-net Cc** — when a Cc edge has **both** endpoints
   in prescribed nets' meshes, it's recorded **once** in the
   `inter_net_couplings` list with 4 position-weighted channels, so
   injection places it on exactly one set of pre-R/post-R pairs.
   Prevents the double-counting that would otherwise occur when each
   net independently records its side of the edge.
5. **Driver source auto-detection** — if a net has no MOS D/S pins in
   its mesh (DUT port like VINP), the bare canonical node is used as
   the driver entry; marked as `"driver_source": "dut_port"` in the
   output for audit.

Canonical resolution uses auto-discovery by default (every named
canonical in the circuit gets expanded into its R-component so Cc
peers on anonymous subnodes can be attributed back).

### JSON output shape

```json
{
  "source": "...", "dut": "...",
  "prescriptions": [
    {
      "net": "V1P",
      "component_size": 9346,
      "r_eff": 17.44,
      "driver_source": "mos_ds",
      "driver_pins": ["M3.D", "M4.D", ...],
      "load_pins":   ["M12.G", "M70.G", ...],
      "total_external_cc": 8.60e-14,

      "cc_driver_side": {             // attach to pre-R node
        "VINN":  4.75e-14,
        "net26": 2.35e-14,
        "net28": 2.29e-14,
        ...
      },
      "cc_load_side": {                // attach to post-R node
        "net14": 2.09e-14,
        "VOUTN": 1.88e-14,
        ...
      },
      "cc_distribution": { ...total = driver+load... }
    },
    ...
  ],
  "inter_net_couplings": [
    {
      "net_a": "V1P", "net_b": "VINN",
      "DD": 0.48e-15,   // weight·val for (pre, pre)  pair
      "DL": 0.02e-15,   //               (pre, post) pair
      "LD": 45.12e-15,  //               (post, pre) pair
      "LL": 1.00e-15,   //               (post, post) pair
      "total": 47.6e-15
    },
    ...
  ]
}
```

### Interpreting the fields

- `r_eff`: DC cluster-to-cluster R via Laplacian.  Direct extraction,
  no heuristic.  For a dense mesh with many parallel paths this
  comes out smaller than any pair R — that's correct (all the
  parallel gate-finger paths collapse into a low-R cluster short).
- `cc_driver_side` + `cc_load_side`: first-order moment-matched
  partition of each Cc's contribution between the two ends of the
  lumped π-model.  Sum of `cc_driver_side[peer] + cc_load_side[peer]`
  equals the original Cc total to that peer.
- `inter_net_couplings`: edges between two prescribed nets get the
  4-way split so injection hits the correct node pair (not all 4 at
  once — whichever weight is dominant captures where that Cc
  physically sits).

### What pre-sim accuracy to expect

Injecting the full prescription (`r_eff` series + driver/load Cc +
inter-net Cc) into the schematic and resimulating:

- **PM ≤ 1° off** from post-layout (pole location faithfully captured
  by RC structure).
- **UGB 10-15% off** — this is the intrinsic limit of 2-section
  lumped π against distributed mesh; higher-order poles/zeros can't
  be compressed further without adding more lumped sections.

The previous iteration (before the inter-net de-duplication fix)
could accidentally match UGB to 2% because it over-counted Cc
between prescribed nets — that was a bug masquerading as accuracy.
The current physical-correct model trades nominal UGB match for
**honest, auditable, composable** R+C values.

Full OTA validation numbers: see the **Validation case** section
near the bottom.

## inject.py — schematic + prescription → modified schematic

```bash
python scripts/inject.py <schematic.scs> rc_model.json \
    --dut L4_OTA1_STAGE1 \
    --min-cc 1e-16 \
    --allow-peer _net0 \
    -o dut_with_rx.scs
```

### What gets written into the DUT subckt

For **each prescription entry** (e.g. `V1P`):

1. Every MOS with G on `<net>` has its gate terminal renamed to
   `<net>_post`.  No other MOS attributes change.
2. Series R between the original pin and the renamed pin:
   ```
   R_rc_<net> (<net> <net>_post) resistor r=<r_eff>
   ```
3. **Driver-side Cc** (one instance per peer):
   ```
   C_rc_d_<net>_<peer> (<net> <peer>) capacitor c=<cc_driver_side[peer]>
   ```
4. **Load-side Cc** (one instance per peer):
   ```
   C_rc_l_<net>_<peer> (<net>_post <peer>) capacitor c=<cc_load_side[peer]>
   ```

For **each inter-net coupling** (e.g. `V1P ↔ VOUTN`), up to 4
instances with prefix `C_rc_ij_` placed on the weighted combinations:

```
C_rc_ij_DD_V1P_VOUTN (V1P      VOUTN     ) capacitor c=<DD weight>
C_rc_ij_DL_V1P_VOUTN (V1P      VOUTN_post) capacitor c=<DL weight>
C_rc_ij_LD_V1P_VOUTN (V1P_post VOUTN     ) capacitor c=<LD weight>
C_rc_ij_LL_V1P_VOUTN (V1P_post VOUTN_post) capacitor c=<LL weight>
```

Weights summing to 1 means the **total** C injected across these 4
equals the physical Cc (no double-count).

### Filters

- `--min-cc <farads>` — drop Cc peers below this (default 0.1 fF).
  Applied to both one-sided and inter-net channels.
- Peers with anonymous names (`c_NNN_n`, `_net42`, `MMxxx_g`,
  pure digits) are **skipped with a warning**; use
  `--allow-peer NAME` (repeatable) to force-inject specific ones.
  For Calibre RCC extractions the `_net0` pseudo-substrate is
  typically worth allowing (~1-10 fF per net of effective ground
  cap).

### Prefix conventions (grep-friendly)

| Prefix | Meaning |
|---|---|
| `R_rc_<net>` | Series R between `<net>` and `<net>_post` |
| `C_rc_d_<net>_<peer>` | External Cc, driver-side |
| `C_rc_l_<net>_<peer>` | External Cc, load-side |
| `C_rc_ij_<chan>_<na>_<nb>` | Inter-net Cc, one of DD/DL/LD/LL |

## Validating the prescription (hand off to the `spectre` skill)

**netlist-crawl does NOT simulate.**  Keep analysis and simulation
separate — that's a deliberate boundary.  To close the loop:

1. Produce `dut_rx.scs` with `inject.py` (this skill)
2. Rename `dut_rx.scs` → `netlist` (or edit testbench `include
   "netlist"` to `include "dut_rx.scs"`)
3. Use the **`spectre` skill** to run the simulation
4. Parse the PSF output for UGB/PM:
   - **ADM UGB** = frequency where `(VOUTP-VOUTN)/(VINP-VINN)`
     crosses 1 in `ac.ac`
   - **stb Phase Margin** = read as text scalar from
     `<raw_dir>/stb.margin.stb` (grep `phaseMargin`)

Minimal glue (belongs in your project scripts, not this skill):

```python
from virtuoso_bridge.spectre.runner import SpectreSimulator, spectre_mode_args
from virtuoso_bridge.spectre.parsers import parse_psf_ascii_directory

sim = SpectreSimulator.from_env(spectre_args=spectre_mode_args("ax"),
                                work_dir="./sim_out", output_format="psfascii")
result = sim.run_simulation("input.scs",
    {"include_files": ["dut_rx.scs"]})
psf = parse_psf_ascii_directory(result.metadata["output_dir"])
# parse ac_VOUTP, ac_VOUTN, ac_VINP, ac_VINN → UGB
# read stb.margin.stb → phaseMargin scalar
```

Ship the **prescription JSON** alongside the final schematic so
reviewers can see which R/C values came from the post-layout and why.

## Validation case (TB_OTA1_STAGE1, fully differential 2-stage OTA)

Real end-to-end run from this skill against a `L4_OTA1_STAGE1` DUT:

| Config | ADM UGB | stb PM | stb PM freq |
|---|---|---|---|
| schematic baseline (no rc model) | 46.99 GHz | 43.35° | 29.85 GHz |
| + 6-net rc model (V1P, V1N, VINP, VINN, VOUTP, VOUTN) | **26.62 GHz** | **36.52°** | 16.89 GHz |
| **post-layout target (calibre_rcc)** | **23.56 GHz** | **36.17°** | **15.11 GHz** |
| **gap** | **+13%** | **+0.35°** | **+12%** |

- **PM nails post-layout within 0.35°** — RC pole location
  faithfully reproduced.
- UGB is 13% too fast — this is the intrinsic 2-section π model
  ceiling against a distributed mesh, not a missing-data problem.
- Zero fitting: all R and C values came straight out of
  `prescribe.py`, no tuning.

Compression:

| | post-layout netlist | injected lumped model |
|---|---|---|
| R elements | 199,273 | 6 |
| C elements | 216,957 | ~100 (driver/load/inter-net combined) |
| **Total parasitic elements** | **416,230** | **~110** |
| **Compression ratio** | — | **~3800×** |

## The two primary analyses

### (1) Within-net pin-to-pin R — the buffer / reference-rail headline

For each canonical net, find every device pin landing on it (via
`canonicalize`), pick a bounded sample of those pins, and report
effective R between every pair through the parasitic mesh.  Output:
percentile distribution (min/p25/median/p75/p95/max) plus top-K
largest-R pairs with device-pin annotations.

**Why it's the central metric for multi-terminal blocks**: a single
logical net like VREFN is physically distributed across hundreds of
device terminals.  The buffer driver sees one subnode; each load sees
a different subnode; the parasitic R between them is real and
distinct.  The median pair R tells you the bulk settling impedance;
the max pair R tells you the worst-case matching / IR-drop extreme.

Real-world example: on `LR_REF_BUFF_FULL`, VREFN has 977 pin touches,
median pair R = 67 Ω, max 81 Ω.  SETP has 707 pin touches, median
381 Ω, max 405 Ω.  SETN (707 pins) has max 334 Ω — so SETP vs SETN
worst-case differs by 21 %: the kind of matching-critical asymmetry
that only pair-distribution analysis surfaces.

### (2) Effective R between arbitrary node sets (driving-point R)

`--trace "label:src1,src2->snk1,snk2"` solves the full Laplacian with
Dirichlet BCs on source=1V, sink=0V, returns R = 1/I.  Nodes within a
side are shorted together (seed-set semantics).  Use for: comparator
gate → CDAC top, bias → VSS, any specific pair you care about.

Multi-component handling: only connected R-graph components that
contain BOTH a source AND a sink node contribute.  A component with
only source (or only sink) nodes would make the Laplacian singular —
those are dropped, equivalent to open-circuit in that component.

## Correctness anchoring (fixtures)

Every kernel change is regressed against `scripts/test_all.py`, a
matrix of 9 tiny hand-crafted circuits with closed-form expected
values.  Run:

```bash
cd scripts && python test_all.py
```

The anchor set:

| Fixture | Topology | What it pins down |
|---|---|---|
| F1 RC ladder | 3R series + 1 Cg | basic series KCL, Cg per-net folding |
| F2 diff-pair + Cc | 2 isolated halves + 1 Cc | DC isolation (Cc → R_eff = inf), Cc pair identification |
| F3a | 10Ω ‖ 30Ω | pure parallel (7.5Ω) |
| F3b | symmetric diamond | parallel branches (15Ω) |
| **F3c Wheatstone** | **unbalanced bridge, 5 R's all loaded** | **full Laplacian, every KCL branch active (30.75Ω = 123/4 exact)** |
| F3d | shorted seeds across components | multi-component parallel (5Ω); guards singular-Laplacian bug |
| F3 cross-component pairs | disjoint sub-circuits | R_eff = +inf required (not numerical garbage) |
| **F4 within-net** | **4 MOSFETs with gates on 4 series-chained VREFN subnodes** | **pseudo-inverse formula `R=L⁺[a,a]+L⁺[b,b]−2·L⁺[a,b]`; caught a bug where `V_a[a]−V_a[b]` coincidentally worked only when one seed was the ground node** |

Each fixture exists in its applicable format(s) (`*.mrpp`,
`*.flat.scs`, `*.subckt.scs`) so a kernel bug always shows up the
same way regardless of adapter.

## The interpretation workflow (the LLM's job)

Parser + kernels give you a report.txt.  Turning that into a useful
design review is what the skill codifies.

### Step 1 — Classify the input

`head -40 <file>` and `tail -40 <file>`.  `scan.py` auto-detects, but
a glance confirms:

| Cue | Format |
|---|---|
| `mr_pp 'r "..."`, `mgc_rve_device_template` | mrpp |
| `simulator lang=spectre` + `subckt <NAME>` | spectre subckt (maybe with includes) |
| `simulator lang=spectre` + no `subckt` header | spectre flat |
| 3 sibling files `foo.pex.netlist` / `foo.pex.netlist.pex` / `foo.pex.netlist.*.pxi` | split with includes |

### Step 2 — Run scan.py

Pick **`--within-net NET1,NET2,...`** for the DUT's critical nets
(output rail, reference rails, bias lines).  Add `--trace` for any
specific pair you need driving-point R on.  Pass `--dut` if the
file has a wrapped subckt.

### Step 3 — Read the report sections

| § | Content | Misreading to watch for |
|---|---|---|
| **Within-net** | per-net pin-pair R distribution + top-K farthest pairs | the **central** section for buffers — spend time here |
| R-matrix | pairwise R between listed nodes | for parasitic-only extracts, port-to-port is usually +inf (no direct wire) — that's correct, not a bug |
| §1 Per-net Σ R | arithmetic sum over all R segments on each canonical net | ranking only, NOT R_eff.  62 kΩ on a 22k-segment mesh can have 58 Ω driving-point R |
| §2 Per-net Σ Cg | total ground cap per canonical net | effective Cg |
| §3 Net-pair Cc | net-to-net coupling ranking | large coupling between arrayed neighbors is often design-normal |
| §6 Drill-down | which devices touch heaviest Cg nets | if pin count is 0, canonicalize isn't folding — file a bug |
| §7 Red flags | auto-thresholded Σ R / Cg / Cc | first-pass triage; not a conclusion |
| §8 Driving-point R | true electrical R between specified source/sink sets | only present if --trace passed |

### Step 4 — Interpret (the LLM value)

For each data point, answer three questions:

1. **Is this normal for this circuit type?**  VREFN heavy Cg in a
   reference buffer = expected; same pattern on a digital clock =
   bug.
2. **Does data + topology agree?**  If §within-net flags a large
   max-R pair and §6 shows the two endpoints are on devices at
   opposite ends of the layout's long axis, that's routing-geometry
   explained.  If they're on nominally-adjacent devices, that's a
   routing bug.
3. **What's the worst-realistic reading?**  A 400 Ω pair on SETP
   looks small — but 400 Ω × I_kick = spike on the gate drive right
   before the next decision.  That's the read the designer needs.

### Step 5 — Write the interpretation markdown

Save to `output/netlist-crawl/<dut>/<dut>_interpretation.md`:

```markdown
# <DUT> 后仿网表分析解读
**DUT**: <cellname>
**输入网表**: <path>
**脚本输出**: output/netlist-crawl/<dut>/<dut>_report.txt
**解读作者**: Claude
**日期**: <YYYY-MM-DD>

## 1. 扫描规模与健康度
(cite report header: #R/#Cg/#Cc edges, #devices, #nodes)

## 2. 关键网的 within-net R 分布
(for each net from --within-net: pin count, median, max, worst pair
 interpretation — which devices, what geometric path, what spec it
 affects)

## 3. 耦合（§3 Cc top pairs）
(rank interpretation: which coupling is design-normal vs routing
 accident)

## 4. Driving-point R（若跑了 --trace）
(specific src→snk traces, thermal-noise / kickback / settling
 consequences)

## 5. 下一步建议（按优先级）
1. 版图改动（具体位置 / 具体宽化 / 具体屏蔽）
2. 前仿加 R 的宏模型（带具体 Ω 值）
3. 电路 review
4. 重跑回归

## 6. 方法论与数据可信性
(report.txt 可复现 / interpretation.md 是 LLM 解读 / fixtures 锁死 kernel 正确性)
```

### Step 6 — Convert to PDF

```bash
python scripts/md_to_pdf.py \
    output/netlist-crawl/<dut>/<dut>_interpretation.md \
    output/netlist-crawl/<dut>/<dut>_interpretation.pdf
```

Supports `#/##/###` headings, tables, lists, `**bold**`, `` `code` ``,
code blocks, `---` rules.  Uses Microsoft YaHei so CJK renders.

### Step 7 — Feed numbers back to the schematic

**The part most engineers skip.**  Every pair R ≥ ~10 Ω from
`--within-net` or `--trace` matters in pre-simulation.  Three
second-order effects invisible without it:

**(a) Thermal noise** — `v_n,rms = √(4·k·T·R·B)`.  At 1 GHz BW, 80 Ω →
~36 μV rms.  For an N-bit SAR with LSB = VDD/2^N, compute as fraction
of LSB.  If > ~0.1 LSB, flag.

**(b) Kickback attenuation** — during latching the gate injects
transient current back into the input.  R × I_kick produces a voltage
spike that bleeds into the next decision.  A schematic without this R
is blind to the effect.

**(c) Settling accuracy tail** — first-order τ = R·C may be
picosecond-scale, but the full distributed response has higher-order
components only visible when R is physically present.

Concrete recommendation shape:

> "Add a series resistor between `<device>:<role>` and the driver's
>  output in the schematic, value = `<R_eff>` Ω.  This captures the
>  parasitic mesh between those two pins that currently doesn't exist
>  in pre-sim."

## Calibre naming quick reference

| Token pattern | Meaning |
|---|---|
| `c_NNN` | anonymous to-ground parasitic cap |
| `cc_NNN` | net-to-net coupling cap |
| `ciNET_N` | per-subnode ground cap; `NET` is the canonical net |
| `rNET_N` | parasitic R segment; `NET` is the canonical net |
| `c_<num>_p` / `c_<num>_n` | anonymous R-mesh internal subnode |
| `N_<NET>_<rest>` | spectre-style hierarchical subnode (folds to `<NET>`) |
| `XM<name>` | top-level MOSFET |
| `XX.../MM<n>` | hierarchical MOSFET |
| `xX.../XC<n>` | designer capacitor (cfmom_2t / MIM / mos_cap) |
| `D_noxref`, `noxref_NNN` | extractor couldn't cross-reference — **possible DRC / xref issue** |

## Known gotchas

- **Σ R is not effective R.**  A 62 kΩ Σ R on parallel mesh can have
  58 Ω driving-point R.  Always compare §1 vs within-net / §8.
- **"P/N" names aren't always diff pairs.**  `VREFP`/`VREFN` may be
  PMOS and NMOS bias rails — the §4 P/N check will false-flag.  It's
  opt-in (`--mismatch`) for this reason.
- **R-matrix between DUT ports is often all +inf.**  Parasitics only
  form local meshes within each canonical net; port-to-port DC paths
  go through devices (which this skill deliberately does NOT put into
  r_edges).  That +inf matrix is a correct finding about parasitic
  topology, not a bug.
- **Absolute include paths in split format** — Calibre writes Linux
  absolute paths into `include "..."`.  The spectre adapter's
  `_resolve_include` falls back to the basename in the main file's
  directory, so copies of the bundle across machines work.
- **Helper-subckt flattening** — pre-declared `subckt PM_X`
  instantiated by `x_PM_X ... PM_X` inside the DUT gets inlined with
  a positional pin-map.  Local numeric nodes get prefixed by instance
  path to avoid collisions.
- **Zero-valued R** — Calibre occasionally emits `r=0` as a
  topology-only connection.  The Laplacian skips these (`r <= 0`
  filter); treat as hard-short in downstream graph work if you need
  to.
- **Shell path handling on Windows** — Git-bash eats backslashes in
  unquoted Windows paths.  Use `/` or quote.

## What this skill does NOT do

- **No SPICE simulation.**  Redirect to Spectre for waveforms / MC.
- **No design-device resistance.**  Designer R's (`rupolym` etc.)
  live in `Circuit.devices`, NOT `r_edges` — this skill is strictly
  about the **parasitic** R network.  That's deliberate: the schematic
  already models designer R's; the question this skill answers is
  what the extraction ADDS on top.
- **No Elmore-tree delay.**  The net is a mesh; Elmore doesn't apply.
  Driving-point R via sparse Laplacian is the right abstraction.
- **No modifications to the input netlist.**  Read-only analysis.

## Trigger pattern

When this skill triggers on a new netlist:

1. `head -40 <file>` + `tail -40 <file>` to classify the format.
2. Decide `--dut` (if subckt-wrapped) and `--within-net` target
   nets — usually DUT output + reference rails + bias lines.
3. Run `scan.py` → `output/netlist-crawl/<dut>/<dut>_report.txt`.
4. Read the report end-to-end; spend the most time on the Within-net
   section.
5. Cross-check §within-net worst pairs against topology
   (`--drilldown` + `--trace` if needed).
6. Write `<dut>_interpretation.md` with data → topology →
   worst-realistic reading → concrete schematic-macro-model
   recommendations.
7. Convert to PDF.
8. Report to user: what was found, what to fix, what to add to
   pre-sim.
