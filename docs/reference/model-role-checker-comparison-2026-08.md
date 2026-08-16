# RAPTOR model-role tournament: checker comparison

**Status:** Opus ranked first; no autonomous checker qualified  
**Machine record:** [`model_role_checker_comparison_result_2026-08-16.json`](../../data/eval/model_role_checker_comparison_result_2026-08-16.json)

The isolated checker comparison paired Claude Opus 5 and Grok 4.6 over 30 final cells from the
Phase 2 paired-doer corpus. Grok's frozen Phase 2 outputs supplied 26 final cells; four registry
pairs were invalidated before score use when Opus exposed binding-field behavior missing from the
frozen gold. Those pairs were replaced by eight fresh runs after a candidate-visible SPEC
clarification and byte-identical rematerialization.

All scoring used:

`SPEC -> candidate-visible fixtures -> PLAN -> tests -> implementation`

## Result

| Metric | Claude Opus 5 | Grok 4.6 |
|---|---:|---:|
| Hard-gate pass | **20/30 (66.7%)** | 14/30 (46.7%) |
| Semantic defect recall | **29/85 (34.1%)** | 22/85 (25.9%) |
| Severity-weighted recall | **124/371 (33.4%)** | 107/371 (28.8%) |
| Finding precision | 29/134 (21.6%) | **22/28 (78.6%)** |
| Wrong `CLEAN` failures | **0** | 11 |
| Mean evidence score | **9.47/10** | 7.07/10 |
| Invalid verdicts | **0** | 1 |
| Input-mutation cells | **0** | 4 |

Opus ranks first because the frozen ordering prioritizes hard-gate pass rate, recall and
severity-weighted recall before precision. Grok was substantially more precise, but its 11 wrong
`CLEAN` failures are unsafe for a terminal checker. Opus never returned `CLEAN`; its principal
failure mode was the opposite: unsupported HIGH or CRITICAL overcalls in ten cells.

## Scenario behavior

- **Registry bridge:** after four replacement pairs, Opus matched 16/18 defects versus Grok 11/18;
  both passed hard gates in 9/10 cells.
- **Snapshot publisher:** both matched only 3/52 defects. Opus passed 5/10 hard gates with no wrong
  `CLEAN`; Grok passed 1/10 and returned seven wrong `CLEAN` verdicts.
- **Workspace boundary:** Opus matched 10/15 defects versus Grok 8/15 and passed 6/10 hard gates
  versus 4/10. Grok's reported findings were precise, but four missed-defect `CLEAN` verdicts
  remained.

## Invalidated cells and replacement

The v1 gold did not specify missing binding-comparand behavior for:

- `DV-SONNET/registry-bridge/run-04`
- `DV-SONNET/registry-bridge/run-05`
- `DV-MAI/registry-bridge/run-02`
- `DV-MAI/registry-bridge/run-04`

No v1 score had been used. Both candidate outputs were excluded for each pair. The rerun made
binding-field presence, corresponding closed error codes and the non-scored malformed-input domain
candidate-visible. All eight replacement verdicts were valid, all eight returned `DO_NOT_MERGE`,
and no replacement workspace was mutated. Opus matched all 14 rerun defects; Grok matched 10.

## Decision boundary

The experiment authorizes the **checker ranking**, not an autonomous replacement:

1. Claude Opus 5 is the supervised primary checker.
2. Grok 4.6 remains the high-precision challenger.
3. Human adjudication is mandatory for Opus HIGH and CRITICAL findings.
4. A Grok `CLEAN` verdict cannot close a task without independent confirmation.

Neither candidate qualifies for unattended terminal review. Opus passed only 20/30 hard gates and
recalled 29/85 defects; Grok's wrong-`CLEAN`, invalid-artifact and workspace-mutation failures are
more severe despite its precision advantage. Planner, test-author, doer and full-stack decisions
are unchanged.
