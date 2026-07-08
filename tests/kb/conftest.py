"""Shared fixtures for the PRD-03 KB test suite."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

import pytest

from raptor.kb.store import KBStore

# A stable "genesis" evidence_kinds pair seeded by migration 0001, used by
# most tests that need a valid (tier, criterion) to satisfy evidence's FK.
TIER1_CRITERION = ("tier1", "PM2")
TIER1_CRITERION_STRENGTH = "moderate"
TIER1_CRITERION_DIRECTION = "pathogenic"


@pytest.fixture
def kb_path(tmp_path: Path) -> Path:
    return tmp_path / "kb.sqlite3"


@pytest.fixture
def store(kb_path: Path):
    s = KBStore(kb_path)
    yield s
    s.close()


@pytest.fixture
def make_provenance() -> Callable[..., str]:
    """Factory for a complete, valid provenance JSON blob."""

    def _make(run_id: str = "run-1", **overrides: Any) -> str:
        base = dict(
            tool_version="raptor-kb-test-0.1.0",
            source="test-fixture",
            source_snapshot_version="snap-2026-01-01",
            env_versions={"python": "3.12.3"},
            originating_run=run_id,
            timestamp="2026-01-01T00:00:00Z",
        )
        base.update(overrides)
        return KBStore.build_provenance(**base)

    return _make


@pytest.fixture
def seeded_history(store: KBStore, make_provenance: Callable[..., str]) -> dict[str, Any]:
    """Insert one minimal, valid row directly into each of the 8 history tables.

    Returns identifying info per table so tests can target UPDATE/DELETE at
    a real row. Inserted via raw SQL (not the staging/publish pipeline) so
    each table's own constraints are exercised directly and independently.
    """
    run_id = "seed-run"
    prov = make_provenance(run_id=run_id)
    conn = store.conn

    variant_id = "NC_000016.10:2100000:A:G"
    conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES (?, ?, ?, ?)",
        (variant_id, "TSC2", "missense", prov),
    )

    source_ref_id = KBStore.compute_source_ref_id("ClinVar", "VCV000099999", "snap-2026-01-01", "row-1")
    conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_ref_id, "ClinVar", "VCV000099999", "snap-2026-01-01", "2026-01-01",
         "checksum123", "row-1", "raw clinvar row", "resolved", prov),
    )

    conn.execute(
        "INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance) VALUES (?, ?, ?)",
        (variant_id, source_ref_id, prov),
    )

    cur = conn.execute(
        """
        INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp)
        VALUES ('variant_observed', ?, ?, ?, ?, ?)
        """,
        (variant_id, run_id, '{"variant_id":"%s"}' % variant_id, prov, "2026-01-01T00:00:00Z"),
    )
    ledger_seq = cur.lastrowid

    cur = conn.execute(
        """
        INSERT INTO evidence
            (ledger_seq, variant_id, tier, criterion, strength, direction,
             supporting_record, source_ref_id, run_id, supersedes_evidence_id, provenance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (ledger_seq, variant_id, TIER1_CRITERION[0], TIER1_CRITERION[1], TIER1_CRITERION_STRENGTH,
         TIER1_CRITERION_DIRECTION, "span:1-2", source_ref_id, run_id, prov),
    )
    evidence_id = cur.lastrowid

    snapshot_id = f"{variant_id}#v1.0"
    conn.execute(
        """
        INSERT INTO evidence_snapshots
            (snapshot_id, variant_id, ledger_high_watermark, input_hash, combination_rule_ref, provenance)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, variant_id, ledger_seq, "deadbeef" * 4, "fixture-rule-v1", prov),
    )

    conn.execute(
        """
        INSERT INTO classification_versions
            (variant_id, version, evidence_snapshot_ref, status, approvals, timestamp, provenance)
        VALUES (?, 'v1.0', ?, 'VUS', '[]', ?, ?)
        """,
        (variant_id, snapshot_id, "2026-01-01T00:00:00Z", prov),
    )

    cur = conn.execute(
        """
        INSERT INTO knowledge_assertions
            (source_ref_id, assertion_type, subject, object, status, provenance)
        VALUES (?, 'co-occurrence', ?, 'TSC2', 'hypothesis', ?)
        """,
        (source_ref_id, variant_id, prov),
    )
    assertion_id = cur.lastrowid

    return {
        "variants": ("variant_id = ?", (variant_id,)),
        "source_refs": ("source_ref_id = ?", (source_ref_id,)),
        "variant_source_refs": ("variant_id = ? AND source_ref_id = ?", (variant_id, source_ref_id)),
        "ledger": ("ledger_seq = ?", (ledger_seq,)),
        "evidence": ("evidence_id = ?", (evidence_id,)),
        "evidence_snapshots": ("snapshot_id = ?", (snapshot_id,)),
        "classification_versions": ("variant_id = ? AND version = 'v1.0'", (variant_id,)),
        "knowledge_assertions": ("assertion_id = ?", (assertion_id,)),
        "_ids": {
            "variant_id": variant_id,
            "source_ref_id": source_ref_id,
            "ledger_seq": ledger_seq,
            "evidence_id": evidence_id,
            "snapshot_id": snapshot_id,
        },
    }


HISTORY_TABLES: tuple[str, ...] = (
    "ledger",
    "variants",
    "source_refs",
    "variant_source_refs",
    "evidence",
    "evidence_snapshots",
    "classification_versions",
    "knowledge_assertions",
)
