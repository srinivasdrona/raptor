"""AC1 — Grounding constraint (GP-9).

Inserting a groundable row (`variants` via `variant_source_refs`, `evidence`,
`manual_queue`) without a valid FK to a *complete* `source_refs` row fails:
both a NULL ref and a reference to an incomplete/nonexistent source_refs row
are rejected. A malformed (incomplete) `source_refs` row itself can never be
created in the first place, so nothing can ever point at one.
"""

from __future__ import annotations

import sqlite3

import pytest

from raptor.kb.store import KBStore, PublishError


def _valid_variant(store, prov, variant_id="NC_000016.10:2200000:A:G"):
    store.conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES (?, ?, ?, ?)",
        (variant_id, "TSC2", "missense", prov),
    )
    return variant_id


def _valid_source_ref(store, prov, row_locator="row-42"):
    source_ref_id = KBStore.compute_source_ref_id("ClinVar", "VCV000011111", "snap-1", row_locator)
    store.conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, 'ClinVar', 'VCV000011111', 'snap-1', '2026-01-01', 'chk123', ?, 'raw', 'resolved', ?)
        """,
        (source_ref_id, row_locator, prov),
    )
    return source_ref_id


class TestMalformedSourceRefsRejected:
    """A source_refs row missing a required field can never be created."""

    @pytest.mark.parametrize(
        "missing_field",
        ["source", "snapshot_id", "snapshot_date", "source_file_checksum", "raw_value"],
    )
    def test_missing_required_field_rejected(self, store, make_provenance, missing_field):
        prov = make_provenance()
        fields = {
            "source_ref_id": "abc123",
            "source": "ClinVar",
            "accession": "VCV1",
            "snapshot_id": "snap-1",
            "snapshot_date": "2026-01-01",
            "source_file_checksum": "chk",
            "row_locator": "row-1",
            "raw_value": "raw",
            "resolver_status": "resolved",
            "provenance": prov,
        }
        fields[missing_field] = None
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                """
                INSERT INTO source_refs
                    (source_ref_id, source, accession, snapshot_id, snapshot_date,
                     source_file_checksum, row_locator, raw_value, resolver_status, provenance)
                VALUES (:source_ref_id, :source, :accession, :snapshot_id, :snapshot_date,
                        :source_file_checksum, :row_locator, :raw_value, :resolver_status, :provenance)
                """,
                fields,
            )
        # Prove it never landed — nothing can ever reference this "row".
        (count,) = store.conn.execute(
            "SELECT COUNT(*) FROM source_refs WHERE source_ref_id = 'abc123'"
        ).fetchone()
        assert count == 0


class TestEvidenceGrounding:
    def test_null_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
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
                    (ledger_seq, variant_id, tier, criterion, strength, direction,
                     source_ref_id, run_id, provenance)
                VALUES (?, ?, 'tier1', 'PM2', 'moderate', 'pathogenic', NULL, 'run-1', ?)
                """,
                (ledger_seq, variant_id, prov),
            )

    def test_nonexistent_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
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
                    (ledger_seq, variant_id, tier, criterion, strength, direction,
                     source_ref_id, run_id, provenance)
                VALUES (?, ?, 'tier1', 'PM2', 'moderate', 'pathogenic', 'no-such-source-ref', 'run-1', ?)
                """,
                (ledger_seq, variant_id, prov),
            )

    def test_valid_source_ref_succeeds(self, store, make_provenance):
        """Positive control: proves the rejections above are due to grounding, not unrelated errors."""
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
        source_ref_id = _valid_source_ref(store, prov)
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
            VALUES (?, ?, 'tier1', 'PM2', 'moderate', 'pathogenic', ?, 'run-1', ?)
            """,
            (ledger_seq, variant_id, source_ref_id, prov),
        )
        (count,) = store.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()
        assert count == 1


class TestManualQueueGrounding:
    def test_null_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                """
                INSERT INTO manual_queue
                    (raw_input, source_ref_id, failure_stage, error_code, reason,
                     config_pins, run_id, excluded_from_scorer, provenance, created_at)
                VALUES ('raw', NULL, 'normalize', 'E001', 'unresolvable transcript',
                        '{}', 'run-1', 1, ?, '2026-01-01T00:00:00Z')
                """,
                (prov,),
            )

    def test_nonexistent_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                """
                INSERT INTO manual_queue
                    (raw_input, source_ref_id, failure_stage, error_code, reason,
                     config_pins, run_id, excluded_from_scorer, provenance, created_at)
                VALUES ('raw', 'no-such-source-ref', 'normalize', 'E001', 'unresolvable transcript',
                        '{}', 'run-1', 1, ?, '2026-01-01T00:00:00Z')
                """,
                (prov,),
            )

    def test_valid_source_ref_succeeds(self, store, make_provenance):
        prov = make_provenance()
        source_ref_id = _valid_source_ref(store, prov)
        store.conn.execute(
            """
            INSERT INTO manual_queue
                (raw_input, source_ref_id, failure_stage, error_code, reason,
                 config_pins, run_id, excluded_from_scorer, provenance, created_at)
            VALUES ('raw', ?, 'normalize', 'E001', 'unresolvable transcript',
                    '{}', 'run-1', 1, ?, '2026-01-01T00:00:00Z')
            """,
            (source_ref_id, prov),
        )
        (count,) = store.conn.execute("SELECT COUNT(*) FROM manual_queue").fetchone()
        assert count == 1


class TestVariantGroundingViaLinkTable:
    """A `variants` row grounds through `variant_source_refs` (PRD-02 §2.1: many
    source rows -> one variant_id); the link table's FK is where NULL/absent
    source_ref grounding is enforced for variants."""

    def test_null_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance) VALUES (?, NULL, ?)",
                (variant_id, prov),
            )

    def test_nonexistent_source_ref_fk_rejected(self, store, make_provenance):
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance) VALUES (?, 'no-such-ref', ?)",
                (variant_id, prov),
            )

    def test_valid_source_ref_succeeds(self, store, make_provenance):
        prov = make_provenance()
        variant_id = _valid_variant(store, prov)
        source_ref_id = _valid_source_ref(store, prov)
        store.conn.execute(
            "INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance) VALUES (?, ?, ?)",
            (variant_id, source_ref_id, prov),
        )
        (count,) = store.conn.execute("SELECT COUNT(*) FROM variant_source_refs").fetchone()
        assert count == 1


class TestAC1UngroundedVariantRejected:
    """AC1-VARIANT-GROUNDING-GAP (checker fix): a *published* `variants` row
    must have >=1 linked, complete `source_refs` row. `variants` has no FK
    column of its own (PRD-02 §2.1: many source rows -> one variant_id via
    `variant_source_refs`), so grounding is enforced two ways: (1) the
    sanctioned staging API (`KBStore.stage_variant`) requires >=1
    `source_ref_ids` to even construct a staged variant, and (2)
    `KBStore.publish()` independently re-verifies the invariant against the
    published `variant_source_refs` table before committing, since staging
    (TEMP) tables carry no FK enforcement of their own.
    """

    def test_stage_variant_without_any_source_ref_is_rejected(self, store, make_provenance):
        """The sanctioned staging API itself refuses to construct an
        ungrounded variant — `source_ref_ids` is a required argument."""
        prov = make_provenance()
        with pytest.raises(TypeError):
            store.stage_variant(  # missing required `source_ref_ids`
                "run-ac1-missing-arg", variant_id="NC_000016.10:2400000:A:G",
                gene="TSC2", class_="missense", provenance=prov,
            )

    def test_stage_variant_with_empty_source_ref_ids_is_rejected(self, store, make_provenance):
        prov = make_provenance()
        with pytest.raises(ValueError):
            store.stage_variant(
                "run-ac1-empty-list", variant_id="NC_000016.10:2410000:A:G",
                gene="TSC2", class_="missense", provenance=prov, source_ref_ids=[],
            )
        (count,) = store.conn.execute(
            "SELECT COUNT(*) FROM temp.stg_variants WHERE run_id = 'run-ac1-empty-list'"
        ).fetchone()
        assert count == 0

    def test_publish_rejects_a_variant_staged_with_zero_linked_source_refs(self, store, make_provenance):
        """Even bypassing the sanctioned stage_variant() API (by writing
        straight into the TEMP staging table, which has no FK of its own),
        publish() itself must refuse to let an ungrounded variant become
        part of the published/ledger state."""
        run_id = "run-ac1-publish-ungrounded"
        prov = make_provenance(run_id=run_id)
        variant_id = "NC_000016.10:2420000:A:G"
        store.conn.execute(
            """
            INSERT INTO temp.stg_variants
                (run_id, variant_id, gene, class, hgvs_g, hgvs_c, hgvs_p,
                 hgvs_c_null_reason, hgvs_p_null_reason, provenance)
            VALUES (?, ?, 'TSC2', 'missense', NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (run_id, variant_id, prov),
        )
        with pytest.raises(PublishError):
            store.publish(run_id)

        # It never landed in the published table.
        (count,) = store.conn.execute(
            "SELECT COUNT(*) FROM variants WHERE variant_id = ?", (variant_id,)
        ).fetchone()
        assert count == 0
        # And the failed run's staging was discarded (FR4), not left dangling.
        (staged,) = store.conn.execute(
            "SELECT COUNT(*) FROM temp.stg_variants WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert staged == 0

    def test_stage_variant_with_valid_source_ref_publishes_and_is_grounded(self, store, make_provenance):
        """Positive control: the normal, sanctioned path publishes cleanly
        and really does create the variant_source_refs link."""
        run_id = "run-ac1-grounded-ok"
        prov = make_provenance(run_id=run_id)
        variant_id = "NC_000016.10:2430000:A:G"
        source_ref_id = store.stage_source_ref(
            run_id, source="ClinVar", accession="VCV_ac1_ok", snapshot_id="snap-1",
            snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
        )
        store.stage_variant(
            run_id, variant_id=variant_id, gene="TSC2", class_="missense", provenance=prov,
            source_ref_ids=source_ref_id,
        )
        store.publish(run_id)

        (count,) = store.conn.execute(
            "SELECT COUNT(*) FROM variants WHERE variant_id = ?", (variant_id,)
        ).fetchone()
        assert count == 1
        (link_count,) = store.conn.execute(
            "SELECT COUNT(*) FROM variant_source_refs WHERE variant_id = ? AND source_ref_id = ?",
            (variant_id, source_ref_id),
        ).fetchone()
        assert link_count == 1
