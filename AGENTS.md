# AGENTS.md — AI Agent Guide for analog-agents

Agentic analog / mixed-signal circuit design workflows built on top of
[`virtuoso-bridge-lite`](./virtuoso-bridge-lite) and the consumer tooling
in this repo.

## Start here (new session orientation)

1. **Python**: use `H:/analog-agents/.venv/Scripts/python.exe` — the project is
   editable-installed against a local clone of the bridge. Never use the
   global Python.
2. **Bridge source**: `virtuoso-bridge-lite/` at project root is a git
   **submodule** tracking `Arcadia-1/virtuoso-bridge-lite`, editable-installed
   into `.venv`. Fresh clones must use `git clone --recurse-submodules`
   (or `git submodule update --init` after a plain clone). Local edits take
   effect immediately; `cd virtuoso-bridge-lite && git pull` advances it
   without touching the parent pointer (parent `git status` will show the
   submodule as "dirty" — that's expected, ignore unless you want to bump
   the baseline for new clones).
3. **Local context**: `_local/context.yml` summarizes remote hosts, PDK paths,
   projects, and usernames — read it once to orient yourself without
   re-probing the environment.
4. **Sensitive map**: `_local/sanitize-map.yml` is the pure replacement table
   used by the sanitizer. It's gitignored.
5. **Proxy**: every GitHub request (git, uv, gh, curl, WebFetch) must go
   through `http://127.0.0.1:7897` with TLS verification disabled (see
   `~/.claude/skills/github-connection/`).

## Directory layout

| Path | Role | Tracked by git? |
|---|---|---|
| `tools/` | Persistent CLI tools (argparse + docstring). New tools land here. | ✅ |
| `tmp/` | Throwaway scripts: demos, probes, experiments. Often empty. | ❌ |
| `output/` | Snapshot / download artifacts produced by the standard SanitizingClient flow. May contain absolute paths. | ❌ |
| `WORK_<TASK>/` | Per-task scratch dirs for downloaded reports, tool outputs, intermediate files. **Preferred over `output/<task>/`** for anything tied to a specific verification / generation run. E.g. LVS+DRC reports → `WORK_CALIBRE/{drc,lvs}/`. | ❌ (`WORK_*` glob in `.gitignore`) |
| `example_artifacts/` | Raw + sanitized sample files for testing the sanitizer. | ❌ |
| `_local/` | Repo-root cross-skill site config: `context.yml`, `sanitize-map.yml`, `site.yaml` (hosts/license/ssh). Loaded by `tools/sanitizer.py` + skills that need cross-skill lab values. Per-skill values live in `skills/<X>/_local/site.yaml`. | ❌ |
| `virtuoso-bridge-lite/` | Git submodule of the upstream bridge (editable-installed). | ✅ (submodule) |
| `skills/` | Slash-command skill definitions consumed by Claude Code. | ✅ |
| `wiki/` | Knowledge graph: blocks, lessons, anti-patterns, strategies. | ✅ (except `projects/`) |
| `checklists/` | Per-phase checklists referenced by workflows. | ✅ |
| `config/` | Shared config. `servers.yml` / `reviewers.yml` / `effort.yml` are per-user, gitignored. | mixed |

Rule of thumb: **short-lived = `tmp/`, long-lived = `tools/`**. Promote from
`tmp/` to `tools/` when a script earns its keep.

## Standard download pattern

> Always use `SanitizingClient` for downloads. Reach for plain
> `VirtuosoClient` only when you're not going to download, or when you've
> thought about why the raw is OK to share.

```python
from virtuoso_bridge import VirtuosoClient, SanitizingClient
from tools.sanitizer import get_sanitize_fn

client = SanitizingClient(
    VirtuosoClient.from_env(),
    get_sanitize_fn(),      # reads _local/sanitize-map.yml
)

client.download_file(remote, "output/netlists/foo.scs")
# → output/netlists/foo.scs              (raw, gitignored)
# → output/netlists/sanitized/foo.scs    (redacted, shareable)

# Per-call opt-out for when raw IS the shareable artifact:
client.download_file(remote, local, sanitize=False)

# All other methods (execute_skill, load_il, upload_file, open_window, ...)
# transparently delegate — SanitizingClient is a drop-in replacement.
```

Direct invocation of `VirtuosoClient.download_file` is discouraged — it's
easy to forget to sanitize before sharing.

## Discovering new sensitive tokens

The sanitize map is **never complete** — every new design/user brings new
tokens. Standard loop:

1. Download a file via `SanitizingClient`.
2. Open `output/.../sanitized/<name>` and scan for anything that *still
   looks sensitive* (usernames, absolute paths, project codenames).
3. If you find something unsanitized, add a row to `_local/sanitize-map.yml`
   with longest-first ordering (path-prefixes come before the substrings
   they contain).
4. Re-sanitize: `python tools/sanitize_snapshot.py <dir>` for directories,
   or just re-download with `SanitizingClient` (which reads the updated
   map fresh each session).

Common tells:
- `/home/<unknown-user>/` → new username
- `Library name: <unknown>` / `Cell name: <unknown>` — in netlist headers
- `<vendor>/<tool>/<version>` paths under `/home/`, `/opt/`, `/eda/`

## Snapshot directory convention

Snapshots of a live Maestro session land under `output/snapshots/` as:

```
{YYYYMMDD_HHMMSS}__{lib}__{cell}/
├── snapshot.json     # session_info + config + env + variables + outputs + corners + status
├── maestro.sdb       # raw XML the corners section was parsed from
└── metrics.json      # per-step wall time / skill calls / scp transfers
```

**Naming rule** (applies here and to any multi-part file or directory):
- **single `_`** = within a segment (includes the date/time `_` between
  `YYYYMMDD` and `HHMMSS`, and any `_` that naturally appears in
  lib/cell/user names — these are part of the segment)
- **double `__`** = between segments

Segments are therefore unambiguously parseable.

## Canonical tasks & their scripts

| Goal | Tool |
|---|---|
| Dump a live Maestro session to JSON + metrics | `virtuoso-bridge-lite/examples/01_virtuoso/maestro/09_snapshot_with_metrics.py` |
| Sanitize a file or directory in place | `python tools/sanitize_snapshot.py <path> [--dry-run] [--unmap]` |
| Reverse a sanitization (with same map) | `python tools/sanitize_snapshot.py <sanitized_path> --unmap` |
| Build a `sanitize_fn` callable for `SanitizingClient` | `from tools.sanitizer import get_sanitize_fn` |
| Review / regenerate wiki entries | `python tools/wiki_ops.py ...` |
| Cross-model design review | `python tools/review_bridge.py ...` |
| Condense post-layout netlist | `python tools/postlayout_filter.py ...` |

## GitHub / network

The workstation requires a local HTTP proxy for all GitHub access:

```bash
export HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897
export GIT_SSL_NO_VERIFY=true                # proxy MITMs TLS
```

- `gh` CLI does NOT respect these reliably; prefer `curl -sk -x
  http://127.0.0.1:7897 -H "Authorization: Bearer $(gh auth token)" ...`
  for API calls.
- `uv sync` and `git clone` respect the env vars.
- Full details in the global skill `github-connection`.

## Bridge changes workflow

- `virtuoso-bridge-lite/` is a submodule and editable-installed; local
  edits apply immediately to `.venv`.
- To land a change upstream: commit inside the submodule, push to
  `origin/main` (`Arcadia-1/virtuoso-bridge-lite`).
- `cd virtuoso-bridge-lite && git pull` to stay current. The parent
  `git status` will show the submodule as dirty — ignore unless you want
  every future `git clone --recurse-submodules` of the parent to land on
  this commit, in which case `git add virtuoso-bridge-lite && git commit`
  to bump the baseline.
- Don't pin a SHA in `pyproject.toml` — we're on local path install. If
  you ever swap back to a git URL install, pin to a specific commit, not
  a branch.

## Intentionally NOT done (context for future sessions)

These were discussed and rejected or deferred. Don't re-litigate without
new information:

1. **Remote-side sanitize** (apply map on server before scp) — rejected.
   Breaks the discovery loop (can't see missed tokens in raw), needs
   remote map distribution, adds complexity for zero security gain since
   local disk is trusted.
2. **Bidirectional replacement** (auto-"un-sanitize" on upload) — rejected.
   Not a bijective function (value collisions, non-invertible). Silently
   corrupts user-authored content that happens to match a replacement
   value.
3. **Bridge auto-detects remote map** — rejected. Violates the
   policy-free principle of `virtuoso-bridge-lite`; produces surprising
   behavior for other consumers.
4. **`keep_raw=False` mode for SanitizingClient** — deferred. Would delete
   the raw immediately after producing the sanitized sibling. Would save
   disk but also break post-hoc audit. Revisit if local-disk trust ever
   becomes a concern.
5. **`[project.scripts]` CLI entry for `sanitize`** — deferred. Would need
   `package = true` in pyproject and a `tools/__init__.py`. Not worth the
   regression risk while we have only one tool that warrants it. Revisit
   when there are 3+ user-facing CLIs.

## Don'ts

- Don't commit `output/`, `WORK_*/`, `_local/`, `tmp/`, or
  `example_artifacts/` — all gitignored for good reason.
  (`virtuoso-bridge-lite/` is a submodule, not gitignored; edits inside
  it belong upstream.)
- Don't write throwaway scripts into `tools/` — use `tmp/`.
- Don't directly edit `virtuoso-bridge-lite/` files unless you also intend
  to push the change upstream; the editable install makes silent edits
  easy and silent regressions easier.
- Don't use plain `VirtuosoClient.download_file` for anything that might
  leave the machine. Use `SanitizingClient`.
- Don't bypass the sanitize discovery loop: if something "feels
  sensitive" and shows up in sanitized output, it probably is. Add it.
