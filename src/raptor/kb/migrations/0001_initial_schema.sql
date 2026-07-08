-- =============================================================================
-- RAPTOR KB schema — migration 0001: initial schema (PRD-03 v1)
-- =============================================================================
-- Source of truth: docs/prd/PRD-03-kb-schema-provenance-ledger.md §4/§4.1/§5.1.
--
-- Design notes (so the intent is auditable, not just the DDL):
--
-- * All tables are SQLite STRICT tables (§4.1). STRICT tables implicitly add a
--   NOT NULL constraint to every PRIMARY KEY column (verified against SQLite
--   3.45), so composite PKs below do not need to repeat NOT NULL for PK cols
--   (we still write NOT NULL explicitly on non-PK required columns).
--
-- * Provenance (GP-5 / FR7 / ARCHITECTURE §8): every history/operational row
--   carries a `provenance` TEXT column holding a JSON object with the
--   required field set `{tool_version, source, source_snapshot_version,
--   env_versions, originating_run, timestamp}` (all NOT NULL/required) plus
--   optional `{model, prompt_version}`. A CHECK constraint (SQLite JSON1,
--   built-in since 3.38) validates the JSON is well-formed and every
--   required key is present and non-null. A row missing a required
--   provenance field fails at INSERT time (AC6). Where a table also has its
--   own top-level `run_id` column, an additional CHECK enforces
--   provenance.originating_run == run_id so the two representations can
--   never silently disagree.
--
-- * Grounding (GP-9 / FR2 / AC1): `source_refs` is the single grounding
--   table. Every groundable row (`evidence`, `manual_queue`,
--   `variant_source_refs`) carries a NOT NULL foreign key to a *complete*
--   `source_refs` row (source_refs itself enforces NOT NULL on its own
--   required fields, so an incomplete source_refs row can never be created
--   to be pointed at in the first place). `variants` grounds via the
--   `variant_source_refs` link table (PRD-02 §2.1: many source rows -> one
--   variant_id), not a direct column, matching the §4.1 contract table.
--
-- * `source_ref_id` is a deterministic, content-addressed key (computed by
--   the application from `(source, accession, snapshot_id, row_locator)`;
--   see raptor.kb.store.compute_source_ref_id) rather than an opaque
--   autoincrement id. This lets writers stage `evidence`/`variant_source_refs`
--   rows that reference a source_ref *before* that source_ref has been
--   published in the same run, without a post-publish id-rewrite step.
--
-- * Immutability (FR3 / AC2): every table in the "history" class gets a
--   `BEFORE UPDATE` and `BEFORE DELETE` trigger that RAISE(ABORT, ...)
--   unconditionally. The history class is exactly: ledger, variants,
--   source_refs, variant_source_refs, evidence, evidence_snapshots,
--   classification_versions, knowledge_assertions. Corrections/retractions
--   are only representable as *new* ledger events (evidence_corrected /
--   evidence_retracted) targeting a prior id — see raptor.kb.ledger.
--
-- * `manual_queue` is the *operational* table (FR3): its `status` column is
--   the only mutable field. A trigger blocks UPDATE of any other column,
--   so "operational" does not mean "unrestricted mutable" — resolutions are
--   also logged as ledger events by the application layer.
--
-- * `evidence_kinds` is the *reference* table (FR3/FR9/AC7): it is the
--   generic extensibility hook — new (tier, criterion) vocabulary entries
--   (including brand-new Tier-3 kinds) are inserted as plain rows with NO
--   schema/DDL migration required. This is the mechanism, not a contradiction
--   of "reference table": no UPDATE/DELETE trigger blocks it, only INSERT is
--   the intended write path (governance over *who* adds rows is a process
--   concern, not a mechanically-enforced one, since AC7 requires it to be
--   insertable without a new migration file).
--
-- * `(tier, criterion)` validity on `evidence` is enforced via a composite
--   FOREIGN KEY to `evidence_kinds(tier, criterion)` rather than a CHECK,
--   because SQLite CHECK constraints may not contain subqueries.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Migration bookkeeping (infrastructure, not part of the KB "history" set).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT NOT NULL PRIMARY KEY,
    applied_at  TEXT NOT NULL
) STRICT;

-- -----------------------------------------------------------------------------
-- evidence_kinds — REFERENCE class (FR3/FR9): registry of valid
-- (tier, criterion) + strength vocabulary. Extended by plain INSERT
-- (extensibility hook, AC7) — no UPDATE/DELETE trigger; not part of the
-- immutable "history" set.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_kinds (
    tier            TEXT NOT NULL,
    criterion       TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('pathogenic', 'benign')),
    strength_vocab  TEXT NOT NULL CHECK (json_valid(strength_vocab) AND json_type(strength_vocab) = 'array'),
    description     TEXT,
    PRIMARY KEY (tier, criterion)
) STRICT;

-- Initial v1 Tier-1/2 vocabulary (BIAS-2015-automated ACMG criteria; PRD-01
-- §1). This is generic ACMG *rule vocabulary* (public standard criterion
-- codes), not benchmark/label/oracle data — it seeds the registry so
-- migration 0001 alone is sufficient to validate v1 evidence rows. New
-- kinds (e.g. Tier-3) are added later via plain INSERT, not a new migration
-- (FR9/AC7).
INSERT INTO evidence_kinds (tier, criterion, direction, strength_vocab, description) VALUES
    ('tier1', 'PVS1', 'pathogenic', '["very_strong","strong","moderate","supporting"]', 'Null variant in a gene where LOF is a known mechanism of disease'),
    ('tier1', 'PS1',  'pathogenic', '["strong"]',                                       'Same amino acid change as an established pathogenic variant'),
    ('tier1', 'PM2',  'pathogenic', '["moderate","supporting"]',                        'Absent/extremely low frequency in population databases'),
    ('tier1', 'PM5',  'pathogenic', '["moderate"]',                                     'Novel missense change at a residue with a known pathogenic missense change'),
    ('tier1', 'PP3',  'pathogenic', '["supporting"]',                                   'Multiple computational evidence supports a deleterious effect'),
    ('tier1', 'BA1',  'benign',     '["stand_alone"]',                                  'Allele frequency too high to be pathogenic'),
    ('tier1', 'BS1',  'benign',     '["strong"]',                                       'Allele frequency greater than expected for disorder'),
    ('tier1', 'BP4',  'benign',     '["supporting"]',                                   'Multiple computational evidence suggests no impact'),
    ('tier1', 'BP7',  'benign',     '["supporting"]',                                   'Silent variant with no predicted splice impact');

-- -----------------------------------------------------------------------------
-- source_refs — HISTORY class (FR2): grounding rows. PK is a deterministic,
-- content-addressed id assigned by the application (see store.py).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_refs (
    source_ref_id           TEXT NOT NULL PRIMARY KEY,
    source                  TEXT NOT NULL,
    accession               TEXT,
    snapshot_id             TEXT NOT NULL,
    snapshot_date           TEXT NOT NULL,
    source_file_checksum    TEXT NOT NULL,
    row_locator             TEXT,
    raw_value               TEXT NOT NULL,
    resolver_status         TEXT NOT NULL DEFAULT 'unresolved'
                                 CHECK (resolver_status IN ('resolved', 'unresolved', 'stale')),
    provenance              TEXT NOT NULL,
    UNIQUE (source, accession, snapshot_id, row_locator),
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- variants — HISTORY class. Grounds via variant_source_refs (PRD-02 §2.1:
-- many source rows -> one variant_id), not a direct source_ref_id column.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS variants (
    variant_id              TEXT NOT NULL PRIMARY KEY,  -- normalized GRCh38 genomic SPDI
    gene                     TEXT NOT NULL,
    class                    TEXT NOT NULL,              -- variant-class matrix (PRD-02 FR3)
    hgvs_g                   TEXT,
    hgvs_c                   TEXT,
    hgvs_p                   TEXT,
    hgvs_c_null_reason       TEXT,
    hgvs_p_null_reason       TEXT,
    provenance               TEXT NOT NULL,
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- variant_source_refs — HISTORY class (FR2): the grounding link table.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS variant_source_refs (
    variant_id      TEXT NOT NULL REFERENCES variants(variant_id),
    source_ref_id   TEXT NOT NULL REFERENCES source_refs(source_ref_id),
    provenance      TEXT NOT NULL,
    PRIMARY KEY (variant_id, source_ref_id),
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- ledger — HISTORY class, the single source of truth (FR1). `evidence`,
-- `classification_versions`, etc. are projections derived by replaying it.
-- `target_id` semantics: the id of the entity the event concerns — for a
-- *creation* event, the parent id (e.g. variant_id, since the child does not
-- exist yet); for a *correction/retraction* event, the id of the prior
-- entity being acted on (FR3: "new ledger event targeting a prior id").
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger (
    ledger_seq   INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL CHECK (event_type IN (
                     'variant_observed',
                     'evidence_added',
                     'evidence_corrected',
                     'evidence_retracted',
                     'source_superseded',
                     'classification_versioned'
                 )),
    target_id    TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    payload      TEXT NOT NULL CHECK (json_valid(payload)),
    provenance   TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') = run_id
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- evidence — HISTORY class (FR6): criterion-level evidence, one row per
-- ledger event that produced it (`ledger_seq` FK). `supersedes_evidence_id`
-- (nullable, self-FK) records that this row is the correction of a prior
-- effective row for the same (variant_id, criterion) — the mechanism behind
-- FR6's "one effective row per (variant_id, criterion) unless superseded".
-- Retraction never mutates or re-inserts an evidence row; it is purely a
-- `evidence_retracted` ledger event targeting this evidence_id (see
-- raptor.kb.store.effective_evidence_at for the replay logic).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id             INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    ledger_seq              INTEGER NOT NULL REFERENCES ledger(ledger_seq),
    variant_id              TEXT NOT NULL REFERENCES variants(variant_id),
    tier                    TEXT NOT NULL,
    criterion               TEXT NOT NULL,
    strength                TEXT NOT NULL CHECK (strength IN (
                                'stand_alone', 'very_strong', 'strong', 'moderate', 'supporting'
                            )),
    direction               TEXT NOT NULL CHECK (direction IN ('pathogenic', 'benign')),
    supporting_record       TEXT,
    source_ref_id           TEXT NOT NULL REFERENCES source_refs(source_ref_id),
    run_id                  TEXT NOT NULL,
    supersedes_evidence_id  INTEGER REFERENCES evidence(evidence_id),
    provenance              TEXT NOT NULL,
    FOREIGN KEY (tier, criterion) REFERENCES evidence_kinds(tier, criterion),
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') = run_id
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- evidence_snapshots — HISTORY class (FR5): the effective evidence at a
-- ledger position, for versioning/replay + storage-determinism (AC4/AC5).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_snapshots (
    snapshot_id             TEXT NOT NULL PRIMARY KEY,
    variant_id              TEXT NOT NULL REFERENCES variants(variant_id),
    ledger_high_watermark   INTEGER NOT NULL REFERENCES ledger(ledger_seq),
    input_hash              TEXT NOT NULL,
    combination_rule_ref    TEXT NOT NULL,
    provenance              TEXT NOT NULL,
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- classification_versions — HISTORY class (FR5): v1.0 -> v1.1 -> v2.0 etc.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classification_versions (
    variant_id              TEXT NOT NULL REFERENCES variants(variant_id),
    version                 TEXT NOT NULL,
    evidence_snapshot_ref   TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    status                  TEXT NOT NULL CHECK (status IN ('P', 'LP', 'VUS', 'LB', 'B')),
    approvals               TEXT NOT NULL CHECK (json_valid(approvals) AND json_type(approvals) = 'array'),
    timestamp                TEXT NOT NULL,
    provenance               TEXT NOT NULL,
    PRIMARY KEY (variant_id, version),
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- knowledge_assertions — HISTORY class (FR9): cross-linkage stub, not
-- variant-scoped. Extensibility hook (AC7): no migration needed to insert.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_assertions (
    assertion_id     INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    source_ref_id    TEXT NOT NULL REFERENCES source_refs(source_ref_id),
    assertion_type   TEXT NOT NULL,
    subject          TEXT NOT NULL,
    object           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'hypothesis' CHECK (status IN ('hypothesis', 'supported', 'refuted')),
    provenance       TEXT NOT NULL,
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
    )
) STRICT;

-- -----------------------------------------------------------------------------
-- manual_queue — OPERATIONAL class (FR3, PRD-02 FR6): the only table with a
-- mutable field (`status`); everything else is fixed at insert time (see the
-- trigger below). `excluded_from_scorer` is CHECK-pinned to 1: a
-- scorer-includable manual-queue row is impossible by construction (AC8).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS manual_queue (
    mq_id                   INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    raw_input                TEXT NOT NULL,
    source_ref_id            TEXT NOT NULL REFERENCES source_refs(source_ref_id),
    failure_stage            TEXT NOT NULL,
    error_code               TEXT NOT NULL,
    reason                   TEXT NOT NULL,
    attempted_coords         TEXT,
    tool_error                TEXT,
    config_pins               TEXT NOT NULL CHECK (json_valid(config_pins)),
    run_id                     TEXT NOT NULL,
    excluded_from_scorer       INTEGER NOT NULL DEFAULT 1 CHECK (excluded_from_scorer = 1),
    status                     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'rejected')),
    provenance                 TEXT NOT NULL,
    created_at                 TEXT NOT NULL,
    CHECK (
        json_valid(provenance)
        AND json_extract(provenance, '$.tool_version') IS NOT NULL
        AND json_extract(provenance, '$.source') IS NOT NULL
        AND json_extract(provenance, '$.source_snapshot_version') IS NOT NULL
        AND json_extract(provenance, '$.env_versions') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') IS NOT NULL
        AND json_extract(provenance, '$.timestamp') IS NOT NULL
        AND json_extract(provenance, '$.originating_run') = run_id
    )
) STRICT;

-- =============================================================================
-- Immutability triggers (FR3/AC2) — the "history" set, exactly 8 tables.
-- Every UPDATE/DELETE unconditionally RAISE(ABORT, ...). Corrections are
-- only representable as new ledger events (application-level contract,
-- enforced structurally: there is no other way to change history content).
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_ledger_no_update
BEFORE UPDATE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_no_delete
BEFORE DELETE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_variants_no_update
BEFORE UPDATE ON variants
BEGIN
    SELECT RAISE(ABORT, 'variants is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_variants_no_delete
BEFORE DELETE ON variants
BEGIN
    SELECT RAISE(ABORT, 'variants is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_refs_no_update
BEFORE UPDATE ON source_refs
BEGIN
    SELECT RAISE(ABORT, 'source_refs is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_refs_no_delete
BEFORE DELETE ON source_refs
BEGIN
    SELECT RAISE(ABORT, 'source_refs is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_variant_source_refs_no_update
BEFORE UPDATE ON variant_source_refs
BEGIN
    SELECT RAISE(ABORT, 'variant_source_refs is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_variant_source_refs_no_delete
BEFORE DELETE ON variant_source_refs
BEGIN
    SELECT RAISE(ABORT, 'variant_source_refs is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_no_update
BEFORE UPDATE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_no_delete
BEFORE DELETE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_snapshots_no_update
BEFORE UPDATE ON evidence_snapshots
BEGIN
    SELECT RAISE(ABORT, 'evidence_snapshots is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_snapshots_no_delete
BEFORE DELETE ON evidence_snapshots
BEGIN
    SELECT RAISE(ABORT, 'evidence_snapshots is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_classification_versions_no_update
BEFORE UPDATE ON classification_versions
BEGIN
    SELECT RAISE(ABORT, 'classification_versions is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_classification_versions_no_delete
BEFORE DELETE ON classification_versions
BEGIN
    SELECT RAISE(ABORT, 'classification_versions is append-only: DELETE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_knowledge_assertions_no_update
BEFORE UPDATE ON knowledge_assertions
BEGIN
    SELECT RAISE(ABORT, 'knowledge_assertions is append-only: UPDATE forbidden (history table)');
END;

CREATE TRIGGER IF NOT EXISTS trg_knowledge_assertions_no_delete
BEFORE DELETE ON knowledge_assertions
BEGIN
    SELECT RAISE(ABORT, 'knowledge_assertions is append-only: DELETE forbidden (history table)');
END;

-- -----------------------------------------------------------------------------
-- manual_queue: operational class — only `status` may change. Any UPDATE
-- that touches another column is rejected. Resolutions are still expected to
-- be logged as ledger events by the application layer (FR3).
-- -----------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_manual_queue_status_only
BEFORE UPDATE ON manual_queue
WHEN
    NEW.mq_id IS NOT OLD.mq_id
    OR NEW.raw_input IS NOT OLD.raw_input
    OR NEW.source_ref_id IS NOT OLD.source_ref_id
    OR NEW.failure_stage IS NOT OLD.failure_stage
    OR NEW.error_code IS NOT OLD.error_code
    OR NEW.reason IS NOT OLD.reason
    OR NEW.attempted_coords IS NOT OLD.attempted_coords
    OR NEW.tool_error IS NOT OLD.tool_error
    OR NEW.config_pins IS NOT OLD.config_pins
    OR NEW.run_id IS NOT OLD.run_id
    OR NEW.excluded_from_scorer IS NOT OLD.excluded_from_scorer
    OR NEW.provenance IS NOT OLD.provenance
    OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'manual_queue: only status is mutable (operational table)');
END;
