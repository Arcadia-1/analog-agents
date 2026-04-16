# Wiki Schema

## Storage Layout

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
        ├── narrative.md    # most valuable artifact — free-form design story
        ├── trajectory.yml
        └── blocks/
            └── <block>.yml
```

`wiki/projects/` is gitignored. Users share specific cases via `git add -f`.

## Polanyi Principle

**Project narratives are the primary knowledge unit.** Topologies, strategies,
corner-lessons, and anti-patterns are indexes into narratives — they emerge
from project cases.

Every domain knowledge entry has a `derived_from` field linking back to the
project(s) where it was learned. A rule without provenance is less trustworthy.

## Entry Types

| Type | Directory | ID Prefix | Description |
|------|-----------|-----------|-------------|
| topology | topologies/ | topo- | Circuit topology (folded cascode, StrongArm, ...) |
| strategy | strategies/ | strat- | Design methodology (gm/Id, mixed-L, ...) |
| corner-lesson | corner-lessons/ | corner- | PVT corner surprise |
| anti-pattern | anti-patterns/ | anti- | Known trap with failure mechanism |
| project | projects/ | proj- | Project instance (summary.yml) |
| block-case | projects/*/blocks/ | case- | Per-block design case |

## Entry Schema (domain knowledge)

```yaml
id: topo-001
type: topology
name: "Folded-Cascode OTA"
tags: [ota, single-stage, high-gain, cascode]
process_nodes: [28nm, 65nm, 180nm]

content:
  description: "Single-stage transconductance amplifier..."
  key_tradeoffs:
    - "Gain vs output swing: double cascode eats 4x Vdsat"
  typical_specs:
    dc_gain: "50-70 dB"
  sizing_anchors:
    input_pair: "gm/Id=15-18, L=2xLmin"

derived_from: ["proj-001", "proj-005"]
confidence: verified        # unverified | verified | deprecated
source: "manual + N project validations"
created: 2026-04-10
updated: 2026-04-16
```

## Entry Schema (project)

```yaml
# projects/<name>/summary.yml
id: proj-001
type: project
name: "8-bit SAR ADC — 28nm 100MS/s"
tags: [sar-adc, 28nm, 100msps]
architecture: "async SAR with StrongArm + C-DAC"
total_blocks: 4
total_iterations: 11
convergence: true
final_specs:
  enob: { value: 7.6, target: ">= 7.5", margin: "+0.1" }
created: 2026-04-12
```

## Entry Schema (block-case)

```yaml
# projects/<name>/blocks/<block>.yml
id: case-012
type: block-case
name: "8-bit SAR Comparator (StrongArm)"
tags: [comparator, strongarm, 28nm]
topology_ref: topo-005
final_sizing:
  W_input: 2u
  L_input: 60n
iterations_to_converge: 2
key_decisions:
  - decision: "Short-channel input pair"
    reason: "Speed priority, offset corrected by redundant bits"
    outcome: "delay 380ps, offset 1.2mV"
final_specs:
  offset: { value: 1.2, unit: mV, target: "< 1.95", margin: "+0.75mV" }
```

## Edge Schema (edges.jsonl)

One JSON object per line:

```json
{"from": "topo-001", "to": "topo-005", "rel": "contains", "note": "optional"}
```

Supported relations:
- `contains` — A contains B as a sub-component
- `instance_of` — A is a concrete instance of topology B
- `extends` — A extends/improves on B
- `contradicts` — A's findings contradict B
- `prevents` — applying A prevents anti-pattern B
- `discovered_in` — lesson A was discovered in project B
- `validated` — case A validated strategy B
- `invalidated` — case A invalidated strategy B
- `supersedes` — A replaces B (B should be deprecated)
- `requires` — A requires B as a prerequisite

Dangling edges (target not found) are silently skipped during queries.

## Index Schema (index.yml)

```yaml
entries:
  topo-001:
    path: topologies/folded-cascode-ota.yml
    type: topology
    summary: "Folded-cascode OTA — single-stage, 50-70dB gain"
  anti-007:
    path: anti-patterns/diode-load-cmfb-trap.yml
    type: anti-pattern
    summary: "Diode-load CMFB kills DM gain on high-Z nodes"
```
