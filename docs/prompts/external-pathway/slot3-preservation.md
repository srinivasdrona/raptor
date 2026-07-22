# Slot 3 — external-pathway preservation and inversion

## Preserve

- **PRD-04 is the sole entry point.** Only an `EXTERNAL_SUBMISSION_READY` packet may be mapped; PRD-04's
  gates (approved non-null policy + non-null direction + gate `PASS` + ADR-0009 mask ruling + two distinct QMG
  sign-offs + primary grounding) are **not** re-litigated or weakened here.
- **Two sign-off levels (STRATEGY §9) stand.** Operator approval is internal-only; any ClinVar submission or
  externally meaningful classification requires a qualified molecular geneticist / VCEP. This PRD adds a
  boundary, not a shortcut.
- **Candidate direction is a review direction, never a classification.** Mapping to
  `germlineClassificationDescription` (inside the new `germlineSubmission[].germlineClassification` object)
  requires a per-variant qualified sign-off decision-log record.
- **Reveal-only comparator discipline (AAVC).** The AAVC comparator and any existing-ClinVar classification are
  reveal-only, excluded from evidence/citation, never a truth label; `ScorerProvenance` resolves to a BIAS raw
  row and is never primary evidence.
- **Append-only decision log** semantics (variant-scoped, hash-chained, `predecessor_packet_id` supersession)
  are mirrored, not bypassed; no reviewer/pattern decision is written to `classification_versions`.
- **No frozen doc is edited.** No change to PROGRAM, STRATEGY, DECISIONS, RISK_REGISTER, PRD-01/03/04/06, or
  the scorer/eval/KB/packet internals. New artifacts land only under `docs/prd/PRD-09-*`,
  `docs/reference/clinvar-vcep-*`, `docs/prompts/external-pathway/**`, and later `configs/external/**`,
  `src/raptor/external/**`, `tests/external/**`.
- **PRD-04 types are imported, never re-declared.** The pinned Task A/B/C surface (PRD-09 §15) binds to the
  **verified** `src/raptor/packet/{model,decisions}.py` symbols — `CandidateEvidencePacket`, `ReviewState`,
  `GateStatus`, `CandidateDirection`, `CanonicalVariantIdentity`, `PrimaryEvidenceRef`, `ResolutionStatus`,
  `ScorerProvenance`, `DecisionLogRecord`, `DecisionHistory`, `DecisionEventType`, `ActorRole`. There is **no**
  `DecisionEvent` type; sign-off is bound via `VariantSignoff.from_decision_history(...)`. The frozen contract
  is **MagicMock-proof**: a mock cannot satisfy the QMG-role/event-type/hash-match binder.
- **Buildable ≠ authoritative (GP-1).** Every artifact is planning/mechanical; the increment creates **no SCV**,
  contacts **no one**, and classifies **nothing**.

## Four failure modes (and their inversions)

1. **False authority at the submission boundary (R-G5).** A schema-valid, dry-run-green record is read as
   *submittable* / *classified*. **Invert:** every mapped record + conformance report is stamped
   non-authoritative, previews review status as **1★ unless an approved VCEP**, and the PRD states explicitly
   that schema-conformance is not authority (GP-1). Actual authority = registered org + VCEP/3★ + per-variant
   sign-off + gate `PASS` + final policy.

2. **Accidental / silent submission.** A code path POSTs to the production submissions endpoint, or the live
   dry-run runs by default. **Invert:** `SUBMISSION_AUTHORIZED` is unreachable by construction; there is **no**
   function that POSTs without `dry-run=true`; Layer B is off by default, operator-gated, key out-of-repo, and
   excluded from automated tests; a test greps for and forbids any un-`dry-run` production POST.

3. **Circular / laundered evidence, or wrong-shape output.** AAVC or a BIAS `ScorerProvenance` row is emitted
   as a ClinVar `citation`/evidence, or a raw census direction / `signed_points` is written as a
   classification, or a candidate direction is auto-copied to `germlineClassificationDescription`, or the
   output uses the **legacy `clinvarSubmission`/`clinicalSignificance` shape** (or mixes it with the new
   `germlineSubmission`). **Invert:** fail-loud do-not-map deny-list; per-variant qualified sign-off gate for
   direction→classification; only **resolved primary** PubMed/DOI refs become citations; **pin the new
   `germlineSubmission`/`germlineClassification`/`germlineClassificationDescription` shape only** (live schema
   verified 2026-07-12, HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`,
   point-in-time), reject legacy/mixed, and a **schema-freshness re-pin guard** blocks generation on live-schema
   hash drift until human re-pin.

4. **Lifecycle / PHI leakage.** An update loses its `clinvarAccession` linkage, a withdrawal loses its
   `clinvarDeletion` SCV `accession`, a withdrawal has no audit event, or PHI reaches a public field.
   **Invert:** `recordStatus="update"` requires `clinvarAccession`; withdrawal is the **separate top-level**
   `clinvarDeletion.accessionSet[] {accession, reason?}` (the live schema's `recordStatus` enum is
   `novel`/`update` only — `delete` is rejected), each with a decision-log event (supersession, or a specified
   new `WITHDRAWAL` event — noted as an open dependency on the frozen `DecisionEventType` enum); a PHI scan
   fails on any identifier in `localID`/`localKey`/`comment`;
   source-snapshot pins + freshness KPI (GP-5) keep versioned records honest.

## Inversion test (rubber-duck)

If a reader could conclude that RAPTOR **has submitted**, **has contacted a VCEP**, **has an authoritative
classification**, or **could submit today by running the code**, the PRD has failed. The correct reading:
RAPTOR has a *prepared, conformance-checked, non-authoritative* package and an explicit, mechanically-proven
**wall** between preparation and submission.
