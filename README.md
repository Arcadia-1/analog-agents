<p align="center">
  <img src="https://img.shields.io/badge/analog--agents-spec%20in%2C%20verified%20schematic%20out-00d4aa?style=for-the-badge&labelColor=0a0a0a" alt="analog-agents"/>
</p>

<p align="center">
  <strong>Agentic analog front-end design — spec in, verified schematic out.</strong><br/>
  Four specialized agents. One convergence loop. Zero ambiguity.
</p>

<p align="center">
  <!-- GitHub -->
  <a href="https://github.com/Arcadia-1/analog-agents/stargazers"><img src="https://img.shields.io/github/stars/Arcadia-1/analog-agents?style=flat-square&logo=github&color=f5c542" alt="GitHub Stars"/></a>
  <a href="https://github.com/Arcadia-1/analog-agents/network/members"><img src="https://img.shields.io/github/forks/Arcadia-1/analog-agents?style=flat-square&logo=github&color=8b949e" alt="GitHub Forks"/></a>
  <a href="https://github.com/Arcadia-1/analog-agents/issues"><img src="https://img.shields.io/github/issues/Arcadia-1/analog-agents?style=flat-square&logo=github&color=3fb950" alt="Open Issues"/></a>
  <a href="https://github.com/Arcadia-1/analog-agents/commits/main"><img src="https://img.shields.io/github/last-commit/Arcadia-1/analog-agents?style=flat-square&logo=git&color=3fb950" alt="Last Commit"/></a>
</p>

<p align="center">
  <!-- Built for -->
  <img src="https://img.shields.io/badge/built%20for-agentic%20design-ff6b35?style=flat-square" alt="Built for Agentic Design"/>
  <img src="https://img.shields.io/badge/works%20with-any%20coding%20agent-blueviolet?style=flat-square" alt="Any Coding Agent"/>
  <img src="https://img.shields.io/badge/format-skill%20library-64748b?style=flat-square" alt="Skill Library"/>
</p>

<p align="center">
  <!-- Tech stack -->
  <img src="https://img.shields.io/badge/Spectre-simulator-1e3a5f?style=flat-square&logo=cadence&logoColor=white" alt="Spectre"/>
  <img src="https://img.shields.io/badge/Virtuoso-schematic-0057a8?style=flat-square" alt="Virtuoso"/>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/SPICE%2FSpectre-netlist-orange?style=flat-square" alt="SPICE Netlist"/>
  <img src="https://img.shields.io/badge/PVT-corner%20aware-9b59b6?style=flat-square" alt="PVT Corners"/>
</p>

<p align="center">
  <!-- License & contribution -->
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e?style=flat-square" alt="MIT License"/></a>
  <a href="https://github.com/Arcadia-1/analog-agents/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square" alt="PRs Welcome"/></a>
  <img src="https://img.shields.io/badge/skill%20library-markdown%20only-64748b?style=flat-square" alt="No Runtime Dependencies"/>
</p>

---

## What Is This?

**analog-agents** is an agentic skill framework that brings real analog engineering discipline to AI-assisted circuit design. It works with any coding agent that supports skill files.

Most AI tools treat analog design like software: write some code, run some tests, ship it. That misses everything that makes analog hard — the architecture tradeoffs, the spec budgeting across sub-blocks, the PVT corner matrix, the sizing rationale, the convergence loop between design and simulation, the sign-off gate before delivering a verified schematic.

analog-agents doesn't miss any of that.

**v2** adds four new capabilities: a **design knowledge graph** that captures anti-patterns, strategies, and topology lessons as a searchable wiki; **cross-model review** that dispatches circuit audits to external models (minimax, qwen, kimi, glm) for independent verification; **topology-specific checklists** that enforce mandatory checks per circuit type; and **effort levels** that scale verification depth from lite to exhaustive.

It dispatches four agents — a **librarian**, an **architect**, a **designer**, and a **verifier** — with distinct roles, strict permissions, and defined handoff contracts. The librarian surveys existing Virtuoso libraries. The architect decomposes the system, writes testbenches, and validates the architecture with behavioral models. The designer produces transistor-level netlists. The verifier reviews both the circuit and testbench before simulating. They iterate until every spec passes with margin.

```
top-level spec.yml
        |
        |-- librarian (background, optional)
        |     survey existing Virtuoso library
        |     output: survey-report.md + library-index.md
        |
        v
  architect agent (Phase 1: decompose)
  |-- select architecture, tradeoff analysis
  |-- derive sub-block specs + budget allocation
  |-- write testbenches + verification plans
  |-- output: architecture.md + budget.md + blocks/*/spec.yml + testbenches
        |
        v
  architect agent (Phase 2: behavioral validation)
  |-- Verilog-A model per sub-block
  |-- system-level behavioral simulation
  |-- confirm top-level specs achievable
        |
        v
  +------------------------------------------------------+
  |  For each sub-block:                                 |
  |                                                      |
  |    designer (circuit) + architect (testbench)        |
  |         |                                            |
  |         v                                            |
  |    verifier: review both --> approve? --> simulate   |
  |         |                       |                    |
  |         FAIL                 REJECT                  |
  |         |                (no sim run)                |
  |         v                    |                       |
  |    designer revises     architect or designer fixes  |
  |                                                      |
  |    (max 3 design iterations per sub-block)           |
  +------------------------------------------------------+
        |
        v
  architect agent (Phase 3: integration)
  |-- replace behavioral models with verified netlists
  |-- top-level integration verification
        |
        v
  sign-off gate --> L3 PVT required
        |
        v
  verified schematic delivered
```

## The Four Agents

### Librarian
Surveys and manages Virtuoso design libraries. Runs in the background.

- Scans Virtuoso libraries, exports netlists, identifies circuit topologies
- Produces `survey-report.md` (detailed) and `library-index.md` (quick-reference)
- Assesses reusability of existing blocks against current project specs
- Can write back to Virtuoso: create schematics from netlists, update parameters
- Uses `virtuoso-bridge` for all Virtuoso interactions
- Long-running — dispatched in background, parallel with architect

### Architect
Owns the system architecture and all testbenches.

- Selects architecture (e.g., SAR vs pipeline vs sigma-delta) with tradeoff analysis
- Breaks system into sub-blocks, derives each sub-block's spec from top-level requirements
- Allocates power/noise/timing budgets (must close before proceeding)
- Builds Verilog-A behavioral models to validate architecture before transistor design
- **Writes all testbenches** — the designer does not write testbenches
- Defines verification plans — what to verify, which analyses, what extraction method
- Integrates verified sub-blocks and runs system-level verification
- Writes `lessons_learned` at project completion for future design knowledge

### Designer
Owns the circuit netlist. Thinks in small-signal equations. Shows their math.

- Reads sub-block `spec.yml`, produces `<block>.scs` + `rationale.md`
- Every `.param` value comes with a design equation
- Responds to verifier failures with calculated adjustments, not guesses
- Can invoke the **optimizer** skill when specs conflict or margins are tight
- Writes **custom post-simulation hooks** per block to track what matters during iteration
- Delivers verified netlist ready for next design stage

### Verifier
Reviews before simulating. Never touches the netlist. Always quantifies.

- **Reviews both circuit netlist and testbench before simulating** — catches errors before they burn simulation cycles
- Circuit problem → rejects, routes feedback to designer
- Testbench problem → rejects, routes feedback to architect
- If both are sound → runs Spectre, writes `margin-report.md`
- Every result includes: measured value, target, margin, corner
- Every failure includes: shortfall, likely cause, suggested fix

## Verification Levels

Escalate verification deliberately. Don't run full PVT corners just to check if the circuit turns on.

| Level | When | What Runs | Purpose |
|-------|------|-----------|---------|
| **L1 Functional** | Every iteration (default) | `.op` + `.tran`/`.ac` at TT/27C | Does the circuit perform its basic function? |
| **L2 Performance** | When L1 passes | All spec analyses at TT | Do all spec targets pass at typical corner? |
| **L3 Robustness** | Before sign-off (mandatory) | Full corner matrix | Does the design hold across process/voltage/temperature? |

L1 is not just a DC operating point check. It confirms the circuit does what it's supposed to do: an ADC produces output codes, a comparator resolves correctly, a bootstrap switch tracks the input, an amplifier amplifies.

## Pre-Simulation Review

The verifier reviews both the circuit netlist and testbench **before** running any simulation:

1. **Circuit review** — missing connections? pin mismatches? parameterization errors?
2. **Testbench review** — correct stimulus node? proper load? right analysis type? common pitfalls (PSRR/CMRR/PM setup)?

If either has issues, the verifier rejects without simulating and routes feedback to the responsible agent. This saves simulation time and catches errors that would otherwise produce misleading results.

## Iteration Tracking

Every design run produces `iteration-log.yml` with:

- Per-sub-block iteration history (what parameters changed, why)
- Pre-simulation rejections by verifier
- Optimizer invocation records
- Lessons learned at project completion

Parameter changes are auto-recorded by hooks whenever a netlist is modified. The architect writes `lessons_learned` at sign-off — these insights make the next project's architect smarter.

## Designer's Custom Hooks

At the start of each block's design, the designer writes `blocks/<name>/post-sim-hook.py` — a custom script that runs automatically after every simulation for that block. The designer decides what it does: plot optimization trends, track parameter sensitivities, flag operating point drift. It's the designer's tool — modified, rewritten, or discarded as iteration focus shifts.

## Spec Sheet

The `spec.yml` is the central contract. Every agent reads it. Nothing ships without it.

```yaml
block: folded-cascode-ota
process: tsmc28nm
supply: 1.8V

specs:
  dc_gain:      { min: 60,  unit: dB       }
  ugbw:         { min: 100, unit: MHz      }
  phase_margin: { min: 45,  unit: deg      }
  noise_input:  { max: 5,   unit: nV/rtHz  }
  power:        { max: 1.0, unit: mW       }

corners:                          # used for L3 PVT
  - { name: tt_27c,   process: tt, voltage: 1.8,  temp: 27  }
  - { name: ss_125c,  process: ss, voltage: 1.62, temp: 125 }
  - { name: ff_m40c,  process: ff, voltage: 1.98, temp: -40 }
```

## Simulation Hooks

After every Spectre run, a `PostToolUse` hook fires automatically:

1. Finds the most recent PSF output directory
2. Parses results via `virtuoso-bridge`
3. Checks every value against `spec.yml` targets
4. Appends a timestamped entry to `sim-log.yml`
5. Injects a margin table into context — the agent sees pass/fail immediately
6. Runs designer's custom per-block hook (if present)

After every netlist edit, a separate hook:
1. Runs `spectre -check` for syntax validation
2. Diffs `.param` changes and records them to `iteration-log.yml`

## Multi-Server Support

Teams with dedicated EDA infrastructure can map roles to separate servers and accounts:

```yaml
# config/servers.yml
servers:
  design-server:
    host: eda01.company.com
    user: designer_bot
    key: ~/.ssh/id_design
    tools: [virtuoso, spectre]

  sim-server:
    host: hpc02.company.com
    user: sim_bot
    key: ~/.ssh/id_sim
    tools: [spectre]

role_mapping:
  librarian: design-server    # needs Virtuoso read/write
  architect: design-server
  designer: design-server     # read/write Virtuoso
  verifier: sim-server        # simulation only
```

Single-server teams: just define a `default` entry and skip `role_mapping`.

## Installation

**1. Clone the repo**

```bash
git clone https://github.com/Arcadia-1/analog-agents.git
```

**2. Register skills with your coding agent**

For the full pipeline (recommended):
```bash
ln -s /path/to/analog-agents/skills/analog-pipeline ~/.claude/skills/analog-pipeline
```

Or symlink individual skills as needed:
```bash
ln -s /path/to/analog-agents/skills/analog-design ~/.claude/skills/analog-design
ln -s /path/to/analog-agents/skills/analog-verify ~/.claude/skills/analog-verify
# ... etc
```

**3. (Optional) Enable cross-model review**

```bash
cp config/reviewers.example.yml config/reviewers.yml
# Edit with your API keys for minimax, qwen, kimi, glm
```

**4. Configure your servers**

```bash
cp config/servers.example.yml config/servers.yml
# Edit with your host, user, and SSH key
```

**5. Create a spec sheet in your project directory**

```bash
cat > spec.yml << 'EOF'
block: my-ota
process: tsmc28nm
supply: 1.8V
specs:
  dc_gain:      { min: 60, unit: dB  }
  phase_margin: { min: 45, unit: deg }
  power:        { max: 1.0, unit: mW }
EOF
```

**6. Invoke the skill**

```
Use the analog-pipeline skill. Design an OTA for spec.yml.
```

## What's Inside

```
analog-agents/
├── skills/
│   ├── analog-pipeline/          # Full design pipeline orchestrator
│   ├── analog-decompose/         # Architecture decomposition and budgeting
│   ├── analog-behavioral/        # Behavioral model validation
│   ├── analog-design/            # Transistor-level netlist design
│   ├── analog-verify/            # Pre-sim review and simulation
│   ├── analog-integrate/         # Integration verification and sign-off
│   ├── analog-review/            # Cross-model circuit audit
│   ├── analog-wiki/              # Design knowledge graph
│   ├── analog-learn/             # Interactive design teaching companion
│   ├── analog-explore/           # Design space exploration
│   └── analog-audit/             # Static netlist audit service
├── prompts/
│   ├── architect-prompt.md       # Architect agent template
│   ├── designer-prompt.md        # Designer agent template
│   ├── librarian-prompt.md       # Librarian agent template
│   └── verifier-prompt.md        # Verifier agent template
├── shared-references/
│   ├── checklist-schema.md       # Checklist format spec
│   ├── cmfb.md                   # CMFB design reference
│   ├── effort-contract.md        # Effort level definitions
│   ├── handoff-contracts.md      # Agent handoff protocols
│   ├── review-protocol.md        # Cross-model review protocol
│   └── wiki-schema.md            # Wiki entry schema
├── checklists/                   # Topology-specific verification checklists
│   ├── common.yml                # Universal checks (all circuits)
│   ├── amplifier.yml             # OTA / amplifier checks
│   ├── folded_cascode.yml        # Folded cascode specific
│   ├── differential.yml          # Fully-differential checks
│   ├── comparator.yml            # Comparator checks
│   ├── adc.yml                   # ADC checks
│   ├── current-mirror.yml        # Current mirror checks
│   ├── bandgap.yml               # Bandgap reference checks
│   ├── ldo.yml                   # LDO regulator checks
│   └── pll.yml                   # PLL checks
├── wiki/                         # Design knowledge graph
│   ├── index.yml                 # Entry index
│   ├── edges.jsonl               # Relationship edges
│   ├── anti-patterns/            # Known failure modes
│   ├── strategies/               # Design strategies
│   ├── topologies/               # Topology knowledge
│   └── corner-lessons/           # PVT corner lessons
├── config/
│   ├── servers.example.yml       # Multi-server config template
│   ├── reviewers.example.yml     # Cross-model reviewer config
│   └── effort.yml                # Default effort level
├── tools/
│   ├── review_bridge.py          # Cross-model review dispatcher
│   └── wiki_ops.py               # Wiki search/add/consult operations
├── hooks/
│   ├── hooks.json                # Hook event registration
│   ├── session-start             # Inject skill + check bridge + read spec on startup
│   ├── post-sim.sh               # Triggered after every Spectre run
│   ├── post_sim_check.py         # PSF parser -> spec checker -> sim-log writer
│   ├── post-netlist-check.sh     # Syntax check + param change recording
│   └── session-summary.sh        # End-of-session summary
└── docs/specs/                   # Design documents
```

## Skills

| Skill | Description |
|-------|-------------|
| `/analog-pipeline` | Full design pipeline orchestrator |
| `/analog-decompose` | Architecture decomposition and budgeting |
| `/analog-behavioral` | Behavioral model validation |
| `/analog-design` | Transistor-level netlist design |
| `/analog-verify` | Pre-sim review and simulation |
| `/analog-integrate` | Integration verification and sign-off |
| `/analog-review` | Cross-model circuit audit (minimax, qwen, kimi, glm) |
| `/analog-wiki` | Design knowledge graph |
| `/analog-learn` | Interactive design teaching companion (no EDA needed) |
| `/analog-explore` | Design space exploration with hand calculations (no EDA needed) |
| `/analog-audit` | Static netlist audit service (no EDA needed) |

## Effort Levels

Scale verification depth to match your design phase:

| Level | When | Scope |
|-------|------|-------|
| **lite** | Quick sanity check | DC op + basic function at TT only |
| **standard** | Normal design iteration | L1 + L2 at TT, key specs |
| **intensive** | Pre-tapeout review | Full L1-L3 with PVT corners |
| **exhaustive** | Sign-off | All corners, Monte Carlo, mismatch, cross-model review |

See `shared-references/effort-contract.md` for full definitions.

## Cross-Model Review

Independent circuit audits dispatched to external models for a second opinion. Supported models: **minimax**, **qwen**, **kimi**, **glm**.

The review bridge (`tools/review_bridge.py`) sends the netlist, spec, and rationale to one or more external models and collects structured findings. Each reviewer scores independently, and findings are merged into a unified report.

Copy `config/reviewers.example.yml` to `config/reviewers.yml` and add your API keys to enable cross-model review.

## Knowledge Graph

The `wiki/` directory is a persistent design knowledge base — anti-patterns, strategies, topology lessons, and corner-case gotchas captured as structured YAML entries with typed edges between them.

Following Polanyi's principle, the wiki captures tacit design knowledge that experienced engineers carry but rarely document — the kind of knowledge that prevents a team from repeating the same mistakes across projects.

Use the `/analog-wiki` skill to search, consult, and contribute to the knowledge graph.

## Philosophy

**Spec-driven, not vibe-driven.** Every design decision traces back to a quantitative target. The spec sheet is not documentation — it is the contract.

**Survey before you design.** The librarian scans existing libraries for reusable blocks before anyone writes a new transistor. Don't redesign what already exists.

**Architect before designer.** Don't jump to transistors before validating the architecture. Decompose, budget, model behaviorally, then design.

**Review before you simulate.** The verifier checks both circuit and testbench before running Spectre. A bad testbench produces bad numbers — catch it before it wastes simulation time.

**Margin, not just pass/fail.** A design that passes at TT/27C and fails at SS/125C is not done. Verification reports numbers, not verdicts.

**Rationale is a deliverable.** A netlist without hand-calc justification is a guess. The designer documents the equation behind every parameter.

**Three iterations maximum.** If the design hasn't converged after three designer-verifier loops, the problem is topology, not tuning. Escalate to architect or human.

**Agents build their own tools.** Predefined templates limit what agents can do. The designer writes custom hooks, scripts, and plots as needed — no fixed formats.

**Learn from every project.** Iteration logs and lessons learned accumulate design knowledge that makes the next project's architect smarter.

## Related Skills

analog-agents orchestrates workflow. For domain knowledge:

| Skill | What It Does |
|-------|-------------|
| `spectre` | Run Spectre simulations from a netlist file |
| `virtuoso` | Cadence Virtuoso schematic operations via virtuoso-bridge |
| `veriloga` | Write Verilog-A behavioral models |
| `evas-sim` | Behavioral simulation with EVAS Verilog-A simulator |
| `sar-adc` | SAR ADC architecture, design, and budgeting |
| `optimizer` | Bayesian optimization of circuit parameters |

## License

MIT — see [LICENSE](LICENSE)
