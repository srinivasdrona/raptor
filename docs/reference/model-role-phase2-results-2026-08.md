# RAPTOR model-role tournament: Phase 2 results

**Status:** Bounded planner and paired-doer comparisons complete; no full stack selected  
**Machine record:** [`model_role_phase2_result_2026-08-16.json`](../../data/eval/model_role_phase2_result_2026-08-16.json)

Phase 2 ranked 45 planner-comparison cells and 30 paired-doer cells over `registry-bridge`,
`snapshot-publisher`, and `workspace-boundary`. Thirty planner cells and all 30 doer cells were
newly executed; the 15-cell Opus planner arm reused S1 as frozen. The final inventory tracked 90
materialized cells when the 15 shared upstream plan/test cells are included. This was a bounded
role-isolation tournament, not the abandoned exhaustive eight-stack run.

All adjudication used the frozen authority order:

`SPEC -> candidate-visible fixtures -> PLAN -> tests -> implementation`

A plan may clarify mechanics but may not add, contradict, or weaken a binding SPEC requirement.
Raw execution failures and corrected role attribution are therefore reported separately.

## Planner comparison

Gemini test author, Sonnet 5 doer, and Sol checker were fixed. The primary metric is the number of
runs without a planner-attributable SPEC-authority failure.

| Rank | Planner | Corrected eligibility | Registry | Snapshot | Boundary |
|---:|---|---:|---:|---:|---:|
| 1 | GPT-5.6 Sol | **10/15** | 0/5 | **5/5** | **5/5** |
| 2 | Claude Opus 5 (S1 reuse) | **9/15** | 0/5 | 4/5 | **5/5** |
| 3 | Gemini 3.7 Flash | **4/15** | 0/5 | 0/5 | 4/5 |

Sol is the planner leader, but **there is no qualified planner winner**. Every planner failed the
registry authority hard gate in all five runs by adding behavior outside the closed SPEC contract.
Sol's one-run aggregate lead over Opus cannot override that scenario-wide failure, so replacing the
incumbent planner is not authorized.

The ordering is stable under the recorded sensitivity checks. Reassigning Gemini snapshot run 04
to the fixed test author raises Gemini only to 5/15. Waiving Gemini boundary run 03 makes that
scenario a tie but leaves the aggregate order unchanged. Registry remains non-discriminating at
the hard gate; its advisory shipped-artifact ordering is Gemini, Sol, Opus.

## Paired doer comparison

Gemini planner, Codex test author, and Grok checker were fixed. Matching plans and authored tests
were byte-identical between the two variants; execution forked only at the doer.

| Rank | Doer | Corrected eligibility | Registry | Snapshot | Boundary |
|---:|---|---:|---:|---:|---:|
| 1 | MAI-Code-1.1-Flash | **10/15** | **5/5** | 0/5 | **5/5** |
| 2 | Claude Sonnet 5 | **7/15** | **5/5** | 0/5 | 2/5 |

MAI-Code is the **SPEC-first, pre-efficiency doer leader**, driven by a 5/5 versus 2/5 advantage on
workspace boundary. It is not a qualified doer winner: both models retained HIGH defects in every
snapshot-publisher run. That 0/5 result does not depend on disputed source/output alias behavior;
non-finite JSON acceptance and unchecked short writes independently fail every candidate.

Raw hidden quality means before efficiency favored Sonnet, 79.00 versus 77.33, but those values are
descriptive only. They cannot offset hard-gate failures.

## Artifact and attribution rulings

- `DV-MAI/registry-bridge/run-03/VERDICT.yaml` is invalid YAML. This is a raw protocol failure owned
  by the checker; it does not change MAI-Code's corrected doer eligibility.
- `PC-SOL/snapshot-publisher/run-05` and `PC-SOL/workspace-boundary/run-03` contain no authored
  `tests/test_*.py` artifact. Both are raw protocol failures owned by test authorship/execution;
  complete plans and sibling evidence exonerate the planner.
- Several boundary failures came from inconsistent mock resolvers or test data that a canonical
  SPEC-faithful reference also failed. Those are upstream test defects, not reasons to weaken
  correct containment.
- Low checker numeric scores sometimes reflect evaluator category-name mismatch rather than an
  incorrect clean verdict. Checker scores and hard-gate status remain separate dimensions.

Frozen artifacts were not repaired after the fact.

The final inventory found 267/270 valid required stage artifacts and 120/120 parseable hidden
evaluation files. Its three raw-gap cells are exactly the two missing authored-test artifacts and
one invalid checker verdict above; none is planner-attributable.

## Efficiency

The preregistered ten efficiency points remain `PENDING_UNAWARDABLE`. No frozen deterministic
formula or attributable candidate-run telemetry exists. The component is neutrally excluded;
neither equal nor model-dependent points are invented.

## Decision boundary

Phase 2 authorizes the planner and doer **rankings only**:

- planner leader: GPT-5.6 Sol;
- paired-doer leader: MAI-Code-1.1-Flash.

It does **not** authorize a planner replacement, doer replacement, test-author choice, checker
choice, full stack, or operating-model change. ADR-0003 and ADR-0005 remain binding. A later
selection requires a planner that clears corrected registry authority, a doer that clears the
snapshot HIGH-defect gate, isolated test-author and checker evidence, and either deterministic
efficiency measurement or a prospectively amended rubric that removes it.

The required isolated checker evidence was subsequently produced in the
[Opus-versus-Grok checker comparison](model-role-checker-comparison-2026-08.md). It ranks Opus first
but still authorizes no autonomous checker replacement; Opus is a supervised default and Grok a
precision challenger. Other Phase 2 authorization boundaries are unchanged.

## Limits

- This is a RAPTOR-specific software-engineering benchmark, not a general model leaderboard.
- Phase 2 reused the Phase 1 scenarios; prior task exposure is disclosed.
- The Opus planner arm reused S1 rather than rerunning identical cells.
- Five repetitions per arm/scenario support directional comparison, not broad statistical claims.
- The fixed downstream roles exposed material defects of their own; attribution correction is
  essential and raw stack outcomes must not be read as planner-only performance.
