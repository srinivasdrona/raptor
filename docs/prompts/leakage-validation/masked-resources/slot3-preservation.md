# Slot 3 — Preservation & inversion guard (held-out-masked ClinVar comparator regeneration)

## Preserve (semantics that must not change)

- **Full VUS comparator resources are byte-unchanged.** The five full-resource comparator resources and
  the full-resource VUS scoring path (BIAS output sha256
  `0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e`, 6,618 rows) are untouched. Masked
  outputs live only under `masked_namespace`. ADR-0009: "VUS production uses the **full** resources."
- **Static mask set is fixed at five.** `requires_heldout_mask = [PS1, PM5, PM1, PP2, BP1]`
  (`bias_lineage.yaml`, sha256 `743a0248…`). Zero dynamic incidence for `PM1/PP2/BP1` does **not** remove
  them from the mask set (`tsc_bias_lineage_audit_2026-07-10.json` `interpretation_limits`).
- **Direct-copy criteria stay forbidden.** `PS4/PP5/BP6` remain in `eval.config.FORBIDDEN_CRITERIA`;
  masking their fallback inputs is defence-in-depth, **not** a re-enabling — they are never scored.
- **Labels boundary (H1/R-A2).** The masking tool reads variant **identity** only; no benchmark
  `label`/`source`/`review_status` is reachable, and a ClinVar significance is masked as an
  identity-scoped record, never consumed by RAPTOR as a training label.
- **Arm's-length AGPL boundary (ADR-0007).** RAPTOR emits masked **data** + an **independent** audit;
  BIAS's own generators do the rebuild. No `bias_2015`/preprocessing import or source-text copy.
- **Reference discipline (R-A10/R-A11).** Canonical SPDI + checksum-verify is reused from
  `ingest.normalizer`; a reference/normalization disagreement fails loud, never a silent correction.

## Reconciliations the doer MAY make (not weakening)

- Masking a held-out variant's **own** ClinVar record from the PS1/PM5 inputs while **retaining** other
  variants' records at the same residue/gene — the mask removes the held-out variant's self-evidence, not
  the legitimate comparator evidence for its neighbours.
- Recording a held-out id that matches **zero** ClinVar records as an expected no-op (the variant is
  simply absent from ClinVar), distinct from the fatal multi-match ambiguity.

## Prohibited (weakening tests/config to match an implementation)

- Do **not** shrink the mask set to the dynamically-fired subset (`PS1/PM5`) because `PM1/PP2/BP1` fired
  zero times — static lineage governs; all five (plus the three fallbacks) are masked.
- Do **not** mask by raw ClinVar coordinate string equality; normalize to canonical GRCh38 SPDI first (an
  indel echo mismatch would silently leave a held-out variant unmasked).
- Do **not** over-remove: dropping a non-held-out ClinVar record to make an aggregate "look masked"
  corrupts the comparator for every other variant — a silent row-loss breach.
- Do **not** mutate the originals or write a masked file inside a full-resource path.
- Do **not** import `bias_2015`/BIAS preprocessing or reimplement a generator's aggregation to "prove"
  conservation by construction; the audit **independently re-derives** the aggregates.
- Do **not** trust the generator's own output as the conservation oracle; the audit re-normalizes every
  referenced identity and recomputes every aggregate from the masked ClinVar.
- Do **not** read any benchmark `label`/`source`/`review_status` value, or treat a ClinVar significance
  as a training signal.

## Highest-risk inversion failures

1. **Incidence-driven mask shrink.** Masking only the criteria that fired (`PS1/PM5`) and skipping the
   zero-incidence `PM1/PP2/BP1`. A future VUS-distribution or a re-score with different data reactivates
   the unmasked aggregate leak. **Guard:** AC-M3 injects a **non-firing** held-out variant into a domain
   aggregate and requires the audit to flag it.
2. **Raw-coordinate mask miss (indel echo).** Masking by raw string leaves a left/right-shifted indel
   unmasked; the held-out variant survives transitively in a domain/gene count. **Guard:** AC-M1/M2 use
   canonical-SPDI membership as the oracle; the fixture includes an echo-shifted indel.
3. **Silent over-removal.** Dropping extra ClinVar records (or a whole gene) to force a clean aggregate,
   corrupting the comparator for non-held-out variants and inflating measured recall. **Guard:** AC-M2
   conservation identity (`remaining == input_total − matched_removed`, set-difference exact).
4. **Full-resource contamination.** Writing masked outputs over, or re-pointing the VUS path at, the
   masked namespace — so production VUS scoring silently loses legitimate comparator evidence. **Guard:**
   AC-M7 full-resource byte-invariance + output-path containment check.
5. **Aggregate laundering.** The audit recomputes a domain rate using the **generator's** cached total
   (which may still include the held-out contributor) instead of re-deriving from the masked ClinVar.
   **Guard:** AC-M4 hand-computed aggregate oracle; the audit must recompute from the masked source.

No production code, tests, `docs/PROGRAM.md`, `docs/STRATEGY.md`, or risk documents are modified by this
planning task. The untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor
deleted.
