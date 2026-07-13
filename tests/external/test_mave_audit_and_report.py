from __future__ import annotations

import ast
import json
from importlib import import_module
from pathlib import Path

import pytest


def _source_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.source")
    except ImportError as exc:
        pytest.fail(f"external MAVE source loader is not implemented: {exc}")
    return {
        "MaveScoreRecord": module.MaveScoreRecord,
    }


def _endpoint_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.endpoint")
    except ImportError as exc:
        pytest.fail(f"external MAVE endpoint is not implemented: {exc}")
    return {
        "run_label_blind_validation": module.run_label_blind_validation,
    }


def _import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _score_record(*, variant_id, score, hgvs_c=None, reference=None):
    api = _source_api()
    return api["MaveScoreRecord"](
        variant_id=variant_id,
        hgvs_c=hgvs_c,
        score=score,
        reference=reference,
    )


def _walk_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_keys(value)


def _build_report(reverse: bool = False):
    api = _endpoint_api()
    rows = [
        _score_record(variant_id="SENTINEL_VARIANT_1", hgvs_c="c.100A>G", score=0.200, reference="A"),
        _score_record(variant_id="SENTINEL_VARIANT_2", hgvs_c="c.200C>T", score=0.620, reference="C"),
        _score_record(variant_id="SENTINEL_VARIANT_3", hgvs_c="c.300G>A", score=0.590, reference="G"),
        _score_record(variant_id="SENTINEL_VARIANT_4", hgvs_c="c.400T>C", score=0.610, reference="T"),
        _score_record(variant_id="SENTINEL_VARIANT_5", hgvs_c="c.500A>C", score=0.100, reference="A"),
        _score_record(variant_id="SENTINEL_VARIANT_6", hgvs_c="c.600G>T", score=0.300, reference="G"),
    ]
    if reverse:
        rows = list(reversed(rows))

    def fake_scorer(variant_id: str) -> float:
        return {
            "SENTINEL_VARIANT_1": 0.120,
            "SENTINEL_VARIANT_2": 0.700,
            "SENTINEL_VARIANT_3": 0.680,
            "SENTINEL_VARIANT_4": 0.710,
            "SENTINEL_VARIANT_5": 0.180,
            "SENTINEL_VARIANT_6": 0.330,
        }[variant_id]

    return api["run_label_blind_validation"](
        rows,
        fake_scorer,
        bootstrap_resamples=32,
        random_seed=7,
    )


def test_scorer_modules_do_not_import_external_mave() -> None:
    scorer_dir = Path("src/raptor/scorer")
    for path in scorer_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _import_names(tree)
        assert not any(
            name == "raptor.external.mave" or name.startswith("raptor.external.mave.")
            for name in imported
        ), f"{path} imports external MAVE"


def test_mave_modules_preserve_bias_label_and_gate_boundaries() -> None:
    forbidden = {
        "bias_2015",
        "raptor.eval.benchmark",
        "raptor.eval.gate",
        "raptor.eval.harness",
        "raptor.eval.knowns",
    }
    modules = (
        Path("src/raptor/external/mave/register.py"),
        Path("src/raptor/external/mave/source.py"),
        Path("src/raptor/external/mave/endpoint.py"),
        Path("src/raptor/external/mave/identity.py"),
        Path("src/raptor/external/mave/partition.py"),
        Path("src/raptor/external/mave/orthogonal_metrics.py"),
        Path("src/raptor/external/mave/report.py"),
    )
    for path in modules:
        if not path.is_file():
            pytest.fail(f"implementation missing: {path}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _import_names(tree)
        assert not any(
            name == blocked or name.startswith(blocked + ".")
            for name in imported
            for blocked in forbidden
        ), f"{path} crosses a forbidden dependency boundary: {sorted(imported)!r}"


def test_aggregate_is_identity_free_label_free_and_deterministic() -> None:
    first = _build_report()
    second = _build_report(reverse=True)

    aggregate_first = first.aggregate()
    aggregate_second = second.aggregate()
    blob = json.dumps(aggregate_first, sort_keys=True)

    assert aggregate_first == aggregate_second
    assert first.content_hash() == second.content_hash()
    assert aggregate_first["validation_mode"] == "NON_GATING"
    assert "SENTINEL_VARIANT_1" not in blob
    assert "SENTINEL_VARIANT_6" not in blob

    forbidden_keys = {
        "variant_id",
        "variant_ids",
        "clinical_label",
        "clinical_labels",
        "holdout_label_counts",
        "labels",
    }
    assert forbidden_keys.isdisjoint(set(_walk_keys(aggregate_first)))
