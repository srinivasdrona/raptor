# RAPTOR model-role operating panel: final tiered-planner governance decision

**Status:** Final governance decision; the model-role exercise is closed
**Decision date:** 2026-08-16
**Scope:** Supervised development operating panel; not an autonomous stack qualification

## Final operating panel

| Role | Selected model | Operating rationale |
|---|---|---|
| Default planner | **GPT-5.6 Terra at xhigh** | Default for routine, tightly specified, bounded, and reversible work. |
| Escalation planner | **GPT-5.6 Sol** | Required for ambiguous requirements, architecture, migrations, security/safety-critical changes, irreversible or high-blast-radius work, cross-domain integration, or a Terra authority/acceptance-review failure. |
| Test author | **GPT-5.3 Codex** | Phase 1 test-author leader on the governing hard-gate rule, with 11/15 passes. |
| Doer | **MAI-Code-1.1-Flash** | First in the byte-identical paired-doer comparison at 10/15 corrected eligible runs. |
| Checker | **Claude Opus 5** | First in the isolated checker comparison on hard-gate pass rate, recall, and severity-weighted recall. |

Human/staff adjudication remains the terminal authority for every task. In particular, **all Opus
HIGH and CRITICAL findings require human/staff adjudication** before they can determine disposition.
No model verdict, including `CLEAN`, independently authorizes merge, release, scope expansion, or
clinical use.

## What the evidence measured, and what this decision does

The tournament did **not** qualify a fully autonomous stack:

- Every planner, including Sol, failed the `registry-bridge` planner-authority gate in 5/5 runs.
- Both paired doers retained HIGH snapshot-publisher defects in all five runs; the preregistered
  efficiency component is `PENDING_UNAWARDABLE`.
- Opus was the best checker, but passed hard gates in 20/30 cells and identified 29/85 semantic
  defects. Its ten unsupported HIGH or CRITICAL overcalls require supervision.
- Test-author selection was measured in Phase 1 rather than independently isolated in Phase 2.

Those are measured qualification limits, not revised or hidden results. **Terra was actually tested
at xhigh and achieved 7/15 corrected eligible planner runs; Sol led the same final planner ranking
at 10/15.** The tiered routing policy is therefore an explicit cost/operating governance decision,
not a claim that Terra won the planner comparison or an award of the unmeasured efficiency points.
It assigns lower-risk, bounded work to Terra and reserves Sol for the escalation conditions stated
above.

The panel is a supervised operating model: it chooses the best available role-specific evidence
while retaining human terminal authority and the controls below. It does not retroactively declare
an autonomous winner or alter a frozen machine record.

## Evidence record

| Evidence | Measured result relevant to this decision | Records |
|---|---|---|
| Phase 1 role evaluation | Codex led test authorship by hard-gate reliability (11/15). Opus led the isolated planner score; Terra led isolated doer quality/stability; checker scores tied, with Opus having the strongest worst-run floor. | [Report](model-role-phase1-results-2026-08.md) · [machine record](../../data/eval/model_role_phase1_result_2026-08-15.json) |
| Phase 2 planner and paired-doer comparisons | Sol led planners at 10/15 corrected eligible runs; MAI-Code led paired doers at 10/15 versus Sonnet's 7/15. Neither result independently qualified a replacement. | [Report](model-role-phase2-results-2026-08.md) · [machine record](../../data/eval/model_role_phase2_result_2026-08-16.json) |
| Terra and Grok planner extension | Terra was executed at xhigh. Sol remained first: Sol 10/15, Opus 9/15, Terra 7/15, Grok 5/15, Gemini 4/15. | [Report](model-role-planner-extension-2026-08.md) · [machine record](../../data/eval/model_role_planner_extension_result_2026-08-16.json) |
| Isolated checker comparison | Opus led Grok: 20/30 versus 14/30 hard-gate passes, 29/85 versus 22/85 defect recall, and zero versus 11 wrong-`CLEAN` failures. | [Report](model-role-checker-comparison-2026-08.md) · [machine record](../../data/eval/model_role_checker_comparison_result_2026-08-16.json) |

All comparisons used the frozen authority order:

`SPEC -> candidate-visible fixtures -> PLAN -> tests -> implementation`

## Alternatives and challengers

- **Planner measurement:** Sol is the measured leader (10/15), with Claude Opus 5 close behind
  (9/15). Terra was tested at xhigh and scored 7/15; Grok (5/15) and Gemini (4/15) followed.
  The default-Terra/escalation-Sol policy does not change that ordering. Phase 1's isolated
  planner-quality lead for Opus does not override the later authority-first comparison.
- **Test author:** Opus passed 9/15 Phase 1 hard gates; Gemini had the highest raw score but only
  6/15 hard-gate passes. Neither displaces Codex's reliability lead.
- **Doer:** Claude Sonnet 5 was the paired-doer alternative (7/15) and had the higher descriptive
  pre-efficiency hidden-quality mean, but MAI-Code's SPEC-first corrected eligibility led 10/15 to
  7/15. Terra led Phase 1 isolated quality/stability, but was not part of this paired-doer
  comparison and is therefore not inferred to outrank MAI-Code here.
- **Checker:** Grok 4.6 remains the high-precision challenger (22/28 reported findings were
  supported), but its 11 wrong-`CLEAN` failures, one invalid verdict, and four input mutations
  make it unsuitable as the terminal checker. A Grok `CLEAN` verdict cannot close a task without
  independent confirmation.

## Operating controls

1. Preserve the frozen authority order. A plan may clarify mechanics but may not add, contradict,
   or weaken a binding SPEC requirement.
2. Route only routine, tightly specified, bounded, reversible work to Terra at xhigh. Route every
   ambiguous requirement, architecture or migration, security/safety-critical change, irreversible
   or high-blast-radius change, and cross-domain integration to Sol.
3. Review every Terra plan for authority and acceptance before implementation. A failed review
   escalates planning to Sol; it is not repaired by relaxing the SPEC or acceptance criteria.
4. Keep authored tests protected and retain the role separation embodied by this four-family panel.
5. Use Opus as a supervised checker only. Human/staff adjudicates all Opus HIGH and CRITICAL
   findings and remains the terminal decision-maker for every finding and final disposition.
6. Keep checker workspaces immutable except for the verdict artifact; do not use a Grok `CLEAN`
   verdict as a closing decision without independent confirmation.
7. Treat efficiency as unmeasured until a deterministic formula and attributable run telemetry are
   prospectively frozen. Do not use cost or speed to offset a hard-gate failure.
8. Record any future role change as a new prospective, role-isolated evaluation; it must not
   rewrite the frozen Phase 1, Phase 2, checker-comparison, or planner-extension records.

## Known limitations

- This is a RAPTOR-specific software-engineering benchmark with three reused task families and five
  repetitions per arm/scenario; it is not a general model leaderboard or a broad statistical claim.
- Phase 2 was a bounded planner isolation and paired-doer comparison, not the abandoned exhaustive
  eight-stack execution. The Opus planner arm reused S1 evidence.
- Corrected eligibility depends on role attribution; raw stack outcomes must not be read as a
  single-role measure.
- No participant cleared every cross-scenario hard gate, and checker recall remains limited. The
  supervisory controls are therefore part of the decision, not optional follow-up work.

## Closure

This governance decision closes the model-role tournament. RAPTOR v2 and RescueScreen work may
proceed under this supervised panel, while retaining their separate scope, safety, evidence, and
entry-gate requirements. This decision does not bypass those requirements and does not authorize
autonomous operation or clinical use.
