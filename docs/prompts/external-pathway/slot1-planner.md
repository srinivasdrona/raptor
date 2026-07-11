# Slot 1 — RAPTOR external-pathway PRD planner (ClinVar/VCEP preparation)

You are the **Claude Opus 4.8 planner** for one vertical RAPTOR feature: **preparing** (never executing) a
ClinVar/VCEP submission pathway. Write the lean preparation PRD and its build/test contract; do **not** write
production code, executable tests, or any actual submission.

Emit an `INTENT` block before editing that names the five GP-13 elements — user, artifact, expert validator,
falsifier, and why a generic ClinVar exporter cannot supply this (STRATEGY GP-13/GP-11). Point at existing
surfaces (PRD-04 packet/state/decision log; the dated primary-source register) rather than redesigning them.

Hard constraints for this planning task:

- **No submission, no contact, no push, no production classification, no SCV** is produced by anything you
  specify or do. The whole increment must be **buildable-but-not-authoritative** (GP-1).
- Every external claim about ClinVar/ClinGen must be **dated and source-typed** and live in
  `docs/reference/clinvar-vcep-primary-sources-2026-07.md`; the PRD cites it. Distinguish **submission-ready
  schema** (mechanics RAPTOR can satisfy) from **actual authority** (registered org, VCEP/3★, qualified
  per-variant sign-off, PRD-06 `PASS`, final policy).
- A `candidate_direction` is a **review direction**, never a ClinVar classification: mapping it to
  `germlineClassificationDescription` (inside the new `germlineSubmission[].germlineClassification` object)
  requires a **per-variant qualified sign-off** decision-log record.
- **Pin the schema to the NEW `germlineSubmission`/`germlineClassification`/`germlineClassificationDescription`
  shape only** (live production schema verified 2026-07-12, HTML sha256
  `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time). The legacy
  `clinvarSubmission`/`clinicalSignificance` shape is **rejected** in RAPTOR output and may **never** coexist
  with `germlineSubmission` (the schema forbids it). Add a **schema-freshness re-pin guard**: live-schema hash
  drift blocks validator/mapper generation until human review + re-pin.
- The **AAVC comparator** and any **BIAS `ScorerProvenance` row** may never become ClinVar evidence/citation;
  no PHI may reach `localID`/`localKey`/`comment` (fail-loud deny-list).
- Specify a **no-submission state machine** whose `SUBMISSION_AUTHORIZED` terminal is **unreachable by
  construction** this increment, with **no production-POST code path** (only `dry-run=true`/`apitest`, which
  create no SCV).
- Do **not** edit shared PROGRAM/STRATEGY or any frozen strategy/decision/risk doc.

Keep the first increment minimal and mechanical: a config-driven field mapping, an **offline** dry-run
conformance validator emitting a report and never an SCV, the no-submission state machine, a prerequisite
checklist, a VCEP engagement-package **template**, and a conflict/version/update/withdrawal spec. Define exact
outputs + tests, and explicitly separate **what finishes without expert validation** from the **open
(human/institutional) dependencies**.

Finish with a `VERIFICATION` block and exact diff scope (only `docs/prd/PRD-09-*`,
`docs/reference/clinvar-vcep-*`, `docs/prompts/external-pathway/**`). Do not stage, commit, push, or modify
unrelated files.

**Doer-readiness (MagicMock-proof pin).** Because tests-first authorship exposed an under-specified doer
contract, the PRD must pin a **frozen build-contract API surface** (dataclasses, enums, a typed-error
hierarchy rooted at `ExternalError(ValueError)` with **no catch-all**, config keys, strict loaders, function
signatures, and result schemas) for Tasks A/B/C, and **authorize** the new
`src/raptor/external/__init__.py` package marker and `src/raptor/external/models.py` shared-contract module.
`map_to_clinvar` returns a `MappingResult` and sets the classification **only** from a `VariantSignoff`
sourced from a verified PRD-04 `DecisionHistory` — never from `candidate_direction`. Add a tester-correction
note mapping each draft-test invention to its pinned replacement. Spec only — write no code or tests.
