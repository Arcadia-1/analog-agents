"""Shared lexical helpers used by all format adapters."""
from __future__ import annotations

import re


_SI = {
    "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6,
    "\u00b5": 1e-6, "m": 1e-3, "K": 1e3, "k": 1e3,
    "M": 1e6, "G": 1e9, "T": 1e12,
}

# number [SI][F]  e.g. "0.0269134f", "1e-15", "10.0", "5p"
_VALUE_RE = re.compile(
    r"""^\s*
        ([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)    # mantissa
        \s*
        ([afpnum\u00b5mKkMGT]?)                # optional SI prefix
        \s*[fF]?                               # optional trailing 'F' / 'f' for Farad unit
        \s*$
    """,
    re.VERBOSE,
)


def parse_si(s: str) -> float:
    """Parse numbers with SI suffix.  ``'5p'`` → 5e-12, ``'0.1f'`` → 1e-16.

    Returns float('nan') on unparseable input; callers should filter NaN
    rather than crashing, to keep the parser resilient against stray
    comments or unexpected lines.
    """
    m = _VALUE_RE.match(s)
    if not m:
        try:
            return float(s)
        except Exception:
            return float("nan")
    mant = float(m.group(1))
    pref = m.group(2)
    if pref:
        mant *= _SI.get(pref, 1.0)
    return mant
