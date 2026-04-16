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
