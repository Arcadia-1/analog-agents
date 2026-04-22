"""Canonical in-memory IR for post-layout netlists.

Every format adapter reads its source syntax and produces a ``Circuit``.
Every kernel consumes a ``Circuit``.  The format is invisible to the
kernels — that's the point of this module.

Design notes:

- We keep three separate edge lists (``r_edges``, ``cg_edges``,
  ``cc_edges``) instead of one tagged list.  The kernels care about
  exactly one kind each, and separate lists make their hot loops trivial
  (no per-edge type check).

- Discrimination between **Cg** (one terminal is a power/ground rail)
  and **Cc** (two signal nets) is the adapter's job, not the kernel's.
  Adapters call ``is_power(name)`` — a single source of truth defined
  below.  Kernels trust that cg_edges's second terminal is always a rail.

- We deliberately keep node names as *strings* for now.  For ~10⁶-edge
  netlists this is 10-100 MB of memory overhead that a node-interning
  layer could reclaim, but strings keep the IR trivially inspectable
  (pickle it, print it, grep it) during refactor.  Interning is a
  drop-in later optimization.

- ``alias`` is an **explicit** subnode → canonical-net map populated by
  the adapter.  ``canonical(node)`` falls back to a **rule-based guess**
  (:func:`canonicalize`) when the alias table is silent — so we cover
  both kinds of naming: flatten-derived numeric IDs (only expressible
  via explicit alias) and Calibre's pattern-based subnode names
  (derivable on the fly).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Standard power/ground rail names.  Adapters may augment this set via
# `Circuit.metadata["extra_power"]` if the design uses non-standard rails.
POWER_NETS: frozenset[str] = frozenset({
    "VSS", "VDD", "GND", "SUB", "0", "gnd!", "vss!", "vdd!",
    "vss", "vdd", "gnd",
})


def is_power(name: str, extra: frozenset[str] | set[str] = frozenset()) -> bool:
    """Is this net name a power/ground rail?"""
    return name in POWER_NETS or name in extra


# ---------------------------------------------------------------------------
# Canonicalization — strip Calibre's subnode naming to the parent net.
#
# Covers three patterns seen in real Calibre xRC output:
#   1. ``<net>_<digits>``   — mrpp subnode suffix    (SETN_94966    → SETN)
#   2. ``N_<net>_<rest>``   — spectre hierarchical   (N_VREFN_X…   → VREFN)
#   3. ``c_<digits>_[np]``  — anonymous mesh subnode (leave as-is; no parent)
#
# Pure-numeric names (from helper-subckt flattening, e.g. "5719") are also
# left as-is — they only mean something in their local scope and the
# adapter is responsible for promoting them via the explicit alias map
# when it can.
# ---------------------------------------------------------------------------

_ANON_C_RE = re.compile(r"^c_\d+_[np]$")
_NUMERIC_RE = re.compile(r"^\d+$")
_N_PREFIX_RE = re.compile(r"^N_([^_/\\]+)")          # N_VREFN_… → VREFN
_SUBNODE_SUFFIX_RE = re.compile(r"^(.+?)_{1,2}(\d+)$")  # VREFN_12 → VREFN


def canonicalize(name: str,
                 *,
                 extra_power: frozenset[str] | set[str] = frozenset()) -> str:
    """Return a best-effort canonical net name for ``name`` via naming rules.

    Callers who have explicit domain knowledge (e.g. flattened helper
    subckts) should set ``Circuit.alias[subnode] = canonical`` — that
    overrides this function.  This rule set is the fallback for node
    names that only a pattern can decode.
    """
    if not name:
        return name
    if name in POWER_NETS or name in extra_power:
        return name
    if _ANON_C_RE.match(name):
        return name
    if _NUMERIC_RE.match(name):
        return name
    m = _N_PREFIX_RE.match(name)
    if m:
        return m.group(1)
    m = _SUBNODE_SUFFIX_RE.match(name)
    if m:
        return m.group(1)
    return name


# ---------------------------------------------------------------------------
# Edge shape: a single tuple, used in all three edge lists.  Keeping the
# same shape across R/Cg/Cc makes adapter code symmetric (one append path
# regardless of kind).
#
# An edge is ``(node_a, node_b, value, name)`` where:
#   - ``value`` is ohms for R, farads for C
#   - ``name`` is the original instance name (e.g. "r1343", "ciVREFOUT_27551")
#     preserved for debug, trace, and cross-reference to source
#
# For ``cg_edges`` specifically, ``node_b`` is always a power rail.
# ---------------------------------------------------------------------------


@dataclass
class Device:
    """A MOSFET, subckt call, or other non-parasitic leaf instance.

    Kernels don't consume Devices directly — they're retained for the
    report layer ("§6 Drill-down: what hangs off this net") and for
    future topological checks.
    """
    name: str
    model: str                          # 'pch_hv18_mac', 'cfmom_2t', etc.
    pins: dict[str, str] = field(default_factory=dict)   # role_or_idx -> net
    params: dict[str, str] = field(default_factory=dict) # w, l, nf, ...


@dataclass
class Circuit:
    """The canonical IR.  Produced by adapters, consumed by kernels."""

    dut: str = ""                                   # DUT / top cell name
    ports: list[str] = field(default_factory=list)  # DUT external pins (if known)

    r_edges:  list[tuple[str, str, float, str]] = field(default_factory=list)
    cg_edges: list[tuple[str, str, float, str]] = field(default_factory=list)
    cc_edges: list[tuple[str, str, float, str]] = field(default_factory=list)

    devices: list[Device] = field(default_factory=list)
    alias:   dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # --- convenience accessors (no business logic — just readable shortcuts) ---

    def nodes(self) -> set[str]:
        """Every node name appearing in any edge or device pin."""
        s: set[str] = set()
        for a, b, *_ in self.r_edges:  s.add(a); s.add(b)
        for a, b, *_ in self.cg_edges: s.add(a); s.add(b)
        for a, b, *_ in self.cc_edges: s.add(a); s.add(b)
        for d in self.devices:
            for v in d.pins.values(): s.add(v)
        return s

    def n_elements(self) -> dict[str, int]:
        return {
            "R":  len(self.r_edges),
            "Cg": len(self.cg_edges),
            "Cc": len(self.cc_edges),
            "devices": len(self.devices),
        }

    def canonical(self, node: str) -> str:
        """Return the canonical (logical) net name for a subnode.

        Lookup order:
          1. Explicit alias (set by adapter, e.g. flatten pin-mapping)
          2. Pattern-based guess via :func:`canonicalize`

        The alias wins when present, so adapters can override any
        pattern guess where they have authoritative information.

        Results are memoized on the Circuit instance — the regex-based
        canonicalize() is expensive and gets called millions of times
        during map/BFS operations on big meshes.
        """
        if node in self.alias:
            return self.alias[node]
        cache = self.__dict__.get("_canon_cache")
        if cache is None:
            cache = {}
            self.__dict__["_canon_cache"] = cache
        r = cache.get(node)
        if r is None:
            r = canonicalize(node)
            cache[node] = r
        return r
