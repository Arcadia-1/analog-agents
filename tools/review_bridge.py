#!/usr/bin/env python3
"""
Cross-model review bridge for analog-agents.

Usage:
  python3 review_bridge.py check [--config CONFIG]
  python3 review_bridge.py review --netlist PATH --rationale PATH --spec PATH [--config CONFIG] [--effort LEVEL]

Reads config/reviewers.yml, sends review prompts to configured models,
collates results into a divergence-focused report.
"""
import argparse
import json
import os
import sys
import time
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from string import Template


REVIEW_PROMPT = """You are an analog IC design review expert. Review the following circuit netlist and design rationale.

## Circuit Netlist
${netlist_content}

## Design Rationale
${rationale_content}

## Target Specifications
${spec_content}

${anti_patterns_section}

Evaluate on these dimensions, giving PASS / WARN / FAIL for each:

1. **Connection correctness**: dangling nodes, pin mismatches, bulk errors
2. **Bias soundness**: mirror ratios, gm/Id range, headroom margins
3. **Sizing consistency**: do rationale equations match actual parameters?
4. **Topology risks**: known traps (CMFB polarity, compensation, etc.)
5. **Spec achievability**: can these specs be met with the given sizing?

For each WARN/FAIL: describe the problem, its impact, and a suggested fix.

Respond in this exact format for each dimension:
DIMENSION: <name>
VERDICT: PASS|WARN|FAIL
REASONING: <your analysis>
"""

DIMENSIONS = [
    "Connection correctness",
    "Bias soundness",
    "Sizing consistency",
    "Topology risks",
    "Spec achievability",
]


def load_config(config_path: str) -> dict:
    """Load reviewers.yml with environment variable substitution."""
    with open(config_path) as f:
        raw = f.read()
    # Substitute ${ENV_VAR} patterns
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    return yaml.safe_load(raw)


def call_reviewer(name: str, cfg: dict, prompt: str) -> dict:
    """Call a single reviewer via OpenAI-compatible API. Returns dict with name, status, response, latency."""
    try:
        import httpx
    except ImportError:
        # Fallback to urllib if httpx not available
        return _call_reviewer_urllib(name, cfg, prompt)

    url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    start = time.time()
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=cfg.get("timeout", 120))
        latency = time.time() - start
        if resp.status_code != 200:
            return {"name": name, "status": "FAIL", "error": f"{resp.status_code} {resp.text[:200]}", "latency": latency}
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"name": name, "status": "ok", "response": content, "latency": round(latency, 1)}
    except Exception as e:
        return {"name": name, "status": "FAIL", "error": str(e), "latency": round(time.time() - start, 1)}


def _call_reviewer_urllib(name: str, cfg: dict, prompt: str) -> dict:
    """Fallback reviewer call using urllib (no external deps)."""
    import urllib.request
    import urllib.error

    url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 120)) as resp:
            latency = time.time() - start
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            return {"name": name, "status": "ok", "response": content, "latency": round(latency, 1)}
    except Exception as e:
        return {"name": name, "status": "FAIL", "error": str(e), "latency": round(time.time() - start, 1)}


def check_connectivity(config: dict) -> list:
    """Send lightweight probe to each reviewer. Returns list of status dicts."""
    results = []
    probe_prompt = "Reply with exactly: OK"

    def probe(name, cfg):
        return call_reviewer(name, cfg, probe_prompt)

    with ThreadPoolExecutor(max_workers=len(config["reviewers"])) as pool:
        futures = {pool.submit(probe, name, cfg): name for name, cfg in config["reviewers"].items()}
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(results, key=lambda r: r["name"])


def parse_verdicts(response: str) -> dict:
    """Parse structured verdicts from reviewer response. Returns {dimension: {verdict, reasoning}}."""
    verdicts = {}
    current_dim = None
    current_verdict = None
    current_reasoning = []

    for line in response.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("DIMENSION:"):
            if current_dim and current_verdict:
                verdicts[current_dim] = {"verdict": current_verdict, "reasoning": "\n".join(current_reasoning).strip()}
            current_dim = line_stripped.split(":", 1)[1].strip()
            current_verdict = None
            current_reasoning = []
        elif line_stripped.startswith("VERDICT:"):
            current_verdict = line_stripped.split(":", 1)[1].strip().upper()
            if current_verdict not in ("PASS", "WARN", "FAIL"):
                current_verdict = "WARN"  # default on parse error
        elif line_stripped.startswith("REASONING:"):
            current_reasoning.append(line_stripped.split(":", 1)[1].strip())
        elif current_dim and current_verdict:
            current_reasoning.append(line_stripped)

    if current_dim and current_verdict:
        verdicts[current_dim] = {"verdict": current_verdict, "reasoning": "\n".join(current_reasoning).strip()}

    return verdicts


def select_reviewers(config: dict, effort: str, available: list) -> list:
    """Select which reviewers to use based on effort level."""
    available_names = [r["name"] for r in available if r["status"] == "ok"]
    if effort == "lite" or not available_names:
        return []
    if effort == "standard":
        # Pick lowest latency
        by_latency = sorted([r for r in available if r["status"] == "ok"], key=lambda r: r["latency"])
        return [by_latency[0]["name"]] if by_latency else []
    if effort == "intensive":
        by_latency = sorted([r for r in available if r["status"] == "ok"], key=lambda r: r["latency"])
        return [r["name"] for r in by_latency[:2]]
    # exhaustive: all available
    return available_names


def generate_report(reviewer_results: list, all_verdicts: dict) -> str:
    """Generate markdown report with consensus matrix and divergence analysis."""
    lines = []
    lines.append("## Reviewer Status")
    lines.append("| Reviewer | Status | Latency |")
    lines.append("|----------|--------|---------|")
    for r in reviewer_results:
        status = r["status"]
        latency = f"{r['latency']}s" if "latency" in r else "N/A"
        lines.append(f"| {r['name']} | {status} | {latency} |")

    active = [r["name"] for r in reviewer_results if r["status"] == "ok"]
    if not active:
        lines.append("\nNo reviewers available. Review skipped.")
        return "\n".join(lines)

    lines.append("")
    lines.append("## Consensus Matrix")
    header = "| Check |" + "|".join(f" {n} " for n in active) + "| Consensus |"
    sep = "|-------|" + "|".join("---" for _ in active) + "|-----------|"
    lines.append(header)
    lines.append(sep)

    divergences = []
    for dim in DIMENSIONS:
        verdicts_for_dim = []
        cells = []
        for name in active:
            v = all_verdicts.get(name, {}).get(dim, {}).get("verdict", "N/A")
            verdicts_for_dim.append(v)
            cells.append(f" {v} ")

        # Calculate consensus
        counts = {}
        for v in verdicts_for_dim:
            counts[v] = counts.get(v, 0) + 1
        majority = max(counts, key=counts.get)
        ratio = f"{counts[majority]}/{len(verdicts_for_dim)}"
        if counts[majority] == len(verdicts_for_dim):
            consensus = majority
        else:
            consensus = f"{majority} ({ratio})"
            divergences.append((dim, active, all_verdicts))

        row = f"| {dim} |" + "|".join(cells) + f"| {consensus} |"
        lines.append(row)

    if divergences:
        lines.append("")
        lines.append("## Divergence Analysis")
        lines.append("")
        for dim, names, verdicts in divergences:
            lines.append(f"### {dim}")
            for name in names:
                entry = verdicts.get(name, {}).get(dim, {})
                v = entry.get("verdict", "N/A")
                reasoning = entry.get("reasoning", "No reasoning provided")
                lines.append(f"- **{name} ({v})**: {reasoning}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="analog-agents cross-model review bridge")
    sub = parser.add_subparsers(dest="command")

    check_p = sub.add_parser("check", help="Verify reviewer connectivity")
    check_p.add_argument("--config", default="config/reviewers.yml")

    review_p = sub.add_parser("review", help="Run cross-model review")
    review_p.add_argument("--netlist", required=True)
    review_p.add_argument("--rationale", required=True)
    review_p.add_argument("--spec", required=True)
    review_p.add_argument("--anti-patterns", default="")
    review_p.add_argument("--config", default="config/reviewers.yml")
    review_p.add_argument("--effort", default="standard", choices=["lite", "standard", "intensive", "exhaustive"])
    review_p.add_argument("--output", default="verifier-reports/cross-model-review.md")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)

    if args.command == "check":
        results = check_connectivity(config)
        ok_count = sum(1 for r in results if r["status"] == "ok")
        for r in results:
            status_str = f"ok  {r['latency']}s" if r["status"] == "ok" else f"FAIL  {r.get('error', 'unknown')}"
            print(f"  {r['name']:20s} {status_str}")
        min_req = config.get("voting", {}).get("min_reviewers", 2)
        met = "meets" if ok_count >= min_req else "DOES NOT meet"
        print(f"\n  Available: {ok_count}/{len(results)} — {met} min_reviewers ({min_req})")

    elif args.command == "review":
        if args.effort == "lite":
            print("[effort: lite] Cross-model review skipped.")
            sys.exit(0)

        # Check connectivity first
        available = check_connectivity(config)
        selected = select_reviewers(config, args.effort, available)
        if not selected:
            print("No reviewers available. Review skipped.")
            sys.exit(1)

        # Read input files
        netlist_content = Path(args.netlist).read_text()
        rationale_content = Path(args.rationale).read_text()
        spec_content = Path(args.spec).read_text()
        anti_patterns = Path(args.anti_patterns).read_text() if args.anti_patterns and Path(args.anti_patterns).exists() else ""

        anti_section = ""
        if anti_patterns:
            anti_section = f"## Known Risks for This Topology (from knowledge base)\n{anti_patterns}"

        prompt = Template(REVIEW_PROMPT).safe_substitute(
            netlist_content=netlist_content,
            rationale_content=rationale_content,
            spec_content=spec_content,
            anti_patterns_section=anti_section,
        )

        # Send to selected reviewers concurrently
        print(f"[effort: {args.effort}] Sending to {len(selected)} reviewer(s): {', '.join(selected)}")
        reviewer_results = []
        all_verdicts = {}

        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {}
            for name in selected:
                cfg = config["reviewers"][name]
                futures[pool.submit(call_reviewer, name, cfg, prompt)] = name
            for future in as_completed(futures):
                result = future.result()
                reviewer_results.append(result)
                if result["status"] == "ok":
                    all_verdicts[result["name"]] = parse_verdicts(result["response"])
                    print(f"  {result['name']}: done ({result['latency']}s)")
                else:
                    print(f"  {result['name']}: FAIL ({result.get('error', 'unknown')})")

        # Generate report
        report = generate_report(reviewer_results, all_verdicts)
        header = f"# Cross-Model Review — {Path(args.netlist).stem} — {time.strftime('%Y-%m-%d')}\n\n"
        full_report = header + report

        # Write output
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_report)
        print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
