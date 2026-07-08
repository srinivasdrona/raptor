# PRD-03 — KB Schema & Provenance Ledger

> **Status:** Draft · **Owner:** @sdrona_microsoft · **Phase:** 0 (STRATEGY §7) · **Last updated:** 2026-07-08
>
> **Format:** standard lean PRD; acceptance criteria feed the build-loop gates (OPERATING_MODEL §4)
> and the eval mapping (EVAL_PLAN §3.4). One feature per PRD.
>
> **Links:** ARCHITECTURE §8 (provenance/ledger, event-sourcing, run-scoped staging, atomic publish) ·
> GP-5 (provenance first-class), GP-6 (config-as-truth), GP-9 (grounded execution) · RISK_REGISTER
> R-C2/R-A11/H4/H5 · PRD-01 & PRD-02 (writers/readers).

## 1. Context / problem

PRD-02 (normalized variants + manual queue) and PRD-01 (criterion-level evidence) both need a
persistent, **auditable, versioned** store. Without a schema that *enforces* grounding and
immutability, the system drifts into unbacked greens (H4), silent placeholders (H5), and
un-reproducible state (R-C2/R-A11). This feature is the **GP-5/GP-9 substrate** — the one place the
"no artifact, no action" rule is enforced *mechanically* by schema constraints, not convention.

**v1 scope:** schema + append-only ledger for **TSC2 Tier-1/2** (variants, criterion-level evidence,
provenance, manual queue, versioned classifications). Tier-3 and cross-linkage are **extensibility
hooks only** (FR8), not built here.

## 2. Goal & non-goals

**Goal:** define and implement the SQLite **KB schema + an append-only provenance ledger** that stores
normalized variants, criterion-level evidence (each with a resolvable `source_ref` + provenance),
versioned per-variant evidence history, and the manual-review queue — supporting **run-scoped
staging, atomic publish, and reproducible recompute** (ARCHITECTURE §8).

**Non-goals (explicit):**
- Scoring or normalization *logic* (PRD-01 / PRD-02 — writers into this schema).
- Tier-3 evidence tables and cross-linkage (extensible hook only, FR8).
- Any review UI; the benchmark store (that lives with EVAL).

## 3. Users & need

| User | Need this serves |
|---|---|
| PRD-02 | Write normalized `variants` + `manual_queue` rows with enforced provenance. |
| PRD-01 | Write criterion-level `evidence` rows; read `variants`. |
| EVAL harness | Read evidence/classifications to compute metrics against the frozen benchmark. |
| Auditor / human | Reconstruct the full evidence + provenance chain for any variant/version (defensibility). |

## 4. Functional requirements

- **FR1 — Ledger is the source of truth.** An append-only **`ledger`** of typed events is authoritative; `evidence`, `classification_versions`, etc. are **projections** derived by replaying events. Event types: `variant_observed`, `evidence_added`, `evidence_corrected`, `evidence_retracted`, `source_superseded`, `classification_versioned` — each with `target_id`, `run_id`, provenance, and a monotonic `ledger_seq`.
- **FR2 — Grounding as first-class rows (GP-9):** a `source_ref` is a **`source_refs` row** (`{source, accession/VariationID, snapshot_id, snapshot_date, source_file_checksum, row_locator, raw_value, resolver_status}`), FK-referenced by evidence/observations. A variant may have **many** source refs (PRD-02 §2.1): a `variant_source_refs (variant_id, source_ref_id)` link table keeps every source. A groundable row without a **valid FK to a complete `source_refs` row** fails.
- **FR3 — Immutability of published history:** the **history set** — `ledger`, `variants`, `source_refs`, `variant_source_refs`, `evidence`, `evidence_snapshots`, `classification_versions`, `knowledge_assertions` — is append-only; `UPDATE`/`DELETE` is blocked by triggers on **every** one. `evidence_kinds` is a **reference** table changed only by versioned migration (no runtime writes). `manual_queue` is the **only operational** table (mutable `status` for resolution) and sits *outside* the history boundary; its resolutions are also logged as ledger events. Corrections/retractions to history are **new ledger events** targeting a prior id; nothing in the history set is edited in place.
- **FR4 — Run-scoped staging + atomic publish (R-C2):** writers write to a **per-run staging area outside the published tables** (attached staging DB or `stg_*` tables); a single `BEGIN IMMEDIATE` publish `INSERT…SELECT`s validated rows into the immutable published tables. A failed run discards staging; the **published-state hash** (over published tables, post-checkpoint) is unchanged.
- **FR5 — Evidence snapshots + versioning:** an **`evidence_snapshots`** row = `{snapshot_id, variant_id, ledger_high_watermark, input_hash, combination_rule_ref}` defines the *effective* evidence at a ledger position. `classification_versions.evidence_snapshot_ref` is an **FK** to it; `v1.0→v1.1→v2.0` is reconstructable by replaying the ledger to each watermark.
- **FR6 — Criterion-level evidence contract (matches PRD-01):** `evidence` rows carry `{variant_id FK, tier, criterion, strength, direction, supporting_record/span, source_ref_id FK, run_id, provenance}`, with an **effective-state uniqueness invariant** — one effective evidence row per `(variant_id, criterion)` unless superseded by a ledger event — preventing double-counting (PRD-01 FR4).
- **FR7 — Provenance completeness (GP-5):** every row/event carries the ARCHITECTURE §8 field set `{tool_version, prompt_version?, model?, source, source_snapshot_version, env_versions, originating_run, timestamp}`; a row missing a required field fails (NOT NULL/CHECK).
- **FR8 — Config-driven schema + migrations (GP-6):** declarative schema; **versioned `.sql` migrations** applied by a tiny runner that also enforces the runtime contract (§5.1); no ad-hoc DDL.
- **FR9 — Extensibility via a generic contract:** Tier-3 evidence fits the generic `evidence` shape (new `tier`/`criterion` values validated against an **`evidence_kinds` registry table**, not code); **cross-linkage** (not variant-scoped) goes to a separate `knowledge_assertions` stub table. New rows that fit these contracts need **no migration** — a genuinely new *shape* still does.

### 4.1 Schema contract (spec-level)

All tables are SQLite **`STRICT`**; the migration runner asserts `PRAGMA foreign_keys=ON`.

| Table | Class | Key / constraints |
|---|---|---|
| `variants` | history | PK `variant_id` (SPDI text); NOT NULL gene, class |
| `source_refs` | history | PK `source_ref_id`; NOT NULL source, snapshot_id, checksum, raw_value; UNIQUE(source, accession, snapshot_id, row_locator) |
| `variant_source_refs` | history | PK (`variant_id`,`source_ref_id`); FKs → variants, source_refs |
| `evidence` | history | PK `evidence_id`; FK variant_id, source_ref_id; CHECK (tier,criterion) ∈ `evidence_kinds`; NOT NULL strength, direction, run_id, provenance |
| `ledger` | history (SoT) | PK `ledger_seq` (autoinc); NOT NULL event_type (CHECK enum), target_id, run_id, provenance, timestamp |
| `evidence_snapshots` | history | PK `snapshot_id`; FK variant_id; NOT NULL ledger_high_watermark, input_hash, combination_rule_ref |
| `classification_versions` | history | PK (`variant_id`,`version`); FK `evidence_snapshot_ref`; NOT NULL status, approvals, timestamp |
| `knowledge_assertions` | history | PK `assertion_id`; FK source_ref_id (NOT NULL); NOT NULL assertion_type, subject, object, status (default `hypothesis`), provenance *(cross-linkage stub — GP-1/GP-2; not variant-scoped)* |
| `manual_queue` | **operational** | PK `mq_id`; FK source_ref_id; NOT NULL failure_stage, error_code, reason, run_id, config_pins; CHECK `excluded_from_scorer`=1; mutable `status` only |
| `evidence_kinds` | **reference** | registry of valid (tier, criterion) + strength vocab; changed **only by versioned migration** |

**History** tables are append-only (UPDATE/DELETE blocked by triggers, FR3); **operational** =
`manual_queue` (mutable status; resolutions also logged as ledger events); **reference** =
`evidence_kinds` (migration-managed).

## 5. Non-functional requirements

- **Single-writer (ARCHITECTURE §4 / R-C2):** the Queen is the sole writer; concurrency is not a v1 concern.
- **Integrity:** immutability + atomic publish are enforced/observable (triggers or app+test), not just documented.
- **Reproducibility (R-A11):** derived classifications recompute **identically** from the immutable inputs.
- **Performance:** thousands of variants × criteria is trivial for SQLite; no tuning needed at this scale.
- **Provenance completeness (GP-5)** and **config-driven (GP-6).**

### 5.1 SQLite runtime contract

`journal_mode=WAL`, `synchronous=FULL` for the publish transaction, `foreign_keys=ON` per connection;
publish in a single `BEGIN IMMEDIATE` transaction; **checkpoint before** computing the published-state
hash. Immutability via `BEFORE UPDATE/DELETE` triggers (`RAISE(ABORT,…)`) on published tables. The
migration runner **verifies** all of these at startup — they are correctness settings, not tuning.

## 6. Acceptance criteria *(→ EVAL_PLAN §3.4; become OPERATING_MODEL gates)*

- **AC1 — Grounding constraint (GP-9):** inserting a groundable row (`variants`/`evidence`/`manual_queue`) **without a valid FK to a complete `source_refs` row fails** — both a NULL ref and a malformed/incomplete `source_refs` row are rejected; test proves both.
- **AC2 — Immutability (H4/H5):** `UPDATE`/`DELETE` on **every history table** (`ledger`, `variants`, `source_refs`, `variant_source_refs`, `evidence`, `evidence_snapshots`, `classification_versions`, `knowledge_assertions`) fails; a correction/retraction is representable **only** as a new ledger event; test proves both **per table**. (`manual_queue` is operational; `evidence_kinds` changes only via migration.)
- **AC3 — Atomic publish / rollback (R-C2):** with staging **outside** the published tables, a run that fails mid-publish leaves the **published-state hash unchanged** (over published tables, post-checkpoint); a successful run publishes in one `BEGIN IMMEDIATE` transaction; test simulates a failed run and asserts the hash equals last-good.
- **AC4 — Versioning:** replaying the ledger to each `evidence_snapshots.ledger_high_watermark` reconstructs `v1.0→v1.1→v2.0` effective evidence + approvals; test builds the sequence and reconstructs each.
- **AC5 — Storage determinism (R-A11):** given a fixed snapshot + a pinned `combination_rule_ref` + canonically-serialized inputs, the stored derived output is **identical** on recompute — using a **tiny local fixture rule** (the *real* rule's correctness is PRD-01's, not this PRD's).
- **AC6 — Provenance completeness (GP-5):** a row missing any required provenance field **fails**; test proves rejection.
- **AC7 — Extensibility (bounded):** inserting a Tier-3 `evidence` row (new `evidence_kinds` entry) **and** a `knowledge_assertions` cross-linkage stub row needs **no migration**; a genuinely new *shape* still does; test inserts both against the v1 schema.
- **AC8 — Manual-queue integrity:** `manual_queue` rows conform to PRD-02 FR6 (incl. `source_ref`, `run_id`, `error_code`, `failure_stage`, `config_pins`, `excluded_from_scorer=1`); a scorer-includable manual row fails.
- **AC9 — Config + no trace-cribbing:** migrations schema-validate and the runtime contract (§5.1) is verified (GP-6); the module reads no benchmark/label/oracle file (G2 audit — manual until lint).

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| SQLite (Python stdlib `sqlite3`) | available | No |
| Migration runner (plain versioned SQL + tiny runner) | to build | internal |

> **Fully buildable now** — no external data, no network, no oracle. This is the **best first build**:
> PRD-01 and PRD-02 depend on it, and it validates entirely against local tests/fixtures.

## 8. Risks (see RISK_REGISTER for mitigations)

R-C2 (state corruption → staging + atomic publish, FR4) · R-A11 (reproducibility → immutable inputs,
FR3/AC5) · **H4** (unbacked green → `source_ref` constraint, FR2/AC1) · **H5** (silent placeholder →
provenance-complete constraint, FR6/AC6). **GP-9 note:** grounding is enforced by the *schema*, so a
downstream module cannot write an ungrounded record even by mistake.

## 9. Open questions

- **Combination-rule ownership:** the real posterior/combination rule lives in PRD-01; PRD-03 stores it opaque + references it by `combination_rule_ref`. Confirm the ref contract.
- **Staging mechanism:** attached per-run DB vs `stg_*` tables — both satisfy FR4/AC3; decide at build.
- **Immutability enforcement:** triggers (default, hard guarantee) vs app-layer + tests.
- **`knowledge_assertions`** cross-linkage stub: minimal columns now, full shape when Tier-3/cross-linkage is designed (GP-7).

## 10. Known limitations (signed-off scope)

- **`published_state_hash()` is scoped to AC3 (same-DB atomic-publish detection)** — ADR-0006. It also
  provides a *best-effort* cross-DB canonical logical fingerprint (surrogate-, order-, type-invariant,
  ledger-sequence-sensitive), fully test-covered (Gemini property tests + determinism tests, 100
  green), with **one deferred gap**: JSON TEXT columns other than `ledger.payload` (`provenance`,
  `approvals`, `config_pins`, `strength_vocab`) are hashed raw, so two *different* DBs whose JSON
  differs only by key order can hash differently. **AC3 is unaffected** (same-DB, values unchanged).
  Full JSON canonicalization is deferred to R-A11 reproducibility work (a `_JSON_COLUMNS` registry).
