<p align="center">
  <img src="https://img.shields.io/badge/analog-agents-0a0a0a?style=for-the-badge&labelColor=0a0a0a&color=00d4aa" alt="analog-agents"/>
</p>

<p align="center">
  <strong>AI-native analog IC design — spec in, silicon out.</strong><br/>
  Two specialized agents. One convergence loop. Zero ambiguity.
</p>

<p align="center">
  <a href="https://claude.ai/code"><img src="https://img.shields.io/badge/Claude%20Code-native-blueviolet?style=flat-square" alt="Claude Code"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"/></a>
  <a href="https://github.com/Arcadia-1/analog-agents/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square" alt="PRs Welcome"/></a>
</p>

---

## What Is This?

**analog-agents** is a skill library for Claude Code that brings real analog engineering discipline to AI-assisted circuit design.

Most AI tools treat analog design like software: write some code, run some tests, ship it. That misses everything that makes analog hard — the spec sheet with quantitative targets, the PVT corner matrix, the sizing rationale, the convergence loop between design and simulation, the sign-off gate before tape-out.

analog-agents doesn't miss any of that.

It dispatches two agents — a **designer** and a **verifier** — with distinct roles, strict permissions, and defined handoff contracts. They iterate until every spec passes with margin. Then the designer tapes out to Virtuoso.

```
spec.yml  ──►  designer agent
                    │
           ┌────────┴────────┐
           ▼                 ▼
     verifier agent    (documents rationale)
           │
           ▼
     all specs pass?
     ├── NO  → margin report → designer → revise → repeat
     └── YES → sign-off gate (L3 PVT required)
                    │
                    ▼
          designer: tape-out → Virtuoso
```

## The Two Agents

### 🎯 Designer
Owns the netlist. Thinks in small-signal equations. Shows their math.

- Reads `spec.yml`, produces `<block>.scs` + `rationale.md`
- Every `.param` value comes with a design equation
- Responds to verifier failures with calculated adjustments, not guesses
- Handles tape-out to Virtuoso after sign-off

### 🔬 Verifier
Owns the simulation. Never touches the netlist. Always quantifies.

- Writes testbench, runs Spectre, writes `margin-report.md`
- Every result includes: measured value, target, margin, corner
- Every failure includes: shortfall, likely cause, suggested fix
- Three verification levels — from quick functional check to full PVT matrix

## Verification Levels

Don't run full PVT corners just to check if the circuit turns on. Escalate deliberately.

| Level | When | What Runs | Purpose |
|-------|------|-----------|---------|
| **L1 Functional** | Every iteration (default) | `.op` at TT/27°C/nominal | Does the circuit operate? Are transistors in saturation? |
| **L2 Spec** | When L1 passes | AC + noise + tran + DC at TT | Do all spec targets pass at typical corner? |
| **L3 PVT** | Before tape-out (mandatory) | Full corner matrix | Does the design hold across process/voltage/temperature? |

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

No manual PSF parsing. No wondering if that last simulation passed.

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
  designer: design-server   # read/write Virtuoso
  verifier: sim-server      # simulation only
```

Single-server teams: just define a `default` entry and skip `role_mapping`.

## Installation

**1. Clone the repo**

```bash
git clone https://github.com/Arcadia-1/analog-agents.git
```

**2. Register the skill with Claude Code**

```bash
ln -s /path/to/analog-agents/skills/analog-agents ~/.claude/skills/analog-agents
```

**3. Configure your servers**

```bash
cp config/servers.example.yml config/servers.yml
# Edit with your host, user, and SSH key
```

**4. Create a spec sheet in your project directory**

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

**5. Invoke in Claude Code**

```
Use the analog-agents skill. Design an OTA for spec.yml.
```

## What's Inside

```
analog-agents/
├── skills/analog-agents/
│   ├── SKILL.md                  # Master skill: workflow, convergence, sign-off gate
│   ├── designer-prompt.md        # Designer agent template
│   └── verifier-prompt.md        # Verifier agent template
├── config/
│   └── servers.example.yml       # Multi-server config template
├── hooks/
│   ├── hooks.json                # Claude Code hook registration
│   ├── session-start             # Inject skill + check bridge + read spec on startup
│   ├── post-sim.sh               # Triggered after every Spectre run
│   └── post_sim_check.py         # PSF parser → spec checker → sim-log writer
└── docs/specs/                   # Design documents
```

## Philosophy

**Spec-driven, not vibe-driven.** Every design decision traces back to a quantitative target. The spec sheet is not documentation — it is the contract.

**Margin, not just pass/fail.** A design that passes at TT/27°C and fails at SS/125°C is not done. Verification reports numbers, not verdicts.

**Rationale is a deliverable.** A netlist without hand-calc justification is a guess. The designer documents the equation behind every parameter.

**Three iterations maximum.** If the design hasn't converged after three designer↔verifier loops, the problem is topology, not tuning. Stop and involve the human.

**Convergence over automation.** The loop runs until the circuit is right, not until the timer runs out. Sign-off requires L3 PVT. There are no shortcuts to tape-out.

## Related Skills

analog-agents orchestrates workflow. For domain knowledge:

| Skill | What It Does |
|-------|-------------|
| `spectre` | Run Spectre simulations from a netlist file |
| `virtuoso` | Cadence Virtuoso schematic and layout via virtuoso-bridge |
| `veriloga` | Write Verilog-A behavioral models |
| `sar-adc` | SAR ADC architecture, design, and budgeting |
| `optimizer` | Bayesian optimization of circuit parameters |

## License

MIT — see [LICENSE](LICENSE)
