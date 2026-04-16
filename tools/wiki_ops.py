#!/usr/bin/env python3
"""
Knowledge graph operations for analog-agents wiki.

Usage:
  python3 wiki_ops.py search <query> [--wiki-dir WIKI_DIR]
  python3 wiki_ops.py consult <block-type> [--wiki-dir WIKI_DIR]
  python3 wiki_ops.py add <type> --name NAME --tags TAG1,TAG2 [--wiki-dir WIKI_DIR]
  python3 wiki_ops.py relate <from_id> <rel> <to_id> [--note NOTE] [--wiki-dir WIKI_DIR]
  python3 wiki_ops.py deprecate <id> [--wiki-dir WIKI_DIR]
  python3 wiki_ops.py archive-project --iteration-log PATH [--wiki-dir WIKI_DIR]
"""
import argparse
import json
import os
import sys
import yaml
from datetime import date
from pathlib import Path


DEFAULT_WIKI_DIR = "wiki"

TYPE_TO_DIR = {
    "topology": "topologies",
    "strategy": "strategies",
    "corner-lesson": "corner-lessons",
    "anti-pattern": "anti-patterns",
    "project": "projects",
    "block-case": "projects",
}

TYPE_TO_PREFIX = {
    "topology": "topo",
    "strategy": "strat",
    "corner-lesson": "corner",
    "anti-pattern": "anti",
    "project": "proj",
    "block-case": "case",
}

VALID_RELATIONS = [
    "contains", "instance_of", "extends", "contradicts", "prevents",
    "discovered_in", "validated", "invalidated", "supersedes", "requires",
]


def load_index(wiki_dir: str) -> dict:
    """Load wiki/index.yml. Returns entries dict."""
    index_path = Path(wiki_dir) / "index.yml"
    if not index_path.exists():
        return {}
    with open(index_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("entries", {})


def save_index(wiki_dir: str, entries: dict):
    """Save wiki/index.yml."""
    index_path = Path(wiki_dir) / "index.yml"
    with open(index_path, "w") as f:
        yaml.dump({"entries": entries}, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_entry(wiki_dir: str, path: str) -> dict:
    """Load a single wiki entry YAML file."""
    full_path = Path(wiki_dir) / path
    if not full_path.exists():
        return {}
    with open(full_path) as f:
        return yaml.safe_load(f) or {}


def next_id(entries: dict, prefix: str) -> str:
    """Generate next ID for a given prefix (e.g., topo-001 -> topo-002)."""
    existing = [k for k in entries if k.startswith(prefix + "-")]
    if not existing:
        return f"{prefix}-001"
    nums = []
    for k in existing:
        try:
            nums.append(int(k.split("-", 1)[1]))
        except ValueError:
            pass
    return f"{prefix}-{max(nums) + 1:03d}" if nums else f"{prefix}-001"


def search(wiki_dir: str, query: str) -> list:
    """Search entries by matching query against name, tags, description."""
    entries = load_index(wiki_dir)
    query_lower = query.lower()
    results = []
    for entry_id, meta in entries.items():
        score = 0
        summary_lower = meta.get("summary", "").lower()
        if query_lower in summary_lower:
            score += 2
        if query_lower in entry_id.lower():
            score += 1
        # Load full entry for tag matching
        entry = load_entry(wiki_dir, meta["path"])
        tags = [t.lower() for t in entry.get("tags", [])]
        if query_lower in tags:
            score += 3
        for tag in tags:
            if query_lower in tag:
                score += 1
        if score > 0:
            results.append({"id": entry_id, "score": score, **meta})
    return sorted(results, key=lambda r: -r["score"])


def consult(wiki_dir: str, block_type: str) -> dict:
    """Return relevant entries for a block type. Groups by entry type."""
    entries = load_index(wiki_dir)
    block_lower = block_type.lower()
    relevant = {"topologies": [], "strategies": [], "anti_patterns": [], "corner_lessons": [], "cases": []}

    for entry_id, meta in entries.items():
        entry = load_entry(wiki_dir, meta["path"])
        if not entry:
            continue
        tags = [t.lower() for t in entry.get("tags", [])]
        name_lower = entry.get("name", "").lower()

        match = block_lower in tags or block_lower in name_lower
        if not match:
            for tag in tags:
                if tag in block_lower or block_lower in tag:
                    match = True
                    break

        if match:
            etype = entry.get("type", "")
            bucket = {
                "topology": "topologies",
                "strategy": "strategies",
                "anti-pattern": "anti_patterns",
                "corner-lesson": "corner_lessons",
                "block-case": "cases",
                "project": "cases",
            }.get(etype, "cases")
            relevant[bucket].append({"id": entry_id, "name": entry.get("name", ""), "entry": entry})

    return relevant


def add_entry(wiki_dir: str, entry_type: str, name: str, tags: list, content: dict = None) -> str:
    """Add a new entry to the wiki. Returns the new ID."""
    entries = load_index(wiki_dir)
    prefix = TYPE_TO_PREFIX.get(entry_type, entry_type[:4])
    new_id = next_id(entries, prefix)
    subdir = TYPE_TO_DIR.get(entry_type, entry_type)
    filename = name.lower().replace(" ", "-").replace("/", "-") + ".yml"
    rel_path = f"{subdir}/{filename}"
    full_path = Path(wiki_dir) / rel_path

    full_path.parent.mkdir(parents=True, exist_ok=True)

    entry_data = {
        "id": new_id,
        "type": entry_type,
        "name": name,
        "tags": tags,
        "content": content or {"description": ""},
        "derived_from": [],
        "confidence": "unverified",
        "source": "manual",
        "created": str(date.today()),
        "updated": str(date.today()),
    }

    with open(full_path, "w") as f:
        yaml.dump(entry_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    entries[new_id] = {
        "path": rel_path,
        "type": entry_type,
        "summary": name,
    }
    save_index(wiki_dir, entries)
    return new_id


def add_edge(wiki_dir: str, from_id: str, rel: str, to_id: str, note: str = ""):
    """Add a relationship edge to edges.jsonl."""
    if rel not in VALID_RELATIONS:
        print(f"Error: invalid relation '{rel}'. Valid: {VALID_RELATIONS}", file=sys.stderr)
        sys.exit(1)
    edge = {"from": from_id, "to": to_id, "rel": rel}
    if note:
        edge["note"] = note
    edges_path = Path(wiki_dir) / "edges.jsonl"
    with open(edges_path, "a") as f:
        f.write(json.dumps(edge, ensure_ascii=False) + "\n")


def deprecate(wiki_dir: str, entry_id: str):
    """Mark an entry as deprecated."""
    entries = load_index(wiki_dir)
    if entry_id not in entries:
        print(f"Error: entry '{entry_id}' not found in index.", file=sys.stderr)
        sys.exit(1)
    entry_path = Path(wiki_dir) / entries[entry_id]["path"]
    entry = load_entry(wiki_dir, entries[entry_id]["path"])
    entry["confidence"] = "deprecated"
    entry["updated"] = str(date.today())
    with open(entry_path, "w") as f:
        yaml.dump(entry, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    print(f"Deprecated: {entry_id}")


def archive_project(wiki_dir: str, iteration_log_path: str):
    """Create project case entries from an iteration-log.yml."""
    with open(iteration_log_path) as f:
        log = yaml.safe_load(f) or {}

    project_name = log.get("project", "unknown-project")
    today = str(date.today())
    safe_name = f"{today}-{project_name}".lower().replace(" ", "-")

    project_dir = Path(wiki_dir) / "projects" / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "blocks").mkdir(exist_ok=True)

    # Write summary.yml
    entries = load_index(wiki_dir)
    proj_id = next_id(entries, "proj")

    summary = {
        "id": proj_id,
        "type": "project",
        "name": f"{project_name}",
        "tags": [project_name.lower()],
        "architecture": log.get("architecture", "unknown"),
        "total_blocks": log.get("summary", {}).get("total_blocks", 0),
        "total_iterations": log.get("summary", {}).get("total_iterations", 0),
        "convergence": True,
        "created": today,
    }
    with open(project_dir / "summary.yml", "w") as f:
        yaml.dump(summary, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Write trajectory.yml (copy of iteration log blocks section)
    trajectory = log.get("blocks", {})
    with open(project_dir / "trajectory.yml", "w") as f:
        yaml.dump(trajectory, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Write placeholder narrative.md
    with open(project_dir / "narrative.md", "w") as f:
        f.write(f"# Design Narrative — {project_name}\n\n")
        f.write("<!-- Write your design story here. What was tried, what failed, why. -->\n")
        f.write("<!-- This is the most valuable artifact — capture tacit knowledge. -->\n\n")
        lessons = log.get("summary", {}).get("lessons_learned", [])
        if lessons:
            f.write("## Lessons Learned (from iteration-log)\n\n")
            for lesson in lessons:
                f.write(f"- {lesson}\n")

    # Update index
    entries[proj_id] = {
        "path": f"projects/{safe_name}/summary.yml",
        "type": "project",
        "summary": project_name,
    }
    save_index(wiki_dir, entries)
    print(f"Archived project: {proj_id} -> projects/{safe_name}/")
    print(f"Please edit projects/{safe_name}/narrative.md with your design story.")
    return proj_id


def main():
    parser = argparse.ArgumentParser(description="analog-agents wiki operations")
    parser.add_argument("--wiki-dir", default=DEFAULT_WIKI_DIR)
    sub = parser.add_subparsers(dest="command")

    search_p = sub.add_parser("search")
    search_p.add_argument("query")

    consult_p = sub.add_parser("consult")
    consult_p.add_argument("block_type")

    add_p = sub.add_parser("add")
    add_p.add_argument("type", choices=list(TYPE_TO_DIR.keys()))
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--tags", required=True, help="Comma-separated tags")

    relate_p = sub.add_parser("relate")
    relate_p.add_argument("from_id")
    relate_p.add_argument("rel", choices=VALID_RELATIONS)
    relate_p.add_argument("to_id")
    relate_p.add_argument("--note", default="")

    dep_p = sub.add_parser("deprecate")
    dep_p.add_argument("id")

    archive_p = sub.add_parser("archive-project")
    archive_p.add_argument("--iteration-log", required=True)

    args = parser.parse_args()
    wiki_dir = args.wiki_dir

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "search":
        results = search(wiki_dir, args.query)
        if not results:
            print("No results found.")
        for r in results[:20]:
            print(f"  [{r['id']}] ({r['type']}) {r['summary']}")

    elif args.command == "consult":
        results = consult(wiki_dir, args.block_type)
        for category, items in results.items():
            if items:
                print(f"\n## {category}")
                for item in items:
                    print(f"  [{item['id']}] {item['name']}")

    elif args.command == "add":
        tags = [t.strip() for t in args.tags.split(",")]
        new_id = add_entry(wiki_dir, args.type, args.name, tags)
        print(f"Created: {new_id}")

    elif args.command == "relate":
        add_edge(wiki_dir, args.from_id, args.rel, args.to_id, args.note)
        print(f"Added edge: {args.from_id} --{args.rel}--> {args.to_id}")

    elif args.command == "deprecate":
        deprecate(wiki_dir, args.id)

    elif args.command == "archive-project":
        archive_project(wiki_dir, args.iteration_log)


if __name__ == "__main__":
    main()
