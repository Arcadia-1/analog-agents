# analog-agents

AI-native analog frontend design framework for Claude Code and compatible agents.

Dispatches a **designer** and a **verifier** agent to iterate on a circuit netlist
until all specs pass, then tapes out to Virtuoso.

## How It Works

1. You provide a `spec.yml` with quantitative targets
2. The **designer** agent produces a netlist with hand-calc rationale
3. The **verifier** agent runs Spectre simulations and reports margins
4. They iterate until all specs pass (staged verification: L1 → L2 → L3 PVT)
5. The designer tapes out the verified netlist to Virtuoso

## Installation

### 1. Configure servers

```bash
cp config/servers.example.yml config/servers.yml
# Edit config/servers.yml with your host, user, key
```

### 2. Register as a Claude Code skill

```bash
ln -s /path/to/analog-agents/skills/analog-agents ~/.claude/skills/analog-agents
```

### 3. Create a spec sheet

```bash
cat > spec.yml << 'EOF'
block: my-ota
process: tsmc28nm
supply: 1.8V
specs:
  dc_gain:      { min: 60,  unit: dB  }
  phase_margin: { min: 45,  unit: deg }
  power:        { max: 1.0, unit: mW  }
EOF
```

### 4. Invoke the skill

In Claude Code: use the `analog-agents` skill and describe your circuit block.

## Verification Levels

| Level | Trigger | What Runs |
|-------|---------|-----------|
| L1 Functional | default | DC operating point, TT/27°C |
| L2 Spec | explicit request | All spec analyses, TT/27°C |
| L3 PVT | sign-off required | Full corner matrix from spec.yml |

## Output Files

| File | Description |
|------|-------------|
| `<block>.scs` | Final verified netlist |
| `rationale.md` | Designer's hand-calc justification |
| `testbench_<block>.scs` | Verifier's testbench |
| `sim-log.yml` | Auto-maintained simulation history with margins |
| `margin-report.md` | Latest margin summary |

## Related Skills

This skill orchestrates workflow. For domain knowledge, use:

- `spectre` — run Spectre simulations from a netlist file
- `virtuoso` — Virtuoso schematic/layout operations via virtuoso-bridge
- `veriloga` — write Verilog-A behavioral models
- `sar-adc` — SAR ADC architecture, design, and budgeting
