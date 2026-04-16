---
name: analog-review
description: >
  Cross-model circuit design review with divergence analysis.
  Sends netlist and rationale to multiple external LLMs for independent audit.
  Supports minimax-m2.7, qwen-3.6-plus, kimi-k2.5, glm-5.1.
  Use after analog-design to get independent review before simulation.
---

# analog-review

Cross-model circuit audit with divergence-focused reporting. After a designer
completes a netlist and rationale, this skill sends the raw design files to
multiple external LLMs for independent review, then collates their responses
into a divergence analysis report.

## Polanyi Principle

**Divergence over consensus.** When reviewers disagree, the disagreement IS the
knowledge -- it reveals what is non-obvious about the circuit. The consensus
matrix is a summary view; the divergence analysis section is the core of every
report. A well-reasoned minority FAIL outweighs a vague majority PASS.

Default behavior on disagreement: **flag for human judgment** with full reasoning
from each reviewer. NOT automatic resolution by vote count.

See `shared-references/review-protocol.md` for the full review discipline.

## Effort Gating

Read effort level per `shared-references/effort-contract.md`. Print at startup:

    [effort: <level>] reviewers=<count>

| Effort | Review behavior |
|--------|----------------|
| **lite** | Skip entirely -- return immediately with "skipped by effort level" |
| **standard** | 1 model (lowest-latency available) |
| **intensive** | 2 models, divergence analysis |
| **exhaustive** | All available models, full divergence report |

## Supported Models

| Name | Provider | Model ID |
|------|----------|----------|
| minimax | minimax | minimax-m2.7 |
| qwen | openai-compatible | qwen-3.6-plus |
| kimi | openai-compatible | kimi-k2.5 |
| glm | openai-compatible | glm-5.1 |

## Configuration

Copy `config/reviewers.example.yml` to `config/reviewers.yml` and fill in API
keys. `config/reviewers.yml` is gitignored.

```yaml
# config/reviewers.example.yml (abbreviated)
reviewers:
  minimax:
    model: minimax-m2.7
    api_key: "${MINIMAX_API_KEY}"
    base_url: "https://api.minimax.chat/v1"
    timeout: 120
  qwen:
    model: qwen-3.6-plus
    api_key: "${QWEN_API_KEY}"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout: 120
  kimi:
    model: kimi-k2.5
    api_key: "${KIMI_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    timeout: 120
  glm:
    model: glm-5.1
    api_key: "${GLM_API_KEY}"
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    timeout: 120

voting:
  min_reviewers: 2
  tie_break: "flag_for_human"
```

## Subcommands

### `/analog-review check`

Verify all reviewer connectivity. Sends a lightweight probe to each configured
reviewer and reports status and latency.

```bash
python3 tools/review_bridge.py check --config config/reviewers.yml
```

Example output:

```
  minimax (minimax-m2.7)   ok  1.2s
  qwen (qwen-3.6-plus)    ok  0.8s
  kimi (kimi-k2.5)        FAIL  401 Unauthorized
  glm (glm-5.1)           ok  1.5s

  Available: 3/4 -- meets min_reviewers (2)
```

### `/analog-review run <block-path>`

Execute a cross-model review for the specified block.

1. Read input files:
   - `circuit/<block>.scs` -- netlist
   - `circuit/rationale.md` -- design rationale
   - `spec.yml` -- target specifications
2. Optionally load anti-patterns from `wiki/anti-patterns/` matching the current
   topology tags. This is the ONLY wiki content injected into the review prompt.
3. Assemble the standardized review prompt (see below).
4. Send concurrently to selected reviewers (count depends on effort level).
5. Collate responses and generate divergence analysis.
6. Write output to `verifier-reports/cross-model-review.md`.

```bash
python3 tools/review_bridge.py review \
  --netlist circuit/<block>.scs \
  --rationale circuit/rationale.md \
  --spec spec.yml \
  --effort <level>
```

### `/analog-review report`

Display the most recent `verifier-reports/cross-model-review.md`.

## Review Prompt Template

Sent identically to every external model. Contains ONLY raw files -- no agent
self-assessments, prior review results, or designer confidence statements
(reviewer independence).

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

## Review Dimensions

Each reviewer evaluates 5 dimensions with PASS / WARN / FAIL:

1. **Connection correctness** -- dangling nodes, pin mismatches, bulk errors
2. **Bias soundness** -- mirror ratios, gm/Id range, headroom margins
3. **Sizing consistency** -- rationale equations match actual parameters
4. **Topology risks** -- known traps (CMFB polarity, compensation, etc.)
5. **Spec achievability** -- can specs be met with given sizing

## Report Format

Output to `verifier-reports/cross-model-review.md`:

1. **Reviewer status table** -- name, status, latency for each model
2. **Consensus matrix** -- 5 dimensions x N reviewers, with per-row consensus
3. **Divergence analysis** (the CORE of the report) -- one subsection per
   disagreement, with each reviewer's full reasoning and an assessment of
   reasoning quality
4. **Action items** -- labeled `[DIVERGENCE]` or `[CONSENSUS]`

When reviewers disagree, default behavior is flag for human judgment with full
reasoning from each side -- not automatic resolution by vote count.

## Wiki Interaction

If `wiki/anti-patterns/` contains entries tagged with the current topology,
those entries are appended to the review prompt under "Known Risks for This
Topology." This is the only wiki content that enters the review prompt.

## Reviewer Independence

The review prompt contains ONLY raw file contents:
- Circuit netlist (.scs)
- Design rationale (rationale.md)
- Target specifications (spec.yml)
- Known anti-patterns from wiki (if any)

NEVER include: agent self-assessments, prior review results, designer confidence
statements, or any interpretation of the design. Each reviewer must form its own
judgment from raw materials.

## Standalone Use

This skill can be used independently -- it does not require `/analog-pipeline`.
Given the input files (netlist, rationale, spec), it runs a complete review cycle.
