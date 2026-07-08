"""AC3 — Atomic publish / rollback (R-C2).

Staging lives outside the published tables (SQLite TEMP tables). A run that
fails mid-publish leaves the published-state hash unchanged (equal to
last-good); a successful run publishes in one BEGIN IMMEDIATE transaction.
"""

from __future__ import annotations

import sqlite3

import pytest

from raptor.kb.store import KBStore, PublishError


def _stage_valid_variant_bundle(store, run_id, prov, variant_id, criterion="PM2"):
    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession=f"VCV{variant_id}", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    store.stage_variant(
        run_id, variant_id=variant_id, gene="TSC2", class_="missense", provenance=prov,
        source_ref_ids=source_ref_id,
    )
    store.stage_evidence_added(
        run_id, seq_in_run=1, variant_id=variant_id, tier="tier1", criterion=criterion,
        strength="moderate", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov, event_provenance=prov, event_timestamp="2026-01-01T00:00:00Z",
    )
    return source_ref_id


def test_successful_publish_is_atomic_and_visible(store, make_provenance):
    h_before = store.published_state_hash()

    run_id = "run-ok-1"
    prov = make_provenance(run_id=run_id)
    _stage_valid_variant_bundle(store, run_id, prov, "NC_000016.10:3000000:A:G")
    store.publish(run_id)

    h_after = store.published_state_hash()
    assert h_after != h_before

    (variant_count,) = store.conn.execute(
        "SELECT COUNT(*) FROM variants WHERE variant_id = 'NC_000016.10:3000000:A:G'"
    ).fetchone()
    assert variant_count == 1
    (evidence_count,) = store.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()
    assert evidence_count == 1
    # Staging for this run is empty after a successful publish.
    assert store.staged_counts(run_id) == {
        "stg_variants": 0, "stg_source_refs": 0, "stg_variant_source_refs": 0,
        "stg_evidence_rows": 0, "stg_ledger_events": 0, "stg_manual_queue": 0,
    }


def test_failed_run_mid_publish_leaves_hash_at_last_good(store, make_provenance):
    run_id_1 = "run-ok-2"
    prov1 = make_provenance(run_id=run_id_1)
    _stage_valid_variant_bundle(store, run_id_1, prov1, "NC_000016.10:3100000:A:G")
    store.publish(run_id_1)
    h_last_good = store.published_state_hash()

    # A second run stages an otherwise-valid bundle PLUS a manual_queue row
    # that violates the excluded_from_scorer=1 CHECK — this only fails at
    # publish time against the *published* table (staging has no such
    # constraint), simulating a failure partway through the transaction.
    run_id_2 = "run-fails-mid-publish"
    prov2 = make_provenance(run_id=run_id_2)
    source_ref_id = _stage_valid_variant_bundle(store, run_id_2, prov2, "NC_000016.10:3200000:A:G")
    store.stage_manual_queue(
        run_id_2,
        raw_input="bad-row",
        source_ref_id=source_ref_id,
        failure_stage="normalize",
        error_code="E999",
        reason="forced failure for AC3 test",
        config_pins={"pin": "v1"},
        provenance=prov2,
        created_at="2026-01-01T00:00:00Z",
        excluded_from_scorer=0,  # <-- violates CHECK(excluded_from_scorer = 1)
    )

    with pytest.raises(PublishError):
        store.publish(run_id_2)

    h_after_failure = store.published_state_hash()
    assert h_after_failure == h_last_good, "failed publish must leave published state at last-good hash"

    # None of run_id_2's rows made it in — not the variant, not the evidence.
    (variant_count,) = store.conn.execute(
        "SELECT COUNT(*) FROM variants WHERE variant_id = 'NC_000016.10:3200000:A:G'"
    ).fetchone()
    assert variant_count == 0
    (mq_count,) = store.conn.execute(
        "SELECT COUNT(*) FROM manual_queue WHERE error_code = 'E999'"
    ).fetchone()
    assert mq_count == 0

    # And FR4: the failed run's staging was discarded, not left dangling.
    assert store.staged_counts(run_id_2) == {
        "stg_variants": 0, "stg_source_refs": 0, "stg_variant_source_refs": 0,
        "stg_evidence_rows": 0, "stg_ledger_events": 0, "stg_manual_queue": 0,
    }

    # A subsequent, fully-valid run still publishes cleanly and moves the hash forward.
    run_id_3 = "run-ok-3"
    prov3 = make_provenance(run_id=run_id_3)
    _stage_valid_variant_bundle(store, run_id_3, prov3, "NC_000016.10:3300000:A:G")
    store.publish(run_id_3)
    h_final = store.published_state_hash()
    assert h_final != h_last_good


def test_published_state_hash_is_order_independent_and_content_addressed(store, make_provenance):
    """Same content published via two differently-ordered runs -> same hash."""
    variant_id = "NC_000016.10:3400000:A:G"

    run_a = "hash-order-a"
    prov_a = make_provenance(run_id=run_a)
    _stage_valid_variant_bundle(store, run_a, prov_a, variant_id)
    store.publish(run_a)
    h1 = store.published_state_hash()
    h2 = store.published_state_hash()
    assert h1 == h2  # recomputing without further writes is stable


def test_published_state_hash_is_canonical_across_insertion_order(tmp_path, make_provenance):
    """AC3 (checker fix #2 — corrected): the ledger's event SEQUENCE is
    SEMANTIC (FR1/FR5 — replay reads ``ledger_seq <= watermark ORDER BY
    ledger_seq ASC``), so a legitimate "insertion order doesn't matter"
    test must never swap the relative order of two ledger-producing runs
    (an earlier version of this test did exactly that, which happened to
    be harmless only because the two runs' events never interact — but it
    is not a safe general pattern, and `published_state_hash()` must now
    treat ledger order as significant; see
    `test_published_state_hash_detects_ledger_event_order_divergence`
    below for the corresponding negative case).

    This version keeps the ledger event SEQUENCE byte-for-byte identical
    between the two databases (both publish run_x then run_y, in that
    order) and instead varies only the PHYSICAL insertion order of two
    `manual_queue` rows — rows that carry their own AUTOINCREMENT surrogate
    id (`mq_id`) but are never replayed from the ledger (publish() inserts
    manual_queue rows directly, with no corresponding ledger event), so
    which one is published first is genuinely non-semantic. The resulting
    hashes must still be equal.
    """
    variant_x = "NC_000016.10:3500000:A:G"
    run_x = "hash-canon-run-x"
    prov_x = make_provenance(run_id=run_x)

    store_forward = KBStore(tmp_path / "order_forward.sqlite3")
    store_reverse = KBStore(tmp_path / "order_reverse.sqlite3")
    try:
        # Identical ledger-producing run, identical order, in both stores.
        source_ref_f = _stage_valid_variant_bundle(store_forward, run_x, prov_x, variant_x, criterion="PM2")
        store_forward.publish(run_x)
        source_ref_r = _stage_valid_variant_bundle(store_reverse, run_x, prov_x, variant_x, criterion="PM2")
        store_reverse.publish(run_x)

        run_p, run_q = "hash-canon-run-p", "hash-canon-run-q"
        prov_p = make_provenance(run_id=run_p)
        prov_q = make_provenance(run_id=run_q)

        def _stage_and_publish_mq(store, run_id, prov, source_ref_id, error_code):
            store.stage_manual_queue(
                run_id, raw_input="bad-row", source_ref_id=source_ref_id,
                failure_stage="normalize", error_code=error_code, reason="hash canon test",
                config_pins={"pin": "v1"}, provenance=prov, created_at="2026-01-01T00:00:00Z",
                excluded_from_scorer=1,
            )
            store.publish(run_id)

        # forward: P published before Q -> P gets the lower mq_id.
        _stage_and_publish_mq(store_forward, run_p, prov_p, source_ref_f, "E-P")
        _stage_and_publish_mq(store_forward, run_q, prov_q, source_ref_f, "E-Q")

        # reverse: same two manual_queue rows, OPPOSITE publish order ->
        # Q gets the lower mq_id this time.
        _stage_and_publish_mq(store_reverse, run_q, prov_q, source_ref_r, "E-Q")
        _stage_and_publish_mq(store_reverse, run_p, prov_p, source_ref_r, "E-P")

        # Sanity: same logical row counts...
        for tbl in ("variants", "evidence", "source_refs", "variant_source_refs", "manual_queue"):
            (n_f,) = store_forward.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            (n_r,) = store_reverse.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            assert n_f == n_r
        # ...and the ledger SEQUENCE (content, in ledger_seq order) is
        # exactly the same in both — this test varies NOTHING about ledger
        # order, only manual_queue insertion order.
        ledger_f = store_forward.conn.execute(
            "SELECT event_type, target_id, payload FROM ledger ORDER BY ledger_seq ASC"
        ).fetchall()
        ledger_r = store_reverse.conn.execute(
            "SELECT event_type, target_id, payload FROM ledger ORDER BY ledger_seq ASC"
        ).fetchall()
        assert [tuple(r) for r in ledger_f] == [tuple(r) for r in ledger_r]

        assert store_forward.published_state_hash() == store_reverse.published_state_hash()
    finally:
        store_forward.close()
        store_reverse.close()


def test_published_state_hash_detects_ledger_event_order_divergence(tmp_path, make_provenance):
    """AC3 negative case (checker-demanded): ledger order is SEMANTIC.

    Two databases hold the exact same SET of ledger events (same variant,
    same evidence, same two `classification_versioned` events for v1.0 and
    v1.1, same evidence_snapshots row) but in OPPOSITE relative order for
    the two classification events. `classification_versions_at()` replays
    strictly in ledger order, so the reconstructed version history differs
    between the two databases -- this is a real, observable divergence in
    KB state, and `published_state_hash()` must NOT hash them equal (the
    bug this test guards against: a content-rank-based ledger hash that
    discards event order and hashes these two DBs identically, hiding the
    divergence -- FALSE-EQUAL).
    """
    variant_id = "NC_000016.10:3700000:A:G"
    run_id = "hash-divergence-run-1"
    prov = make_provenance(run_id=run_id)

    store_a = KBStore(tmp_path / "order_divergence_a.sqlite3")
    store_b = KBStore(tmp_path / "order_divergence_b.sqlite3")
    try:
        # Identical common ground in both: one variant + one evidence row
        # + one evidence_snapshot, published identically.
        for store in (store_a, store_b):
            _stage_valid_variant_bundle(store, run_id, prov, variant_id, criterion="PM2")
            store.publish(run_id)
            (watermark,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
            store.build_evidence_snapshot(
                snapshot_id=f"{variant_id}#snap", variant_id=variant_id,
                ledger_high_watermark=watermark, combination_rule_ref="fixture-rule-v1", provenance=prov,
            )

        prov_v10 = make_provenance(run_id="hash-divergence-cls-v10")
        prov_v11 = make_provenance(run_id="hash-divergence-cls-v11")

        def _record_v10(store):
            store.record_classification_version(
                variant_id=variant_id, version="v1.0", evidence_snapshot_ref=f"{variant_id}#snap",
                status="VUS", approvals=[], timestamp="2026-01-01T00:00:00Z", provenance=prov_v10,
            )

        def _record_v11(store):
            store.record_classification_version(
                variant_id=variant_id, version="v1.1", evidence_snapshot_ref=f"{variant_id}#snap",
                status="LP", approvals=[{"by": "operator-1"}], timestamp="2026-01-02T00:00:00Z",
                provenance=prov_v11,
            )

        # store_a: v1.0 recorded (and thus ledger-ordered) BEFORE v1.1.
        _record_v10(store_a)
        _record_v11(store_a)

        # store_b: the exact same two events, but in the OPPOSITE ledger
        # order -- v1.1 recorded before v1.0.
        _record_v11(store_b)
        _record_v10(store_b)

        # Sanity: same logical row SET in classification_versions (same
        # content, just published in different order) and same row counts
        # everywhere.
        for tbl in ("variants", "evidence", "ledger", "evidence_snapshots", "classification_versions"):
            (n_a,) = store_a.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            (n_b,) = store_b.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            assert n_a == n_b
        rows_a = {tuple(r) for r in store_a.conn.execute(
            "SELECT variant_id, version, status FROM classification_versions"
        ).fetchall()}
        rows_b = {tuple(r) for r in store_b.conn.execute(
            "SELECT variant_id, version, status FROM classification_versions"
        ).fetchall()}
        assert rows_a == rows_b  # same SET of rows in both

        # The real, observable divergence: replaying the ledger yields a
        # DIFFERENT ordered version history in each database.
        (watermark_a,) = store_a.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
        (watermark_b,) = store_b.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
        reconstructed_a = store_a.classification_versions_at(watermark_a, variant_id=variant_id)
        reconstructed_b = store_b.classification_versions_at(watermark_b, variant_id=variant_id)
        assert [r["version"] for r in reconstructed_a] == ["v1.0", "v1.1"]
        assert [r["version"] for r in reconstructed_b] == ["v1.1", "v1.0"]
        assert reconstructed_a != reconstructed_b  # real replay-result difference

        # Therefore the published-state hash MUST differ too -- otherwise
        # the hash is masking a real semantic divergence (the bug fixed
        # here).
        assert store_a.published_state_hash() != store_b.published_state_hash()
    finally:
        store_a.close()
        store_b.close()


def test_published_state_hash_ignores_surrogate_id_remapping(tmp_path, make_provenance):
    """Class-closing regression (checker-confirmed remaining false-negative).

    `published_state_hash()` must be invariant not merely to a row's OWN
    surrogate id, but to EVERY place a surrogate id VALUE can appear:
    * a ledger `target_id` that names a surrogate (`evidence_corrected` /
      `evidence_retracted` target a prior/existing `evidence_id`), and
    * a JSON `payload` key that embeds one (`prior_evidence_id`,
      `evidence_id`), and
    * `evidence_snapshots.input_hash`'s own inputs.

    Two databases run the EXACT same logical sequence -- add two evidence
    rows, correct one (`evidence_corrected`), retract the other
    (`evidence_retracted`), then build one `evidence_snapshots` row -- in
    the same relative order, but `store_b`'s `ledger`/`evidence`
    AUTOINCREMENT counters are pre-seeded (via `sqlite_sequence`) to start
    far higher than `store_a`'s. Every `ledger_seq`/`evidence_id` surrogate
    VALUE therefore differs between the two databases even though the
    logical content and event sequence are identical.
    `published_state_hash()` must still be equal -- this assertion FAILS
    against the pre-fix code (raw `evidence_id` leaking via `target_id` and
    JSON payload keys, plus `evidence_snapshots.input_hash` itself baked
    from a raw `evidence_id`).
    """
    variant_id = "NC_000016.10:3900000:A:G"
    run_1, run_2, run_3 = "surrogate-run-1", "surrogate-run-2", "surrogate-run-3"

    def _build(store: KBStore) -> None:
        # Same run_id / provenance / snapshot_id TEXT in both stores -- the
        # only thing that differs between store_a and store_b is which
        # AUTOINCREMENT surrogate id VALUES get assigned (via the
        # sqlite_sequence pre-seed below), never the logical content.
        prov1 = make_provenance(run_id=run_1)
        source_ref_id = store.stage_source_ref(
            run_1, source="ClinVar", accession=f"VCV{variant_id}", snapshot_id="snap-1",
            snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov1,
        )
        store.stage_variant(
            run_1, variant_id=variant_id, gene="TSC2", class_="missense",
            provenance=prov1, source_ref_ids=source_ref_id,
        )
        store.stage_evidence_added(
            run_1, seq_in_run=1, variant_id=variant_id, tier="tier1", criterion="PM2",
            strength="moderate", direction="pathogenic", source_ref_id=source_ref_id,
            row_provenance=prov1, event_provenance=prov1, event_timestamp="2026-01-01T00:00:00Z",
        )
        store.stage_evidence_added(
            run_1, seq_in_run=2, variant_id=variant_id, tier="tier1", criterion="BP4",
            strength="supporting", direction="benign", source_ref_id=source_ref_id,
            row_provenance=prov1, event_provenance=prov1, event_timestamp="2026-01-01T00:00:00Z",
        )
        store.publish(run_1)

        (pm2_evidence_id,) = store.conn.execute(
            "SELECT evidence_id FROM evidence WHERE variant_id = ? AND criterion = 'PM2'", (variant_id,)
        ).fetchone()
        (bp4_evidence_id,) = store.conn.execute(
            "SELECT evidence_id FROM evidence WHERE variant_id = ? AND criterion = 'BP4'", (variant_id,)
        ).fetchone()

        # evidence_corrected: PM2 moderate -> strong (target_id + payload
        # `prior_evidence_id` both embed the raw prior evidence_id).
        prov2 = make_provenance(run_id=run_2)
        store.stage_evidence_correction(
            run_2, seq_in_run=1, prior_evidence_id=pm2_evidence_id, variant_id=variant_id,
            tier="tier1", criterion="PM2", strength="strong", direction="pathogenic",
            source_ref_id=source_ref_id, row_provenance=prov2, event_provenance=prov2,
            event_timestamp="2026-02-01T00:00:00Z",
        )
        store.publish(run_2)

        # evidence_retracted: retract BP4 (target_id + payload `evidence_id`
        # both embed the raw retracted evidence_id).
        prov3 = make_provenance(run_id=run_3)
        store.stage_evidence_retraction(
            run_3, seq_in_run=1, evidence_id=bp4_evidence_id,
            provenance=prov3, timestamp="2026-02-02T00:00:00Z", reason="retracted for test",
        )
        store.publish(run_3)

        (watermark,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
        store.build_evidence_snapshot(
            snapshot_id=f"{variant_id}#snap", variant_id=variant_id,
            ledger_high_watermark=watermark, combination_rule_ref="fixture-rule-v1", provenance=prov3,
        )

    store_a = KBStore(tmp_path / "surrogate_remap_a.sqlite3")
    store_b = KBStore(tmp_path / "surrogate_remap_b.sqlite3")
    try:
        # Force store_b's ledger/evidence AUTOINCREMENT counters to start
        # far higher than store_a's, BEFORE any row is inserted into either
        # table -- every surrogate id VALUE store_b assigns will differ
        # from store_a's even though the logical content and relative
        # event order built below are identical.
        store_b.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('ledger', 500)")
        store_b.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('evidence', 900)")

        _build(store_a)
        _build(store_b)

        # Sanity: the surrogate ids genuinely differ between the two DBs --
        # otherwise this test would (falsely) pass no matter what.
        ledger_seqs_a = {r[0] for r in store_a.conn.execute("SELECT ledger_seq FROM ledger").fetchall()}
        ledger_seqs_b = {r[0] for r in store_b.conn.execute("SELECT ledger_seq FROM ledger").fetchall()}
        assert ledger_seqs_a.isdisjoint(ledger_seqs_b)
        evidence_ids_a = {r[0] for r in store_a.conn.execute("SELECT evidence_id FROM evidence").fetchall()}
        evidence_ids_b = {r[0] for r in store_b.conn.execute("SELECT evidence_id FROM evidence").fetchall()}
        assert evidence_ids_a.isdisjoint(evidence_ids_b)
        # And the raw leak points genuinely differ too (target_id / payload).
        targets_a = [r[0] for r in store_a.conn.execute(
            "SELECT target_id FROM ledger WHERE event_type IN ('evidence_corrected', 'evidence_retracted') "
            "ORDER BY ledger_seq"
        ).fetchall()]
        targets_b = [r[0] for r in store_b.conn.execute(
            "SELECT target_id FROM ledger WHERE event_type IN ('evidence_corrected', 'evidence_retracted') "
            "ORDER BY ledger_seq"
        ).fetchall()]
        assert targets_a != targets_b
        (input_hash_a,) = store_a.conn.execute("SELECT input_hash FROM evidence_snapshots").fetchone()
        (input_hash_b,) = store_b.conn.execute("SELECT input_hash FROM evidence_snapshots").fetchone()

        # The actual class-closing assertion: identical logical state,
        # different surrogate id VALUES (own columns, target_id, JSON
        # payload keys, and evidence_snapshots.input_hash) -> EQUAL hash.
        assert store_a.published_state_hash() == store_b.published_state_hash()
        # input_hash itself must ALSO be surrogate-remap-invariant (it is
        # folded into published_state_hash as an opaque stored value, so a
        # raw-id-dependent input_hash would silently reintroduce the leak).
        assert input_hash_a == input_hash_b

        # Sanity (no over-canonicalization to false-equal): a genuine
        # logical difference must still hash differently -- add one more,
        # distinct evidence row to store_b only.
        prov_extra = make_provenance(run_id="surrogate-extra")
        source_ref_id_b = KBStore.compute_source_ref_id("ClinVar", f"VCV{variant_id}", "snap-1", None)
        store_b.stage_evidence_added(
            "surrogate-extra", seq_in_run=1, variant_id=variant_id, tier="tier1", criterion="PP3",
            strength="supporting", direction="pathogenic", source_ref_id=source_ref_id_b,
            row_provenance=prov_extra, event_provenance=prov_extra, event_timestamp="2026-03-01T00:00:00Z",
        )
        store_b.publish("surrogate-extra")
        assert store_a.published_state_hash() != store_b.published_state_hash()
    finally:
        store_a.close()
        store_b.close()
