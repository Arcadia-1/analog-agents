#!/usr/bin/env python3
"""Strip parasitic R/C from an rcc-extracted netlist, keeping only the
device rows (MOSFETs, diodes — every per-finger instance with its full
LOD/WPE/STI-stress parameter set) and remapping each device pin from
its mesh subnode back to the canonical net name.

The output is a clean subckt-wrapped DUT with *identical* transistor
modelling to the rcc extraction (same per-finger LOD params, same
placement-dependent ``sa/sb/enx/eny/...``) but NO parasitic mesh.  It
is equivalent to a ``norc`` view, reconstructed from the rcc netlist,
so there's no need to run a separate norc extraction.

``inject.py`` then drops the lumped R+Cc prescription onto this clean
device-only netlist.

Usage::

    python strip_parasitics.py <rcc.scs> \\
        --dut AMP_5T_D2S \\
        --ports "I_DOWN,VDD,VIN,VIP,VOUT,VSS" \\
        -o AMP_5T_D2S_devices.scs
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from adapters import parse_netlist
from kernels.r_network import _build_adjacency, _component_of


# Spectre/SPICE device-line prefixes we keep.
# MOSFETs: M/MM (incl. \@finger escapes), Diodes: D (incl. noxref placeholders).
_KEEP_LINE = re.compile(r"^\s*(M\w|D\w)")


def _is_kept_device_model(model_lc: str) -> bool:
    """Parasitic R/C/Cc are stored in circuit.r_edges / cg_edges /
    cc_edges by the parser and NEVER become Device objects.  So every
    entry in ``circuit.devices`` is a designer-placed element (MOS,
    diode, designer R like rupolym, designer C like cfmom_2t, BJT...)
    and should be preserved.  Blanket-accept returns True."""
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("netlist", help="rcc-extracted .scs netlist")
    ap.add_argument("--dut", required=True,
                    help="subckt name to wrap the device-only output in")
    ap.add_argument("--ports", required=True,
                    help="comma-separated ordered DUT ports, e.g. "
                         "'I_DOWN,VDD,VIN,VIP,VOUT,VSS'")
    ap.add_argument("--internal-nets", default="",
                    help="comma-separated non-port canonical nets that "
                         "live INSIDE the DUT (e.g. 'net1,net2').  Mesh "
                         "subnodes inside these nets' R-components will "
                         "be folded back to the canonical name.  Default: "
                         "auto-discover by walking every non-anonymous "
                         "canonical name in the netlist.")
    ap.add_argument("--format", default=None, choices=("mrpp", "spectre"))
    ap.add_argument("--keep", default="none",
                    help="which parasitic element classes to keep in the "
                         "output, comma-separated.  Choices: "
                         "'none' (default, devices-only, equivalent to "
                         "norc), 'r' (R mesh only), 'cg' (ground caps "
                         "only), 'cc' (coupling caps only), or any "
                         "combination like 'r,cg' or 'r,cg,cc' "
                         "(latter is equivalent to the original rcc). "
                         "When any parasitics are kept, MOS pins are "
                         "emitted with their ORIGINAL mesh subnode names "
                         "so the kept edges stay connected; when keep=none, "
                         "pins are folded to canonical net names.")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)

    keep_set = {x.strip() for x in args.keep.split(",") if x.strip()}
    if keep_set == {"none"} or not keep_set:
        keep_set = set()
    valid = {"none", "r", "cg", "cc"}
    bad = keep_set - valid
    if bad:
        raise SystemExit(f"--keep: unknown class(es): {bad}.  Valid: {valid}")

    if not os.path.exists(args.netlist):
        raise SystemExit(f"no such file: {args.netlist}")
    ports = [p.strip() for p in args.ports.split(",") if p.strip()]

    circuit = parse_netlist(args.netlist, format=args.format)

    # Build {device_name: Device} for O(1) lookup while streaming lines.
    dev_by_name = {d.name: d for d in circuit.devices}
    kept_names = {n for n, d in dev_by_name.items()
                  if _is_kept_device_model(d.model.lower())}

    # Collapse the R-mesh: every R-connected component becomes ONE
    # logical node in the device-only output.  Pick the component's
    # canonical name by priority:
    #   (1) a declared DUT port  (highest)
    #   (2) a declared internal net
    #   (3) a canonical from canonicalize() that isn't anonymous
    #   (4) a synthetic ``mesh_<id>`` name  (lowest)
    #
    # Designer devices (XR, XC) that were connected to the mesh only
    # via parasitic R will now land on whichever name the containing
    # component claims — which is always a real canonical if one exists
    # in that component.  No designer pin is left with a raw subnode
    # name, so the circuit topology is preserved end-to-end.
    import re as _re
    _ANON = [_re.compile(p) for p in (
        r"^c_\d+_[np]$",       # Calibre anonymous mesh subnode
        r"^_net\d*$",          # Calibre pseudo-net
        r"^\d+$",              # numeric helper local
        r".+_[dgsb]$",         # device-local pin name (MM42_d etc.)
        r".+_plus$", r".+_minus$",  # designer-device local pin
        r"^noxref", r"_noxref", # unresolved extraction markers
    )]
    def _is_anon(c: str) -> bool:
        return any(r.match(c) for r in _ANON)

    priority_ports = set(ports)
    priority_internal = set(
        x.strip() for x in args.internal_nets.split(",") if x.strip())

    adj = _build_adjacency(circuit)

    # All nodes that appear in any edge (the mesh universe).
    mesh_nodes: set[str] = set()
    for edges in (circuit.r_edges, circuit.cg_edges, circuit.cc_edges):
        for e in edges:
            mesh_nodes.add(e[0]); mesh_nodes.add(e[1])
    # Also ensure every device pin is considered.
    for d in circuit.devices:
        for sn in d.pins.values():
            mesh_nodes.add(sn)

    # Find R-connected components.  Nodes with no R-edges form
    # singleton components; they get their own canonical.
    node_to_comp: dict[str, int] = {}
    comps: list[set[str]] = []
    for n in mesh_nodes:
        if n in node_to_comp:
            continue
        comp = _component_of(adj, {n})
        cid = len(comps)
        comps.append(comp)
        for m in comp:
            node_to_comp[m] = cid

    # Pick canonical name per component by priority.
    comp_name: list[str] = [""] * len(comps)
    for cid, comp in enumerate(comps):
        pick = None
        pri = 99
        for n in comp:
            cn = circuit.canonical(n)
            if cn in priority_ports and pri > 0:
                pick, pri = cn, 0
            elif cn in priority_internal and pri > 1:
                pick, pri = cn, 1
            elif cn and not _is_anon(cn) and pri > 2:
                # tiebreak: prefer shorter (more "schematic-like") names
                if pri > 2 or (pick and len(cn) < len(pick)):
                    pick, pri = cn, 2
            if pri == 0:
                break
        if pick is None:
            pick = f"mesh_{cid}"
        comp_name[cid] = pick

    # Final subnode → canonical map.
    node_to_canon: dict[str, str] = {
        n: comp_name[cid] for n, cid in node_to_comp.items()
    }
    internals = sorted(set(comp_name) - priority_ports - {f"mesh_{i}" for i in range(len(comps))})
    synth = sum(1 for c in comp_name if c.startswith("mesh_"))
    print(f"  {len(comps)} R-components folded into "
          f"{len(set(comp_name))} canonical names "
          f"({len(priority_ports & set(comp_name))} ports, "
          f"{len(internals)} internal names, "
          f"{synth} synthetic mesh_*)",
          file=sys.stderr)

    # Read the raw netlist and emit a cleaned subckt.
    src = Path(args.netlist).read_text(encoding="utf-8", errors="replace")
    # Fold backslash-continued lines so we can match per statement.
    folded = re.sub(r"\\\s*\n\s*", " ", src)

    # When keeping any parasitics, we CANNOT fold MOS pin subnodes to
    # canonical names — that would disconnect the mesh (pin lands on
    # VDD canonical while R mesh uses MM3_s subnode).  So only fold in
    # pure devices-only mode.
    do_fold = not keep_set

    body_lines: list[str] = []
    for line in folded.splitlines():
        m = re.match(
            r"^\s*(\S+)\s*\(([^)]+)\)\s+(\S+)\s*(.*)$", line)
        if not m:
            continue
        name, pin_str, model, tail = m.groups()
        if name not in kept_names:
            continue
        pins = pin_str.split()
        if do_fold:
            new_pins = [
                (node_to_canon.get(n) or circuit.canonical(n) or n)
                for n in pins
            ]
        else:
            new_pins = pins
        body_lines.append(
            f"    {name} ({' '.join(new_pins)}) {model} {tail}".rstrip())

    # Parasitic element emission.  For each kept class, emit each edge
    # with its original element name so the generated netlist stays
    # traceable back to the rcc.
    parasitic_lines: list[str] = []
    n_r = n_cg = n_cc = 0
    if "r" in keep_set:
        for e in circuit.r_edges:
            a, b, v = e[0], e[1], e[2]
            ename = e[3] if len(e) > 3 else f"r_{n_r}"
            if v <= 0: continue
            parasitic_lines.append(f"    {ename} ({a} {b}) resistor r={v:.6g}")
            n_r += 1
    if "cg" in keep_set:
        for e in circuit.cg_edges:
            a, b, v = e[0], e[1], e[2]
            ename = e[3] if len(e) > 3 else f"cg_{n_cg}"
            if v <= 0: continue
            parasitic_lines.append(f"    {ename} ({a} {b}) capacitor c={v:.6g}")
            n_cg += 1
    if "cc" in keep_set:
        for e in circuit.cc_edges:
            a, b, v = e[0], e[1], e[2]
            ename = e[3] if len(e) > 3 else f"cc_{n_cc}"
            if v <= 0: continue
            parasitic_lines.append(f"    {ename} ({a} {b}) capacitor c={v:.6g}")
            n_cc += 1

    mode_desc = "devices only (no parasitics)" if not keep_set \
                else f"devices + {'+'.join(sorted(keep_set))}"

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(f"// Reduction of {os.path.abspath(args.netlist)}\n")
        fh.write(f"// Mode: {mode_desc}\n")
        fh.write(f"// Devices: {len(body_lines)}; "
                 f"parasitic R: {n_r}, Cg: {n_cg}, Cc: {n_cc}\n")
        if not keep_set:
            fh.write("// MOS pins remapped from mesh subnodes to canonical nets.\n")
        else:
            fh.write("// MOS pins preserved as original mesh subnodes "
                     "so kept parasitic edges stay connected.\n")
        fh.write("simulator lang=spectre\n\n")
        fh.write(f"subckt {args.dut} {' '.join(ports)}\n")
        for ln in body_lines:
            fh.write(ln + "\n")
        if parasitic_lines:
            fh.write("\n// --- kept parasitic edges ---\n")
            for ln in parasitic_lines:
                fh.write(ln + "\n")
        fh.write(f"ends {args.dut}\n")

    print(f"wrote {out_path}  ({len(body_lines)} devices, "
          f"{n_r} R, {n_cg} Cg, {n_cc} Cc)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
