# PRD-09 — ClinVar / VCEP Submission **Preparation** (field mapping + no-submission state machine + dry-run conformance validator)

> **Status:** Draft / planning increment — **preparation & research artifacts only. No submission, no
> contact, no production classification, no SCV is produced by anything in this PRD.** · **Owner:**
> @dronasrinivas · **Phase:** external-pathway (post-PRD-04) · **Last updated:** 2026-07-12 ·
> **Branch:** `track/external-pathway-2026-07` · **Source commit:** `e52e855` ·
> **API-pinned (§15/§16):** tests-first authorship exposed under-specified Task A/B/C APIs; §15 pins a frozen,
> MagicMock-proof build-contract surface and §16 records the tester-correction. Revised Ready claim in §17.
>
> **Format:** lean PRD (Context · Goals/Non-goals · Users · Functional · Non-functional · Acceptance ·
> Dependencies · Risks · Open questions) + build contract + Definition-of-Ready Task Specs. Acceptance
> criteria are authored as executable tests by the test-author **before** the doer implements; the checker
> re-verifies (STRATEGY Part II §4).
>
> **Links:** STRATEGY Part I §6 (three vertical lines), **§9** (scope + **two sign-off levels** + "no ClinVar
> submission without a qualified molecular geneticist / VCEP") · **GP-1** (validation ceiling: buildable ≠
> authoritative), **GP-3** (oracle-first), **GP-5** (provenance/freshness), **GP-6** (config-as-truth),
> **GP-8** (adversarial honesty), **GP-11** (enabler-not-decision-maker), **GP-13** (vertical scope) ·
> DECISIONS **ADR-0009** (ClinVar-derived criterion lineage / masking), **ADR-0010** (vertical reset) ·
> **PRD-04** (candidate evidence packet + `EXTERNAL_SUBMISSION_READY` terminal state — the sole entry point
> here) · PRD-06 (held-out gate that authorizes any external disposition) · PRD-02/PRD-07 (variant
> normalization + ClinVar term vocabulary) · **Primary sources:**
> `docs/reference/clinvar-vcep-primary-sources-2026-07.md` (every external claim dated + source-typed) ·
> `docs/reference/aavc-prior-art-audit-2026-07.md` (reveal-only comparator boundary).

---

## 0. Intent (GP-13 gate — named five)

| Element | This feature |
|---|---|
| **(a) TSC/mTOR user** | The TSC VCEP curator / qualified molecular geneticist (GP-3 oracle) who will *eventually* submit expert-reviewed TSC1/TSC2 classifications to ClinVar, and the RAPTOR operator who must **prepare** a conformant, auditable submission package **without** submitting. |
| **(b) Artifact** | (1) A deterministic **field-mapping** from RAPTOR packet/evidence/decision artifacts to the ClinVar submission schema; (2) an **offline dry-run conformance validator** that emits a report and **never an SCV**; (3) a **no-submission state machine** that is unreachable-to-submission by construction; (4) an **organization/submitter/reviewer prerequisite** checklist and a **VCEP contact/engagement package template**; (5) a **conflict/version/update/withdrawal** handling spec. |
| **(c) Expert validator** | Mechanical checks (schema conformance / no-SCV invariant / state reachability) validate **form**. A **qualified molecular geneticist / VCEP** is the only validator of any externally meaningful **classification**, and ClinGen/NCBI are the only authorities for **VCEP status** and **organization registration** (STRATEGY Part I §9). Schema-validity is explicitly **not** authority (GP-1). |
| **(d) Falsifier** | Any of: the pipeline **creates or transmits an SCV** (or calls the ClinVar *production* submissions endpoint) in this increment; OR a `candidate_direction` (a *review direction*) is mapped to a ClinVar `germlineClassificationDescription` **without** a per-variant qualified sign-off record; OR the generated output emits the **legacy `clinvarSubmission`/`clinicalSignificance` shape**, or **mixes** legacy and new `germlineSubmission` in one submission (the live schema forbids their coexistence); OR the state machine can reach an "authorized/submitted" state **without** gate `PASS` + per-variant sign-off + a final approved policy; OR the **AAVC comparator** or a **BIAS `ScorerProvenance` row** is emitted as a ClinVar `citation`/evidence; OR any PHI reaches `localID`/`localKey`/`comment`; OR an **update** is expressed without the required `clinvarAccession` (SCV), or a **withdrawal** without a top-level `clinvarDeletion.accessionSet[]` SCV `accession`, in either case lacking the decision-log event; OR the validator/mapper is generated against a **drifted live schema hash** without human review + re-pin (FR2.1); OR the dry-run live check is **on by default** or runs in automated tests; OR the plan claims schema-conformance as authority to submit. |
| **(e) Why a generic product cannot supply it** | Generic ACMG/interpretation platforms emit a *call* and a generic ClinVar exporter. RAPTOR must carry the **leakage-audited** (ADR-0009), **gate-blocked** (PRD-06), **two-sign-off** (STRATEGY Part I §9), **review-direction-not-classification** discipline **through** the submission boundary — mapping only *after* per-variant expert authority, and proving non-submission mechanically. That is TSC-vertical governance, not a generic export (GP-11/GP-13). |

> This section IS the persisted INTENT block. It names the five GP-13 elements and points at existing
> surfaces (PRD-04 packet/state/decisions; the primary-source register) rather than redesigning them.

---

## 1. Context

PRD-04 ends at `EXTERNAL_SUBMISSION_READY` — a packet cleared, per its own gates, for an external worklist.
It deliberately excludes "ClinVar-submission automation" (PRD-04 §Output surfaces). This PRD prepares the
**next** boundary: turning an `EXTERNAL_SUBMISSION_READY` packet into a **submission-ready, dry-run-validated
ClinVar record** and a **VCEP engagement package**, while guaranteeing that **no actual submission happens**
until human/institutional authority exists.

Grounding facts (dated in the primary-source register):

- ClinVar accepts submissions via the NCBI Submission Portal Public API; **`?dry-run=true`** and the
  **`apitest`** endpoint both create **no public record / no SCV** (register §1.7–1.8). These anchor the
  dry-run validator.
- A schema-valid submission still yields **1★ ("criteria provided, single submitter")** unless submitted by
  an approved **ClinGen VCEP** (3★, "reviewed by expert panel") (register §3). TSC has **0** 3★ records today
  (STRATEGY.md).
- STRATEGY Part I §9: **any ClinVar submission requires a qualified molecular geneticist / VCEP**; operator approval
  is internal-only.

**This increment is buildable now; it is not authoritative and cannot submit (GP-1).**

## 2. Goals / Non-goals

**Goals**

1. A deterministic, config-driven **field mapping** (RAPTOR → ClinVar submission JSON) with an explicit
   **do-not-map** deny-list.
2. An **offline conformance validator** producing a machine-readable report, provably emitting **no SCV** and
   opening **no production network connection**.
3. A **no-submission state machine** extending PRD-04, with actual submission **unreachable by construction**.
4. A **prerequisite checklist** (organization, submitter, API, assertion criteria, reviewer authority).
5. A **VCEP contact/engagement package template** (assembled, never sent).
6. A **conflict / version / update / withdrawal** handling spec mapped to internal decision-log semantics.
7. An enumerated list of **exact outputs + tests**, and an explicit statement of **what finishes without
   expert validation vs. what remains an open (human/institutional) dependency**.

**Non-goals (hard)**

- **No** real submission, transmission, POST to the production submissions endpoint, or SCV creation.
- **No** contact with ClinVar, ClinGen, any VCEP, CDWG, or third party.
- **No** production/authoritative classification of any variant; **no** conversion of a candidate direction to
  a ClinVar classification without a per-variant qualified sign-off.
- **No** editing of shared PROGRAM/STRATEGY (or other frozen strategy/decision docs).
- No frontend, no scheduler/flow, no patient-facing output, no credential storage in the repo.

## 3. Field mapping (RAPTOR packet/evidence/decision → ClinVar submission)

**FR1 — Config-as-truth mapping.** The mapping is a pinned machine-readable config
(`configs/external/clinvar_field_map.yaml`) consumed by a pure mapper; unknown/unmapped source fields **fail
loud** (GP-6). The mapper reads an `EXTERNAL_SUBMISSION_READY` packet + its decision log; it never reads
labels/oracle/benchmark files.

**FR2 — Mapping table (single small TSC variant, germline).** Field names on the ClinVar side follow the
primary-source register §2. **Schema pinned (verified 2026-07-12, RESOLVED — prior HARD-BLOCK closed):** the
live production schema page (HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`,
point-in-time — register §2.5) contains the **new top-level `germlineSubmission[]` array**, each record
requiring a **`germlineClassification`** object whose **required** classification field is
**`germlineClassificationDescription`**. The same page still exposes the **legacy** `clinvarSubmission[]` /
`clinicalSignificance` shape, and the schema **explicitly forbids the old `clinvarSubmission` and new
`germlineSubmission` from appearing together**. **RAPTOR pins its mapping/validator to the NEW
`germlineSubmission` / `germlineClassification` / `germlineClassificationDescription` shape only and MUST
reject any generated output that emits the legacy `clinvarSubmission`/`clinicalSignificance` shape or mixes
the two** (register §2.1–§2.2, §6.1). `recordStatus` (`novel`/`update`) and the separate top-level
`clinvarDeletion` withdrawal object remain verified against the live schema (register §2.1–§2.2, 2026-07-12).

| RAPTOR source (INTERNAL) | ClinVar target (NEW `germlineSubmission` shape — pinned) | Rule / transform |
|---|---|---|
| — (submission envelope; container) | top-level **`germlineSubmission[]`** array (NOT legacy `clinvarSubmission[]`) | RAPTOR emits records into `germlineSubmission[]` **only**; emitting `clinvarSubmission`/`clinicalSignificance`, or both containers together, **fails loud** (FR2 pin; register §2.1). |
| `identity.canonical_spdi` (+ `transcript`) | `germlineSubmission[].variantSet.variant.hgvs` **or** `chromosomeCoordinates` (mutually exclusive) | SPDI → HGVS or GRCh38 coordinates via PRD-02 normalizer + the ClinVar/HGVS golden corpus; exactly one form; `assembly="GRCh38"`. |
| `identity.gene` (`TSC1`/`TSC2`) | `germlineSubmission[].variantSet.variant.gene.symbol` | HGNC symbol; direct. |
| `candidate_direction.direction` (`candidate_LP_review`/`candidate_LB_review`/…) | `germlineSubmission[].germlineClassification.germlineClassificationDescription` | **Gated, non-mechanical.** Only a **per-variant qualified sign-off** decision-log record may authorize `candidate_LP_review→"Likely pathogenic"` / `candidate_LB_review→"Likely benign"`. A review direction is **never** auto-copied (FR7). |
| QMG sign-off timestamp (decision log) | `germlineSubmission[].germlineClassification.dateLastEvaluated` | `yyyy-mm-dd` from the sign-off record, not the run date. |
| `candidate_direction.policy_id`/`policy_version` (the VCEP ACMG specification) | submission-level `assertionCriteria {db,id}` or `{url}` | The VCEP's published ACMG/AMP TSC specification (PubMed/DOI or uploaded file). |
| template-rendered narrative + `criterion.rationale` | `germlineSubmission[].germlineClassification.comment` / `explanationOfInterpretation` | Deterministic template expansion only; **no PII**; ACMG codes plus prose. |
| `criterion.primary_evidence_refs[]` where `source_type ∈ {PubMed, DOI, pmc}` and `resolution_status=resolved` | `germlineSubmission[].germlineClassification.citation[] {db,id}` | Only **resolved primary** refs. |
| condition (fixed: tuberous sclerosis) | `germlineSubmission[].conditionSet.condition {db,id}` | `db ∈ {MONDO, MedGen, OMIM}`; id **curator-verified** (register §6.5). |
| — (curation submission; no patient obs) | `germlineSubmission[].observedIn {collectionMethod:"curation", alleleOrigin:"germline", affectedStatus:"not provided"}` | Fixed defaults; RAPTOR holds no primary patient observation. |
| packet variant local id | `germlineSubmission[].localID` | Public, stable, **PHI-free**. |
| `packet_id` / `evidence_core_hash` | `germlineSubmission[].localKey` (variant–condition linking id) | Deterministic. |
| prior SCV (from decision log, if any) | `germlineSubmission[].clinvarAccession` | Required for `update` (SCV of the record being revised); also for `novel` only if accessions were reserved (FR9). |
| supersession state (new vs revise-prior-SCV) | `germlineSubmission[].recordStatus` (`novel`/`update`) | Enum is **only** `novel`/`update` (live schema verified 2026-07-12; register §2.1–§2.2/§6.2). There is **no `recordStatus="delete"`** value. |
| withdrawal / retraction state | top-level `clinvarDeletion.accessionSet[] {accession, reason?}` | Withdrawal is a **separate top-level object** (sibling of `germlineSubmission[]`), **not** a `recordStatus`: each `accessionSet` entry carries the prior SCV `accession` (**required**) + an optional public `reason` (FR9; register §2.1). |

**FR2.1 — Schema pin + freshness/re-pin guard (GP-5).** The mapper/validator pin to the **new
`germlineSubmission`/`germlineClassification`/`germlineClassificationDescription`** shape captured in a
snapshot that records the **live schema page HTML sha256** (`3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`,
verified 2026-07-12 — a **point-in-time** value, **not** permanent; register §2.5). A **schema-freshness
guard** re-hashes the live schema page and compares it to the pinned hash: **on drift, validator/mapper
generation is blocked** until a human reviews the schema diff and re-pins. This closes the germline
object-name block by construction while preventing a silently-stale schema from producing false-conformant
records. **Legacy/mixed rejection:** the mapper emits `germlineSubmission[]` only and **fails loud** if asked
to emit `clinvarSubmission`/`clinicalSignificance`, or if both containers would coexist (the schema forbids
their coexistence).

**FR3 — Do-not-map deny-list (fail loud).** The mapper **must reject** (never silently drop) any attempt to
place into a ClinVar field: (a) the **AAVC / any `external_comparators`** value; (b) a **`ScorerProvenance`
(BIAS raw row)** as citation/evidence; (c) `signed_points`, internal policy internals, or a raw census
direction as a classification; (d) **run metadata** (`run_id`, `generated_at`); (e) any value failing the
PHI scan; (f) the **legacy `clinvarSubmission`/`clinicalSignificance` container**, or any output mixing it
with `germlineSubmission` (FR2.1).

**FR4 — Non-authoritative marking.** Every mapped record is emitted into a `dry_run` envelope stamped
non-authoritative, carrying the source `packet_id`/`evidence_core_hash`, `code_commit`, schema snapshot id,
and the review status it would receive (**1★ unless an approved VCEP** — FR13). No mapped record is ever an
SCV.

## 4. No-submission state machine (fail-closed, extends PRD-04)

**FR5 — States (all pre-submission; none creates an SCV).** Entry is a PRD-04 `EXTERNAL_SUBMISSION_READY`
packet.

| State | Meaning | Guard to enter |
|---|---|---|
| `SUBMISSION_RECORD_MAPPED` | Packet mapped to a candidate ClinVar JSON record (dry-run envelope). | Source packet is `EXTERNAL_SUBMISSION_READY`; per-variant qualified sign-off record exists for the direction→classification (FR7); deny-list clean (FR3). |
| `SUBMISSION_CONFORMANCE_VALIDATED` | Passed the offline conformance validator (§6). | All conformance rules pass; **no-SCV invariant** holds. |
| `SUBMISSION_DRYRUN_CHECKED` *(optional)* | Passed ClinVar `dry-run=true` **or** `apitest` (format/comm/validation; **no public record**). | Operator-authorized flag set; API key present out-of-repo; **never in automated tests**. |
| `SUBMISSION_PACKAGE_ASSEMBLED` | Org/submitter prereqs + assertion criteria + VCEP engagement package assembled. | Prerequisite checklist (§7) complete as a *record of readiness*, not proof of authority. |
| `SUBMISSION_AUTHORIZED` **(terminal; UNREACHABLE this increment)** | Cleared to actually submit. | Requires **all** of: PRD-06 gate `PASS`; ADR-0009 mask ruling landed; per-variant qualified sign-off; **final approved production policy**; **registered ClinVar organization**; **approved VCEP / named qualified submitter**; explicit operator authorization. |

**FR6 — Unreachable by construction.** `SUBMISSION_AUTHORIZED` is unreachable in this increment (no approved
policy, gate not `PASS`, no registered org, no VCEP). **Actual transmission has no code path at all** — there
is no function that POSTs to `https://submit.ncbi.nlm.nih.gov/api/v1/submissions/` without `dry-run=true`.
Tests assert the production-submit path does not exist / is refused. (Mirrors PRD-04's unreachable
`EXTERNAL_SUBMISSION_READY`.)

**FR7 — Direction→classification requires per-variant sign-off.** No transition may set
`germlineClassificationDescription` (inside `germlineSubmission[].germlineClassification`) from
`candidate_direction` unless a decision-log `reviewer_decision` by a `qualified_molecular_geneticist`
(per-variant) authorizes it. Absent that, the field stays unset and the record cannot advance past
`SUBMISSION_RECORD_MAPPED`.

## 5. Prerequisites — organization / submitter / reviewer

**FR8 — Prerequisite checklist (record of readiness, not authority).** Emit a machine-checkable checklist
distinguishing **mechanical** items (RAPTOR can complete) from **institutional** items (external authority):

| Prerequisite | Type | Owner | Source |
|---|---|---|---|
| MyNCBI account (ORCID/login.gov/eRA/university) + profile (email, name, notifications) | institutional | submitter | register §1.4, submission_portal |
| **Register organization** once; accept **Terms of submission**; set affiliation | institutional | org admin | submission_portal |
| Authorize additional submitters under the org | institutional | org admin | submission_portal |
| **Service account + `SP-API-KEY`** (request via `clinvar@ncbi.nlm.nih.gov`); store **out of repo** | institutional | org admin | register §1.5 |
| **Assertion criteria** document (VCEP ACMG TSC specification) uploaded or citable | mixed | VCEP | register §2.1, §4.4 |
| **Reviewer authority**: approved ClinGen **VCEP** (3★) *or* named qualified molecular geneticist (1★) | institutional | ClinGen / QMG | register §3–§4, STRATEGY Part I §9 |
| Condition identifier (MONDO/MedGen/OMIM for TSC) confirmed | mechanical→curator-verified | curator | register §6.5 |

## 6. Dry-run conformance validator (produces **no SCV**)

**FR10 — Layer A (primary; offline; deterministic; no network, no credentials).** Validate each mapped record
against a **pinned ClinVar submission JSON schema snapshot** + business rules, emitting a machine-readable
report (`pass`/`fail` per rule per record):

0. **Schema-pin freshness (FR2.1):** the pinned snapshot's live-schema HTML sha256 matches the recorded pin
   (`3ed6b64…`, register §2.5); **on drift the validator refuses to run** (blocks generation) pending human
   review + re-pin. The record uses the **new `germlineSubmission[]` container** and **not** the legacy
   `clinvarSubmission`/`clinicalSignificance`; a record emitting the legacy shape, or mixing both containers,
   **fails** (the schema forbids their coexistence);
1. exactly one of `{hgvs, chromosomeCoordinates}` present;
2. `assembly`/`chromosome` in enum; small-variant `ref`/`alt` present;
3. `conditionSet.condition` has `{db∈enum, id}` (or `name` only if no id);
4. `observedIn` required fields present + in enum (`collectionMethod="curation"`);
5. `assertionCriteria` present (`{db,id}` or `{url}`);
6. `germlineSubmission[].germlineClassification.germlineClassificationDescription` ∈ ClinVar germline term
   enum (GTR standard-terms file) **and** an authorizing per-variant sign-off exists (FR7); `dateLastEvaluated`
   = `yyyy-mm-dd`;
7. `recordStatus` ∈ {`novel`,`update`} (**no `delete` value**); `update` ⇒ `clinvarAccession` (SCV format)
   present; a **withdrawal** is expressed as a top-level `clinvarDeletion.accessionSet[]` where each entry has a
   SCV `accession` (**required**) + optional `reason`, and is **never** a `recordStatus` (FR9);
8. **PHI scan** over `localID`/`localKey`/`comment`/`explanationOfInterpretation` — fail on any identifier
   pattern;
9. **deny-list** clean (FR3): no AAVC, no BIAS row, no run metadata as evidence, no legacy
   `clinvarSubmission`/`clinicalSignificance` container;
10. **no-SCV / no-authority invariant**: the record carries no fabricated SCV for a `novel` record; the
    validator emits only a report and **never** an SCV, and performs **no** network I/O.

**FR11 — Layer B (optional; operator-gated; still no SCV).** A live check may POST with `?dry-run=true`
(format+communication only) or use the `apitest` endpoint (data validation; **never public**). Both create
**no SCV / no public record** (register §1.7–1.8). This layer is **off by default**, requires an
out-of-repo API key + explicit operator flag, and is **excluded from automated tests**. The production
submissions URL is never targeted.

**FR12 — Report is not a verdict.** A green conformance report means *schema-conformant + dry-run-safe*, **not**
*authorized to submit* (GP-1). The report states so on its face.

## 7. Conflict / version / update / withdrawal handling

**FR9 — Lifecycle mapped to decision-log semantics.**

- **Conflict (pre-submission, reveal-only).** Compare the candidate record against the **existing public
  ClinVar** classification for the same variant as a **reveal-only comparator** (same discipline as AAVC —
  register §5.4): it may **inform reconciliation** but is **never** a truth label and never auto-resolves.
  Conflicts route to expert reconciliation (decision-log `reconciliation`), not to an automated flip. Note
  that a 3★ VCEP record supersedes 1★ single-submitter records in ClinVar's aggregation (authority, not code).
- **Version / freshness (GP-5).** Records pin the ClinVar/gnomAD/literature **source snapshot**; ClinVar's
  weekly cadence means any candidate is re-evaluated when its inputs change. Freshness lag is a monitored KPI.
- **Update.** `recordStatus="update"` + `clinvarAccession` (prior SCV from the decision log) + a **new**
  `dateLastEvaluated` + a **fresh** per-variant sign-off; recorded as a decision-log `supersession` event
  linking `predecessor_packet_id`.
- **Withdrawal (deletion).** Modeled with the **separate top-level `clinvarDeletion` object** (live schema
  verified 2026-07-12): `clinvarDeletion.accessionSet[]`, each entry `{accession: <prior SCV>, reason?: <public comment>}`.
  Withdrawal is **not** a `recordStatus` value — `recordStatus` accepts only `novel`/`update` (register §2.1–§2.2).
  *(A `recordStatus="delete"` was an earlier misreading of the schema and is **rejected**; retained only as a
  quoted prior error — see the schema-block closure note, §14.)* **Open dependency:** the decision-log
  `DecisionEventType` enum is frozen and has **no withdrawal event** (register §5.3) — PRD-09 build must
  either extend the enum (`WITHDRAWAL`) or model withdrawal as a typed `supersession`-to-retracted; specify a
  test either way. Withdrawal triggers: evidence retraction, gate regression (`PASS→FAIL`), newly discovered
  leakage/masking failure, expert reversal, or a curator/ClinVar request.

## 8. Acceptance criteria (authored as tests before implementation)

1. **AC1 — Mapping determinism + fail-loud.** Same packet ⇒ byte-identical mapped record; an unmapped/unknown
   source field fails loud (FR1).
2. **AC2 — Direction is not a classification.** Mapping a packet **without** a per-variant QMG sign-off leaves
   `germlineClassificationDescription` unset and blocks advance past `SUBMISSION_RECORD_MAPPED`; with a sign-off
   record it maps `candidate_LP_review→"Likely pathogenic"` / `candidate_LB_review→"Likely benign"` (FR7).
3. **AC3 — Deny-list.** Attempting to map AAVC/`external_comparators`, a `ScorerProvenance` BIAS row, run
   metadata, `signed_points`, or the **legacy `clinvarSubmission`/`clinicalSignificance` container** into any
   ClinVar field fails loud (FR3/FR2.1).
4. **AC4 — No-SCV invariant.** The mapper and validator never emit an SCV and never open a network socket to
   the production endpoint; a test greps the codebase to prove no un-`dry-run` production POST path exists
   (FR6/FR10.10).
5. **AC5 — Conformance rules.** Each §6 rule passes on a valid fixture and fails on a targeted-broken fixture
   (one broken field each).
6. **AC6 — PHI scan.** A record with an identifier-shaped `localID`/`comment` fails (FR10.8).
7. **AC7 — Update/withdrawal integrity.** A `recordStatus="update"` record without `clinvarAccession` fails;
   a `recordStatus="delete"` value is **rejected** (enum is `novel`/`update` only); a withdrawal is expressed
   as a top-level `clinvarDeletion.accessionSet[]` entry whose SCV `accession` is **required** (optional
   `reason`), and requires the decision-log withdrawal/supersession event (FR9).
8. **AC8 — State reachability (structural).** `SUBMISSION_AUTHORIZED` is unreachable **by construction**:
   `ExternalStateMachine.can_transition(current, SUBMISSION_AUTHORIZED, context)` returns `False` **even when
   every `ExternalContext` guard is `True`**, because `AUTHORIZATION_ENABLED_THIS_INCREMENT is False` (§15.5);
   the test enumerates the guard and proves unreachability with an all-`True` context, not merely an unmet one
   (FR6).
9. **AC9 — Dry-run live check is opt-in (structural, not `pass`).** The test proves Layer B is absent/default-off
   **by construction**: `raptor.external.dryrun.LAYER_B_ENABLED is False`, the `dryrun` module exposes **no**
   production submissions URL constant, `validate_conformance` has **no** network parameter and reports
   `network_used is False`, and `run_layer_b` raises `LayerBDisabledError` without the operator flag +
   out-of-repo key; the production URL is never constructed without `dry-run=true`; Layer B is absent from the
   automated test path (FR11; §15.6).
10. **AC10 — Report ≠ authority.** The conformance report and every mapped record are stamped
    non-authoritative and carry the would-be review status (1★ unless VCEP) (FR4/FR12/FR13).
11. **AC11 — Prerequisite checklist typing.** The checklist marks each item mechanical vs institutional and
    fails "ready to submit" while any institutional item is open (FR8).
12. **AC12 — New-shape pin + schema-freshness guard.** A mapped record uses the **new `germlineSubmission[]`
    → `germlineClassification` → `germlineClassificationDescription`** shape; a fixture emitting the legacy
    `clinvarSubmission`/`clinicalSignificance` shape, or mixing both containers, **fails** (FR2/FR2.1/FR10.0).
    A test proves the validator **refuses to run** (blocks generation) when the live-schema HTML sha256 differs
    from the pinned `3ed6b64…` value until a human re-pins (FR2.1/FR10.0).

**FR13 — Review-status honesty.** Any preview of the would-be ClinVar review status must show **1★
("criteria provided, single submitter")** unless an approved VCEP affiliation is supplied (register §3);
never preview 3★ without VCEP approval.

## 9. Dependencies

| Dependency | State | Blocks |
|---|---|---|
| PRD-04 packet + `EXTERNAL_SUBMISSION_READY` + decision log | built (provisional) | entry point |
| PRD-06 gate `PASS` (masked rerun + ADR-0009 ruling) | **not yet PASS** | `SUBMISSION_AUTHORIZED` only |
| PRD-02 normalizer + ClinVar/HGVS golden corpus | built | SPDI→HGVS/coords (FR2) |
| Live ClinVar germline **classification object name** | **RESOLVED (2026-07-12)** — new `germlineSubmission`→`germlineClassification`→`germlineClassificationDescription`; RAPTOR pins new shape only, rejects legacy/mixed (register §2.1–§2.2, §6.1) | schema pin **unblocked**; freshness guard (FR2.1) governs re-pin |
| ClinGen **VCEP Protocol v12** exact steps | **unverified** (register §6.4) | engagement package accuracy |
| Decision-log **withdrawal event** | **absent** (frozen enum) | withdrawal (FR9) |
| Registered org / API key / VCEP status / final policy | **absent** (institutional) | `SUBMISSION_AUTHORIZED` |

## 10. What finishes without expert validation vs. open dependencies

**Finishes now (mechanical; no expert/institution needed):** the field-mapping spec + config; the mapper
module (dry-run envelope, non-authoritative); the offline conformance validator + report + fixtures + schema
pin; the no-submission state machine + reachability tests; the prerequisite checklist; the VCEP engagement
package **template**; the conflict/version/update/withdrawal spec; the primary-source reference register; all
AC tests. **All of these produce zero SCV and cannot submit.**

**Cannot finish without external authority (open dependencies):** the authoritative classification value
(per-variant qualified sign-off — GP-3/STRATEGY Part I §9); PRD-06 gate `PASS` + ADR-0009 ruling; a final approved
production candidate-direction policy; ClinVar **organization registration** + Terms acceptance; **service
account + API key**; ClinGen **VCEP approval / 3★ status** (or a named qualified submitter); the published
**assertion-criteria** (VCEP ACMG TSC specification); the **condition identifier** verification; the
decision-log **withdrawal event** code extension; and the **actual submission**, which is out of scope for
this increment entirely.

## 11. Risks

- **R — False authority at the boundary (R-G5).** A schema-valid, dry-run-green record *looks* submittable →
  FR4/FR12/FR13/AC10 keep every artifact non-authoritative and preview 1★.
- **R — Accidental submission.** A code path could POST for real → FR6/AC4: no production-POST path exists;
  Layer B is opt-in + dry-run-only.
- **R — Circular evidence via comparator/BIAS (R-A2).** AAVC/BIAS leaking into `citation` → FR3/AC3 deny-list.
- **R — Direction laundered into a classification (R-A1/H4).** → FR7/AC2 per-variant sign-off gate.
- **R — Stale record (freshness).** ClinVar weekly cadence → FR9 snapshot pins + freshness KPI (GP-5).
- **R — Schema drift / stale pin (R-G5).** ClinVar redesigns the submission schema (e.g. the 2024
  germline/somatic split) → FR2.1/FR10.0 re-pin guard blocks validator/mapper generation on live-schema HTML
  hash drift until human review + re-pin; RAPTOR emits the **new** `germlineSubmission` shape only and rejects
  legacy/mixed output.

## 12. Open questions

1. Model withdrawal as a new `DecisionEventType.WITHDRAWAL` or as a typed `supersession`-to-retracted?
2. **RESOLVED (2026-07-12).** The live germline classification **object name** is confirmed: the production
   schema page (HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time)
   contains the **new `germlineSubmission[]` array requiring `germlineClassification` with required field
   `germlineClassificationDescription`**, alongside the **mutually exclusive** legacy
   `clinvarSubmission`/`clinicalSignificance` shape (the two cannot coexist). RAPTOR **pins to the new shape
   only and rejects legacy/mixed** (register §2.1–§2.2, §6.1); the prior hard-block is **closed**. Remaining
   question is operational: the **schema-freshness re-pin cadence** governed by FR2.1 (re-hash + block on
   drift). The `recordStatus` enum (`novel`/`update`) and the separate top-level `clinvarDeletion` withdrawal
   object are likewise **resolved** (register §2.1–§2.2).
3. Confirm the canonical TSC condition identifier (register §6.5) and the **current TSC VCEP roster / status /
   contact and engagement route** — the TSC VCEP **exists** (STRATEGY, verified 2026-06-16, with 0 ClinVar
   submissions at that date); the open item is confirming its current membership/status and the correct CDWG
   engagement route, **not** its existence (register §6.6).
4. Batch strategy for eventual submission (≤10,000 records/API call) — deferred until authority exists.

---

## 13. Build contract (Definition-of-Ready Task Specs)

> Authored outputs live under `docs/prd/PRD-09-*` (this file), `docs/reference/clinvar-vcep-*`,
> `configs/external/**`, `src/raptor/external/**`, `tests/external/**`. **No** shared PROGRAM/STRATEGY edits.
> Tester authors tests first; doer implements; checker re-verifies (cross-family, STRATEGY Part II §4).

- **Task A — Mapping + deny-list.** `src/raptor/external/__init__.py` (NEW package marker) +
  `src/raptor/external/models.py` (NEW shared frozen contracts — §15.2) +
  `configs/external/clinvar_field_map.yaml` + `src/raptor/external/clinvar_map.py`
  (pure, dry-run envelope returning **`MappingResult`**; **new `germlineSubmission` shape only**, legacy/mixed
  rejected — FR2/FR2.1). Pinned surface: **§15.1–§15.3**. ACs 1–3, 10, 12, 13. ≤4 reference files.
- **Task B — Offline conformance validator.** Pinned schema snapshot
  `configs/external/clinvar_submission_schema.snapshot.json` (records live-schema HTML sha256 `3ed6b64…`) +
  `configs/external/clinvar_conformance.yaml` + `src/raptor/external/conformance.py` returning
  **`ConformanceReport`** + **schema-freshness re-pin guard** (FR2.1/FR10.0). Pinned surface: **§15.4**.
  ACs 4–6, 12. ≤4 reference files.
- **Task C — No-submission state machine + lifecycle.** `src/raptor/external/state.py` (state extension +
  `ExternalContext` guards + update/withdrawal validators + `PrerequisiteChecklist` + reachability) +
  `src/raptor/external/dryrun.py` (Layer B opt-in stub, **structurally OFF** — no default network, no
  production URL). Pinned surface: **§15.5–§15.6**. ACs 4, 7–9, 11. ≤4 reference files.

> **Buildable vs authoritative (GP-1).** Ship the mapping, validator, state machine, packages, and tests;
> **gate the submission.** This increment creates **no SCV**, contacts **no one**, and classifies **nothing**.

---

## 14. Schema-block closure note (rubber-duck MAJOR findings — 2026-07-12)

Three MAJOR/hard-block findings against earlier drafts are now **all closed** by dated live-schema evidence.
This increment remains planning-only: no submission, no contact, no SCV.

- **MAJOR-1 (closed) — Withdrawal was mis-modeled as `recordStatus="delete"`.** The live ClinVar Submission
  API (`.../docs/api_http/`, verified **2026-07-12**) makes `recordStatus` a **required enum of only
  `novel`/`update`**. Withdrawal/deletion is a **separate top-level `clinvarDeletion` object** whose
  `accessionSet[]` entries each carry a **required** SCV `accession` (`SCVnnnnnnnnn`, not RCV/VCV) and an
  **optional** public `reason`. FR2, FR9, FR10.7, AC7, the (d) falsifier, §9 dependencies, §12 open questions,
  the primary-source register (§2.1–§2.2, §6.2), and the slot contracts/manifest are corrected. **No
  `recordStatus="delete"` remains anywhere except as a quoted, explicitly-rejected prior error.**

- **MAJOR-2 (closed) — TSC VCEP framed as "may not exist".** Reconciled with the frozen STRATEGY: a **TSC
  VCEP exists** but had **0 ClinVar submissions** at the dated verification (**2026-06-16**). The open
  dependency is reframed from *"does a TSC VCEP exist?"* to **confirming the current roster/membership,
  status, contact, and CDWG engagement route**. Claim typing and verification dates are preserved; no frozen
  STRATEGY text is edited.

- **HARD-BLOCK (now CLOSED) — germline classification object name.** The prior NO-GO (earlier drafts saw only
  a `clinicalSignificance` container) is **resolved** by the live **production** schema page (verified
  **2026-07-12**, HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, recorded as
  **point-in-time, not permanent**): it contains the **new top-level `germlineSubmission[]` array requiring a
  `germlineClassification` object whose required classification field is `germlineClassificationDescription`**,
  and still exposes the **legacy** `clinvarSubmission[]`/`clinicalSignificance` shape, which the schema
  **explicitly forbids from coexisting** with `germlineSubmission`. **RAPTOR pins its dry-run mapping/validator
  to the NEW `germlineSubmission`/`germlineClassification`/`germlineClassificationDescription` shape only and
  rejects legacy/mixed output** (FR2/FR2.1/FR3/FR10.0/AC3/AC12; register §2.1–§2.2, §2.5, §6.1). A
  **schema-freshness re-pin guard** (FR2.1) blocks validator/mapper generation on live-schema hash drift until
  human review + re-pin. The `germlineClassification.*` mapping targets are now **pinned**, not placeholders.

**Net status: GO for the schema-pinned build.** All three MAJOR/hard-block findings are closed; the germline
object-name pin is **resolved (GO)** with a freshness re-pin guard. Remaining open items are **external
authority / institutional dependencies only** — PRD-06 gate `PASS` + ADR-0009 ruling, final approved policy,
per-variant qualified sign-off, ClinVar org registration + Terms, service account + `SP-API-KEY`, ClinGen VCEP
approval / 3★ status (or named qualified submitter), published assertion-criteria, curator-verified condition
id, current TSC VCEP roster/status/contact + CDWG engagement route, the decision-log `WITHDRAWAL` event
extension, and the **actual submission** (out of scope) — none of which block the buildable, non-authoritative
planning increment (GP-1).

---

## 15. Frozen build-contract API surface (Definition-of-Ready pin — no MagicMock/invention)

> **Why this section exists.** Test authorship (Gemini, tests-first) against §13 revealed the doer-facing API
> was under-specified: the draft tests could only proceed by **`MagicMock`-ing** every type and by **inventing**
> symbols that do not exist in PRD-04 (e.g. a `DecisionEvent` class — the real type is `DecisionLogRecord`;
> a boolean-kwarg `PrerequisiteChecklist(...)`; a bare-`dict` return from `map_to_clinvar`; a `pass`-only AC9).
> This section **pins the exact frozen dataclasses, enums, typed errors, config keys, loader signatures,
> function signatures, and result schemas** for Tasks A/B/C so the doer implements — and the tester re-authors —
> against a **closed contract**: no `MagicMock`, no invented symbol, no `dict`-shaped guesswork. Every internal
> binding is sourced from the **verified PRD-04 surfaces** in `src/raptor/packet/{model,decisions}.py`
> (register §5.1–§5.5), not re-designed here. This section is normative; where a draft test in §16 conflicts
> with it, **this section wins** and the test must be re-authored.

### 15.0 Package + module layout (authorized future-implementation scope)

```
src/raptor/external/__init__.py     # NEW package marker (docstring only, no side effects) — Task A
src/raptor/external/models.py       # NEW shared frozen contracts (Task A owns; B/C import)
src/raptor/external/clinvar_map.py  # Task A — mapper + map-config loader + map errors
src/raptor/external/conformance.py  # Task B — offline validator + conformance-config loader + conf errors
src/raptor/external/state.py        # Task C — state machine + prerequisites + update/withdrawal + state errors
src/raptor/external/dryrun.py       # Task C — Layer B opt-in stub, STRUCTURALLY OFF by default
configs/external/clinvar_field_map.yaml            # Task A
configs/external/clinvar_conformance.yaml          # Task B
configs/external/clinvar_submission_schema.snapshot.json   # Task B — pinned schema snapshot (records HTML sha256)
```

Auto-discovered by `[tool.setuptools.packages.find] where=["src"]` (pyproject); `tests/external/**` runs under
`pythonpath=["src"]`. **No** `src/raptor/packet/**` edit; PRD-04 types are imported, never re-declared.

### 15.1 Shared error hierarchy (no catch-all; every raise is a typed subclass)

All external errors subclass `ExternalError(ValueError)` (mirrors PRD-04's `ValueError`-rooted packet errors).
**No bare `except Exception` and no catch-all base other than `ExternalError` is permitted.**

```
ExternalError(ValueError)                              # raptor.external.models
├─ ClinvarConfigError(ExternalError)                   # models — strict config load (unknown/missing key, pin mismatch)
├─ ClinvarMappingError(ExternalError)                  # clinvar_map — base map failure (re-exported from models is NOT done)
│  ├─ ClinvarDenyListError(ClinvarMappingError)        # clinvar_map — a denied source routed to a ClinVar field
│  └─ ClinvarSignoffError(ClinvarMappingError)         # clinvar_map — invalid VariantSignoff binding
├─ ConformanceError(ExternalError)                     # conformance — base
│  ├─ ClinvarShapeError(ConformanceError)              # conformance — legacy/mixed OR structurally-invalid germline shape
│  ├─ PhiDetectedError(ConformanceError)               # conformance — PHI in localID/localKey/comment/explanationOfInterpretation
│  ├─ NoScvInvariantError(ConformanceError)            # conformance — fabricated SCV on a novel record / SCV emission attempt
│  └─ SchemaFreshnessError(ConformanceError)           # conformance — live-schema hash ≠ pinned hash (refuse to run)
├─ ExternalStateError(ExternalError)                   # state — base
│  ├─ UpdateWithdrawalIntegrityError(ExternalStateError)  # state — update w/o SCV, delete value, bad withdrawal set
│  └─ PrerequisiteError(ExternalStateError)            # state — malformed checklist
└─ LayerBDisabledError(ExternalError)                  # dryrun — Layer B invoked without operator flag + out-of-repo key
```

`clinvar_map.py` re-exports `ClinvarMappingError`, `ClinvarDenyListError`, `ClinvarSignoffError` at module
level (Task A test imports them from `raptor.external.clinvar_map`). `conformance.py` defines the five
`Conformance*` errors at module level. `state.py` defines the state errors at module level.

### 15.2 Task A — `raptor.external.models` (shared frozen contracts)

**Module constants (pinned):**

```python
PINNED_SCHEMA_SHA256: str = "3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad"  # point-in-time
GERMLINE_TERM_ENUM: tuple[str, ...] = (
    "Pathogenic", "Likely pathogenic", "Uncertain significance", "Likely benign", "Benign",
    "Pathogenic/Likely pathogenic", "Likely benign/Benign",
)  # GTR standard_terms/Clinical_significance.txt (register §2.2); ONLY the germline set
DIRECTION_CLASSIFICATION_MAP: Mapping[str, str] = {
    "candidate_LP_review": "Likely pathogenic",
    "candidate_LB_review": "Likely benign",
}  # CONSISTENCY oracle only — NOT the source of the emitted value (see FR7/§15.3)
CONDITION_DB_ENUM: tuple[str, ...] = ("MONDO", "MedGen", "OMIM")
CITATION_DB_ENUM: tuple[str, ...] = ("PubMed", "DOI", "pmc")
SCV_ACCESSION_RE: str = r"^SCV\d{9}$"
```

**`ClinvarConditionRef`** — `@dataclass(frozen=True)`; strict `__post_init__`.

| field | type | rule |
|---|---|---|
| `db` | `str` | must be in `CONDITION_DB_ENUM`, else `ClinvarConfigError` |
| `id` | `str` | non-blank; **curator-verified** flag lives in config, not here (register §6.5) |
| `name` | `Optional[str]` | optional public label |

**`AssertionCriteriaRef`** — `@dataclass(frozen=True)`; **exactly one of** `{db,id}` or `url`, else
`ClinvarConfigError`.

| field | type | rule |
|---|---|---|
| `db` | `Optional[str]` | `PubMed`/`DOI`/`pmc` when set |
| `id` | `Optional[str]` | set iff `db` set |
| `url` | `Optional[str]` | set iff `db`/`id` unset |

**`ClinvarCitation`** — `@dataclass(frozen=True)`; `db: str` (∈ `CITATION_DB_ENUM`), `id: str` (non-blank).

**`ClinvarMapConfig`** — `@dataclass(frozen=True)` — the **strict** config object (mirror of
`configs/external/clinvar_field_map.yaml`). **Unknown/missing keys fail loud** (`ClinvarConfigError`). Exact
strict fields (no `**extra`, no attribute injection — a stray `config.invalid_field` cannot exist because the
dataclass is `frozen=True` and slotted-by-contract):

| field | type | rule / source |
|---|---|---|
| `config_version` | `str` | non-blank |
| `schema_pin_sha256` | `str` | must `== PINNED_SCHEMA_SHA256`, else `ClinvarConfigError` |
| `assembly` | `str` | fixed `"GRCh38"` |
| `condition` | `ClinvarConditionRef` | fixed TSC condition (register §6.5) |
| `condition_id_curator_verified` | `bool` | must be `True` to advance; audit flag |
| `assertion_criteria` | `AssertionCriteriaRef` | VCEP ACMG TSC spec ref |
| `observed_in_defaults` | `Mapping[str, str]` | frozen to `{"collectionMethod":"curation","alleleOrigin":"germline","affectedStatus":"not provided"}`; any deviation → `ClinvarConfigError` |
| `germline_term_enum` | `tuple[str, ...]` | subset of `GERMLINE_TERM_ENUM` |
| `direction_classification_map` | `Mapping[str, str]` | subset of `DIRECTION_CLASSIFICATION_MAP` (consistency oracle only) |
| `citation_scheme_map` | `Mapping[str, str]` | source-id prefix → citation db: `{"PMID":"PubMed","DOI":"DOI","PMC":"pmc"}` |
| `deny_list` | `tuple[str, ...]` | see §15.3 deny-list keys; any denied source routed to a ClinVar field → `ClinvarDenyListError` |
| `phi_patterns` | `tuple[str, ...]` | regex list for the localID/localKey/comment scan |
| `review_status_default` | `str` | fixed `"1-star"` (FR13); `"3-star"` is not a settable config value here |

**Loader (Task A):**
```python
def load_clinvar_map_config(path: str | Path) -> ClinvarMapConfig: ...
# strict YAML → dataclass; unknown top-level key OR missing required key OR
# schema_pin_sha256 != PINNED_SCHEMA_SHA256 → ClinvarConfigError. No silent defaults.
```

**`VariantSignoff`** — `@dataclass(frozen=True)` — the **exact per-variant qualified-sign-off binding**,
**sourced only from a verified PRD-04 `DecisionHistory`** (a hash-chain-verified replay; register §5.1/§5.3).
It is the **sole** source of `germlineClassificationDescription` (FR7). Fields:

| field | type | binding / rule |
|---|---|---|
| `variant_id` | `str` | `== packet.identity.canonical_spdi` and `== DecisionLogRecord.variant_id` |
| `packet_id` | `str` | `== packet.packet_id` and `== DecisionLogRecord.packet_id` |
| `evidence_core_hash` | `str` | `== packet.evidence_core_hash` and `== DecisionLogRecord.evidence_core_hash` |
| `reviewer_actor_id` | `str` | `DecisionLogRecord.actor_id` |
| `reviewer_role` | `ActorRole` | **must** be `ActorRole.QUALIFIED_MOLECULAR_GENETICIST`, else `ClinvarSignoffError` |
| `event_type` | `DecisionEventType` | **must** be `DecisionEventType.REVIEWER_DECISION`, else `ClinvarSignoffError` |
| `classification` | `str` | the germline term from the sign-off **decision**, `∈ GERMLINE_TERM_ENUM`; the value written to ClinVar |
| `signoff_date` | `str` | `yyyy-mm-dd` derived from `DecisionLogRecord.timestamp` → `dateLastEvaluated` |
| `record_hash` | `str` | `DecisionLogRecord.record_hash` it is bound to (audit link) |

**Strict binder (Task A) — the only constructor path from a decision log:**
```python
@classmethod
def from_decision_history(
    cls,
    history: DecisionHistory,          # MUST be a verified replay() result (hash-chained)
    *,
    packet: CandidateEvidencePacket,
    config: ClinvarMapConfig,
) -> Optional["VariantSignoff"]: ...
# Selects the LATEST DecisionLogRecord whose event_type == REVIEWER_DECISION AND
# actor_role == QUALIFIED_MOLECULAR_GENETICIST AND variant_id/packet_id/evidence_core_hash
# all match `packet`. Returns None if no such record (⇒ classification stays unset, FR7/AC2).
# The classification is parsed from that record's `decision` field; if not in GERMLINE_TERM_ENUM
# → ClinvarSignoffError. CROSS-CHECK: DIRECTION_CLASSIFICATION_MAP[packet.candidate_direction.direction]
# must equal the parsed classification, else ClinvarSignoffError (guards a mismatched sign-off);
# the direction is used ONLY for this consistency check, NEVER as the source of the value.
```

**`MappingStatus`** — `Enum`: `MAPPED = "mapped"` · `BLOCKED_NO_SIGNOFF = "blocked_no_signoff"` ·
`BLOCKED = "blocked"`.

**`MappingResult`** — `@dataclass(frozen=True)` — the pinned return of `map_to_clinvar` (**not** a bare dict):

| field | type | meaning |
|---|---|---|
| `payload` | `Optional[Mapping[str, Any]]` | the dry-run envelope: `{"germlineSubmission":[{...}], "dry_run": true, ...}`; `None` when `status == BLOCKED` before mapping |
| `status` | `MappingStatus` | `MAPPED` iff a valid `VariantSignoff` set the classification; `BLOCKED_NO_SIGNOFF` if the record mapped but classification is unset (cannot advance past `SUBMISSION_RECORD_MAPPED`); `BLOCKED` on hard stop |
| `blockers` | `tuple[str, ...]` | machine reasons, e.g. `("no_per_variant_signoff",)`, `("condition_id_unverified",)` |
| `non_authoritative` | `bool` | **always `True`** this increment (FR4); a `False` value is unconstructible |
| `review_status_preview` | `str` | **always `"1-star"`** unless an approved VCEP affiliation is supplied (FR13); never `"3-star"` here |

The mapped ClinVar record inside `payload["germlineSubmission"][0]` uses **only** the new-shape keys
(`variantSet`, `germlineClassification`, `conditionSet`, `observedIn`, `localID`, `localKey`,
`recordStatus`, `clinvarAccession?`); it **never** contains `clinvarSubmission`/`clinicalSignificance`.

### 15.3 Task A — `raptor.external.clinvar_map` (mapper)

**Function signature (pinned):**
```python
def map_to_clinvar(
    packet: CandidateEvidencePacket,
    config: ClinvarMapConfig,
    *,
    signoff: Optional[VariantSignoff] = None,
) -> MappingResult: ...
```

- **Deterministic** (AC1): same `(packet, config, signoff)` ⇒ byte-identical `payload` (canonical key order).
- **Classification source (FR7/AC2):** `germlineClassification.germlineClassificationDescription` is set
  **iff** `signoff is not None`; its value is **exactly `signoff.classification`**. `map_to_clinvar` **never**
  reads `packet.candidate_direction.direction` to produce the classification — with `signoff=None` the field
  is **absent** and `status = BLOCKED_NO_SIGNOFF`. (There is **no** `allow_*` kwarg; a real deny-list is
  structural, not a test flag.)
- **Citation mapping (exact; from resolved primary refs only):** for each
  `entry.primary_evidence_refs[]` with `resolution_status is ResolutionStatus.RESOLVED`:
  - `source_type == "literature"` → derive `ClinvarCitation` via `config.citation_scheme_map` from the
    `source_id` prefix (`PMID:`→`PubMed`, `DOI:`→`DOI`, `PMC`→`pmc`); an unrecognized scheme on a resolved
    **literature** ref → `ClinvarMappingError` (fail loud — a literature citation must resolve to a db);
  - `source_type ∈ {"functional_assay","clingen_guidance","database_record"}` → **not** a `citation[]`
    entry (may inform `comment` prose only), never fabricated as a citation;
  - `resolution_status is UNRESOLVED` → **never** a citation.
  Only the resulting `ClinvarCitation` objects populate `germlineClassification.citation[]`.
- **Deny-list keys (FR3/AC3) — routing any of these into a ClinVar field raises `ClinvarDenyListError`:**
  `external_comparators`/AAVC (`ExternalComparator`); `ScorerProvenance` (BIAS raw row, incl.
  `entries[].scorer_provenance`); `candidate_direction.signed_points` / `candidate_direction.per_criterion_points`
  / `entries[].production_disposition` (policy internals); `run_metadata.run_id` / `run_metadata.generated_at`
  (run metadata); the **legacy `clinvarSubmission`/`clinicalSignificance` container** (also fails loud). The
  loader additionally rejects a `config.deny_list` source path pointed at any ClinVar target at load time.
- **New-shape guarantee (FR2/AC12):** the emitted record contains `germlineSubmission` and **never**
  `clinvarSubmission` or `clinicalSignificance`.

### 15.4 Task B — `raptor.external.conformance` (offline validator; no network, no SCV)

**`ConformanceConfig`** — `@dataclass(frozen=True)` (mirror of `configs/external/clinvar_conformance.yaml`):

| field | type | rule |
|---|---|---|
| `pinned_schema_sha256` | `str` | `== PINNED_SCHEMA_SHA256` |
| `schema_snapshot_path` | `str` | path to `clinvar_submission_schema.snapshot.json` (records the live-page HTML sha256) |
| `germline_term_enum` | `tuple[str, ...]` | subset of `GERMLINE_TERM_ENUM` |
| `condition_db_enum` | `tuple[str, ...]` | `CONDITION_DB_ENUM` |
| `assembly_enum` | `tuple[str, ...]` | `("GRCh38",)` |
| `collection_method` | `str` | `"curation"` |
| `phi_patterns` | `tuple[str, ...]` | identifier regexes |
| `deny_list_markers` | `tuple[str, ...]` | legacy container + AAVC/BIAS/run-metadata markers |

**Loader (Task B):** `def load_conformance_config(path: str | Path) -> ConformanceConfig: ...` (strict;
unknown/missing key or pin mismatch → `ClinvarConfigError`).

**`RuleResult`** — `@dataclass(frozen=True)`: `rule_id: str`, `passed: bool`, `detail: str`.

**`ConformanceReport`** — `@dataclass(frozen=True)` (pinned return; exact fields):

| field | type | meaning |
|---|---|---|
| `is_valid` | `bool` | all business rules passed |
| `is_authoritative` | `bool` | **always `False`** (FR12/AC10) |
| `review_status` | `str` | **always `"1-star"`** unless approved VCEP (FR13) |
| `rule_results` | `tuple[RuleResult, ...]` | per-rule §6.1–§6.10 outcomes |
| `record_id` | `Optional[str]` | the record `localID` if present |
| `schema_snapshot_id` | `str` | pinned snapshot id |
| `pinned_schema_sha256` | `str` | `PINNED_SCHEMA_SHA256` |
| `emitted_scv` | `bool` | **always `False`** — no-SCV invariant proof |
| `network_used` | `bool` | **always `False`** — no-network invariant proof |

**Function signature (pinned):**
```python
def validate_conformance(
    record: Mapping[str, Any],
    *,
    config: Optional[ConformanceConfig] = None,   # None ⇒ load the pinned default snapshot
    live_hash: Optional[str] = None,              # for the freshness guard test
    pinned_hash: str = PINNED_SCHEMA_SHA256,
) -> ConformanceReport: ...
```

Validation semantics (removes the raise-vs-report ambiguity):
- **Guard/falsifier conditions RAISE (fail loud), before any rule runs or is reported:**
  - `live_hash is not None and live_hash != pinned_hash` → `SchemaFreshnessError` (refuse to run; FR2.1/FR10.0).
  - record emits `clinvarSubmission`/`clinicalSignificance`, mixes both containers, or a
    `germlineSubmission[]` record is missing the required `germlineClassification`/
    `germlineClassificationDescription` shape → `ClinvarShapeError` (FR2/FR10.0/AC12).
  - a PHI pattern matches `localID`/`localKey`/`comment`/`explanationOfInterpretation` → `PhiDetectedError`
    (FR10.8/AC6).
  - a `novel` record carries a fabricated SCV, or any code path would emit an SCV → `NoScvInvariantError`
    (FR10.10/AC4). The validator opens **no socket** and performs **no network I/O** (`network_used=False`).
- **Business-rule conformance (§6.1–§6.7, §6.9) is REPORTED**, not raised: each becomes a `RuleResult`;
  `is_valid` is their conjunction. AC5 asserts each rule `passed=True` on a valid fixture and `passed=False`
  on a one-field-broken fixture. (A completely absent required sub-object is a **shape** error and RAISES, per
  above; a present-but-out-of-enum value is a **reported** rule failure.)

### 15.5 Task C — `raptor.external.state` (state machine + prerequisites + lifecycle)

**`ExternalReviewState`** — `Enum` (values exactly):
`SUBMISSION_RECORD_MAPPED` · `SUBMISSION_CONFORMANCE_VALIDATED` · `SUBMISSION_DRYRUN_CHECKED` ·
`SUBMISSION_PACKAGE_ASSEMBLED` · `SUBMISSION_AUTHORIZED` (terminal; **structurally unreachable this
increment**).

**`RecordStatus`** — `Enum`: `NOVEL = "novel"` · `UPDATE = "update"`. **No `delete` member exists** (a
`"delete"` string is rejected by `validate_record_status`).

**`ExternalContext`** — `@dataclass(frozen=True)` — the guard inputs for `SUBMISSION_AUTHORIZED`:

| field | type |
|---|---|
| `gate_status` | `GateStatus` |
| `policy_approved` | `bool` |
| `adr0009_ruling_landed` | `bool` |
| `per_variant_signoff_present` | `bool` |
| `org_registered` | `bool` |
| `vcep_authority_present` | `bool` |
| `final_policy_approved` | `bool` |
| `operator_authorized` | `bool` |

**`PrerequisiteType`** — `Enum`: `MECHANICAL` · `INSTITUTIONAL` · `MIXED`.

**`PrerequisiteItem`** — `@dataclass(frozen=True)`: `key: str`, `label: str`, `item_type: PrerequisiteType`,
`owner: str`, `source: str`, `satisfied: bool`.

**`PrerequisiteChecklist`** — `@dataclass(frozen=True)`: `items: tuple[PrerequisiteItem, ...]` (the **only**
constructor arg — there is **no** boolean-kwarg constructor). Methods:
```python
def is_ready_to_submit(self) -> bool: ...          # False if ANY INSTITUTIONAL or MIXED item is unsatisfied
def missing_institutional(self) -> tuple[str, ...]: ...   # keys of unsatisfied INSTITUTIONAL/MIXED items
```
Builder for the FR8 seven-item checklist:
```python
def default_checklist(**satisfied: bool) -> PrerequisiteChecklist: ...
# keys: myncbi_account, org_registered, submitters_authorized, api_key_present,
#       assertion_criteria_uploaded, reviewer_authority, condition_id_verified
```

**`ExternalStateMachine`** — transition APIs (exact):
```python
AUTHORIZATION_ENABLED_THIS_INCREMENT: bool = False   # module constant — hard wall

TRANSITIONS: Mapping[ExternalReviewState, tuple[ExternalReviewState, ...]]  # allowed edges

def can_transition(
    self,
    current: ExternalReviewState,
    target: ExternalReviewState,
    context: ExternalContext,
) -> bool: ...
# Returns False for target == SUBMISSION_AUTHORIZED UNCONDITIONALLY while
# AUTHORIZATION_ENABLED_THIS_INCREMENT is False — i.e. unreachable BY CONSTRUCTION,
# even when EVERY ExternalContext guard is True (AC8 structural proof, FR6).

def next_state(self, current: ExternalReviewState, context: ExternalContext) -> Optional[ExternalReviewState]: ...

@staticmethod
def validate_record_status(record_status: str, *, accession: Optional[str]) -> None: ...
# raises UpdateWithdrawalIntegrityError if:
#   record_status not in {"novel","update"}  (so "delete" ALWAYS raises), OR
#   record_status == "update" and accession is None / not matching SCV_ACCESSION_RE.

@staticmethod
def validate_withdrawal(accession_set: Optional[Sequence[Mapping[str, Any]]]) -> None: ...
# raises UpdateWithdrawalIntegrityError if accession_set is None/empty or any entry lacks a
# valid SCV `accession` (SCV_ACCESSION_RE). Withdrawal is the top-level clinvarDeletion object.

@staticmethod
def build_clinvar_deletion(
    accession_set: Sequence[tuple[str, Optional[str]]],
) -> Mapping[str, Any]: ...
# → {"clinvarDeletion": {"accessionSet": [{"accession": scv, "reason": reason?}, ...]}}

@staticmethod
def review_status_preview(context: ExternalContext) -> str: ...
# returns "3-star" ONLY if context.vcep_authority_present else "1-star";
# this increment never supplies VCEP authority ⇒ always "1-star" (FR13; no fake 3★).
```

`can_transition`/`next_state` accept an `ExternalReviewState` (the packet's `review_state`), **not** a packet
object — callers pass `packet.review_state`.

### 15.6 Task C — `raptor.external.dryrun` (Layer B opt-in stub; structurally OFF)

```python
LAYER_B_ENABLED: bool = False                        # module constant — default OFF (AC9 structural)
# NO production submissions URL constant exists in this module. The only permissible endpoints
# carry `dry-run=true` or the `apitest` path; both create no SCV / no public record.

def run_layer_b(
    record: Mapping[str, Any],
    *,
    operator_authorized: bool = False,
    api_key: Optional[str] = None,
    endpoint: str,
) -> ConformanceReport: ...
# Raises LayerBDisabledError unless (operator_authorized and api_key). Raises ValueError if
# `endpoint` is not a dry-run/apitest URL. EXCLUDED from automated tests. validate_conformance
# (Layer A) NEVER calls this and takes no network parameter.
```

**AC9 (structural, not `pass`):** the automated test proves Layer B is **absent/default-off by construction** —
it asserts `dryrun.LAYER_B_ENABLED is False`, asserts the module exposes **no** production submissions URL
constant, and asserts `validate_conformance` has **no** network parameter and sets `report.network_used is
False` — it does **not** call `run_layer_b`.

---

## 16. Tester-correction note (tests-first authorship exposed incomplete APIs — 2026-07-12)

Gemini authored the AC tests **before** the doer implemented (STRATEGY Part II §4). That first pass could only
compile by `MagicMock`-ing every type and inventing symbols, which is itself the finding: **the §13 contract
was not doer-ready.** The draft tests currently under `tests/external/` are recorded here as the correction
trigger; §15 is the closed contract they must be **re-authored** against (planning-only — this task does not
edit tests):

| # | Draft-test symptom (invention / MagicMock) | Correct pinned contract (§15) |
|---|---|---|
| 1 | Imports `DecisionEvent` from `raptor.packet.decisions` | The real type is **`DecisionLogRecord`** (+ `DecisionHistory`, `DecisionDraft`); sign-off is bound via `VariantSignoff.from_decision_history(...)` (§15.2) |
| 2 | `map_to_clinvar(...)` indexed as a bare `dict` (`record["germlineClassificationDescription"]`) | Returns **`MappingResult`**; the record is `result.payload["germlineSubmission"][0]["germlineClassification"]["germlineClassificationDescription"]` (§15.2–§15.3) |
| 3 | `map_to_clinvar(..., allow_aavc=True, allow_bias=True)` flags to trip the deny-list | **No `allow_*` kwargs**; the deny-list is **structural** — routing `external_comparators`/`ScorerProvenance` into a ClinVar field raises `ClinvarDenyListError` (§15.3) |
| 4 | `CandidateDirection(direction="candidate_LP_review", null_reason=None)` (missing required fields) | `CandidateDirection` requires `policy_id`/`policy_version`/`approval_status`/`per_criterion_points`; use a real PRD-04 fixture, not a partial constructor (model.py) |
| 5 | `config.invalid_field = "unknown"` to force fail-loud | `ClinvarMapConfig` is `frozen=True`; strict `load_clinvar_map_config` raises `ClinvarConfigError` on an **unknown YAML key** (§15.2) — attribute injection is impossible |
| 6 | `signoff=MagicMock()` yields a hard-coded `"Likely pathogenic"` | Classification comes **only** from a real `VariantSignoff.classification` sourced from a verified `DecisionHistory`; a mock cannot satisfy the QMG-role/event-type/hash-match binder (§15.2) |
| 7 | `PrerequisiteChecklist(org_registered=False, api_key_present=True)` boolean kwargs | Constructor is `PrerequisiteChecklist(items=(PrerequisiteItem, ...))`; use `default_checklist(**satisfied)` and `missing_institutional()` (§15.5) |
| 8 | `ExternalStateMachine.validate_record_status`/`validate_withdrawal` called as bare class methods | Pinned as **`@staticmethod`s** with the exact signatures in §15.5; `"delete"` always raises `UpdateWithdrawalIntegrityError` |
| 9 | `sm.can_transition(packet, target, context)` passes a `MagicMock` packet | `can_transition(current: ExternalReviewState, target, context)` takes the **state enum** (`packet.review_state`); AC8 must also prove unreachability with **all** `ExternalContext` guards `True` (§15.5) |
| 10 | `test_ac9_dry_run_opt_in` body is `pass` (proves nothing); `test_ac9` lives in the Task B file | AC9 is **Task C** and must be **structural**: assert `dryrun.LAYER_B_ENABLED is False`, no production URL constant, `validate_conformance` has no network param (§15.6) |
| 11 | `validate_conformance(broken_record)` / PHI record expected to **raise** while §6 says "report per rule" | Disambiguated in §15.4: **guards/falsifiers raise** (`ClinvarShapeError`/`PhiDetectedError`/`SchemaFreshnessError`/`NoScvInvariantError`); **business rules are reported** as `RuleResult`s |

**Boundaries preserved (unchanged by this correction):** no network (Layer A offline; Layer B off by
construction), **no SCV** (`emitted_scv`/`network_used` invariants; no production-POST path), **no per-variant
classification without a QMG `DecisionHistory` sign-off**, **no contact**, **no submission**, no frozen-doc
edits. §15/§16 are **spec-only**; no `src/raptor/external/**` or `tests/external/**` code is written by this
planning task.

---

## 17. Ready claim (revised — Definition-of-Ready, API-pinned)

**READY (GO) for the schema-pinned, API-pinned, buildable, non-authoritative planning increment (GP-1).** The
three prior MAJOR/hard-block findings remain **closed** (§14). This revision additionally **closes the
doer-readiness gap** surfaced by tests-first authorship: Tasks A/B/C now expose a **frozen, MagicMock-proof
contract** (§15) — exact dataclasses, enums, typed-error hierarchy (no catch-all), config keys, strict
loaders, function signatures, and result schemas — with a tester-correction note (§16) mapping every draft-test
invention to its pinned replacement. `src/raptor/external/models.py` and the `src/raptor/external/__init__.py`
package marker are now **authorized** future-implementation scope. Remaining open items are **external
authority / institutional dependencies only** (PRD-06 gate `PASS` + ADR-0009 ruling, final approved policy,
per-variant QMG/VCEP sign-off, ClinVar org registration + Terms, `SP-API-KEY`, ClinGen VCEP 3★/named
submitter, published assertion-criteria, curator-verified condition id, TSC VCEP roster/status/contact + CDWG
route, the decision-log `WITHDRAWAL` event extension, and the out-of-scope actual submission) — none of which
block the build. **No submission, no contact, no SCV, no push, no network, no production classification.**
