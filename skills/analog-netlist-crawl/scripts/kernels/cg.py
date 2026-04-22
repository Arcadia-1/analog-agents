"""Cg kernel: per-net ground-capacitance sum.

Folds subnode Cg's up to their canonical logical nets via
``Circuit.alias``.  For adapters that don't populate alias (e.g. flat
schematic netlists), this degrades to per-node reporting — the node
name IS the net name.
"""
from __future__ import annotations

from collections import defaultdict

from ir import Circuit


def per_net_cg_sum(circuit: Circuit) -> dict[str, float]:
    """Return ``{net: sum_Cg_farads}`` over non-power terminals.

    By convention ``cg_edges[i][1]`` is a power rail — we only aggregate
    the first terminal, the signal side.
    """
    total: dict[str, float] = defaultdict(float)
    for a, _rail, v, _name in circuit.cg_edges:
        if v <= 0: continue
        net = circuit.canonical(a)
        total[net] += v
    return dict(total)


def cg_count_per_net(circuit: Circuit) -> dict[str, int]:
    """Companion to per_net_cg_sum — how many Cg segments hang off each net."""
    cnt: dict[str, int] = defaultdict(int)
    for a, _rail, _v, _name in circuit.cg_edges:
        net = circuit.canonical(a)
        cnt[net] += 1
    return dict(cnt)
