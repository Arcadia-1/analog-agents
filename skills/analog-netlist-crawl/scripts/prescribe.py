#!/usr/bin/env python3
"""Extract an R + Cc prescription from a post-layout netlist.

One job only: read the post-layout / extracted netlist, compute an
in-memory prescription for each requested canonical net (effective
driver-to-load R + coupling-Cc distribution), and emit JSON.

This CLI does NOT run any simulation and does NOT modify the schematic.
Its output is a durable prescription document that ``inject.py``
consumes to produce a modified schematic.

Usage::

    python prescribe.py <post_layout.scs> --dut L4_OTA1_STAGE1 \\
        --nets "V1P,V1N,VOUTP,VOUTN,VDD,VSS,net_tail" \\
        -o rc_model.json

All listed nets are processed uniformly — no signal vs rail distinction.
For each net, the Laplacian solver finds every MOS pin whose subnode
lands on the net's R-component (regardless of D/G/S/B role) and
computes per-pin driving-point R from the schematic-level port node
(the bare canonical subnode) to that individual pin, with all other
pins floating.  The mesh is then decomposed into a 2-level star:

    <net> port ──R_common── hub ─┬── R_branch_i ── pin_i (renamed)
                                   ├── R_branch_j ── pin_j (renamed)
                                   └── ...

This preserves both the aggregate cluster R and per-finger spatial
asymmetry.  ``inject.py`` renames each MOS pin to a unique
``<net>_<instance>_<role>_post`` and drops in the star.

JSON shape::

    {
      "source": "...", "dut": "...",
      "prescriptions": [
        { "net": "VDD",
          "component_size": 226,
          "r_eff": 4.01,
          "r_common": 3.3,
          "r_branch": {"M3.S": 1.7, "M3.B": 1.7, "M4.S": 1.8, ...},
          "per_pin_r": {"M3.S": 5.0, ...},
          "pin_entries": [{"instance":"M3","role":"S","key":"M3.S", ...}, ...],
          "cc_distribution": {"VOUT": 2.3e-16, ...} },
        ...
      ]
    }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from adapters import parse_netlist
from kernels import batch_prescription, _build_canonical_node_map
from kernels.r_network import _build_adjacency
from parse_cache import load_or_parse


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("netlist", help="post-layout / extracted .scs")
    ap.add_argument("--dut", default=None,
                    help="DUT subckt name (auto-detected if omitted)")
    ap.add_argument("--format", default=None, choices=("mrpp", "spectre"),
                    help="force input format (default: auto-detect)")
    ap.add_argument("--nets", default="",
                    help="comma-separated canonical nets to prescribe — "
                         "signal nets, power rails, internal tails, etc. "
                         "processed uniformly (every MOS pin on each "
                         "mesh gets a per-pin R stub).")
    # Back-compat aliases (deprecated — they all feed into --nets).
    ap.add_argument("--signal-nets", default="", dest="signal_nets_compat",
                    help="deprecated alias; use --nets")
    ap.add_argument("--rail-nets", "--rails", default="", dest="rail_nets_compat",
                    help="deprecated alias; use --nets")
    ap.add_argument("--extra-resolve-nets", default="",
                    help="comma-separated extra canonical nets to use ONLY "
                         "for resolving the other end of Cc edges "
                         "(e.g. 'VDD,VSS,VBN,VBP').  These improve Cc "
                         "attribution but don't get their own prescription.  "
                         "Default: auto-discover every canonical name that "
                         "appears anywhere in the circuit (pass '-' to "
                         "disable auto-discovery).")
    ap.add_argument("-o", "--output", required=True,
                    help="output JSON path")
    ap.add_argument("--no-cache", action="store_true",
                    help="skip the pickle parse cache (force re-parse)")
    ap.add_argument("--algo", default="order0",
                    choices=("order0", "elmore", "awe", "prima"),
                    help="per-pin reduction algorithm. 'order0' = pure R "
                         "(DC only). 'elmore' = single-pole RC (Elmore 1948). "
                         "'awe' = [k-1/k] Padé (Pillage & Rohrer 1990). "
                         "'prima' = Arnoldi Krylov projection "
                         "(Odabasioglu et al. 1998).")
    ap.add_argument("--order", type=int, default=0,
                    help="reduction order (number of poles) for AWE / PRIMA. "
                         "Ignored for order0 and elmore.")
    args = ap.parse_args(argv)
    if args.algo == "order0":
        args.order = 0
    elif args.algo == "elmore":
        args.order = 1
    elif args.order < 1:
        args.order = 1

    if not os.path.exists(args.netlist):
        raise SystemExit(f"no such file: {args.netlist}")

    # Merge --nets with the deprecated --signal-nets / --rail-nets aliases.
    parts: list[str] = []
    for raw in (args.nets, args.signal_nets_compat, args.rail_nets_compat):
        parts += [x.strip() for x in raw.split(",") if x.strip()]
    # Preserve order, dedupe.
    seen: set[str] = set()
    nets: list[str] = []
    for n in parts:
        if n not in seen:
            nets.append(n); seen.add(n)
    if not nets:
        raise SystemExit("pass at least one net via --nets")

    kw = {}
    if args.dut:
        kw["dut_name"] = args.dut
    circuit = load_or_parse(args.netlist, use_cache=not args.no_cache,
                            parse_kw=kw, fmt=args.format,
                            log=lambda *a, **kw: print(*a, **{k:v for k,v in kw.items() if k != 'file'}, file=sys.stderr))

    # Resolve map: which canonical nets to use for attributing the other
    # end of Cc edges.  Default is "every canonical name that shows up
    # in the netlist" — anything less than that leaves Cc mass orphaned
    # in anonymous `c_NNN_*` subnodes that inject.py will drop.
    if args.extra_resolve_nets == "-":
        extra = []
    elif args.extra_resolve_nets.strip():
        extra = [x.strip() for x in args.extra_resolve_nets.split(",") if x.strip()]
    else:
        # Auto-discover: every distinct non-anonymous canonical name
        # visible in R/Cg/Cc edges.  Skips pure-anonymous patterns (c_*,
        # _net*, numeric helper locals, device-local _d/_g/_s/_b names).
        import re
        _ANON = [re.compile(p) for p in (
            r"^c_\d+_[np]$",        # Calibre mesh subnode
            r"^_net\d*$",           # Calibre pseudo-net
            r"^\d+$",               # helper-subckt local
            r".+_[dgsb]$",          # MOS local pin
        )]
        def _is_anon(n):
            return any(r.match(n) for r in _ANON)
        seen: set[str] = set()
        for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
            for e in edges:
                for n in e[:2]:
                    c = circuit.canonical(n)
                    if c and not _is_anon(c):
                        seen.add(c)
        extra = sorted(seen - set(nets))
        print(f"  auto-discovered {len(extra)} extra canonical nets for Cc resolve",
              file=sys.stderr)

    # Build node → canonical map over nets + extra
    adj = _build_adjacency(circuit)
    resolve_map = _build_canonical_node_map(circuit, nets + extra, adj=adj)

    batch = batch_prescription(circuit, nets,
                               algo=args.algo, order=args.order,
                               resolve_map=resolve_map, _adj=adj)

    # Sort Cc distributions descending for readability
    for rx in batch["prescriptions"]:
        for k in ("cc_distribution", "cc_driver_side", "cc_load_side"):
            rx[k] = dict(sorted(rx[k].items(), key=lambda kv: -kv[1]))
        r_str = (f"{rx['r_eff']:.2f} Ω" if rx["r_eff"] != float("inf")
                 else "inf")
        rc = rx.get("r_common", 0.0)
        print(f"  {rx['net']}: R_eff = {r_str} (R_common={rc:.2f}Ω), "
              f"{len(rx.get('pin_entries') or [])} MOS pins, "
              f"ΣCc external = {rx['total_external_cc']*1e15:.1f} fF",
              file=sys.stderr)

    # Inter-net couplings (between two prescribed nets) — deduplicated
    if batch["inter_net_couplings"]:
        print(f"  inter-net Cc (deduplicated, 4-way split):", file=sys.stderr)
        for ic in batch["inter_net_couplings"]:
            print(f"    {ic['net_a']:<8s} ↔ {ic['net_b']:<8s} "
                  f"total = {ic['total']*1e15:.2f} fF",
                  file=sys.stderr)

    result = {
        "source": os.path.abspath(args.netlist),
        "dut": circuit.dut,
        "format": circuit.metadata.get("format", ""),
        "prescriptions": batch["prescriptions"],
        "inter_net_couplings": batch["inter_net_couplings"],
    }

    # Write JSON (convert inf to string "inf" since JSON doesn't grok it)
    def _json_safe(obj):
        if isinstance(obj, float):
            if obj == float("inf"):  return "inf"
            if obj == float("-inf"): return "-inf"
            if obj != obj:            return "nan"
        return obj

    Path(args.output).write_text(
        json.dumps(result, indent=2, default=_json_safe),
        encoding="utf-8",
    )
    print(f"wrote {args.output}  ({len(result['prescriptions'])} prescription(s))",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
