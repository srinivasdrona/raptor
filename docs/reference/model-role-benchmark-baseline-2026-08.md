# RAPTOR model-role benchmark: incumbent baseline

**Status:** proposed internal baseline; prospective tournament not run
**Machine-readable sources:** [`model-role-benchmark-v1.yaml`](../project/specs/model-role-benchmark-v1.yaml) and [`model_role_incumbent_baseline_2026-08-15.json`](../../data/eval/model_role_incumbent_baseline_2026-08-15.json)

The historical record is sufficient to describe the incumbent stack and design a fair tournament, but not to name a winning model family. The current Opus → Gemini → Sonnet 5 → GPT process remains binding until prospective paired runs, publication of the results and an owner decision.

## What the retrospective record contains

- 53 retained three-slot manifests: 8 planning, 17 test-authoring, 13 implementation, 5 formal-execution and 10 composition/review/research packets.
- 412 non-merge commits since July 1, including 92 `test(...)`, 55 `fix(...)`, 28 `feat(...)`, 11 `data(...)` and 6 `plan(...)` commits.
- 349 main-session turns and 31,526 request-level usage events with token, duration and internal AI-usage telemetry.
- Ten benchmarkable historical workflows, with the Atlas selector as the richest case: 31 manifests, five execution packets, four blocked precondition attempts and at least nine named real-input or audit defect classes before the authoritative run.

These counts measure process volume, not quality. Request telemetry contains repeated context and is not cleanly attributable to a role or accepted task.

## Important metrics added before comparison

The original proposal covered plan quality, mutation-killing tests, implementation correctness, checker recall/precision, escaped defects, loops, time and cost. The baseline adds six controls that are necessary to avoid a misleading leaderboard:

| Added metric | Why it matters |
|---|---|
| **Defect severity** | One provenance bypass or wrong CLEAN must outweigh many minor style findings. |
| **Attribution confidence** | A defect can originate in the plan, tests, implementation, review, orchestration or several of them. |
| **Real-fixture fidelity** | Synthetic tests repeatedly passed while real artifact shapes failed. |
| **Run-to-run variance** | A model that succeeds once and fails twice is not a reliable winner. |
| **Confidence calibration** | Strongly stated but wrong output should score worse than an explicit uncertainty or block. |
| **Human-review burden** | Cheap generation can be expensive if the operator must reconstruct, repair or re-check it. |

The benchmark also records scope compliance, maintainability, tool/finish reliability, post-merge escapes and worst-run behavior.

## Incumbent baseline

| Role | Observed strengths | Observed limitations | Evidence confidence |
|---|---|---|---|
| **Planner — Opus** | Governance, decomposition, leakage boundaries, machine-readable contracts | Real artifact shapes and executable integration details were sometimes omitted | Medium |
| **Test author — Gemini** | Broad adversarial coverage and large protected suites | Vacuous tests, impossible fixtures and synthetic/real-shape divergence occurred | Medium |
| **Doer — Sonnet 5** | Strong large-surface implementation and targeted repair | Initial green builds retained schema, path, snapshot and audit defects | Medium |
| **Checker — GPT** | High-value reproducible findings and strong provenance/TOCTOU review | Recall and false-positive rates were not measured; some real-input defects appeared after CLEAN | Medium-low |
| **Whole stack** | High eventual quality on completed audited cases | Low-to-moderate first-pass efficiency and substantial repair burden | Medium |

No selection-grade tournament composite is reported because mutation scores, hidden-task results, checker false-positive adjudication, human minutes and repeat-run variance were not collected consistently. The proxy below summarizes only the recoverable historical evidence.

## Deprecated expert-coded historical proxy

The earlier **69/100** was an expert-coded historical maturity rubric, not a quantitatively measured baseline. The weighted arithmetic is reproducible, but most component inputs were qualitative judgments informed by evidence rather than observed rates with standardized denominators. It is retained for audit history and must not be compared with tournament scores.

| Dimension | Weight | Score |
|---|---:|---:|
| Eventual correctness | 25% | 90 |
| First-pass quality | 15% | 50 |
| Real-fixture robustness | 15% | 45 |
| Review effectiveness | 15% | 80 |
| Auditability | 10% | 72 |
| Process efficiency | 10% | 45 |
| Safety and governance | 10% | 90 |
| **Weighted total** | **100%** | **69.45 → 69** |

The result says the process is strong at eventually producing safe, audited artifacts, but pays for that result through substantial repair loops and weak first-pass fidelity to real inputs.

The backing for each input was:

| Input | Evidence backing | Measurement status |
|---|---|---|
| Eventual correctness 90 | Completed audited workflows eventually reached green terminal artifacts | Qualitative; no frozen task denominator |
| First-pass quality 50 | Repeated repair chains; four blocked Atlas attempts before the valid run | Qualitative; not a 50% rate |
| Real-fixture robustness 45 | At least nine named real-input/schema/path/audit defect classes in the Atlas case | Qualitative; not normalized |
| Review effectiveness 80 | Many findings reproduced and fixed; recall and wrong-CLEAN rates absent | Qualitative |
| Auditability 72 | **38/53 manifests had explicit model ids = 71.7%, rounded to 72**; telemetry linkage remained incomplete | Partly quantitative |
| Efficiency 45 | Large repair and usage burden without accepted-task cost denominator | Qualitative |
| Governance 90 | No known reviewed boundary breach; fail-closed/non-clinical rules preserved | Qualitative; no opportunity denominator |

Role-specific maturity proxies are:

| Role | Score | Reading |
|---|---:|---|
| Planner — Opus | **69** | Strong governance; mixed executable and real-shape completeness |
| Test author — Gemini | **59** | Strong adversarial breadth; weak nonvacuity and fixture fidelity |
| Doer — Sonnet 5 | **78** | Strong eventual implementation and repair; moderate first-pass robustness |
| Checker — GPT | **72** | High-value findings; unmeasured recall and wrong-CLEAN risk |

These scores are **not comparable across roles**, because each role uses different dimensions.

The role values—planner 69, test author 59, doer 78 and checker 72—were created the same way: weighted expert judgments over role-specific dimensions. They are useful as a structured narrative of historical strengths and weaknesses, but they are not measured model-performance scores. Prospective task scores replace them for every comparison.

Four historical hard gates pass on reviewed evidence, but `no_wrong_clean` remains **indeterminate** and reproducibility is only **partial** because several model manifests and task-level telemetry links are missing. Therefore the score cannot qualify the incumbent as the winner; that requires the prospective tournament.

## How candidates will be compared

Every candidate receives the same frozen task, three-slot prompt, tools, permissions, timeout, context budget, base commit and hidden evaluator. Failed runs remain in the record. Screening uses at least three runs per model/task; finalists use five.

Hard gates precede scoring:

1. no critical/high-severity escape;
2. no wrong CLEAN on a seeded critical/high defect;
3. no protected-test weakening;
4. no safety, grounding or domain-overclaim breach;
5. complete reproducibility artifacts;
6. honest blocked/failure states.

Among hard-gate passers, the ranking weights correctness and safety first, followed by reproducibility, role effectiveness, human burden and normalized efficiency. Results are paired by task and stratified by role, artifact type, risk and complexity.

## Validated multi-model strategy

A two-model Sonnet-versus-MAI comparison would be too narrow. Official product descriptions establish that:

- **GPT-5.3-Codex** is explicitly an agentic coding model for long-running, tool-using software work ([OpenAI](https://openai.com/index/introducing-gpt-5-3-codex/)).
- **MAI-Code-1.1-Flash** is a small-tier coding model improved for coding quality, instruction following and tool use, positioned for lightweight cost-efficient coding workflows ([GitHub](https://github.blog/changelog/2026-08-11-mai-code-1-1-flash-available-in-github-copilot/)).
- **Claude Sonnet 5** is positioned for everyday development and agentic workflows, with particularly strong CLI-style results in GitHub's internal testing ([GitHub](https://github.blog/changelog/2026-06-30-claude-sonnet-5-is-generally-available-for-github-copilot/)).
- **GPT-5.6 Terra** is the balanced agentic-coding default; **Sol** targets high-ceiling large-codebase reasoning and **Luna** smaller cost-efficient tasks ([GitHub](https://github.blog/changelog/2026-07-09-openais-gpt-5-6-sol-terra-and-luna-are-now-available-in-github-copilot/)).
- **Gemini 3.7 Flash** is described by Google as its most intelligent workhorse model yet for coding and agents, built for reliable multi-step execution with tunable high reasoning; GitHub reports improved codebase research and verification on complex coding tasks ([Google](https://ai.google.dev/gemini-api/docs/latest-model), [GitHub](https://github.blog/changelog/2026-08-13-gemini-3-7-flash-is-now-available-in-github-copilot/)).

Those descriptions justify **eligibility**, not scores. The primary doer comparison therefore includes Sonnet 5, GPT-5.3-Codex, GPT-5.6 Terra and MAI-Code-1.1-Flash on the same complete task set. Sol and Opus 5 form a high-reasoning supplement on complex tasks; Luna and MAI-Code-1-Flash form an efficiency supplement on smaller tasks. Results remain stratified so a lightweight model is not misleadingly declared an unconditional winner or loser.

The other role pools are also multi-model:

| Role | Primary comparison pool |
|---|---|
| Planner | Opus 5 · GPT-5.6 Sol · GPT-5.6 Terra · Gemini 3.7 Flash · Grok 4.6 |
| Test author | Gemini 3.7 Flash · MAI-Code-1.1-Flash · GPT-5.3-Codex · Opus 5 |
| Doer | Sonnet 5 · GPT-5.3-Codex · GPT-5.6 Terra · MAI-Code-1.1-Flash |
| Checker | GPT-5.4 · GPT-5.6 Sol · Opus 5 · Grok 4.6 · Gemini 3.7 Flash |

The tournament uses successive halving: all primary peers run the same three-task screen with three repeats; hard-gate failures are removed; the top two or three per role run the full corpus with five repeats. Only then are a few governance-valid full stacks assembled. This preserves attribution without attempting every possible permutation.

Gemini was initially omitted from the planner pool because its `Flash` label was treated as a speed/test-author signal. That was not evidence-based. Planner eligibility is now determined by observed planning metrics, not model naming. If Gemini wins more than one isolated role, the final stack still separately evaluates whether reusing one family would create correlated blind spots; role wins do not automatically override the existing four-family independence control.

## Publication and launch gate

The exercise ends with a public blog post containing the task corpus, exact model versions, hard-gate failures, negative/null results, variance, worst runs, elapsed time, token/AI usage, human-review burden and generalizability limits. It must not claim a universally best model or hide failed and expensive runs.

The owner selects the stack only after that publication. RAPTOR v2 and RescueScreen then start as separate parallel tracks under the selected, governance-approved stack.
