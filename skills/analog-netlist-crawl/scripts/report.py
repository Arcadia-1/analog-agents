"""Text report generator — consumes a Circuit + kernel outputs, format-agnostic.

This is the new home for what pex_scan.py used to do in ``report_rc``,
but now operates on the IR so all three formats produce identical
reports (modulo the real rcx-mode data differences).

Sections emitted:

  §1  Per-net arithmetic Σ R   (ranking only, NOT effective R)
  §2  Per-net Σ Cg
  §3  Net-pair Cc (ranked, min-coupling threshold)
  §4  Differential P/N mismatch (auto-paired by name suffix)
  §6  Drill-down: devices touching the N heaviest nets
  §7  Red flags (auto-triggered thresholds)
  §8  Driving-point R (only when explicit source/sink sets are provided)
"""
from __future__ import annotations

import io
from collections import defaultdict

from ir import Circuit
from kernels import (
    effective_resistance,
    resistance_matrix,
    within_net_pin_r,
    per_net_r_sum,
    per_net_cg_sum,
    per_pair_cc_sum,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_r(r: float) -> str:
    if r == 0: return "0"
    if abs(r) >= 1e6:  return f"{r/1e6:.3f}M"
    if abs(r) >= 1e3:  return f"{r/1e3:.3f}k"
    if abs(r) >= 1:    return f"{r:.3f}"
    if abs(r) >= 1e-3: return f"{r*1e3:.3f}m"
    return f"{r:.4g}"


def _fmt_c(c: float) -> str:
    if c == 0: return "0"
    if abs(c) >= 1e-12: return f"{c*1e12:.3f}p"
    if abs(c) >= 1e-15: return f"{c*1e15:.3f}f"
    if abs(c) >= 1e-18: return f"{c*1e18:.3f}a"
    return f"{c:.3e}"


def _rank_desc(d: dict, key=lambda v: v):
    """Sort dict items by key(value) descending."""
    return sorted(d.items(), key=lambda kv: -key(kv[1]))


# ---------------------------------------------------------------------------
# Section emitters
# ---------------------------------------------------------------------------

def _emit_header(out: io.StringIO, circuit: Circuit) -> None:
    n = circuit.n_elements()
    md = circuit.metadata or {}
    out.write(f"# File           : {md.get('source_file', '?')}\n")
    out.write(f"# Format         : {md.get('format', '?')}\n")
    out.write(f"# DUT            : {circuit.dut}\n")
    if circuit.ports:
        out.write(f"# DUT ports      : {' '.join(circuit.ports)}\n")
    out.write(f"# R edges        : {n['R']:>12,}\n")
    out.write(f"# Cg edges       : {n['Cg']:>12,}\n")
    out.write(f"# Cc edges       : {n['Cc']:>12,}\n")
    out.write(f"# Devices        : {n['devices']:>12,}\n")
    out.write(f"# Unique nodes   : {len(circuit.nodes()):>12,}\n")
    out.write(f"# Alias entries  : {len(circuit.alias):>12,}\n")


def _emit_section_1_r(out: io.StringIO, circuit: Circuit, top: int) -> None:
    data = per_net_r_sum(circuit)
    out.write(f"\n## 1. Per-net Σ R  ({len(data):,} nets)\n")
    out.write(f"{'rank':>4}  {'net':<48s}  {'Σ R':>12s}\n")
    for i, (net, sum_r) in enumerate(_rank_desc(data)[:top], 1):
        out.write(f"{i:>4}  {net:<48s}  {_fmt_r(sum_r):>12s}\n")


def _emit_section_2_cg(out: io.StringIO, circuit: Circuit, top: int) -> None:
    data = per_net_cg_sum(circuit)
    total = sum(data.values())
    out.write(f"\n## 2. Per-net Σ Cg  ({len(data):,} nets, total {_fmt_c(total)})\n")
    out.write(f"{'rank':>4}  {'net':<48s}  {'Σ Cg':>12s}  {'%':>6s}\n")
    for i, (net, sum_c) in enumerate(_rank_desc(data)[:top], 1):
        pct = (sum_c / total * 100) if total > 0 else 0.0
        out.write(f"{i:>4}  {net:<48s}  {_fmt_c(sum_c):>12s}  {pct:>5.1f}%\n")


def _emit_section_3_cc(out: io.StringIO, circuit: Circuit, top: int,
                        min_coupling: float) -> None:
    data = per_pair_cc_sum(circuit)
    filtered = {k: v for k, v in data.items() if v >= min_coupling}
    total = sum(filtered.values())
    out.write(f"\n## 3. Net-pair Cc  ({len(filtered):,} pairs ≥ {_fmt_c(min_coupling)}, "
              f"total {_fmt_c(total)})\n")
    out.write(f"{'rank':>4}  {'net A':<30s}  {'net B':<30s}  {'Σ Cc':>12s}\n")
    for i, ((a, b), v) in enumerate(_rank_desc(filtered)[:top], 1):
        out.write(f"{i:>4}  {a:<30s}  {b:<30s}  {_fmt_c(v):>12s}\n")


def _emit_section_4_mismatch(out: io.StringIO, circuit: Circuit) -> None:
    """Auto-pair nets ending in P/N and flag Cg + Σ R asymmetry."""
    cg = per_net_cg_sum(circuit)
    r  = per_net_r_sum(circuit)
    pairs: list[tuple[str, str]] = []
    seen = set()
    for net in cg:
        if net.endswith("P") and net not in seen:
            n = net[:-1] + "N"
            if n in cg or n in r:
                pairs.append((net, n))
                seen.add(net); seen.add(n)
    out.write(f"\n## 4. Differential P/N mismatch  ({len(pairs)} pairs)\n")
    if not pairs:
        out.write("  (no matched P/N pairs)\n")
        return
    out.write(f"  {'P':<24s} {'N':<24s} {'Cg(P)':>10s} {'Cg(N)':>10s} {'ΔCg%':>7s}"
              f"  {'ΣR(P)':>10s} {'ΣR(N)':>10s} {'ΔR%':>7s}\n")
    for p, n in pairs:
        cgp, cgn = cg.get(p, 0.0), cg.get(n, 0.0)
        rp, rn = r.get(p, 0.0), r.get(n, 0.0)
        dcg = _pct(cgp, cgn)
        dr  = _pct(rp, rn)
        flag = ""
        if abs(dcg) > 5 or abs(dr) > 10:
            flag = "  <-- mismatch"
        out.write(f"  {p:<24s} {n:<24s} "
                  f"{_fmt_c(cgp):>10s} {_fmt_c(cgn):>10s} {dcg:>6.1f}% "
                  f"  {_fmt_r(rp):>10s} {_fmt_r(rn):>10s} {dr:>6.1f}%{flag}\n")


def _pct(a: float, b: float) -> float:
    m = max(abs(a), abs(b))
    return (a - b) / m * 100 if m > 0 else 0.0


def _emit_section_6_drilldown(out: io.StringIO, circuit: Circuit, n_nets: int) -> None:
    cg = per_net_cg_sum(circuit)
    heavy = [net for net, _ in _rank_desc(cg)[:n_nets]]
    # Map device -> nets touched (via canonical alias)
    net_to_devs: dict[str, list[str]] = defaultdict(list)
    for d in circuit.devices:
        for role, node in d.pins.items():
            cn = circuit.canonical(node)
            net_to_devs[cn].append(f"{d.name}:{role}({d.model})")
    out.write(f"\n## 6. Drill-down — devices touching top {n_nets} Cg-heavy nets\n")
    for net in heavy:
        devs = net_to_devs.get(net, [])
        out.write(f"  {net}  (Σ Cg = {_fmt_c(cg[net])}, {len(devs)} pins)\n")
        for d in devs[:8]:
            out.write(f"      {d}\n")
        if len(devs) > 8:
            out.write(f"      ... ({len(devs)-8} more)\n")


def _emit_section_7_flags(out: io.StringIO, circuit: Circuit,
                           *, r_sum_thresh: float = 1e3,
                           cg_thresh: float = 5e-15,
                           cc_thresh: float = 1e-15) -> None:
    r = per_net_r_sum(circuit)
    cg = per_net_cg_sum(circuit)
    cc = per_pair_cc_sum(circuit)
    flags: list[str] = []
    for net, v in r.items():
        if v >= r_sum_thresh:
            flags.append(f"  Σ R on {net!r} = {_fmt_r(v)} ≥ {_fmt_r(r_sum_thresh)}")
    heavy_cg = [(n, v) for n, v in cg.items() if v >= cg_thresh]
    for n, v in sorted(heavy_cg, key=lambda kv: -kv[1])[:10]:
        flags.append(f"  Cg on {n!r} = {_fmt_c(v)} ≥ {_fmt_c(cg_thresh)}")
    heavy_cc = [(k, v) for k, v in cc.items() if v >= cc_thresh]
    for (a, b), v in sorted(heavy_cc, key=lambda kv: -kv[1])[:10]:
        flags.append(f"  Cc on {a!r}↔{b!r} = {_fmt_c(v)} ≥ {_fmt_c(cc_thresh)}")
    out.write(f"\n## 7. Red flags  ({len(flags)} triggered)\n")
    if not flags:
        out.write("  none triggered.\n")
    else:
        for f in flags:
            out.write(f"{f}\n")


def _emit_section_within_net_r(
    out: io.StringIO,
    circuit: Circuit,
    nets: list[str],
    *,
    max_pins: int,
    top_pairs: int,
) -> None:
    """For each named net, emit pin-to-pin R distribution + top-K worst pairs.

    This is the engineering core for multi-terminal blocks (buffers,
    reference rails): within one canonical net the parasitic mesh
    spreads signal across many device pins, and the effective R
    between pins drives IR drops, delay, kickback bleed.  For each
    net we show:

    - header: total pins found, pins actually sampled, component size
    - distribution percentiles of all pair Rs
    - top-K pairs with largest R (the electrically-far pin pairs)
    """
    out.write(f"\n## Within-net pin-to-pin R  ({len(nets)} net(s))\n")
    if not nets:
        out.write("  (pass --within-net NET1,NET2,... to enable)\n")
        return
    # Build the R-edge adjacency once and share across every net —
    # within_net_pin_r would otherwise rebuild it per call (O(E) each,
    # and E ≈ hundreds of thousands on real data).
    from kernels.r_network import _build_adjacency
    adj = _build_adjacency(circuit)
    for net in nets:
        out.write(f"\n---- {net} ----\n")
        res = within_net_pin_r(circuit, net, max_pins=max_pins, _adj=adj)
        total = res.get("total_pins", 0)
        if total < 2:
            out.write(f"  {total} pin(s) on this net — nothing to compare.\n")
            continue
        live = res.get("live_pins", 0)
        sampled = res.get("sampled_pins", 0)
        comp = res.get("component_size", 0)
        redges = res.get("r_edges_in_component", 0)
        out.write(f"  pins total / sampled / in-R-graph : "
                  f"{total:,} / {sampled:,} / {live:,}\n")
        out.write(f"  R-component size                  : "
                  f"{comp:,} nodes, {redges:,} edges\n")
        pairs = res.get("pairs", {})
        if not pairs:
            out.write("  (no pairs — component too small or pins not in R graph)\n")
            continue
        vals = sorted(v for v in pairs.values() if v >= 0)
        if not vals:
            out.write("  (all pair Rs non-positive — unexpected, skipping)\n")
            continue
        # Distribution percentiles
        def _p(q: float) -> float:
            i = int(q * (len(vals) - 1))
            return vals[i]
        out.write(f"  R distribution over {len(vals):,} pin pairs:\n")
        out.write(f"      min    = {_fmt_r(vals[0]):>12s}\n")
        out.write(f"      p25    = {_fmt_r(_p(0.25)):>12s}\n")
        out.write(f"      median = {_fmt_r(_p(0.50)):>12s}\n")
        out.write(f"      p75    = {_fmt_r(_p(0.75)):>12s}\n")
        out.write(f"      p95    = {_fmt_r(_p(0.95)):>12s}\n")
        out.write(f"      max    = {_fmt_r(vals[-1]):>12s}\n")
        # Top-K worst pairs
        ranked = sorted(pairs.items(), key=lambda kv: -kv[1])[:top_pairs]
        out.write(f"  top {len(ranked)} largest-R pin pairs (electrically farthest):\n")
        devs = res.get("pin_devices", {})
        for (a, b), rv in ranked:
            out.write(f"      {_fmt_r(rv):>10s}  {a}  ↔  {b}\n")
            # Show which device pins these are
            for label, subnode in (("A", a), ("B", b)):
                dlist = devs.get(subnode, [])
                if dlist:
                    shown = dlist[:2]
                    extra = f" (+{len(dlist)-2})" if len(dlist) > 2 else ""
                    devs_str = ", ".join(f"{dn}:{role}" for dn, role, _m in shown)
                    out.write(f"          {label}: {devs_str}{extra}\n")


def _emit_section_rmatrix(
    out: io.StringIO,
    circuit: Circuit,
    nodes: list[str],
) -> None:
    """Pairwise R-matrix between the given nodes — headline section for
    buffers and multi-terminal blocks where every port-to-port R matters.

    Rendered as an upper-triangle table plus a column of diagonals (0);
    pairs without a DC path show ``inf``.
    """
    nodes = sorted(set(nodes))
    N = len(nodes)
    out.write(f"\n## R-matrix  (pairwise effective R across {N} nodes)\n")
    if N < 2:
        out.write(f"  (need at least 2 nodes; got {N})\n")
        return
    mat = resistance_matrix(circuit, nodes)
    # Header row
    label_w = max(len(n) for n in nodes) + 1
    col_w = 10
    out.write(" " * label_w + "  ")
    for n in nodes:
        out.write(f"{n:>{col_w}s} ")
    out.write("\n")
    for i, a in enumerate(nodes):
        out.write(f"{a:<{label_w}s}  ")
        for j, b in enumerate(nodes):
            if i == j:
                cell = "-"
            else:
                key = (a, b) if a < b else (b, a)
                v = mat.get(key, float("inf"))
                cell = "inf" if v == float("inf") else _fmt_r(v)
            out.write(f"{cell:>{col_w}s} ")
        out.write("\n")


def _emit_section_8_trace(out: io.StringIO, circuit: Circuit,
                           trace_pairs: list[tuple[list[str], list[str], str]]) -> None:
    """Emit driving-point R for explicit source/sink pairs.

    ``trace_pairs`` is a list of ``(source_nodes, sink_nodes, label)``.
    """
    out.write(f"\n## 8. Driving-point R  ({len(trace_pairs)} traced pair(s))\n")
    if not trace_pairs:
        out.write("  (no pairs — pass --trace to enable)\n")
        return
    out.write(f"  {'label':<32s}  {'R_eff':>12s}\n")
    for src, snk, label in trace_pairs:
        r_eff = effective_resistance(circuit, src, snk)
        r_str = "inf" if r_eff == float("inf") else _fmt_r(r_eff)
        out.write(f"  {label:<32s}  {r_str:>12s}\n")


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def build_report(
    circuit: Circuit,
    *,
    top: int = 25,
    min_coupling: float = 0.0,
    drilldown_n: int = 5,
    trace_pairs: list[tuple[list[str], list[str], str]] | None = None,
    rmatrix_nodes: list[str] | None = None,
    within_net_nets: list[str] | None = None,
    within_net_max_pins: int = 40,
    within_net_top_pairs: int = 10,
    include_mismatch: bool = False,
) -> str:
    """Return the full text report for a Circuit.

    Section order, with optionality:
      (header)  — always
      R-matrix  — iff rmatrix_nodes is non-empty.  Headline section for
                  buffers / multi-terminal blocks.
      §1 Σ R    — always
      §2 Σ Cg   — always
      §3 Cc     — always
      §4 P/N mismatch — iff include_mismatch=True.  Off by default: it
                  auto-pairs by P/N suffix and false-flags on designs
                  where SETP/SETN or similar names aren't real diff
                  pairs.  Opt-in when you know you have a diff design.
      §6 drill  — always
      §7 flags  — always
      §8 trace  — iff trace_pairs is non-empty
    """
    out = io.StringIO()
    _emit_header(out, circuit)
    if within_net_nets:
        _emit_section_within_net_r(out, circuit, within_net_nets,
                                    max_pins=within_net_max_pins,
                                    top_pairs=within_net_top_pairs)
    if rmatrix_nodes:
        _emit_section_rmatrix(out, circuit, rmatrix_nodes)
    _emit_section_1_r(out, circuit, top)
    _emit_section_2_cg(out, circuit, top)
    _emit_section_3_cc(out, circuit, top, min_coupling)
    if include_mismatch:
        _emit_section_4_mismatch(out, circuit)
    _emit_section_6_drilldown(out, circuit, drilldown_n)
    _emit_section_7_flags(out, circuit)
    _emit_section_8_trace(out, circuit, trace_pairs or [])
    return out.getvalue()
