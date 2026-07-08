"""AC7 — Extensibility (bounded).

Inserting a Tier-3 `evidence` row (new `evidence_kinds` entry) and a
`knowledge_assertions` cross-linkage stub row needs NO migration against
the v1 schema; a genuinely new *shape* still does.
"""

from __future__ import annotations

import sqlite3

import pytest

from raptor.kb.schema import migrate
from raptor.kb.store import KBStore


def test_new_tier3_evidence_kind_and_evidence_row_need_no_migration(store, make_provenance):
    applied_before = {
        row[0] for row in store.conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    assert applied_before == {"0001_initial_schema"}

    prov = make_provenance()
    variant_id = "NC_000016.10:6000000:A:G"
    store.conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES (?, 'TSC2', 'missense', ?)",
        (variant_id, prov),
    )
    source_ref_id = KBStore.compute_source_ref_id("PMC", "PMC1234567", "snap-lit-1", "span-1")
    store.conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, 'PMC', 'PMC1234567', 'snap-lit-1', '2026-01-01', 'chk', 'span-1',
                'functional assay showed reduced protein stability', 'resolved', ?)
        """,
        (source_ref_id, prov),
    )

    # 1) Register a brand-new Tier-3 (tier, criterion) — a plain INSERT, no DDL.
    store.conn.execute(
        """
        INSERT INTO evidence_kinds (tier, criterion, direction, strength_vocab, description)
        VALUES ('tier3', 'PS3', 'pathogenic', '["strong","moderate","supporting"]',
                'Well-established functional study shows a deleterious effect')
        """
    )

    # 2) Insert an evidence row using that brand-new kind — fits the generic shape.
    cur = store.conn.execute(
        "INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) "
        "VALUES ('variant_observed', ?, 'run-1', '{}', ?, '2026-01-01T00:00:00Z')",
        (variant_id, prov),
    )
    ledger_seq = cur.lastrowid
    store.conn.execute(
        """
        INSERT INTO evidence
            (ledger_seq, variant_id, tier, criterion, strength, direction,
             supporting_record, source_ref_id, run_id, provenance)
        VALUES (?, ?, 'tier3', 'PS3', 'strong', 'pathogenic', 'functional assay span', ?, 'run-1', ?)
        """,
        (ledger_seq, variant_id, source_ref_id, prov),
    )
    (tier3_count,) = store.conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE tier = 'tier3' AND criterion = 'PS3'"
    ).fetchone()
    assert tier3_count == 1

    # 3) knowledge_assertions cross-linkage stub row — also fits the existing shape.
    store.conn.execute(
        """
        INSERT INTO knowledge_assertions (source_ref_id, assertion_type, subject, object, provenance)
        VALUES (?, 'gene-disease-link', 'TSC2', 'TSC', ?)
        """,
        (source_ref_id, prov),
    )
    (assertion_count,) = store.conn.execute(
        "SELECT COUNT(*) FROM knowledge_assertions WHERE subject = 'TSC2' AND object = 'TSC'"
    ).fetchone()
    assert assertion_count == 1

    # 4) No migration was applied to accomplish any of the above.
    applied_after = {
        row[0] for row in store.conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    assert applied_after == applied_before == {"0001_initial_schema"}

    # Re-running the migration runner is still a no-op (idempotent, confirms
    # nothing new needed to be applied).
    newly_applied = migrate(store.conn)
    assert newly_applied == []


def test_evidence_kind_not_in_registry_is_rejected(store, make_provenance):
    """CHECK-via-FK: an (tier, criterion) pair absent from evidence_kinds is rejected."""
    prov = make_provenance()
    variant_id = "NC_000016.10:6100000:A:G"
    store.conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES (?, 'TSC2', 'missense', ?)",
        (variant_id, prov),
    )
    source_ref_id = KBStore.compute_source_ref_id("ClinVar", "VCV_ext", "snap-1", "row-1")
    store.conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, 'ClinVar', 'VCV_ext', 'snap-1', '2026-01-01', 'chk', 'row-1', 'raw', 'resolved', ?)
        """,
        (source_ref_id, prov),
    )
    cur = store.conn.execute(
        "INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) "
        "VALUES ('variant_observed', ?, 'run-1', '{}', ?, '2026-01-01T00:00:00Z')",
        (variant_id, prov),
    )
    ledger_seq = cur.lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO evidence
                (ledger_seq, variant_id, tier, criterion, strength, direction, source_ref_id, run_id, provenance)
            VALUES (?, ?, 'tier9', 'MADE_UP_CRITERION', 'strong', 'pathogenic', ?, 'run-1', ?)
            """,
            (ledger_seq, variant_id, source_ref_id, prov),
        )


def test_genuinely_new_shape_requires_migration_not_insert(store):
    """Contrast case: a column that doesn't exist cannot be conjured by INSERT alone."""
    with pytest.raises(sqlite3.OperationalError):
        store.conn.execute(
            "INSERT INTO evidence_kinds (tier, criterion, direction, strength_vocab, brand_new_column) "
            "VALUES ('tier3', 'XYZ', 'pathogenic', '[]', 'nope')"
        )
