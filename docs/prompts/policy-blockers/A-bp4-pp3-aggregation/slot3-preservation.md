# Slot 3 — Preservation & inversion guard (BP4/PP3 aggregation defect)

## Preserve (semantics that must not change)

- **Vendored AGPL source is byte-frozen.** The pinned BIAS 3.0.0 tree
  (`D:\AIProjects\raptor-data\sources\BIAS-2015`, commit `ade13f206f…`) is **not** edited. The correction
  lives entirely on the RAPTOR side, over observable output (ADR-0007 arm's-length).
- **Scorer parsing faithfulness.** `parse_rationale` still emits BIAS's **emitted** (buggy) strength for
  every fired criterion, unchanged. The correction is a **separate eval-side annotation**, never an
  in-place rewrite of `parse.py`, the scorer contract, or the scorer output.
- **Emitted strength stays visible.** `AggregationCorrection` carries **both** `emitted_strength` and
  `corrected_strength`. The defect must remain observable downstream; nothing overwrites the emitted value
  so the discrepancy is auditable.
- **Lineage/disposition invariance.** BP4/PP3 stay `label_independent_reference_or_predictor` / `allowed`
  in `configs/eval/bias_lineage.yaml`; the lineage policy, registry, and audit are untouched. The
  correction changes strength only — never lineage, direction, can-fire membership, or disposition.
- **Labels boundary (R-A2/H1).** No benchmark/held-out/label file is reachable from
  `predictor_aggregation.py`; the corrected strength is a function of observable BIAS output + config only.
- **Config-as-policy.** The corrected aggregation rule + weight map live in
  `configs/eval/predictor_aggregation.yaml` (schema-validated, version-pinned), never hardcoded in the
  wrapper.
- **Probes precede the correction.** The synthetic oracle (Probe 1), the real-corpus diff (Probe 2), and
  the decidability proof (Probe 3) are authored/run **before** the route decision; the decision is derived
  from their measured output, not asserted.

## Reconciliations the doer MAY make (not weakening — adding a correct, arm's-length layer)

- Adding the new config, wrapper module, probe script, and their tests.
- Recording the corrected strength as a **new annotation** consumed by decision D, alongside (never
  replacing) BIAS's emitted strength.
- Choosing the **wrapper** route when Probe 3 shows `undecidable == 0` (the expected result) — this is the
  arm's-length correct fix, not a shortcut.
- Documenting a good-citizen **upstream PR proposal** against the external `bitscopic/BIAS-2015` repo
  (fixing `best_score` at L944–954 / L491–503) in the report/notes.

## Prohibited (weakening tests/config, or crossing the AGPL boundary)

- Do **not** edit the vendored AGPL BIAS source to "just fix `best_score`", and do **not** import
  `bias_2015` into RAPTOR. The pin stays byte-identical.
- Do **not** change the pinned BIAS commit, or adopt/merge the upstream fix, as part of this task
  (adoption is gated on a separate re-pin + full re-score + re-validation).
- Do **not** overwrite BIAS's emitted strength in `parse_rationale`, the scorer contract, or the scorer
  output — the correction is a side annotation only.
- Do **not** treat an undecidable rationale as pass-through / silently emit the emitted strength as if it
  were corrected — an undecidable row **fails loud** (`AggregationUndecidableError`).
- Do **not** derive the corrected strength from labels, the census fired-set, or benchmark incidence — it
  is derived per-variant from the observable per-tool tokens + the config rule only.
- Do **not** hardcode the aggregation rule, caps, or weight map in the wrapper (they live in config).
- Do **not** silently reproduce BIAS's asymmetry (PP3 over-bump / BP4 no-bump); the corrected rule is
  symmetric and explicit in config, and the divergence from emitted is measured, not hidden.
- Do **not** use the corrected strength to re-call / re-classify any variant — producing a
  clinical classification is out of scope (that is decision D's *unapproved, non-authoritative* policy;
  A only specifies + measures).
- Do **not** patch a test fixture (e.g. a frozen BIAS output slice) to mask the emitted-vs-corrected
  divergence.

## Highest-risk inversion failures

1. **AGPL-edit shortcut.** Editing the vendored `pathogenic_classifiers.py` / `benign_classifiers.py` (or
   importing `bias_2015`) to fix the bug in place — violates the arm's-length boundary (ADR-0007) and
   silently changes the pinned engine's behavior without a re-pin/re-score. **Guard:** AC-A5 — no
   `bias_2015` import, pin byte-unchanged; the fix is a RAPTOR-side wrapper or an external PR proposal.
2. **Silent in-place mutation.** Overwriting BIAS's emitted strength in the scorer path so downstream can
   no longer see the defect existed — destroys auditability and blurs which value fed a candidate
   direction. **Guard:** AC-A2/A6 — both emitted and corrected are carried; `parse_rationale` output
   unchanged.
3. **Fabricated decidability.** Choosing the wrapper route without the Probe-3 information-completeness
   proof, then silently emitting the emitted strength for rows the wrapper couldn't reconstruct.
   **Guard:** AC-A4 — per-corpus decidability proof; undecidable rows fail loud and (if any) force the
   upstream route.
4. **Materiality by assertion.** Asserting a magic correction/flip count instead of deriving it from the
   real corpora, or dismissing the defect as immaterial without measuring the 92%-BP4-Strong-driven LB
   directions. **Guard:** AC-A3 — the counts are derived and persisted from the census + held-out TSVs.
5. **Scope creep into classification.** Using the corrected strength to produce a call/worklist — that is
   an unapproved production-policy action (decision D), gated on validation + expert sign-off. **Guard:**
   AC-A6 — no clinical classification; strength annotation only.

No production code, tests, strategy, program, or risk documents are modified by this planning task. The
untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
