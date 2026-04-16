# analog-agents v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure analog-agents from a monolithic skill into 8 federated skills with knowledge graph, cross-model review, standardized checklists, and effort levels.

**Architecture:** Federated autonomy — each skill is independently executable via its own SKILL.md, sharing conventions through `shared-references/`. No circular dependencies. `analog-pipeline` is a lightweight orchestrator.

**Tech Stack:** Markdown (SKILL.md files), YAML (checklists, wiki entries, config), JSONL (edges), Python 3.9+ (review_bridge.py, wiki_ops.py), OpenAI-compatible API (cross-model review).

**Spec:** `docs/superpowers/specs/2026-04-16-analog-agents-v2-design.md`

---

## Phase 1: Scaffolding & Migration (no behavior change)

Move existing files to new locations. After this phase, the repo has the v2
directory structure but all content is identical to v1.

### Task 1: Create directory structure and move prompt templates

**Files:**
- Create: `prompts/` directory
- Create: `shared-references/` directory
- Create: `wiki/` directory tree
- Create: `tools/` directory
- Move: `skills/analog-agents/architect-prompt.md` -> `prompts/architect-prompt.md`
- Move: `skills/analog-agents/designer-prompt.md` -> `prompts/designer-prompt.md`
- Move: `skills/analog-agents/verifier-prompt.md` -> `prompts/verifier-prompt.md`
- Move: `skills/analog-agents/librarian-prompt.md` -> `prompts/librarian-prompt.md`
- Move: `skills/analog-agents/references/cmfb.md` -> `shared-references/cmfb.md`
- Move: `pre-sim-checklists/` -> `checklists/`

- [ ] **Step 1: Create new directories**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
mkdir -p prompts
mkdir -p shared-references
mkdir -p wiki/topologies wiki/strategies wiki/corner-lessons wiki/anti-patterns wiki/projects
mkdir -p tools
mkdir -p skills/analog-pipeline skills/analog-decompose skills/analog-behavioral
mkdir -p skills/analog-design skills/analog-verify skills/analog-integrate
mkdir -p skills/analog-review skills/analog-wiki
```

- [ ] **Step 2: Move prompt templates**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
git mv skills/analog-agents/architect-prompt.md prompts/architect-prompt.md
git mv skills/analog-agents/designer-prompt.md prompts/designer-prompt.md
git mv skills/analog-agents/verifier-prompt.md prompts/verifier-prompt.md
git mv skills/analog-agents/librarian-prompt.md prompts/librarian-prompt.md
git mv skills/analog-agents/references/cmfb.md shared-references/cmfb.md
```

- [ ] **Step 3: Move checklists directory**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
git mv pre-sim-checklists checklists
```

- [ ] **Step 4: Update .gitignore**

Add to `.gitignore`:

```
wiki/projects/
config/reviewers.yml
config/effort.yml
```

- [ ] **Step 5: Create placeholder files for wiki**

Create `wiki/index.yml`:

```yaml
# analog-wiki entry index
# Each entry: id -> path, type, one-line summary
entries: {}
```

Create `wiki/edges.jsonl` (empty file):

```
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: create v2 directory structure, move prompts and checklists"
```

---

### Task 2: Create config templates

**Files:**
- Create: `config/reviewers.example.yml`
- Create: `config/effort.yml`

- [ ] **Step 1: Write reviewers.example.yml**

Create `config/reviewers.example.yml`:

```yaml
# Cross-model reviewer configuration for /analog-review
# Copy to config/reviewers.yml and fill in real API keys. Never commit reviewers.yml.

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

- [ ] **Step 2: Write effort.yml**

Create `config/effort.yml`:

```yaml
# Project-level effort configuration for analog-agents.
# Command-line --effort overrides this file.
# Default: standard

default_effort: standard

# Per block-type overrides (optional):
# overrides:
#   comparator: intensive
#   bias: lite
```

- [ ] **Step 3: Commit**

```bash
git add config/reviewers.example.yml config/effort.yml
git commit -m "feat: add reviewer and effort config templates"
```

---

## Phase 2: Shared References (conventions all skills read)

### Task 3: Write effort-contract.md

**Files:**
- Create: `shared-references/effort-contract.md`

- [ ] **Step 1: Write effort-contract.md**

Create `shared-references/effort-contract.md`:

```markdown
# Effort Contract

Four effort tiers control resource investment across all analog-agents skills.

## Reading Effort

Priority (high overrides low):

1. Command-line: `--effort exhaustive`
2. Project config: `config/effort.yml` (with optional per-block overrides)
3. Default: `standard`

Every skill prints its active effort at startup:

    [effort: intensive] corners=5, max_iter=5, reviewers=2, wiki=lesson+strategy

## Dimension Table

| Dimension | lite | standard | intensive | exhaustive |
|-----------|------|----------|-----------|------------|
| **Corner matrix** | TT 27C only | TT + SS/125C + FF/-40C | 5 corners (TT/SS/FF/SF/FS) | Full PVT + MC (if mismatch models available, else full PVT) |
| **Designer iteration limit** | 2 rounds | 3 rounds | 5 rounds | Unlimited + optimizer auto-trigger on iter 2+ tight margin |
| **Cross-model review** | Skip | 1 model | 2 models, divergence analysis | All models, full divergence report |
| **Wiki writes** | None | lesson_learned only | lesson + sizing strategy | Full case archive + narrative.md + relationship edges |
| **Pre-sim checks** | structural only | structural + estimate | All (incl. semantic) | All; results written to review-gate.md for async human review |
| **Behavioral validation** | Skip | Quick (key specs only) | Full (all specs) | Full + sensitivity sweep |
| **Reflection** | None | None | None | Architect writes retrospective narrative |

## Invariants (never change regardless of effort)

- Verifier NEVER modifies netlist files
- Every FAIL includes measured / target / margin
- Handoff contract required fields are never optional
- Checklist items with `severity: error` AND `effort: lite` always execute
- Cross-model reviewer independence: no agent self-assessments passed to reviewers
```

- [ ] **Step 2: Commit**

```bash
git add shared-references/effort-contract.md
git commit -m "docs: add effort contract shared reference"
```

---

### Task 4: Write review-protocol.md

**Files:**
- Create: `shared-references/review-protocol.md`

- [ ] **Step 1: Write review-protocol.md**

Create `shared-references/review-protocol.md`:

```markdown
# Cross-Model Review Protocol

## Core Principles

### Reviewer Independence

The review prompt contains ONLY raw file contents:
- Circuit netlist (.scs)
- Design rationale (rationale.md)
- Target specifications (spec.yml)
- Known anti-patterns from wiki (if any)

NEVER include: agent self-assessments, prior review results, designer's
confidence statements, or any interpretation of the design. The reviewer
must form its own judgment from raw materials.

### Divergence Over Consensus

When reviewers disagree, the disagreement IS the knowledge. The consensus
matrix is a summary view; the divergence analysis section is the core of
every review report.

Default behavior on disagreement: **flag for human judgment** with full
reasoning from each reviewer. NOT automatic resolution by vote count.

A well-reasoned minority FAIL outweighs a vague majority PASS.

### Prompt Standardization

All reviewers receive an identical prompt. No reviewer gets additional
context, hints, or different framing.

### Anti-Pattern Injection

If `wiki/anti-patterns/` contains entries tagged with the current topology,
append them to the review prompt under "Known Risks for This Topology."
This is the ONLY wiki content that enters the review prompt.

## Review Dimensions

Each reviewer evaluates 5 dimensions with PASS / WARN / FAIL:

1. **Connection correctness** — dangling nodes, pin mismatches, bulk errors
2. **Bias soundness** — mirror ratios, gm/Id range, headroom margins
3. **Sizing consistency** — rationale equations match actual parameters
4. **Topology risks** — known traps (CMFB polarity, compensation, etc.)
5. **Spec achievability** — can specs be met with given sizing

## Report Structure

1. Reviewer status table (name, status, latency)
2. Consensus matrix (5 dimensions x N reviewers)
3. Divergence analysis (one subsection per disagreement, with each reviewer's
   full reasoning and an assessment of reasoning quality)
4. Action items (labeled [DIVERGENCE] or [CONSENSUS])
```

- [ ] **Step 2: Commit**

```bash
git add shared-references/review-protocol.md
git commit -m "docs: add cross-model review protocol shared reference"
```

---

### Task 5: Write checklist-schema.md

**Files:**
- Create: `shared-references/checklist-schema.md`

- [ ] **Step 1: Write checklist-schema.md**

Create `shared-references/checklist-schema.md`:

```markdown
# Checklist Schema

## Field Specification

Every checklist entry has 7 fields:

```yaml
<check_name>:
  description: "One-line description"
  method: structural | estimate | semantic
  severity: error | warn
  effort: lite | standard | intensive | exhaustive
  auto_checkable: true | false
  references: []
  how: >
    Procedure description
```

### Fields

- **description**: One sentence. What this check catches.
- **method**: How the check is performed.
  - `structural` — parseable from netlist text (connections, ratios, sizing)
  - `estimate` — computable from netlist + process assumptions (Vth~0.3V, Vdsat~0.1V)
  - `semantic` — requires design-intent reasoning (feedback polarity, compensation strategy)
- **severity**: What happens on failure.
  - `error` — blocks simulation (verifier must reject)
  - `warn` — flags concern, simulation proceeds
- **effort**: Minimum effort level that triggers this check. `lite` = always runs.
- **auto_checkable**: Metadata flag. `true` if a script could verify this
  programmatically. No automated engine exists yet — this is for future tooling.
- **references**: List of wiki entry IDs related to this check. Populated
  incrementally as the wiki grows. Empty list `[]` is valid.
- **how**: Step-by-step procedure for performing the check.

## Checklist Loading

### Explicit (preferred)

Architect sets the `checklists` field in each sub-block's `spec.yml`:

```yaml
checklists: [common, amplifier, folded-cascode, differential]
```

Verifier loads `checklists/<name>.yml` for each listed name.

### Fallback: Keyword Matching

If `checklists` field is absent, match the `block` field against this table:

| Keyword in block name | Checklists loaded |
|-----------------------|-------------------|
| ota, opamp, amplifier, gain | common, amplifier |
| folded, cascode (+ amplifier match) | common, amplifier, folded-cascode |
| differential, fully-differential | common, differential |
| comparator, strongarm, latch | common, comparator |
| mirror, bias, current-source | common, current-mirror |
| bandgap, reference | common, bandgap |
| pll, vco, oscillator | common, pll |
| adc, sar, pipeline, sigma-delta | common, adc |
| ldo, regulator | common, ldo |

`common.yml` is always loaded.

## Execution Modes

### Guided Mode (effort lite / standard)

Execute checklist items sequentially. Check each item, report result.
Appropriate for unfamiliar topologies.

### Expert Mode (effort intensive / exhaustive)

1. Agent performs holistic circuit review first — forms own assessment
2. THEN uses checklist as retrospective validation: "did my review miss
   anything on this list?"
3. Order: whole-first, parts-second

This preserves integrated understanding (Polanyi: decomposing into
subsidiary particulars destroys focal awareness of the whole).
```

- [ ] **Step 2: Commit**

```bash
git add shared-references/checklist-schema.md
git commit -m "docs: add checklist schema shared reference"
```

---

### Task 6: Write wiki-schema.md

**Files:**
- Create: `shared-references/wiki-schema.md`

- [ ] **Step 1: Write wiki-schema.md**

Create `shared-references/wiki-schema.md`:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add shared-references/wiki-schema.md
git commit -m "docs: add wiki schema shared reference"
```

---

### Task 7: Write handoff-contracts.md

**Files:**
- Create: `shared-references/handoff-contracts.md`

- [ ] **Step 1: Extract handoff contracts from current SKILL.md**

Read the "Handoff Contracts" section from the existing `skills/analog-agents/SKILL.md` (lines 329-398) and create `shared-references/handoff-contracts.md`:

```markdown
# Handoff Contracts

Every agent handoff must include the required payload. An incomplete handoff
is not a valid handoff — do not dispatch the next agent until all items are present.

## Top-level spec -> Architect (analog-decompose)

| Field | Required |
|-------|----------|
| Top-level `spec.yml` path | yes |
| User constraints | yes (can be empty) |
| Server name from `servers.yml` | yes |

Architect returns: `architecture.md` + `budget.md` + sub-block `spec.yml` files + `verification-plan.md` per sub-block + testbench netlists

## Architect -> Designer (analog-design, per sub-block)

| Field | Required |
|-------|----------|
| Sub-block `spec.yml` path | yes |
| Behavioral model `.va` path | yes |
| Interface constraints from `architecture.md` | yes |
| Netlist path or "create from scratch" | yes |
| `verifier-report.md` from last verifier run | yes (empty on first iteration) |
| Server name from `servers.yml` | yes |

Designer returns: `<block>.scs` + `rationale.md`

## Circuit + Testbench -> Verifier (analog-verify)

| Field | Required |
|-------|----------|
| `<block>.scs` path (designer's circuit) | yes |
| `testbench_<block>.scs` path (architect's testbench) | yes |
| Sub-block `spec.yml` path | yes |
| `verification-plan.md` path | yes |
| Verification level (L1 / L2 / L3) | yes |
| Server name from `servers.yml` | yes |

Verifier first reviews both files. Rejection routes to designer (circuit) or architect (testbench). If approved, runs simulation and returns `verifier-report.md`.

## Verifier FAIL -> Designer (loop)

Feedback must be actionable:
- Which spec, which corner, measured value, target, shortfall
- Suggested cause (e.g., "compensation cap too small")

Designer response must update `rationale.md` explaining what changed and why.

## 3x FAIL escalation -> Architect

Escalate with:
- All 3 verifier reports showing trajectory
- Designer's rationale explaining what was attempted
- Architect decides: revise sub-block spec, change topology, or escalate to user

## Verified sub-blocks -> Architect (analog-integrate)

| Field | Required |
|-------|----------|
| All sub-block `.scs` netlists (L2 pass) | yes |
| All sub-block `verifier-report.md` | yes |
| Server name from `servers.yml` | yes |

Architect returns: integration `verifier-report.md` with top-level specs
```

- [ ] **Step 2: Commit**

```bash
git add shared-references/handoff-contracts.md
git commit -m "docs: add handoff contracts shared reference"
```

---

## Phase 3: Checklist Expansion

### Task 8: Update existing checklists with new fields

**Files:**
- Modify: `checklists/common.yml`
- Modify: `checklists/folded-cascode.yml`
- Modify: `checklists/differential.yml`
- Modify: `checklists/amplifier.yml`

- [ ] **Step 1: Add new fields to common.yml**

For every entry in `checklists/common.yml`, append three fields. Example for the first entry:

```yaml
floating_nodes:
  description: "Every net must have at least one DC path to a supply or ground"
  method: structural
  severity: error
  effort: lite
  auto_checkable: true
  references: []
  how: >
    For each net in the subcircuit, check that it connects to at least
    2 device terminals. A net with only 1 connection is dangling.
    Exception: subcircuit ports (connected externally).
```

Apply the same pattern to all entries in common.yml:
- All existing entries get `effort: lite` (fundamental checks)
- `method: structural` entries get `auto_checkable: true`
- `method: semantic` entries get `auto_checkable: false`
- `method: estimate` entries get `auto_checkable: false`
- All get `references: []`

- [ ] **Step 2: Add new fields to folded-cascode.yml**

Same pattern. All entries get `effort: lite` except:
- `cascode_headroom_nmos`: `effort: standard` (estimate)
- `cascode_headroom_pmos`: `effort: standard` (estimate)
- `pmos_load_topology`: `effort: standard` (semantic)
- `bias_chain_tracking`: `effort: standard` (semantic)

- [ ] **Step 3: Add new fields to differential.yml**

Same pattern. All entries `effort: lite` except:
- `cmfb_polarity`: `effort: standard` (semantic)
- `cmfb_error_amp_bias`: `effort: standard` (semantic)
- `output_cm_vs_input_cm`: `effort: standard` (semantic)

- [ ] **Step 4: Add new fields to amplifier.yml**

Same pattern. All entries `effort: lite` except:
- `cascode_bias_voltage`: `effort: standard` (estimate)
- `output_headroom_stack`: `effort: standard` (estimate)
- `compensation`: `effort: standard` (semantic)

- [ ] **Step 5: Commit**

```bash
git add checklists/
git commit -m "feat: add effort/auto_checkable/references fields to existing checklists"
```

---

### Task 9: Create new checklist files

**Files:**
- Create: `checklists/comparator.yml`
- Create: `checklists/current-mirror.yml`
- Create: `checklists/bandgap.yml`
- Create: `checklists/pll.yml`
- Create: `checklists/adc.yml`
- Create: `checklists/ldo.yml`

- [ ] **Step 1: Write comparator.yml**

Create `checklists/comparator.yml` with 5 checks as specified in design spec section 5:
- `input_pair_symmetry` (error, lite, structural, auto_checkable: true)
- `latch_cross_coupling` (error, lite, structural, auto_checkable: true)
- `clock_gating` (error, lite, structural, auto_checkable: true)
- `precharge_completeness` (warn, standard, semantic, auto_checkable: false)
- `offset_estimation` (warn, intensive, estimate, auto_checkable: false)

Each entry must have full `how` field with the detailed procedure from the design spec. Do NOT use placeholder text — copy the exact procedures from spec section 5.

- [ ] **Step 2: Write current-mirror.yml**

Create `checklists/current-mirror.yml` with 3 checks:
- `ratio_accuracy` (error, lite, structural, auto_checkable: true, references: [])
- `compliance_headroom` (error, lite, estimate, auto_checkable: false, references: [])
- `channel_length_modulation` (warn, standard, estimate, auto_checkable: false, references: [strat-mixed-l])

Each with full `how` procedure from design spec.

- [ ] **Step 3: Write bandgap.yml**

Create `checklists/bandgap.yml` with 3 checks:
- `startup_circuit` (error, lite, semantic, auto_checkable: false)
- `bjt_area_ratio` (error, lite, structural, auto_checkable: true)
- `curvature_compensation` (warn, intensive, semantic, auto_checkable: false)

Each with full `how` procedure from design spec.

- [ ] **Step 4: Write pll.yml**

Create `checklists/pll.yml` with 4 checks:
- `loop_filter_component_values` (error, lite, structural, auto_checkable: true)
- `vco_gain_sign` (error, lite, semantic, auto_checkable: false)
- `lock_range_vs_spec` (warn, standard, estimate, auto_checkable: false)
- `phase_noise_budget` (warn, intensive, estimate, auto_checkable: false)

`how` fields:

```yaml
loop_filter_component_values:
  how: >
    Check that loop filter R and C values are physically reasonable.
    R > 0, C > 0. R typically 1k-100k, C typically 1p-100p for GHz PLLs.
    Second-order filter: verify C1 >> C2 (typically 5-10x).
    If charge pump current Icp is specified, verify Icp * R < VDD
    (loop filter voltage must stay in range).

vco_gain_sign:
  how: >
    Trace the PLL feedback loop polarity:
    1. Phase error increases -> charge pump sources current -> Vctrl rises
    2. Vctrl rises -> VCO frequency should INCREASE (positive Kvco)
    3. Higher frequency -> phase advances -> phase error DECREASES
    If Kvco is negative, the loop has positive feedback and won't lock.
    Check VCO schematic: does increasing Vctrl increase oscillation frequency?

lock_range_vs_spec:
  how: >
    Lock range = Kvco * Vctrl_swing.
    Vctrl_swing is limited by charge pump compliance and loop filter.
    Estimate: Vctrl_min ~ 0.2V, Vctrl_max ~ VDD-0.2V.
    Lock range must cover the specified frequency range with margin.
    Also check: is the initial VCO free-running frequency within lock range?

phase_noise_budget:
  how: >
    In-band phase noise dominated by charge pump and reference noise.
    Out-of-band dominated by VCO.
    Estimate VCO phase noise: L(f) ~ -10*log10(2*F*kT*R/P0) - 20*log10(f/f0)
    where F is noise figure, P0 is oscillation power, f0 is carrier.
    Check that total integrated jitter meets spec.
```

- [ ] **Step 5: Write adc.yml**

Create `checklists/adc.yml` with 4 checks:
- `sampling_capacitor_ktc` (error, lite, estimate, auto_checkable: false)
- `timing_budget_closure` (error, standard, estimate, auto_checkable: false)
- `reference_settling` (warn, standard, estimate, auto_checkable: false)
- `dnl_inl_from_component_matching` (warn, intensive, estimate, auto_checkable: false)

`how` fields:

```yaml
sampling_capacitor_ktc:
  how: >
    Thermal noise power on sampling cap: Pn = kT/C.
    For N-bit ADC with Vref range:
      LSB = Vref / 2^N
      Required: sqrt(kT/C) < LSB / (2 * target_sigma)
      Typically target 6-sigma: C > 4*k*T*(2*target_sigma/LSB)^2
    Example: 8-bit, 1V range, 6-sigma -> C > 4*1.38e-23*300*(6*2^8)^2 ~ 50fF
    If calculated C < spec'd C, OK. If not, flag noise budget violation.

timing_budget_closure:
  how: >
    Total conversion time must fit in 1/fs.
    For SAR: N_bits * (DAC_settling + comparator_decision + logic_delay) + sampling_time <= 1/fs
    For pipeline: stage_latency * throughput must meet fs
    Sum all sub-block timing budgets from architecture.md.
    If sum > 1/fs, flag — either speed up sub-blocks or reduce fs.

reference_settling:
  how: >
    DAC reference voltage must settle to < 0.5*LSB accuracy before
    the comparator evaluates. Settling time depends on reference buffer
    output impedance and DAC capacitive load.
    tau = Rout * Cdac, settling to 0.5*LSB requires ~N*ln(2)*tau.
    Check: is settling time < allocated time in timing budget?

dnl_inl_from_component_matching:
  how: >
    For capacitive DAC: DNL ~ sigma(deltaC/C) at MSB transition.
    sigma(deltaC/C) = Ac / sqrt(W*L) for MIM caps, or Ac/sqrt(C) for MOM.
    For 8-bit: need sigma < 0.5*LSB at MSB.
    If no matching data available, flag for Monte Carlo verification.
```

- [ ] **Step 6: Write ldo.yml**

Create `checklists/ldo.yml` with 4 checks:
- `loop_stability_with_load` (error, lite, semantic, auto_checkable: false)
- `dropout_headroom` (error, lite, estimate, auto_checkable: false)
- `load_transient_decoupling` (warn, standard, estimate, auto_checkable: false)
- `psrr_at_frequency` (warn, intensive, estimate, auto_checkable: false)

`how` fields:

```yaml
loop_stability_with_load:
  how: >
    LDO loop has at least two poles: error amp output and pass device gate.
    Output pole location depends on load current and output cap.
    At light load: output pole moves to low frequency -> phase margin drops.
    At heavy load: output pole moves up -> usually more stable.
    Check: does the compensation strategy handle min-to-max load range?
    ESR zero from output cap must be placed correctly for stability.

dropout_headroom:
  how: >
    Dropout = Vin_min - Vout.
    For PMOS pass device: dropout = |Vds_sat| at max load current.
    |Vds_sat| = sqrt(2*Imax / (up*Cox*W/L)) for strong inversion.
    Check: Vin_min - Vout >= |Vds_sat| with margin.
    If pass device is too narrow, dropout is too high at max load.

load_transient_decoupling:
  how: >
    During load step (e.g., 0->100mA in 1ns):
    Initial voltage droop = deltaI * ESR + deltaI * dt / Cout.
    Recovery time depends on loop bandwidth.
    Check: is Cout large enough for spec'd max droop?
    Check: is loop bandwidth fast enough for spec'd recovery time?
    Typical: BW > 10x load step frequency for <5% overshoot.

psrr_at_frequency:
  how: >
    LDO PSRR = error_amp_gain * gm_pass / gds_pass at low frequency.
    At high frequency, PSRR degrades above the loop bandwidth.
    Check: is loop bandwidth high enough to maintain PSRR at the
    frequencies that matter (e.g., switching regulator ripple at 1-10MHz)?
    If spec requires PSRR > 40dB at 1MHz, loop BW must be > 1MHz.
```

- [ ] **Step 7: Commit**

```bash
git add checklists/comparator.yml checklists/current-mirror.yml checklists/bandgap.yml
git add checklists/pll.yml checklists/adc.yml checklists/ldo.yml
git commit -m "feat: add 6 new topology checklists (comparator, mirror, bandgap, pll, adc, ldo)"
```

---

## Phase 4: Python Tools

### Task 10: Write review_bridge.py

**Files:**
- Create: `tools/review_bridge.py`

- [ ] **Step 1: Write review_bridge.py**

Create `tools/review_bridge.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add tools/review_bridge.py
git commit -m "feat: add cross-model review bridge tool"
```

---

### Task 11: Write wiki_ops.py

**Files:**
- Create: `tools/wiki_ops.py`

- [ ] **Step 1: Write wiki_ops.py**

Create `tools/wiki_ops.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add tools/wiki_ops.py
git commit -m "feat: add wiki operations tool"
```

---

## Phase 5: Skill SKILL.md Files

Split the monolithic SKILL.md into 8 independent skills. Each skill reads
shared-references/ for conventions and is self-contained.

### Task 12: Write analog-pipeline SKILL.md

**Files:**
- Create: `skills/analog-pipeline/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-pipeline/SKILL.md`. This is the lightweight orchestrator that replaces the original `skills/analog-agents/SKILL.md`. It contains:

- Frontmatter with the same trigger keywords as the original (OTA, ADC, PLL, etc.)
- "When to Use" section (same as original)
- Required Input section (spec.yml, servers.yml)
- Functional defaults table (same as original)
- Spec sheet format (same as original)
- Server configuration (same as original)
- The workflow diagram (same as original)
- Effort reading instructions (reference `shared-references/effort-contract.md`)
- Orchestration flow: sequences the 7 other skills, with effort-aware gating
- Iteration log format and "Who Writes What" (same as original)
- Project directory structure (same as original)
- Verification levels table (same as original)
- References to the 6 other domain skills (spectre, virtuoso, etc.)

Key difference from original: this SKILL.md does NOT contain agent prompt content (moved to `prompts/`), handoff contracts (moved to `shared-references/handoff-contracts.md`), or per-agent dispatch details (moved to individual skill SKILL.md files).

The orchestration flow section is:

```markdown
## Orchestration Flow

Read effort level per `shared-references/effort-contract.md`.

1. `/analog-wiki consult` (if wiki/ has entries) — get architecture references
2. `/analog-decompose` — architecture decomposition
3. **User gate**: confirm architecture before proceeding
4. `/analog-behavioral` (effort >= standard) — behavioral validation
5. For each sub-block:
   a. `/analog-design` — transistor-level netlist
   b. `/analog-review` (effort >= standard) — cross-model audit
   c. `/analog-verify` — simulation verification
   d. Loop (a)-(c) until convergence or iteration limit
6. `/analog-integrate` — integration verification
7. L3 sign-off via `/analog-verify` with level=L3
8. `/analog-wiki archive-project` (effort >= standard)
9. Reflection narrative (effort = exhaustive only)
```

This skill dispatches agents using prompts from `prompts/` and follows contracts from `shared-references/handoff-contracts.md`.

- [ ] **Step 2: Commit**

```bash
git add skills/analog-pipeline/SKILL.md
git commit -m "feat: add analog-pipeline skill (lightweight orchestrator)"
```

---

### Task 13: Write analog-decompose SKILL.md

**Files:**
- Create: `skills/analog-decompose/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-decompose/SKILL.md`. Contains:

- Frontmatter triggering on "decompose", "architecture", "budget", "sub-block"
- Description: Architect Phase 1 — decompose top-level spec into sub-blocks
- Inputs: spec.yml, user constraints, wiki consult results (optional)
- Outputs: architecture.md, budget.md, blocks/*/spec.yml, blocks/*/verification-plan.md, blocks/*/testbench_*.scs
- Instruction to read `shared-references/effort-contract.md` for effort level
- Instruction to call `/analog-wiki consult` at start if wiki exists
- Architect is responsible for setting `checklists` field in each sub-block spec.yml
- Reference to `prompts/architect-prompt.md` for the agent template
- Reference to `shared-references/handoff-contracts.md` for required payloads
- Architecture decomposition rules (from original SKILL.md lines 80-86 in architect-prompt.md)
- Spec derivation example (SAR ADC, from architect-prompt.md)
- Handoff acceptance criteria for Phase 1

Does NOT contain: Phase 2 or Phase 3 content (those are separate skills).

- [ ] **Step 2: Commit**

```bash
git add skills/analog-decompose/SKILL.md
git commit -m "feat: add analog-decompose skill (architect phase 1)"
```

---

### Task 14: Write analog-behavioral SKILL.md

**Files:**
- Create: `skills/analog-behavioral/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-behavioral/SKILL.md`. Contains:

- Frontmatter triggering on "behavioral", "verilog-a validation", "system simulation"
- Description: Architect Phase 2 — build behavioral models, validate architecture
- Effort gating: skip at lite, quick at standard, full at intensive, +sensitivity at exhaustive
- Inputs: architecture.md, blocks/*/spec.yml
- Outputs: blocks/*/behavioral.va, system simulation results
- Instructions for building Verilog-A models using veriloga skill
- Instructions for system-level simulation using evas-sim skill
- Gate: if behavioral sim fails top-level specs, return to analog-decompose
- Handoff acceptance criteria for Phase 2

- [ ] **Step 2: Commit**

```bash
git add skills/analog-behavioral/SKILL.md
git commit -m "feat: add analog-behavioral skill (architect phase 2)"
```

---

### Task 15: Write analog-design SKILL.md

**Files:**
- Create: `skills/analog-design/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-design/SKILL.md`. Contains:

- Frontmatter triggering on "design", "sizing", "netlist", "transistor"
- Description: Designer — produce transistor-level netlist for one sub-block
- Effort interaction: iteration limits (lite=2, standard=3, intensive=5, exhaustive=unlimited + auto-optimizer)
- Instruction to call `/analog-wiki consult` at start
- All content from `prompts/designer-prompt.md` that defines designer behavior:
  - Step 0 (load design skill)
  - Permissions
  - Inputs/Outputs
  - Netlist requirements
  - MOSFET sizing basics
  - Spectre netlist pitfalls
  - Sizing methodology (steps 1-10)
  - Optimizer usage
  - Custom post-sim hook
  - Margin report response protocol
  - Parameter sweep via batch simulation
  - Verifier dispatch
  - Acceptance criteria
- On completion: suggest running `/analog-review run`
- Reference to `shared-references/handoff-contracts.md`

- [ ] **Step 2: Commit**

```bash
git add skills/analog-design/SKILL.md
git commit -m "feat: add analog-design skill (designer)"
```

---

### Task 16: Write analog-verify SKILL.md

**Files:**
- Create: `skills/analog-verify/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-verify/SKILL.md`. Contains:

- Frontmatter triggering on "verify", "simulate", "spectre", "pre-sim review"
- Description: Verifier — pre-sim review + simulation + margin report
- Effort interaction:
  - Pre-sim check depth per effort level
  - Corner matrix per effort level (for L3)
  - Checklist execution mode: guided (lite/standard) vs expert (intensive/exhaustive)
- Checklist loading: read `checklists` from spec.yml, fallback keyword match per `shared-references/checklist-schema.md`
- All content from `prompts/verifier-prompt.md`:
  - Step 0 (load spectre skill)
  - Permissions
  - Pre-simulation review (circuit + testbench)
  - Verification levels (L1/L2/L3)
  - Report output structure
  - Verification order
  - Cross-validation
  - Parallel simulation patterns
  - Auto-dispatch next agent logic
  - Acceptance criteria
- Reference to `shared-references/handoff-contracts.md`

- [ ] **Step 2: Commit**

```bash
git add skills/analog-verify/SKILL.md
git commit -m "feat: add analog-verify skill (verifier)"
```

---

### Task 17: Write analog-integrate SKILL.md

**Files:**
- Create: `skills/analog-integrate/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-integrate/SKILL.md`. Contains:

- Frontmatter triggering on "integrate", "integration", "top-level verification"
- Description: Architect Phase 3 — replace behavioral models with verified netlists, run integration verification
- Effort interaction: corner matrix same as analog-verify
- Inputs: all verified sub-block .scs, verifier-reports, architecture.md
- Outputs: integration verifier-report.md
- Integration procedure:
  - Replace behavioral models one by one
  - Run top-level specs at each replacement
  - Final all-transistor verification
- Failure routing: identify responsible sub-block, send back to design loop
- Sign-off gate: L3 PVT required before delivery
- Virtuoso migration instructions (dispatch designer with migration task)
- Reference to `shared-references/handoff-contracts.md`

- [ ] **Step 2: Commit**

```bash
git add skills/analog-integrate/SKILL.md
git commit -m "feat: add analog-integrate skill (architect phase 3)"
```

---

### Task 18: Write analog-review SKILL.md

**Files:**
- Create: `skills/analog-review/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-review/SKILL.md`. Contains:

- Frontmatter triggering on "cross-model review", "review check", "analog-review"
- Description: Cross-model circuit audit with divergence analysis
- Reference to `shared-references/review-protocol.md` for discipline
- Reference to `shared-references/effort-contract.md` for effort gating
- Subcommands:
  - `/analog-review check` — calls `python3 tools/review_bridge.py check`
  - `/analog-review run <block-path>` — reads netlist + rationale + spec, optionally loads wiki anti-patterns, calls `python3 tools/review_bridge.py review`
  - `/analog-review report` — reads `verifier-reports/cross-model-review.md`
- Effort behavior table (lite=skip, standard=1, intensive=2, exhaustive=all)
- Configuration reference: `config/reviewers.yml` (copy from `config/reviewers.example.yml`)
- Wiki interaction: load anti-patterns for the current topology from `wiki/anti-patterns/`
- Report interpretation guide: divergence > consensus

- [ ] **Step 2: Commit**

```bash
git add skills/analog-review/SKILL.md
git commit -m "feat: add analog-review skill (cross-model audit)"
```

---

### Task 19: Write analog-wiki SKILL.md

**Files:**
- Create: `skills/analog-wiki/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/analog-wiki/SKILL.md`. Contains:

- Frontmatter triggering on "wiki", "knowledge", "consult", "archive"
- Description: Knowledge graph operations — query, add, relate, archive
- Polanyi principle statement: narratives over rules, derived_from provenance
- Reference to `shared-references/wiki-schema.md` for entry format
- Reference to `shared-references/effort-contract.md` for write gating
- Subcommands with examples:
  - `/analog-wiki consult <block-type>` — calls `python3 tools/wiki_ops.py consult <type>`
  - `/analog-wiki add <type>` — interactive: ask name, tags, content, then call tool
  - `/analog-wiki relate <id1> <rel> <id2>` — calls tool
  - `/analog-wiki archive-project` — reads iteration-log.yml, calls tool, prompts architect for narrative.md
  - `/analog-wiki deprecate <id>` — calls tool
  - `/analog-wiki search <query>` — calls tool
- Effort behavior table
- Seeding instructions: how to populate initial entries from existing knowledge (cmfb.md, designer-prompt.md sizing rules, etc.)

- [ ] **Step 2: Commit**

```bash
git add skills/analog-wiki/SKILL.md
git commit -m "feat: add analog-wiki skill (knowledge graph)"
```

---

## Phase 6: Cleanup & Finalization

### Task 20: Remove old skill directory and seed initial wiki entries

**Files:**
- Remove: `skills/analog-agents/` (entire directory)
- Create: `wiki/anti-patterns/diode-load-cmfb-trap.yml`
- Create: `wiki/anti-patterns/vcm-half-vdd-pmos-input.yml`
- Create: `wiki/strategies/mixed-l-for-matching.yml`
- Modify: `wiki/index.yml`

- [ ] **Step 1: Remove old skill directory**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
git rm -r skills/analog-agents/
```

- [ ] **Step 2: Seed wiki with entries from existing knowledge**

Extract knowledge already in `shared-references/cmfb.md` and `prompts/designer-prompt.md` into wiki entries.

Create `wiki/anti-patterns/diode-load-cmfb-trap.yml`:

```yaml
id: anti-001
type: anti-pattern
name: "Diode-Load CMFB Kills DM Gain"
tags: [cmfb, diode-load, gain, ota, fully-differential]
process_nodes: [28nm, 65nm, 180nm]

content:
  description: >
    If the CMFB error amp uses diode-connected loads and its output directly
    connects to the main OTA's PMOS load gate (a high-impedance node), the
    diode converts that node to low impedance. The PMOS load becomes effectively
    diode-connected, and DM gain collapses.
  failure_mechanism: >
    Diode-connected load impedance ~ 1/gm. Connected to high-Z node (cascode
    output) that sets signal gain. Low impedance dominates, gain drops from
    ~50dB to <10dB.
  measured_impact: "23 dB -> 2.6 dB on a 5T FD OTA"
  fix: "Use mirror-load error amp, or buffer/AC-couple the diode-load output"

derived_from: []
confidence: verified
source: "shared-references/cmfb.md"
created: 2026-04-16
updated: 2026-04-16
```

Create `wiki/anti-patterns/vcm-half-vdd-pmos-input.yml`:

```yaml
id: anti-002
type: anti-pattern
name: "Vcm = VDD/2 With PMOS Input Pair"
tags: [vcm, pmos-input, headroom, folded-cascode, ota]
process_nodes: [28nm, 65nm]

content:
  description: >
    Setting input common-mode to VDD/2 with a PMOS input pair leaves almost
    no headroom for the tail current source. The tail transistor enters triode
    and the circuit fails.
  failure_mechanism: >
    PMOS input: net_tail = Vcm + |Vsg|. At VDD/2 = 0.45V with |Vsg| ~ 0.4V,
    net_tail = 0.85V. |Vds_tail| = VDD - net_tail = 0.9 - 0.85 = 0.05V.
    Tail is in triode.
  fix: "PMOS input: Vcm < 0.3*VDD. NMOS input: Vcm > 0.7*VDD."

derived_from: []
confidence: verified
source: "prompts/designer-prompt.md, shared-references/cmfb.md"
created: 2026-04-16
updated: 2026-04-16
```

Create `wiki/strategies/mixed-l-for-matching.yml`:

```yaml
id: strat-001
type: strategy
name: "Mixed-L Strategy for Matching and Gain"
tags: [sizing, matching, channel-length, mirror, cascode, gain]
process_nodes: [28nm, 65nm]

content:
  description: >
    Use short L (e.g., 60nm in 28nm process) only where speed matters —
    typically the input pair. Use longer L (2-4x minimum) for bias mirrors,
    current sources, and cascodes.
  key_tradeoffs:
    - "Speed vs matching: short L is faster but worse matching"
    - "Short L everywhere causes excessive CLM, degraded mirror accuracy"
  benefits:
    - "Better matching on mirrors and current sources"
    - "Lower gds -> higher intrinsic gain on cascode stacks"
    - "More stable DC equilibria in folded structures"
  when_to_use: "Always, unless the entire circuit is speed-critical"

derived_from: []
confidence: verified
source: "prompts/designer-prompt.md step 8"
created: 2026-04-16
updated: 2026-04-16
```

- [ ] **Step 3: Update wiki/index.yml**

```yaml
entries:
  anti-001:
    path: anti-patterns/diode-load-cmfb-trap.yml
    type: anti-pattern
    summary: "Diode-load CMFB kills DM gain on high-Z nodes"
  anti-002:
    path: anti-patterns/vcm-half-vdd-pmos-input.yml
    type: anti-pattern
    summary: "Vcm=VDD/2 with PMOS input pair collapses tail headroom"
  strat-001:
    path: strategies/mixed-l-for-matching.yml
    type: strategy
    summary: "Use longer L for mirrors/cascodes, short L only for input pair"
```

- [ ] **Step 4: Seed edges.jsonl**

```jsonl
{"from": "strat-001", "to": "anti-002", "rel": "prevents", "note": "longer L on mirrors reduces Vth sensitivity but mixed-L is orthogonal to Vcm choice"}
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove old monolithic skill, seed initial wiki entries"
```

---

### Task 21: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README.md**

Update the README to reflect the v2 structure. Key changes:

1. Update "What's Inside" section to show new directory structure
2. Add "Skills" section listing all 8 skills with one-line descriptions
3. Add "Knowledge Graph" section explaining wiki/ and /analog-wiki commands
4. Add "Cross-Model Review" section explaining /analog-review and reviewers.yml
5. Add "Effort Levels" section with the 4-tier table
6. Add "Checklists" section listing all 10 topology files
7. Update "Installation" section:
   - Step 2 changes: symlink individual skills or analog-pipeline
   - Add step for reviewers.yml setup
8. Update "What Is This?" to mention the 4 new capabilities
9. Keep all existing philosophy, workflow diagram, and technical content

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for v2 structure"
```

---

### Task 22: Update .gitignore and hooks

**Files:**
- Modify: `.gitignore`
- Modify: `hooks/session-start`

- [ ] **Step 1: Update .gitignore**

Add these lines to `.gitignore`:

```
wiki/projects/
config/reviewers.yml
config/effort.yml
```

- [ ] **Step 2: Update session-start hook**

The session-start hook currently reads `skills/analog-agents/SKILL.md`. Update it to read `skills/analog-pipeline/SKILL.md` instead.

In `hooks/session-start`, change:

```bash
SKILL_CONTENT=$(cat "${PLUGIN_ROOT}/skills/analog-agents/SKILL.md" 2>/dev/null \
  || echo "Warning: analog-agents SKILL.md not found")
```

to:

```bash
SKILL_CONTENT=$(cat "${PLUGIN_ROOT}/skills/analog-pipeline/SKILL.md" 2>/dev/null \
  || echo "Warning: analog-pipeline SKILL.md not found")
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore hooks/session-start
git commit -m "chore: update gitignore and session-start hook for v2 paths"
```

---

### Task 23: Final verification

- [ ] **Step 1: Verify directory structure**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
find . -type f -not -path './.git/*' | sort
```

Verify:
- 8 skill directories under `skills/`, each with SKILL.md
- No `skills/analog-agents/` directory
- `prompts/` has 4 prompt files
- `shared-references/` has 6 files (5 new + cmfb.md)
- `checklists/` has 10 files (4 existing + 6 new)
- `wiki/` has index.yml, edges.jsonl, and 3 seed entries
- `config/` has servers.example.yml, reviewers.example.yml, effort.yml
- `tools/` has review_bridge.py and wiki_ops.py
- `hooks/` unchanged except session-start path update

- [ ] **Step 2: Verify no broken references**

```bash
# Check that prompts/ files exist
ls prompts/architect-prompt.md prompts/designer-prompt.md prompts/verifier-prompt.md prompts/librarian-prompt.md

# Check shared-references
ls shared-references/effort-contract.md shared-references/review-protocol.md shared-references/checklist-schema.md shared-references/wiki-schema.md shared-references/handoff-contracts.md shared-references/cmfb.md

# Check wiki seed entries
python3 -c "import yaml; print(yaml.safe_load(open('wiki/index.yml')))"

# Check review_bridge.py imports
python3 -c "import tools.review_bridge" 2>&1 || python3 tools/review_bridge.py --help

# Check wiki_ops.py imports
python3 tools/wiki_ops.py --help
```

- [ ] **Step 3: Run wiki_ops smoke test**

```bash
cd /Users/tokenzhang/Documents/Hermes/analog-agents
python3 tools/wiki_ops.py search "cmfb"
python3 tools/wiki_ops.py consult "ota"
```

Expected: search returns anti-001 (diode-load CMFB trap), consult returns relevant entries.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: final verification fixes"
```

---

## Summary

| Phase | Tasks | What it produces |
|-------|-------|-----------------|
| 1. Scaffolding | 1-2 | v2 directory structure, configs |
| 2. Shared References | 3-7 | 5 convention documents |
| 3. Checklists | 8-9 | 10 topology checklists (4 updated + 6 new) |
| 4. Python Tools | 10-11 | review_bridge.py + wiki_ops.py |
| 5. Skill Files | 12-19 | 8 SKILL.md files |
| 6. Cleanup | 20-23 | Remove old skill, seed wiki, update README |

Total: 23 tasks. Each task is independently committable. Phases can be
parallelized: Phase 2 and 3 are independent. Phase 4 is independent of
Phase 2/3. Phase 5 depends on Phase 1-2. Phase 6 depends on all prior phases.

Parallelization opportunities for subagent dispatch:
- Tasks 3, 4, 5, 6, 7 (all shared references) — fully parallel
- Tasks 8 and 9 (checklists) — parallel with each other
- Tasks 10 and 11 (Python tools) — parallel with each other
- Tasks 12-19 (8 skill files) — all parallel (each is self-contained)
- Task 20, 21, 22 — sequential (cleanup depends on everything)
