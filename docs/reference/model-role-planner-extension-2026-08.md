# RAPTOR model-role tournament: Terra and Grok planner extension

**Status:** Extension complete; Sol remains the planner leader  
**Machine record:** [`model_role_planner_extension_result_2026-08-16.json`](../../data/eval/model_role_planner_extension_result_2026-08-16.json)

GPT-5.6 Terra and Grok 4.6 were each run through the same 15-cell planner configuration used for
the frozen Sol comparison: three scenarios, five repetitions, with Gemini 3.7 Flash as test author,
Claude Sonnet 5 as doer and GPT-5.6 Sol as experimental checker. Terra's prior doer result and
Grok's prior checker result contributed no planner evidence.

The primary metric remained corrected runs without a planner-attributable SPEC-authority failure.

| Rank | Planner | Corrected eligibility | Registry | Snapshot | Boundary |
|---:|---|---:|---:|---:|---:|
| 1 | GPT-5.6 Sol | **10/15** | 0/5 | **5/5** | **5/5** |
| 2 | Claude Opus 5 | **9/15** | 0/5 | 4/5 | **5/5** |
| 3 | GPT-5.6 Terra | **7/15** | 0/5 | 2/5 | **5/5** |
| 4 | Grok 4.6 | **5/15** | 0/5 | 0/5 | **5/5** |
| 5 | Gemini 3.7 Flash | **4/15** | 0/5 | 0/5 | 4/5 |

## Terra

Terra is a credible third-ranked planner, but it does not replace Sol:

- all five registry plans expand or rename the closed six-check/error contract;
- snapshot runs 01-03 omit the required typed `OUTPUT_PATH` mapping for staging, write or replace
  failures;
- both snapshot runs that transmitted that binding surface and all five boundary runs were
  planner-eligible.

Its aggregate corrected result is 7/15, three runs behind Sol and two behind Opus.

## Grok

Grok's advisory planner rubric scores were high, but the authority-first result is weaker:

- all five registry plans failed the same closed-contract authority gate;
- all five snapshot plans limited `OUTPUT_PATH` to the parent-directory precondition and omitted
  typed staging/write/replace failures;
- all five boundary plans were planner-eligible.

This produces 5/15. One registry test-author artifact was missing, but it was attributed to the
fixed test-author/execution stage and did not lower Grok's corrected planner score.

## Measured decision boundary

Sol remains the best-evidenced planner, with Opus the close alternative. Terra and Grok do not
displace either model. No planner is fully qualified because every candidate failed the registry
authority gate in 5/5 runs.

The subsequent [final operating-panel governance decision](model-role-operating-panel-2026-08.md)
uses tiered planning: Terra at xhigh is the default for routine, tightly specified, bounded,
reversible work, while Sol is the escalation planner for higher-risk or failed-review work. That is
a cost/operating routing decision, not a revision of this measured ranking: Terra was tested at
xhigh and scored 7/15, while Sol led at 10/15.
