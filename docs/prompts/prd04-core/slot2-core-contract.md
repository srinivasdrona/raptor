# Slot 2 — PRD-04 Task A: packet core (model + lineage + provenance + direction + hashes)

## Contract

- **Task:** `prd04-packet-core`
- **Goal:** Build the candidate-evidence-packet model + machine-read lineage / two-level provenance +
  nullable production candidate-direction policy + the four canonical hashes, assembled from an injected
  `PacketInput` (no eval-combiner import; no label/benchmark/KB read; no `classification_versions` write).
- **Motivating artifact:** `docs/prd/PRD-04-candidate-evidence-packet.md`
  (r3, source commit `9adbd7b`; read especially §4.1 packet model, §4.2 hash domains, §4.10 `PacketInput`,
  §4.5 states, §10.2 config, §10.3 module layout, §11.1 task spec; ADR-0009 lineage; `bias_lineage.yaml`).
- **Sequencing:** first of three sequenced doer tasks (A → B → C). No prior-task dependency.

## Context surface

Create only:

- `src/raptor/packet/__init__.py` — package marker; no side effects
- `src/raptor/packet/model.py`   — `CandidateEvidencePacket`, `PacketInput`, `CriterionEntry`, `CandidateDirection` (nullable)
- `src/raptor/packet/build.py`   — `build_packet(PacketInput, config, *, narrative_plan=None)`
- `src/raptor/packet/direction.py` — production candidate-direction policy (nullable; **not** `eval.combine`)
- `src/raptor/packet/hashing.py` — the four canonical hashes
- `src/raptor/packet/config.py`  — `PacketConfig`/`CandidateDirectionPolicy` (frozen, schema-validated)
- `configs/packet/schema.yaml`   — packet field set + `packet_schema_version`
- `configs/packet/candidate_direction.yaml` — production policy (`confirm` empty → `candidate_direction=null`, `POLICY_BLOCKED`)

Do not create the surfaces (render/queue) or workflow (state/decisions/comparator) modules — those are
Tasks B and C. Do not edit any frozen file (§9.1).

## Reference files (four maximum — PRD §11.1)

1. `src/raptor/scorer/model.py`       — `CriterionCall`/`EvidenceRecord` shapes (data-only reuse)
2. `src/raptor/eval/lineage_policy.py` — `load_lineage_policy` → `lineage_class` + dispositions (FR4.1)
3. `src/raptor/scorer/report.py`      — `content_hash` canonicalization pattern to mirror (FR8)
4. `data/census/tsc_vus_clinvar_2026-07-07_stats.json` — selection-metadata / topology facts + provenance

## Public API (copied verbatim from PRD §10.3 — implement exactly; you may add, never weaken)

- **`config.py`** — `PacketConfig`/`CandidateDirectionPolicy`/`SelectionConfig`/`NarrativeCatalog`
  (frozen) + `load_*`; schema-validate, raise on missing/blank required pin (GP-6). (Task A owns the
  `PacketConfig` + `CandidateDirectionPolicy` loaders; `SelectionConfig`/`NarrativeCatalog` loaders may
  be stubbed for B but must not be weakened.)
- **`model.py`** — `CandidateEvidencePacket` (§4.1 schema, frozen dataclass), `PacketInput` (§4.10),
  `CriterionEntry` (`criterion, strength, direction, rationale, lineage_class, validation_disposition,
  production_disposition, decision_dependency, packet_policy_disposition, scorer_provenance` (exactly
  one), `primary_evidence_refs` (zero+), `primary_grounding ∈ {present, absent, not_required}`,
  `primary_grounding_reason`, `primary_required: bool`), `ScorerProvenance` + `PrimaryEvidenceRef`
  (FR4.2 pinned schemas), `CandidateDirection` (`direction|None, null_reason, policy_id, policy_version,
  signed_points, per_criterion_points`), `NarrativePlan` (`entries: [{template_id, field_bindings}]`,
  `model, prompt_hash`), `ExternalComparator` (AAVC envelope), `PacketView` enum
  (`FIRST_PASS|OPERATOR|RECONCILIATION`), `FirstPassPacketView`, `ReviewState`, `ReviewerDecision`,
  `DecisionLogRecord`, `PatternRef`. Exposes `resolve_packet_policy_disposition(validation, production)`
  (FR4.1 precedence) + `redact_for_first_pass(packet) -> FirstPassPacketView` (FR14.1).
- **`build.py`** — `build_packet(packet_input: PacketInput, config, *, narrative_plan=None) ->
  CandidateEvidencePacket`: applies the candidate-direction policy (FR5; `null` when unapproved), maps
  machine-read lineage → `packet_policy_disposition` via `resolve_packet_policy_disposition` (FR4.1,
  preserving both raw dispositions), assembles two-level provenance (FR4.2),
  exclusions/contradictions/missing-evidence (FR6). **Reads no KB/benchmark/label file** (FR24); the AAVC
  comparator is attached but excluded from the evidence core and from the first-pass view.
- **`direction.py`** — `compute_candidate_direction(entries, policy) -> CandidateDirection`: signed sum
  under the **production** policy; returns `null`/`null_reason` when unapproved;
  `no_deterministic_resolution`/`manual_review` are first-class. Does **not** import `eval/combine.py`.
- **`hashing.py`** — `evidence_core_hash(packet)`, `narrative_plan_hash(plan)`,
  `packet_envelope_hash(packet)`, `decision_record_hash(prev_hash, record)` — the four canonical domains
  (§4.2/FR8), mirroring `scorer/report.py` + `kb/store.py` canonicalization. Genesis
  `prev_hash = "0"*64` (FR25).

> The doer **must honor**: `PacketInput` is injected (fixtures/temp store in tests); the packet path
> imports **no** `eval.*` combiner, reads **no** label/benchmark/oracle file, reads **no** KB table
> directly, and writes **no** `classification_versions` row; candidate direction is a review direction
> (nullable), never a classification.

## Exact Task-A schemas and signatures (r4 pre-test correction)

This section removes constructor/loader ambiguity exposed at test authorship. It is normative for
Task A and for the Task B/C fields that depend on Task A. All dataclasses are `frozen=True`; tuples are
used for ordered collections and mappings are copied to immutable/read-only values at construction.

### Enums and typed failures

- `PacketPolicyDisposition`: `included | masked | excluded | deferred`
- `PrimaryGrounding`: `present | absent | not_required`
- `ResolutionStatus`: `resolved | unresolved`
- `ReviewState`: `DRAFT_PROVISIONAL | POLICY_BLOCKED | READY_FOR_EXPERT_REVIEW |
  EXPERT_CHANGES_REQUESTED | EXPERT_APPROVED_INTERNAL | SECOND_REVIEW_APPROVED |
  EXTERNAL_SUBMISSION_READY | SUPERSEDED`
- `GateStatus`: `PASS | FAIL | UNDERPOWERED | UNVERIFIED`
- `PacketView`: `FIRST_PASS | OPERATOR | RECONCILIATION`
- typed failures: `PacketConfigError`, `PacketSchemaError`, `PacketValidationError`,
  `ProvenanceValidationError`, `DispositionMappingError`, `DirectionPolicyError`,
  `PacketHashError`. Tests never use catch-all `Exception`.

### Core value objects (exact fields)

- `CanonicalVariantIdentity(canonical_spdi: str, gene: str, transcript: str,
  consequence: str, variant_class: str)`.
- `RunMetadata(run_id: str, generated_at: str, code_commit: str, packet_config_sha256: str,
  lineage_policy_sha256: str, candidate_policy_sha256: str)`. `run_id`/`generated_at` are
  recorded but excluded from every packet hash; the other four fields are envelope pins.
- `SourceSnapshotPins(snapshot_id: str, snapshot_date: str, clinvar_sha256: str,
  bias_output_sha256: str, manifest_sha256: str)`; all three hashes are lowercase hex-64.
- `ScorerProvenance(bias_row_key: str, chromosome: str, position: int, ref: str, alt: str,
  scorer_run_id: str, input_sha256: str, output_sha256: str, raw_row_sha256: str,
  bias_version: str, bias_commit: str, nirvana_version: str, transcript: str)`; all required.
- `PrimaryEvidenceRef(ref_id: str, source_type: str, source_id: str, locator: str,
  source_snapshot: str, source_version: str, source_sha256: str | None,
  source_sha256_null_reason: str | None, supports_criterion: str,
  resolution_status: ResolutionStatus, unresolved_reason: str | None)`.
  `source_type` is one of `literature | functional_assay | clingen_guidance |
  database_record` and never `bias_row`. A resolved ref requires all
  identity/locator/snapshot/version fields and exactly one of checksum or checksum-null-reason;
  an unresolved ref requires `unresolved_reason`.
- `PacketCriterionInput(criterion: str, strength: str, direction: str, rationale: str,
  scorer_provenance: ScorerProvenance, primary_evidence_refs: tuple[PrimaryEvidenceRef, ...],
  primary_grounding: PrimaryGrounding, primary_grounding_reason: str)`. It contains no caller-supplied
  lineage or disposition.
- `MissingEvidence(category: str, next_action: str, supporting_field_paths: tuple[str, ...])`.
- `PatternRef(census_snapshot_id: str, pattern_id: str, census_selection_stratum: str,
  pattern_signature: tuple[str, ...], member_count: int)`. The selection stratum is never a
  production direction.
- `ExternalComparator(comparator_id: str, source_name: str, source_snapshot: str, source_doi: str,
  source_archive_sha256: str, source_commit: str, match_method: str, machine_class: str,
  criteria: tuple[str, ...], flags: tuple[str, ...])`.
- `PacketInput(identity: CanonicalVariantIdentity,
  criterion_inputs: tuple[PacketCriterionInput, ...], run_metadata: RunMetadata,
  source_snapshot: SourceSnapshotPins, quality_flags: tuple[str, ...],
  missing_evidence: tuple[MissingEvidence, ...], pattern_ref: PatternRef | None,
  external_comparators: tuple[ExternalComparator, ...], predecessor_packet_id: str | None,
  predecessor_envelope_hash: str | None)`.
- `CriterionEntry(criterion: str, strength: str, direction: str, rationale: str,
  lineage_class: str, validation_disposition: str, production_disposition: str,
  decision_dependency: str, packet_policy_disposition: PacketPolicyDisposition,
  exclusion_reason: str | None, scorer_provenance: ScorerProvenance,
  primary_evidence_refs: tuple[PrimaryEvidenceRef, ...], primary_grounding: PrimaryGrounding,
  primary_grounding_reason: str, primary_required: bool)`.
- `PointContribution(criterion: str, strength: str, points: int)`.
- `CandidateDirection(direction: str | None, null_reason: str | None, policy_id: str,
  policy_version: str, approval_status: str, signed_points: int | None,
  per_criterion_points: tuple[PointContribution, ...])`. Unapproved means `direction=None`,
  `null_reason=production_policy_unapproved`, `signed_points=None`, no contributions. Approved means
  non-null direction, null `null_reason`, and an integer score.
- `FieldBinding(name: str, field_path: str)`;
  `NarrativePlanEntry(template_id: str, field_bindings: tuple[FieldBinding, ...])`;
  `NarrativePlan(entries: tuple[NarrativePlanEntry, ...], model: str, prompt_hash: str)`.
- `CandidateEvidencePacket(packet_schema_version: str, packet_id: str,
  evidence_core_hash: str, narrative_plan_hash: str, packet_envelope_hash: str,
  identity: CanonicalVariantIdentity, entries: tuple[CriterionEntry, ...],
  candidate_direction: CandidateDirection, exclusions: tuple[str, ...], contradiction: bool,
  quality_flags: tuple[str, ...], missing_evidence: tuple[MissingEvidence, ...],
  narrative_plan: NarrativePlan | None, external_comparators: tuple[ExternalComparator, ...],
  review_state: ReviewState, gate_status: GateStatus, pattern_ref: PatternRef | None,
  run_metadata: RunMetadata, source_snapshot: SourceSnapshotPins,
  predecessor_packet_id: str | None, predecessor_envelope_hash: str | None)`.
  `packet_id == packet_envelope_hash`. Later state/reviewer actions create a new packet or decision
  record; they never mutate this object.

Task B defines the exact `FirstPassPacketView`; Task C defines `ReviewerDecision` and
`DecisionLogRecord`. Task A's `decision_record_hash(prev_hash: str,
record_payload: Mapping[str, object]) -> str` accepts a canonical payload mapping so it does not
invent the Task-C record shape early.

### Exact config and direction API

- `load_candidate_direction_policy(path: str | Path) -> CandidateDirectionPolicy`.
- `load_packet_config(path: str | Path) -> PacketConfig`.
- `CandidateDirectionPolicy(policy_id: str, version: str, approval_status: str,
  approved_by: str | None, approval_ref: str | None,
  criterion_strength_points: Mapping[str, Mapping[str, int]],
  candidate_lp_min: int | None, candidate_lb_max: int | None)`.
  `approval_status` is `unapproved | approved`. Unapproved requires null approval fields, empty points,
  and null cutoffs. Approved requires non-blank approval fields, non-empty points, integer cutoffs, and
  `candidate_lb_max < candidate_lp_min`.
- `PacketConfig(packet_schema_version: str, config_version: str,
  lineage_policy: LineagePolicy, lineage_policy_sha256: str,
  candidate_direction_policy: CandidateDirectionPolicy, candidate_policy_sha256: str,
  primary_required_criteria: frozenset[str])`.
- `configs/packet/schema.yaml` has exactly `packet_schema_version`, `config_version`,
  `lineage_policy_path`, `candidate_direction_policy_path`, `primary_required_criteria`; paths resolve
  relative to the repository root and the loader records real SHA-256 values for both referenced files.
- `configs/packet/candidate_direction.yaml` has exactly `policy_id`, `version`, `approval_status`,
  `approved_by`, `approval_ref`, `criterion_strength_points`, `candidate_lp_min`,
  `candidate_lb_max`. The committed first-increment policy is unapproved with empty points and null
  cutoffs; tests may construct an approved policy directly.
- `compute_candidate_direction(entries, policy)` scores only `included` entries whose
  criterion+strength pair exists in `criterion_strength_points`; an included unknown pair raises
  `DirectionPolicyError`. Sum `>= candidate_lp_min` -> `candidate_LP_review`; sum
  `<= candidate_lb_max` -> `candidate_LB_review`; otherwise `no_deterministic_resolution`.
  `manual_review` is selected by packet validation/manual flags, not an invented score cutoff.
- `build_packet(packet_input, config, *, narrative_plan=None)` is the only constructor for a complete
  packet. It resolves every criterion through `config.lineage_policy.records`; missing lineage raises
  `PacketValidationError`. `config=None` is invalid. It validates `PacketInput`, builds immutable entries,
  derives contradiction/direction/state, computes all three packet hashes and returns the frozen packet.

### Exact canonical hash payloads

Canonical JSON is UTF-8, `sort_keys=True`, separators `(",", ":")`; tuple members are serialized as
lists. Criteria sort by `(criterion, strength, scorer_provenance.bias_row_key)`, primary refs by
`ref_id`, flags/exclusions by lexical value, missing evidence by `(category, next_action)`, and point
contributions by `(criterion, strength)`.

- `evidence_core_hash` payload keys are exactly:
  `identity`, `entries`, `candidate_direction`, `exclusions`, `contradiction`, `quality_flags`,
  `missing_evidence`. Each entry includes every `CriterionEntry` field, including `rationale`, both raw
  dispositions, `decision_dependency`, `exclusion_reason`, all 13 scorer-provenance fields, all primary
  reference fields, grounding fields and `primary_required`.
- `narrative_plan_hash` hashes `null` when no plan; otherwise exactly `entries`, `model`,
  `prompt_hash`, with bindings sorted by `(name, field_path)`.
- `packet_envelope_hash` payload keys are exactly:
  `evidence_core_hash`, `narrative_plan_hash`, `packet_schema_version`,
  `run_pins` (`code_commit`, `packet_config_sha256`, `lineage_policy_sha256`,
  `candidate_policy_sha256`), `source_snapshot`, `pattern_ref`, `external_comparators`,
  `review_state`, `gate_status`, `predecessor_packet_id`, `predecessor_envelope_hash`.
  It excludes only `run_id` and `generated_at`. Comparator/pattern/state changes therefore create a
  new immutable envelope while leaving the evidence core unchanged.
- `decision_record_hash` is sha256 of `prev_hash + canonical(record_payload)`; `prev_hash` is lowercase
  hex-64 and Task C owns the exact record payload.

Tests use `dataclasses.replace` to vary frozen values. Mutation of a packet must raise
`FrozenInstanceError`; tests must never require a mutable packet.

## Disposition precedence (PRD §4.1 FR4.1 — implement exactly, first match wins)

`resolve_packet_policy_disposition(validation, production)` — validation dominates for this
pre-validation packet; both raw fields preserved on the `CriterionEntry`:

1. `validation == forbidden` → **excluded** (`direct_copy_forbidden`: PP5/BP6/PS4);
2. `validation == requires_heldout_mask` → **masked** — **regardless of** production (PS1/PM5/PM1/PP2/BP1);
3. `validation == deferred` **or** `production == deferred` → **deferred** with `decision_dependency` (PS3, BS2);
4. `validation == allowed` **and** `production == allowed` → **included**;
5. any other combination (incl. `production == forbidden` under a non-forbidden validation, or any
   unknown pairing) → **fail loud** (never silently `included`).

## Provenance schemas (PRD §4.1 FR4.2 — pinned; do not drop a field)

- `ScorerProvenance` (all required, strict formats): `bias_row_key, chromosome, position, ref, alt,
  scorer_run_id, input_sha256, output_sha256, raw_row_sha256, bias_version, bias_commit, nirvana_version,
  transcript`. Resolves to a **BIAS raw row**; is **never** a `PrimaryEvidenceRef`.
- `PrimaryEvidenceRef`: `ref_id, source_type, source_id/accession, locator/span, source_snapshot/version,
  source_sha256` (nullable only with `source_sha256_null_reason`), `supports_criterion, resolution_status
  ∈ {resolved, unresolved}, unresolved_reason`. `resolved` **only** with `source_id` + `locator`/`span`
  + `source_snapshot`/`version` + (checksum **or** non-blank checksum-null-reason).
- Each `CriterionEntry` = exactly one `scorer_provenance` + zero-or-more primary refs + `primary_grounding
  ∈ {present, absent, not_required}`. `primary_required` = any included/deferred functional/literature
  (PS3 / `literature_unvalidated`) claim + every config-flagged criterion; **unknown fails closed**.

## Hash domains (PRD §4.2 — four exact names)

1. `evidence_core_hash` — over the immutable evidence core (identity + sorted criterion trail + lineage +
   disposition + strengths/directions + two-level provenance refs + direction/null_reason + signed
   points + exclusions/contradictions/missing-evidence). **Excludes** narrative, comparators, run
   metadata, review state, decisions.
2. `narrative_plan_hash` — over the canonical narrative plan (template ids + bindings) + `model` +
   `prompt_hash`.
3. `packet_envelope_hash` — over `evidence_core_hash` + `narrative_plan_hash` + the **enumerated**
   run-metadata pins (schema version, config/policy versions, source snapshot id); **excludes** `run_id`,
   `generated_at`, other non-reproducible fields.
4. decision-log `record_hash` chain — separate append-only chain (`sha256(prev_hash + canonical(record))`);
   genesis `prev_hash = "0"*64`. (Chain producer lives in Task C; Task A supplies `decision_record_hash`.)

State/reviewer actions **must not mutate a prior packet hash**.

## Acceptance criteria (PRD §11.1 / §6 — the AC subset this task must satisfy; verbatim)

- **AC1** schema completeness + unknown-field fail-loud *(mechanical)*
- **AC2** deterministic JSON + four hashes (core excludes narrative/comparator/run-metadata) *(mechanical)*
- **AC3** no label/oracle/KB read + no `eval.*` import (forbidden-path/import audit) *(mechanical)*
- **AC4** `candidate_direction` nullable; `null_reason=production_policy_unapproved` *(mechanical)*
- **AC5** two-level provenance: exactly one `ScorerProvenance` (never a `PrimaryEvidenceRef`); primary
  optional/explicit-absent *(mechanical)*
- **AC6** exact signed-point arithmetic + policy version *(mechanical)*
- **AC7** machine-read lineage disposition + precedence (validation dominates; `requires_heldout_mask` →
  masked regardless of production) *(mechanical)*
- **AC8** contradiction preservation *(mechanical)*
- **AC19** four hash domains distinct + stable *(mechanical)*
- **AC21** exact provenance schemas (`ScorerProvenance` all-required strict; `PrimaryEvidenceRef`
  resolved/unresolved predicate; BIAS row never a `PrimaryEvidenceRef`) *(mechanical)*
- **AC22** disposition precedence exhaustive + fail-loud on unknown combination (r3-1) *(mechanical)*

Independent oracles (never the implementation's own output): hand-computed signed point sums (AC6);
hand-built expected JSON fixtures (AC2); the `bias_lineage.yaml` loader output as the lineage oracle
(AC7); the census stats file's recorded counts. `na_allowed: false`.

## Out of scope

Rendering; queue; state machine; decision log; comparator reveal; the LLM narrative call; the KB
adapter; any external release.

## Verification

Run the pre-authored Gemini tests for Task A and the full suite; show the frozen preservation set is
byte-unchanged (`git diff --check`, hash compare). The GPT checker re-verifies AC1/2/3/4/5/6/7/8/19/21/22
against the commands in your `VERIFICATION` block.
