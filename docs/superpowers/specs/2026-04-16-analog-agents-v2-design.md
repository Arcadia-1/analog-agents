# analog-agents v2 Design Spec

## Overview

Redesign analog-agents from a monolithic skill into a federated collection of
independently executable skills, with four new capabilities:

1. **Knowledge graph (analog-wiki)** — narrative-first design knowledge base
2. **Cross-model review (analog-review)** — multi-model circuit audit with divergence analysis
3. **Standardized checklists** — expanded topology coverage, effort-aware, wiki-linked
4. **Effort levels** — four-tier intensity control across all skills

Design philosophy informed by Michael Polanyi's theory of tacit knowledge:
- Project narratives over distilled rules
- Divergence analysis over consensus voting
- Expert mode (holistic-then-retrospective) over checklist-driven verification
- Reflection as a first-class activity at exhaustive effort

## Architecture: Federated Autonomy

Each skill is independently executable with its own SKILL.md. Skills share
conventions through `shared-references/` but do not depend on each other at
runtime. `/analog-pipeline` is a lightweight orchestrator that sequences the
other skills but adds no logic of its own.

No circular dependencies. Any skill can run standalone given the right input files.

---

## 1. Directory Structure

```
analog-agents/
├── skills/
│   ├── analog-pipeline/          # Lightweight orchestrator
│   │   └── SKILL.md
│   ├── analog-decompose/         # Architect Phase 1: architecture decomposition
│   │   └── SKILL.md
│   ├── analog-behavioral/        # Architect Phase 2: behavioral validation
│   │   └── SKILL.md
│   ├── analog-design/            # Designer: transistor-level netlist
│   │   └── SKILL.md
│   ├── analog-verify/            # Verifier: pre-sim review + simulation
│   │   └── SKILL.md
│   ├── analog-integrate/         # Architect Phase 3: integration verification
│   │   └── SKILL.md
│   ├── analog-review/            # Cross-model circuit audit
│   │   └── SKILL.md
│   └── analog-wiki/              # Knowledge graph operations
│       └── SKILL.md
│
├── shared-references/            # Conventions shared across all skills
│   ├── effort-contract.md        # Effort tier definitions + per-skill dimension tables
│   ├── review-protocol.md        # Cross-model review discipline
│   ├── checklist-schema.md       # Checklist field spec + keyword-to-checklist mapping
│   ├── wiki-schema.md            # Knowledge graph entry format
│   ├── handoff-contracts.md      # Agent handoff payload requirements
│   └── cmfb.md                   # Technical reference (existing, preserved)
│
├── checklists/                   # Standardized pre-simulation checklists
│   ├── common.yml                # Existing, updated with new fields
│   ├── folded-cascode.yml        # Existing, updated
│   ├── differential.yml          # Existing, updated
│   ├── amplifier.yml             # Existing, updated
│   ├── comparator.yml            # New
│   ├── current-mirror.yml        # New
│   ├── bandgap.yml               # New
│   ├── pll.yml                   # New
│   ├── adc.yml                   # New
│   └── ldo.yml                   # New
│
├── wiki/                         # Knowledge graph storage
│   ├── index.yml                 # Unified entry index
│   ├── edges.jsonl               # Relationship graph
│   ├── topologies/               # Domain knowledge: circuit topologies
│   ├── strategies/               # Domain knowledge: sizing/design strategies
│   ├── corner-lessons/           # Domain knowledge: PVT corner surprises
│   ├── anti-patterns/            # Domain knowledge: known traps
│   └── projects/                 # Project cases (gitignored)
│
├── config/
│   ├── servers.example.yml       # Existing: simulation server config
│   ├── reviewers.example.yml     # New: cross-model reviewer API config
│   └── effort.yml                # New: project-level effort override (optional)
│
├── hooks/                        # Existing hooks, preserved
│   ├── hooks.json
│   ├── session-start
│   ├── post-sim.sh
│   ├── post_sim_check.py
│   ├── post-netlist-check.sh
│   └── session-summary.sh
│
├── prompts/                      # Agent templates (moved from skills/analog-agents/)
│   ├── architect-prompt.md
│   ├── designer-prompt.md
│   ├── verifier-prompt.md
│   └── librarian-prompt.md
│
├── tools/                        # Python utilities
│   ├── review_bridge.py          # New: cross-model API caller + connectivity check
│   └── wiki_ops.py               # New: knowledge graph CRUD operations
│
├── README.md
└── docs/
```

Key changes from v1:
- Single `skills/analog-agents/` split into 8 independent skills
- 4 prompt templates moved to `prompts/`
- `pre-sim-checklists/` renamed to `checklists/`, 6 topologies added
- New `shared-references/` for cross-skill conventions
- New `wiki/` for knowledge graph
- New `config/reviewers.example.yml` for cross-model review
- New `tools/` for Python utilities
- `.gitignore` updated: add `wiki/projects/`, `config/reviewers.yml`

---

## 2. Knowledge Graph (analog-wiki)

### Polanyi Principle

The primary unit of knowledge is the **project narrative**, not the distilled
rule. `wiki/projects/` is the main body of the graph. Topologies, strategies,
corner-lessons, and anti-patterns are **indexes into narratives** — they emerge
from project cases, not the other way around.

### Storage

All in `wiki/` within the repository. `wiki/projects/` is gitignored by default
(contains private project data). Users can `git add -f` specific cases to share.

```
wiki/
├── index.yml                     # Entry index: id -> path + type + one-line summary
├── edges.jsonl                   # Relationship graph (one directed edge per line)
├── topologies/                   # e.g., folded-cascode-ota.yml
├── strategies/                   # e.g., mixed-l-for-matching.yml
├── corner-lessons/               # e.g., ss-125c-offset-blowup.yml
├── anti-patterns/                # e.g., diode-load-cmfb-trap.yml
└── projects/                     # gitignored — e.g., 2026-04-10-sar-adc-8bit/
    └── <project-name>/
        ├── summary.yml           # Architecture, final specs, convergence count
        ├── narrative.md          # Design story: what was tried, what failed, why
        ├── trajectory.yml        # Parameter change trajectory (from iteration-log.yml)
        └── blocks/
            └── <block>.yml       # Per-block case: final sizing, key decisions, specs
```

### Entry Schema

```yaml
# topologies/folded-cascode-ota.yml
id: topo-001
type: topology          # topology | strategy | corner-lesson | anti-pattern | project | block-case
name: "Folded-Cascode OTA"
tags: [ota, single-stage, high-gain, cascode]
process_nodes: [28nm, 65nm, 180nm]

content:
  description: "..."
  key_tradeoffs: [...]
  typical_specs: { dc_gain: "50-70 dB", ... }
  sizing_anchors: { input_pair: "gm/Id=15-18, L=2xLmin", ... }

# Polanyi: link to narratives that gave rise to this knowledge
derived_from: ["proj-001", "proj-005"]    # project IDs where this was learned

confidence: verified    # unverified | verified | deprecated
source: "manual + 3 project validations"
created: 2026-04-10
updated: 2026-04-16
```

```yaml
# projects/2026-04-10-sar-adc-8bit/summary.yml
id: proj-001
type: project
name: "8-bit SAR ADC — 28nm 100MS/s"
tags: [sar-adc, 28nm, 100msps]

architecture: "async SAR with StrongArm comparator + C-DAC"
total_blocks: 4
total_iterations: 11
convergence: true

final_specs:
  enob: { value: 7.6, target: ">= 7.5", margin: "+0.1" }
  power: { value: 1.8, unit: mW, target: "<= 2.0", margin: "+0.2mW" }

created: 2026-04-12
```

```yaml
# projects/2026-04-10-sar-adc-8bit/blocks/comparator.yml
id: case-012
type: block-case
name: "8-bit SAR Comparator (StrongArm)"
tags: [comparator, strongarm, sar-adc, 28nm]
topology_ref: topo-005

final_sizing:
  W_input: 2u
  L_input: 60n
  W_latch: 1u
iterations_to_converge: 2

key_decisions:
  - decision: "Short-channel input pair (60n)"
    reason: "Speed priority, offset corrected by redundant bits"
    outcome: "delay 380ps, offset 1.2mV — acceptable"

final_specs:
  offset: { value: 1.2, unit: mV, target: "< 1.95", margin: "+0.75mV" }
  delay: { value: 380, unit: ps, target: "< 500", margin: "+120ps" }
```

The `narrative.md` in each project is the most valuable artifact — a free-form
design story written by the architect at project completion. It captures the
tacit knowledge that structured YAML cannot: "We almost went with pipeline ADC
but the power budget killed it at behavioral validation. The comparator offset
was fine at TT but we only discovered the SS corner blowup on iteration 3.
Next time, budget 3x margin for offset at SS."

### Relationship Graph (edges.jsonl)

One directed edge per line:

```jsonl
{"from": "topo-001", "to": "topo-005", "rel": "contains", "note": "folded-cascode ADC contains StrongArm"}
{"from": "case-012", "to": "topo-005", "rel": "instance_of"}
{"from": "strat-003", "to": "anti-007", "rel": "prevents", "note": "mixed-L prevents mirror CLM"}
{"from": "corner-001", "to": "proj-001", "rel": "discovered_in"}
{"from": "case-012", "to": "strat-010", "rel": "validated"}
```

Supported relations: `contains`, `instance_of`, `extends`, `contradicts`,
`prevents`, `discovered_in`, `validated`, `invalidated`, `supersedes`, `requires`

Dangling edges (pointing to gitignored projects) are harmless — `consult`
silently skips unresolvable targets.

### `/analog-wiki` Skill Operations

| Command | Description |
|---------|-------------|
| `/analog-wiki consult <block-type>` | Return relevant topologies + strategies + anti-patterns + historical cases |
| `/analog-wiki add <type>` | Interactive entry creation |
| `/analog-wiki relate <id1> <rel> <id2>` | Add relationship edge |
| `/analog-wiki archive-project` | Extract cases from iteration-log.yml; prompt architect for narrative.md |
| `/analog-wiki deprecate <id>` | Mark entry as deprecated |
| `/analog-wiki search <query>` | Full-text search across all entries |

### Interaction with Other Skills

- **analog-decompose**: calls `consult` at start for architecture references
- **analog-design**: calls `consult` for sizing strategies and anti-patterns
- **analog-verify**: on convergence, suggests pushing a `block-case` entry
- **analog-integrate**: on project completion, suggests `archive-project`
- **analog-pipeline**: triggers `archive-project` at end (effort >= standard)

All pushes are advisory ("suggest archiving"), never mandatory. User can skip.

### Effort Interaction

| Effort | Wiki behavior |
|--------|--------------|
| lite | No writes |
| standard | lesson_learned only (appended to corner-lessons/) |
| intensive | lesson + sizing strategy entries |
| exhaustive | Full case archive + narrative.md + relationship edges |

---

## 3. Cross-Model Review (analog-review)

### Polanyi Principle

Divergence analysis over consensus voting. When reviewers disagree, the
disagreement IS the knowledge — it reveals what is non-obvious about the
circuit. The consensus matrix is a summary view; the divergence section is
the core of the report.

### Configuration

```yaml
# config/reviewers.example.yml
# Copy to config/reviewers.yml, fill in real keys. Gitignored.

reviewers:
  minimax:
    provider: minimax
    model: minimax-m2.7
    api_key: "${MINIMAX_API_KEY}"
    base_url: "https://api.minimax.chat/v1"
    timeout: 120

  qwen:
    provider: openai-compatible
    model: qwen-3.6-plus
    api_key: "${QWEN_API_KEY}"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout: 120

  kimi:
    provider: openai-compatible
    model: kimi-k2.5
    api_key: "${KIMI_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    timeout: 120

  glm:
    provider: openai-compatible
    model: glm-5.1
    api_key: "${GLM_API_KEY}"
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    timeout: 120

voting:
  min_reviewers: 2
  tie_break: "flag_for_human"     # flag_for_human | most_severe
```

### Connectivity Verification

`/analog-review check` — sends a lightweight probe ("Reply OK") to each
configured reviewer. Reports status, latency, and whether min_reviewers is met.

```
$ /analog-review check

  minimax (minimax-m2.7)   ok  1.2s
  qwen (qwen-3.6-plus)    ok  0.8s
  kimi (kimi-k2.5)        FAIL  401 Unauthorized
  glm (glm-5.1)           ok  1.5s

  Available: 3/4 — meets min_reviewers (2)
```

### Review Flow

```
Designer completes netlist + rationale.md
        |
        v
  /analog-review run <block-path>
        |
        +-- Read netlist + rationale.md + spec.yml
        +-- If wiki has anti-patterns for this topology, append to prompt
        +-- Assemble standardized review prompt (see below)
        |
        +---> minimax --+
        +---> qwen   --+  Concurrent, mutually blind
        +---> kimi   --+
        +---> glm    --+
                        |
                        v
              Collate + divergence analysis
                        |
                        v
           verifier-reports/cross-model-review.md
```

### Review Prompt Template

Sent to each external model. Contains ONLY raw files — no agent self-assessments
or interpretations (reviewer independence).

```
You are an analog IC design review expert. Review the following circuit netlist
and design rationale.

## Circuit Netlist
{netlist_content}

## Design Rationale
{rationale_content}

## Target Specifications
{spec_yml_content}

## Known Risks for This Topology (from knowledge base)
{wiki_anti_patterns_if_any}

Evaluate on these dimensions, giving PASS / WARN / FAIL for each:

1. **Connection correctness**: dangling nodes, pin mismatches, bulk errors
2. **Bias soundness**: mirror ratios, gm/Id range, headroom margins
3. **Sizing consistency**: do rationale equations match actual parameters?
4. **Topology risks**: known traps (CMFB polarity, compensation, etc.)
5. **Spec achievability**: can these specs be met with the given sizing?

For each WARN/FAIL: describe the problem, its impact, and a suggested fix.
```

### Report Format

```markdown
# Cross-Model Review — <block> — <date>

## Reviewer Status
| Reviewer | Status | Latency |
|----------|--------|---------|
| minimax  | ok     | 8.2s    |
| qwen     | ok     | 6.1s    |
| glm      | ok     | 9.7s    |

## Consensus Matrix
| Check              | minimax | qwen | glm | Consensus    |
|--------------------|---------|------|-----|--------------|
| Connection         | PASS    | PASS | PASS | PASS        |
| Bias soundness     | WARN    | WARN | PASS | WARN (2/3)  |
| Sizing consistency | PASS    | PASS | PASS | PASS        |
| Topology risks     | FAIL    | WARN | FAIL | FAIL (2/3)  |
| Spec achievability | PASS    | PASS | WARN | PASS (2/3)  |

## Divergence Analysis (core of the report)

### Topology risks — reviewer disagreement
- **minimax (FAIL)**: "CMFB uses diode-load, will collapse DM gain of main path"
- **qwen (WARN)**: "CMFB load type needs confirmation, may affect gain"
- **glm (FAIL)**: "diode-connected CMFB error amp on high-Z node, DM gain < 10dB"
- **Assessment**: minimax and glm provide specific mechanism analysis. qwen's
  WARN is consistent in direction but less specific. This is a real issue.

### Bias soundness — partial agreement
- **minimax (WARN)**: "tail CS headroom marginal at SS corner"
- **qwen (WARN)**: "Ibias may be low for target gm"
- **glm (PASS)**: no concern raised
- **Assessment**: two independent concerns about bias adequacy from different
  angles. Worth investigating even though glm disagrees.

## Action Items
1. [DIVERGENCE] Replace CMFB error amp with mirror-load (2/3 FAIL, mechanism confirmed)
2. [DIVERGENCE] Verify tail CS headroom at SS corner (2/3 WARN, different angles)
```

When reviewers disagree, default behavior is **flag for human judgment with
full reasoning from each side** — not automatic resolution by vote count.

### Effort Interaction

| Effort | Review behavior |
|--------|----------------|
| lite | Skipped (skill returns "skipped by effort level") |
| standard | 1 model (lowest-latency available) |
| intensive | 2 models, divergence analysis |
| exhaustive | All available models, full divergence report |

### Subcommands

| Command | Description |
|---------|-------------|
| `/analog-review check` | Verify all reviewer connectivity |
| `/analog-review run <block-path>` | Execute review + divergence analysis |
| `/analog-review report` | View most recent review report |

---

## 4. Effort Levels

### Configuration

Three-layer priority (high overrides low):

```
Command-line --effort  >  config/effort.yml  >  default: standard
```

```yaml
# config/effort.yml (optional, project-level)
default_effort: standard

overrides:
  comparator: intensive     # offset-sensitive, invest more
  bias: lite                # simple blocks, lightweight
```

### Effort Contract

Every skill prints its active effort level and parameters at startup:

```
[effort: intensive] corners=5, max_iter=5, reviewers=2, wiki=lesson+strategy
```

### Dimension Table

| Dimension | lite | standard | intensive | exhaustive |
|-----------|------|----------|-----------|------------|
| **Corner matrix** | TT 27C only | TT + SS/125C + FF/-40C | 5 corners (TT/SS/FF/SF/FS) | Full PVT + MC (if mismatch models available, else full PVT) |
| **Designer iteration limit** | 2 rounds | 3 rounds | 5 rounds | Unlimited + optimizer auto-trigger on iter 2+ tight margin |
| **Cross-model review** | Skip | 1 model | 2 models, divergence | All models, full divergence report |
| **Wiki writes** | None | lesson_learned only | lesson + sizing strategy | Full case archive + narrative.md + edges |
| **Pre-sim checks** | structural only | structural + estimate | All (incl. semantic) | All; results written to review-gate.md for async human review |
| **Behavioral validation** | Skip | Quick (key specs) | Full (all specs) | Full + sensitivity sweep |
| **Reflection** | None | None | None | Architect writes retrospective narrative: "what emerged that could not have been predicted?" |

### Invariants (never change regardless of effort)

- Verifier NEVER modifies netlist files
- Every FAIL includes measured / target / margin
- Handoff contract required fields are never optional
- Checklist items with severity=error AND effort=lite always execute
- Cross-model review independence: no agent self-assessments passed to reviewers

---

## 5. Standardized Checklists

### Updated Field Schema

```yaml
<check_name>:
  description: "One-line description"
  method: structural | estimate | semantic
  severity: error | warn
  effort: lite | standard | intensive | exhaustive   # Minimum effort to trigger
  auto_checkable: true | false                        # Can a script verify this?
  references: []                                      # Wiki entry IDs
  how: >
    Procedure description
```

New fields vs v1: `effort`, `auto_checkable`, `references`.

`auto_checkable` is metadata only — no automated execution engine is implemented
in this version. It marks which items could be automated in the future.

### Existing Checklists — Migration

All existing entries in common.yml, folded-cascode.yml, differential.yml,
amplifier.yml get three new fields appended:
- `effort: lite` (all existing checks are fundamental, always execute)
- `auto_checkable: true` (structural) / `false` (semantic)
- `references: []` (populated incrementally as wiki grows)

Zero breaking changes. All existing checks preserved.

### New Checklists

**comparator.yml** (5 checks):
- `input_pair_symmetry` — error, lite, auto_checkable
- `latch_cross_coupling` — error, lite, auto_checkable
- `clock_gating` — error, lite, auto_checkable
- `precharge_completeness` — warn, standard, semantic
- `offset_estimation` — warn, intensive, estimate

**current-mirror.yml** (3 checks):
- `ratio_accuracy` — error, lite, auto_checkable
- `compliance_headroom` — error, lite, estimate
- `channel_length_modulation` — warn, standard, estimate (ref: strat-mixed-l)

**bandgap.yml** (3 checks):
- `startup_circuit` — error, lite, semantic
- `bjt_area_ratio` — error, lite, auto_checkable
- `curvature_compensation` — warn, intensive, semantic

**pll.yml** (4 checks):
- `loop_filter_component_values` — error, lite, structural
- `vco_gain_sign` — error, lite, semantic
- `lock_range_vs_spec` — warn, standard, estimate
- `phase_noise_budget` — warn, intensive, estimate

**adc.yml** (4 checks):
- `sampling_capacitor_ktc` — error, lite, estimate
- `timing_budget_closure` — error, standard, estimate
- `reference_settling` — warn, standard, estimate
- `dnl_inl_from_component_matching` — warn, intensive, estimate

**ldo.yml** (4 checks):
- `loop_stability_with_load` — error, lite, semantic
- `dropout_headroom` — error, lite, estimate
- `load_transient_decoupling` — warn, standard, estimate
- `psrr_at_frequency` — warn, intensive, estimate

### Checklist Loading

Verifier loads checklists based on `spec.yml`:

```yaml
# In spec.yml (explicit, preferred):
checklists: [common, amplifier, folded-cascode, differential]
```

If `checklists` field is absent, fall back to keyword matching against the
`block` field. Mapping defined in `shared-references/checklist-schema.md`.
Architect is responsible for setting the `checklists` field in sub-block specs.

### Execution Modes (Polanyi-informed)

**Guided mode** (effort lite / standard):
Agent executes checklist items sequentially. Each item checked, result reported.
Appropriate when the agent is unfamiliar with the topology.

**Expert mode** (effort intensive / exhaustive):
Agent first performs a holistic circuit review — forms its own assessment of
the design. THEN uses the checklist as retrospective validation: "did my
holistic review miss anything on this list?" Order is reversed: whole-first,
parts-second. This preserves the integrated understanding that Polanyi argues
is destroyed by premature decomposition into subsidiary particulars.

---

## 6. Skill Responsibilities

### `/analog-pipeline` — Lightweight Orchestrator

**Responsibility**: Sequence other skills, manage global state, maintain
`iteration-log.yml`.

```
Input:  spec.yml + servers.yml + effort config
Output: iteration-log.yml (continuously updated)

Flow:
  Read effort level
  -> /analog-wiki consult (if wiki/ non-empty)
  -> /analog-decompose
  -> user gate: confirm architecture
  -> /analog-behavioral (effort >= standard)
  -> for each sub-block:
      /analog-design
      -> /analog-review (effort >= standard)
      -> /analog-verify
      loop until convergence or iteration limit
  -> /analog-integrate
  -> L3 sign-off
  -> /analog-wiki archive-project (effort >= standard)
  -> reflection narrative (effort = exhaustive)
```

Does NOT: dispatch agents directly, run simulations, write netlists.
Only decides "which skill next" and "record what happened."

### `/analog-decompose` — Architecture Decomposition

**Responsibility**: Architect Phase 1. Top-level spec -> sub-block specs +
architecture documentation.

```
Input:  spec.yml, user constraints, wiki consult results (optional)
Output: architecture.md, budget.md, blocks/*/spec.yml,
        blocks/*/verification-plan.md, blocks/*/testbench_*.scs

Effort: No variation (decomposition itself is not tiered)
Wiki:   Calls consult at start; no writes
```

Uses `prompts/architect-prompt.md`. Architect is responsible for setting
the `checklists` field in each sub-block's spec.yml.

### `/analog-behavioral` — Behavioral Validation

**Responsibility**: Architect Phase 2. Verilog-A behavioral models + system
simulation.

```
Input:  architecture.md, blocks/*/spec.yml
Output: blocks/*/behavioral.va, system simulation results

Effort:
  lite       -> skip entirely
  standard   -> key specs quick check
  intensive  -> all specs verified
  exhaustive -> all specs + sensitivity sweep
```

If behavioral simulation fails top-level specs, must return to
`/analog-decompose` to revise architecture or budget.

### `/analog-design` — Transistor-Level Design

**Responsibility**: Designer produces netlist + rationale for one sub-block.

```
Input:  blocks/<name>/spec.yml, behavioral.va, architecture.md,
        verifier-report (empty on first iteration), effort level
Output: circuit/<block>.scs, circuit/rationale.md

Effort:
  Iteration limit: lite=2, standard=3, intensive=5, exhaustive=unlimited
  Exhaustive: optimizer auto-triggers on iter 2+ with tight margins

Wiki: Calls consult at start for sizing strategies and anti-patterns
```

On completion, suggests running `/analog-review run`.

### `/analog-review` — Cross-Model Audit

**Responsibility**: Send netlist + rationale to external models for independent
review. Collate results with divergence analysis.

```
Input:  circuit/<block>.scs, rationale.md, spec.yml, config/reviewers.yml
Output: verifier-reports/cross-model-review.md

Subcommands:
  /analog-review check   -> verify all reviewer connectivity
  /analog-review run     -> execute review + divergence analysis
  /analog-review report  -> view most recent report

Effort:
  lite       -> skip
  standard   -> 1 model
  intensive  -> 2 models, divergence analysis
  exhaustive -> all models, full divergence report
```

Fully independent. Can be run standalone at any time.

### `/analog-verify` — Simulation Verification

**Responsibility**: Verifier pre-sim review + Spectre simulation + margin report.

```
Input:  circuit/<block>.scs, testbench_*.scs, spec.yml,
        verification-plan.md, verification level, effort
Output: verifier-reports/L{1,2,3}-*/*.md

Effort:
  Pre-sim check depth: lite=structural, standard=+estimate,
                       intensive=all, exhaustive=all+review-gate.md
  Corner matrix (L3): lite=TT, standard=3, intensive=5, exhaustive=full+MC

Checklist loading: from spec.yml checklists field, fallback keyword match
Execution mode: guided (lite/standard), expert (intensive/exhaustive)
```

After simulation, auto-decides next step (PASS/FAIL/ESCALATE).

### `/analog-integrate` — Integration Verification

**Responsibility**: Architect Phase 3. Replace behavioral models with verified
netlists, run top-level integration verification.

```
Input:  all verified sub-block .scs, verifier-reports, architecture.md
Output: integration verifier-report.md

Effort: same corner matrix as /analog-verify
```

If integration fails, identifies the responsible sub-block or interface.

### `/analog-wiki` — Knowledge Graph

**Responsibility**: Manage `wiki/` directory. Query and write interface.

```
Subcommands:
  /analog-wiki consult <block-type>       -> return relevant entries
  /analog-wiki add <type>                 -> interactive entry creation
  /analog-wiki relate <id1> <rel> <id2>   -> add relationship edge
  /analog-wiki archive-project            -> extract cases from iteration-log.yml,
                                             prompt architect for narrative.md
  /analog-wiki deprecate <id>             -> mark entry deprecated
  /analog-wiki search <query>             -> full-text search

Effort:
  lite       -> no writes
  standard   -> lesson_learned only
  intensive  -> lesson + sizing strategy
  exhaustive -> full case archive + narrative.md + edges
```

Fully independent. Can be used without any design activity —
`/analog-wiki add topology` works standalone.

### Skill Dependency Graph

```
analog-wiki <-- consult --- analog-decompose
                            analog-design

analog-pipeline --orchestrates--> analog-decompose
                                  analog-behavioral
                                  analog-design
                                  analog-review
                                  analog-verify
                                  analog-integrate
                                  analog-wiki

analog-review   <- independent, called by pipeline or standalone
analog-wiki     <- independent, called by pipeline or standalone
```

No circular dependencies.

---

## 7. Shared References

### effort-contract.md

Contains the full dimension table, invariant rules, and per-skill effort
parameter listings. Every skill reads this to determine its behavior at the
current effort level.

### review-protocol.md

Cross-model review discipline:
- Reviewer independence: only raw files in prompt, no agent self-assessments
- Divergence over consensus: disagreements are flagged for human judgment
- Prompt standardization: all reviewers get identical prompt
- Anti-pattern injection: if wiki has relevant entries, append to prompt

### checklist-schema.md

Defines the 7-field YAML format. Contains the keyword-to-checklist fallback
mapping table. Documents guided mode vs expert mode execution.

### wiki-schema.md

Defines entry YAML format, edge format, supported relation types, and the
`derived_from` field that links rules back to their source narratives.

### handoff-contracts.md

Extracted from current SKILL.md. Defines required payload for every agent
handoff (architect->designer, designer->verifier, etc.). Shared across all
skills that dispatch agents.

---

## 8. Migration Path from v1

### What Moves

| v1 Location | v2 Location |
|-------------|-------------|
| `skills/analog-agents/SKILL.md` | Split into 8 skills under `skills/` |
| `skills/analog-agents/architect-prompt.md` | `prompts/architect-prompt.md` |
| `skills/analog-agents/designer-prompt.md` | `prompts/designer-prompt.md` |
| `skills/analog-agents/verifier-prompt.md` | `prompts/verifier-prompt.md` |
| `skills/analog-agents/librarian-prompt.md` | `prompts/librarian-prompt.md` |
| `skills/analog-agents/references/cmfb.md` | `shared-references/cmfb.md` |
| `pre-sim-checklists/*.yml` | `checklists/*.yml` (with new fields added) |

### What's New

- `skills/analog-review/SKILL.md` + `tools/review_bridge.py`
- `skills/analog-wiki/SKILL.md` + `tools/wiki_ops.py`
- `shared-references/` (5 convention documents)
- `wiki/` directory structure + initial entries from existing cmfb.md knowledge
- `config/reviewers.example.yml` + `config/effort.yml`
- `checklists/` 6 new topology files

### What's Preserved

- All hooks unchanged
- `config/servers.example.yml` unchanged
- README.md updated to reflect new structure
- All existing checklist content preserved (fields appended, not modified)

### Backward Compatibility

The original `skills/analog-agents/` directory is removed. Users who symlinked
it must update their symlinks to point to individual skills or to
`skills/analog-pipeline/` for the full workflow.

---

## 9. Open Questions / Future Work

- **Automated checklist execution**: `auto_checkable: true` items have no
  execution engine yet. Future: Python tool that parses netlists and runs
  structural checks programmatically.
- **Wiki search quality**: initial implementation is keyword/tag matching.
  Future: embedding-based semantic search if wiki grows large.
- **Cross-model review cost**: exhaustive effort with 4 models per sub-block
  per iteration adds up. May need token budget tracking.
- **Monte Carlo at exhaustive**: requires PDK mismatch models. If unavailable,
  falls back to full PVT corner sweep without MC.
