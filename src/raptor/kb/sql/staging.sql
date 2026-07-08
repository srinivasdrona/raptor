-- =============================================================================
-- RAPTOR KB — run-scoped staging tables (PRD-03 FR4).
-- =============================================================================
-- These are SQLite ``TEMP`` tables: connection-scoped, never part of the
-- published/main KB file, and automatically dropped if the connection is
-- closed without publishing. They exist to hold candidate rows for a
-- `run_id` outside the published tables until `KBStore.publish()` commits
-- them atomically (GP-9: staging is not the source of truth, the ledger
-- is).
--
-- GP-6: this DDL lives in a SQL resource file, not hardcoded in Python —
-- `KBStore._ensure_staging_tables()` loads and executes this file verbatim
-- on every new connection (unlike the versioned migrations in
-- `migrations/*.sql`, TEMP tables must be (re)created per-connection, so
-- this file is intentionally NOT tracked in `schema_migrations`).
-- =============================================================================

CREATE TEMP TABLE IF NOT EXISTS stg_variants (
    run_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    gene TEXT NOT NULL,
    class TEXT NOT NULL,
    hgvs_g TEXT, hgvs_c TEXT, hgvs_p TEXT,
    hgvs_c_null_reason TEXT, hgvs_p_null_reason TEXT,
    provenance TEXT NOT NULL
);

CREATE TEMP TABLE IF NOT EXISTS stg_source_refs (
    run_id TEXT NOT NULL,
    source_ref_id TEXT NOT NULL,
    source TEXT NOT NULL,
    accession TEXT,
    snapshot_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    source_file_checksum TEXT NOT NULL,
    row_locator TEXT,
    raw_value TEXT NOT NULL,
    resolver_status TEXT NOT NULL,
    provenance TEXT NOT NULL
);

CREATE TEMP TABLE IF NOT EXISTS stg_variant_source_refs (
    run_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    source_ref_id TEXT NOT NULL,
    provenance TEXT NOT NULL
);

-- evidence_added / evidence_corrected: each row creates one new
-- ledger event AND one new evidence row (paired, in seq_in_run
-- order) at publish time.
CREATE TEMP TABLE IF NOT EXISTS stg_evidence_rows (
    run_id TEXT NOT NULL,
    seq_in_run INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    event_payload TEXT NOT NULL,
    event_provenance TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    criterion TEXT NOT NULL,
    strength TEXT NOT NULL,
    direction TEXT NOT NULL,
    supporting_record TEXT,
    source_ref_id TEXT NOT NULL,
    supersedes_evidence_id INTEGER,
    row_provenance TEXT NOT NULL
);

-- Standalone ledger events with no paired projection row
-- created here (variant_observed, evidence_retracted,
-- source_superseded).
CREATE TEMP TABLE IF NOT EXISTS stg_ledger_events (
    run_id TEXT NOT NULL,
    seq_in_run INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    provenance TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TEMP TABLE IF NOT EXISTS stg_manual_queue (
    run_id TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    source_ref_id TEXT NOT NULL,
    failure_stage TEXT NOT NULL,
    error_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    attempted_coords TEXT,
    tool_error TEXT,
    config_pins TEXT NOT NULL,
    excluded_from_scorer INTEGER NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);
