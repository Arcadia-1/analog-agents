#!/usr/bin/env python3
"""
Post-simulation spec checker.
Usage: python3 post_sim_check.py <psf_dir> <spec_yml> <sim_log_yml>
Called by hooks/post-sim.sh after every Spectre run.
"""
import sys
import os
import yaml
import json
from datetime import datetime, timezone
from pathlib import Path


def load_spec(spec_path: str) -> dict:
    with open(spec_path) as f:
        return yaml.safe_load(f)


def parse_psf_results(psf_dir: str) -> dict:
    """
    Parse PSF output directory using virtuoso-bridge parsers.
    Returns dict of {signal_name: value} for scalar results.
    Falls back to empty dict if parsers unavailable.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "virtuoso-bridge-lite"))
        from virtuoso_bridge.spectre.parsers import parse_psf_ascii_directory
        data = parse_psf_ascii_directory(psf_dir)
        # Flatten: take last value for each signal (DC/AC final point)
        return {k: v[-1] if isinstance(v, list) else v for k, v in data.items()}
    except Exception as e:
        print(f"[post-sim] Warning: could not parse PSF with virtuoso-bridge: {e}", file=sys.stderr)
        return {}


def check_spec(results: dict, spec: dict) -> list:
    """
    Check parsed results against spec targets.
    Returns list of dicts: {name, value, unit, target, margin, pass}.
    """
    checks = []
    spec_targets = spec.get("specs", {})

    # Signal name mapping: spec key -> possible PSF signal names
    signal_map = {
        "dc_gain":      ["vout_gain_db", "gain_db", "dc_gain"],
        "ugbw":         ["ugbw", "ugf", "unity_gain_bw"],
        "phase_margin": ["phase_margin", "pm"],
        "noise_input":  ["input_noise", "noise_in", "vn_input"],
        "power":        ["power", "pwr", "total_power"],
        "slew_rate":    ["slew_rate", "sr"],
    }

    for spec_name, target in spec_targets.items():
        candidates = signal_map.get(spec_name, [spec_name])
        value = None
        for candidate in candidates:
            if candidate in results:
                value = results[candidate]
                break

        if value is None:
            checks.append({
                "name": spec_name,
                "value": None,
                "unit": target.get("unit", ""),
                "target": target,
                "margin": None,
                "pass": False,
                "note": "signal not found in PSF output",
            })
            continue

        if "min" in target:
            margin = value - target["min"]
            passed = margin >= 0
        elif "max" in target:
            margin = target["max"] - value
            passed = margin >= 0
        else:
            margin = None
            passed = True

        checks.append({
            "name": spec_name,
            "value": round(value, 4),
            "unit": target.get("unit", ""),
            "target": target,
            "margin": round(margin, 4) if margin is not None else None,
            "pass": passed,
        })

    return checks


def append_sim_log(log_path: str, netlist: str, corner: str, level: str, checks: list):
    """Append one simulation result entry to sim-log.yml."""
    log = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = yaml.safe_load(f) or []

    overall = "PASS" if all(c["pass"] for c in checks) else "FAIL"
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "netlist": netlist,
        "corner": corner,
        "level": level,
        "results": {
            c["name"]: {
                "value": c["value"],
                "unit": c["unit"],
                "margin": f"{c['margin']:+.3f}" if c["margin"] is not None else None,
                "pass": c["pass"],
            }
            for c in checks
        },
        "status": overall,
    }
    log.append(entry)

    with open(log_path, "w") as f:
        yaml.dump(log, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def print_summary(checks: list, netlist: str, corner: str):
    """Print markdown summary for context injection."""
    overall = "PASS" if all(c["pass"] for c in checks) else "FAIL"
    print(f"\n## Simulation Result — {netlist} @ {corner}: **{overall}**\n")
    print(f"| Spec | Value | Target | Margin | Status |")
    print(f"|------|-------|--------|--------|--------|")
    for c in checks:
        val = f"{c['value']} {c['unit']}" if c['value'] is not None else "N/A"
        tgt = f"{'≥' if 'min' in c['target'] else '≤'}{c['target'].get('min', c['target'].get('max', '?'))} {c['unit']}"
        margin = f"{c['margin']:+.3f}" if c['margin'] is not None else "N/A"
        status = "✓" if c['pass'] else "✗"
        print(f"| {c['name']} | {val} | {tgt} | {margin} | {status} |")
    print()


def main():
    if len(sys.argv) < 4:
        print("Usage: post_sim_check.py <psf_dir> <spec_yml> <sim_log_yml>", file=sys.stderr)
        sys.exit(1)

    psf_dir   = sys.argv[1]
    spec_path = sys.argv[2]
    log_path  = sys.argv[3]

    netlist = os.environ.get("ANALOG_NETLIST", os.path.basename(psf_dir))
    corner  = os.environ.get("ANALOG_CORNER", "tt_27c")
    level   = os.environ.get("ANALOG_LEVEL", "L1")

    if not os.path.exists(spec_path):
        print(f"[post-sim] No spec.yml found at {spec_path}, skipping spec check.", file=sys.stderr)
        sys.exit(0)

    spec    = load_spec(spec_path)
    results = parse_psf_results(psf_dir)
    checks  = check_spec(results, spec)

    append_sim_log(log_path, netlist, corner, level, checks)
    print_summary(checks, netlist, corner)


if __name__ == "__main__":
    main()
