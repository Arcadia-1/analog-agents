"""Spectre-syntax adapter.

Handles, with the same parser:
  (a) flat netlists          — no subckt wrap; top-level R/C
  (b) subckt-wrapped DUT     — single `subckt <DUT> ... ends`
  (c) subckt + includes      — split-file Calibre output with absolute
                               Linux `include "..."` paths; portable
                               basename fallback in the same dir
  (d) helper-subckt flatten  — pre-declared parasitic subckts referenced
                               inside the DUT get inlined via their
                               positional pin mapping [see _flatten_pass]

Design: one recursive line iterator that inlines includes in textual
order (so subckt scope is preserved across include boundaries), and one
single-pass parser that recognises `subckt` / `ends` / element lines.
The `Circuit.alias` map is how subnode-to-canonical-net resolution
survives the flatten pass — the adapter populates it, kernels read it.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict, Counter

from ir import Circuit, Device, is_power
from adapters._util import parse_si


# ---- low-level file handling -----------------------------------------------

_BS = chr(92)  # backslash; used in Calibre's \< \> escapes


def _iter_logical_lines(path: str):
    """Yield logical lines from one file, joining backslash continuations."""
    buf = ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n").rstrip("\r")
            if line.rstrip().endswith(_BS) and not line.rstrip().endswith(_BS * 2):
                buf += line.rstrip()[:-1] + " "
            else:
                buf += line
                yield buf
                buf = ""
        if buf:
            yield buf


# plain PEX-style include; PDK includes have `section=...` and we skip them
_PEX_INCLUDE_RE = re.compile(r'^\s*include\s+"([^"]+)"\s*$')


def _resolve_include(inc_literal: str, main_dir: str) -> str | None:
    """Literal path first, then basename-in-main-dir fallback."""
    cand = inc_literal if os.path.isabs(inc_literal) else os.path.join(main_dir, inc_literal)
    if os.path.exists(cand):
        return os.path.abspath(cand)
    alt = os.path.join(main_dir, os.path.basename(inc_literal))
    if os.path.exists(alt):
        return os.path.abspath(alt)
    return None


def iter_lines_with_includes(path: str, _seen=None):
    """Yield logical lines, inlining PEX includes in textual order.

    Textual order matters: Calibre places include directives INSIDE the
    DUT subckt body, and the included content must appear within that
    scope so `ends DUT` fires after everything is streamed.
    """
    if _seen is None:
        _seen = set()
    abs_path = os.path.abspath(path)
    if abs_path in _seen:
        return
    _seen.add(abs_path)
    main_dir = os.path.dirname(abs_path)
    for ln in _iter_logical_lines(path):
        m = _PEX_INCLUDE_RE.match(ln)
        if not m:
            yield ln
            continue
        resolved = _resolve_include(m.group(1), main_dir)
        if resolved is None:
            # PDK or missing include — don't chase it, keep the line visible
            yield ln
            continue
        yield from iter_lines_with_includes(resolved, _seen)


# ---- element-line lexing ---------------------------------------------------

# <inst> ( <pins> ) <model> <params...>
_ELEMENT_RE = re.compile(r'^\s*(\S+)\s*\(\s*([^)]*?)\s*\)\s*(\S+)\s*(.*)$')
_SUBCKT_RE  = re.compile(r'^\s*subckt\s+(\S+)\s*\(?\s*(.*?)\s*\)?\s*$')
_ENDS_RE    = re.compile(r'^\s*ends\b\s*(\S*)')
_PARAM_RE   = re.compile(r'(\w+)\s*=\s*(\S+)')


def _normalize_pin(p: str) -> str:
    """Collapse Calibre's `\<` / `\>` bracket escapes to underscore form."""
    return p.replace(_BS + "<", "_").replace(_BS + ">", "")


_BUILTIN_ELEMENTS = {"resistor", "capacitor", "inductor",
                     "isource", "vsource", "diode", "bsource", "iprobe"}


def _is_mos(model_lc: str) -> bool:
    return (model_lc.endswith("_mac")
            or "nch" in model_lc or "pch" in model_lc
            or "nfet" in model_lc or "pfet" in model_lc
            or "nmos" in model_lc or "pmos" in model_lc)


# ---- top-level parser ------------------------------------------------------

def parse_spectre(path: str, *, dut_name: str | None = None) -> Circuit:
    """Parse a Spectre-syntax netlist into a Circuit.

    Strategy:
      1. First pass:  build a table of all subckt definitions (name →
         pins + body lines).  Also note the DUT (largest subckt, or
         ``None`` → flat mode).
      2. Second pass: walk the DUT body; for each line, route to R / Cg
         / Cc / device, or recurse into a helper-subckt instantiation
         with a fresh pin-alias map (subckt flattening).
    """
    subckts = _collect_subckt_definitions(path)
    # Decide DUT
    if dut_name is None:
        if subckts:
            # Pick the subckt with the most body lines.
            dut_name = max(subckts, key=lambda k: len(subckts[k]["body"]))
        else:
            dut_name = os.path.splitext(os.path.basename(path))[0]

    c = Circuit(
        dut=dut_name,
        metadata={
            "source_file": os.path.abspath(path),
            "format": "spectre",
            "has_subckt": bool(subckts),
            "subckt_count": len(subckts),
        },
    )
    if dut_name in subckts:
        c.ports = list(subckts[dut_name]["pins"])
        # Walk the DUT body with an empty rename map (identity).
        _walk_body(c, subckts[dut_name]["body"], subckts,
                   rename={}, instance_prefix="")
    else:
        # Flat mode: the DUT "body" is every non-subckt-definition line
        # in the file.  Collect those once.
        body = _collect_flat_body(path, subckts)
        _walk_body(c, body, subckts, rename={}, instance_prefix="")

    return c


def _collect_subckt_definitions(path: str) -> dict[str, dict]:
    """First pass: return ``{name: {"pins": [...], "body": [line, ...]}}``."""
    subs: dict[str, dict] = {}
    stack: list[str] = []
    cur_body: list[list[str]] = []   # stack of body lists, parallel to `stack`
    for ln in iter_lines_with_includes(path):
        s = ln.strip()
        if not s:
            continue
        # strip inline // comment
        if "//" in s:
            s = s.split("//", 1)[0].rstrip()
            if not s:
                continue
        m = _SUBCKT_RE.match(s)
        if m:
            name = m.group(1)
            pins_raw = m.group(2)
            pins = [_normalize_pin(p) for p in pins_raw.split() if p and p not in ("(", ")")]
            subs[name] = {"pins": pins, "body": []}
            stack.append(name)
            cur_body.append(subs[name]["body"])
            continue
        m = _ENDS_RE.match(s)
        if m:
            if stack:
                stack.pop()
                cur_body.pop()
            continue
        if stack:
            cur_body[-1].append(s)
    return subs


def _collect_flat_body(path: str, subs: dict[str, dict]) -> list[str]:
    """For flat netlists: everything outside any subckt definition."""
    out: list[str] = []
    stack: list[str] = []
    for ln in iter_lines_with_includes(path):
        s = ln.strip()
        if not s:
            continue
        if "//" in s:
            s = s.split("//", 1)[0].rstrip()
            if not s:
                continue
        if _SUBCKT_RE.match(s):
            stack.append("_")
            continue
        if _ENDS_RE.match(s):
            if stack:
                stack.pop()
            continue
        if stack:
            continue   # skip content inside subckt definitions
        if s.startswith("simulator") or s.startswith("global") or s.startswith("include"):
            continue
        out.append(s)
    return out


def _walk_body(
    c: Circuit,
    body: list[str],
    subs: dict[str, dict],
    rename: dict[str, str],
    instance_prefix: str,
) -> None:
    """Walk a subckt body (or flat body).  Parse elements, recurse into
    helper-subckt instantiations.

    ``rename`` maps the callee subckt's local pin names → caller-scope
    net names.  ``instance_prefix`` tags internal subnodes with the
    instance path so flattened helpers don't collide.
    """
    for s in body:
        if s.startswith("simulator") or s.startswith("global") or s.startswith("include"):
            continue
        m = _ELEMENT_RE.match(s)
        if not m:
            continue
        inst, pins_s, model, rest = m.groups()
        model_lc = model.lower()
        pins = [_normalize_pin(p) for p in pins_s.split()]
        if not pins:
            continue

        def remap(node: str) -> str:
            if node in rename:
                return rename[node]
            if is_power(node):
                return node
            # internal subnode of a flattened helper — prefix to namespace it
            if instance_prefix:
                return f"{instance_prefix}/{node}"
            return node

        mapped = [remap(p) for p in pins]
        full_inst = f"{instance_prefix}/{inst}" if instance_prefix else inst

        if model_lc == "resistor":
            if len(mapped) != 2:
                continue
            rv = parse_si(_param(rest, "r"))
            if rv != rv:
                continue
            c.r_edges.append((mapped[0], mapped[1], rv, full_inst))
            continue

        if model_lc == "capacitor":
            if len(mapped) != 2:
                continue
            cv = parse_si(_param(rest, "c"))
            if cv != cv:
                continue
            a, b = mapped[0], mapped[1]
            if is_power(a) and is_power(b):
                continue
            if is_power(a) or is_power(b):
                if is_power(a):
                    a, b = b, a
                c.cg_edges.append((a, b, cv, full_inst))
            else:
                c.cc_edges.append((a, b, cv, full_inst))
            continue

        if model_lc in _BUILTIN_ELEMENTS:
            continue  # inductor / source / etc. — not our concern

        if _is_mos(model_lc):
            # D G S B positional
            roles = ("D", "G", "S", "B")
            pin_map = {r: mapped[i] for i, r in enumerate(roles) if i < len(mapped)}
            c.devices.append(Device(name=full_inst, model=model, pins=pin_map,
                                     params=dict(_PARAM_RE.findall(rest))))
            continue

        # Everything else = subckt instantiation.  Recurse if we know it.
        callee = subs.get(model)
        if callee is None:
            # Unknown subckt — keep as an opaque device; don't flatten.
            c.devices.append(Device(name=full_inst, model=model,
                                     pins={str(i): n for i, n in enumerate(mapped)},
                                     params=dict(_PARAM_RE.findall(rest))))
            continue
        # Build the child rename map: callee's local pin name → caller-side node
        if len(mapped) != len(callee["pins"]):
            # Arity mismatch — can't flatten safely; treat as opaque.
            c.devices.append(Device(name=full_inst, model=model,
                                     pins={str(i): n for i, n in enumerate(mapped)},
                                     params=dict(_PARAM_RE.findall(rest))))
            continue
        child_rename = dict(zip(callee["pins"], mapped))
        child_prefix = full_inst
        _walk_body(c, callee["body"], subs, child_rename, child_prefix)


def _param(rest: str, key: str) -> str:
    """Pull a named parameter out of the `k=v k=v ...` tail.  Missing → ''."""
    for k, v in _PARAM_RE.findall(rest):
        if k.lower() == key.lower():
            return v
    return ""
