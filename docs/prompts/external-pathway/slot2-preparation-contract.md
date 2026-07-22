# Slot 2 — ClinVar/VCEP submission **preparation** contract

## Output

Create only:

- `docs/prd/PRD-09-clinvar-vcep-submission-preparation.md`
- `docs/reference/clinvar-vcep-primary-sources-2026-07.md`

(and the persisted three-slot prompt set under `docs/prompts/external-pathway/`).

**Authorized future-implementation scope (spec/authorize only — do not write code here):**
`src/raptor/external/__init__.py` (package marker), `src/raptor/external/models.py` (shared frozen
contracts), `src/raptor/external/{clinvar_map,conformance,state,dryrun}.py`,
`configs/external/{clinvar_field_map.yaml,clinvar_conformance.yaml,clinvar_submission_schema.snapshot.json}`,
`tests/external/**`.

## Goal

Specify — as **planning/research only** — how a RAPTOR `EXTERNAL_SUBMISSION_READY` packet becomes a
**submission-ready, dry-run-validated** ClinVar record and a **VCEP engagement package**, while **guaranteeing
no submission, no contact, and no SCV**. Submission stays gated on PRD-06 gate `PASS` + ADR-0009 ruling +
per-variant qualified sign-off + a final approved policy + registered org + VCEP/qualified authority.

## Sources (ground every claim; date + source-type each external one)

- **Primary-source register** `docs/reference/clinvar-vcep-primary-sources-2026-07.md` — the ClinVar
  Submission API (`.../docs/api_http/`: `dry-run=true` and `apitest` create **no SCV**; `SP-API-KEY`; ≤10,000
  records; weekly release; API auto-processed), submission fields (`assertionCriteria`, `variantSet.variant`
  hgvs|chromosomeCoordinates, `conditionSet.condition` db-enum, the **new** `germlineSubmission[]` →
  `germlineClassification` → `germlineClassificationDescription` shape (legacy `clinvarSubmission`/
  `clinicalSignificance` **rejected**, mutually exclusive), `observedIn.*`,
  `localID`/`localKey`, `clinvarAccession`, `recordStatus` (`novel`/`update` only), top-level
  `clinvarDeletion.accessionSet`), Submission Portal registration, review-status
  stars, ClinGen VCEP Protocol (v12).
- `docs/STRATEGY.md` **Part I §9** (two sign-off levels; no ClinVar submission without a qualified molecular
  geneticist / VCEP), GP-1/3/5/6/8/11/13.
- `docs/DECISIONS.md` **ADR-0009** (ClinVar-derived criterion lineage / masking), **ADR-0010** (vertical reset).
- `docs/prd/PRD-04-candidate-evidence-packet.md` + `src/raptor/packet/{model,state,decisions}.py`
  (`CandidateEvidencePacket`, `ReviewState.EXTERNAL_SUBMISSION_READY`, `DecisionEventType`/`ActorRole`,
  variant-scoped append-only decision log; AAVC reveal-only; `ScorerProvenance` = BIAS row).
- `docs/reference/aavc-prior-art-audit-2026-07.md` (reveal-only comparator boundary), `clinvar-hgvs-golden-corpus.md`.

## Required content (the PRD must specify)

1. **Field mapping** (RAPTOR packet/evidence/decision → ClinVar submission JSON), config-driven
   (`configs/external/clinvar_field_map.yaml`), unknown fields **fail loud**, with an exact mapping table and a
   **do-not-map deny-list** (AAVC/`external_comparators`; `ScorerProvenance` BIAS row; `signed_points`/policy
   internals; run metadata; any PHI).
2. **Direction≠classification gate**: `candidate_direction → germlineClassificationDescription` (inside the new
   `germlineSubmission[].germlineClassification` object) only via a
   per-variant `qualified_molecular_geneticist` decision-log record. **Schema pin**: emit the NEW
   `germlineSubmission`/`germlineClassification`/`germlineClassificationDescription` shape **only**; reject the
   legacy `clinvarSubmission`/`clinicalSignificance` shape and any mixed output (the schema forbids their
   coexistence); add a **schema-freshness re-pin guard** (live-schema HTML sha256
   `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time — block generation on
   drift until human re-pin).
3. **No-submission state machine** extending PRD-04: `SUBMISSION_RECORD_MAPPED →
   SUBMISSION_CONFORMANCE_VALIDATED → (SUBMISSION_DRYRUN_CHECKED, optional) → SUBMISSION_PACKAGE_ASSEMBLED`,
   with terminal `SUBMISSION_AUTHORIZED` **unreachable by construction** (no approved policy, gate ≠ `PASS`, no
   org, no VCEP) and **no production-POST code path**.
4. **Prerequisites** (organization / submitter / API / assertion criteria / reviewer authority) as a checklist
   typed **mechanical vs institutional**; "ready to submit" is false while any institutional item is open.
5. **VCEP contact/engagement package template** (cover letter with non-authoritative framing; method +
   leakage-audit + gate summary; sample packets; calibration/coverage; AAVC prior-art positioning; proposed
   pilot scope; documented CDWG/VCEP contact route) — **assembled, never sent**.
6. **Conflict/version/update/withdrawal** handling mapped to decision-log semantics: conflict = reveal-only
   comparator (never truth, expert reconciliation); version = source-snapshot pins + freshness KPI (GP-5);
   update = `recordStatus=update` + `clinvarAccession` + fresh sign-off + `supersession`; withdrawal =
   the separate top-level `clinvarDeletion.accessionSet[] {accession, reason?}` (**not** `recordStatus=delete`,
   which the live schema rejects — the enum is `novel`/`update` only) + a decision-log withdrawal event (**note the frozen
   `DecisionEventType` lacks one — open dependency**).
7. **Dry-run conformance validator producing no SCV**: **Layer A** offline/deterministic (schema pin to the
   **new `germlineSubmission` shape** + **schema-freshness re-pin guard** that blocks generation on live-schema
   hash drift + business rules + PHI scan + deny-list incl. legacy `clinvarSubmission`/`clinicalSignificance`
   rejection + **no-SCV/no-network invariant**) emitting a machine-readable report;
   **Layer B** optional operator-gated live `dry-run=true`/`apitest` (no SCV, no public data, off by default,
   excluded from automated tests, production URL never targeted).
8. **Submission-ready schema vs actual authority**: an explicit GP-1 section — schema-conformant + dry-run-green
   is **not** authority to submit; preview review status as **1★** unless an approved VCEP is supplied.
9. **Exact outputs + tests** and **what finishes without expert validation vs open dependencies**.

## Acceptance criteria (authored as tests before any implementation)

Cover: mapping determinism + fail-loud (AC1); direction-not-classification per-variant sign-off gate (AC2);
deny-list fail-loud for AAVC/BIAS/run-metadata (AC3); **no-SCV invariant** + no production-POST path (AC4);
per-rule conformance pass/targeted-fail (AC5); PHI scan (AC6); `update` requires `clinvarAccession` and
withdrawal a top-level `clinvarDeletion.accessionSet[]` SCV `accession`, each with a decision-log event (AC7); `SUBMISSION_AUTHORIZED` unreachable (AC8); Layer B opt-in only, absent from tests,
production URL never constructed without `dry-run=true` (AC9); report/record stamped non-authoritative +
would-be review status (AC10); prerequisite checklist typing blocks "ready" while institutional items open
(AC11); **new-shape pin + schema-freshness guard** — new `germlineSubmission`/`germlineClassification`/
`germlineClassificationDescription` only, legacy/mixed rejected, generation blocked on live-schema hash drift
(AC12); review-status honesty 1★-unless-VCEP (FR13).

Include a Definition-of-Ready Task Spec set (A mapping+deny-list; B offline validator; C state
machine+lifecycle) with ≤4 reference files each, and a preservation set (Slot 3). Tester (Gemini) authors
tests before the Sonnet doer; GPT checks. **No** shared PROGRAM/STRATEGY edits; **no** submission, contact,
push, production classification, or SCV.

10. **Frozen build-contract API surface (MagicMock-proof pin — PRD-09 §15/§16).** Because tests-first
    authorship exposed an under-specified doer contract (draft tests could only compile by `MagicMock`-ing every
    type and inventing symbols — e.g. `DecisionEvent` for the real `DecisionLogRecord`; a bare-`dict` return
    from `map_to_clinvar`; boolean-kwarg `PrerequisiteChecklist`; a `pass`-only AC9), the PRD **must pin** the
    exact per-task surface so no invention is possible:
    - **Task A** (`src/raptor/external/models.py` + `clinvar_map.py`): frozen `ClinvarMapConfig` (strict keys;
      `schema_pin_sha256 == PINNED_SCHEMA_SHA256`; unknown YAML key → `ClinvarConfigError`); `VariantSignoff`
      bound **only** via `from_decision_history(history, *, packet, config)` from a **verified PRD-04
      `DecisionHistory`** (QMG role + `REVIEWER_DECISION` + packet/evidence/variant hash match); `MappingResult`
      (`payload`/`status`/`blockers`/`non_authoritative`/`review_status_preview`); `map_to_clinvar(packet,
      config, *, signoff=None) -> MappingResult` that sets `germlineClassificationDescription` **only** from
      `signoff.classification` (never from `candidate_direction`); exact deny-list keys +
      resolved-`PrimaryEvidenceRef` → `ClinvarCitation` mapping (literature+scheme only; unresolved never).
    - **Task B** (`conformance.py`): `ConformanceConfig`/schema-snapshot pin; `ConformanceReport`
      (`is_valid`/`is_authoritative`/`review_status`/`rule_results`/`emitted_scv`/`network_used`);
      `validate_conformance(record, *, config=None, live_hash=None, pinned_hash=PINNED_SCHEMA_SHA256)` —
      **guards raise** (`SchemaFreshnessError`/`ClinvarShapeError`/`PhiDetectedError`/`NoScvInvariantError`),
      **business rules report**; offline, no network client.
    - **Task C** (`state.py` + `dryrun.py`): `ExternalReviewState`, `ExternalContext`, `PrerequisiteType`,
      `PrerequisiteItem`, `PrerequisiteChecklist(items=...)` + `default_checklist`/`missing_institutional`;
      `RecordStatus` (`novel`/`update` only); `validate_record_status`/`validate_withdrawal`/
      `build_clinvar_deletion`/`review_status_preview` static APIs; `SUBMISSION_AUTHORIZED` unreachable via
      `AUTHORIZATION_ENABLED_THIS_INCREMENT is False` (True even with all-`True` context); Layer B
      `LAYER_B_ENABLED is False`, no production URL constant.
    - Typed-error hierarchy rooted at `ExternalError(ValueError)`; **no catch-all**. Add a **tester-correction
      note** mapping each draft-test invention to its pinned replacement (PRD-09 §16).

## Non-goals (hard)

No real submission/transmission/POST to the production endpoint; no SCV; no contact with ClinVar/ClinGen/VCEP/
CDWG; no authoritative classification; no frontend/scheduler/patient output; no credentials in the repo.
