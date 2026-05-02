#!/usr/bin/env python3
"""Sanitize a snapshot directory (or file) using the token map in
``_local/context.yml``.

Pure-dictionary replacement: whatever appears as a key in the ``sanitize:``
section is replaced by its value in every text file of the snapshot.
Longer keys are applied first so a short token can never overwrite a
longer one that contains it.

Usage:
    # sanitize a snapshot dir
    python tools/sanitize_snapshot.py output/snapshots/<dir>

    # or a single file
    python tools/sanitize_snapshot.py output/snapshots/<dir>/snapshot.json

    # preview only
    python tools/sanitize_snapshot.py <target> --dry-run

    # reverse (requires access to context.yml)
    python tools/sanitize_snapshot.py <sanitized_dir> --unmap

    # point at a different context
    python tools/sanitize_snapshot.py <target> --context path/to/other.yml

Artifacts (non --dry-run, non --unmap):
    <target>__sanitized/
        snapshot.json
        maestro.sdb
        metrics.json           (copied verbatim)
        sanitize.log           (one line per substitution)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = PROJECT_ROOT / "_local" / "sanitize-map.yml"
LEGACY_CONTEXT = PROJECT_ROOT / "_local" / "context.yml"   # fallback: old `sanitize:` section

# Extensions we KNOW are binary — skip them without attempting text decode
# (avoids reading large images/PDFs/zips into memory just to fail).
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar",
               ".gz", ".tgz", ".bz2", ".xz", ".7z", ".exe", ".dll",
               ".so", ".dylib", ".o", ".a", ".pyc", ".pyo",
               ".raw", ".psf"}          # spectre .raw is binary PSF


def load_token_map(path: Path) -> dict[str, str]:
    """Load the replacement table.

    If `path` is a bare YAML map, use it directly.  If it contains a
    top-level `sanitize:` key (legacy layout inside context.yml), use that.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict) and "sanitize" in data:
        data = data["sanitize"] or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must be a flat mapping of src: dst")
    return {str(k): str(v) for k, v in data.items()}


def sanitize_text(text: str, tokens: dict[str, str]) -> tuple[str, list[tuple[str, str, int]]]:
    """Apply the token map and return (new_text, list_of_(src, dst, count))."""
    hits: list[tuple[str, str, int]] = []
    for src in sorted(tokens, key=len, reverse=True):
        if not src:
            continue
        n = text.count(src)
        if n:
            text = text.replace(src, tokens[src])
            hits.append((src, tokens[src], n))
    return text, hits


def process_file(src: Path, dst: Path, tokens: dict[str, str],
                 *, dry_run: bool = False) -> list[tuple[str, str, int]]:
    # Known-binary extensions skip decoding entirely (fast path + safety).
    if src.suffix.lower() in BINARY_EXTS:
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return []

    # Everything else: try UTF-8.  If it decodes, sanitize.  If not, copy.
    try:
        text = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return []

    new_text, hits = sanitize_text(text, tokens)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(new_text, encoding="utf-8")
    return hits


def invert_map(tokens: dict[str, str]) -> dict[str, str]:
    inv: dict[str, str] = {}
    for k, v in tokens.items():
        if v in inv and inv[v] != k:
            print(f"[warn] duplicate replacement value {v!r} "
                  f"({k!r} and {inv[v]!r}) — unmap is ambiguous",
                  file=sys.stderr)
        inv[v] = k
    return inv


def target_dir_for(src: Path, unmap: bool) -> Path:
    suffix = "__unmapped" if unmap else "__sanitized"
    if src.is_dir():
        return src.parent / f"{src.name}{suffix}"
    return src.parent / f"{src.stem}{suffix}{src.suffix}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", type=Path,
                    help="snapshot directory or single file")
    ap.add_argument("--map", "--context", dest="map_path", type=Path,
                    default=None,
                    help="path to sanitize-map.yml (default: _local/sanitize-map.yml; "
                         "falls back to _local/context.yml `sanitize:` section)")
    ap.add_argument("--out", type=Path, default=None,
                    help="destination; default is <target>__sanitized/")
    ap.add_argument("--dry-run", action="store_true",
                    help="only print substitutions, don't write")
    ap.add_argument("--unmap", action="store_true",
                    help="reverse sanitization (needs the same context.yml)")
    args = ap.parse_args()

    if not args.target.exists():
        print(f"No such file or directory: {args.target}", file=sys.stderr)
        return 2

    map_path = args.map_path
    if map_path is None:
        map_path = DEFAULT_MAP if DEFAULT_MAP.exists() else LEGACY_CONTEXT
    if not map_path.exists():
        print(f"map file not found: {map_path}", file=sys.stderr)
        return 2

    tokens = load_token_map(map_path)
    if args.unmap:
        tokens = invert_map(tokens)

    out = args.out or target_dir_for(args.target, args.unmap)

    total_hits: dict[str, tuple[str, int]] = {}  # src -> (dst, count)
    log_lines: list[str] = []

    if args.target.is_dir():
        for src_file in sorted(args.target.rglob("*")):
            if src_file.is_dir():
                continue
            rel = src_file.relative_to(args.target)
            dst_file = out / rel
            hits = process_file(src_file, dst_file, tokens,
                                dry_run=args.dry_run)
            for src, dst, n in hits:
                prev_dst, prev_n = total_hits.get(src, (dst, 0))
                total_hits[src] = (dst, prev_n + n)
                log_lines.append(f"{rel}\t{src}\t->\t{dst}\t(x{n})")
    else:
        dst_file = out if args.out else target_dir_for(args.target, args.unmap)
        hits = process_file(args.target, dst_file, tokens, dry_run=args.dry_run)
        for src, dst, n in hits:
            total_hits[src] = (dst, total_hits.get(src, (dst, 0))[1] + n)
            log_lines.append(f"{args.target.name}\t{src}\t->\t{dst}\t(x{n})")

    # Summary
    mode = "DRY-RUN" if args.dry_run else ("UNMAP" if args.unmap else "SANITIZE")
    print(f"[{mode}] token map: {map_path}")
    print(f"[{mode}] input:     {args.target}")
    print(f"[{mode}] output:    {out if not args.dry_run else '(not written)'}")
    print()
    print(f"{'src':40s}  {'dst':30s}  {'hits':>5s}")
    print("-" * 80)
    for src in sorted(total_hits, key=lambda k: (-total_hits[k][1], k)):
        dst, n = total_hits[src]
        print(f"{src[:40]:40s}  {dst[:30]:30s}  {n:>5d}")
    print("-" * 80)
    print(f"{'TOTAL substitutions:':40s}  "
          f"{sum(n for _, n in total_hits.values()):>5d} "
          f"across {len(log_lines)} file×token hits")

    # Write sanitize.log into output dir
    if not args.dry_run and args.target.is_dir() and log_lines:
        log_path = out / "sanitize.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print(f"\nlog:       {log_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
