"""Cc kernel: per-pair coupling-capacitance sum.

Folds subnode-level Cc edges up to canonical-net pairs (via
``Circuit.alias``) and sums.  Pairs are stored unordered — ``(A, B)``
and ``(B, A)`` collapse to the same bucket.
"""
from __future__ import annotations

from collections import defaultdict

from ir import Circuit


def per_pair_cc_sum(circuit: Circuit) -> dict[tuple[str, str], float]:
    """Return ``{(netA, netB): sum_Cc}`` for every distinct net pair.

    Self-couplings (both endpoints resolve to the same canonical net)
    are dropped — they're an artifact of aggregate, not real coupling.
    """
    total: dict[tuple[str, str], float] = defaultdict(float)
    for a, b, v, _name in circuit.cc_edges:
        if v <= 0: continue
        na = circuit.canonical(a)
        nb = circuit.canonical(b)
        if na == nb: continue
        key = (na, nb) if na < nb else (nb, na)
        total[key] += v
    return dict(total)


def cc_count_per_pair(circuit: Circuit) -> dict[tuple[str, str], int]:
    """Number of coupling edges per canonical pair."""
    cnt: dict[tuple[str, str], int] = defaultdict(int)
    for a, b, _v, _name in circuit.cc_edges:
        na = circuit.canonical(a)
        nb = circuit.canonical(b)
        if na == nb: continue
        key = (na, nb) if na < nb else (nb, na)
        cnt[key] += 1
    return dict(cnt)
