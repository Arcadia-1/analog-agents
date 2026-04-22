#!/usr/bin/env python3
"""Matrix test: every adapter × every fixture × every kernel → expected values.

Run from the ``scripts/`` directory::

    python test_all.py

Each test case is one row in the matrix below.  A case passes iff the
parsed Circuit makes every kernel return its expected value within
tolerance.  This is the ground-truth validation for the refactor.
"""
from __future__ import annotations

import math
import os
import sys

# Make absolute imports like `from ir import Circuit` work regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from adapters import parse_mrpp, parse_spectre, detect_format     # noqa: E402
from kernels import (                                              # noqa: E402
    effective_resistance,
    per_net_cg_sum,
    per_pair_cc_sum,
    within_net_pin_r,
)


# ---------------------------------------------------------------------------
# Expected values for each fixture circuit (format-independent).
# ---------------------------------------------------------------------------

F1_EXPECTED = {
    "r_pairs": [
        (("n1",), ("n4",), 60.0),   # simple series sum
        (("n1",), ("n2",), 10.0),
        (("n2",), ("n4",), 50.0),
        (("n1",), ("n3",), 30.0),
    ],
    "cg": {"n2": 1e-15},
    "cc": {},                                 # no coupling caps
}

F2_EXPECTED = {
    "r_pairs": [
        (("nIP",), ("nOP",), 10.0),           # left-half series
        (("nIN",), ("nON",), 10.0),           # right-half series
        (("nIP",), ("nIN",), float("inf")),   # Cc blocks DC → no path
        (("nA",),  ("nB",),  float("inf")),
    ],
    "cg": {},
    "cc": {("nA", "nB"): 1e-15},
}

# F4: within-net pin-to-pin R anchor.  A MOSFET gate sits on each of
# four subnodes VREFN_1..VREFN_4 which are chained by parasitic R of
# 1Ω, 2Ω, 3Ω.  within_net_pin_r(circuit, 'VREFN') must find the four
# pins and return series-sum R between any two.
F4_EXPECTED_WITHIN_NET = {
    "net": "VREFN",
    "expected_pair_count": 6,          # C(4,2) = 6 ordered pairs
    "pair_r": {
        frozenset(("VREFN_1", "VREFN_2")): 1.0,
        frozenset(("VREFN_2", "VREFN_3")): 2.0,
        frozenset(("VREFN_3", "VREFN_4")): 3.0,
        frozenset(("VREFN_1", "VREFN_3")): 3.0,   # 1 + 2
        frozenset(("VREFN_2", "VREFN_4")): 5.0,   # 2 + 3
        frozenset(("VREFN_1", "VREFN_4")): 6.0,   # 1 + 2 + 3
    },
}


# F3: Series/parallel correctness anchor.  All answers are closed-form
# from KCL — see the fixture header for derivations.  Sub-circuits a,
# b, c share no R edges, so cross-sub-circuit pairs must be +inf — this
# guards against a singular-Laplacian bug where including seed nodes
# from disjoint R-components used to produce nonsense (≈10^16 Ω).
F3_EXPECTED = {
    "r_pairs": [
        # Valid intra-sub-circuit paths
        (("a1",), ("a2",),            7.5),          # 3a: 10 || 30
        (("b_top",), ("b_bot",),     15.0),          # 3b: diamond, 30||30
        (("c_top",), ("c_bot",),     30.75),         # 3c: unbalanced Wheatstone
        (("a1", "b_top"), ("a2", "b_bot"), 5.0),     # 3d: parallel across two sub-comps
        # Cross-component isolation (seeds live in disjoint components)
        (("a1",), ("b_top",), float("inf")),
        (("b_bot",), ("c_bot",), float("inf")),
        (("a2",), ("c_top",), float("inf")),
    ],
    "cg": {},
    "cc": {},
}

# (fixture_file, expected_dict, adapter_fn, dut_override)
CASES = [
    ("fixtures/f1_rc_ladder.mrpp",          F1_EXPECTED, parse_mrpp,    None),
    ("fixtures/f1_rc_ladder.flat.scs",      F1_EXPECTED, parse_spectre, None),
    ("fixtures/f1_rc_ladder.subckt.scs",    F1_EXPECTED, parse_spectre, "F1_DUT"),
    ("fixtures/f2_diffpair_cc.mrpp",        F2_EXPECTED, parse_mrpp,    None),
    ("fixtures/f2_diffpair_cc.flat.scs",    F2_EXPECTED, parse_spectre, None),
    ("fixtures/f2_diffpair_cc.subckt.scs",  F2_EXPECTED, parse_spectre, "F2_DUT"),
    ("fixtures/f3_series_parallel.mrpp",    F3_EXPECTED, parse_mrpp,    None),
    ("fixtures/f3_series_parallel.flat.scs", F3_EXPECTED, parse_spectre, None),
]


# ---------------------------------------------------------------------------
# Assertion helpers — tolerant of floating-point drift, clear on failure.
# ---------------------------------------------------------------------------

RTOL = 1e-6
ATOL_CAP = 1e-20     # picofemtofarad noise floor for cap comparisons


def _close(a: float, b: float, *, atol: float = ATOL_CAP, rtol: float = RTOL) -> bool:
    if math.isinf(a) and math.isinf(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return False
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))


def _fmt(x: float) -> str:
    if math.isinf(x): return "inf"
    if abs(x) < 1e-9: return f"{x:.3e}"
    return f"{x:.6g}"


# ---------------------------------------------------------------------------

def run_case(fixture_path: str, expected: dict, adapter_fn, dut_override) -> list[str]:
    """Return a list of failure strings; empty list = pass."""
    fails: list[str] = []
    full_path = os.path.join(_HERE, fixture_path)
    circuit = adapter_fn(full_path) if dut_override is None else adapter_fn(full_path, dut_name=dut_override)

    # R-network kernel
    for src, snk, expected_r in expected["r_pairs"]:
        got = effective_resistance(circuit, src, snk)
        if not _close(got, expected_r):
            fails.append(
                f"R_eff({src!r} -> {snk!r}): got {_fmt(got)}, expected {_fmt(expected_r)}"
            )

    # Cg kernel
    cg_got = per_net_cg_sum(circuit)
    # Any net in expected must appear with right value
    for net, exp_v in expected["cg"].items():
        got_v = cg_got.get(net, 0.0)
        if not _close(got_v, exp_v):
            fails.append(f"Cg[{net!r}]: got {_fmt(got_v)}, expected {_fmt(exp_v)}")
    # And nets NOT in expected must be zero (or absent)
    extras = {n: v for n, v in cg_got.items() if n not in expected["cg"] and v > ATOL_CAP}
    if extras:
        fails.append(f"unexpected Cg entries: { {k: _fmt(v) for k, v in extras.items()} }")

    # Cc kernel
    cc_got = per_pair_cc_sum(circuit)
    for pair, exp_v in expected["cc"].items():
        # Normalize pair ordering to match kernel convention (lexicographic)
        key = tuple(sorted(pair))
        got_v = cc_got.get(key, 0.0)
        if not _close(got_v, exp_v):
            fails.append(f"Cc[{key!r}]: got {_fmt(got_v)}, expected {_fmt(exp_v)}")
    extras = {k: v for k, v in cc_got.items() if tuple(sorted(k)) not in
              {tuple(sorted(p)) for p in expected["cc"]} and v > ATOL_CAP}
    if extras:
        fails.append(f"unexpected Cc pairs: { {k: _fmt(v) for k, v in extras.items()} }")

    return fails


def run_within_net_case(fixture: str, exp: dict) -> list[str]:
    """Verify within_net_pin_r output against expected pair Rs."""
    fails: list[str] = []
    full = os.path.join(_HERE, fixture)
    circuit = parse_spectre(full)
    res = within_net_pin_r(circuit, exp["net"], max_pins=None)
    pairs = res.get("pairs", {})
    if len(pairs) != exp["expected_pair_count"]:
        fails.append(
            f"pair count: got {len(pairs)}, expected {exp['expected_pair_count']}"
        )
    for pair_key, expected_r in exp["pair_r"].items():
        # Kernel returns tuple keys; reduce both to frozenset for lookup
        got = None
        for (a, b), v in pairs.items():
            if frozenset((a, b)) == pair_key:
                got = v
                break
        if got is None:
            fails.append(f"missing pair: {sorted(pair_key)}")
            continue
        if not _close(got, expected_r):
            fails.append(
                f"R{sorted(pair_key)}: got {_fmt(got)}, expected {_fmt(expected_r)}"
            )
    return fails


def main() -> int:
    print(f"{'FIXTURE':<40s}  {'FORMAT':<8s}  {'STATUS'}")
    print("-" * 70)
    all_fails = 0
    for path, exp, fn, dut in CASES:
        fmt_name = detect_format(os.path.join(_HERE, path))
        fails = run_case(path, exp, fn, dut)
        status = "PASS" if not fails else f"FAIL ({len(fails)})"
        print(f"{os.path.basename(path):<40s}  {fmt_name:<8s}  {status}")
        if fails:
            for f in fails:
                print(f"    - {f}")
            all_fails += len(fails)

    # F4: within-net anchor (separate check shape — not the R/Cg/Cc matrix)
    wn_fails = run_within_net_case(
        "fixtures/f4_within_net.flat.scs", F4_EXPECTED_WITHIN_NET
    )
    wn_status = "PASS" if not wn_fails else f"FAIL ({len(wn_fails)})"
    print(f"{'f4_within_net.flat.scs':<40s}  {'spectre':<8s}  {wn_status}  (within-net)")
    if wn_fails:
        for f in wn_fails:
            print(f"    - {f}")
        all_fails += len(wn_fails)

    print("-" * 70)
    print(f"Total failures: {all_fails}")
    return 0 if all_fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
