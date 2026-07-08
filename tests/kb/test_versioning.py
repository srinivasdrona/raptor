"""AC4 — Versioning.

Build v1.0 -> v1.1 -> v2.0 via ledger events; replay to each
evidence_snapshots.ledger_high_watermark reconstructs the effective
evidence for that version.
"""

from __future__ import annotations

from raptor.kb.store import KBStore

VARIANT_ID = "NC_000016.10:4000000:A:G"


def _seed_variant_and_source(store, prov, run_id):
    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession="VCV_versioning", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    store.stage_variant(
        run_id, variant_id=VARIANT_ID, gene="TSC2", class_="missense", provenance=prov,
        source_ref_ids=source_ref_id,
    )
    return source_ref_id


def test_v1_0_v1_1_v2_0_replay_reconstructs_effective_evidence(store, make_provenance):
    # --- v1.0: variant observed + first evidence (PM2 moderate) ---
    run1 = "version-run-1"
    prov1 = make_provenance(run_id=run1)
    source_ref_id = _seed_variant_and_source(store, prov1, run1)
    store.stage_evidence_added(
        run1, seq_in_run=1, variant_id=VARIANT_ID, tier="tier1", criterion="PM2",
        strength="moderate", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov1, event_provenance=prov1, event_timestamp="2026-01-01T00:00:00Z",
    )
    store.publish(run1)
    (pm2_evidence_id,) = store.conn.execute(
        "SELECT evidence_id FROM evidence WHERE variant_id = ? AND criterion = 'PM2'", (VARIANT_ID,)
    ).fetchone()
    (watermark_v1_0,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    derived_v1_0, hash_v1_0 = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#v1.0", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark_v1_0, combination_rule_ref="fixture-rule-v1", provenance=prov1,
    )
    store.record_classification_version(
        variant_id=VARIANT_ID, version="v1.0", evidence_snapshot_ref=f"{VARIANT_ID}#v1.0",
        status=derived_v1_0["label"], approvals=[], timestamp="2026-01-01T00:00:00Z", provenance=prov1,
    )
    (cls_watermark_v1_0,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    # --- v1.1: add a second, independent criterion (PP3 supporting) ---
    run2 = "version-run-2"
    prov2 = make_provenance(run_id=run2)
    store.stage_evidence_added(
        run2, seq_in_run=1, variant_id=VARIANT_ID, tier="tier1", criterion="PP3",
        strength="supporting", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov2, event_provenance=prov2, event_timestamp="2026-01-02T00:00:00Z",
    )
    store.publish(run2)
    (pp3_evidence_id,) = store.conn.execute(
        "SELECT evidence_id FROM evidence WHERE variant_id = ? AND criterion = 'PP3'", (VARIANT_ID,)
    ).fetchone()
    (watermark_v1_1,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    derived_v1_1, _ = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#v1.1", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark_v1_1, combination_rule_ref="fixture-rule-v1", provenance=prov2,
    )
    store.record_classification_version(
        variant_id=VARIANT_ID, version="v1.1", evidence_snapshot_ref=f"{VARIANT_ID}#v1.1",
        status=derived_v1_1["label"], approvals=[], timestamp="2026-01-02T00:00:00Z", provenance=prov2,
    )
    (cls_watermark_v1_1,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    # --- v2.0: correct PM2 moderate -> strong (supersedes the v1.0 row) ---
    run3 = "version-run-3"
    prov3 = make_provenance(run_id=run3)
    store.stage_evidence_correction(
        run3, seq_in_run=1, prior_evidence_id=pm2_evidence_id, variant_id=VARIANT_ID,
        tier="tier1", criterion="PM2", strength="strong", direction="pathogenic",
        source_ref_id=source_ref_id, row_provenance=prov3, event_provenance=prov3,
        event_timestamp="2026-03-01T00:00:00Z",
    )
    store.publish(run3)
    (pm2_corrected_evidence_id,) = store.conn.execute(
        "SELECT evidence_id FROM evidence WHERE supersedes_evidence_id = ?", (pm2_evidence_id,)
    ).fetchone()
    (watermark_v2_0,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    derived_v2_0, _ = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#v2.0", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark_v2_0, combination_rule_ref="fixture-rule-v1", provenance=prov3,
    )
    store.record_classification_version(
        variant_id=VARIANT_ID, version="v2.0", evidence_snapshot_ref=f"{VARIANT_ID}#v2.0",
        status=derived_v2_0["label"], approvals=[{"by": "operator-1"}], timestamp="2026-03-01T00:00:00Z",
        provenance=prov3,
    )
    (cls_watermark_v2_0,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    # --- Replay each watermark and assert EXACT reconstructed evidence sets ---
    effective_v1_0 = store.effective_evidence_at(watermark_v1_0, variant_id=VARIANT_ID)
    assert [(r["criterion"], r["strength"], r["evidence_id"]) for r in effective_v1_0] == [
        ("PM2", "moderate", pm2_evidence_id),
    ]

    effective_v1_1 = store.effective_evidence_at(watermark_v1_1, variant_id=VARIANT_ID)
    assert [(r["criterion"], r["strength"], r["evidence_id"]) for r in effective_v1_1] == [
        ("PM2", "moderate", pm2_evidence_id),
        ("PP3", "supporting", pp3_evidence_id),
    ]

    effective_v2_0 = store.effective_evidence_at(watermark_v2_0, variant_id=VARIANT_ID)
    assert [(r["criterion"], r["strength"], r["evidence_id"]) for r in effective_v2_0] == [
        ("PM2", "strong", pm2_corrected_evidence_id),
        ("PP3", "supporting", pp3_evidence_id),
    ]
    # The superseded v1.0 PM2 row must NOT appear as effective at v2.0.
    assert pm2_evidence_id not in [r["evidence_id"] for r in effective_v2_0]

    # Replaying an *earlier* watermark from "the future" still reproduces
    # exactly the v1.0/v1.1 snapshots (immutable inputs -> reproducible replay).
    assert store.effective_evidence_at(watermark_v1_0, variant_id=VARIANT_ID) == effective_v1_0

    # --- FR1/AC4 (checker fix): classification versions are a ledger
    # projection, not independently authoritative — reconstruct exact
    # status AND approvals for each of v1.0 -> v1.1 -> v2.0 purely by
    # REPLAYING `classification_versioned` ledger events (never by
    # reading the `classification_versions` table directly). ---
    reconstructed_at_v1_0 = store.classification_versions_at(cls_watermark_v1_0, variant_id=VARIANT_ID)
    assert [(r["version"], r["status"], r["approvals"]) for r in reconstructed_at_v1_0] == [
        ("v1.0", derived_v1_0["label"], []),
    ]

    reconstructed_at_v1_1 = store.classification_versions_at(cls_watermark_v1_1, variant_id=VARIANT_ID)
    assert [(r["version"], r["status"], r["approvals"]) for r in reconstructed_at_v1_1] == [
        ("v1.0", derived_v1_0["label"], []),
        ("v1.1", derived_v1_1["label"], []),
    ]

    reconstructed_at_v2_0 = store.classification_versions_at(cls_watermark_v2_0, variant_id=VARIANT_ID)
    assert [(r["version"], r["status"], r["approvals"]) for r in reconstructed_at_v2_0] == [
        ("v1.0", derived_v1_0["label"], []),
        ("v1.1", derived_v1_1["label"], []),
        ("v2.0", derived_v2_0["label"], [{"by": "operator-1"}]),
    ]
    # Replaying from "the future" (a later watermark) still reproduces the
    # exact same earlier reconstruction (immutable ledger -> reproducible replay).
    assert store.classification_versions_at(cls_watermark_v1_0, variant_id=VARIANT_ID) == reconstructed_at_v1_0

    # Sanity: three distinct classification_versions rows exist, each FK'd
    # to its own evidence_snapshot.
    rows = store.conn.execute(
        "SELECT version, evidence_snapshot_ref, status FROM classification_versions "
        "WHERE variant_id = ? ORDER BY version",
        (VARIANT_ID,),
    ).fetchall()
    assert [r["version"] for r in rows] == ["v1.0", "v1.1", "v2.0"]
    assert [r["evidence_snapshot_ref"] for r in rows] == [
        f"{VARIANT_ID}#v1.0", f"{VARIANT_ID}#v1.1", f"{VARIANT_ID}#v2.0",
    ]
