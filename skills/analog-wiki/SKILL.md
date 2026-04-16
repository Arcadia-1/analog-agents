---
name: analog-wiki
description: >
  Knowledge graph for analog circuit design. Stores topologies, strategies,
  corner lessons, anti-patterns, and project cases. Query with consult,
  add entries, track relationships, archive project cases.
  Use to build and query design knowledge across projects.
---

# analog-wiki

Narrative-first knowledge graph for analog circuit design. Stores topologies,
sizing strategies, corner lessons, anti-patterns, and project cases. Supports
querying, adding entries, tracking relationships, and archiving full project
cases with design narratives.

## Polanyi Principle

**Project narratives are the primary knowledge unit.** Rules emerge from cases,
not the other way around. Topologies, strategies, corner-lessons, and
anti-patterns are indexes into narratives -- they exist because someone learned
them in a real project.

Every domain knowledge entry has a `derived_from` field linking back to the
project(s) where it was learned. A rule without provenance is less trustworthy.

The `narrative.md` in each project case is the most valuable artifact -- a
free-form design story capturing tacit knowledge that structured YAML cannot.

See `shared-references/wiki-schema.md` for the full entry and edge schemas.

## Effort Gating

Read effort level per `shared-references/effort-contract.md`. Print at startup:

    [effort: <level>] wiki=<mode>

| Effort | Wiki behavior |
|--------|--------------|
| **lite** | No writes -- read-only queries only |
| **standard** | lesson_learned only (appended to `corner-lessons/`) |
| **intensive** | lesson + sizing strategy entries |
| **exhaustive** | Full case archive + narrative.md + relationship edges |

## Storage

All data lives in the `wiki/` directory within the repository.

```
wiki/
├── index.yml           # id -> path + type + one-line summary
├── edges.jsonl         # one directed edge per line
├── topologies/         # circuit topology knowledge
├── strategies/         # design/sizing strategies
├── corner-lessons/     # PVT corner surprises
├── anti-patterns/      # known traps
└── projects/           # project cases (gitignored)
    └── <project-name>/
        ├── summary.yml
        ├── narrative.md
        ├── trajectory.yml
        └── blocks/
            └── <block>.yml
```

`wiki/projects/` is gitignored by default (contains private project data).
Users can `git add -f` specific cases to share them with the team.

## Subcommands

### `/analog-wiki consult <block-type>`

Return relevant topologies, strategies, anti-patterns, and historical cases
matching the given block type.

```bash
python3 tools/wiki_ops.py consult <block-type>
```

Example:

```
/analog-wiki consult "folded-cascode"
```

Returns matching entries across all categories, with derived_from links to
project narratives where available.

### `/analog-wiki add <type>`

Interactive creation of a new knowledge entry. Ask the user for name, tags,
and content. Valid types: `topology`, `strategy`, `corner-lesson`, `anti-pattern`.

```bash
python3 tools/wiki_ops.py add <type> --name "..." --tags "..."
```

The tool assigns the next available ID (e.g., `topo-002`, `strat-004`) and
updates `wiki/index.yml`.

### `/analog-wiki relate <id1> <rel> <id2>`

Add a directed relationship edge between two entries.

```bash
python3 tools/wiki_ops.py relate <id1> <rel> <id2>
```

10 valid relations:

| Relation | Meaning |
|----------|---------|
| `contains` | A contains B as a sub-component |
| `instance_of` | A is a concrete instance of topology B |
| `extends` | A extends/improves on B |
| `contradicts` | A's findings contradict B |
| `prevents` | Applying A prevents anti-pattern B |
| `discovered_in` | Lesson A was discovered in project B |
| `validated` | Case A validated strategy B |
| `invalidated` | Case A invalidated strategy B |
| `supersedes` | A replaces B (B should be deprecated) |
| `requires` | A requires B as a prerequisite |

Edges are appended to `wiki/edges.jsonl`. Dangling edges (target not found)
are silently skipped during queries.

### `/analog-wiki archive-project`

Extract cases from the current project's `iteration-log.yml`. Creates:

- `summary.yml` -- architecture, final specs, convergence count
- `trajectory.yml` -- parameter change trajectory from iteration log
- Placeholder `narrative.md` -- prompts the architect to write the design story
  (the most valuable artifact)

```bash
python3 tools/wiki_ops.py archive-project --iteration-log iteration-log.yml
```

After creating the placeholder, prompt the architect to write the narrative.
The narrative captures tacit knowledge: what was tried, what failed, and why.

### `/analog-wiki deprecate <id>`

Mark an entry as deprecated (`confidence: deprecated`).

```bash
python3 tools/wiki_ops.py deprecate <id>
```

### `/analog-wiki search <query>`

Full-text search across all wiki entries.

```bash
python3 tools/wiki_ops.py search <query>
```

## Interaction with Other Skills

| Skill | Interaction |
|-------|-------------|
| **analog-decompose** | Calls `consult` at start for architecture references |
| **analog-design** | Calls `consult` for sizing strategies and anti-patterns |
| **analog-verify** | On convergence, suggests pushing a `block-case` entry |
| **analog-pipeline** | Triggers `archive-project` at end (effort >= standard) |

All pushes are **advisory** ("suggest archiving"), never mandatory. The user
can always skip.

## Seeding

Initial wiki entries can be created from existing knowledge in:
- `shared-references/cmfb.md` -- CMFB design knowledge
- `prompts/designer-prompt.md` -- sizing methodology and strategies

Use `/analog-wiki add` to formalize these into structured entries with proper
`derived_from` provenance.

## Standalone Use

This skill can be used independently -- it does not require `/analog-pipeline`.
Any skill or user can query, add, relate, or archive entries directly.
