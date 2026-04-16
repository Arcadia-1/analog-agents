#!/usr/bin/env python3
"""
Self-evolution engine for analog-agents.

Analyzes completed design sessions and proposes improvements to:
1. Wiki entries (lessons, anti-patterns, strategies)
2. Checklist additions
3. Prompt refinements
4. User preference extraction

Usage:
  python3 evolve_engine.py review [--project-dir DIR] [--wiki-dir DIR]
  python3 evolve_engine.py wiki [--project-dir DIR] [--wiki-dir DIR]
  python3 evolve_engine.py checklist [--project-dir DIR] [--checklists-dir DIR]
  python3 evolve_engine.py preferences [--project-dir DIR] [--wiki-dir DIR]
  python3 evolve_engine.py status [--wiki-dir DIR]
"""
import argparse
import json
import os
import re
import sys
import yaml
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict


# ============================================================
# Data Loading
# ============================================================

def load_yaml(path):
    """Load a YAML file, return empty dict if not found."""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def load_text(path):
    """Load a text file, return empty string if not found."""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text()


def find_files(directory, pattern):
    """Find files matching a glob pattern in a directory."""
    d = Path(directory)
    if not d.exists():
        return []
    return sorted(d.glob(pattern))


def load_iteration_log(project_dir):
    """Load iteration-log.yml from project directory."""
    return load_yaml(Path(project_dir) / "iteration-log.yml")


def load_verifier_reports(project_dir):
    """Load all verifier reports as list of (path, content) tuples."""
    reports = []
    report_dir = Path(project_dir) / "verifier-reports"
    if not report_dir.exists():
        return reports
    for md_file in sorted(report_dir.rglob("*.md")):
        reports.append((str(md_file.relative_to(project_dir)), md_file.read_text()))
    return reports


def load_rationale(project_dir):
    """Load rationale.md from circuit/ directory."""
    candidates = [
        Path(project_dir) / "circuit" / "rationale.md",
        Path(project_dir) / "rationale.md",
    ]
    for c in candidates:
        if c.exists():
            return c.read_text()
    # Try blocks/*/circuit/rationale.md
    for f in Path(project_dir).glob("blocks/*/circuit/rationale.md"):
        return f.read_text()
    return ""


def load_cross_model_reviews(project_dir):
    """Load cross-model review reports."""
    reports = []
    report_dir = Path(project_dir) / "verifier-reports"
    if not report_dir.exists():
        return reports
    for f in report_dir.glob("cross-model-review*.md"):
        reports.append(f.read_text())
    return reports


# ============================================================
# Wiki Enrichment
# ============================================================

def extract_parameter_changes(iteration_log):
    """Extract significant parameter changes from iteration log."""
    changes = []
    blocks = iteration_log.get("blocks", {})
    for block_name, block_data in blocks.items():
        iterations = block_data.get("iterations", [])
        for it in iterations:
            for change in it.get("designer_changes", []):
                changes.append({
                    "block": block_name,
                    "iteration": it.get("iteration", "?"),
                    "param": change.get("param", "?"),
                    "from": change.get("from"),
                    "to": change.get("to"),
                    "reason": change.get("reason", ""),
                    "outcome": it.get("outcome", "unknown"),
                })
    return changes


def extract_corner_surprises(iteration_log):
    """Find specs that passed at one corner but failed at another."""
    surprises = []
    blocks = iteration_log.get("blocks", {})
    for block_name, block_data in blocks.items():
        spec_history = defaultdict(list)
        for it in block_data.get("iterations", []):
            for result in it.get("results", []):
                spec_history[result.get("spec", "")].append({
                    "iteration": it.get("iteration"),
                    "corner": result.get("corner", "tt_27c"),
                    "measured": result.get("measured"),
                    "target": result.get("target"),
                    "margin": result.get("margin"),
                    "status": result.get("status"),
                })
        for spec_name, entries in spec_history.items():
            passed = [e for e in entries if e["status"] == "pass"]
            failed = [e for e in entries if e["status"] == "fail"]
            if passed and failed:
                surprises.append({
                    "block": block_name,
                    "spec": spec_name,
                    "passed_corners": list(set(e.get("corner", "?") for e in passed)),
                    "failed_corners": list(set(e.get("corner", "?") for e in failed)),
                    "worst_margin": min(
                        (e.get("margin", "0") for e in entries),
                        key=lambda x: float(str(x).replace("+", "")) if x else 0
                    ),
                })
    return surprises


def extract_failure_patterns(iteration_log):
    """Find specs that failed multiple times (indicates a hard problem)."""
    patterns = []
    blocks = iteration_log.get("blocks", {})
    for block_name, block_data in blocks.items():
        spec_fails = defaultdict(int)
        spec_details = defaultdict(list)
        for it in block_data.get("iterations", []):
            for result in it.get("results", []):
                if result.get("status") == "fail":
                    spec_fails[result.get("spec", "")] += 1
                    spec_details[result.get("spec", "")].append({
                        "iteration": it.get("iteration"),
                        "measured": result.get("measured"),
                        "target": result.get("target"),
                        "margin": result.get("margin"),
                    })
        for spec_name, count in spec_fails.items():
            if count >= 2:
                patterns.append({
                    "block": block_name,
                    "spec": spec_name,
                    "fail_count": count,
                    "trajectory": spec_details[spec_name],
                })
    return patterns


def extract_optimizer_usage(iteration_log):
    """Find where optimizer was used (indicates manual sizing was insufficient)."""
    usages = []
    blocks = iteration_log.get("blocks", {})
    for block_name, block_data in blocks.items():
        for it in block_data.get("iterations", []):
            if it.get("optimizer_used"):
                usages.append({
                    "block": block_name,
                    "iteration": it.get("iteration"),
                    "config": it.get("optimizer_config", {}),
                    "outcome": it.get("outcome"),
                })
    return usages


def propose_wiki_entries(project_dir, wiki_dir):
    """Analyze session and propose wiki entries."""
    log = load_iteration_log(project_dir)
    if not log:
        print("No iteration-log.yml found. Nothing to analyze.")
        return []

    proposals = []

    # 1. Parameter changes that fixed failing specs -> strategy candidates
    changes = extract_parameter_changes(log)
    fixing_changes = [c for c in changes if c["outcome"] == "pass" and c["from"] is not None]
    for change in fixing_changes:
        if change["reason"]:
            proposals.append({
                "type": "strategy",
                "name": f"Sizing fix: {change['param']} adjustment for {change['block']}",
                "tags": [change["block"], change["param"], "sizing"],
                "evidence": (
                    f"Iteration {change['iteration']}: changed {change['param']} "
                    f"from {change['from']} to {change['to']}. "
                    f"Reason: {change['reason']}"
                ),
                "confidence": "unverified",
                "source": "iteration-log parameter change",
            })

    # 2. Corner surprises -> corner-lesson candidates
    surprises = extract_corner_surprises(log)
    for surprise in surprises:
        proposals.append({
            "type": "corner-lesson",
            "name": f"{surprise['spec']} corner surprise in {surprise['block']}",
            "tags": [surprise["block"], surprise["spec"]] + surprise["failed_corners"],
            "evidence": (
                f"Passed at {surprise['passed_corners']}, "
                f"failed at {surprise['failed_corners']}. "
                f"Worst margin: {surprise['worst_margin']}"
            ),
            "confidence": "unverified",
            "source": "iteration-log corner analysis",
        })

    # 3. Repeated failures -> anti-pattern candidates
    patterns = extract_failure_patterns(log)
    for pattern in patterns:
        if pattern["fail_count"] >= 2:
            trajectory_str = "; ".join(
                f"iter {t['iteration']}: {t['measured']} vs {t['target']} "
                f"(margin {t['margin']})"
                for t in pattern["trajectory"]
            )
            proposals.append({
                "type": "anti-pattern",
                "name": f"Persistent {pattern['spec']} failure in {pattern['block']}",
                "tags": [pattern["block"], pattern["spec"], "failure-pattern"],
                "evidence": (
                    f"Failed {pattern['fail_count']} times. "
                    f"Trajectory: {trajectory_str}"
                ),
                "confidence": "unverified",
                "source": "iteration-log failure analysis",
            })

    # 4. Optimizer usage -> strategy about when hand-calc isn't enough
    usages = extract_optimizer_usage(log)
    for usage in usages:
        proposals.append({
            "type": "strategy",
            "name": f"Optimizer needed for {usage['block']}",
            "tags": [usage["block"], "optimizer", "multi-parameter"],
            "evidence": (
                f"Iteration {usage['iteration']}: optimizer invoked. "
                f"Config: {usage['config']}. Outcome: {usage['outcome']}"
            ),
            "confidence": "unverified",
            "source": "iteration-log optimizer usage",
        })

    # 5. Lessons learned (from summary section)
    lessons = log.get("summary", {}).get("lessons_learned", [])
    for lesson in lessons:
        proposals.append({
            "type": "corner-lesson",
            "name": lesson[:80],
            "tags": extract_tags_from_text(lesson),
            "evidence": lesson,
            "confidence": "unverified",
            "source": "iteration-log lessons_learned",
        })

    # Deduplicate by checking existing wiki
    proposals = deduplicate_proposals(proposals, wiki_dir)

    return proposals


def extract_tags_from_text(text):
    """Extract likely tags from a text string."""
    keywords = [
        "offset", "gain", "bandwidth", "noise", "power", "settling", "slew",
        "phase_margin", "cmfb", "cascode", "mirror", "comparator", "ota",
        "adc", "pll", "ldo", "bandgap", "ss", "ff", "tt", "corner",
        "mismatch", "headroom", "saturation", "triode",
    ]
    text_lower = text.lower()
    return [k for k in keywords if k in text_lower]


def deduplicate_proposals(proposals, wiki_dir):
    """Remove proposals that overlap with existing wiki entries."""
    index_path = Path(wiki_dir) / "index.yml"
    if not index_path.exists():
        return proposals

    index = load_yaml(index_path)
    existing_summaries = [
        v.get("summary", "").lower()
        for v in index.get("entries", {}).values()
    ]

    filtered = []
    for p in proposals:
        name_lower = p["name"].lower()
        # Simple overlap check: if >50% of words match an existing entry, skip
        dominated = False
        for existing in existing_summaries:
            name_words = set(name_lower.split())
            existing_words = set(existing.split())
            if name_words and len(name_words & existing_words) / len(name_words) > 0.5:
                dominated = True
                break
        if not dominated:
            filtered.append(p)

    return filtered


# ============================================================
# Checklist Evolution
# ============================================================

def load_all_checklists(checklists_dir):
    """Load all checklist entries into a flat list."""
    entries = []
    for yml_file in Path(checklists_dir).glob("*.yml"):
        data = load_yaml(yml_file)
        for check_name, check_data in data.items():
            if isinstance(check_data, dict) and "description" in check_data:
                entries.append({
                    "file": yml_file.name,
                    "name": check_name,
                    **check_data,
                })
    return entries


def extract_verifier_rejections(project_dir):
    """Extract pre-sim rejection reasons from verifier reports."""
    rejections = []
    reports = load_verifier_reports(project_dir)
    for path, content in reports:
        if "REJECTED" in content or "NOT READY" in content:
            # Extract issues
            issues = re.findall(
                r'###\s*\[([^\]]+)\]\s*(.*?)\n-\s*\*\*What\*\*:\s*(.*?)(?:\n|$)',
                content,
                re.MULTILINE,
            )
            for responsible, issue_title, what in issues:
                rejections.append({
                    "report": path,
                    "responsible": responsible.strip(),
                    "title": issue_title.strip(),
                    "what": what.strip(),
                })

        # Also extract FAIL results
        fail_matches = re.findall(
            r'\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*[xFAIL]+\s*\|',
            content,
        )
        for match in fail_matches:
            rejections.append({
                "report": path,
                "responsible": "verifier",
                "title": f"Spec fail: {match[0]}",
                "what": f"measured={match[1]}, target={match[2]}, margin={match[3]}",
            })

    return rejections


def match_rejection_to_checklist(rejection, checklist_entries):
    """Check if a rejection is covered by an existing checklist entry."""
    what_lower = rejection["what"].lower()
    title_lower = rejection["title"].lower()

    for entry in checklist_entries:
        desc_lower = entry.get("description", "").lower()
        how_lower = entry.get("how", "").lower()
        # Simple keyword overlap
        combined = desc_lower + " " + how_lower
        match_words = set(what_lower.split()) | set(title_lower.split())
        check_words = set(combined.split())
        overlap = len(match_words & check_words)
        if overlap >= 3:
            return entry["name"]
    return None


def propose_checklist_entries(project_dir, checklists_dir):
    """Propose new checklist entries from unmatched verifier rejections."""
    rejections = extract_verifier_rejections(project_dir)
    existing = load_all_checklists(checklists_dir)

    proposals = []
    for rejection in rejections:
        match = match_rejection_to_checklist(rejection, existing)
        if match is None:
            # Determine target file from rejection context
            target_file = guess_checklist_file(rejection)
            proposals.append({
                "target_file": target_file,
                "issue": rejection["what"],
                "source_report": rejection["report"],
                "suggested_name": slugify(rejection["title"]),
                "suggested_description": rejection["what"],
                "suggested_severity": "warn",
                "suggested_effort": "standard",
                "suggested_method": "semantic",
            })

    return proposals


def guess_checklist_file(rejection):
    """Guess which checklist file a new entry belongs in."""
    text = (rejection.get("what", "") + " " + rejection.get("title", "")).lower()
    if any(k in text for k in ["cmfb", "common-mode", "differential"]):
        return "differential.yml"
    if any(k in text for k in ["cascode", "folded"]):
        return "folded-cascode.yml"
    if any(k in text for k in ["comparator", "latch", "strongarm"]):
        return "comparator.yml"
    if any(k in text for k in ["mirror", "bias", "current"]):
        return "current-mirror.yml"
    if any(k in text for k in ["gain", "amplifier", "ota", "opamp"]):
        return "amplifier.yml"
    return "common.yml"


def slugify(text):
    """Convert text to a checklist entry name."""
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9\s_]', '', s)
    s = re.sub(r'\s+', '_', s)
    return s[:60]


# ============================================================
# User Preferences
# ============================================================

def load_preferences(wiki_dir):
    """Load existing user preferences."""
    pref_path = Path(wiki_dir) / "user-preferences.yml"
    if not pref_path.exists():
        return []
    data = load_yaml(pref_path)
    return data.get("preferences", [])


def save_preferences(wiki_dir, preferences):
    """Save user preferences."""
    pref_path = Path(wiki_dir) / "user-preferences.yml"
    pref_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pref_path, "w") as f:
        yaml.dump(
            {"preferences": preferences},
            f, default_flow_style=False, sort_keys=False, allow_unicode=True,
        )


def extract_preferences(project_dir, wiki_dir):
    """Extract user preference candidates from the design session."""
    log = load_iteration_log(project_dir)
    proposals = []

    # Architecture preference (from iteration-log)
    arch = log.get("architecture")
    if arch:
        proposals.append({
            "category": "topology",
            "rule": f"Used {arch} architecture",
            "discovered": str(date.today()),
            "confirmed": False,
        })

    # Process-specific patterns from rationale
    rationale = load_rationale(project_dir)
    if rationale:
        # Look for device flavor mentions
        flavors = re.findall(r'(ulvt|lvt|svt|hvt)', rationale.lower())
        if flavors:
            flavor_set = sorted(set(flavors))
            proposals.append({
                "category": "process",
                "rule": f"Device flavors used: {', '.join(flavor_set)}",
                "discovered": str(date.today()),
                "confirmed": False,
            })

        # Look for gm/Id targets
        gmid_matches = re.findall(r'gm/[Ii]d\s*[=~]\s*([\d.]+)', rationale)
        if gmid_matches:
            proposals.append({
                "category": "sizing",
                "rule": f"gm/Id targets used: {', '.join(set(gmid_matches))}",
                "discovered": str(date.today()),
                "confirmed": False,
            })

    # Deduplicate against existing
    existing = load_preferences(wiki_dir)
    existing_rules = {p.get("rule", "").lower() for p in existing}
    proposals = [p for p in proposals if p["rule"].lower() not in existing_rules]

    return proposals


# ============================================================
# Reporting
# ============================================================

def format_wiki_proposals(proposals):
    """Format wiki proposals as markdown."""
    if not proposals:
        return "No new wiki entries proposed.\n"

    lines = ["## Proposed Wiki Entries\n"]
    for i, p in enumerate(proposals, 1):
        lines.append(f"### {i}. [{p['type']}] {p['name']}")
        lines.append(f"- **Tags**: {', '.join(p.get('tags', []))}")
        lines.append(f"- **Evidence**: {p['evidence']}")
        lines.append(f"- **Confidence**: {p['confidence']}")
        lines.append(f"- **Source**: {p['source']}")
        lines.append("")
    return "\n".join(lines)


def format_checklist_proposals(proposals):
    """Format checklist proposals as markdown."""
    if not proposals:
        return "No new checklist entries proposed.\n"

    lines = ["## Proposed Checklist Additions\n"]
    for i, p in enumerate(proposals, 1):
        lines.append(f"### {i}. {p['suggested_name']}")
        lines.append(f"- **Target file**: `checklists/{p['target_file']}`")
        lines.append(f"- **Description**: {p['suggested_description']}")
        lines.append(f"- **Severity**: {p['suggested_severity']}")
        lines.append(f"- **Effort**: {p['suggested_effort']}")
        lines.append(f"- **Method**: {p['suggested_method']}")
        lines.append(f"- **Source report**: {p['source_report']}")
        lines.append("")
        lines.append("```yaml")
        lines.append(f"{p['suggested_name']}:")
        lines.append(f"  description: \"{p['suggested_description']}\"")
        lines.append(f"  method: {p['suggested_method']}")
        lines.append(f"  severity: {p['suggested_severity']}")
        lines.append(f"  effort: {p['suggested_effort']}")
        lines.append(f"  auto_checkable: false")
        lines.append(f"  references: []")
        lines.append(f"  how: >")
        lines.append(f"    TODO: describe the checking procedure")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def format_preference_proposals(proposals):
    """Format preference proposals as markdown."""
    if not proposals:
        return "No new preferences discovered.\n"

    lines = ["## Discovered Preferences\n"]
    for i, p in enumerate(proposals, 1):
        lines.append(f"{i}. **[{p['category']}]** {p['rule']}")
    lines.append("")
    lines.append("Confirm these preferences? They will be saved to `wiki/user-preferences.yml`")
    lines.append("and used by future design sessions.")
    return "\n".join(lines)


def format_evolution_status(wiki_dir):
    """Show evolution history."""
    index = load_yaml(Path(wiki_dir) / "index.yml")
    entries = index.get("entries", {})

    lines = ["## Evolution Status\n"]

    # Count by type and confidence
    type_counts = defaultdict(lambda: defaultdict(int))
    for eid, meta in entries.items():
        etype = meta.get("type", "unknown")
        # Load full entry for confidence
        entry = load_yaml(Path(wiki_dir) / meta.get("path", ""))
        confidence = entry.get("confidence", "unknown")
        type_counts[etype][confidence] += 1

    lines.append("### Wiki Entries by Type and Confidence\n")
    lines.append("| Type | Unverified | Verified | Deprecated | Total |")
    lines.append("|------|-----------|---------|-----------|-------|")
    for etype in sorted(type_counts.keys()):
        counts = type_counts[etype]
        total = sum(counts.values())
        lines.append(
            f"| {etype} | {counts.get('unverified', 0)} | {counts.get('verified', 0)} | "
            f"{counts.get('deprecated', 0)} | {total} |"
        )

    # Edge count
    edges_path = Path(wiki_dir) / "edges.jsonl"
    edge_count = 0
    if edges_path.exists():
        edge_count = sum(1 for line in edges_path.read_text().strip().split("\n") if line.strip())
    lines.append(f"\n**Relationship edges**: {edge_count}")

    # Preferences
    prefs = load_preferences(wiki_dir)
    confirmed = sum(1 for p in prefs if p.get("confirmed"))
    lines.append(f"**User preferences**: {len(prefs)} ({confirmed} confirmed)")

    return "\n".join(lines)


# ============================================================
# Main Commands
# ============================================================

def cmd_review(args):
    """Full review: wiki + checklist + preferences."""
    project_dir = args.project_dir
    wiki_dir = args.wiki_dir
    checklists_dir = args.checklists_dir

    report_parts = []
    report_parts.append(f"# Evolution Review — {date.today()}\n")
    report_parts.append(f"**Project**: {project_dir}\n")

    # Wiki enrichment
    wiki_proposals = propose_wiki_entries(project_dir, wiki_dir)
    report_parts.append(format_wiki_proposals(wiki_proposals))

    # Checklist evolution
    checklist_proposals = propose_checklist_entries(project_dir, checklists_dir)
    report_parts.append(format_checklist_proposals(checklist_proposals))

    # Preferences
    pref_proposals = extract_preferences(project_dir, wiki_dir)
    report_parts.append(format_preference_proposals(pref_proposals))

    report = "\n".join(report_parts)

    # Write report
    output_path = Path(project_dir) / "evolve-report.md"
    output_path.write_text(report)
    print(report)
    print(f"\nReport saved to: {output_path}")

    # Summary
    total = len(wiki_proposals) + len(checklist_proposals) + len(pref_proposals)
    print(f"\n--- Summary: {total} proposals ---")
    print(f"  Wiki entries:    {len(wiki_proposals)}")
    print(f"  Checklist items: {len(checklist_proposals)}")
    print(f"  Preferences:     {len(pref_proposals)}")
    if total == 0:
        print("  Nothing to evolve. Clean session!")


def cmd_wiki(args):
    """Wiki enrichment only."""
    proposals = propose_wiki_entries(args.project_dir, args.wiki_dir)
    print(format_wiki_proposals(proposals))
    print(f"Total: {len(proposals)} proposals")


def cmd_checklist(args):
    """Checklist evolution only."""
    proposals = propose_checklist_entries(args.project_dir, args.checklists_dir)
    print(format_checklist_proposals(proposals))
    print(f"Total: {len(proposals)} proposals")


def cmd_preferences(args):
    """User preference extraction."""
    proposals = extract_preferences(args.project_dir, args.wiki_dir)
    print(format_preference_proposals(proposals))

    if proposals and input("\nSave these preferences? [y/N] ").strip().lower() == "y":
        existing = load_preferences(args.wiki_dir)
        existing.extend(proposals)
        save_preferences(args.wiki_dir, existing)
        print(f"Saved {len(proposals)} preferences to wiki/user-preferences.yml")


def cmd_status(args):
    """Show evolution status."""
    print(format_evolution_status(args.wiki_dir))


def main():
    parser = argparse.ArgumentParser(description="analog-agents self-evolution engine")
    parser.add_argument("--project-dir", default=".", help="Project working directory")
    parser.add_argument("--wiki-dir", default="wiki", help="Wiki directory")
    parser.add_argument("--checklists-dir", default="checklists", help="Checklists directory")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("review", help="Full evolution review")
    sub.add_parser("wiki", help="Wiki enrichment only")
    sub.add_parser("checklist", help="Checklist evolution only")
    sub.add_parser("preferences", help="Extract user preferences")
    sub.add_parser("status", help="Show evolution status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "review":
        cmd_review(args)
    elif args.command == "wiki":
        cmd_wiki(args)
    elif args.command == "checklist":
        cmd_checklist(args)
    elif args.command == "preferences":
        cmd_preferences(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
