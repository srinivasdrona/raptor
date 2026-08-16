from __future__ import annotations

import builtins
import copy
import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_MANIFEST_PATH = REPO_ROOT / "configs" / "rescuescreen" / "entry_gates.yaml"

CANONICAL_GATE_ORDER = ("EG-1", "EG-2", "EG-3", "EG-4", "EG-5")
CANONICAL_FAIL_STATE_BY_GATE = {
    "EG-1": "MECHANISM_UNVERIFIED",
    "EG-2": "MAPPING_UNVERIFIED",
    "EG-3": "STRUCTURE_COVERAGE_INSUFFICIENT",
    "EG-4": "LICENCE_INCOMPATIBLE",
    "EG-5": "NO_TRACTABLE_ASSAY",
}


def _require_rescuescreen_api():
    try:
        import raptor.rescuescreen as api
    except Exception as exc:  # pragma: no cover - exercised in RED state now
        pytest.fail(f"implementation missing: raptor.rescuescreen ({exc})")

    required_exports = (
        "GateEvidenceRef",
        "EntryGateAssessment",
        "EntryGateManifest",
        "EntryGateReport",
        "RescueScreenError",
        "RescueScreenSchemaError",
        "RescueScreenHashError",
        "RescueScreenPathError",
        "entry_gate_manifest_content_hash",
        "load_entry_gate_manifest",
        "evaluate_entry_gates",
        "entry_gate_report_to_dict",
    )
    missing = [name for name in required_exports if not hasattr(api, name)]
    assert not missing, f"raptor.rescuescreen missing required public exports: {missing}"
    return api


def _require_committed_manifest_path() -> Path:
    if not COMMITTED_MANIFEST_PATH.is_file():
        pytest.fail(f"implementation missing: {COMMITTED_MANIFEST_PATH}")
    return COMMITTED_MANIFEST_PATH


def _read_committed_manifest_mapping() -> dict[str, Any]:
    path = _require_committed_manifest_path()
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "committed manifest must parse to a mapping"
    return parsed


def _oracle_manifest_content_hash(manifest_mapping: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest_mapping))
    payload.pop("manifest_content_hash", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_valid_manifest_hash(manifest_mapping: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(manifest_mapping))
    payload["manifest_content_hash"] = _oracle_manifest_content_hash(payload)
    return payload


def _reverse_mapping_order(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _reverse_mapping_order(v) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reverse_mapping_order(v) for v in value]
    return value


def _write_manifest(
    tmp_path: Path,
    file_name: str,
    manifest_mapping: Mapping[str, Any],
    *,
    line_ending: str = "\n",
) -> Path:
    rendered = yaml.safe_dump(manifest_mapping, sort_keys=False, allow_unicode=True)
    if line_ending != "\n":
        rendered = rendered.replace("\n", line_ending)
    out_path = tmp_path / file_name
    out_path.write_bytes(rendered.encode("utf-8"))
    return out_path


def _valid_evidence_ref(index: int) -> dict[str, str]:
    return {
        "artifact_id": f"artifact-{index}",
        "artifact_schema": "atlas.claim.bundle.v1",
        "content_hash": "a" * 64,
        "reviewed_by": f"reviewer-{index}",
        "reviewed_at": f"2026-08-{index:02d}T00:00:00Z",
    }


def _all_satisfied_manifest_from(base_manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(base_manifest))
    gates = payload.get("gates", [])
    assert isinstance(gates, list), "manifest gates must be a list in test fixture"
    for index, gate in enumerate(gates, start=1):
        assert isinstance(gate, dict), "manifest gate must be a mapping in test fixture"
        gate["status"] = "SATISFIED"
        gate["evidence_refs"] = [_valid_evidence_ref(index)]
        gate["note"] = f"{gate.get('gate_id', f'gate-{index}')} reviewed evidence registered"
    return _with_valid_manifest_hash(payload)


def _report_canonical_bytes(report_dict: Mapping[str, Any]) -> bytes:
    return json.dumps(report_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_rseg_ac01_closed_schema_rejects_missing_unknown_mistyped_and_invalid_enums(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _read_committed_manifest_mapping()

    # missing required top-level field
    missing_required = _all_satisfied_manifest_from(base)
    missing_required.pop("lane_id", None)
    missing_required = _with_valid_manifest_hash(missing_required)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "missing_required.yaml", missing_required))

    # unknown top-level field
    unknown_top_level = _all_satisfied_manifest_from(base)
    unknown_top_level["unexpected_top_level"] = "forbidden"
    unknown_top_level = _with_valid_manifest_hash(unknown_top_level)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "unknown_top_level.yaml", unknown_top_level))

    # wrong top-level type
    wrong_type = _all_satisfied_manifest_from(base)
    wrong_type["lane_version"] = {"wrong": "type"}
    wrong_type = _with_valid_manifest_hash(wrong_type)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "wrong_type.yaml", wrong_type))

    # invalid enum
    bad_enum = _all_satisfied_manifest_from(base)
    bad_enum["gates"][0]["status"] = "PARTIAL"
    bad_enum = _with_valid_manifest_hash(bad_enum)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "bad_enum.yaml", bad_enum))

    # unknown nested key in gate
    unknown_gate_key = _all_satisfied_manifest_from(base)
    unknown_gate_key["gates"][0]["unexpected_gate_key"] = True
    unknown_gate_key = _with_valid_manifest_hash(unknown_gate_key)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "unknown_gate_key.yaml", unknown_gate_key))

    # unknown nested key in evidence_ref
    unknown_evidence_key = _all_satisfied_manifest_from(base)
    unknown_evidence_key["gates"][0]["evidence_refs"][0]["unexpected_evidence_key"] = "forbidden"
    unknown_evidence_key = _with_valid_manifest_hash(unknown_evidence_key)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "unknown_evidence_key.yaml", unknown_evidence_key))


def test_rseg_ac02_gate_ids_order_and_fail_state_bindings_are_exact(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _read_committed_manifest_mapping()

    duplicate_gate = _all_satisfied_manifest_from(base)
    duplicate_gate["gates"][1]["gate_id"] = "EG-1"
    duplicate_gate = _with_valid_manifest_hash(duplicate_gate)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "duplicate_gate.yaml", duplicate_gate))

    missing_gate = _all_satisfied_manifest_from(base)
    missing_gate["gates"] = missing_gate["gates"][:-1]
    missing_gate = _with_valid_manifest_hash(missing_gate)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "missing_gate.yaml", missing_gate))

    out_of_order = _all_satisfied_manifest_from(base)
    out_of_order["gates"][0], out_of_order["gates"][1] = out_of_order["gates"][1], out_of_order["gates"][0]
    out_of_order = _with_valid_manifest_hash(out_of_order)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "out_of_order.yaml", out_of_order))

    unknown_gate = _all_satisfied_manifest_from(base)
    unknown_gate["gates"][2]["gate_id"] = "EG-6"
    unknown_gate = _with_valid_manifest_hash(unknown_gate)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "unknown_gate.yaml", unknown_gate))

    wrong_fail_state_binding = _all_satisfied_manifest_from(base)
    wrong_fail_state_binding["gates"][0]["fail_state"] = CANONICAL_FAIL_STATE_BY_GATE["EG-2"]
    wrong_fail_state_binding = _with_valid_manifest_hash(wrong_fail_state_binding)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(
            _write_manifest(tmp_path, "wrong_fail_state_binding.yaml", wrong_fail_state_binding)
        )


def test_rseg_ac03_satisfied_requires_complete_reviewed_evidence_refs(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _read_committed_manifest_mapping()

    no_evidence = _all_satisfied_manifest_from(base)
    no_evidence["gates"][0]["evidence_refs"] = []
    no_evidence = _with_valid_manifest_hash(no_evidence)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "satisfied_without_evidence.yaml", no_evidence))

    missing_field = _all_satisfied_manifest_from(base)
    missing_field["gates"][0]["evidence_refs"][0].pop("reviewed_by", None)
    missing_field = _with_valid_manifest_hash(missing_field)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "evidence_missing_field.yaml", missing_field))

    blank_field = _all_satisfied_manifest_from(base)
    blank_field["gates"][0]["evidence_refs"][0]["reviewed_by"] = "   "
    blank_field = _with_valid_manifest_hash(blank_field)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "evidence_blank_field.yaml", blank_field))

    bad_hash = _all_satisfied_manifest_from(base)
    bad_hash["gates"][0]["evidence_refs"][0]["content_hash"] = "ABCDEF"
    bad_hash = _with_valid_manifest_hash(bad_hash)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "evidence_bad_hash.yaml", bad_hash))


def test_rseg_ac03_yaml_coerced_reviewed_at_date_and_datetime_are_rejected(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _read_committed_manifest_mapping()

    yaml_date = _all_satisfied_manifest_from(base)
    yaml_date["gates"][0]["evidence_refs"][0]["reviewed_at"] = dt.date(2026, 8, 16)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "yaml_date.yaml", yaml_date))

    yaml_datetime = _all_satisfied_manifest_from(base)
    yaml_datetime["gates"][0]["evidence_refs"][0]["reviewed_at"] = dt.datetime(2026, 8, 16, 0, 0, 0)
    with pytest.raises(api.RescueScreenSchemaError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "yaml_datetime.yaml", yaml_datetime))


def test_rseg_ac04_independent_hash_oracle_properties() -> None:
    base = _read_committed_manifest_mapping()
    base = _with_valid_manifest_hash(base)
    base_hash = _oracle_manifest_content_hash(base)

    reordered_keys = _reverse_mapping_order(base)
    reordered_hash = _oracle_manifest_content_hash(reordered_keys)
    assert reordered_hash == base_hash

    sequence_changed = copy.deepcopy(base)
    sequence_changed["gates"] = list(reversed(sequence_changed["gates"]))
    sequence_changed_hash = _oracle_manifest_content_hash(sequence_changed)
    assert sequence_changed_hash != base_hash

    semantic_change = copy.deepcopy(base)
    semantic_change["gates"][0]["note"] = f"{semantic_change['gates'][0]['note']} (semantic delta)"
    semantic_change_hash = _oracle_manifest_content_hash(semantic_change)
    assert semantic_change_hash != base_hash

    changed_hash_field_only = copy.deepcopy(base)
    changed_hash_field_only["manifest_content_hash"] = "f" * 64
    assert _oracle_manifest_content_hash(changed_hash_field_only) == base_hash


def test_rseg_ac04_implementation_hash_matches_oracle_and_hash_errors_on_mismatch(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _read_committed_manifest_mapping()
    base = _with_valid_manifest_hash(base)
    expected = _oracle_manifest_content_hash(base)

    lf_manifest_path = _write_manifest(tmp_path, "lf_manifest.yaml", base, line_ending="\n")
    crlf_manifest_path = _write_manifest(tmp_path, "crlf_manifest.yaml", base, line_ending="\r\n")

    lf_mapping = yaml.safe_load(lf_manifest_path.read_text(encoding="utf-8"))
    crlf_mapping = yaml.safe_load(crlf_manifest_path.read_text(encoding="utf-8"))
    assert api.entry_gate_manifest_content_hash(lf_mapping) == expected
    assert api.entry_gate_manifest_content_hash(crlf_mapping) == expected

    loaded_lf = api.load_entry_gate_manifest(lf_manifest_path)
    loaded_crlf = api.load_entry_gate_manifest(crlf_manifest_path)
    assert loaded_lf.manifest_content_hash == expected
    assert loaded_crlf.manifest_content_hash == expected

    mismatched_hash = copy.deepcopy(base)
    mismatched_hash["manifest_content_hash"] = "0" * 64
    with pytest.raises(api.RescueScreenHashError):
        api.load_entry_gate_manifest(_write_manifest(tmp_path, "mismatched_hash.yaml", mismatched_hash))


def test_rseg_immutable_loaded_models_are_frozen_dataclasses_and_tuples(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    base = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    loaded = api.load_entry_gate_manifest(_write_manifest(tmp_path, "immutable_manifest.yaml", base))

    assert dataclasses.is_dataclass(loaded)
    assert isinstance(loaded.gates, tuple)
    assert loaded.gates
    assert all(dataclasses.is_dataclass(gate) for gate in loaded.gates)
    assert all(isinstance(gate.evidence_refs, tuple) for gate in loaded.gates)

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        loaded.lane_id = "tampered"
    with pytest.raises((AttributeError, TypeError)):
        loaded.gates.append(loaded.gates[0])

    first_gate = loaded.gates[0]
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        first_gate.status = "NOT_SATISFIED"
    with pytest.raises((AttributeError, TypeError)):
        first_gate.evidence_refs.append(first_gate.evidence_refs[0])

    first_ref = first_gate.evidence_refs[0]
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        first_ref.reviewed_by = "tampered"


def test_rseg_ac05_ac06_committed_manifest_reports_blocked_with_eg1_first_blocking() -> None:
    api = _require_rescuescreen_api()
    loaded_manifest = api.load_entry_gate_manifest(_require_committed_manifest_path())
    report = api.evaluate_entry_gates(loaded_manifest)
    report_dict = api.entry_gate_report_to_dict(report)

    assert report_dict["schema"] == "rescuescreen.entry_gate_status.v1"
    assert report_dict["overall_status"] == "BLOCKED"
    assert report_dict["first_blocking_gate"] == "EG-1"
    assert report_dict["blocking_fail_state"] == "MECHANISM_UNVERIFIED"
    assert list(report_dict["blocking_gates"]) == list(CANONICAL_GATE_ORDER)
    assert report_dict["eligible_next_stage"] is None
    assert report_dict["stage_execution_authorized"] is False

    gate_rows = report_dict["gates"]
    assert [row["gate_id"] for row in gate_rows] == list(CANONICAL_GATE_ORDER)
    for row in gate_rows:
        assert row["status"] == "NOT_SATISFIED"
        assert row["fail_state"] == CANONICAL_FAIL_STATE_BY_GATE[row["gate_id"]]


def test_rseg_ac06_partial_pass_never_yields_readiness_and_preserves_blocking_order(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    fixture = _all_satisfied_manifest_from(_read_committed_manifest_mapping())

    for gate in fixture["gates"][3:]:
        gate["status"] = "NOT_SATISFIED"
        gate["evidence_refs"] = []
    fixture = _with_valid_manifest_hash(fixture)

    loaded = api.load_entry_gate_manifest(_write_manifest(tmp_path, "partial_pass.yaml", fixture))
    report_dict = api.entry_gate_report_to_dict(api.evaluate_entry_gates(loaded))

    assert report_dict["overall_status"] == "BLOCKED"
    assert report_dict["first_blocking_gate"] == "EG-4"
    assert report_dict["blocking_fail_state"] == CANONICAL_FAIL_STATE_BY_GATE["EG-4"]
    assert list(report_dict["blocking_gates"]) == ["EG-4", "EG-5"]
    assert report_dict["eligible_next_stage"] is None
    assert report_dict["stage_execution_authorized"] is False

    input_statuses = [gate.status for gate in loaded.gates]
    output_statuses = [row["status"] for row in report_dict["gates"]]
    assert output_statuses == input_statuses


def test_rseg_ac07_all_satisfied_fixture_is_ready_for_s1_review_but_never_authorized(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    all_satisfied = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    loaded = api.load_entry_gate_manifest(_write_manifest(tmp_path, "all_satisfied.yaml", all_satisfied))
    report_dict = api.entry_gate_report_to_dict(api.evaluate_entry_gates(loaded))

    assert report_dict["overall_status"] == "READY_FOR_S1_REVIEW"
    assert report_dict["eligible_next_stage"] == "S1"
    assert report_dict["stage_execution_authorized"] is False
    assert report_dict["first_blocking_gate"] is None
    assert report_dict["blocking_fail_state"] is None
    assert list(report_dict["blocking_gates"]) == []

    gate_rows = report_dict["gates"]
    assert [row["gate_id"] for row in gate_rows] == list(CANONICAL_GATE_ORDER)
    assert all(row["status"] == "SATISFIED" for row in gate_rows)


def test_rseg_evaluation_canonical_json_is_deterministic_for_identical_input(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()
    manifest = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    manifest_path = _write_manifest(tmp_path, "deterministic_eval.yaml", manifest)

    loaded_a = api.load_entry_gate_manifest(manifest_path)
    loaded_b = api.load_entry_gate_manifest(manifest_path)
    report_a = api.entry_gate_report_to_dict(api.evaluate_entry_gates(loaded_a))
    report_b = api.entry_gate_report_to_dict(api.evaluate_entry_gates(loaded_b))

    assert _report_canonical_bytes(report_a) == _report_canonical_bytes(report_b)


def test_rseg_ac08_loader_rejects_missing_nonregular_and_symlink_paths(tmp_path: Path) -> None:
    api = _require_rescuescreen_api()

    missing_path = tmp_path / "missing.yaml"
    with pytest.raises(api.RescueScreenPathError):
        api.load_entry_gate_manifest(missing_path)

    with pytest.raises(api.RescueScreenPathError):
        api.load_entry_gate_manifest(tmp_path)

    valid_manifest = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    target_path = _write_manifest(tmp_path, "symlink_target.yaml", valid_manifest)
    symlink_path = tmp_path / "symlink_manifest.yaml"
    try:
        symlink_path.symlink_to(target_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable in this environment")

    with pytest.raises(api.RescueScreenPathError):
        api.load_entry_gate_manifest(symlink_path)


def test_rseg_ac08_loader_never_opens_evidence_reference_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _require_rescuescreen_api()
    manifest = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    forbidden_evidence_target = tmp_path / "forbidden_evidence_target.txt"
    forbidden_evidence_target.write_text("must never be opened by entry-gate loader", encoding="utf-8")
    manifest["gates"][0]["evidence_refs"][0]["artifact_id"] = str(forbidden_evidence_target)
    manifest = _with_valid_manifest_hash(manifest)

    manifest_path = _write_manifest(tmp_path, "no_evidence_open.yaml", manifest)
    opened_paths: list[Path] = []
    real_open = builtins.open
    forbidden_resolved = forbidden_evidence_target.resolve()

    def guarded_open(file: Any, *args: Any, **kwargs: Any):
        try:
            candidate = Path(file)
        except TypeError:
            return real_open(file, *args, **kwargs)

        resolved = candidate.resolve(strict=False)
        if resolved == forbidden_resolved:
            raise AssertionError(f"evidence target was opened: {resolved}")
        opened_paths.append(resolved)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    loaded = api.load_entry_gate_manifest(manifest_path)
    assert loaded.manifest_content_hash == manifest["manifest_content_hash"]
    assert forbidden_resolved not in opened_paths
