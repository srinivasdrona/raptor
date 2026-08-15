# RAPTOR model-role tournament: Phase 1 results

**Status:** Phase 1 individual-role evaluation complete; bounded Phase 2 role comparisons later
completed with no full stack selected
**Machine record:** [`model_role_phase1_result_2026-08-15.json`](../../data/eval/model_role_phase1_result_2026-08-15.json)
**Subsequent result:** [Phase 2 report](model-role-phase2-results-2026-08.md)

Phase 1 evaluated models independently in planner, test-author, doer and checker roles. Each finalist completed three task families with five valid independent runs per task. No stack was evaluated or selected.

Eight paired cells were invalidated before result use when the benchmark itself was found defective. Every invalidated output is preserved in [`INVALIDATED_CELLS.json`](../../benchmarks/model_role_v1/INVALIDATED_CELLS.json), excluded from scoring and rerun after a versioned refreeze.

## Planner

| Model | Role score | Hard gates | Worst run |
|---|---:|---:|---:|
| Claude Opus 5 | **95.00** | 15/15 | 87.50 |
| Gemini 3.7 Flash | **93.06** | 15/15 | 77.50 |
| GPT-5.6 Sol | **92.50** | 15/15 | 84.17 |

Opus leads on aggregate planning quality. Gemini slightly exceeds Sol on aggregate score, while Sol has the stronger worst-run floor.

## Test author

Hard-gate reliability takes precedence over the raw role score.

| Model | Role score | Hard gates | Worst run |
|---|---:|---:|---:|
| GPT-5.3-Codex | **88.12** | **11/15** | 71.25 |
| Claude Opus 5 | **84.37** | **9/15** | 71.25 |
| Gemini 3.7 Flash | **88.75** | **6/15** | 0.00 |

Gemini has the highest raw score but the weakest reproducibility: nine of fifteen runs failed a hard gate, including one missing-test artifact. Codex is the Phase 1 test-author leader because it combines comparable quality with the strongest gate reliability.

## Doer

Doer scores are quality subtotals out of 90. The preregistered 10 efficiency points remain pending because candidate-run token and AI-usage telemetry could not be reliably joined to run identifiers.

| Model | Quality score / 90 | Hard gates | Worst run |
|---|---:|---:|---:|
| GPT-5.6 Terra | **90.00** | 15/15 | **90.00** |
| Claude Sonnet 5 | **90.00** | 15/15 | 80.00 |
| MAI-Code-1.1-Flash | **85.00** | 15/15 | 75.00 |

Terra and Sonnet tie on aggregate quality; Terra leads on worst-run stability. MAI-Code passes every hard gate and remains a credible coding finalist, but trails the two leaders on the current high-assurance task set.

## Checker

| Model | Role score | Hard gates | Worst run |
|---|---:|---:|---:|
| Claude Opus 5 | **100.00** | 15/15 | **100.00** |
| Gemini 3.7 Flash | **100.00** | 15/15 | 91.18 |
| GPT-5.6 Sol | **100.00** | 15/15 | 91.18 |
| Grok 4.6 | **100.00** | 15/15 | 88.45 |

All four checker finalists achieved perfect scenario-median scores and passed every hard gate. Opus has the strongest worst-run floor. Phase 2 must determine whether these isolated checker results survive interaction with different planners, test authors and doers.

## Phase 2 candidate pool

- **Planner:** Claude Opus 5, Gemini 3.7 Flash, GPT-5.6 Sol
- **Test author:** GPT-5.3-Codex, Claude Opus 5, Gemini 3.7 Flash
- **Doer:** GPT-5.6 Terra, Claude Sonnet 5, MAI-Code-1.1-Flash
- **Checker:** Claude Opus 5, Gemini 3.7 Flash, GPT-5.6 Sol, Grok 4.6

Role winners do not automatically form a valid stack. Phase 2 must enforce:

- test-author family differs from doer family;
- checker family differs from doer family;
- reduced family diversity requires an explicit governance decision;
- hard-gate failures cannot be offset by speed or cost.

## Limits

- This is a RAPTOR-specific software-engineering benchmark, not a general model leaderboard.
- Human-review minutes were not instrumented.
- Doer efficiency points are pending.
- The evaluator remains embargoed until Phase 2 candidate outputs are frozen.
- No operating-model change, RAPTOR v2 launch or RescueScreen launch is authorized by Phase 1 alone.
