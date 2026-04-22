"""Calibre mr_pp syntax adapter (self-contained .pex.netlist files).

Format looks like::

    mr_pp 'r "rSETN_188072"  '("node_a" "node_b")     0.282454
    mr_pp 'c "ciVREFOUT_27551" '("n" "VSS")           0.00476236f
    mr_pp 'c "cc_391728"       '("na" "nb")           0.0269134f

Discrimination between Cg and Cc is by terminal: if either terminal is
a power rail (via ``ir.is_power``), it's Cg.  Otherwise Cc.  We do NOT
rely on instance name prefixes — `ci`, `c_`, `cc_` are hints, not
contract.
"""
from __future__ import annotations

import os
import re

from ir import Circuit, is_power
from adapters._util import parse_si


# mr_pp lines:  mr_pp '<kind> "<name>" '(<pair>) <value>
_MRPP_LINE = re.compile(
    r"""^\s*mr_pp\s+'(?P<kind>[rc])\s+
        "(?P<name>[^"]+)"\s+
        '\(\s*(?P<pair>[^)]*)\s*\)\s+
        (?P<value>\S+)""",
    re.VERBOSE,
)

# Pin tokens inside the paren-pair look like  "name1" "name2"  — extract
# each quoted token.
_PIN_TOK = re.compile(r'"([^"]+)"')


def parse_mrpp(path: str, *, dut_name: str | None = None) -> Circuit:
    """Parse a Calibre mr_pp netlist into a Circuit.

    ``dut_name`` is cosmetic — mr_pp files don't wrap content in a
    subckt so the whole file IS the DUT.  Default is the filename stem.
    """
    if dut_name is None:
        dut_name = os.path.splitext(os.path.basename(path))[0]

    c = Circuit(
        dut=dut_name,
        metadata={"source_file": os.path.abspath(path), "format": "calibre_mrpp"},
    )

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith(";") or s.startswith("//") or s.startswith("mgc_"):
                continue
            m = _MRPP_LINE.match(s)
            if not m:
                continue
            kind = m.group("kind")
            name = m.group("name")
            pins = _PIN_TOK.findall(m.group("pair"))
            if len(pins) != 2:
                continue
            a, b = pins[0], pins[1]
            val = parse_si(m.group("value"))
            if val != val:  # NaN
                continue
            if kind == "r":
                c.r_edges.append((a, b, val, name))
            else:  # 'c
                if is_power(a) and is_power(b):
                    continue  # pure rail-to-rail cap, ignore
                if is_power(a) or is_power(b):
                    # put signal terminal first, rail second — convention
                    if is_power(a):
                        a, b = b, a
                    c.cg_edges.append((a, b, val, name))
                else:
                    c.cc_edges.append((a, b, val, name))

    c.metadata["n_lines_parsed"] = len(c.r_edges) + len(c.cg_edges) + len(c.cc_edges)
    return c
