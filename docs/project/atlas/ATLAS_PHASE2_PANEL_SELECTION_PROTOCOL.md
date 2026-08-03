# RAPTOR Mechanism Atlas — Phase 2 contrast-panel selection protocol

| Field | Value |
|---|---|
| Status | **REGISTERED / FROZEN — post-discovery, pre-selection** |
| Protocol version | `1.0.2` (pre-first-run correction of `1.0.1`; no selection run has ever executed) |
| Freeze timestamp | `2026-08-02T23:41:07+05:30` (`2026-08-02T18:11:07Z`) |
| Registration artifact | `docs/project/atlas/atlas-phase2-panel-selection-registration-v1.yaml` |
| Scope | Selection of the TSC2 missense contrast panel for the bounded Phase 2 Atlas pilot |
| Governs | Which already-discovered candidates enter the panel, and in what order |
| Does not govern | Whether any claim is true, admissible, or grounded (ADR-0015/ADR-0016, Gates 1–8) |
| Authority | Binding on panel **selection** only; subordinate to `docs/project/specs/mechanism-atlas-starter.yaml`, ADR-0014/0015/0016, and `tests/atlas/` |
| Clinical status | **None.** Research-use-only; asserts no mechanism, classification, prognosis or treatment |

> **Reading rule.** This protocol fixes the panel-selection procedure **before any panel is
> selected** and **after candidate discovery has already run**. It is therefore a
> *post-discovery, pre-selection registered protocol* — **not** a preregistration. It names no
> candidate, reports no candidate count, and states no functional result. It exists so that a
> separate executor can produce the panel mechanically, and so that a reader can verify the panel
> was not shaped by which results looked attractive.

---

## 1. Purpose, scope and non-clinical boundary

**Purpose.** Phase 2 of the RAPTOR Mechanism Atlas uses `TSC2 p.Arg611Gln (R611Q)` as its first
anchor. A single anchor cannot show that the mechanism ontology generalizes. The contrast panel is
the generalization test: a small set of additional TSC2 missense variants, spanning deliberately
different evidence situations, run through the same identity → source → span → context pipeline.

**In scope.** Defining, before selection: the locked candidate-universe handoff contract and its
binding to the complete discovery output, identity normalization, machine-executable stratum
determination, deterministic source-lineage collapse, eligibility/exclusion, panel size, coverage,
diversity and independence constraints, the deterministic fixed-size search, infeasibility
handling, the audit record, and the freeze/versioning procedure.

**Out of scope.** Source acquisition, claim extraction, span verification, contradiction analysis,
mechanism synthesis, and any classification. Those remain governed by ADR-0015 (internal summaries
are context-only; every real claim needs a primary publication or direct dataset with an exact
supporting span), ADR-0016 (deterministic offline citation resolver), and the eight-gate promotion
pipeline in `raptor.atlas.promote`.

**Non-clinical boundary.** Nothing produced under this protocol is a clinical, diagnostic, ACMG,
VCEP or ClinVar statement. Panel membership is a *sampling decision*. It is not evidence that a
variant is pathogenic, benign, damaging, tolerated, actionable or interesting.

---

## 2. Registration honesty and bias disclosure

**Disclosure (mandatory, must be reproduced in any citation of this protocol).** Candidate
discovery for the Phase 2 contrast panel was carried out **before** this protocol was written. The
author of this protocol was deliberately isolated from the discovery output, but the organization
as a whole already holds candidate-level information. This protocol is therefore registered
*post-discovery* and *pre-selection*, and must never be described as a preregistration.

**Residual risk.** Rules written after a candidate landscape is known can be tuned — consciously or
not — so that a desirable panel falls out of an apparently neutral procedure.

**Mitigations (binding).**

| # | Mitigation |
|---|---|
| M1 | This protocol contains **no candidate identifier, no candidate count, and no functional result**. Only structural rules. |
| M2 | The candidate universe is **locked, hash-pinned, and bound to the complete raw discovery inventory** by a pre-selection discovery-set commitment plus a total normalization ledger (§4.5), and is **pinned before any selection may run** by a separate immutable universe-lock record (§4.6). Omitting a discovered candidate, or rewriting the universe after normalization, is mechanically detectable. |
| M3 | Selection is **deterministic and complete over the full eligible universe**: `(frozen protocol version, locked universe hash, recorded seed)` reproduces the identical panel for any third party (§17). |
| M4 | The tie-breaking **seed is a fixed literal recorded at freeze time** (§17.2), independent of any candidate, universe content, or observed result. |
| M5 | Every universe record receives a recorded disposition with a rule id (§18). **No outcome-dependent replacement** (§18.3). |
| M6 | Normalization, identity admission, stratum assignment and source-lineage grouping are **replayed/recomputed by the executor** from the raw inventory and declared primitive fields and fail closed on disagreement (§4.5.5, §6, §7) — custodian-supplied outcomes are never trusted. |
| M7 | Any rule change requires a **version bump plus a new registration record** (§20.4). Re-running selection to obtain a different panel without a version bump and a recorded reason is a protocol violation. |
| M8 | The resulting panel is **provisional** until the named human-oracle review (`atlas-phase2-human-span-review`). |

**Permitted citation.** This protocol may be cited — including in the Anthropic rare-disease
application — **only** as a completed governance/method milestone ("a registered, deterministic
panel-selection protocol exists and was frozen before selection"). It may never be cited as a
scientific result, a validation, or evidence about any variant.

---

## 3. Roles

| Role | Responsibility | Prohibited from |
|---|---|---|
| Registrar | Freezes this protocol and its registration artifact | Selecting the panel |
| Universe custodian | Captures the immutable raw discovery inventory, normalizes it, emits the ledger and the locked universe (§4), and publishes the pre-selection universe-lock record **immediately after normalization and before any selection** (§4.6) | Filtering by attractiveness; editing a locked universe; publishing a lock record late, selectively, or more than once per `universe_version`; assigning strata or lineage groups by judgment |
| Selection executor (may be an agent) | Verifies all digests and the universe-lock record, **replays** normalization and pack identity admission from the raw inventory (§4.5.5), recomputes all derived fields, applies §17 mechanically, emits the run record | Any scientific judgment about which result is attractive; manual reordering; reseeding; trusting custodian outcomes; reading candidate evidence |
| Named human oracle | Reviews evidence downstream (Gate 8) | Retroactively rewriting the selection record |

The executor requires **no domain judgment**. If a step appears to need one, the protocol is
defective: stop, record `EXECUTOR_BLOCKED` with the ambiguous rule id, and escalate for a versioned
amendment. Do not improvise.

---

## 4. Locked candidate-universe handoff contract

### 4.1 Location, schema and hash

| Item | Value |
|---|---|
| Raw discovery inventory | `configs/atlas/panels/tsc2/discovery_inventory.raw.yaml` (immutable once captured) |
| Normalized universe | `configs/atlas/panels/tsc2/candidate_universe.yaml` |
| Pre-selection universe lock | `configs/atlas/panels/tsc2/atlas-phase2-candidate-universe-lock-v1.yaml` (tracked, candidate-free; §4.6) |
| Schema id | `atlas.candidate_universe.v1` |
| Self-hash field | `universe_content_hash` |
| Universe hash algorithm | `atlas.candidate_universe_content_hash.v1` — identical in construction to `atlas.pack_content_hash.v1`: `yaml.safe_load` the file, validate, strip **only** the top-level `universe_content_hash` key, serialize the remainder as canonical JSON (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`, sequence order preserved), lowercase SHA-256 hex |
| Raw inventory hash algorithm | `atlas.raw_inventory_hash.v1` — read as UTF-8, normalize by `atlas.text_norm.v1` (CRLF/CR → LF, NFC, no case-fold, no whitespace collapse), encode UTF-8, lowercase SHA-256 hex, plus the normalized byte length. Canonical-LF is mandatory because this repository checks out with `core.autocrlf=true` |
| Ledger hash algorithm | `atlas.normalization_ledger_hash.v1` — canonical-JSON serialize the `normalization_ledger` sequence exactly as it appears in the universe file (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`, row order preserved), lowercase SHA-256 hex, plus the row count |

The raw inventory and the normalized universe carry candidate identities and **may live under the
external, uncommitted content root** if licensing or data-handling rules require it; the paths above
are then relative to that root. The **universe lock record of §4.6 is candidate-free and must be
tracked in the repository regardless**, so the commitment is durable even when the data is not.

All dates/timestamps in these files are **quoted strings** so the canonical-JSON hash is computable
without type coercion.

### 4.2 Required top-level fields of the normalized universe

`schema`, `universe_id`, `universe_version`, `universe_content_hash`, `gene`, `assembly`,
`transcript_pin`, `pack_binding` (`pack_id`, `pack_version`, `pack_content_hash`),
`discovery_run_ref` (opaque run id + ISO timestamp string), `raw_inventory` (§4.5.1),
`discovery_set_commitment` (§4.5.2), `normalization_ledger` (§4.5.3), `completeness_attestation`,
`records`.

### 4.3 Required per-record fields

**Identity and structure:** `record_id`, `universe_key` (§5.6), `identity_state`
(`resolved` | `unresolved`), `spdi_canonical` (required iff `resolved`), `hgvs_c`, `hgvs_p`,
`residue_index`, `codon_index`, `consequence_class`.

**Stratum primitives** (inputs to §6; the six functional strata are **derived**, never declared as
an opinion): `functional_evidence_present` (bool) and `observations` (list; empty iff
`functional_evidence_present == false`). Each observation carries:

`observation_id`, `reported_outcome_bucket` ∈ {`substantial_deviation`, `intermediate_deviation`,
`near_reference`}, `assay_kind` (pack-ontology id), `model_system`, `cell_or_tissue`,
`zygosity_context`, `throughput_class` ∈ {`low_throughput`, `high_throughput`},
`source_identifiers` (normalized `PMID:`/`PMCID:`/`DOI:`/`ACCESSION:` forms per ADR-0016),
`dataset_accession` (or `null`), `version_of` (normalized identifier of the preprint/journal
counterpart, or `null`), `experimental_program_id` (or `unknown`), `lab_lineage_key` (or
`unknown`), `assay_protocol_lineage_key` (or `unknown`), `derived_from_observation_ids` (list),
`access_status` ∈ {`open_lawful`, `restricted`, `unknown`}, `license_family`,
`span_verifiable` (bool), `bucket_basis` (the declared, attributable basis for the bucket).

**Compatibility axis (§10):** `spec_stratum` ∈ {`known_pathogenic`, `known_benign`, `conflicting`,
`vus_with_functional_evidence`, `vus_without_functional_evidence`}, plus `spec_stratum_basis`
(which label source/review status drove it) and `spec_stratum_derivation` ∈ {`external_label`,
`recomputed_from_locked_observations`} (§10.1).

**Record-level derived fields, declared by the custodian and recomputed by the executor:**
`all_matched_strata`, `primary_stratum` (§6), `support_source_groups`, `lineage_confidence`,
`support_class` (§7, §14), `exclusion_flags`.

Optional: `region_id` (protein domain/region), reported but never constraining (§16.5).

### 4.4 Permitted and prohibited universe content

**Permitted (and required) as *sampling metadata*:** the enumerated, attributable fields above,
including `reported_outcome_bucket`. A bucket is a coarse, three-valued, per-observation record of
*what a source reported*, always attributed via `bucket_basis`. It is **never verified, never
quoted, never admissible, and never a mechanism statement**; the Atlas is free to contradict it and
must report such contradictions (§18.4).

**Prohibited (contract failure):**

* Free-text mechanism narrative; effect sizes, scores, percentages, p-values, or thresholds;
  any aggregated "consensus" or "overall" verdict across observations.
* Any ranking, priority, novelty, "recommended", "promising" or "interesting" field.
* Any declared stratum or lineage grouping that is not reproducible from the primitive fields.
* Classifier scores or ClinVar-derived criteria anywhere except as `spec_stratum_basis` for the
  compatibility axis (§10), which never enters the functional-stratum predicates (§6.2).
* Patient-level, identifiable or non-public data; paywalled full text or its derivatives.
* Free-text commentary fields other than the enumerated basis fields.

### 4.5 Binding the universe to the complete discovery output

#### 4.5.1 Raw inventory artifact (immutable)

`raw_inventory` records: `path`, `captured_at` (quoted ISO string), `record_count`,
`content_hash_algorithm: atlas.raw_inventory_hash.v1`, `content_hash`, `normalized_byte_length`,
`format`. The raw inventory is the discovery output **as produced**, one row per emitted candidate,
each row carrying at minimum `raw_record_id` and `raw_identity_string`. It is captured **before**
normalization, is never edited, and never has rows removed. Additions after capture require a new
`raw_inventory` capture, a `universe_version` bump, and a full re-run.

#### 4.5.2 Pre-selection discovery-set commitment

```text
raw_identity_normalized(s) = collapse_internal_whitespace_runs_to_one_space(
                                 strip( NFC(s) ) )          # NO case-folding: HGVS is case-bearing

universe_key(record)       = spdi_canonical                          if identity_state == resolved
                           = "UNRESOLVED:" + sha256(utf8(raw_identity_normalized(raw_identity_string)))
                                                                     if identity_state == unresolved

discovery_set_count        = number of DISTINCT universe_key values
discovery_set_hash         = sha256( utf8( "\n".join( sorted(distinct universe_key values) ) ) )
```

`discovery_set_commitment` records `discovery_set_count`, `discovery_set_hash`, the algorithm id
`atlas.discovery_set_commitment.v1`, and a quoted `committed_at`. It is inside the hashed universe
file and therefore locked before selection.

**Unresolved identities are never dropped.** They become universe records with
`identity_state: unresolved`, a surrogate `universe_key`, and exclusion `X1` (§8.2). They still
count in `discovery_set_count`, still appear in the audit, and are reported as an explicit
`unresolved_identity_count` in the run record. Silent omission is a contract breach, not an
eligibility decision.

#### 4.5.3 Normalization ledger (total function, no silent loss)

One ledger row per raw inventory row: `raw_record_id`, `raw_identity_string`,
`normalization_rule_id`, `normalization_outcome` ∈ {`resolved_identity`, `collapsed_duplicate`,
`unresolved_identity`, `out_of_scope_consequence`, `out_of_scope_gene_or_transcript`}, and
`universe_key` (always present — `out_of_scope_*` and `unresolved_*` rows still map to a key and
still yield a universe record carrying the corresponding exclusion code).

#### 4.5.4 Conservation checks (executor recomputes; all fail closed)

| Id | Check |
|---|---|
| U1 | Recomputed `atlas.raw_inventory_hash.v1` equals `raw_inventory.content_hash`, and the row count equals `raw_inventory.record_count` |
| U2 | `len(normalization_ledger) == raw_inventory.record_count`, and `raw_record_id` values are unique and in bijection with the raw inventory rows |
| U3 | The set of distinct `universe_key` values in the ledger equals the set of `universe_key` values across `records`, with exactly one record per distinct key |
| U4 | Recomputed `discovery_set_count` / `discovery_set_hash` from `records` equal the committed values |
| U5 | Recomputed `atlas.candidate_universe_content_hash.v1` equals `universe_content_hash` |
| U6 | `completeness_attestation` is present, names the attesting role, and states that no discovered candidate was withheld and no record was added after any selection was attempted |
| U7 | The §4.5.5 normalization/admission **replay** reproduces every ledger row and every record identity field exactly |

Any failure ⇒ `UNIVERSE_CONTRACT_BREACH`: the run terminates, no panel is emitted.

### 4.5.5 Mandatory executor replay of normalization and admission (fail-closed)

The executor **recomputes normalization from the raw inventory** and never trusts the custodian's
recorded outcomes. For every raw row `r`, it applies the deterministic §5 rules and the bound pack's
`raptor.atlas.identity.admit_identity` to `r.raw_identity_string`, obtaining a replayed tuple:

```text
replay(r) = ( normalization_outcome, universe_key, identity_state, spdi_canonical,
              hgvs_c, hgvs_p, transcript_pin, residue_index, codon_index,
              consequence_class, scope_decision, exclusion_code )
```

| Id | Replay check (each fails closed with `UNIVERSE_CONTRACT_BREACH` and the offending `raw_record_id`) |
|---|---|
| RP1 | Replayed `normalization_outcome` equals the ledger row's value |
| RP2 | Replayed `universe_key` equals the ledger row's and the referenced record's `universe_key` |
| RP3 | Replayed `identity_state` equals the record's; a row declared `resolved` that fails to admit, **or** a row declared `unresolved` that does admit, is a breach — unresolved rows must be confirmed genuinely unresolved, never accepted on assertion |
| RP4 | Replayed `spdi_canonical`, `hgvs_c`, `hgvs_p`, `transcript_pin`, `residue_index`, `codon_index` equal the record's (character-identical after `atlas.text_norm.v1`) |
| RP5 | Replayed `consequence_class` and `scope_decision` (in-scope / `out_of_scope_consequence` / `out_of_scope_gene_or_transcript`) equal the declared values, and are themselves derived only from the raw identity string plus the pinned pack under §5 rules 8–9 — never from a custodian assertion |
| RP6 | Replayed eligibility exclusion code (§8.2) equals the declared `exclusion_flags` for every excluded record |
| RP7 | The replayed ledger is a bijection onto the raw rows (`U2`) and its `universe_key` image equals the record set (`U3`); duplicate collapse (§5 rule 5) reproduces the same surviving `record_id` |

Replay is **deterministic and offline**: it reads the raw inventory, the pinned pack and this
protocol only. It never fetches sources, never consults evidence, and never repairs a mismatch — a
mismatch is reported, not corrected. The run record carries a `normalization_replay` attestation
with the replayed row count and the count of each `normalization_outcome`.

### 4.6 Pre-selection universe lock record (mandatory, candidate-free)

The universe file's own self-hash is **not** sufficient: a custodian could rewrite both the universe
and its self-hash at any moment before the first run. The commitment is therefore externalized into
a separate, tracked, candidate-free lock record that must exist **before** selection.

| Item | Value |
|---|---|
| Path | `configs/atlas/panels/tsc2/atlas-phase2-candidate-universe-lock-v1.yaml` |
| Schema id | `atlas.candidate_universe_lock.v1` |
| Self-hash field | `lock_content_hash` |
| Hash algorithm | `atlas.universe_lock_content_hash.v1` — `yaml.safe_load`, strip **only** the top-level `lock_content_hash` key, canonical JSON (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`), lowercase SHA-256 hex. Non-circular: the record never contains a digest of itself as input |
| Tracked | **Yes**, always — even when the universe and raw inventory live under the external uncommitted content root |
| Created | **Immediately after normalization completes and before any selection attempt**; exactly one lock record per `universe_version` |

**Required fields** (all timestamps quoted strings; no candidate identity, no candidate count beyond
the aggregate counts below, no result of any kind):

`schema`, `lock_id`, `lock_version`, `universe_id`, `universe_version`, `created_at`,
`created_by_role`, `protocol_version` and `protocol_doc_hash` in force at lock time,
`registration_content_hash` in force at lock time, `universe_content_hash`,
`universe_content_hash_algorithm`, `raw_inventory` (`path`, `content_hash`,
`content_hash_algorithm`, `record_count`, `normalized_byte_length`, `captured_at`),
`normalization_ledger` (`hash`, `hash_algorithm`, `row_count`), `discovery_set_commitment`
(`hash`, `hash_algorithm`, `count`, `committed_at`), `pack_binding` (`pack_id`, `pack_version`,
`pack_content_hash`), `storage_location` (`repository` | `external_content_root`),
`completeness_attestation_ref`, `lock_content_hash`.

**Executor obligations (precondition `V5`, §17.1):**

| Id | Lock check |
|---|---|
| K1 | The lock record exists at the declared path; absence ⇒ `UNIVERSE_LOCK_MISSING`, terminate |
| K2 | Recomputed `atlas.universe_lock_content_hash.v1` equals its stored `lock_content_hash` ⇒ else `UNIVERSE_LOCK_CORRUPT`, terminate |
| K3 | `universe_content_hash`, `raw_inventory.content_hash` + `record_count`, `normalization_ledger.hash` + `row_count`, and `discovery_set_commitment.hash` + `count` in the lock record equal the values recomputed from the live artifacts ⇒ else `UNIVERSE_LOCK_MISMATCH`, terminate |
| K4 | `pack_binding.pack_content_hash` in the lock record equals the live pack hash and the registration snapshot (§17.1 `V4`) |
| K5 | The lock's `protocol_doc_hash` / `registration_content_hash` either equal the digests in force, or the run explicitly records a `lock_protocol_version_delta` naming both versions; a delta never waives `K3` |
| K6 | Exactly one lock record exists for the cited `universe_version`; a second lock record for the same version, or a lock `created_at` later than any selection attempt, ⇒ `UNIVERSE_LOCK_INVALID`, terminate |

A universe that is not locked is not selectable. There is no "unlocked run", no "provisional run",
and no override flag.

### 4.7 Immutability and the no-names rule

Once a universe is locked (§4.6) it is frozen — not merely once a run cites it. A correction
requires a `universe_version` bump, a recorded reason, a **new** lock record, retention of the
superseded lock and its audit, and a full deterministic re-run — never a patch to a live selection.
This protocol deliberately contains no candidate identity; the universe file is the only place
candidate identities are enumerated, and the lock record deliberately contains none.

---

## 5. Identity normalization

1. `gene` must be `TSC2`; `assembly` and `transcript_pin` must equal the pinned GRCh38 assembly and
   MANE-Select transcript of the bound disease pack (`configs/atlas/packs/tsc2/pack.yaml`).
2. `spdi_canonical` is the **primary key** of a resolved candidate. It must be admissible by
   `raptor.atlas.identity.admit_identity` under the bound pack; an identity that does not admit is
   recorded `identity_state: unresolved` with exclusion `X1` — never guessed, repaired by
   inference, or deleted.
3. `hgvs_c` / `hgvs_p` must use the pinned transcript and its protein accession. Legacy numbering,
   transcript-ambiguous, protein-only-without-resolvable-`c.`, and non-canonical nomenclature yield
   `unresolved`.
4. `residue_index` and `codon_index` must be derivable from `hgvs_p` / `hgvs_c` and drive §16.
5. Records sharing an identical `spdi_canonical` are **one** candidate: collapse to the
   lexicographically smallest `record_id`, mark the absorbed ledger rows `collapsed_duplicate`, and
   record the collapse in the audit (`X4`).
6. `universe_key` is defined in §4.5.2 and is the join key across the raw inventory, the ledger,
   the universe records, and the run record.
7. Distinct nucleotide changes yielding the same protein substitution remain distinct records but
   share a residue key and therefore compete under §16.
8. **Scope decisions are computed, not asserted.** `scope_decision` is derived from the raw identity
   string plus the pinned pack alone: a row whose resolved gene/transcript is not the pinned
   `TSC2` MANE-Select transcript is `out_of_scope_gene_or_transcript` (`X10`); a row that resolves
   on the pinned transcript but whose `consequence_class` — itself derived from the reference and
   alternate residues at `codon_index` — is not a single missense substitution is
   `out_of_scope_consequence` (`X2`). A row that cannot be resolved far enough to decide scope is
   `unresolved` (`X1`), never "out of scope" by default.
9. These rules are a **total deterministic function** from a raw inventory row to a normalized
   record. The executor replays them for every raw row under §4.5.5 and fails closed on any
   disagreement; the custodian's recorded outcome carries no authority.

---

## 6. Machine-executable stratum determination

### 6.1 Observation comparison primitives

For a record with observation list `O` (`|O| = m`):

```text
buckets(O)            = { o.reported_outcome_bucket : o in O }            # a SET
context_key(o)        = (o.assay_kind, o.model_system, o.cell_or_tissue, o.zygosity_context)
differing_pair(o1,o2) = o1.reported_outcome_bucket != o2.reported_outcome_bucket
same_context(o1,o2)   = context_key(o1) == context_key(o2)
```

A bucket difference is treated as disagreement even between `substantial_deviation` and
`intermediate_deviation`. This is deliberately conservative: it routes graded differences toward
the contested strata rather than toward a clean extreme.

### 6.2 Stratum predicates (declared here; evaluated over §4.3 primitives only)

| Stratum | Predicate `P(S)` |
|---|---|
| `S6` evidence-poor / abstention | `functional_evidence_present == false` (equivalently `m == 0`) |
| `S4` conflicting across assays | `m ≥ 2` ∧ ∃ `(o1,o2)`: `differing_pair(o1,o2)` ∧ `same_context(o1,o2)` |
| `S5` context-dependent | `m ≥ 2` ∧ ∃ `(o1,o2)`: `differing_pair(o1,o2)` ∧ ¬`same_context(o1,o2)` |
| `S2` partial / intermediate | `m ≥ 1` ∧ `intermediate_deviation ∈ buckets(O)` |
| `S3` null / benign-like | `m ≥ 1` ∧ `near_reference ∈ buckets(O)` |
| `S1` strong functional signal | `m ≥ 1` ∧ `substantial_deviation ∈ buckets(O)` |

Predicates are **independent**, so multi-stratum matching is normal and expected. No classification
label, computational score, `spec_stratum`, or access/licence field is an input to any predicate
(§9.1 firewall).

### 6.3 `all_matched_strata`, precedence and `primary_stratum`

* `all_matched_strata` = every `S` with `P(S)` true, listed in the declared order **Ω**.
* **Ω = `[S6, S4, S5, S2, S3, S1]`** — one declared order used for *both* precedence and
  processing (§17.5). Rationale, fixed in advance: `S6` is mutually exclusive with the rest;
  contested strata (`S4`, `S5`) dominate graded ones; the scarcer intermediate stratum (`S2`)
  precedes the abundant extremes (`S3`, `S1`), so cap pressure never falls on the informative
  strata.
* `primary_stratum` = the **first element of `all_matched_strata` under Ω**. There is no
  discretionary primary assignment anywhere in this protocol.
* The executor recomputes `all_matched_strata` and `primary_stratum` from the primitives. Any
  disagreement with the declared values ⇒ `UNIVERSE_CONTRACT_BREACH` (fail closed).
* A record with `functional_evidence_present == true` but `m == 0`, or `false` with `m > 0`, is a
  contract breach.

### 6.4 Coverage semantics

Coverage (§11.3) counts a member under its `primary_stratum` **only**; a stratum is *non-empty*
iff at least one eligible record has it as `primary_stratum`. Secondary matches are preserved and
published as an auxiliary-coverage table (§18.1) but never fill a coverage slot — this keeps
coverage single-valued, deterministic and non-gameable.

---

## 7. Source lineage: normalization and deterministic collapse

Opaque, custodian-supplied group ids are not trusted. Groups are **recomputed** from the declared
normalized provenance fields of §4.3.

### 7.1 Collapse edges

Build an undirected graph over all observations in the universe. Add an edge between `o1` and `o2`
when **any** of:

| Id | Edge rule |
|---|---|
| L1 | Equal non-null normalized `dataset_accession` (shared dataset/accession) |
| L2 | Version linkage: `o1.version_of` resolves to a `source_identifier` of `o2` (or vice versa) — preprint and journal versions of the same work are one lineage |
| L3 | Equal non-null `experimental_program_id` (same experimental program/screen) |
| L4 | Equal non-null `lab_lineage_key` **and** equal non-null `assay_protocol_lineage_key` (same lab/method lineage) |
| L5 | Derivation reachability via `derived_from_observation_ids` (follow-up reports re-analyzing the same assay program) |
| L6 | Any shared normalized `source_identifier` |

`source_group` = a connected component. Its deterministic id is

```text
lineage_group_key = "LG:" + first16hex( sha256( utf8( "|".join( sorted(distinct normalized source_identifiers in the component) ) ) ) )
```

so the id is stable under renaming and cannot be shopped. Declared `support_source_groups` are
compared with the recomputation; mismatch ⇒ `UNIVERSE_CONTRACT_BREACH`.

### 7.2 Unknown lineage is conservative, never assumed independent

An observation with `lab_lineage_key == unknown` **or** `assay_protocol_lineage_key == unknown`
(and no L1/L2/L3/L5/L6 edge that already establishes its lineage) has
`lineage_confidence: unknown`. For every independence constraint (§13):

* Groups containing any `unknown`-lineage observation are pooled into the **single** conservative
  pseudo-group `LG:UNKNOWN-POOL`. Unknowns are never counted as multiple independent sources.
* Only groups whose members are all `lineage_confidence: established` count toward the distinct
  source-group minimum `P2`.
* Pooling itself is **never** relaxed. If pooling makes the constraint set unsatisfiable, relief
  comes only through the declared ladder (§13.2), with `lineage_unknown_observation_count` and
  `lineage_unknown_record_count` disclosed in the run record.

---

## 8. Eligibility and exclusion

### 8.1 Eligibility predicate (all must hold)

| Id | Rule |
|---|---|
| E1 | `identity_state == resolved` and the identity admits under §5 |
| E2 | The protein consequence is a **single missense substitution** in TSC2 (no nonsense, frameshift, splice, in-frame indel, synonymous, or multi-residue change) |
| E3 | The record is neither the R611Q anchor identity nor any other substitution at the anchor residue (§16.3) |
| E4 | Either at least one observation has `access_status == open_lawful` ∧ `span_verifiable == true`, **or** the record is a bona fide `S6` member (`functional_evidence_present == false`) |
| E5 | All supporting material is public and lawfully usable; no patient-identifiable content |
| E6 | `primary_stratum` recomputes to exactly one of the six strata (§6) |
| E7 | All required fields of §4.3 are present and well-formed, and all §4.5.4 conservation checks pass |
| E8 | No hard exclusion flag is set (retracted source, licence prohibits verification use, identity disputed at the source) |

### 8.2 Exclusion codes (eligibility failures — recorded for every failing record)

`X1` identity_unresolved · `X2` not_single_missense · `X3` anchor_or_anchor_residue ·
`X4` duplicate_identity_collapsed · `X5` access_blocked_and_not_evidence_absent ·
`X6` metadata_incomplete · `X7` stratum_underivable · `X8` hard_exclusion_flag ·
`X9` non_public_or_identifiable_source · `X10` out_of_scope_gene_or_transcript.

### 8.3 Selection dispositions (not eligibility failures — separate vocabulary)

`SEL` selected · `NS_CAP_SOURCE` source-concentration cap ·
`NS_CAP_HIGH_THROUGHPUT` single-high-throughput cap ·
`NS_CAP_ASSAY` assay-share cap · `NS_STRATUM_FULL` stratum share cap ·
`NS_COLLISION_RESIDUE` / `NS_COLLISION_CODON` lost the residue/codon draw ·
`NS_NOT_IN_SOLUTION` eligible and considered, not part of the accepted solution.

Every eligible record is considered: there is no pre-search cutoff disposition (the v1.0.1
`NS_SHORTLIST_CUTOFF` was removed in v1.0.2, §17.4). "Eligible but not selected" must never be
recorded as an exclusion. That distinction is what makes the audit falsifiable.

---

## 9. Firewall, lawful access and the anti-proxy rule

### 9.1 The firewall (highest-priority rule in this document)

**Selection metadata is not evidence.** Strata, `spec_stratum`, ClinVar classifications,
computational/classifier scores, `reported_outcome_bucket`, `support_class`, `access_status` and
`license_family` may be used **only** to sample candidates. They may never:

* become an `ObservedClaim`, a `MechanismEdge`, or support for either;
* satisfy grounding, replace an exact span, or influence Gate 1–8 outcomes;
* be reported as a mechanism, a classification, or a functional result.

Existing repository language may use `pathogenic` / `benign` / `conflicting` / `VUS` as selection
labels. Under this protocol those words define **sampling strata only** (§10). Gate 7
(`no_classification_leakage`) and the static leakage scanner remain the enforcement mechanism; this
section is a selection-side restatement, not an exemption.

### 9.2 Evidence admissibility is unchanged

A panel member's claims are admissible only under the existing rules: a primary publication or
direct dataset, `role == direct_evidence_leaf`, `source_type ∈ {PRIMARY-LIT, DATASET}`,
`permitted_use == grounding_and_quote`, `verification == verified`, verified local content, and an
exact quote at a `text-char:<start>:<end>` locator against text normalized by `atlas.text_norm.v1`.
Selection under this protocol grants **no** admissibility.

### 9.3 Lawful access and licensing

Only public and appropriately licensed content may be acquired, stored or quoted. No paywall
circumvention, no redistribution of restricted full text, and no committed source artifacts — raw
and extracted-text files live under an external, uncommitted content root (ADR-0016).
`license_family` and `access_status` are recorded per observation.

### 9.4 Anti-proxy rule: open access must not become a proxy for positive findings

1. **Access-blocked ≠ evidence-absent.** `access_status = restricted` (evidence exists but cannot
   be lawfully verified here) and `functional_evidence_present = false` (`S6`) are **different
   states**. Only the latter may serve as the abstention control (§15).
2. **Unavailable evidence is documented, not deleted.** Access-blocked candidates remain in the
   locked universe with `X5` recorded.
3. **Attrition is published.** The run record reports the count and per-stratum distribution of
   `X5` exclusions plus a plain statement that these were dropped for access reasons and **not**
   for any evidential reason.
4. **No inference from access.** Being unreadable here is never absence of effect; being open
   access is never evidence quality.

---

## 10. Taxonomy governance and the fail-closed crosswalk

Two taxonomies exist and **both remain in force**. Neither is overwritten.

| Axis | Vocabulary | Source of authority | Role |
|---|---|---|---|
| Functional-situation strata (six) | `S1`–`S6` (§6) | This protocol | **Governs selection coverage** (`C1`–`C4`) |
| Spec strata (five) | `known_pathogenic`, `known_benign`, `conflicting`, `vus_with_functional_evidence`, `vus_without_functional_evidence` | `docs/project/specs/mechanism-atlas-starter.yaml` §`panel_selection_contract.required_strata` | **Governs compatibility coverage** (`C5`) and is reported in every run record |

The two axes are **orthogonal and independently declared**, not derived from one another: the
functional axis comes from reported-observation primitives (§6.2); the spec axis comes from
classification/review-status labels (`spec_stratum_basis`). No crosswalk collapses one into the
other, because that would let a classification label determine a functional stratum.

### 10.1 Deterministic compatibility matrix

Discordance between an external classification label and the functional strata is **flagged and
reported, never corrected, and never fatal**. A definitional contradiction is fatal **only** when
the spec label was itself deterministically recomputed from the same locked observations — because
only then can the contradiction be internal to one dataset rather than an artifact of a stale
external label.

`spec_stratum_derivation` (§4.3) selects the regime:

* `external_label` — the label came from an outside classification/review source (ClinVar, a VCEP,
  a legacy sampling table). Such a label may simply predate the observations in the locked
  universe. **Every** cell below is permitted; contradictory cells are `report_only_discordant`.
* `recomputed_from_locked_observations` — the custodian derived `spec_stratum` mechanically from the
  same `observations` list that feeds §6, using declared rules recorded in `spec_stratum_basis`.
  Only in this regime is a contradictory cell a `UNIVERSE_CONTRACT_BREACH`, because the same input
  set cannot both have and lack functional evidence.

| `spec_stratum` | `S6` | `S1` | `S2` | `S3` | `S4` | `S5` |
|---|---|---|---|---|---|---|
| `known_pathogenic` | permitted | permitted | permitted | permitted + `discordant` | permitted | permitted |
| `known_benign` | permitted | permitted + `discordant` | permitted | permitted | permitted | permitted |
| `conflicting` | permitted | permitted | permitted | permitted | permitted | permitted |
| `vus_with_functional_evidence` | **contradictory** | permitted | permitted | permitted | permitted | permitted |
| `vus_without_functional_evidence` | permitted | **contradictory** | **contradictory** | **contradictory** | **contradictory** | **contradictory** |

Handling of a **contradictory** cell:

| `spec_stratum_derivation` | Outcome |
|---|---|
| `external_label` | `stale_label_discordant: true`, counted and named in the run record, record stays fully eligible; **no abort, no relabelling** of either axis |
| `recomputed_from_locked_observations` | `UNIVERSE_CONTRACT_BREACH` (internal inconsistency in one locked observation set) |

`discordant` cells set `label_function_discordant: true` and are likewise counted, never corrected.
Neither flag ever alters a functional stratum, an eligibility outcome, or a selection order:
classification and legacy sampling labels are kept strictly separate from functional evidence, and a
stale label is a fact about the label, not about the variant.

### 10.2 Compatibility coverage (`C5`)

At level `L0` the panel must include ≥1 selected member for every `spec_stratum` value that is
non-empty among eligible records. `C5` is the **first** constraint relaxed by the ladder (§13.2,
step `R1`) because it is the most label-dependent requirement; when relaxed, the run record reports
`spec_taxonomy_coverage: PARTIAL` with the uncovered values named. `C5` never overrides `C1`/`C2`.

No amendment to `mechanism-atlas-starter.yaml` is required or made: its `required_strata` remain
binding via `C5`, its `size: {min: 5, max: 10}` matches §11.2, and no test or document pins a
different reading.

---

## 11. Panel size and coverage

### 11.1 Strata (sampling labels only — see §9.1)

| Id | Stratum | Intent |
|---|---|---|
| `S1` | strong functional-loss / strong signal | A substantial reported deviation |
| `S2` | partial / intermediate | An intermediate reported deviation |
| `S3` | null / benign-like functional result | A near-reference reported result |
| `S4` | conflicting across assays | Reported results disagree within comparable context |
| `S5` | context-dependent | Reported results differ across declared context keys |
| `S6` | evidence-poor / abstention | No functional observations exist |

A stratum describes the *literature situation*, not a prediction of the Atlas outcome. Contradiction
by the Atlas is a reportable result, never a reason to re-select (§18.4).

### 11.2 Size rule (no circular dependence on the result)

* `K` = number of strata that are non-empty by `primary_stratum` among eligible records.
* `N_target = clamp(K + 2, 5, 10)`.
* Selection proceeds by **fixed-size attempts** `n = N_target, N_target − 1, …, 5` (§17.3). Every
  cap in §11.3, §12 and §13 is computed from the **attempt size `n`**, never from an unknown
  outcome size.
* `N_selected` is defined **only after** a valid solution exists, as the `n` of the accepted
  attempt. The panel is always within **5–10** members.

### 11.3 Coverage constraints (evaluated at attempt size `n`)

| Id | Constraint |
|---|---|
| C1 | Each non-empty stratum contributes **at least one** selected member |
| C2 | `S6` contributes at least one member when non-empty (abstention control, §15) |
| C3 | No stratum contributes more than `ceil(n / 2)` members |
| C4 | Stratum assignment is recomputed, never re-labelled to achieve coverage |
| C5 | Compatibility coverage across the spec taxonomy (§10.2) |

`C1`, `C2` and `C4` are **never** relaxed.

---

## 12. Assay, model and context diversity

Computed from observation-level `assay_kind` / `model_system` (selection metadata, §9.1),
evaluated at attempt size `n`.

| Id | Constraint |
|---|---|
| D1 | The panel spans **≥ 3 distinct assay kinds** |
| D2 | The panel spans **≥ 2 distinct model systems** |
| D3 | No single assay kind is present in more than `ceil(n / 2)` members |
| D4 | If any eligible candidate has ≥ 2 distinct assay kinds, at least one such candidate is selected |

---

## 13. Source concentration, independence, and the fail-closed ladder

### 13.1 Constraints (evaluated at attempt size `n`, over recomputed lineage groups §7)

| Id | Constraint |
|---|---|
| P1 | No single `source_group` is the **sole** support of more than `ceil(n / 2)` selected members |
| P2 | The panel draws on **≥ 3 distinct established-lineage `source_group`s** (`LG:UNKNOWN-POOL` never counts as more than one, and never as established) |
| P3 | At most **2** selected members have `support_class = single_high_throughput_only` (§14) |

### 13.2 Relaxation ladder (fixed order, weakest requirement first)

Constraint levels `L0` (declared) … `L7`. The executor **never improvises**: it exhausts every
attempt size at level `L` before moving to `L+1`, so a fully independent smaller panel is always
preferred over a larger relaxed one.

| Step | Relaxation | Why here |
|---|---|---|
| R1 | `C5` spec-taxonomy coverage → report-only | Most label-dependent, least evidential |
| R2 | `P2` minimum established groups 3 → 2 | First independence concession |
| R3 | `P1` sole-support cap `ceil(n/2)` → `ceil(2n/3)` | Concentration before diversity loss |
| R4 | `D1` minimum assay kinds 3 → 2 | |
| R5 | `P3` single-high-throughput cap 2 → 3 | |
| R6 | `D2` minimum model systems 2 → 1 | |
| R7 | `P2` minimum established groups → 1 (single-source panel) | Terminal |

Rules: each applied step is recorded with `relaxation_step`, the triggering constraint, and
before/after values; relaxation may **only** make the constraint set satisfiable and may **never**
be invoked to admit a particular candidate; any level `> L0` stamps
`independence_status: RELAXED` and the run record must state plainly, in prose, that the available
literature could not supply the declared independence. Lineage pooling (§7.2), eligibility (§8),
the firewall (§9.1), coverage `C1`/`C2`/`C4`, the anti-proxy rule (§9.4) and the dedupe rules (§16)
are **never** relaxed.

**Relaxation requires proven infeasibility (v1.0.2).** A level `L` may be left for `L+1` **only if
every attempt at level `L` terminated as `INFEASIBLE_COMPLETE`** — i.e. the search space was
exhausted over the full eligible universe. If any attempt at level `L` ended `UNDETERMINED`
(resource budget exhausted, §17.4), the run terminates immediately with
`UNDETERMINED_SEARCH_INCOMPLETE`: **no relaxation is applied and no infeasibility is declared**, and
the record names the undetermined attempts. A resource limit may never be used as evidence that the
literature is inadequate.

### 13.3 Terminal outcomes when no panel is found

* Every attempt at every level `INFEASIBLE_COMPLETE` ⇒ `INFEASIBLE_PANEL`. No panel is emitted, and
  no constraint outside the ladder is weakened to reach a number.
* Any attempt `UNDETERMINED` ⇒ `UNDETERMINED_SEARCH_INCOMPLETE` (§17.4). This is an honest
  "not computed", not a finding about the literature; the correct response is to re-run with a
  larger budget or a more efficient complete solver, never to relax a constraint.

---

## 14. Candidates supported only by one high-throughput dataset

### 14.1 `support_class` (recomputed by the executor from §4.3 primitives)

| Value | Definition |
|---|---|
| `multi_independent` | ≥ 2 established-lineage `source_group`s |
| `single_low_throughput` | Exactly 1 group; no observation is `high_throughput` |
| `single_high_throughput_only` | Exactly 1 group and every observation is `high_throughput` |
| `access_blocked` | Observations exist but none is `open_lawful` ∧ `span_verifiable` |
| `evidence_absent` | `functional_evidence_present == false` |

### 14.2 Constraints

| Id | Constraint |
|---|---|
| H1 | `P3` applies: at most 2 selected members are `single_high_throughput_only` |
| H2 | A stratum's mandatory `C1` member may not be `single_high_throughput_only` while a non-`single_high_throughput_only` eligible member exists in that stratum |
| H3 | Every selected `single_high_throughput_only` member is flagged, and its downstream Atlas output must carry the limitation: one dataset, one assay context, no independent replication |

A large multiplexed dataset is one observation context, not a consensus. Its scale is never treated
as independent replication.

---

## 15. Evidence-poor / abstention control

1. When `S6` is non-empty, at least one `S6` member is selected (`C2`).
2. The expected output for that member is `UNKNOWN` / empty / no accepted claim. Producing no claim
   is a **PASS**, reported as such.
3. Coercing an `S6` member into a claim, or substituting a better-evidenced candidate to avoid an
   empty result, is a protocol violation.
4. `access_blocked` candidates may **not** serve as the abstention control (they test access, not
   evidence sparsity); their count is reported (§9.4).
5. When `S6` is empty, the run is stamped `ABSTENTION_CONTROL_MISSING`, the panel is **not**
   certified complete, and no substitute control is fabricated.

---

## 16. Duplicates, same codon, same residue

1. **Exact duplicates** (identical `spdi_canonical`) collapse to one record (§5.5).
2. **Same codon**: at most one selected member per `(transcript_pin, codon_index)`.
3. **Same residue**: at most one selected member per `residue_index`; the R611Q anchor
   pre-occupies its residue, so no other substitution there is selectable (`X3`).
4. **Collision resolution** is by draw order (§17.2) — never by which variant has the more
   interesting or stronger reported result. Both rules are hereditary and are used as sound pruning
   predicates in §17.5.
5. **Region spread** (`region_id`) is a *reported diversity metric only* — never a constraint —
   because protein-region annotation is not part of the frozen pack ontology. Absent ⇒ report
   `UNKNOWN`, never infer.

---

## 17. Deterministic selection algorithm

### 17.1 Hard inputs and fail-closed preconditions

| Id | Precondition (all fail closed; the run emits no panel) |
|---|---|
| V1 | Recomputed `atlas.protocol_doc_hash.v1` of this file equals `protocol_doc_hash` in the registration artifact |
| V2 | Recomputed `atlas.registration_content_hash.v1` of the registration artifact equals its stored `registration_content_hash` (self-verification; §20.3) |
| V3 | `selection_seed` used equals the registration artifact's `selection_seed` |
| V4 | **Pack binding**: `atlas.pack_content_hash.v1` recomputed from the live `configs/atlas/packs/tsc2/pack.yaml` equals **all three** of `pack_binding_observed_at_freeze.pack_content_hash` in the registration artifact, `pack_binding.pack_content_hash` in the locked universe, and `pack_binding.pack_content_hash` in the universe lock record. Any mismatch ⇒ `PACK_DRIFT`, terminate |
| V5 | **Universe lock**: the §4.6 lock record exists, self-verifies, and binds the live universe, raw inventory, normalization ledger and discovery-set commitment (checks `K1`–`K6`). Absence or mismatch ⇒ `UNIVERSE_LOCK_MISSING` / `UNIVERSE_LOCK_CORRUPT` / `UNIVERSE_LOCK_MISMATCH` / `UNIVERSE_LOCK_INVALID`, terminate |
| V6 | All §4.5.4 conservation checks `U1`–`U7` pass, including the §4.5.5 normalization/admission replay (`RP1`–`RP7`) |

Every verified digest (`protocol_doc_hash`, `registration_content_hash`, live
`pack_content_hash`, `lock_content_hash`, `universe_content_hash`, `raw_inventory.content_hash`,
`normalization_ledger.hash`, `discovery_set_hash`) is recorded in the run record (§18.1). A missing
or unverifiable digest is never waived.

### 17.2 Seed and draw key

* `selection_seed = "raptor-atlas-phase2-panel-v1"` — a **fixed literal**, recorded in this
  protocol and in the registration artifact at freeze time. It is derived from nothing: not from
  the universe, not from candidate identities, not from any observed result, not from a hash of
  this document. This avoids both circularity and seed-shopping.
* `draw_key(record) = lowercase_hex( sha256( utf8( selection_seed + "|" + spdi_canonical ) ) )`.
* Global order: ascending `draw_key`, then ascending `spdi_canonical`. There is no quality ranking,
  score ordering, or reviewer preference anywhere in the ordering.
* Re-seeding is prohibited; a different seed requires a version bump with a recorded reason, and
  the prior run record is retained.

### 17.3 Attempt schedule (outer: constraint level, inner: fixed size)

```text
for L in [L0, R1, R2, R3, R4, R5, R6, R7]:            # §13.2, strictest first
    level_undetermined = false
    for n in [N_target, N_target-1, ..., 5]:          # largest panel first at this level
        outcome = complete_search(n, constraints(L, n))     # over the FULL eligible universe
        if outcome == SOLUTION:            accept -> N_selected = n; stop
        if outcome == UNDETERMINED:        level_undetermined = true      # budget exhausted
        # outcome == INFEASIBLE_COMPLETE:  search space provably exhausted
    if level_undetermined:
        terminate UNDETERMINED_SEARCH_INCOMPLETE      # never relax on an uncomputed attempt
terminate INFEASIBLE_PANEL                            # only after all attempts proved complete
```

All caps are functions of `n` only. Nothing in the constraint set references `N_selected`. A level
is left only when every attempt at that level was proved infeasible (§13.2).

### 17.4 Search space: the full eligible universe (no shortlist)

* **Scope.** The search considers **every eligible record** (§8.1), grouped by `primary_stratum`.
  The v1.0.1 per-stratum "first 12 in draw order" shortlist is **removed**: a cutoff that can hide
  a feasible solution must never be able to trigger relaxation or `INFEASIBLE_PANEL`. The Phase 2
  eligible universe is small by construction (a single gene, single-missense only, after
  deduplication), so exhaustive search is tractable.
* **Resource guard.** `search_node_budget = 5000000` search-state expansions per `(L, n)` attempt is
  a pure resource guard. Exhaustion yields **`UNDETERMINED`** for that attempt and, per §13.2,
  terminates the run with `UNDETERMINED_SEARCH_INCOMPLETE`. Budget exhaustion **never** produces
  relaxation, never produces `INFEASIBLE_PANEL`, and never removes a candidate from consideration.
  The remedy is a larger budget or a better complete solver — both are re-runs of the same frozen
  rules and yield the same panel whenever a solution exists.
* **Optional optimization, gated by a proof.** A future implementation may restrict the search to a
  subset **only** if it also emits a machine-checked completeness argument showing that every
  omitted candidate is exchange-equivalent to a retained one under the full constraint set for the
  attempt in question (identical `primary_stratum`, `support_class`, lineage-group multiset, assay
  kinds, model systems, residue/codon keys, and strictly later draw order). Absent such a proof for
  a given attempt, the attempt must run over the full eligible pool. Any subset used, and its
  proof id, is recorded in the run record; an unproved subset is a protocol violation.

### 17.5 Complete deterministic search at a fixed size `n`

1. **Allocation vectors.** Enumerate `a = (a_S)` over non-empty strata with `a_S ≥ 1` (`C1`),
   `a_S ≤ min(ceil(n/2), |eligible_S|)` (`C3`), and `Σ a_S = n`. Order them by
   `(max_S a_S ascending, then lexicographic ascending with strata in Ω order)` — a declared
   preference for the most balanced spread. If no vector exists, the attempt is
   `INFEASIBLE_COMPLETE`.
2. **Depth-first assignment.** For each allocation in order, process strata in Ω order and choose
   `a_S` members from `eligible_S` (all eligible records of that stratum, ascending draw order) as
   combinations in lexicographic order over sorted indices.
3. **Sound pruning only.** Prune a partial assignment when a *hereditary* constraint is already
   violated (`C3`, `D3`, `P1`, `P3`, residue/codon collisions) or when the remaining eligible pool
   is too small to complete the allocation. Non-hereditary minimums (`C2`, `C5`, `D1`, `D2`, `D4`,
   `P2`) are checked on complete assignments only, so no solution is ever pruned away.
4. **First solution wins.** The search is exhaustive over the full eligible pool, so acceptance is
   not greedy-order dependent: the accepted set is the lexicographically first complete solution
   under the declared allocation and draw orders. An attempt that exhausts the space without a
   solution returns `INFEASIBLE_COMPLETE`; one that hits the node budget first returns
   `UNDETERMINED`.
5. **Determinism.** Identical inputs always yield an identical panel, an identical attempt log, and
   an identical audit.

### 17.6 Executor prohibitions

No manual reordering or swapping; no "better fit" substitution; no dropping a selected member after
seeing its evidence; no re-running with a different seed, universe, constraint set or unproved
candidate subset; no editing the universe or its lock record; no consultation of results, scores or
narratives during selection. Selection completes before any source is read.

---

## 18. Audit trail

### 18.1 Run record

| Item | Value |
|---|---|
| Path | `data/atlas/tsc2_phase2_panel_selection_run_<YYYY-MM-DD>.json` |
| Verified digests | `protocol_version`, `verified_protocol_doc_hash`, `verified_registration_content_hash`, `verified_live_pack_content_hash`, `verified_lock_content_hash`, `verified_universe_content_hash`, `verified_raw_inventory_hash` + `record_count`, `verified_normalization_ledger_hash` + `row_count`, `verified_discovery_set_hash` + `discovery_set_count`, `lock_protocol_version_delta` (if any) |
| Replay | `normalization_replay`: replayed row count, per-`normalization_outcome` counts, `RP1`–`RP7` all-pass attestation |
| Procedure | `selection_seed`, `search_scope: full_eligible_universe`, `search_node_budget`, any proved candidate-subset optimization with its proof id, declared constraint set, `attempt_log` (per `(L, n)`: `SOLUTION` / `INFEASIBLE_COMPLETE` / `UNDETERMINED`), applied `relaxation_step`s, `independence_status`, `terminal_outcome` |
| Result | `N_target`, `N_selected`, selected members, per-stratum coverage table, auxiliary (secondary) stratum-match table, `spec_taxonomy_coverage`, recomputed lineage groups with `lineage_confidence`, `label_function_discordant` and `stale_label_discordant` counts with the discordant `spec_stratum` × stratum cells named, `unresolved_identity_count`, `X5` access-attrition counts and distribution |
| Dispositions | The complete per-record table of §18.2 |
| Provenance | Executor identity, quoted ISO timestamp, run flags |

### 18.2 Per-record disposition table (every universe record, no omissions)

`record_id`, `universe_key`, `identity_state`, `all_matched_strata`, `primary_stratum`,
`spec_stratum` + `spec_stratum_derivation`, `support_class`, `source_group` ids, `draw_key`,
`disposition` (§8.2 exclusion code or §8.3 selection disposition), the `rule_id` that produced it,
and — for selected members — the allocation vector and stratum slot they filled. An audit that
lists only the selected panel is non-conforming.

### 18.3 No outcome-dependent replacement

After selection, a member may be removed **only** for a pre-declared structural fault:

`F1` identity later found unadmissible · `F2` source retracted · `F3` licence does not permit lawful
verification · `F4` patient-identifiable content discovered · `F5` duplicate/same-residue violation
missed at selection · `F6` universe contract breach discovered · `F7` pack drift discovered ·
`F8` universe lock record found missing, corrupt, or inconsistent with the artifacts it pins.

A removal is recorded as an amendment with its fault code, and the replacement is computed by
re-running §17.5 with that record marked ineligible — never chosen. Removal for any evidential
reason — null result, conflicting result, weak result, "uninteresting", "not novel", inconvenient
direction — is prohibited and, if attempted, invalidates the run.

### 18.4 Expected disagreement

Where an Atlas outcome contradicts a member's sampling stratum or its `spec_stratum`, the run
report records the disagreement as a finding about the *metadata* (and, honestly, about label
quality). It never triggers re-selection, re-labelling of the locked universe, or removal.

---

## 19. What selection does and does not establish

* Selection establishes **sampling**, reproducibly and auditably. Nothing else.
* No panel member carries any claim until Gates 1–8 pass, including exact-span verification and
  named human-oracle review.
* The panel is **provisional** until that review; reviewer rejection on evidence grounds is
  recorded downstream and does not rewrite the selection record.
* Honest terminal outcomes include: supported, contradicted, context-dependent, unknown, empty,
  `ABSTENTION_CONTROL_MISSING`, `RELAXED`, `UNDETERMINED_SEARCH_INCOMPLETE` and `INFEASIBLE_PANEL`.
  None of them is a failure of this protocol. `UNDETERMINED_SEARCH_INCOMPLETE` in particular says
  only "not computed yet" — it is never reported as a finding about the literature.

---

## 20. Freeze metadata, hashing and versioning

### 20.1 Why the hash lives next door

A document cannot contain its own hash. The digest of **this file** is recorded in the adjacent
registration artifact `docs/project/atlas/atlas-phase2-panel-selection-registration-v1.yaml`, which
also carries the freeze timestamp, version, seed literal, pack-binding snapshot and registrar.

### 20.2 `atlas.protocol_doc_hash.v1` (this markdown file)

Read as UTF-8, normalize by `atlas.text_norm.v1` (CRLF/CR → LF, Unicode NFC, no case-fold, no
whitespace collapse), encode UTF-8, lowercase SHA-256 hex. Canonical-LF is required because this
repository checks out with `core.autocrlf=true`; a raw-byte digest would differ per platform.

```bash
python -c "import hashlib,unicodedata,pathlib;t=pathlib.Path('docs/project/atlas/ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md').read_text(encoding='utf-8').replace('\r\n','\n').replace('\r','\n');print(hashlib.sha256(unicodedata.normalize('NFC',t).encode('utf-8')).hexdigest())"
```

### 20.3 `atlas.registration_content_hash.v1` (the registration YAML, self-verifying)

Mirrors `atlas.pack_content_hash.v1`: `yaml.safe_load` the file, strip **only** the top-level
`registration_content_hash` key, canonical-JSON serialize the remainder (`sort_keys=True`,
`separators=(",",":")`, `ensure_ascii=False`), lowercase SHA-256 hex. All timestamps in that file
are quoted strings so the payload is JSON-serializable without coercion. The executor **must**
recompute and verify this digest (precondition `V2`) and record it in the run.

```bash
python -c "import hashlib,json,yaml,pathlib;m=yaml.safe_load(pathlib.Path('docs/project/atlas/atlas-phase2-panel-selection-registration-v1.yaml').read_text(encoding='utf-8'));m.pop('registration_content_hash',None);print(hashlib.sha256(json.dumps(m,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest())"
```

### 20.4 Versioning and amendment

* Semantic versioning: **MAJOR** = changed rule semantics or outcome-affecting change after a run
  exists; **MINOR** = added constraint or clarification that cannot change an already-computed
  panel; **PATCH** = editorial, **or any correction made before the first selection run has ever
  executed** (`pre_first_run_correction: true` in the registration record), since no computed panel
  can be affected. Versions `1.0.1` and `1.0.2` are such pre-first-run corrections of `1.0.0`.
* **Every** content change to this file requires a new registration record with the new version, a
  new digest, a reason, and a timestamp. A stale digest is fail-closed for the executor (`V1`).
* A panel already selected under `vN` is never silently re-derived under `vN+1`; a re-run is a new
  run record citing the new version and the reason, with the prior run retained.
* Amendments made after any candidate-level result is known must state that fact explicitly in the
  registration record's `reason` field and set `known_candidate_level_results_at_amendment: true`.

---

## 21. Executor checklist

1. Recompute §20.2 digest of this protocol; compare with the registration artifact (`V1`). Mismatch ⇒ stop.
2. Recompute §20.3 digest of the registration artifact and compare with its own stored value (`V2`). Mismatch ⇒ stop.
3. Confirm the seed literal (`V3`). Mismatch ⇒ stop.
4. Recompute the live pack hash and compare with the registration snapshot, the universe pack binding **and** the lock record (`V4`). Mismatch ⇒ `PACK_DRIFT`, stop.
5. Load the §4.6 universe lock record, verify its self-hash and every pinned digest/count (`V5`, `K1`–`K6`). Missing, corrupt, mismatched or duplicated ⇒ stop.
6. Verify the raw inventory hash/count, ledger hash/bijection, discovery-set commitment and universe hash (`U1`–`U6`), then **replay** normalization and pack admission for every raw row (`U7`, `RP1`–`RP7`). Any disagreement ⇒ `UNIVERSE_CONTRACT_BREACH`, stop.
7. Recompute `all_matched_strata` / `primary_stratum` (§6) and lineage groups / `support_class` (§7, §14); disagreement with declared values ⇒ stop.
8. Apply eligibility (§8) over every record, then run the §17.3 schedule with the §17.5 complete search over the **full eligible universe**; relax only after a level is proved `INFEASIBLE_COMPLETE`.
9. Emit the run record with all verified digests, the replay attestation, the attempt log and the complete disposition table (§18).
10. Report every flag plainly: `independence_status`, `spec_taxonomy_coverage`, `ABSTENTION_CONTROL_MISSING`, `UNDETERMINED_SEARCH_INCOMPLETE`, `INFEASIBLE_PANEL`, `X5` attrition, `lineage_unknown_*`, `label_function_discordant`, `stale_label_discordant`, `unresolved_identity_count`.
11. Do **not** acquire, read, or reason about candidate evidence during selection.
12. Hand the provisional panel to the Gate 1–8 pipeline and the named human-oracle review.

---

## Related artifacts

* `docs/project/atlas/atlas-phase2-panel-selection-registration-v1.yaml` — freeze/registration record.
* `configs/atlas/panels/tsc2/atlas-phase2-candidate-universe-lock-v1.yaml` — pre-selection universe lock record (§4.6), created by the universe custodian before selection.
* `docs/project/atlas/ATLAS_RUNBOOK.md` — Phase 1/2 operational guide and Phase 2 stop/go gate.
* `docs/project/specs/mechanism-atlas-starter.yaml` — `panel_selection_contract` (size, spec strata; §10), unchanged by this protocol.
* `docs/project/specs/atlas-citation-resolver-v1.yaml` — identifier normalization and span binding.
* `docs/DECISIONS.md` — ADR-0014 (core/pack boundary), ADR-0015 (source roles, R611Q anchor), ADR-0016 (citation resolver, span verification).
* `docs/project/TODOS.yaml` — `atlas-phase2-panel-protocol-freeze`, `atlas-phase2-candidate-universe-lock`,
  `atlas-phase2-panel-selection-run`, `atlas-phase2-contrast-panel`.
