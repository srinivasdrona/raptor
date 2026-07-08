"""PRD-01 sec 10.3 — `KBStore.register_evidence_kind` (FR9/AC7 extensibility).

Migration 0001 seeds only 9 (tier, criterion) pairs; the PRD-01 scorer's
config-driven vocabulary (`configs/acmg/*.yaml`) registers its full
criterion set at `run_scorer` setup via this idempotent method. Mirrors
`tests/kb/test_extensibility.py`'s "plain INSERT, no migration" pattern,
but exercised through the sanctioned API method rather than raw SQL.
"""
from __future__ import annotations

import json


def test_register_evidence_kind_inserts_new_entry_without_migration(store):
    applied_before = {
        row[0] for row in store.conn.execute("SELECT version FROM schema_migrations").fetchall()
    }

    store.register_evidence_kind(
        tier="tier1", criterion="PP2", direction="pathogenic", strength_vocab=["supporting"]
    )

    row = store.conn.execute(
        "SELECT direction, strength_vocab, description FROM evidence_kinds "
        "WHERE tier = 'tier1' AND criterion = 'PP2'"
    ).fetchone()
    assert row is not None
    assert row["direction"] == "pathogenic"
    assert json.loads(row["strength_vocab"]) == ["supporting"]

    applied_after = {
        row[0] for row in store.conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    assert applied_after == applied_before == {"0001_initial_schema"}


def test_register_evidence_kind_is_idempotent_and_does_not_overwrite_existing(store):
    """PVS1 is already seeded by migration 0001 with a 4-entry strength_vocab
    (no `stand_alone`). Re-registering it with a DIFFERENT vocab must be a
    no-op (INSERT OR IGNORE) -- never silently narrow/widen an
    already-published reference-table row."""
    (original_vocab,) = store.conn.execute(
        "SELECT strength_vocab FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PVS1'"
    ).fetchone()
    assert json.loads(original_vocab) == ["very_strong", "strong", "moderate", "supporting"]

    store.register_evidence_kind(
        tier="tier1",
        criterion="PVS1",
        direction="pathogenic",
        strength_vocab=["stand_alone", "very_strong", "strong", "moderate", "supporting"],
    )

    (count,) = store.conn.execute(
        "SELECT COUNT(*) FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PVS1'"
    ).fetchone()
    assert count == 1  # no duplicate row

    (vocab_after,) = store.conn.execute(
        "SELECT strength_vocab FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PVS1'"
    ).fetchone()
    assert json.loads(vocab_after) == ["very_strong", "strong", "moderate", "supporting"]


def test_register_evidence_kind_new_kind_is_usable_for_evidence_rows(store, make_provenance):
    """A freshly-registered (tier, criterion) satisfies `evidence`'s FK --
    same shape/story as test_extensibility.py's raw-SQL Tier-3 case, but via
    the new sanctioned method."""
    store.register_evidence_kind(
        tier="tier1", criterion="PM1", direction="pathogenic", strength_vocab=["moderate", "supporting"]
    )

    prov = make_provenance()
    variant_id = "NC_000016.10:6200000:A:G"
    store.conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES (?, 'TSC2', 'missense', ?)",
        (variant_id, prov),
    )
    from raptor.kb.store import KBStore

    source_ref_id = KBStore.compute_source_ref_id("bias_output", variant_id, "snap-1", "row-1")
    store.conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, 'bias_output', ?, 'snap-1', '2026-01-01', 'chk', 'row-1', 'raw', 'resolved', ?)
        """,
        (source_ref_id, variant_id, prov),
    )
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
             source_ref_id, run_id, provenance)
        VALUES (?, ?, 'tier1', 'PM1', 'moderate', 'pathogenic', ?, 'run-1', ?)
        """,
        (ledger_seq, variant_id, source_ref_id, prov),
    )
    (count,) = store.conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE tier = 'tier1' AND criterion = 'PM1'"
    ).fetchone()
    assert count == 1
