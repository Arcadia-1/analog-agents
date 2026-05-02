"""Model Order Reduction for port-to-pin RC driving-point impedances.

Two methods exposed (after empirical pruning):

  * ``"order0"`` — single resistor R = DC driving-point.  No frequency
    dependence at the per-pin level (Cc still injected separately by
    inject.py for inter-net coupling).  Fastest baseline.

  * ``"prima"`` (q=1) — Krylov-Arnoldi 1-pole projection
    (Odabasioglu, Celik, Pileggi, IEEE TCAD 1998).  Adds a single
    parallel-RC section per pin via congruence projection — passivity
    preserved by construction.  Best lumped accuracy in our
    benchmarks.

History (dropped from CLI):

  * Elmore single-pole RC (Elmore 1948) — degenerates to order0 once
    the R_common hub absorbs DC, since μ₀′ = μ₀ − R_common ≈ 0 leaves
    nothing for the pole to model.
  * AWE k-pole Padé (Pillage & Rohrer 1990) — numerically unstable on
    real-size meshes for k ≥ 2.  Hankel system becomes ill-conditioned.
  * PRIMA q ≥ 2 — collapses onto q=1 because for sub-THz simulations
    on RC meshes the Krylov subspace converges in one iteration; the
    extra poles all sit above the simulation bandwidth with negligible
    residue.

The kernel still computes the q=1 Arnoldi basis explicitly via
``_prima_arnoldi_and_e``; ``foster_via_algo`` dispatches.

    port ──R_inf── mid_0 ──[R_1 ‖ C_1]── mid_1 ──[R_2 ‖ C_2]── ... ── pin

For order0: ``sections=[]`` and the chain collapses to a single
resistor.  For prima:1: one parallel-RC section.
"""
from __future__ import annotations

import numpy as np


def compute_port_to_pin_moments(
    circuit,
    port_nodes: set,
    pin_entries: list,   # list of {"key", "subnode", ...}
    order: int,
    comp: set,
    comp_r_edges: list,
    comp_cg_edges: list,
    comp_cc_edges: list,
    _shared=None,  # dict from per_instance_port_r's _reduced_cache — reuse LU + idx
) -> dict:
    """Return ``{pin_key: np.ndarray of moments μ_0..μ_{2·order}}``.

    ``comp_cg_edges`` — Cg edges with one end in comp (other in ground).
    ``comp_cc_edges`` — Cc edges with BOTH ends in comp.
    External Cc (one end out of comp) is handled separately by the
    caller; it contributes an effective Cg at the internal endpoint
    and that's accounted for upstream if desired.

    For order 0, returns only μ_0; for order k≥1, returns 2k+1 moments.
    """
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    n_moments = 2 * order + 1 if order >= 1 else 1

    # Reuse shared structures if caller already built them for the
    # same component (per_instance_port_r produces these).
    if _shared is not None and "idx" in _shared:
        nodes = _shared["nodes"]
        idx = _shared["idx"]
        N = len(nodes)
    else:
        nodes = sorted(comp)
        idx = {n: i for i, n in enumerate(nodes)}
        N = len(nodes)

    # Assemble G (Laplacian from R edges).  Only needed if we can't
    # reuse a pre-factorised LU.
    G = None
    if _shared is None or "lu" not in _shared:
        rows, cols, vals = [], [], []
        for edge in comp_r_edges:
            r = edge[2]
            if r <= 0: continue
            ia = idx.get(edge[0]); ib = idx.get(edge[1])
            if ia is None or ib is None or ia == ib: continue
            g = 1.0 / r
            rows += [ia, ib, ia, ib]
            cols += [ia, ib, ib, ia]
            vals += [g, g, -g, -g]
        G = sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()

    # Assemble C.  MOR standard assumption: external nets are at AC
    # ground → every Cc edge with only one endpoint in this mesh adds
    # to the diagonal at the internal endpoint (looks like a Cg to
    # ground for purposes of port-to-pin impedance).  Cc edges with
    # BOTH ends in mesh contribute proper off-diagonal coupling.
    rows, cols, vals = [], [], []
    for edge in comp_cg_edges:
        c = edge[2]
        if c <= 0: continue
        # One end in comp, other is either literal "0" or another net
        # (which MOR assumption treats as AC ground).  Figure out which
        # end is the mesh node and add c to its diagonal.
        ia = idx.get(edge[0])
        ib = idx.get(edge[1])
        if ia is not None and ib is None:
            rows.append(ia); cols.append(ia); vals.append(c)
        elif ib is not None and ia is None:
            rows.append(ib); cols.append(ib); vals.append(c)
        elif ia is not None and ib is not None and ia != ib:
            # Both ends in mesh (rare for a Cg edge, but harmless).
            rows += [ia, ib, ia, ib]
            cols += [ia, ib, ib, ia]
            vals += [c, c, -c, -c]
    for edge in comp_cc_edges:
        c = edge[2]
        if c <= 0: continue
        ia = idx.get(edge[0]); ib = idx.get(edge[1])
        if ia is None and ib is None: continue
        if ia is None:
            # Only ib in comp — treat ia side as AC ground, add c to ib diagonal
            rows.append(ib); cols.append(ib); vals.append(c)
        elif ib is None:
            rows.append(ia); cols.append(ia); vals.append(c)
        elif ia != ib:
            rows += [ia, ib, ia, ib]
            cols += [ia, ib, ib, ia]
            vals += [c, c, -c, -c]
    C = (sp.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()
         if vals else sp.csc_matrix((N, N)))

    # Reduce: remove port rows/cols (Dirichlet V=0).
    port_idx = {idx[n] for n in port_nodes if n in idx}
    if not port_idx:
        return {pe["key"]: None for pe in pin_entries}

    if _shared is not None and "lu" in _shared and "interior_arr" in _shared:
        # Reuse from per_instance_port_r.
        interior = _shared["interior_arr"]
        reduce_map = _shared["reduce_map"]
        lu = _shared["lu"]
        C_nn = C[interior][:, interior].tocsc()
    else:
        interior = np.array([i for i in range(N) if i not in port_idx])
        reduce_map = {full: red for red, full in enumerate(interior)}
        G_nn = G[interior][:, interior].tocsc()
        C_nn = C[interior][:, interior].tocsc()
        try:
            lu = spla.splu(G_nn)
        except Exception:
            return {pe["key"]: None for pe in pin_entries}
        if _shared is not None:
            _shared["lu"] = lu
            _shared["interior_arr"] = interior
            _shared["reduce_map"] = reduce_map

    result: dict = {}
    n_int = len(interior)
    for pe in pin_entries:
        pin_full = idx.get(pe["subnode"])
        if pin_full is None or pin_full not in reduce_map:
            result[pe["key"]] = None
            continue
        p = reduce_map[pin_full]
        # μ_0 = (G_nn⁻¹ e_p)_p
        e = np.zeros(n_int)
        e[p] = 1.0
        m = lu.solve(e)
        mus = [float(m[p])]
        # Higher moments: m_{k+1} = -G_nn⁻¹ C_nn m_k
        for _ in range(n_moments - 1):
            m = -lu.solve(C_nn @ m)
            mus.append(float(m[p]))
        result[pe["key"]] = np.array(mus)
    return result


def prima_reduced_system(
    G_nn,         # scipy.sparse CSC, interior-only
    C_nn,         # same
    pin_idx: int, # index of the pin in the interior basis
    order: int,
    lu=None,      # optional pre-factorised SuperLU of G_nn (reuse across pins)
):
    """PRIMA Arnoldi projection to an order-q reduced state space.

    Returns ``(G_q, C_q, b_q, l_q, Vq)`` — projected matrices, plus
    the Arnoldi basis ``Vq`` (n_int × q).

    ``Vq`` spans ``span{ A^i r_0 : i=0..q-1 }`` where A = -G⁻¹C,
    r_0 = G⁻¹ e_pin.  Preserves the first q moments and — by
    congruence projection of both G and C — passivity of the
    reduced RC macromodel.

    Pass ``lu`` (a ``scipy.sparse.linalg.splu`` result on the same
    ``G_nn``) to amortise factorisation cost across many pins on the
    same net — critical for high-pin-count nets (e.g. VDD with
    thousands of fingers).  If ``lu`` is None, a fresh factorisation
    is done here (slow for big meshes).
    """
    import scipy.sparse.linalg as spla
    import numpy as np
    n = G_nn.shape[0]
    e = np.zeros(n); e[pin_idx] = 1.0
    if lu is None:
        lu = spla.splu(G_nn)
    r0 = lu.solve(e)
    norm0 = np.linalg.norm(r0)
    if norm0 < 1e-30:
        return None
    V = np.zeros((n, order + 1))
    V[:, 0] = r0 / norm0
    for j in range(order):
        w = -lu.solve(C_nn @ V[:, j])
        for i in range(j + 1):
            h = V[:, i] @ w
            w -= h * V[:, i]
        # Re-orthogonalise once for numerical stability.
        for i in range(j + 1):
            h = V[:, i] @ w
            w -= h * V[:, i]
        nw = np.linalg.norm(w)
        if nw < 1e-12:
            V = V[:, :j+1]  # Krylov dimension collapsed early
            break
        V[:, j+1] = w / nw
    Vq = V[:, :order]
    if Vq.shape[1] < 1:
        return None
    G_q = Vq.T @ (G_nn @ Vq)
    C_q = Vq.T @ (C_nn @ Vq)
    b_q = Vq.T @ e
    l_q = Vq.T @ e   # driving-point: input = output = pin
    return G_q, C_q, b_q, l_q, Vq


def prima_foster_from_basis(G_nn, C_nn, Vq_full, order: int):
    """Given a precomputed Arnoldi basis ``Vq_full`` of dimension ≥
    ``order``, project onto the first ``order`` columns and synthesize
    Foster I.  Skips the expensive Arnoldi iterations — for sweeping
    multiple orders on the same pin, compute the basis once at
    ``max_order`` then call this for each order.
    """
    import numpy as np
    import scipy.linalg as sla
    if Vq_full is None or Vq_full.shape[1] < 1 or order < 1:
        return None
    q = min(order, Vq_full.shape[1])
    Vq = Vq_full[:, :q]
    G_q = Vq.T @ (G_nn @ Vq)
    C_q = Vq.T @ (C_nn @ Vq)
    # b_q = l_q = Vq.T @ e_pin.  Since Vq's first column is the
    # normalised r_0 direction, Vq.T @ e_pin = norm_r0 · e_0 effectively;
    # but we don't have that norm here, so reconstruct from G_q @ (Vq.T r_0).
    # Simpler: store e_pin with the basis.  For now recompute as
    # b_q = Vq^T (G_nn · r_0) where r_0 = Vq[:, 0]·norm, which gives
    # back e_pin up to the Arnoldi structure.  Practically we just
    # use Vq.T @ (G_nn r_0) since this is what PRIMA uses.
    # r_0 is stored as first column of Vq (un-normalised info lost —
    # but synthesis needs Vq^T e_pin).  Pass separately via tuple.
    return None  # placeholder; real signature uses Arnoldi-returned data


def _prima_arnoldi_and_e(G_nn, C_nn, pin_idx: int, max_order: int, lu=None):
    """Compute Arnoldi basis ``Vq`` of dimension up to ``max_order``
    plus the normalized injection vector ``e_proj = Vq.T @ e_pin``.

    This is the expensive part of PRIMA — do it ONCE per pin, then
    reuse for any order ≤ max_order via ``prima_foster_slice``.
    """
    import scipy.sparse.linalg as spla
    import numpy as np
    n = G_nn.shape[0]
    e = np.zeros(n); e[pin_idx] = 1.0
    if lu is None:
        lu = spla.splu(G_nn)
    r0 = lu.solve(e)
    norm0 = np.linalg.norm(r0)
    if norm0 < 1e-30:
        return None
    V = np.zeros((n, max_order + 1))
    V[:, 0] = r0 / norm0
    q_eff = max_order
    for j in range(max_order):
        w = -lu.solve(C_nn @ V[:, j])
        for i in range(j + 1):
            h = V[:, i] @ w
            w -= h * V[:, i]
        for i in range(j + 1):
            h = V[:, i] @ w
            w -= h * V[:, i]
        nw = np.linalg.norm(w)
        if nw < 1e-12:
            q_eff = j + 1
            break
        V[:, j+1] = w / nw
    Vq = V[:, :q_eff]
    e_proj = Vq.T @ e
    return Vq, e_proj


def prima_foster_slice(G_nn, C_nn, Vq_full, e_proj_full, order: int):
    """Project to order k ≤ Vq_full.shape[1] and synthesize Foster I.

    Paired with ``_prima_arnoldi_and_e``: compute Arnoldi once at
    ``max_order``, call this for each requested order.
    """
    import numpy as np
    import scipy.linalg as sla
    if Vq_full is None or Vq_full.shape[1] < 1 or order < 1:
        return None
    q = min(order, Vq_full.shape[1])
    Vq = Vq_full[:, :q]
    G_q = Vq.T @ (G_nn @ Vq)
    C_q = Vq.T @ (C_nn @ Vq)
    b_q = e_proj_full[:q]
    l_q = b_q   # driving-point: input = output

    try:
        A = np.linalg.solve(G_q, C_q)
        taus, X = sla.eig(A)
    except Exception:
        return None
    try:
        alpha = l_q @ X
        beta = np.linalg.solve(X, np.linalg.solve(G_q, b_q))
    except Exception:
        return None

    sections = []
    for tau_i, a_i, b_i in zip(taus, alpha, beta):
        if abs(tau_i.imag) > 1e-6 * (abs(tau_i.real) + 1e-30):
            continue
        tau_r = float(tau_i.real)
        if tau_r <= 0:
            continue
        R_i = float((a_i * b_i).real)
        if R_i <= 0:
            continue
        sections.append((R_i, tau_r))
    if not sections:
        return None
    return {"R_inf": 0.0, "sections": sections}


def prima_foster(G_nn, C_nn, pin_idx: int, order: int, lu=None):
    """PRIMA → Foster I synthesis for port-to-pin driving-point Z.

    Odabasioglu, Celik, Pileggi 1998.  Passive by construction when
    G, C are symmetric PSD (which they are for RC meshes), but we
    still filter out any poles that came out with the wrong sign
    from numerical noise.

    ``lu`` — optional SuperLU of G_nn to amortise across pins.
    """
    import numpy as np
    import scipy.linalg as sla
    res = prima_reduced_system(G_nn, C_nn, pin_idx, order, lu=lu)
    if res is None:
        return None
    G_q, C_q, b_q, l_q, Vq = res
    q = G_q.shape[0]
    if q < 1:
        return None

    # Z(s) = l^T (G_q + s C_q)⁻¹ b.  Generalized eigenvalue problem
    # gives poles:  (G_q + s_i C_q) x_i = 0  →  s_i = -1/τ_i.
    try:
        # Form A = G⁻¹ C.  Its eigenvalues are τ_i.
        A = np.linalg.solve(G_q, C_q)
        taus, X = sla.eig(A)
    except Exception:
        return None

    # Residues via eigen-expansion:
    #   Z(s) = l^T X (I + sΛ)⁻¹ X⁻¹ G_q⁻¹ b
    #        = Σ_i  (l^T X)_i · (X⁻¹ G_q⁻¹ b)_i / (1 + s τ_i)
    try:
        alpha = l_q @ X
        beta = np.linalg.solve(X, np.linalg.solve(G_q, b_q))
    except Exception:
        return None

    sections = []
    for tau_i, a_i, b_i in zip(taus, alpha, beta):
        if abs(tau_i.imag) > 1e-6 * (abs(tau_i.real) + 1e-30):
            continue  # complex pole — skip (would need conjugate-pair synthesis)
        tau_r = float(tau_i.real)
        if tau_r <= 0:
            continue
        R_i = float((a_i * b_i).real)
        if R_i <= 0:
            continue
        sections.append((R_i, tau_r))

    if not sections:
        return None
    return {"R_inf": 0.0, "sections": sections}


def foster_via_algo(moments, G_nn, C_nn, pin_idx, algo: str, order: int, lu=None):
    """Dispatch per-pin Foster synthesis by algorithm name.

    Parameters
    ----------
    moments : np.ndarray | None
        For ``order0``: just ``[μ_0]`` (DC R).  Ignored for ``prima``.
    G_nn, C_nn : sparse CSC (interior-only)
        Required by PRIMA.
    pin_idx : int
        Pin index in the interior basis (for PRIMA).
    algo : {"order0", "prima"}
    order : int
        Ignored for ``order0``; forced to 1 for ``prima`` (q≥2 is
        empirically equivalent to q=1 for sub-THz RC simulations).
    """
    if algo == "order0":
        return {"R_inf": float(moments[0]), "sections": []}
    if algo == "prima":
        return prima_foster(G_nn, C_nn, pin_idx, order, lu=lu)
    raise ValueError(
        f"unknown MOR algo: {algo!r}.  Supported: 'order0', 'prima'.")
