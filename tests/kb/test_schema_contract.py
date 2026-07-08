"""AC9 — Config + no trace-cribbing.

Migrations apply cleanly and are idempotent; the runtime contract (§5.1) is
verified; a forbidden-path audit asserts the module source reads no
benchmark/label/oracle file (G2 audit).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import raptor.kb
from raptor.kb.schema import (
    MIGRATIONS_DIR,
    RuntimeContractError,
    applied_versions,
    migrate,
    verify_runtime_contract,
)

SRC_ROOT = Path(raptor.kb.__file__).resolve().parent.parent  # src/raptor (whole package, not just kb/)


def test_migrations_apply_cleanly_and_are_idempotent(tmp_path):
    db_path = tmp_path / "contract.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        applied_1 = migrate(conn)
        assert applied_1 == ["0001_initial_schema"]
        assert applied_versions(conn) == {"0001_initial_schema"}

        # Idempotent: running again applies nothing new and does not error.
        applied_2 = migrate(conn)
        assert applied_2 == []
        assert applied_versions(conn) == {"0001_initial_schema"}

        (row_count,) = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '0001_initial_schema'"
        ).fetchone()
        assert row_count == 1  # not duplicated by the second run
    finally:
        conn.close()


def test_runtime_contract_verified_on_open(tmp_path):
    db_path = tmp_path / "contract2.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        migrate(conn)
        (fk,) = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk == 1
        (journal_mode,) = conn.execute("PRAGMA journal_mode").fetchone()
        assert str(journal_mode).lower() == "wal"
        (synchronous,) = conn.execute("PRAGMA synchronous").fetchone()
        assert int(synchronous) == 2  # FULL (§5.1)
        # Should not raise:
        verify_runtime_contract(conn)
    finally:
        conn.close()


def test_runtime_contract_violation_is_detected(tmp_path):
    db_path = tmp_path / "contract3.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        migrate(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        with pytest.raises(RuntimeContractError):
            verify_runtime_contract(conn)
    finally:
        conn.close()


def test_runtime_contract_synchronous_downgrade_is_detected(tmp_path):
    """AC9 (checker fix): §5.1 requires synchronous=FULL; downgrading it must
    be caught by the runtime-contract check, not silently accepted."""
    db_path = tmp_path / "contract3b.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        migrate(conn)
        verify_runtime_contract(conn)  # sanity: passes before the downgrade

        conn.execute("PRAGMA synchronous = NORMAL")
        (synchronous,) = conn.execute("PRAGMA synchronous").fetchone()
        assert int(synchronous) == 1  # confirm the downgrade actually took effect
        with pytest.raises(RuntimeContractError, match="synchronous"):
            verify_runtime_contract(conn)

        conn.execute("PRAGMA synchronous = OFF")
        with pytest.raises(RuntimeContractError, match="synchronous"):
            verify_runtime_contract(conn)
    finally:
        conn.close()


def test_foreign_keys_enforced_end_to_end(tmp_path):
    """A concrete proof that PRAGMA foreign_keys=ON is actually enforced, not just set."""
    db_path = tmp_path / "contract4.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        migrate(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance) "
                "VALUES ('no-such-variant', 'no-such-source-ref', '{}')"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Forbidden-path audit (G2, manual until lint): production code must read no
# benchmark/label/oracle file. We scan the actual shipped source, not a
# hardcoded claim, so this genuinely re-verifies the property every run.
# ---------------------------------------------------------------------------

FORBIDDEN_CALL_PATTERNS = [
    re.compile(r"\bopen\s*\("),
    re.compile(r"\.loadmat\s*\("),
    re.compile(r"\bnp\.load\s*\("),
    re.compile(r"\.read_csv\s*\("),
    re.compile(r"\.read_excel\s*\("),
    re.compile(r"\bpickle\.load\s*\("),
]

FORBIDDEN_PATH_LITERAL_PATTERNS = [
    # Suspicious file-path *literals* pointing at answer-key style data —
    # deliberately narrower than a blanket word scan, since this module's
    # own compliance documentation legitimately *discusses* "benchmark" /
    # "oracle" / "label" as concepts (GP-9/H1) without ever reading such a
    # file. This checks for actual path-like literals, not prose mentions.
    re.compile(
        r"""['"][^'"]*(benchmark|ground_truth|answer_key|oracle|_labels?)[^'"]*\.(csv|xlsx?|mat|json|parquet|tsv)['"]""",
        re.IGNORECASE,
    ),
]


def _iter_source_files():
    return sorted(SRC_ROOT.rglob("*.py"))


def test_no_forbidden_file_read_calls_in_kb_source():
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_CALL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path}: matched {pattern.pattern!r}")
    assert offenders == [], f"forbidden file-read calls found: {offenders}"


def test_no_benchmark_label_oracle_path_literals_in_kb_source():
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATH_LITERAL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path}: matched {pattern.pattern!r}")
    assert offenders == [], f"benchmark/label/oracle path literals found: {offenders}"


def test_migrations_directory_is_the_only_ddl_source():
    """GP-6: schema lives in SQL files, not hardcoded DDL scattered in .py files.

    Tightened (checker fix, GP6-GAP): the original regex only matched
    ``CREATE TABLE`` and missed ``CREATE TEMP TABLE`` / ``CREATE TEMPORARY
    TABLE`` (SQLite's staging-table DDL) — this now catches both forms and
    scans the whole ``src/raptor`` tree (``SRC_ROOT``), not just ``kb/``.
    """
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert len(sql_files) >= 1
    assert sql_files[0].name == "0001_initial_schema.sql"

    ddl_pattern = re.compile(r"\bCREATE\s+(TEMP(?:ORARY)?\s+)?TABLE\b", re.IGNORECASE)
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        assert not ddl_pattern.search(text), f"raw CREATE TABLE found outside migrations/*.sql: {path}"


def test_staging_ddl_lives_in_sql_resource_not_python():
    """AC9 (checker fix, AC9-HARDCODED-STAGING-DDL): the run-scoped staging
    tables' DDL must be loaded from a ``.sql`` resource file, not built as
    a Python string in ``store.py``."""
    from raptor.kb.store import STAGING_SQL_PATH

    assert STAGING_SQL_PATH.is_file()
    assert STAGING_SQL_PATH.suffix == ".sql"
    staging_sql = STAGING_SQL_PATH.read_text(encoding="utf-8")
    for expected_table in (
        "stg_variants", "stg_source_refs", "stg_variant_source_refs",
        "stg_evidence_rows", "stg_ledger_events", "stg_manual_queue",
    ):
        assert expected_table in staging_sql

    store_source = (SRC_ROOT / "kb" / "store.py").read_text(encoding="utf-8").upper()
    assert "CREATE TEMP TABLE" not in store_source
    assert "CREATE TEMPORARY TABLE" not in store_source
    assert "CREATE TABLE" not in store_source

