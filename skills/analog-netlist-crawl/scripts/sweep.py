#!/usr/bin/env python3
"""Fused multi-algorithm prescribe sweep.

Parses the netlist and does the expensive upstream analysis (canonical
map, R-component BFS, G/C assembly, LU factorization, moment series)
ONCE, then synthesizes a Foster ladder for every requested (algo,
order) combination.  The non-Foster analysis is 100% shared across
variants, so sweeping N configurations costs ~= a single prescribe
plus N · <1 s of synthesis — not N · prescribe.

Usage::

    # Simplest — just the 2 configs that give distinct results
    # (order0 + PRIMA-1):
    python sweep.py <post_layout.scs> \\
        --dut L4_OTA1_STAGE1 \\
        --nets "VINP,VINN,VOUTP,VOUTN,VDD,VSS,..." \\
        --out-dir output/netlist-crawl/L4_OTA1_STAGE1/

    # Full methodological sweep (all 4 algorithms × usable orders):
    python sweep.py ... --preset all

    # Explicit configs:
    python sweep.py ... --configs "order0:0,prima:1,prima:3"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from adapters import parse_netlist
from kernels.r_network import (
    _build_adjacency, _build_canonical_node_map, _component_of,
    effective_resistance, per_instance_port_r, _compute_position_map,
)
from kernels.mor import (foster_via_algo,
                         _prima_arnoldi_and_e, prima_foster_slice)
from parse_cache import load_or_parse


def _parse_configs(spec: str) -> list[tuple[str, int]]:
    out = []
    for token in spec.split(","):
        token = token.strip()
        if not token: continue
        if ":" not in token:
            raise SystemExit(f"--configs entry {token!r} must be algo:order")
        algo, order_s = token.split(":", 1)
        order = int(order_s)
        out.append((algo.strip(), order))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("netlist")
    ap.add_argument("--dut", default=None)
    ap.add_argument("--format", default=None, choices=("mrpp", "spectre"))
    ap.add_argument("--nets", required=True)
    ap.add_argument("--extra-resolve-nets", default="")
    ap.add_argument("--configs", default=None,
                    help="comma-separated algo:order pairs, e.g. "
                         "'order0:0,prima:1'.  If omitted, defaults to "
                         "the value selected by --preset.  Only "
                         "order0:0 and prima:1 are exposed — see "
                         "kernels/mor.py for why other variants were "
                         "dropped.")
    ap.add_argument("--preset", default="minimal",
                    choices=("minimal",),
                    help="shortcut config set when --configs is not "
                         "given.  Only 'minimal' = 'order0:0,prima:1' is "
                         "exposed — that's the full useful set.  After "
                         "an empirical sweep of (order0, elmore, awe 1..4, "
                         "prima 1..4) on AMP and OTA test circuits, only "
                         "these two produced distinct numerical results "
                         "with stable behaviour; the rest collapsed onto "
                         "one of them or blew up numerically.  Use "
                         "--configs for custom mixes.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--out-prefix", default="rc_")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    presets = {
        "minimal": "order0:0,prima:1",
    }
    cfg_str = args.configs if args.configs else presets[args.preset]
    print(f"# configs string: {cfg_str}", file=sys.stderr)
    configs = _parse_configs(cfg_str)
    nets = [x.strip() for x in args.nets.split(",") if x.strip()]
    if not nets:
        raise SystemExit("--nets is required")
    outdir = Path(args.out_dir); outdir.mkdir(parents=True, exist_ok=True)

    # Validate: only order0 and prima are exposed configs.
    for algo, order in configs:
        if algo not in ("order0", "prima"):
            raise SystemExit(
                f"unsupported algo {algo!r}.  Only 'order0' and 'prima' "
                "remain after empirical pruning (see mor.py docstring).")
    need_prima = any(a == "prima" for a, _ in configs)
    max_prima_order = max((o for a, o in configs if a == "prima"), default=0)

    print(f"# configs: {configs}", file=sys.stderr)
    print(f"# need_prima={need_prima}, max_prima_order={max_prima_order}",
          file=sys.stderr)

    # ---- parse (cached) ----
    t0 = time.perf_counter()
    kw = {}
    if args.dut: kw["dut_name"] = args.dut
    circuit = load_or_parse(args.netlist, use_cache=not args.no_cache,
                            parse_kw=kw, fmt=args.format,
                            log=lambda *a, **kw: print(*a,
                                **{k: v for k, v in kw.items() if k != 'file'},
                                file=sys.stderr))
    print(f"# parse+cache: {time.perf_counter()-t0:.2f}s", file=sys.stderr)

    # ---- adjacency + canonical map (shared) ----
    t0 = time.perf_counter()
    adj = _build_adjacency(circuit)

    # Auto-discover extra nets (same logic as prescribe.py).
    if args.extra_resolve_nets == "-":
        extra = []
    elif args.extra_resolve_nets.strip():
        extra = [x.strip() for x in args.extra_resolve_nets.split(",") if x.strip()]
    else:
        _ANON = [re.compile(p) for p in (
            r"^c_\d+_[np]$", r"^_net\d*$", r"^\d+$", r".+_[dgsb]$")]
        seen = set()
        for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
            for e in edges:
                for n in e[:2]:
                    c = circuit.canonical(n)
                    if c and not any(r.match(c) for r in _ANON):
                        seen.add(c)
        extra = sorted(seen - set(nets))
    resolve_map = _build_canonical_node_map(circuit, nets + extra, adj=adj)
    print(f"# canonical map: {time.perf_counter()-t0:.2f}s "
          f"({len(resolve_map)} nodes over {len(nets)+len(extra)} nets)",
          file=sys.stderr)

    # ---- per-net shared analysis ----
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    from collections import defaultdict

    net_shared: dict = {}     # {net: {...}}
    net_moments: dict = {}    # {net: {pin_key: moments}} (only if need_moments)

    # --- Pre-compute all R-components + bucket edges once -----
    # Walk every net's R-seeds once, collect comp per net.  Then in a
    # single pass over each edge list, drop each edge into the bucket
    # of the net whose comp contains its endpoints.  Avoids re-filtering
    # the global edge lists N_nets times (which on OTA was 15 × 581k
    # iterations ≈ 8.7 M Python-level checks).
    t_net = time.perf_counter()
    comps_by_net: dict[str, set[str]] = {}
    for net in nets:
        seeds = set()
        for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
            for e in edges:
                if circuit.canonical(e[0]) == net: seeds.add(e[0])
                if circuit.canonical(e[1]) == net: seeds.add(e[1])
        comps_by_net[net] = _component_of(adj, seeds) if seeds else set()

    # Node → net (first-hit-wins, same as batch_prescription convention)
    node_to_net_full: dict[str, str] = {}
    for net, comp in comps_by_net.items():
        for n in comp:
            node_to_net_full.setdefault(n, net)

    # Pre-bucket edges: O(|edges|) once.
    bucket_r = {n: [] for n in nets}
    bucket_cg = {n: [] for n in nets}
    bucket_cc = {n: [] for n in nets}
    for e in circuit.r_edges:
        if e[2] <= 0: continue
        ha = node_to_net_full.get(e[0]); hb = node_to_net_full.get(e[1])
        if ha is not None and ha == hb:
            bucket_r[ha].append(e)
    for e in circuit.cg_edges:
        if e[2] <= 0: continue
        ha = node_to_net_full.get(e[0]); hb = node_to_net_full.get(e[1])
        if ha is not None:
            bucket_cg[ha].append(e)
        elif hb is not None:
            bucket_cg[hb].append(e)
    for e in circuit.cc_edges:
        if e[2] <= 0: continue
        ha = node_to_net_full.get(e[0]); hb = node_to_net_full.get(e[1])
        if ha is not None:
            bucket_cc[ha].append(e)
        # If only other end is in a net, add to that net's bucket too
        # (the moment solver treats external Cc as AC-ground cap).
        if hb is not None and hb != ha:
            bucket_cc[hb].append(e)
    print(f"# edge pre-bucket: {time.perf_counter()-t_net:.2f}s", file=sys.stderr)
    t_net = time.perf_counter()

    for net in nets:
        comp = comps_by_net[net]
        if not comp:
            net_shared[net] = None; continue

        comp_r_edges  = bucket_r[net]
        comp_cg_edges = bucket_cg[net]
        comp_cc_edges = bucket_cc[net]

        pin_entries = []
        for d in circuit.devices:
            ml = d.model.lower()
            if not (ml.endswith("_mac") or "nch" in ml or "pch" in ml): continue
            for role, sn in d.pins.items():
                if sn not in comp: continue
                pin_entries.append({
                    "instance": d.name, "role": role,
                    "subnode": sn, "key": f"{d.name}.{role}",
                })
        port_nodes = {net} if net in comp else set()
        all_pin_nodes = {e["subnode"] for e in pin_entries}
        r_eff = (effective_resistance(circuit, port_nodes, all_pin_nodes,
                                      _comp_edges=comp_r_edges, _adj=adj)
                 if port_nodes and all_pin_nodes else float("inf"))
        reduced_cache: dict = {}
        per_pin = (per_instance_port_r(
                       circuit, port_nodes,
                       {e["key"]: {e["subnode"]} for e in pin_entries},
                       comp=comp, _comp_edges=comp_r_edges,
                       _reduced_cache=reduced_cache)
                   if port_nodes and pin_entries else {})

        # Star decomposition
        r_common = 0.0; r_branch = {}
        finite_r = {k: v for k, v in per_pin.items()
                    if v != float("inf") and v > 0}
        N = len(finite_r)
        if N >= 2 and r_eff != float("inf") and r_eff > 0:
            mean_r = sum(finite_r.values()) / N
            r_common = max((N * r_eff - mean_r) / (N - 1), 0.0)
            r_common = min(r_common, min(finite_r.values()))
            r_branch = {k: max(v - r_common, 0.0) for k, v in finite_r.items()}
        elif N == 1:
            r_branch = dict(finite_r)

        pos = _compute_position_map(
            circuit, comp, port_nodes, all_pin_nodes,
            _comp_edges=comp_r_edges) \
              if (port_nodes and all_pin_nodes and r_eff not in (float("inf"),) and r_eff > 0) else {}

        # PRIMA matrices.  Reuse LU from reduced_cache when available
        # (same G_nn factorisation as per_instance_port_r).
        prima_mats = None
        if need_prima and port_nodes and pin_entries:
            nodes = sorted(comp)
            idx = {n: i for i, n in enumerate(nodes)}
            N0 = len(nodes)
            rows, cols, vals = [], [], []
            for e in comp_r_edges:
                ia = idx.get(e[0]); ib = idx.get(e[1])
                if ia is None or ib is None or ia == ib: continue
                g = 1.0 / e[2]
                rows += [ia, ib, ia, ib]
                cols += [ia, ib, ib, ia]
                vals += [g, g, -g, -g]
            G_full = sp.coo_matrix((vals, (rows, cols)), shape=(N0, N0)).tocsc()
            rows, cols, vals = [], [], []
            for e in comp_cg_edges:
                ia = idx.get(e[0]); ib = idx.get(e[1])
                if ia is not None and ib is None:
                    rows.append(ia); cols.append(ia); vals.append(e[2])
                elif ib is not None and ia is None:
                    rows.append(ib); cols.append(ib); vals.append(e[2])
                elif ia is not None and ib is not None and ia != ib:
                    rows += [ia, ib, ia, ib]
                    cols += [ia, ib, ib, ia]
                    vals += [e[2], e[2], -e[2], -e[2]]
            for e in comp_cc_edges:
                ia = idx.get(e[0]); ib = idx.get(e[1])
                if ia is None and ib is None: continue
                if ia is None:
                    rows.append(ib); cols.append(ib); vals.append(e[2])
                elif ib is None:
                    rows.append(ia); cols.append(ia); vals.append(e[2])
                elif ia != ib:
                    rows += [ia, ib, ia, ib]
                    cols += [ia, ib, ib, ia]
                    vals += [e[2], e[2], -e[2], -e[2]]
            C_full = (sp.coo_matrix((vals, (rows, cols)), shape=(N0, N0)).tocsc()
                      if vals else sp.csc_matrix((N0, N0)))
            port_set = {idx[n] for n in port_nodes if n in idx}
            interior = [i for i in range(N0) if i not in port_set]
            int_arr = np.array(interior)
            reduce_map = {full: red for red, full in enumerate(interior)}
            G_nn = G_full[int_arr][:, int_arr].tocsc()
            C_nn = C_full[int_arr][:, int_arr].tocsc()
            pin_int_idx = {}
            for pe in pin_entries:
                f = idx.get(pe["subnode"])
                if f is not None and f in reduce_map:
                    pin_int_idx[pe["key"]] = reduce_map[f]
            # Reuse the shared LU when available (from per_instance_port_r
            # / moments).  Otherwise factorise once per net.
            prima_lu = reduced_cache.get("lu")
            if prima_lu is None:
                try:
                    prima_lu = spla.splu(G_nn)
                except Exception:
                    prima_lu = None
            # Pre-compute Arnoldi basis + e projection at MAX PRIMA
            # order, ONCE per pin.  Reused for every PRIMA config via
            # prima_foster_slice (O(k³) projection, vs full Arnoldi
            # which costs k back-subs per pin).  This is the biggest
            # win when the sweep includes multiple PRIMA orders.
            prima_basis: dict = {}
            if max_prima_order >= 1:
                for pe in pin_entries:
                    pin_i = pin_int_idx.get(pe["key"])
                    if pin_i is None:
                        prima_basis[pe["key"]] = None
                        continue
                    try:
                        res = _prima_arnoldi_and_e(
                            G_nn, C_nn, pin_i, max_prima_order, lu=prima_lu)
                    except Exception:
                        res = None
                    prima_basis[pe["key"]] = res  # (Vq, e_proj) or None
            prima_mats = (G_nn, C_nn, pin_int_idx, prima_lu, prima_basis)

        net_shared[net] = dict(
            comp=comp, pin_entries=pin_entries,
            port_nodes=port_nodes, r_eff=r_eff,
            per_pin_r=per_pin, r_common=r_common, r_branch=r_branch,
            position=pos, comp_cc_edges=comp_cc_edges,
            prima_mats=prima_mats,
        )

    print(f"# per-net analysis: {time.perf_counter()-t_net:.2f}s", file=sys.stderr)

    # ---- Inter-net Cc (shared) ----
    node_to_net: dict[str, str] = {}
    for net, d in net_shared.items():
        if d is None: continue
        for n in d["comp"]:
            node_to_net.setdefault(n, net)

    external_all = {n: defaultdict(float) for n in nets if net_shared.get(n)}
    external_driver = {n: defaultdict(float) for n in nets if net_shared.get(n)}
    external_load = {n: defaultdict(float) for n in nets if net_shared.get(n)}
    inter: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"DD": 0.0, "DL": 0.0, "LD": 0.0, "LL": 0.0})

    def _resolve(n: str) -> str:
        return resolve_map.get(n) or circuit.canonical(n)

    for a, b, v, _ in circuit.cc_edges:
        if v <= 0: continue
        ha = node_to_net.get(a); hb = node_to_net.get(b)
        if ha and hb:
            if ha == hb: continue
            pa = net_shared[ha]["position"].get(a, 0.5)
            pb = net_shared[hb]["position"].get(b, 0.5)
            if ha > hb:
                ha, hb = hb, ha; pa, pb = pb, pa
            key = (ha, hb)
            inter[key]["DD"] += v*(1-pa)*(1-pb)
            inter[key]["DL"] += v*(1-pa)*pb
            inter[key]["LD"] += v*pa*(1-pb)
            inter[key]["LL"] += v*pa*pb
            continue
        if ha:
            host = ha; internal = a; peer = _resolve(b)
        elif hb:
            host = hb; internal = b; peer = _resolve(a)
        else:
            continue
        p = net_shared[host]["position"].get(internal, 0.5)
        external_all[host][peer] += v
        external_driver[host][peer] += v*(1-p)
        external_load[host][peer] += v*p

    # ---- for each config, synthesize Foster + emit JSON ----
    for algo, order in configs:
        t_syn = time.perf_counter()
        prescriptions = []
        for net in nets:
            sh = net_shared.get(net)
            if sh is None:
                prescriptions.append({
                    "net": net, "component_size": 0, "pin_entries": [],
                    "r_eff": float("inf"), "per_pin_r": {}, "r_common": 0.0,
                    "r_branch": {}, "foster": {},
                    "algo": algo, "order": order,
                    "cc_distribution": {}, "cc_driver_side": {}, "cc_load_side": {},
                    "total_external_cc": 0.0,
                })
                continue
            foster: dict = {}
            if algo == "order0" or not sh["pin_entries"]:
                pass  # legacy star path (foster stays empty, inject uses r_branch)
            elif algo == "prima" and sh["prima_mats"]:
                G_nn_, C_nn_, pin_int, lu_, prima_basis = sh["prima_mats"]
                for pe in sh["pin_entries"]:
                    k = pe["key"]
                    basis = prima_basis.get(k)
                    if basis is None:
                        foster[k] = None
                        continue
                    Vq, e_proj = basis
                    try:
                        foster[k] = prima_foster_slice(
                            G_nn_, C_nn_, Vq, e_proj, order)
                    except Exception:
                        foster[k] = None
            prescriptions.append({
                "net": net, "component_size": len(sh["comp"]),
                "pin_entries": sh["pin_entries"],
                "r_eff": sh["r_eff"], "per_pin_r": dict(sh["per_pin_r"]),
                "r_common": sh["r_common"], "r_branch": dict(sh["r_branch"]),
                "foster": foster,
                "algo": algo, "order": order,
                "cc_distribution": dict(sorted(external_all[net].items(),
                                               key=lambda kv: -kv[1])),
                "cc_driver_side": dict(sorted(external_driver[net].items(),
                                              key=lambda kv: -kv[1])),
                "cc_load_side":   dict(sorted(external_load[net].items(),
                                              key=lambda kv: -kv[1])),
                "total_external_cc": sum(external_all[net].values()),
            })
        inter_list = [
            {"net_a": na, "net_b": nb, "DD": w["DD"], "DL": w["DL"],
             "LD": w["LD"], "LL": w["LL"],
             "total": w["DD"]+w["DL"]+w["LD"]+w["LL"]}
            for (na, nb), w in inter.items()
        ]
        inter_list.sort(key=lambda x: -x["total"])
        tag = f"{algo}{order}" if algo != "order0" else "order0"
        out = outdir / f"{args.out_prefix}{tag}.json"

        def _safe(obj):
            if isinstance(obj, float):
                if obj == float("inf"):  return "inf"
                if obj == float("-inf"): return "-inf"
                if obj != obj:            return "nan"
            return obj
        doc = {
            "source": os.path.abspath(args.netlist),
            "dut": circuit.dut,
            "format": circuit.metadata.get("format", ""),
            "prescriptions": prescriptions,
            "inter_net_couplings": inter_list,
        }
        out.write_text(json.dumps(doc, indent=2, default=_safe))
        print(f"  {tag}: wrote {out}  ({time.perf_counter()-t_syn:.2f}s synth)",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
