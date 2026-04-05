# analog-team Skill Library — Design Spec

**Date:** 2026-04-05  
**Status:** Approved  

---

## Overview

`analog-team` is a skill library for AI-native analog frontend design, built for Claude Code and compatible agents. It applies the core ideas of `superpowers` (structured agent roles, prompt templates, workflow discipline) to the analog IC design domain.

The central difference from superpowers: the unit of work is a **netlist**, the central contract is a **spec sheet**, and verification is **simulation-based with quantitative margin**, not a test suite.

---

## Design Philosophy

- **Spec-driven**: Every agent reads `spec.yml`. Nothing ships without specs being met.
- **Two real roles**: designer and verifier — matching how actual analog teams are organized.
- **Convergence, not one-shot**: designer and verifier iterate until all specs pass with margin.
- **Staged verification**: don't run PVT corners until the circuit works at typical first.
- **Flexible infrastructure**: single account or multi-server/multi-account, same skill works.

---

## Library Structure

```
analog-team/                          ← repo root IS the skill library
├── skills/
│   └── analog-team/
│       ├── SKILL.md                  ← master skill: when to use, how to coordinate
│       ├── designer-prompt.md        ← designer agent template
│       └── verifier-prompt.md        ← verifier agent template
├── config/
│   └── servers.example.yml           ← multi-server config template (no real credentials)
├── hooks/
│   ├── hooks.json                    ← Claude Code hook registration
│   ├── session-start                 ← inject skill + check bridge + read spec summary
│   └── post-sim.sh                   ← parse PSF + check spec + append sim-log.yml
└── docs/
    └── specs/                        ← design spec documents (this file lives here)
```

---

## Agent Roles

### designer

- Reads `spec.yml` and produces hand-calculation rationale + netlist (`.scs`)
- Has read/write access to netlist files and Virtuoso
- After sign-off gate passes, executes Virtuoso migration (tape-out)
- Must accompany every netlist with a `rationale.md` explaining sizing decisions

### verifier

- Read-only access to netlist files
- Writes testbench, runs Spectre simulations, reports margin per spec per corner
- Runs verification at the requested level (see Staged Verification below)
- Updates `sim-log.yml` via the post-sim hook
- Returns structured margin report to designer for convergence decisions

---

## Workflow

```
spec.yml
    │
    ▼
designer agent
  ├─ hand-calc sizing
  └─ produces: netlist.scs + rationale.md
    │
    ├──────────────────────────┐
    ▼                          ▼
verifier agent            (designer continues
  ├─ writes testbench      documenting rationale)
  ├─ runs simulation
  └─ returns margin report
    │
    ▼
all specs pass?
  ├─ NO → margin report → designer → revise netlist → repeat
  └─ YES
    │
    ▼
sign-off gate
(L3 PVT required before tape-out)
    │
    ▼
designer agent
  └─ tape-out: netlist → Virtuoso cellview + LVS check
```

---

## Staged Verification

Verifier runs at three levels. Default is L1. Higher levels are requested explicitly or required at sign-off.

| Level | Trigger | Corners | Purpose |
|-------|---------|---------|---------|
| **L1 Functional** | default | TT / 27°C / nominal | Does the circuit operate? Is the operating point sane? |
| **L2 Spec** | explicit request | TT / 27°C / nominal | Do all spec targets pass at typical? |
| **L3 PVT** | explicit request or sign-off | Full corner matrix | Does the design hold across process/voltage/temperature? |

L3 is mandatory before tape-out. L1 and L2 are the normal iteration loop.

**Example corner matrix for L3:**

```yaml
corners:
  - { name: tt_27c,   process: tt, voltage: 1.0,  temp: 27  }
  - { name: ss_125c,  process: ss, voltage: 0.9,  temp: 125 }
  - { name: ff_m40c,  process: ff, voltage: 1.1,  temp: -40 }
  - { name: sf_27c,   process: sf, voltage: 1.0,  temp: 27  }
  - { name: fs_27c,   process: fs, voltage: 1.0,  temp: 27  }
```

---

## Spec Sheet Format (`spec.yml`)

Central contract read by all agents. Quantitative, not prose.

```yaml
block: folded-cascode-ota
version: 1.0
process: tsmc28nm
supply: 1.8V

specs:
  dc_gain:      { min: 60,  unit: dB       }
  ugbw:         { min: 100, unit: MHz      }
  phase_margin: { min: 45,  unit: deg      }
  noise_input:  { max: 5,   unit: nV/rtHz, freq: 1MHz }
  power:        { max: 1.0, unit: mW       }
  slew_rate:    { min: 50,  unit: V/us     }

corners:
  - { name: tt_27c,  process: tt, voltage: 1.8,  temp: 27  }
  - { name: ss_125c, process: ss, voltage: 1.62, temp: 125 }
  - { name: ff_m40c, process: ff, voltage: 1.98, temp: -40 }
```

---

## Server Configuration (`servers.example.yml`)

Supports two modes. Role-to-server mapping is optional.

```yaml
# Mode A: single shared account
servers:
  default:
    host: eda01.company.com
    user: shared_user
    key: ~/.ssh/id_eda
    tools: [virtuoso, spectre]

# Mode B: per-role accounts (optional)
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

# Optional role mapping (if absent, all roles use 'default')
role_mapping:
  designer:  design-server
  verifier:  sim-server
```

Agent prompts reference `role_mapping.<role>` at runtime. Role permissions (read-only vs read-write) are defined in the prompt, not by the account.

---

## Hooks

### SessionStart

Fires on session startup. Injects `using-analog-team` skill content into context, checks virtuoso-bridge connectivity, reads `spec.yml` summary if present in current directory.

### PostToolUse — matcher: `spectre|virtuoso-bridge simulate`

Fires after any Spectre simulation. Runs `post-sim.sh`:
1. Parses PSF output
2. Checks results against `spec.yml` targets
3. Appends structured entry to `sim-log.yml`
4. Injects margin summary into context so the agent sees pass/fail immediately

### PreToolUse — matcher: `Write|Edit`

Fires before file writes. If the active agent is verifier and the target file matches `*.scs|*.sp|*.net`, emits a warning that verifier should not modify netlist files.

---

## sim-log.yml (auto-maintained)

```yaml
- timestamp: 2026-04-05T14:23:00
  netlist: ota_v3.scs
  corner: tt_27c
  level: L1
  results:
    dc_gain:      { value: 62.1, unit: dB,  margin: +2.1,  pass: true  }
    phase_margin: { value: 41.2, unit: deg, margin: -3.8,  pass: false }
  status: FAIL

- timestamp: 2026-04-05T15:41:00
  netlist: ota_v4.scs
  corner: tt_27c
  level: L2
  results:
    dc_gain:      { value: 63.4, unit: dB,  margin: +3.4,  pass: true }
    phase_margin: { value: 47.1, unit: deg, margin: +2.1,  pass: true }
  status: PASS
```

---

## Comparison with superpowers

| Dimension | superpowers | analog-team |
|-----------|-------------|-------------|
| Central contract | implementation plan (prose) | spec sheet (quantitative) |
| Unit of work | code diff | netlist (.scs) |
| Verification | test suite (pass/fail) | simulation + margin (numerical) |
| Iteration | fix → re-review | convergence loop with explicit exit condition |
| Sign-off | merge approval | all corners pass with margin → tape-out |
| Roles | implementer / reviewer | designer / verifier |
| Infrastructure | none | sim-log.yml, spec.yml, servers.yml |
| Hooks | SessionStart only | SessionStart + PostToolUse + PreToolUse |

---

## What This Is Not

- Not a replacement for `virtuoso`, `spectre`, `veriloga`, or `sar-adc` skills — those teach circuit knowledge. This teaches workflow.
- Not a simulation runner — it orchestrates agents that use existing tools.
- Not tied to a specific process node or circuit topology.
