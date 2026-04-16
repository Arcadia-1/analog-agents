#!/usr/bin/env python3
"""
Post-layout netlist filter for analog-agents.

Extracts the essential circuit skeleton from a massive post-layout netlist:
- Active devices (MOSFETs, BJTs, diodes) with their parasitic-annotated parameters
- Critical parasitic paths (large caps on high-Z nodes, long RC chains)
- Inter-block coupling capacitances
- Strips trivial parasitics below threshold

Usage:
  python3 postlayout_filter.py extract <netlist> [--threshold 1f] [--output filtered.scs]
  python3 postlayout_filter.py compare <pre_layout.scs> <post_layout.scs> [--output diff.md]
  python3 postlayout_filter.py stats <netlist>
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


def parse_value(s):
    """Parse SPICE value string to float. E.g., '1.5p' -> 1.5e-12."""
    s = s.strip().lower()
    multipliers = {
        'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, '\u00b5': 1e-6,
        'm': 1e-3, 'k': 1e3, 'meg': 1e6, 'g': 1e9, 't': 1e12,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if s.endswith(suffix):
            try:
                return float(s[:-len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def count_stats(lines):
    """Count device types in a netlist."""
    stats = defaultdict(int)
    total_lines = len(lines)
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('*'):
            continue
        # Detect device types by instance name prefix or model
        first_token = stripped.split()[0] if stripped.split() else ''
        if first_token.startswith(('M', 'm')):
            stats['mosfet'] += 1
        elif first_token.startswith(('R', 'r')):
            stats['resistor'] += 1
        elif first_token.startswith(('C', 'c')):
            stats['capacitor'] += 1
        elif first_token.startswith(('Q', 'q')):
            stats['bjt'] += 1
        elif first_token.startswith(('D', 'd')):
            stats['diode'] += 1
        elif first_token.startswith(('I', 'i')) and not stripped.startswith('include'):
            stats['isource'] += 1
        elif first_token.startswith(('V', 'v')):
            stats['vsource'] += 1
        elif stripped.startswith('subckt') or stripped.startswith('.subckt'):
            stats['subcircuit_def'] += 1
        elif stripped.startswith('ends') or stripped.startswith('.ends'):
            pass
        elif stripped.startswith('include') or stripped.startswith('.include'):
            stats['include'] += 1
    stats['total_lines'] = total_lines
    return dict(stats)


def extract_active_devices(lines):
    """Extract all active device (MOSFET/BJT/diode) lines."""
    active = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped.split()[0] if stripped.split() else ''
        if first and first[0].upper() in ('M', 'Q', 'D'):
            active.append(line)
    return active


def extract_significant_parasitics(lines, cap_threshold=1e-15, res_threshold=1e6):
    """Extract parasitic R/C above threshold. Default: C >= 1fF, R <= 1M (low-R paths matter)."""
    significant = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped.split()[0] if stripped.split() else ''

        if first and first[0].upper() == 'C':
            # Parse capacitor value -- typically last positional or c= parameter
            match = re.search(r'[cC]=?([\d.]+[a-zA-Z\u00b5]*)', stripped)
            if match:
                val = parse_value(match.group(1))
                if val >= cap_threshold:
                    significant.append(('cap', val, line.rstrip()))

        elif first and first[0].upper() == 'R':
            match = re.search(r'[rR]=?([\d.]+[a-zA-Z\u00b5]*)', stripped)
            if match:
                val = parse_value(match.group(1))
                # Low resistance paths are interesting (shorts, IR drop)
                # Very high resistance is usually isolation (less interesting)
                if val <= res_threshold:
                    significant.append(('res', val, line.rstrip()))

    return significant


def find_node_parasitics(parasitics, node_name):
    """Find all parasitics connected to a specific node."""
    connected = []
    for ptype, val, line in parasitics:
        if node_name in line:
            connected.append((ptype, val, line))
    return connected


def extract_subcircuit_ports(lines):
    """Extract subcircuit definitions and their ports."""
    subcircuits = {}
    for line in lines:
        stripped = line.strip()
        match = re.match(r'(?:\.)?subckt\s+(\S+)\s+(.*)', stripped, re.IGNORECASE)
        if match:
            name = match.group(1)
            ports = match.group(2).split()
            subcircuits[name] = ports
    return subcircuits


def extract_skeleton(lines, cap_threshold, res_threshold):
    """Build the filtered skeleton: headers + active devices + significant parasitics."""
    skeleton_lines = []

    # Keep headers (comments, includes, parameters, subcircuit defs/ends)
    for line in lines:
        stripped = line.strip()
        if (stripped.startswith('//') or stripped.startswith('*') or
            stripped.startswith('include') or stripped.startswith('.include') or
            stripped.startswith('simulator') or
            stripped.startswith('parameters') or stripped.startswith('.param') or
            stripped.startswith('subckt') or stripped.startswith('.subckt') or
            stripped.startswith('ends') or stripped.startswith('.ends') or
            stripped.startswith('global') or stripped.startswith('.global')):
            skeleton_lines.append(line.rstrip())

    skeleton_lines.append('')
    skeleton_lines.append('// === Active Devices ===')
    for line in extract_active_devices(lines):
        skeleton_lines.append(line.rstrip())

    parasitics = extract_significant_parasitics(lines, cap_threshold, res_threshold)

    if parasitics:
        skeleton_lines.append('')
        skeleton_lines.append(f'// === Significant Parasitics (C >= {cap_threshold:.0e}F, R <= {res_threshold:.0e}ohm) ===')
        skeleton_lines.append(f'// Total significant: {len(parasitics)} out of many thousands')

        # Sort by value (largest caps first, smallest R first)
        caps = sorted([p for p in parasitics if p[0] == 'cap'], key=lambda x: -x[1])
        ress = sorted([p for p in parasitics if p[0] == 'res'], key=lambda x: x[1])

        if caps:
            skeleton_lines.append(f'// --- Capacitors ({len(caps)} significant) ---')
            for _, val, line in caps[:100]:  # Top 100
                skeleton_lines.append(line)
            if len(caps) > 100:
                skeleton_lines.append(f'// ... and {len(caps) - 100} more')

        if ress:
            skeleton_lines.append(f'// --- Resistors ({len(ress)} significant) ---')
            for _, val, line in ress[:100]:
                skeleton_lines.append(line)
            if len(ress) > 100:
                skeleton_lines.append(f'// ... and {len(ress) - 100} more')

    return skeleton_lines


def compare_pre_post(pre_lines, post_lines, cap_threshold):
    """Compare pre-layout and post-layout netlists. Returns markdown report."""
    pre_stats = count_stats(pre_lines)
    post_stats = count_stats(post_lines)

    pre_active = extract_active_devices(pre_lines)
    post_active = extract_active_devices(post_lines)

    post_parasitics = extract_significant_parasitics(post_lines, cap_threshold)
    post_caps = [p for p in post_parasitics if p[0] == 'cap']
    post_res = [p for p in post_parasitics if p[0] == 'res']

    total_parasitic_cap = sum(v for _, v, _ in post_caps)

    report = []
    report.append('# Pre-Layout vs Post-Layout Comparison\n')

    report.append('## Device Count\n')
    report.append('| Type | Pre-Layout | Post-Layout | Delta |')
    report.append('|------|-----------|-------------|-------|')
    for dtype in ['mosfet', 'bjt', 'resistor', 'capacitor', 'total_lines']:
        pre_count = pre_stats.get(dtype, 0)
        post_count = post_stats.get(dtype, 0)
        delta = post_count - pre_count
        label = dtype.replace('_', ' ').title()
        report.append(f'| {label} | {pre_count} | {post_count} | +{delta} |')

    report.append(f'\n## Parasitic Summary\n')
    report.append(f'- Significant capacitors (>= {cap_threshold:.0e}F): **{len(post_caps)}**')
    report.append(f'- Total parasitic capacitance: **{total_parasitic_cap*1e12:.1f} pF**')
    report.append(f'- Significant resistors: **{len(post_res)}**')

    report.append(f'\n## Top 20 Parasitic Capacitors\n')
    report.append('| Rank | Nodes | Value | Notes |')
    report.append('|------|-------|-------|-------|')
    for i, (_, val, line) in enumerate(sorted(post_caps, key=lambda x: -x[1])[:20], 1):
        tokens = line.strip().split()
        nodes = ' -- '.join(tokens[1:3]) if len(tokens) >= 3 else '?'
        report.append(f'| {i} | {nodes} | {val*1e15:.1f} fF | |')

    report.append(f'\n## Active Device Comparison\n')
    report.append(f'- Pre-layout active devices: {len(pre_active)}')
    report.append(f'- Post-layout active devices: {len(post_active)}')
    if len(post_active) != len(pre_active):
        report.append(f'- **WARNING**: device count mismatch -- layout may have added/removed devices')

    report.append('\n## Impact Assessment\n')
    report.append('Estimate parasitic impact on key specs:\n')
    report.append(f'- **Bandwidth**: total parasitic cap {total_parasitic_cap*1e12:.1f}pF added to load --')
    report.append(f'  if original CL was small, this could significantly reduce UGBW')
    report.append(f'- **Gain**: parasitic R at high-impedance nodes reduces output resistance')
    report.append(f'- **Settling**: additional RC time constants slow step response')
    report.append(f'- **Noise**: parasitic R adds thermal noise at signal nodes')
    report.append(f'\nRecommend: re-simulate with extracted netlist to quantify actual impact.')

    return '\n'.join(report)


def cmd_stats(args):
    """Print netlist statistics."""
    content = Path(args.netlist).read_text()
    lines = content.split('\n')
    stats = count_stats(lines)

    print(f'Netlist: {args.netlist}')
    print(f'Total lines: {stats.get("total_lines", 0):,}')
    print(f'---')
    for dtype in ['mosfet', 'bjt', 'diode', 'resistor', 'capacitor', 'isource', 'vsource', 'subcircuit_def', 'include']:
        count = stats.get(dtype, 0)
        if count > 0:
            print(f'  {dtype:20s} {count:>10,}')

    parasitic_c = sum(1 for l in lines if l.strip() and l.strip()[0].upper() == 'C')
    parasitic_r = sum(1 for l in lines if l.strip() and l.strip()[0].upper() == 'R')
    print(f'---')
    print(f'  parasitic C (all)    {parasitic_c:>10,}')
    print(f'  parasitic R (all)    {parasitic_r:>10,}')

    if stats.get('total_lines', 0) > 50000:
        print(f'\nThis is a post-layout netlist. Use "extract" to filter before auditing.')


def cmd_extract(args):
    """Extract circuit skeleton from post-layout netlist."""
    content = Path(args.netlist).read_text()
    lines = content.split('\n')

    cap_thresh = parse_value(args.threshold) if args.threshold else 1e-15
    res_thresh = parse_value(args.res_threshold) if args.res_threshold else 1e6

    stats = count_stats(lines)
    print(f'Input: {stats.get("total_lines", 0):,} lines', file=sys.stderr)

    skeleton = extract_skeleton(lines, cap_thresh, res_thresh)

    print(f'Output: {len(skeleton):,} lines ({len(skeleton)*100//max(stats.get("total_lines",1),1)}% of original)', file=sys.stderr)

    output_path = args.output or args.netlist.replace('.scs', '_filtered.scs')
    Path(output_path).write_text('\n'.join(skeleton) + '\n')
    print(f'Written to: {output_path}', file=sys.stderr)


def cmd_compare(args):
    """Compare pre-layout and post-layout netlists."""
    pre_content = Path(args.pre_layout).read_text()
    post_content = Path(args.post_layout).read_text()

    cap_thresh = parse_value(args.threshold) if args.threshold else 1e-15

    report = compare_pre_post(
        pre_content.split('\n'),
        post_content.split('\n'),
        cap_thresh,
    )

    output_path = args.output or 'verifier-reports/pre-vs-post-layout.md'
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report + '\n')
    print(f'Report written to: {output_path}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Post-layout netlist filter for analog-agents')
    sub = parser.add_subparsers(dest='command')

    stats_p = sub.add_parser('stats', help='Print netlist statistics')
    stats_p.add_argument('netlist')

    extract_p = sub.add_parser('extract', help='Extract circuit skeleton')
    extract_p.add_argument('netlist')
    extract_p.add_argument('--threshold', default='1f', help='Min capacitor value to keep (default: 1fF)')
    extract_p.add_argument('--res-threshold', default='1meg', help='Max resistor value to keep (default: 1Mohm)')
    extract_p.add_argument('--output', help='Output file path')

    compare_p = sub.add_parser('compare', help='Compare pre vs post layout')
    compare_p.add_argument('pre_layout')
    compare_p.add_argument('post_layout')
    compare_p.add_argument('--threshold', default='1f', help='Min cap for significance')
    compare_p.add_argument('--output', help='Output report path')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'stats':
        cmd_stats(args)
    elif args.command == 'extract':
        cmd_extract(args)
    elif args.command == 'compare':
        cmd_compare(args)


if __name__ == '__main__':
    main()
