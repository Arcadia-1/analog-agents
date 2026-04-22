"""Format-adapter package.

``parse_netlist(path)`` auto-detects the format and dispatches to the
right adapter.  Individual adapters are also importable directly if
the caller wants to force a format.
"""
from __future__ import annotations

from .mrpp import parse_mrpp
from .spectre import parse_spectre


def detect_format(path: str) -> str:
    """Sniff the first ~200 non-comment lines and classify.

    Return one of:  ``"mrpp"``, ``"spectre"``, or ``"unknown"``.

    Calibre mr_pp files commonly open with many ``mgc_rve_device_template``
    lines (~80 of them for a full PDK) before the first ``mr_pp`` payload,
    so we need a generous scan window and treat ``mgc_`` prefixes as an
    mr_pp indicator.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        looked = 0
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith(";") or s.startswith("//") or s.startswith("*"):
                continue
            looked += 1
            if s.startswith("mr_pp ") or s.startswith("mgc_"):
                return "mrpp"
            if s.startswith("simulator ") or s.startswith("subckt "):
                return "spectre"
            if looked > 200:
                break
    return "unknown"


def parse_netlist(path: str, *, format: str | None = None, **kw):
    """Parse a netlist into a Circuit.  Format auto-detected if not given."""
    fmt = format or detect_format(path)
    if fmt == "mrpp":
        return parse_mrpp(path, **kw)
    if fmt == "spectre":
        return parse_spectre(path, **kw)
    raise ValueError(
        f"unknown netlist format for {path!r}; pass format='mrpp' or 'spectre' explicitly"
    )


__all__ = ["parse_mrpp", "parse_spectre", "parse_netlist", "detect_format"]
