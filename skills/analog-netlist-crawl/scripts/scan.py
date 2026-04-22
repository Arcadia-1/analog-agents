#!/usr/bin/env python3
"""analog-netlist-crawl — new CLI entry.

Takes a netlist in any supported format (Calibre mr_pp, Spectre flat,
Spectre with subckt + includes), parses it into the canonical IR, then
emits a text report built from format-agnostic kernels.

Usage::

    python scan.py <netlist> [--top N] [--min-coupling 1f]
                              [--trace "label:A,B->C,D" ...]
                              [--dut NAME]
                              [--format mrpp|spectre]

The ``--trace`` flag accepts any number of ``label:src1,src2->snk1,snk2``
specs.  Commas separate nodes within a side (they're shorted together
for the solve); ``->`` separates source from sink.
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from adapters import parse_netlist, detect_format
from parse_cache import load_or_parse
from report import build_report


def parse_trace_spec(spec: str) -> tuple[list[str], list[str], str]:
    """Parse ``label:src1,src2->snk1,snk2`` into (src_list, snk_list, label)."""
    if ":" in spec:
        label, rest = spec.split(":", 1)
    else:
        label, rest = spec, spec
    if "->" not in rest:
        raise SystemExit(f"--trace spec missing '->' : {spec!r}")
    src_s, snk_s = rest.split("->", 1)
    src = [x.strip() for x in src_s.split(",") if x.strip()]
    snk = [x.strip() for x in snk_s.split(",") if x.strip()]
    return src, snk, label


def parse_si_threshold(s: str) -> float:
    """Parse a user-typed threshold like "1f" into farads."""
    from adapters._util import parse_si
    v = parse_si(s)
    if v != v:
        raise SystemExit(f"unparseable threshold: {s!r}")
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("netlist", help="path to the netlist file")
    ap.add_argument("--top", type=int, default=25,
                    help="rank length for §1/§2/§3 (default 25)")
    ap.add_argument("--min-coupling", default="0",
                    help="ignore Cc pairs below this (e.g. 1f, 100a; default 0)")
    ap.add_argument("--drilldown", type=int, default=5,
                    help="§6 drill down on top-N Cg-heavy nets (default 5)")
    ap.add_argument("--trace", action="append", default=[],
                    metavar="SPEC",
                    help="driving-point trace spec "
                         "'label:src1,src2->snk1,snk2' (repeatable)")
    ap.add_argument("--within-net", default=None, metavar="NETS",
                    help="pin-to-pin R distribution WITHIN each given "
                         "canonical net (comma-separated). For each net, "
                         "finds every device pin touching it, then solves "
                         "for effective R between sampled pins via the "
                         "parasitic R mesh.  The headline engineering "
                         "view for buffers / reference rails.")
    ap.add_argument("--within-net-max-pins", type=int, default=60,
                    help="cap on sampled pins per net (default 60 → "
                         "~1770 pair solves).  Deterministic stride "
                         "sampling can miss entire array-structure classes "
                         "(e.g. all gate pins of a 20-finger cross-coupler "
                         "if stride aligns with period); bump to 100+ when "
                         "tails look too narrow to be real.")
    ap.add_argument("--within-net-top-pairs", type=int, default=10,
                    help="top-K largest-R pairs to show per net (default 10)")
    ap.add_argument("--rmatrix", default=None, metavar="NODES",
                    help="pairwise R-matrix between the given nodes "
                         "(comma-separated), or 'ports' to use DUT ports. "
                         "For pure-parasitic extracts, port-to-port is "
                         "usually +inf (no direct wire link); consider "
                         "--within-net instead.")
    ap.add_argument("--mismatch", action="store_true",
                    help="include §4 P/N differential mismatch check. "
                         "Off by default — it auto-pairs by name suffix "
                         "and false-flags on designs where SETP/SETN "
                         "or similar names aren't real diff pairs.")
    ap.add_argument("--dut", default=None,
                    help="force a DUT subckt name (else auto-pick)")
    ap.add_argument("--format", default=None, choices=("mrpp", "spectre"),
                    help="force format (else auto-detect)")
    ap.add_argument("-o", "--output", default=None,
                    help="write report to this path (else stdout)")
    ap.add_argument("--no-cache", action="store_true",
                    help="skip the pickle parse cache (force re-parse)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.netlist):
        raise SystemExit(f"no such file: {args.netlist}")

    kw = {}
    if args.dut:
        kw["dut_name"] = args.dut
    circuit = load_or_parse(
        args.netlist,
        use_cache=not args.no_cache,
        parse_kw=kw,
        fmt=args.format,
    )

    traces = [parse_trace_spec(s) for s in args.trace]
    min_cc = parse_si_threshold(args.min_coupling)

    # Resolve --rmatrix argument: "ports" keyword → use DUT ports.
    rmatrix_nodes: list[str] = []
    if args.rmatrix:
        if args.rmatrix.strip().lower() == "ports":
            rmatrix_nodes = list(circuit.ports)
            if not rmatrix_nodes:
                print("# WARNING: --rmatrix ports requested but DUT has no ports "
                      "(flat netlist?). Skipping R-matrix.", file=sys.stderr)
        else:
            rmatrix_nodes = [x.strip() for x in args.rmatrix.split(",") if x.strip()]

    within_net_nets: list[str] = []
    if args.within_net:
        within_net_nets = [x.strip() for x in args.within_net.split(",") if x.strip()]

    report = build_report(
        circuit,
        top=args.top,
        min_coupling=min_cc,
        drilldown_n=args.drilldown,
        trace_pairs=traces,
        rmatrix_nodes=rmatrix_nodes,
        within_net_nets=within_net_nets,
        within_net_max_pins=args.within_net_max_pins,
        within_net_top_pairs=args.within_net_top_pairs,
        include_mismatch=args.mismatch,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"wrote {args.output}  ({len(report.splitlines())} lines, "
              f"{len(report)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
