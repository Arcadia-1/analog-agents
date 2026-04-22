#!/usr/bin/env python3
"""Apply an R + Cc prescription to a schematic-view netlist.

One job only: read a clean schematic-view ``.scs`` netlist, apply the
JSON prescription produced by ``prescribe.py``, and write a new
``.scs`` with per-pin series R inserted between the schematic-level
net node and every MOS terminal that physically lands on that net in
the post-layout mesh, plus coupling caps added to peer nets.  The
output is a drop-in replacement for the original schematic DUT.

Uniform treatment: for every prescribed net, inject.py enumerates
every MOS pin (D/G/S/B) whose original schematic connection is that
net, renames that pin to ``<net>_<instance>_<role>_post``, and drops
in a 2-level star:

    <net> ──R_common── <net>_hub ─┬── R_branch_i ── <net>_<i>_<role>_post
                                     ├── R_branch_j ── <net>_<j>_<role>_post
                                     └── ...

This captures per-finger spatial asymmetry (drain-side series R, gate
delay, source/body supply IR drop — all at once) from a single
Laplacian solve per net.

This CLI does NOT simulate anything — ship the output to Spectre
yourself (or use the spectre skill).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# Peer-filter defaults: skip anonymous mesh subnodes, device-local names,
# and Calibre's ``_net0`` / ``_net42`` pseudo-nodes.  The user can
# override with ``--allow-peer`` to force-inject specific names.
_ANON_PEER_PATTERNS = [
    r"^c_\d+_[np]$",
    r"^_net\d*$",
    r"^\d+$",
    r"^MM[A-Z0-9_@\\<>]+_[dgsb]$",
]
_ANON_RE = [re.compile(p) for p in _ANON_PEER_PATTERNS]


def _is_anonymous(name: str) -> bool:
    return any(r.match(name) for r in _ANON_RE)


# When a Cc peer resolves to an anonymous name (truly isolated mesh
# subnode or extraction artifact), the physical endpoint is almost
# always bulk / substrate / some floating mesh node AC-coupled to VSS.
# Reroute these to VSS instead of dropping them.  This preserves the
# first-order contribution of 100's of fF of Cc that would otherwise
# vanish from the reduced model.
_ANON_FALLBACK_PEER = "VSS"


_INST_LINE = re.compile(r"^(\s*)(\S+)\s*\(([^)]*)\)\s*(\S+)(.*)$")

# 4-pin MOS order in Spectre subckt calls: (D G S B) at positions 0..3.
_ROLE_IDX = {"D": 0, "G": 1, "S": 2, "B": 3}


def _post_name(net: str, instance: str, role: str) -> str:
    """Rename token for a specific (net, instance, role) pin.  Sanitised
    for Spectre-legal node names (strip backslash-escape + @ finger
    suffixes → '_')."""
    safe_inst = re.sub(r"[^A-Za-z0-9_]", "_", instance)
    return f"{net}_{safe_inst}_{role}_post"


def _rewrite_instance_line(
    line: str,
    rewrites: dict[str, dict[str, str]],
) -> str:
    """``rewrites[instance_name][role] = new_pin_token`` — for each MOS
    instance line, replace any listed pin positions."""
    m = _INST_LINE.match(line)
    if not m:
        return line
    indent, name, pins_s, model, tail = m.groups()
    if name not in rewrites:
        return line
    pins = pins_s.split()
    role_map = rewrites[name]
    changed = False
    for role, new_tok in role_map.items():
        idx = _ROLE_IDX.get(role)
        if idx is None or idx >= len(pins):
            continue
        pins[idx] = new_tok
        changed = True
    if changed:
        return f"{indent}{name} ({' '.join(pins)}) {model}{tail}\n"
    return line


def apply_prescription(
    in_netlist: Path,
    out_netlist: Path,
    subckt_name: str,
    prescriptions: list[dict],
    *,
    inter_net_couplings: list[dict] | None = None,
    min_cc: float = 0.0,
    min_branch_r: float = 0.0,
    allow_peer: list[str] | None = None,
    log=print,
) -> None:
    """Core injection logic.

    Reads ``pin_entries`` + ``r_common`` + ``r_branch`` from each
    prescription and emits a per-pin star.

    Parameters
    ----------
    min_cc : float
        Drop Cc peers below this value in farads.
    min_branch_r : float
        Drop per-pin branch resistors below this value in Ω.  Useful
        to keep only pins that actually see non-trivial parasitic R.
        Default 0 keeps every pin.
    allow_peer : list[str]
        If set, override the anonymous-peer filter for these names.
    """
    # Collect per-instance rewrites: which MOS role indices to change,
    # and to which new token.
    rewrites: dict[str, dict[str, str]] = {}
    # Also collect R injections and Cc attachments.
    for rx in prescriptions:
        net = rx["net"]
        r_branch = rx.get("r_branch") or {}
        # Filter out pins with sub-threshold branch R — we still rename
        # them but the R we emit = 0.  Simpler: just skip them entirely
        # (their connection stays on the bare net).
        for pe in (rx.get("pin_entries") or []):
            key = pe["key"]
            r = r_branch.get(key)
            if r is None or r <= min_branch_r:
                continue
            rewrites.setdefault(pe["instance"], {})[pe["role"]] = (
                _post_name(net, pe["instance"], pe["role"]))

    with open(in_netlist, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.readlines()

    ends_re = re.compile(rf"^\s*ends\s+{re.escape(subckt_name)}\b")
    ends_idx = next((i for i, ln in enumerate(raw) if ends_re.match(ln)), None)
    if ends_idx is None:
        raise RuntimeError(f"no `ends {subckt_name}` line in {in_netlist}")

    # Walk lines, joining backslash-continuations before rewriting
    # instance lines.
    out_lines: list[str] = []
    i = 0
    while i < ends_idx:
        buf = raw[i]
        while buf.rstrip().endswith("\\") and i + 1 < len(raw):
            i += 1
            buf = buf.rstrip()[:-1] + " " + raw[i]
        if i >= ends_idx:
            break
        out_lines.append(_rewrite_instance_line(buf, rewrites))
        i += 1

    # Build the injected block.
    inj: list[str] = ["\n", "// --- injected by netlist-crawl inject.py ---\n"]
    allow_peer_set = set(allow_peer or [])
    for rx in prescriptions:
        net = rx["net"]
        r_common = rx.get("r_common") or 0.0
        r_branch = rx.get("r_branch") or {}
        r_eff = rx.get("r_eff")
        pin_entries = rx.get("pin_entries") or []
        # Decide which pins actually get branches after the threshold filter.
        live_pins = [pe for pe in pin_entries
                     if (r_branch.get(pe["key"], 0.0) > min_branch_r)]

        # Prefer Foster-ladder per-pin synthesis when present.
        foster = rx.get("foster") or {}
        live_pins_foster = [pe for pe in pin_entries if foster.get(pe["key"])]

        if live_pins_foster:
            # Foster path: hub node between port and Foster ladder absorbs
            # the shared R_common bottleneck.  Each pin gets its own
            # Foster ladder from hub to the pin's post-node.  This is
            # the correct topology — without the hub, per-pin parallel R
            # collapses aggregate DC impedance in high-fanout nets (e.g.
            # VDD with thousands of fingers).
            hub_node = f"{net}_hub"
            if r_common > 1e-18:
                inj.append(
                    f"R_rc_common_{net} ({net} {hub_node}) "
                    f"resistor r={r_common:.6g}\n")
            else:
                # Collapse hub to port via a near-short.
                inj.append(
                    f"R_rc_common_{net} ({net} {hub_node}) resistor r=1e-6\n")
            for pe in live_pins_foster:
                key = pe["key"]
                sec = foster[key]
                R_inf = sec.get("R_inf", 0.0)
                sections = sec.get("sections", [])
                safe_inst = re.sub(r"[^A-Za-z0-9_]", "_", pe["instance"])
                tag = f"{safe_inst}_{pe['role']}_{net}"
                pin_node = _post_name(net, pe["instance"], pe["role"])
                # Build chain: hub --R_inf-- m_0 --[R1||C1]-- m_1 --[R2||C2]-- ... -- pin
                cur = hub_node
                if R_inf > 1e-18 and sections:
                    mid = f"{tag}_m0"
                    inj.append(
                        f"R_rc_{tag}_inf ({cur} {mid}) resistor r={R_inf:.6g}\n")
                    cur = mid
                elif R_inf > 1e-18 and not sections:
                    # Pure resistor — goes directly to pin node.
                    inj.append(
                        f"R_rc_{tag}_inf ({cur} {pin_node}) resistor r={R_inf:.6g}\n")
                    continue
                for i, (Ri, tau_i) in enumerate(sections):
                    Ci = tau_i / Ri if Ri > 0 else 0.0
                    nxt = pin_node if i == len(sections) - 1 else f"{tag}_m{i+1}"
                    inj.append(
                        f"R_rc_{tag}_s{i} ({cur} {nxt}) resistor r={Ri:.6g}\n")
                    if Ci > 1e-30:
                        inj.append(
                            f"C_rc_{tag}_s{i} ({cur} {nxt}) capacitor c={Ci:.6g}\n")
                    cur = nxt
        elif not live_pins:
            # No per-pin stubs — fall back to a lumped R if we have one.
            if isinstance(r_eff, (int, float)) and r_eff not in (float("inf"),) and r_eff > 0:
                pass
            hub_node = net
        else:
            # Legacy star (R_common + per-pin R_branch).
            hub_node = f"{net}_hub"
            if r_common > 0:
                inj.append(
                    f"R_rc_common_{net} ({net} {hub_node}) "
                    f"resistor r={r_common:.6g}\n")
            else:
                inj.append(
                    f"R_rc_common_{net} ({net} {hub_node}) resistor r=1e-6\n")
            for pe in live_pins:
                key = pe["key"]
                r = r_branch[key]
                node = _post_name(net, pe["instance"], pe["role"])
                safe_inst = re.sub(r"[^A-Za-z0-9_]", "_", pe["instance"])
                inj.append(
                    f"R_rc_{safe_inst}_{pe['role']}_{net} "
                    f"({hub_node} {node}) resistor r={r:.6g}\n")

        # Cc distribution: driver-side Cc attaches to `<net>` (bare port),
        # load-side Cc attaches to `<hub>`.  Anonymous-peer filter and
        # duplicate-with-inter-net skip still apply.
        cc_driver = rx.get("cc_driver_side") or {}
        cc_load   = rx.get("cc_load_side")   or {}
        if not cc_driver and not cc_load:
            cc_driver = rx.get("cc_distribution") or {}
        for side, host_node, cc in [
                ("d", net, cc_driver),
                ("l", hub_node, cc_load),
        ]:
            # Aggregate anonymous peers into a single VSS-bound cap.
            # Keeps the total bulk coupling (many 100's of fF on big
            # nets) in the reduced model instead of silently dropping it.
            anon_total = 0.0
            n_anon = 0
            for peer, val in cc.items():
                if val < min_cc: continue
                if peer == net or peer == f"{net}_hub": continue
                if peer not in allow_peer_set and _is_anonymous(peer):
                    anon_total += val; n_anon += 1
                    continue
                safe_peer = re.sub(r"[^A-Za-z0-9_]", "_", peer)
                inj.append(
                    f"C_rc_{side}_{net}_{safe_peer} "
                    f"({host_node} {peer}) capacitor c={val:.6g}\n")
            if anon_total > min_cc:
                inj.append(
                    f"C_rc_{side}_{net}_anonbulk ({host_node} "
                    f"{_ANON_FALLBACK_PEER}) capacitor c={anon_total:.6g}\n")
                log(f"  [{net}:{side}-side] aggregated {n_anon} anonymous "
                    f"Cc peers into bulk → {_ANON_FALLBACK_PEER} "
                    f"(Σ = {anon_total*1e15:.1f} fF)")

    # Inter-net Cc: between two prescribed nets — each (port_A or hub_A)
    # to (port_B or hub_B) per the 4-way split.
    for ic in inter_net_couplings or []:
        na, nb = ic["net_a"], ic["net_b"]
        hub_a = f"{na}_hub"
        hub_b = f"{nb}_hub"
        # Check that both nets are actually prescribed (= have a hub).
        if not any(rx["net"] == na for rx in prescriptions): continue
        if not any(rx["net"] == nb for rx in prescriptions): continue
        safe_na = re.sub(r"[^A-Za-z0-9_]", "_", na)
        safe_nb = re.sub(r"[^A-Za-z0-9_]", "_", nb)
        pairs = [
            ("DD", na,    nb),
            ("DL", na,    hub_b),
            ("LD", hub_a, nb),
            ("LL", hub_a, hub_b),
        ]
        for tag, node_a, node_b in pairs:
            val = ic.get(tag, 0.0)
            if val < min_cc: continue
            inj.append(
                f"C_rc_ij_{tag}_{safe_na}_{safe_nb} "
                f"({node_a} {node_b}) capacitor c={val:.6g}\n")

    inj.append("// --- end injection ---\n\n")

    with open(out_netlist, "w", encoding="utf-8") as fh:
        fh.writelines(out_lines)
        fh.writelines(inj)
        fh.writelines(raw[ends_idx:])

    log(f"wrote {out_netlist}")
    for rx in prescriptions:
        net = rx["net"]
        r_branch = rx.get("r_branch") or {}
        n_pins = sum(1 for v in r_branch.values() if v > min_branch_r)
        r_common = rx.get("r_common", 0.0)
        log(f"  {net}: {n_pins} pin(s) → {net}_hub via per-pin R_branch  "
            f"(R_common={r_common:.3g} Ω, {len(rx.get('cc_distribution') or {})} Cc peers)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("schematic", help="clean schematic-view .scs netlist")
    ap.add_argument("prescription_json", help="JSON from prescribe.py")
    ap.add_argument("--dut", required=True,
                    help="DUT subckt name (must match the schematic)")
    ap.add_argument("--min-cc", type=float, default=1e-16,
                    help="drop Cc peers below this (farads, default 0.1 fF)")
    ap.add_argument("--min-branch-r", type=float, default=0.0,
                    help="drop per-pin branch Rs below this (Ω, default 0 keeps all)")
    ap.add_argument("--allow-peer", action="append", default=[],
                    help="force-inject this peer name even if it looks "
                         "anonymous; repeatable")
    ap.add_argument("-o", "--output", required=True,
                    help="output .scs path")
    args = ap.parse_args(argv)

    rx_doc = json.loads(Path(args.prescription_json).read_text(encoding="utf-8"))
    prescriptions = rx_doc.get("prescriptions") or []
    inter_net   = rx_doc.get("inter_net_couplings") or []
    if not prescriptions:
        raise SystemExit("prescription JSON has no `prescriptions` entries")

    apply_prescription(
        in_netlist=Path(args.schematic),
        out_netlist=Path(args.output),
        subckt_name=args.dut,
        prescriptions=prescriptions,
        inter_net_couplings=inter_net,
        min_cc=args.min_cc,
        min_branch_r=args.min_branch_r,
        allow_peer=args.allow_peer,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
