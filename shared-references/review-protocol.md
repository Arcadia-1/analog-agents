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
