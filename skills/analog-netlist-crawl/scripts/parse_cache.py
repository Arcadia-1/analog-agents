"""Shared pickle cache for parsed Circuit objects.

Parsing a 60-MB Calibre netlist is the most expensive step (~8-80s
depending on size).  A pickle cache keyed by (abspath, mtime, size,
format, parse_kw) makes iterative runs near-instant on the same file.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "analog-netlist-crawl-cache")


def _cache_path(source: str, extra_key: str = "") -> str:
    st = os.stat(source)
    key = hashlib.md5(
        f"{os.path.abspath(source)}|{st.st_mtime_ns}|{st.st_size}|{extra_key}".encode()
    ).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{key}.pkl")


def load_or_parse(source: str, *, use_cache: bool = True,
                  parse_kw: dict | None = None,
                  fmt: str | None = None,
                  log=print):
    """Parse a netlist, using a pickle cache keyed by file identity."""
    from adapters import parse_netlist   # lazy — avoids import cycles
    parse_kw = parse_kw or {}
    extra_key = f"fmt={fmt}|{sorted(parse_kw.items())}"
    cache_file = _cache_path(source, extra_key)
    if use_cache and os.path.exists(cache_file):
        t0 = time.perf_counter()
        with open(cache_file, "rb") as fh:
            circuit = pickle.load(fh)
        dt = time.perf_counter() - t0
        log(f"# cache hit  ({dt:.2f}s load, "
            f"{os.path.getsize(cache_file)/1e6:.1f} MB): {cache_file}",
            file=sys.stderr)
        return circuit

    t0 = time.perf_counter()
    circuit = parse_netlist(source, format=fmt, **parse_kw)
    dt_parse = time.perf_counter() - t0

    if use_cache:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(cache_file, "wb") as fh:
                pickle.dump(circuit, fh, protocol=pickle.HIGHEST_PROTOCOL)
            log(f"# parsed + cached  ({dt_parse:.2f}s parse, "
                f"{os.path.getsize(cache_file)/1e6:.1f} MB saved)",
                file=sys.stderr)
        except OSError as e:
            log(f"# cache write failed: {e}", file=sys.stderr)
    else:
        log(f"# parsed  ({dt_parse:.2f}s, cache disabled)", file=sys.stderr)
    return circuit
