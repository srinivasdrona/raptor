"""PRD-01 checker round-1 findings (planner-authored, spec-correct invariants).

Each test exercises the REAL `run_scorer`/`load_config` path and asserts the
correct behavior (not the impl's current buggy output). RED against the pre-fix
scorer. Covers: splice-region compound consequences (FR8/AC5), out-of-scope gene
routing (v1 TSC2 scope/R-A3), strength-vs-criterion-vocab enforcement (§10.3),
config direction/family consistency, and zero-fired per-variant accounting (R-A10).
"""
from __future__ import annotations

import pytest
import yaml

from raptor.kb.store import KBStore
from raptor.scorer.config import ScorerConfig, load_config, ConfigError
from raptor.scorer.model import BiasRecord
from raptor.scorer.pipeline import run_scorer


class _Source:
    def __init__(self, records):
        self._records = records

    def records(self, run=None):
        return self._records


def _base_cfg_dict():
    return {
        "bias_version": "3.0.0",
        "bias_data_version": "2026.03.01",
        "included_criteria": ["PVS1", "PM2", "PM4"],
        "strength_map": {"1": "supporting", "2": "moderate", "3": "strong",
                         "4": "very_strong", "5": "stand_alone"},
        "acmg_criteria": {
            "PVS1": {"direction": "pathogenic",
                     "strength_vocab": ["very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["moderate", "supporting"]},
            "PM4": {"direction": "pathogenic", "strength_vocab": ["moderate"]},
        },
        "edge_cases": {"splice_region": True, "non_mane_transcript": True},
        "genes": {"TSC2": "NM_000548.5"},
        "licensing": {"revel": "research"},
    }


def _cfg(**overrides):
    d = _base_cfg_dict()
    d.update(overrides)
    return ScorerConfig(
        bias_version=d["bias_version"], bias_data_version=d["bias_data_version"],
        included_criteria=d["included_criteria"], strength_map=d["strength_map"],
        acmg_criteria=d["acmg_criteria"], edge_cases=d["edge_cases"],
        genes=d["genes"], licensing=d["licensing"],
    )


def _rec(variant_id, gene, consequence, criteria, transcript="NM_000548.5"):
    return BiasRecord(
        chromosome="chr16", position=100, ref_allele="A", alt_allele="T",
        variant_id=variant_id, variant_type="SNV", consequence=consequence,
        acmg_classification="uncertain", gene_name=gene, transcript=transcript,
        criteria=criteria, provenance={"source": "bias"},
    )


def _evidence_variant_ids(store):
    return {r[0] for r in store.conn.execute("SELECT DISTINCT variant_id FROM evidence").fetchall()}


def _manual_count(store):
    return store.conn.execute("SELECT COUNT(*) FROM manual_queue").fetchone()[0]


@pytest.mark.parametrize("consequence", [
    "splice_region_variant&intron_variant",   # VEP compound
    "missense_variant,splice_region_variant",  # comma-joined
    "splice_region_variant",                   # exact (control — already routes)
])
def test_splice_region_compound_routes_to_manual(consequence):
    """[major] FR8/AC5: a splice-region variant in ANY (incl. compound/VEP)
    consequence encoding must route to manual review, never be auto-scored."""
    store = KBStore(":memory:")
    try:
        rec = _rec("chr16:1:A:T", "TSC2", consequence, {"pm2": (1, "PM2:")})
        run_scorer(_cfg(), _Source([rec]), store)
        assert "chr16:1:A:T" not in _evidence_variant_ids(store), f"{consequence!r} was auto-scored"
        assert _manual_count(store) == 1
    finally:
        store.close()


def test_out_of_scope_gene_routes_to_manual():
    """[major] v1 scope is TSC2 (R-A3): a record for a gene not in config.genes
    must route to manual review, never be silently scored."""
    store = KBStore(":memory:")
    try:
        rec = _rec("chr9:1:A:T", "TSC1", "missense_variant", {"pm2": (1, "PM2:")})
        run_scorer(_cfg(), _Source([rec]), store)
        assert "chr9:1:A:T" not in _evidence_variant_ids(store), "out-of-scope TSC1 was auto-scored"
        assert _manual_count(store) == 1
    finally:
        store.close()


def test_out_of_vocab_strength_routes_to_manual():
    """[major] §10.3: an emitted strength must be within the criterion's
    strength_vocab. PVS1 fired at int 5 -> 'stand_alone' is NOT in PVS1's vocab;
    the scorer must NOT emit it — route to manual review instead."""
    store = KBStore(":memory:")
    try:
        rec = _rec("chr16:2:A:T", "TSC2", "frameshift_variant", {"pvs1": (5, "PVS1_stand-alone")})
        run_scorer(_cfg(), _Source([rec]), store)
        rows = store.conn.execute(
            "SELECT strength FROM evidence WHERE variant_id='chr16:2:A:T'"
        ).fetchall()
        assert rows == [], f"emitted out-of-vocab strength: {rows}"
        assert _manual_count(store) == 1
    finally:
        store.close()


def test_config_rejects_direction_family_mismatch(tmp_path):
    """[major] §10.3: a criterion's configured direction must match its ACMG
    family (P* -> pathogenic, B* -> benign). A PM4 declared benign is a config
    error and must fail loud (else evidence_kinds and emitted direction diverge)."""
    d = _base_cfg_dict()
    d["acmg_criteria"]["PM4"] = {"direction": "benign", "strength_vocab": ["moderate"]}
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError):
        load_config(str(p))


def test_zero_fired_variant_is_accounted_in_report():
    """[major] R-A10: a record with 0 fired (or 0 included) criteria must be
    durably accounted for as an explicit per-variant outcome, not silently
    dropped with only a source_ref."""
    store = KBStore(":memory:")
    try:
        rec = _rec("chr16:3:A:T", "TSC2", "missense_variant", {"pm2": (0, ""), "pvs1": (0, "")})
        report = run_scorer(_cfg(), _Source([rec]), store)
        assert report.total_input == 1
        outcomes = {o["variant_id"]: o["outcome"] for o in report.variant_outcomes}
        assert outcomes.get("chr16:3:A:T") == "no_evidence", (
            f"zero-fired variant not accounted: {getattr(report, 'variant_outcomes', None)}"
        )
    finally:
        store.close()


def test_duplicate_variant_id_fails_loud():
    """[major] BIAS output is a source-contract: exactly one row per variant. A
    duplicate variant_id is drift/corruption -> FAIL LOUD with a clear message
    (not a cryptic UNIQUE-constraint crash), and nothing partially published."""
    store = KBStore(":memory:")
    try:
        recs = [
            _rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm2": (1, "PM2:")}),
            _rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm4": (2, "PM4_moderate")}),
        ]
        with pytest.raises(Exception) as exc:
            run_scorer(_cfg(), _Source(recs), store)
        msg = str(exc.value).lower()
        assert "duplicate" in msg and "variant" in msg, f"unclear duplicate-variant error: {exc.value!r}"
        assert store.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM manual_queue").fetchone()[0] == 0
    finally:
        store.close()


def test_failed_duplicate_run_leaves_no_published_state_change():
    """[major] Auditability: a run that fails a source-contract check must be a
    no-op on PUBLISHED state — including `evidence_kinds` vocabulary registration.
    A duplicate variant_id must abort BEFORE any KB mutation, so
    `published_state_hash()` is identical before and after (validate-before-mutate)."""
    store = KBStore(":memory:")
    try:
        before = store.published_state_hash()
        recs = [  # PM4 is unseeded — registering it would change evidence_kinds/state
            _rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm4": (2, "PM4_moderate")}),
            _rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm2": (1, "PM2:")}),
        ]
        with pytest.raises(Exception):
            run_scorer(_cfg(), _Source(recs), store)
        after = store.published_state_hash()
        assert after == before, "failed duplicate run mutated published state (e.g. evidence_kinds)"
    finally:
        store.close()


@pytest.mark.parametrize("records, trigger", [
    ([_rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm4": (2, "PM4_moderate")}),
      _rec("chr16:601:A:T", "TSC2", "missense_variant", {"pm2": (1, "PM2:")})], "duplicate_variant_id"),
    ([_rec("chr16:700:A:T", "TSC2", "missense_variant", {"pm4": (9, "PM4_unmapped")})], "unmapped_strength_int"),
])
def test_failed_run_never_mutates_published_state(records, trigger):
    """[class invariant — 'no-state-change-on-failure'] ANY exception raised by
    run_scorer must leave published state byte-identical, including evidence_kinds
    vocabulary registration. This is the CLASS test (multiple raise triggers), not
    a single instance — evidence_kind registration must be staged+atomic with
    publish so a failed run mutates nothing. (`PM4` is unseeded, so eager
    registration WOULD change state.)"""
    store = KBStore(":memory:")
    try:
        before = store.published_state_hash()
        with pytest.raises(Exception):
            run_scorer(_cfg(), _Source(records), store)
        assert store.published_state_hash() == before, (
            f"failed run ({trigger}) mutated published state (e.g. evidence_kinds)"
        )
    finally:
        store.close()
