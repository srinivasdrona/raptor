"""AC5 — Storage determinism (R-A11).

Given a fixed snapshot + a pinned `combination_rule_ref` + canonically-
serialized inputs, the stored derived output is identical on recompute,
using a tiny LOCAL fixture combination rule (the real ACMG rule is PRD-01's,
not this PRD's).
"""

from __future__ import annotations

from raptor.kb.store import KBStore, canonical_json, fixture_combination_rule

VARIANT_ID = "NC_000016.10:5000000:A:G"


def _seed_two_criteria(store, make_provenance):
    run_id = "determinism-run"
    prov = make_provenance(run_id=run_id)
    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession="VCV_determinism", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    store.stage_variant(
        run_id, variant_id=VARIANT_ID, gene="TSC2", class_="missense", provenance=prov,
        source_ref_ids=source_ref_id,
    )
    store.stage_evidence_added(
        run_id, seq_in_run=1, variant_id=VARIANT_ID, tier="tier1", criterion="PM2",
        strength="moderate", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov, event_provenance=prov, event_timestamp="2026-01-01T00:00:00Z",
    )
    store.stage_evidence_added(
        run_id, seq_in_run=2, variant_id=VARIANT_ID, tier="tier1", criterion="BP4",
        strength="supporting", direction="benign", source_ref_id=source_ref_id,
        row_provenance=prov, event_provenance=prov, event_timestamp="2026-01-01T00:00:00Z",
    )
    store.publish(run_id)
    (watermark,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
    return watermark, prov


def test_recompute_from_same_snapshot_is_byte_identical(store, make_provenance):
    watermark, prov = _seed_two_criteria(store, make_provenance)

    derived_1, input_hash_1 = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#recompute-a", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark, combination_rule_ref="fixture-rule-v1", provenance=prov,
    )
    derived_2, input_hash_2 = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#recompute-b", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark, combination_rule_ref="fixture-rule-v1", provenance=prov,
    )

    assert input_hash_1 == input_hash_2
    assert derived_1 == derived_2
    assert derived_1 == {
        "label": "VUS",
        "pathogenic_weight": 2,  # PM2 moderate
        "benign_weight": 1,  # BP4 supporting
        "net": 1,
    }


def test_fixture_rule_is_input_order_independent(store, make_provenance):
    """Canonical serialization means shuffled input order still hashes identically."""
    watermark, _ = _seed_two_criteria(store, make_provenance)
    effective = store.effective_evidence_at(watermark, variant_id=VARIANT_ID)
    assert len(effective) == 2

    shuffled = list(reversed(effective))
    assert shuffled != effective  # guarantee the input order actually differs

    derived_original = fixture_combination_rule(effective)
    derived_shuffled = fixture_combination_rule(shuffled)
    assert derived_original == derived_shuffled

    canon_original = canonical_json(
        sorted(
            [{"criterion": r["criterion"], "strength": r["strength"], "direction": r["direction"]} for r in effective],
            key=lambda d: d["criterion"],
        )
    )
    canon_shuffled = canonical_json(
        sorted(
            [{"criterion": r["criterion"], "strength": r["strength"], "direction": r["direction"]} for r in shuffled],
            key=lambda d: d["criterion"],
        )
    )
    assert canon_original == canon_shuffled


def test_canonical_json_key_order_independent():
    a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
    b = {"a": 2, "c": {"x": 2, "y": 1}, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_different_evidence_content_yields_different_derived_output(store, make_provenance):
    """Negative control: the fixture rule is not a constant — different inputs -> different output."""
    watermark, prov = _seed_two_criteria(store, make_provenance)
    derived_two_criteria, _ = store.build_evidence_snapshot(
        snapshot_id=f"{VARIANT_ID}#two-criteria", variant_id=VARIANT_ID,
        ledger_high_watermark=watermark, combination_rule_ref="fixture-rule-v1", provenance=prov,
    )

    run_id_2 = "determinism-run-2"
    prov2 = make_provenance(run_id=run_id_2)
    variant_id_2 = "NC_000016.10:5100000:A:G"
    source_ref_id_2 = store.stage_source_ref(
        run_id_2, source="ClinVar", accession="VCV_determinism_2", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov2,
    )
    store.stage_variant(
        run_id_2, variant_id=variant_id_2, gene="TSC2", class_="missense", provenance=prov2,
        source_ref_ids=source_ref_id_2,
    )
    store.stage_evidence_added(
        run_id_2, seq_in_run=1, variant_id=variant_id_2, tier="tier1", criterion="PVS1",
        strength="very_strong", direction="pathogenic", source_ref_id=source_ref_id_2,
        row_provenance=prov2, event_provenance=prov2, event_timestamp="2026-01-01T00:00:00Z",
    )
    store.publish(run_id_2)
    (watermark_2,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()

    derived_one_criterion, _ = store.build_evidence_snapshot(
        snapshot_id=f"{variant_id_2}#one-criterion", variant_id=variant_id_2,
        ledger_high_watermark=watermark_2, combination_rule_ref="fixture-rule-v1", provenance=prov2,
    )

    assert derived_one_criterion != derived_two_criteria
    assert derived_one_criterion["label"] == "P"
