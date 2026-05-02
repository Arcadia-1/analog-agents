"""R-network kernel: effective resistance between arbitrary node sets.

Operates on ``Circuit.r_edges`` only.  Builds the Laplacian (conductance
matrix) over R-connected components, applies Dirichlet boundary
conditions on source/sink, and solves via sparse LU.

The one subtlety: if source and sink live in different R-connected
components (no DC path between them), the full Laplacian would be
singular.  We BFS the component containing source ∪ sink first and
restrict the solve to that subgraph — floating components are dropped.
If source ⊄ sink-component, we return ``inf``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ir import Circuit


def _build_adjacency(circuit: Circuit) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b, r, _ in circuit.r_edges:
        if r <= 0: continue
        adj[a].append(b)
        adj[b].append(a)
    return adj


def _component_of(adj: dict[str, list[str]], seeds: set[str]) -> set[str]:
    """BFS over R-edge adjacency, starting from every seed."""
    comp = set(seeds)
    stack = list(seeds)
    while stack:
        n = stack.pop()
        for nb in adj.get(n, ()):
            if nb not in comp:
                comp.add(nb)
                stack.append(nb)
    return comp


def effective_resistance(
    circuit: Circuit,
    source: Iterable[str],
    sink: Iterable[str],
    _comp_edges: list | None = None,
    _adj: dict[str, list[str]] | None = None,
) -> float:
    """DC effective resistance between ``source`` and ``sink`` node sets.

    Both arguments are iterables of node names.  Nodes within a set are
    treated as shorted together (pinned to the same voltage).  Returns
    ``+inf`` if no DC path exists and ``0.0`` if the two sets overlap.

    Multi-component handling: only keep R-connected components that
    contain AT LEAST ONE source AND AT LEAST ONE sink node.  A
    component with only source nodes (or only sink nodes) contributes
    nothing — floating from the other side's perspective — and
    including it makes the Laplacian singular.  Components with both
    are valid parallel paths and their currents add (see F3d fixture).
    """
    S = set(source)
    D = set(sink)
    if not S or not D:
        return float("inf")
    if S & D:
        return 0.0

    adj = _adj if _adj is not None else _build_adjacency(circuit)

    # Walk every seed once and label it with the component it lives in.
    # Then keep only components seen by BOTH S and D.
    seed_comp: dict[str, frozenset[str]] = {}
    cache: list[frozenset[str]] = []
    for seed in S | D:
        hit = None
        for c in cache:
            if seed in c:
                hit = c
                break
        if hit is None:
            hit = frozenset(_component_of(adj, {seed}))
            cache.append(hit)
        seed_comp[seed] = hit

    useful: set[frozenset[str]] = set()
    for c in cache:
        if (c & S) and (c & D):
            useful.add(c)
    if not useful:
        return float("inf")

    # Restrict the solve to the union of useful components — each one
    # carries independent current between its own S-subset and D-subset;
    # the solver sums them by construction.
    nodes = sorted(set().union(*useful))
    S = S & set(nodes)
    D = D & set(nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    N = len(nodes)

    # Assemble Laplacian: L[i,i] += g, L[i,j] -= g for each R edge (i,j).
    edges_iter = _comp_edges if _comp_edges is not None else circuit.r_edges
    rows, cols, vals = [], [], []
    for edge in edges_iter:
        r = edge[2]
        if r <= 0: continue
        a, b = edge[0], edge[1]
        if a not in idx or b not in idx: continue
        i, j = idx[a], idx[b]
        if i == j: continue
        g = 1.0 / r
        rows += [i, j, i, j]
        cols += [i, j, j, i]
        vals += [g, g, -g, -g]
    L = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsr()

    # Dirichlet BC: replace row k with 1-on-diagonal, RHS = V_target.
    L = L.tolil()
    b_vec = np.zeros(N)
    for n in S:
        k = idx[n]
        L.rows[k] = [k]; L.data[k] = [1.0]; b_vec[k] = 1.0
    for n in D:
        k = idx[n]
        L.rows[k] = [k]; L.data[k] = [1.0]; b_vec[k] = 0.0
    V = spla.spsolve(L.tocsr(), b_vec)

    # Current injected at source = Σ over edges (src_node ↔ non-src) of
    # (V_src - V_neighbor) / r.  Driving voltage is 1 V (1→0), so
    # R_eff = 1 / I_inj.
    S_idx = {idx[n] for n in S}
    I_inj = 0.0
    for edge in edges_iter:
        r = edge[2]
        if r <= 0: continue
        a, b = edge[0], edge[1]
        if a not in idx or b not in idx: continue
        ia, ib = idx[a], idx[b]
        if ia in S_idx and ib not in S_idx:
            I_inj += (V[ia] - V[ib]) / r
        elif ib in S_idx and ia not in S_idx:
            I_inj += (V[ib] - V[ia]) / r
    if I_inj <= 1e-30:
        return float("inf")
    return 1.0 / I_inj


def per_instance_port_r(
    circuit: Circuit,
    port_nodes: set[str],
    instance_pins: dict[str, set[str]],
    comp: set[str] | None = None,
    _comp_edges: list | None = None,
    _lu=None,
    _reduced_cache: dict | None = None,
) -> dict[str, float]:
    """Per-instance driving-point R from ``port_nodes`` to each instance's
    pin set.

    ``instance_pins`` is ``{instance_name: {subnode1, subnode2, ...}}``.
    For each instance we solve for the effective R between ``port_nodes``
    (source, voltage 1) and that instance's pins (sink, voltage 0), with
    all other instances FLOATING (not shorted — their mesh subnodes
    participate passively in current redistribution).

    Uses one Laplacian factorisation over the shared R-component and
    solves N RHS vectors — so cost is ~1 factor + N back-substitutions,
    not N independent solves.

    Returned dict maps instance_name → R (Ω), ``+inf`` if no DC path.
    """
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    if not port_nodes or not instance_pins:
        return {}

    # Determine node set over which we solve.
    if comp is None:
        adj = _build_adjacency(circuit)
        seeds = set(port_nodes)
        for pins in instance_pins.values():
            seeds |= pins
        comp = _component_of(adj, seeds)
    port_nodes = port_nodes & comp
    if not port_nodes:
        return {inst: float("inf") for inst in instance_pins}

    nodes = sorted(comp)
    idx = {n: i for i, n in enumerate(nodes)}
    N = len(nodes)

    # Laplacian: iterate edges restricted to this comp if pre-filtered,
    # else filter globally.  For big global netlists this is the hot loop.
    edges_iter = _comp_edges if _comp_edges is not None else circuit.r_edges
    rows, cols, vals = [], [], []
    for edge in edges_iter:
        r = edge[2]
        if r <= 0: continue
        ia = idx.get(edge[0]); ib = idx.get(edge[1])
        if ia is None or ib is None or ia == ib: continue
        g = 1.0 / r
        rows += [ia, ib, ia, ib]
        cols += [ia, ib, ib, ia]
        vals += [g, g, -g, -g]
    L = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()

    # We need the sub-Laplacian with port rows/cols removed.  Then for
    # each instance, pin its own pins to 0 and pin port as +1V → solve
    # for interior voltages, compute injected current at port.
    # FAST PATH: port is Dirichlet (V=0), each pin gets a unit-current
    # injection (Neumann source), all other nodes float with zero
    # net current.  Then V[pin_i] = effective R from pin_i to port with
    # every other pin open.  Reduced Laplacian is the SAME for all pins,
    # so we factor ONCE and solve N RHS vectors by back-substitution.
    #
    # This replaces the former "pin=Dirichlet V=0, port=V=1, solve per
    # pin" formulation which required a fresh factorisation per pin.
    port_idx = {idx[n] for n in port_nodes}
    interior = [i for i in range(N) if i not in port_idx]
    if not interior:
        return {inst: 0.0 for inst in instance_pins}
    interior_arr = np.array(interior)
    reduce_map = {full_i: red_i for red_i, full_i in enumerate(interior)}

    lu = _lu
    if lu is None:
        L_reduced = L[interior_arr][:, interior_arr].tocsc()
        try:
            lu = spla.splu(L_reduced)
        except Exception:
            return {inst: float("inf") for inst in instance_pins}
    # Publish the factorisation + reduction for caller reuse (e.g.
    # compute_port_to_pin_moments, PRIMA).
    if _reduced_cache is not None:
        _reduced_cache.setdefault("lu", lu)
        _reduced_cache.setdefault("interior", interior)
        _reduced_cache.setdefault("interior_arr", interior_arr)
        _reduced_cache.setdefault("reduce_map", reduce_map)
        _reduced_cache.setdefault("idx", idx)
        _reduced_cache.setdefault("nodes", nodes)

    result: dict[str, float] = {}
    # Group instances by their pin set — we can solve multiple at once
    # by stacking RHS columns.
    insts_in_order = []
    rhs_cols = []
    for inst, pin_set in instance_pins.items():
        pin_nodes = pin_set & comp
        if not pin_nodes:
            result[inst] = float("inf")
            continue
        # Multi-pin instance: pins shorted to a single effective node
        # ≈ distribute the injected 1A equally across pin nodes.  This
        # is the Thévenin R of the cluster vs. port with others open.
        share = 1.0 / len(pin_nodes)
        col = np.zeros(L_reduced.shape[0])
        for sn in pin_nodes:
            full_i = idx.get(sn)
            if full_i is None or full_i not in reduce_map:
                continue
            col[reduce_map[full_i]] += share
        insts_in_order.append((inst, list(pin_nodes)))
        rhs_cols.append(col)

    if not rhs_cols:
        return result

    # Batched solve: one matrix of N_rhs columns
    RHS = np.column_stack(rhs_cols)
    V = lu.solve(RHS)   # shape (Ninterior, N_rhs)

    for col_i, (inst, pin_nodes) in enumerate(insts_in_order):
        # V at pin nodes with the 1A injection = R_eff (volts per amp).
        # For multi-pin cluster: take the avg (they're shorted in the limit).
        vs = []
        for sn in pin_nodes:
            full_i = idx.get(sn)
            if full_i is None or full_i not in reduce_map:
                continue
            vs.append(V[reduce_map[full_i], col_i])
        result[inst] = float(np.mean(vs)) if vs else float("inf")
    return result


def _build_canonical_node_map(
    circuit: Circuit,
    interesting_nets: list[str],
    adj: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Build ``{node: canonical_net}`` by expanding each interesting net's
    R-connected component.

    Nodes in no (or multiple) expanded components keep their bare
    ``canonicalize()`` result — typically useful as-is for explicit
    named nets, and left opaque for anonymous mesh subnodes that
    couldn't be attributed.
    """
    if adj is None:
        adj = _build_adjacency(circuit)
    # Invert pass: walk every edge ONCE, classify both endpoints by
    # their canonical name, build {net: {seed_subnodes}} for only the
    # interesting nets.  This replaces the O(nets × edges × canonical)
    # outer loop that was a major bottleneck.
    interest = set(interesting_nets)
    seeds_per_net: dict[str, set[str]] = {n: set() for n in interesting_nets}
    for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
        for e in edges:
            a, b = e[0], e[1]
            ca = circuit.canonical(a)
            cb = circuit.canonical(b)
            if ca in interest:
                seeds_per_net[ca].add(a)
            if cb in interest:
                seeds_per_net[cb].add(b)

    node_to_canon: dict[str, str] = {}
    for net, seeds in seeds_per_net.items():
        if not seeds:
            continue
        comp = _component_of(adj, seeds)
        for n in comp:
            node_to_canon.setdefault(n, net)

    # Post-pass: rescue subnodes that R-BFS didn't reach but have
    # physical meaning.  These fixes target Calibre rcc extraction
    # artifacts.  They stay within the 1-port / lumped philosophy;
    # they just correct mis-classifications that were dropping real
    # capacitance into "anonymous" buckets.
    import re as _re

    # (1) Calibre substrate pseudo-nets (_net0, _net42, ...) → VSS.
    # These carry bulk coupling that the extractor generated but
    # didn't tag with a schematic name.
    if "VSS" in interest:
        pat_sub = _re.compile(r"^_net\d+$")
        for edges in (circuit.cg_edges, circuit.cc_edges):
            for e in edges:
                for n in (e[0], e[1]):
                    if pat_sub.match(n) and n not in node_to_canon:
                        node_to_canon[n] = "VSS"

    # (2) MOS body (B) pins that R-BFS didn't reach: fall back to the
    # process-conventional rail.  NMOS body → VSS; PMOS body → VDD.
    # In rcc extractions the body terminal is often coupled to the
    # rail only via bulk cap (no R-mesh connection), so the R-walk
    # map misses it even though it's physically tied to the rail.
    has_vss = "VSS" in interest
    has_vdd = "VDD" in interest
    for d in circuit.devices:
        mlc = d.model.lower()
        is_nmos = "nch" in mlc
        is_pmos = "pch" in mlc
        if not (is_nmos or is_pmos):
            continue
        b_node = d.pins.get("B")
        if b_node and b_node not in node_to_canon:
            if is_pmos and has_vdd:
                node_to_canon[b_node] = "VDD"
            elif is_nmos and has_vss:
                node_to_canon[b_node] = "VSS"

    return node_to_canon


def net_prescription(
    circuit: Circuit,
    net: str,
    *,
    pin_role: str = "any",  # deprecated, ignored
    resolve_map: dict[str, str] | None = None,
    _adj: dict[str, list[str]] | None = None,
) -> dict:
    """Full 'R + Cc' prescription for one canonical net.  Prefer
    ``batch_prescription`` for multi-net analyses (correct inter-net
    Cc handling).

    Uniform treatment: every MOS pin landing on the mesh gets its own
    per-pin R via the Laplacian (no D/G/S/B role filtering).

    Returned dict keys:
      - ``net``               : target canonical net name
      - ``component_size``    : # nodes in the R-connected mesh
      - ``pin_entries``       : list of {"instance","role","subnode","key"}
                                for every MOS pin on the mesh
      - ``per_pin_r``         : {key: driving-point R} — per-pin R from
                                port to that single pin, others floating
      - ``r_common``          : shared-path R in the star decomposition
      - ``r_branch``          : {key: branch R} — per-pin tail R in the star
      - ``r_eff``             : lumped aggregate R (port → all pins shorted)
      - ``cc_distribution``   : {peer_net: total_Cc} for external Cc
      - ``total_external_cc`` : Σ of cc_distribution values

    ``pin_role`` is kept for back-compat but ignored.
    """
    from collections import defaultdict

    adj = _adj if _adj is not None else _build_adjacency(circuit)

    # 1. Seed this net's R-connected component
    seeds = set()
    for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
        for e in edges:
            if circuit.canonical(e[0]) == net: seeds.add(e[0])
            if circuit.canonical(e[1]) == net: seeds.add(e[1])
    if not seeds:
        return {"net": net, "component_size": 0, "pin_entries": [],
                "per_pin_r": {}, "r_common": 0.0, "r_branch": {},
                "r_eff": float("inf"),
                "cc_distribution": {}, "cc_driver_side": {},
                "cc_load_side": {}, "total_external_cc": 0.0}
    comp = _component_of(adj, seeds)

    # 2. Enumerate every MOS pin on the mesh (uniform, no role filter).
    pin_entries: list[dict] = []
    for d in circuit.devices:
        mlc = d.model.lower()
        if not (mlc.endswith("_mac") or "nch" in mlc or "pch" in mlc):
            continue
        for role, sn in d.pins.items():
            if sn not in comp: continue
            pin_entries.append({
                "instance": d.name, "role": role,
                "subnode": sn, "key": f"{d.name}.{role}",
            })
    driver_nodes: set[str] = {net} if net in comp else set()
    load_nodes:   set[str] = {e["subnode"] for e in pin_entries}
    driver_source = "dut_port" if driver_nodes else "none"

    # 3. Effective driving-point R drivers → loads
    if driver_nodes and load_nodes:
        r_eff = effective_resistance(circuit, driver_nodes, load_nodes)
    else:
        r_eff = float("inf")

    # 4. Position-weighted Cc split.  Each external Cc edge has one end
    # inside the mesh; the INTERNAL node's "position" p ∈ [0, 1] along
    # the driver→load axis decides how much of that Cc should attach to
    # the pre-R (driver-side) vs post-R (load-side) node in the lumped
    # π-model:
    #   p = R_transfer(drivers, node_i) / R_cluster_short
    #     = fraction of cluster-short R already traversed to reach i
    # p = 0 at a driver, p = 1 at a load.  Cc at position p contributes
    # weight (1-p) to driver side, p to load side.
    pos: dict[str, float] = {}
    if (driver_nodes and load_nodes
            and r_eff != float("inf") and r_eff > 0):
        # One Laplacian solve: pin loads at 0, inject 1/N_d at each driver.
        nodes_sorted = sorted(comp)
        idx = {n: i for i, n in enumerate(nodes_sorted)}
        N = len(nodes_sorted)
        rows, cols, vals = [], [], []
        for a, b, r, _ in circuit.r_edges:
            if r <= 0: continue
            ia = idx.get(a); ib = idx.get(b)
            if ia is None or ib is None or ia == ib: continue
            g = 1.0 / r
            rows += [ia, ib, ia, ib]
            cols += [ia, ib, ib, ia]
            vals += [g, g, -g, -g]
        import scipy.sparse as sp
        import scipy.sparse.linalg as spla
        import numpy as np
        L = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()
        load_idx_set = {idx[n] for n in load_nodes}
        keep = np.array([i for i in range(N) if i not in load_idx_set])
        L_red = L[keep][:, keep].tocsc()
        full_to_red = {}
        j = 0
        for i in range(N):
            if i in load_idx_set: continue
            full_to_red[i] = j; j += 1
        b_vec = np.zeros(L_red.shape[0])
        share = 1.0 / len(driver_nodes)
        for d_node in driver_nodes:
            b_vec[full_to_red[idx[d_node]]] = share
        try:
            V_red = spla.splu(L_red).solve(b_vec)
            # V[driver] ≈ R_cluster_short; normalise so drivers sit at p=0,
            # loads at p=1.
            V_driver_mean = float(np.mean(
                [V_red[full_to_red[idx[d]]] for d in driver_nodes]))
            if V_driver_mean > 0:
                for i in range(N):
                    if i in load_idx_set:
                        pos[nodes_sorted[i]] = 1.0
                    else:
                        pos[nodes_sorted[i]] = 1.0 - V_red[full_to_red[i]] / V_driver_mean
                        # clamp [0,1] for numerical safety
                        p = pos[nodes_sorted[i]]
                        if p < 0: pos[nodes_sorted[i]] = 0.0
                        if p > 1: pos[nodes_sorted[i]] = 1.0
        except Exception:
            pos = {}

    # 5. Cc distribution (grouped by peer canonical), split by position.
    def _resolve(n: str) -> str:
        if resolve_map is not None and n in resolve_map:
            return resolve_map[n]
        return circuit.canonical(n)

    cc_dist: dict[str, float] = defaultdict(float)
    cc_driver: dict[str, float] = defaultdict(float)
    cc_load:   dict[str, float] = defaultdict(float)
    for a, b, v, _ in circuit.cc_edges:
        if v <= 0: continue
        a_in = a in comp
        b_in = b in comp
        internal: str | None = None
        peer: str | None = None
        if a_in and not b_in:
            internal, peer = a, _resolve(b)
        elif b_in and not a_in:
            internal, peer = b, _resolve(a)
        else:
            continue
        cc_dist[peer] += v
        # Position-weighted split; if pos unavailable, default 50/50.
        p = pos.get(internal, 0.5)
        cc_driver[peer] += v * (1.0 - p)
        cc_load[peer]   += v * p
    total_cc = sum(cc_dist.values())

    # Per-pin R + star decomposition
    per_pin_r: dict[str, float] = {}
    if driver_nodes and pin_entries:
        groups = {e["key"]: {e["subnode"]} for e in pin_entries}
        per_pin_r = per_instance_port_r(circuit, driver_nodes, groups, comp=comp)
    r_common = 0.0
    r_branch: dict[str, float] = {}
    finite_rp = {k: v for k, v in per_pin_r.items()
                 if v != float("inf") and v > 0}
    N = len(finite_rp)
    if N >= 2 and r_eff != float("inf") and r_eff > 0:
        mean_r = sum(finite_rp.values()) / N
        r_common = max((N * r_eff - mean_r) / (N - 1), 0.0)
        r_common = min(r_common, min(finite_rp.values()))
        r_branch = {k: max(v - r_common, 0.0) for k, v in finite_rp.items()}
    elif N == 1:
        r_branch = dict(finite_rp)

    return {
        "net": net,
        "component_size": len(comp),
        "pin_entries": pin_entries,
        "driver_source": driver_source,
        "r_eff": r_eff,
        "per_pin_r": per_pin_r,
        "r_common": r_common,
        "r_branch": r_branch,
        "cc_distribution": dict(cc_dist),
        "cc_driver_side":  dict(cc_driver),
        "cc_load_side":    dict(cc_load),
        "total_external_cc": total_cc,
    }


def _compute_position_map(
    circuit: Circuit,
    comp: set[str],
    driver_nodes: set[str],
    load_nodes: set[str],
    _comp_edges: list | None = None,
) -> dict[str, float]:
    """Position p(i) ∈ [0, 1] for each node in the R-component.

    p = 0 at drivers, p = 1 at loads.  Computed by one Laplacian solve
    with loads pinned at 0 and 1A/N injected at each driver.  Returns
    empty dict if the solve fails or the inputs are degenerate.
    """
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    if not driver_nodes or not load_nodes:
        return {}
    nodes_sorted = sorted(comp)
    idx = {n: i for i, n in enumerate(nodes_sorted)}
    N = len(nodes_sorted)
    edges_iter = _comp_edges if _comp_edges is not None else circuit.r_edges
    rows, cols, vals = [], [], []
    for edge in edges_iter:
        r = edge[2]
        if r <= 0: continue
        ia = idx.get(edge[0]); ib = idx.get(edge[1])
        if ia is None or ib is None or ia == ib: continue
        g = 1.0 / r
        rows += [ia, ib, ia, ib]
        cols += [ia, ib, ib, ia]
        vals += [g, g, -g, -g]
    L = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()
    load_idx_set = {idx[n] for n in load_nodes}
    keep = np.array([i for i in range(N) if i not in load_idx_set])
    L_red = L[keep][:, keep].tocsc()
    full_to_red = {}
    j = 0
    for i in range(N):
        if i in load_idx_set: continue
        full_to_red[i] = j; j += 1
    b_vec = np.zeros(L_red.shape[0])
    share = 1.0 / len(driver_nodes)
    for d_node in driver_nodes:
        b_vec[full_to_red[idx[d_node]]] = share
    try:
        V_red = spla.splu(L_red).solve(b_vec)
    except Exception:
        return {}
    V_driver_mean = float(np.mean(
        [V_red[full_to_red[idx[d]]] for d in driver_nodes]))
    if V_driver_mean <= 0:
        return {}
    pos: dict[str, float] = {}
    for i in range(N):
        if i in load_idx_set:
            pos[nodes_sorted[i]] = 1.0
        else:
            p = 1.0 - V_red[full_to_red[i]] / V_driver_mean
            if p < 0: p = 0.0
            elif p > 1: p = 1.0
            pos[nodes_sorted[i]] = p
    return pos


def _analyze_net_basics(
    circuit: Circuit,
    net: str,
    adj: dict[str, list[str]],
    pin_role: str = "any",   # kept for back-compat; no longer branches
    algo: str = "order0",
    order: int = 0,
) -> dict:
    """Collect R-component, per-pin R, r_eff, Cc position map for one net.

    Uniform treatment across net types — NO signal vs rail distinction.
    Every MOS pin whose subnode lands in the net's R-component is
    enumerated regardless of role (D/G/S/B).  Each pin gets its own
    per-pin driving-point R computed against the net's schematic-level
    port node (the bare canonical subnode if present in the mesh).

    Why unified: from a Laplacian POV, effective resistance is symmetric
    — "driver" vs "load" is just a reporting label.  Physically every
    MOS terminal connected to a parasitic mesh sees some R between the
    pin and the schematic-level net node, and capturing all four
    preserves source-degeneration (D/S), gate delay (G), and body-bias
    shift (B) effects uniformly.
    """
    seeds: set[str] = set()
    for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
        for e in edges:
            if circuit.canonical(e[0]) == net: seeds.add(e[0])
            if circuit.canonical(e[1]) == net: seeds.add(e[1])
    if not seeds:
        return {"net": net, "component": set(), "drivers": [],
                "loads": [], "driver_nodes": set(), "load_nodes": set(),
                "r_eff": float("inf"), "position": {}, "driver_source": "none",
                "pin_role": pin_role}
    comp = _component_of(adj, seeds)

    # Pre-filter R/Cg/Cc edges to this component — shared across every
    # Laplacian build in this function, turns O(|circuit.*_edges|)
    # per-net iterations into O(|comp_*_edges|).
    comp_r_edges = [e for e in circuit.r_edges
                    if e[0] in comp and e[1] in comp and e[2] > 0]
    comp_cg_edges = [e for e in circuit.cg_edges
                     if (e[0] in comp or e[1] in comp) and e[2] > 0]
    # For moment computation we want BOTH internal and external-touching
    # Cc edges.  External Cc → AC-ground cap on the internal end.
    comp_cc_edges = [e for e in circuit.cc_edges
                     if (e[0] in comp or e[1] in comp) and e[2] > 0]

    # 1. Enumerate every MOS pin whose subnode lands on the mesh.
    # pin_entries: list of {"instance", "role", "subnode", "key"}
    # key = "<instance>.<role>" — unique identifier for inject rename.
    pin_entries: list[dict] = []
    pin_subnodes_by_key: dict[str, str] = {}
    for d in circuit.devices:
        model_lc = d.model.lower()
        is_mos = model_lc.endswith("_mac") or "nch" in model_lc or "pch" in model_lc
        if not is_mos:
            continue
        for role, sn in d.pins.items():
            if sn not in comp: continue
            key = f"{d.name}.{role}"
            pin_entries.append({
                "instance": d.name, "role": role,
                "subnode": sn, "key": key,
            })
            pin_subnodes_by_key[key] = sn

    # 2. Port = bare canonical subnode if present in mesh.  This is the
    # "schematic-level" anchor for the net: after injection, the bare
    # ``<net>`` node carries ONLY the external connection and Cc peers;
    # every MOS pin gets moved off to its own ``<net>_<inst>_<role>_post``
    # node joined back through its own R.
    port_nodes: set[str] = {net} if net in comp else set()

    # 3. Lumped r_eff (bare port → cluster of all pins).  Used as a
    # reference and in star decomposition.
    all_pin_nodes = {e["subnode"] for e in pin_entries}
    if port_nodes and all_pin_nodes:
        r_eff = effective_resistance(circuit, port_nodes, all_pin_nodes,
                                     _comp_edges=comp_r_edges, _adj=adj)
    else:
        r_eff = float("inf")

    # 4. Per-pin driving-point R: one R per (instance, role) pin,
    # computed with that pin as the only sink and ALL others floating.
    # Laplacian factorisation is reused across pins (fast).
    per_pin_r: dict[str, float] = {}
    if port_nodes and pin_entries:
        pin_groups = {e["key"]: {e["subnode"]} for e in pin_entries}
        per_pin_r = per_instance_port_r(
            circuit, port_nodes, pin_groups, comp=comp,
            _comp_edges=comp_r_edges)

    # 5. Star decomposition: preserve per-pin asymmetry AND aggregate
    # cluster R.
    #
    #   port ──R_common── hub ─┬── R_branch_1 ── pin_1
    #                            ├── R_branch_2 ── pin_2
    #                            └── ...
    #
    # Two constraints:
    #   (a) Open-circuit pin i (others floating):
    #           R_common + R_branch_i = per_pin_r[i]
    #   (b) All-shorted cluster:
    #           R_common + mean(R_branch) / N ≈ r_eff_cluster
    #
    # From (a): R_branch_i = per_pin_r[i] - R_common
    #        => mean(R_branch) = mean(per_pin_r) - R_common
    # Plug into (b):
    #   R_common + (mean(per_pin_r) - R_common)/N = r_eff
    #   R_common · (N-1)/N + mean(per_pin_r)/N = r_eff
    #   R_common = (N · r_eff - mean(per_pin_r)) / (N - 1)
    r_common: float = 0.0
    r_branch: dict[str, float] = {}
    finite_rp = {k: v for k, v in per_pin_r.items()
                 if v != float("inf") and v > 0}
    N = len(finite_rp)
    if N >= 2 and r_eff != float("inf") and r_eff > 0:
        mean_r = sum(finite_rp.values()) / N
        r_common = (N * r_eff - mean_r) / (N - 1)
        if r_common < 0: r_common = 0.0
        # Cap r_common at min(per_pin_r) so no branch goes negative
        r_common = min(r_common, min(finite_rp.values()))
        r_branch = {k: max(v - r_common, 0.0) for k, v in finite_rp.items()}
    elif N == 1:
        r_common = 0.0
        r_branch = dict(finite_rp)

    # Position map (for Cc pi-split) — build from the bare port to all
    # pins collectively, like before.
    pos = _compute_position_map(circuit, comp, port_nodes, all_pin_nodes,
                                _comp_edges=comp_r_edges) \
        if (port_nodes and all_pin_nodes
            and r_eff != float("inf") and r_eff > 0) else {}

    # 6. Per-pin Foster ladder synthesis.  Only algo="prima" exercises
    # this path; "order0" relies on the legacy star (r_common + r_branch)
    # which preserves aggregate r_eff_cluster exactly.
    foster: dict[str, dict | None] = {}
    if port_nodes and pin_entries and algo == "prima":
        from .mor import foster_via_algo
        import scipy.sparse as sp
        import numpy as _np

        nodes = sorted(comp)
        node_idx = {n: i for i, n in enumerate(nodes)}
        N = len(nodes)

        # G assembled from R edges (Laplacian, port-Dirichlet later).
        rows, cols, vals = [], [], []
        for e in comp_r_edges:
            ia = node_idx.get(e[0]); ib = node_idx.get(e[1])
            if ia is None or ib is None or ia == ib: continue
            g = 1.0 / e[2]
            rows += [ia, ib, ia, ib]
            cols += [ia, ib, ib, ia]
            vals += [g, g, -g, -g]
        G_full = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()

        # C from Cg + internal Cc + external-end Cc-as-Cg.  External nets
        # are treated as AC-grounded (standard MOR assumption).
        rows, cols, vals = [], [], []
        for e in comp_cg_edges:
            ia = node_idx.get(e[0]); ib = node_idx.get(e[1])
            if ia is not None and ib is None:
                rows.append(ia); cols.append(ia); vals.append(e[2])
            elif ib is not None and ia is None:
                rows.append(ib); cols.append(ib); vals.append(e[2])
            elif ia is not None and ib is not None and ia != ib:
                rows += [ia, ib, ia, ib]
                cols += [ia, ib, ib, ia]
                vals += [e[2], e[2], -e[2], -e[2]]
        for e in comp_cc_edges:
            ia = node_idx.get(e[0]); ib = node_idx.get(e[1])
            if ia is None and ib is None: continue
            if ia is None:
                rows.append(ib); cols.append(ib); vals.append(e[2])
            elif ib is None:
                rows.append(ia); cols.append(ia); vals.append(e[2])
            elif ia != ib:
                rows += [ia, ib, ia, ib]
                cols += [ia, ib, ib, ia]
                vals += [e[2], e[2], -e[2], -e[2]]
        C_full = (sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()
                  if vals else sp.csc_matrix((N, N)))

        # Reduce by removing port rows/cols (Dirichlet V=0).
        port_set = {node_idx[n] for n in port_nodes if n in node_idx}
        interior = [i for i in range(N) if i not in port_set]
        int_arr = _np.array(interior)
        reduce_map = {full: red for red, full in enumerate(interior)}
        G_nn = G_full[int_arr][:, int_arr].tocsc()
        C_nn = C_full[int_arr][:, int_arr].tocsc()
        interior_idx_of_pin: dict[str, int] = {}
        for pe in pin_entries:
            full_i = node_idx.get(pe["subnode"])
            if full_i is not None and full_i in reduce_map:
                interior_idx_of_pin[pe["key"]] = reduce_map[full_i]

        for pe in pin_entries:
            key = pe["key"]
            pin_idx = interior_idx_of_pin.get(key)
            try:
                foster[key] = foster_via_algo(
                    None, G_nn, C_nn, pin_idx, algo, order)
            except Exception:
                foster[key] = None

    return {
        "net": net,
        "component": comp,
        "pin_entries": pin_entries,
        "port_nodes": port_nodes,
        "driver_nodes": port_nodes,          # legacy alias for downstream
        "load_nodes": all_pin_nodes,         # legacy alias
        "drivers": [f"{net}.port"] if port_nodes else [],
        "loads": [e["key"] for e in pin_entries],
        "r_eff": r_eff,
        "per_pin_r": per_pin_r,
        "r_common": r_common,
        "r_branch": r_branch,
        "foster": foster,
        "algo": algo,
        "order": order,
        "position": pos,
        "driver_source": "dut_port" if port_nodes else "none",
        "pin_role": pin_role,
    }


def batch_prescription(
    circuit: Circuit,
    nets: list[str],
    *,
    rails: set[str] | list[str] | None = None,   # deprecated, ignored
    algo: str = "order0",
    order: int = 0,
    resolve_map: dict[str, str] | None = None,
    _adj: dict[str, list[str]] | None = None,
) -> dict:
    """Joint prescription for multiple nets — correctly handles the
    between-prescribed Cc edges that single-net ``net_prescription``
    would double-count.

    A Cc edge (a, b, val) falls into one of three categories:

      1. **Internal**: both endpoints in the same net's R-component.
         First-order approximation: skip (both ends move together at
         low freq).
      2. **Between-prescribed**: endpoint a in mesh_X, endpoint b in
         mesh_Y (different prescribed nets).  Injected **once** with
         4-way position-weighted split:
            (V1P,    VOUTN   ) := val · (1-p_a)·(1-p_b)
            (V1P,    VOUTN_post) := val · (1-p_a)·   p_b
            (V1P_post,VOUTN  ) := val ·    p_a ·(1-p_b)
            (V1P_post,VOUTN_post):= val ·    p_a ·    p_b
         Weights sum to 1 → total injected = val (no double count).
      3. **External**: endpoint a in mesh_X, b outside every prescribed
         mesh → treated as a simple coupling from mesh_X to a
         canonical peer, with position-split into driver/load side
         (existing behaviour).

    ``rails`` is deprecated and ignored — the analysis is now uniform
    across signal and rail nets, with every MOS pin on each mesh
    getting its own R stub regardless of role.

    Returns ``{"prescriptions": [...], "inter_net_couplings": [...]}``.
    """
    from collections import defaultdict
    adj = _adj if _adj is not None else _build_adjacency(circuit)

    # 1. Per-net basics (no role dispatch)
    net_data: dict[str, dict] = {}
    for net in nets:
        net_data[net] = _analyze_net_basics(circuit, net, adj,
                                            algo=algo, order=order)

    # 2. Build node → prescribed-net map.  First-come-wins on overlap;
    # overlap between different prescribed meshes shouldn't happen in
    # well-formed extractions but we don't assume.
    node_to_net: dict[str, str] = {}
    for net, d in net_data.items():
        for n in d["component"]:
            node_to_net.setdefault(n, net)

    # 3. Resolver for peer canonical when a Cc's other end is NOT in
    # any prescribed mesh.
    def _resolve(n: str) -> str:
        if resolve_map is not None and n in resolve_map:
            return resolve_map[n]
        return circuit.canonical(n)

    # 4. External Cc buckets per prescribed net
    external_all:    dict[str, dict[str, float]] = {
        net: defaultdict(float) for net in nets}
    external_driver: dict[str, dict[str, float]] = {
        net: defaultdict(float) for net in nets}
    external_load:   dict[str, dict[str, float]] = {
        net: defaultdict(float) for net in nets}

    # 5. Between-prescribed Cc buckets per pair (net_a < net_b)
    inter: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"DD": 0.0, "DL": 0.0, "LD": 0.0, "LL": 0.0})

    for a, b, v, _ in circuit.cc_edges:
        if v <= 0: continue
        host_a = node_to_net.get(a)
        host_b = node_to_net.get(b)

        if host_a and host_b:
            if host_a == host_b:
                # Internal: skip (1st-order)
                continue
            # Between-prescribed: 4-way weighted split.
            p_a = net_data[host_a]["position"].get(a, 0.5)
            p_b = net_data[host_b]["position"].get(b, 0.5)
            # Normalise ordering so (net_a, net_b) is canonical
            if host_a > host_b:
                host_a, host_b = host_b, host_a
                p_a, p_b = p_b, p_a
            key = (host_a, host_b)
            inter[key]["DD"] += v * (1 - p_a) * (1 - p_b)
            inter[key]["DL"] += v * (1 - p_a) * p_b
            inter[key]["LD"] += v * p_a * (1 - p_b)
            inter[key]["LL"] += v * p_a * p_b
            continue

        # External to exactly one prescribed mesh
        if host_a:
            host = host_a; internal_node = a; peer = _resolve(b)
        elif host_b:
            host = host_b; internal_node = b; peer = _resolve(a)
        else:
            continue  # neither end in any prescribed mesh — not our concern

        p = net_data[host]["position"].get(internal_node, 0.5)
        external_all[host][peer]    += v
        external_driver[host][peer] += v * (1 - p)
        external_load[host][peer]   += v * p

    # 6. Assemble prescriptions
    prescriptions: list[dict] = []
    for net in nets:
        d = net_data[net]
        prescriptions.append({
            "net": net,
            "component_size": len(d["component"]),
            "pin_entries":    d.get("pin_entries", []),
            "driver_source":  d["driver_source"],
            "r_eff":          d["r_eff"],
            "per_pin_r":      dict(d.get("per_pin_r") or {}),
            "r_common":       d.get("r_common", 0.0),
            "r_branch":       dict(d.get("r_branch") or {}),
            "foster":         d.get("foster") or {},
            "algo":           d.get("algo", algo),
            "order":          d.get("order", order),
            "cc_distribution": dict(external_all[net]),
            "cc_driver_side":  dict(external_driver[net]),
            "cc_load_side":    dict(external_load[net]),
            "total_external_cc": sum(external_all[net].values()),
        })

    inter_list = []
    for (na, nb), w in inter.items():
        inter_list.append({
            "net_a": na, "net_b": nb,
            "DD": w["DD"], "DL": w["DL"], "LD": w["LD"], "LL": w["LL"],
            "total": w["DD"] + w["DL"] + w["LD"] + w["LL"],
        })
    inter_list.sort(key=lambda x: -x["total"])
    return {"prescriptions": prescriptions, "inter_net_couplings": inter_list}


def within_net_pin_r(
    circuit: Circuit,
    net: str,
    *,
    max_pins: int | None = 60,
    _adj: dict | None = None,
) -> dict:
    """Pin-to-pin effective R distribution **inside a single canonical net**.

    This is the headline per-net analysis for multi-terminal blocks
    (buffers, bias trees, reference rails): within one logical net the
    parasitic R mesh spreads the signal across many device pins, and
    the effective R between any two pins tells you where IR drops,
    delay asymmetry, and kickback bleed actually happen.

    Algorithm: find every device pin whose canonical net is ``net``.
    Each such pin lands on a subnode (the parser-preserved hierarchical
    node name, not the canonical fold).  Restrict the solve to the
    R-connected component containing those subnodes.  Factorize the
    reduced Laplacian **once** (the expensive step), then do one
    forward/back-substitution per pin to get its voltage response —
    pair R follows as ``V_a[a] - V_a[b]`` in O(1).  This is the
    standard "effective resistance via pseudo-inverse of Laplacian"
    trick, made cheap by sparse-LU reuse.

    ``max_pins`` caps the pin count by deterministic sampling (evenly
    strided through the pin list) to keep the matrix bounded.  Default
    60 → 60·59/2 = 1770 pair evaluations, finishes in seconds on
    a 30K-subnode component.

    Sampling caveat: even-stride sampling can miss entire structural
    classes if the stride aligns with an array period (e.g. 20-finger
    cross-coupler where every N-th gate is the same pin class).  If the
    distribution tail looks suspiciously narrow — or the top-K pairs
    are all the same element-to-element kind without variety — bump
    ``max_pins`` to 100+ to break aliasing.  F4 fixture guards the
    KERNEL math; sampling coverage is a tuning concern.

    Returns ``{}`` if the net has fewer than 2 pin touches (nothing to
    compare) or none of its pins land in the R graph.
    """
    from collections import defaultdict
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    # 1. Seed the net's electrical component from every node whose
    # canonical folds to the target net.  Devices often land on
    # **local** terminal names (e.g. `MM2_g`) that are R-connected to
    # real canonical subnodes (e.g. `VINN_9985`) via the poly-gate /
    # contact parasitic R.  Those local names don't canonicalize to
    # the target, so we can't filter device pins by `canonical(pin) ==
    # net` directly.  Instead: find every canonical node, BFS over R
    # edges to get the electrically-connected component, THEN match
    # device pins by component membership.
    seed_nodes: set[str] = set()
    for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
        for e in edges:
            if circuit.canonical(e[0]) == net: seed_nodes.add(e[0])
            if circuit.canonical(e[1]) == net: seed_nodes.add(e[1])
    if not seed_nodes:
        return {"net": net, "total_pins": 0, "pairs": {},
                "note": f"no nodes canonicalize to {net!r}"}

    adj = _adj if _adj is not None else _build_adjacency(circuit)
    comp = _component_of(adj, seed_nodes)

    # 2. Collect device-pin subnodes whose node lands in this component.
    pins_by_subnode: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for d in circuit.devices:
        for role, subnode in d.pins.items():
            if subnode in comp:
                pins_by_subnode[subnode].append((d.name, role, d.model))

    all_subnodes = list(pins_by_subnode.keys())
    if len(all_subnodes) < 2:
        return {"net": net, "total_pins": len(all_subnodes),
                "component_size": len(comp), "pairs": {}}

    # 3. Deterministic even-stride sampling so repeated runs give
    # identical output (and so the "extremes" reported below are
    # reproducible).
    if max_pins and len(all_subnodes) > max_pins:
        step = len(all_subnodes) / max_pins
        sampled = [all_subnodes[int(i * step)] for i in range(max_pins)]
    else:
        sampled = all_subnodes

    live = [s for s in sampled if s in comp]
    if len(live) < 2:
        return {"net": net, "total_pins": len(all_subnodes),
                "live_pins": len(live), "pairs": {}}

    # 3. Build the Laplacian on this component.  Index nodes; fix node 0
    # as ground (V=0) to remove the rank-1 null space (constant voltage
    # shift) and leave an invertible (N-1)x(N-1) reduced system.
    nodes = sorted(comp)
    idx = {n: i for i, n in enumerate(nodes)}
    N = len(nodes)
    rows, cols, vals = [], [], []
    for a, b, r, _ in circuit.r_edges:
        if r <= 0: continue
        ia = idx.get(a); ib = idx.get(b)
        if ia is None or ib is None or ia == ib: continue
        g = 1.0 / r
        rows += [ia, ib, ia, ib]
        cols += [ia, ib, ib, ia]
        vals += [g, g, -g, -g]
    L = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()

    ground = 0
    keep = np.array([i for i in range(N) if i != ground])
    L_red = L[keep][:, keep].tocsc()

    # 4. Factorize ONCE.  Each per-pin solve is then forward+back sub,
    # roughly a few ms on a 30K-node component.
    solver = spla.splu(L_red)

    # Map full-index → reduced-index; ground has no reduced column.
    def red_idx(full_i: int) -> int | None:
        if full_i == ground: return None
        return full_i - 1 if full_i > ground else full_i

    # 5. BATCHED solve: stack every pin's RHS unit vector into a single
    # (N-1) x K matrix and call solver.solve() once.  scipy's SuperLU
    # supports matrix RHS natively, which amortizes Python overhead
    # across the K solves — measured ~5× faster on real data vs the
    # per-pin loop for K≈30.
    live_ri: list[int | None] = [red_idx(idx[sn]) for sn in live]
    non_ground_cols = [(j, ri) for j, ri in enumerate(live_ri) if ri is not None]
    voltages: dict[str, np.ndarray | None] = {sn: None for sn in live}
    if non_ground_cols:
        B = np.zeros((N - 1, len(non_ground_cols)))
        for col_j, (j, ri) in enumerate(non_ground_cols):
            B[ri, col_j] = 1.0
        V = solver.solve(B)       # (N-1, K)
        for col_j, (j, _ri) in enumerate(non_ground_cols):
            voltages[live[j]] = V[:, col_j]

    def v_at(vec, node_name):
        ri = red_idx(idx[node_name])
        if ri is None: return 0.0
        if vec is None: return 0.0
        return float(vec[ri])

    # 6. Read off pairwise R via the pseudo-inverse-of-Laplacian formula:
    #
    #       R_eff(a, b) = L+[a,a] + L+[b,b] - 2·L+[a,b]
    #
    # where L+[i,j] = voltage at node i when 1A is injected at node j
    # (with ground pinned at 0).  Ground satisfies L+[*,ground] = 0 by
    # construction (we removed its row/column), which correctly
    # specializes to R_eff(a, ground) = L+[a,a] = V_a[a].
    #
    # The earlier attempt `V_a[a] - V_a[b]` was wrong: it gives only
    # the correct answer when b is the ground node (because then
    # V_a[b] = 0), and silently fails on all other pairs.  F4 locks
    # this in — it's the fixture specifically designed to catch it.
    pairs: dict[tuple[str, str], float] = {}
    for i, a in enumerate(live):
        va = voltages[a]
        for b in live[i + 1:]:
            vb = voltages[b]
            Laa = v_at(va, a)
            Lbb = v_at(vb, b)
            Lab = v_at(va, b) if va is not None else v_at(vb, a)
            pairs[(a, b)] = Laa + Lbb - 2.0 * Lab

    return {
        "net": net,
        "total_pins": len(all_subnodes),
        "sampled_pins": len(sampled),
        "live_pins": len(live),
        "component_size": N,
        "r_edges_in_component": (len(vals) // 4),  # we added 4 entries per edge
        "pairs": pairs,
        "pin_devices": {sn: pins_by_subnode[sn] for sn in live},
    }


def resistance_matrix(
    circuit: Circuit,
    nodes: list[str],
) -> dict[tuple[str, str], float]:
    """Effective R between every unordered pair of ``nodes``.

    Returns ``{(a, b): R_eff}`` for ``a < b``.  Pairs with no DC path
    get ``inf``; ``R_eff(n, n) = 0`` is omitted (trivial).  For a
    port-set of N nodes this is N·(N-1)/2 independent Laplacian solves,
    so keep the node list short (typical DUT has ≤ 10 ports).

    Rationale: for buffers / multi-terminal blocks the headline
    question is "R from port A to port B for every A, B" — a square
    symmetric matrix is the natural shape.  Users answering SAR /
    diff-pair questions use ``effective_resistance`` with explicit
    seed sets instead.
    """
    names = sorted(set(nodes))
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            out[(a, b)] = effective_resistance(circuit, [a], [b])
    return out


def per_net_r_sum(circuit: Circuit) -> dict[str, float]:
    """Arithmetic Σ R per canonical net (ranking metric, NOT effective R).

    Useful for the §1 report — flags nets with lots of mesh segments.
    Each R edge is attributed to the canonical net of *either* endpoint,
    counting once per net touched.  This matches the old pex_scan
    behaviour when the net-name was encoded in the R instance name.
    """
    total: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for a, b, r, _ in circuit.r_edges:
        if r <= 0: continue
        na = circuit.canonical(a)
        nb = circuit.canonical(b)
        if na == nb:
            total[na] += r
            counts[na] += 1
        else:
            # each R segment touches two nets — attribute to both
            total[na] += r; counts[na] += 1
            total[nb] += r; counts[nb] += 1
    return dict(total)
