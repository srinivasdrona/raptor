from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-kickoff.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"


def _first_slice_spec() -> dict[str, Any]:
    kickoff = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(kickoff, dict) or not isinstance(kickoff.get("first_implementation_slice"), dict):
        pytest.fail("Kickoff spec must include first_implementation_slice")
    return kickoff["first_implementation_slice"]


def _inventory_spec() -> dict[str, Any]:
    inventory = _first_slice_spec().get("initial_repository_inventory")
    if not isinstance(inventory, dict):
        pytest.fail("initial_repository_inventory missing from kickoff spec")
    return inventory


def _record_ids_from_spec() -> list[str]:
    ids = _inventory_spec().get("minimum_top_level_registry_records")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        pytest.fail("minimum_top_level_registry_records must be a list[str]")
    return ids


def _root_paths_from_spec() -> list[str]:
    roots = _inventory_spec().get("exact_roots")
    if not isinstance(roots, list):
        pytest.fail("exact_roots must be a list")
    paths: list[str] = []
    for root in roots:
        if not isinstance(root, dict) or not isinstance(root.get("path"), str):
            pytest.fail("each exact_roots item must include path")
        paths.append(root["path"].replace("\\", "/"))
    return paths


def _load_registry_payload() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("SourceOps registry must parse into a mapping")
    return payload


def _load_root_yaml(rel_path: str) -> dict[str, Any]:
    root_path = REPO_ROOT / rel_path
    loaded = yaml.safe_load(root_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail(f"authoritative root must parse into mapping: {rel_path}")
    return loaded


def _canonical_registry_hash(payload: dict[str, Any]) -> str:
    basis = copy.deepcopy(payload)
    basis.pop("registry_content_hash", None)
    canonical = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _run_validate(registry_path: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli("validate", "--registry", str(registry_path))


def _run_status(registry_path: Path, consumer_id: str) -> subprocess.CompletedProcess[str]:
    return _run_cli("status", "--registry", str(registry_path), "--consumer", consumer_id)


def _parse_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "CLI stdout must contain JSON.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        pytest.fail("CLI JSON payload must be an object")
    return payload


def _error_codes(report: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    if isinstance(report.get("errors"), list):
        for err in report["errors"]:
            if isinstance(err, dict) and isinstance(err.get("code"), str):
                codes.add(err["code"])
    if isinstance(report.get("error"), dict) and isinstance(report["error"].get("code"), str):
        codes.add(report["error"]["code"])
    for key in ("code", "error_code", "failure_code"):
        value = report.get(key)
        if isinstance(value, str):
            codes.add(value)
    return {code for code in codes if code}


def _iter_declaration_paths(payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    source_records = payload.get("source_records")
    if isinstance(source_records, list):
        for record in source_records:
            if not isinstance(record, dict):
                continue
            refs = record.get("declaration_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                        found.append(ref["path"].replace("\\", "/"))
    exclusions = payload.get("coverage_exclusions")
    if isinstance(exclusions, list):
        for exclusion in exclusions:
            if isinstance(exclusion, dict) and isinstance(exclusion.get("declaration_path"), str):
                found.append(exclusion["declaration_path"].replace("\\", "/"))
    return found


def _source_record_by_id(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if isinstance(record, dict) and record.get("source_id") == source_id:
            return record
    pytest.fail(f"source_id {source_id!r} not found")


def _consumer_by_id(payload: dict[str, Any], consumer_id: str) -> dict[str, Any] | None:
    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("consumers must be a list")
    for consumer in consumers:
        if isinstance(consumer, dict) and consumer.get("consumer_id") == consumer_id:
            return consumer
    return None


def _consumer_state(report: dict[str, Any]) -> str | None:
    state = report.get("consumer_state")
    if isinstance(state, str):
        return state
    consumer = report.get("consumer")
    if isinstance(consumer, dict) and isinstance(consumer.get("state"), str):
        return consumer["state"]
    return None


def _components(record: dict[str, Any]) -> list[dict[str, Any]]:
    components = record.get("components")
    if components is None:
        return []
    if not isinstance(components, list):
        pytest.fail(f"components must be a list for source_id={record.get('source_id')!r}")
    rows = [row for row in components if isinstance(row, dict)]
    assert len(rows) == len(components), f"all components must be mappings for source_id={record.get('source_id')!r}"
    return rows


def _components_with_locator_token(record: dict[str, Any], token: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for component in _components(record):
        locator = component.get("declaration_locator")
        if isinstance(locator, str) and token in locator:
            hits.append(component)
    return hits


def _iter_accounted_declaration_locators(payload: dict[str, Any]) -> list[str]:
    accounted: list[str] = []
    records = payload.get("source_records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            for component in _components(record):
                locator = component.get("declaration_locator")
                if isinstance(locator, str) and locator.strip():
                    accounted.append(locator.replace("\\", "/"))
    exclusions = payload.get("coverage_exclusions")
    if isinstance(exclusions, list):
        for exclusion in exclusions:
            if not isinstance(exclusion, dict):
                continue
            path = str(exclusion.get("declaration_path", "")).replace("\\", "/").strip()
            locator = str(exclusion.get("declaration_locator", "")).strip()
            if not locator:
                continue
            if "#" in locator:
                accounted.append(locator.replace("\\", "/"))
            elif path:
                accounted.append(f"{path}#{locator}")
    return accounted


def _is_pending_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower().replace("_", "-")
    return any(marker in lowered for marker in ("confirm-pending", "pending", "unconfirmed", "blocked", "unknown"))


def _components_for_exact_locator(payload: dict[str, Any], locator: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    normalized = locator.replace("\\", "/").strip()
    hits: list[tuple[dict[str, Any], dict[str, Any]]] = []
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if not isinstance(record, dict):
            continue
        for component in _components(record):
            raw_locator = component.get("declaration_locator")
            if isinstance(raw_locator, str) and raw_locator.replace("\\", "/").strip() == normalized:
                hits.append((record, component))
    return hits


def _component_by_id(record: dict[str, Any], component_id: str) -> dict[str, Any]:
    for component in _components(record):
        if component.get("component_id") == component_id:
            return component
    pytest.fail(f"component_id {component_id!r} missing for source_id={record.get('source_id')!r}")


def _parse_locator_tokens(pointer: str) -> list[tuple[str, str | int]]:
    if not pointer:
        raise ValueError("empty declaration pointer")

    # Accept JSON-pointer spelling so tests do not mandate one locator grammar.
    if pointer.startswith("/"):
        segments = pointer.split("/")[1:]
        if not segments:
            raise ValueError("empty JSON-pointer")
        return [("key", segment.replace("~1", "/").replace("~0", "~")) for segment in segments]

    tokens: list[tuple[str, str | int]] = []
    index = 0
    expect_next_token = True
    while index < len(pointer):
        char = pointer[index]
        if char == ".":
            if expect_next_token:
                raise ValueError(f"empty pointer token in {pointer!r}")
            expect_next_token = True
            index += 1
            continue
        if char == "[":
            end = pointer.find("]", index + 1)
            if end == -1:
                raise ValueError(f"unclosed bracket token in {pointer!r}")
            raw = pointer[index + 1 : end].strip()
            if not raw:
                raise ValueError(f"empty bracket token in {pointer!r}")
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
                tokens.append(("key", raw[1:-1]))
            elif raw.isdigit():
                tokens.append(("index", int(raw)))
            else:
                tokens.append(("key", raw))
            expect_next_token = False
            index = end + 1
            continue

        start = index
        while index < len(pointer) and pointer[index] not in ".[":
            index += 1
        token = pointer[start:index].strip()
        if not token:
            raise ValueError(f"empty pointer token in {pointer!r}")
        tokens.append(("key", token))
        expect_next_token = False

    if expect_next_token:
        raise ValueError(f"pointer cannot end with a separator in {pointer!r}")
    return tokens


def _try_resolve_declaration_locator_value(locator: str) -> tuple[bool, Any]:
    declaration_path, sep, pointer = locator.replace("\\", "/").partition("#")
    if not sep or not declaration_path or not pointer:
        return False, f"declaration locator must include '<path>#<pointer>': {locator!r}"

    current: Any = _load_root_yaml(declaration_path)
    try:
        tokens = _parse_locator_tokens(pointer)
    except ValueError as exc:
        return False, str(exc)

    for token_kind, token_value in tokens:
        if token_kind == "index":
            if not isinstance(current, list):
                return False, f"declaration locator index {token_value} requires a list in {locator!r}"
            if token_value >= len(current):
                return False, f"declaration locator index {token_value} out of range in {locator!r}"
            current = current[token_value]
            continue

        key = str(token_value)
        if isinstance(current, list) and key.isdigit():
            resolved_index = int(key)
            if resolved_index >= len(current):
                return False, f"declaration locator index {resolved_index} out of range in {locator!r}"
            current = current[resolved_index]
            continue
        if not isinstance(current, dict) or key not in current:
            return False, f"declaration locator token {key!r} missing in {locator!r}"
        current = current[key]

    return True, current


def _resolve_declaration_locator_value(locator: str) -> Any:
    resolved, value_or_error = _try_resolve_declaration_locator_value(locator)
    if not resolved:
        pytest.fail(str(value_or_error))
    return value_or_error


def _append_coverage_exclusion(
    payload: dict[str, Any],
    *,
    exclusion_id: str,
    declaration_path: str,
    declaration_locator: str,
    owner: str,
    reason: str,
    review_condition: str,
) -> None:
    exclusions = payload.get("coverage_exclusions")
    if not isinstance(exclusions, list):
        pytest.fail("coverage_exclusions must be a list")
    exclusions.append(
        {
            "exclusion_id": exclusion_id,
            "declaration_path": declaration_path,
            "declaration_locator": declaration_locator,
            "owner": owner,
            "reason": reason,
            "review_condition": review_condition,
        }
    )


def _remove_component_by_locator(payload: dict[str, Any], *, source_id: str, locator: str) -> None:
    source = _source_record_by_id(payload, source_id)
    components = source.get("components")
    if not isinstance(components, list):
        pytest.fail(f"{source_id} components must be a list")
    normalized = locator.replace("\\", "/").strip()
    removed = False
    kept: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            pytest.fail(f"{source_id} component rows must be mappings")
        raw_locator = component.get("declaration_locator")
        if (
            not removed
            and isinstance(raw_locator, str)
            and raw_locator.replace("\\", "/").strip() == normalized
        ):
            removed = True
            continue
        kept.append(component)
    assert removed, f"could not remove component for locator {locator!r} on source {source_id!r}"
    source["components"] = kept


def test_ac03_exact_seven_records_ids_and_declaration_roots() -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    assert isinstance(records, list), "source_records must be a list"

    expected_ids = _record_ids_from_spec()
    expected_roots = set(_root_paths_from_spec())
    expected_count = _inventory_spec().get("expected_record_count")
    assert isinstance(expected_count, int)

    assert len(records) == expected_count, f"expected exactly {expected_count} top-level source_records, got {len(records)}"
    record_ids = [record.get("source_id") for record in records if isinstance(record, dict)]
    assert record_ids == expected_ids

    declaration_paths = set(_iter_declaration_paths(payload))
    assert expected_roots.issubset(declaration_paths), (
        f"Missing declaration roots: {sorted(expected_roots - declaration_paths)}"
    )
    rooted = {path for path in declaration_paths if path in expected_roots}
    assert len(rooted) == expected_count, (
        f"expected exactly {expected_count} repository declaration roots, got {len(rooted)}"
    )


def test_ac03_consumers_match_in_scope_and_reserved_contract() -> None:
    payload = _load_registry_payload()
    first_slice = _first_slice_spec()
    consumers = payload.get("consumers")
    assert isinstance(consumers, list) and consumers, "consumers must be non-empty"
    actual_ids = {consumer.get("consumer_id") for consumer in consumers if isinstance(consumer, dict)}

    in_scope = set(first_slice.get("consumers_in_scope", []))
    reserved = set(first_slice.get("consumers_reserved_but_not_activatable", []))
    assert in_scope, "consumers_in_scope must be declared in kickoff spec"
    assert reserved, "consumers_reserved_but_not_activatable must be declared in kickoff spec"
    assert in_scope.issubset(actual_ids), f"missing in-scope consumers: {sorted(in_scope - actual_ids)}"
    assert reserved.issubset(actual_ids), f"missing reserved consumers: {sorted(reserved - actual_ids)}"


def test_ac03_baseline_records_are_lineage_roots_with_null_predecessors() -> None:
    payload = _load_registry_payload()
    for source_id in _record_ids_from_spec():
        record = _source_record_by_id(payload, source_id)
        rollback = record.get("rollback")
        assert isinstance(rollback, dict), f"{source_id} rollback must be mapping"
        predecessor = rollback.get("predecessor_source_id")
        assert predecessor is None, (
            f"{source_id} is a baseline authoritative-root record and must not fabricate cross-source predecessor {predecessor!r}"
        )
        origin_reason = rollback.get("origin_reason")
        assert isinstance(origin_reason, str) and origin_reason.strip(), (
            f"{source_id} null predecessor must carry a concrete non-blank origin_reason"
        )


def test_ac04_authoritative_roots_have_exact_nested_fact_accounting() -> None:
    payload = _load_registry_payload()
    record_ids = _record_ids_from_spec()
    root_paths = _root_paths_from_spec()
    id_to_root = dict(zip(record_ids, root_paths, strict=True))

    ingest_record = _source_record_by_id(payload, "tsc-ingest-and-reference-declarations")
    ingest_root = _load_root_yaml(id_to_root["tsc-ingest-and-reference-declarations"])
    checksum_components = _components_with_locator_token(ingest_record, "reference_checksums")
    assert len(checksum_components) == len(ingest_root.get("reference_checksums", {})) == 4
    for token in ("clinvar_snapshot_id", "assembly", "mane_release"):
        assert _components_with_locator_token(ingest_record, token), (
            f"ingest declaration accounting must include {token}"
        )
    pending_locators = [
        "clinvar_snapshot_id",
        "clinvar_snapshot_date",
        "clinvar_snapshot_file_checksum",
        "NM_000548.5",
        "NM_000368.5",
    ]
    assert _is_pending_marker(ingest_root.get("clinvar_snapshot_id"))
    assert _is_pending_marker(ingest_root.get("clinvar_snapshot_date"))
    assert _is_pending_marker(ingest_root.get("clinvar_snapshot_file_checksum"))
    for tx in ("NM_000548.5", "NM_000368.5"):
        assert _is_pending_marker((ingest_root.get("reference_checksums") or {}).get(tx))
    assert ingest_record.get("lifecycle_state") not in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}, (
        "ingest record cannot be VERIFIED_ACTIVE/PINNED_HISTORICAL while ClinVar/MANE/transcript pins remain confirm-pending"
    )
    for locator in pending_locators:
        matches = _components_with_locator_token(ingest_record, locator)
        assert matches, f"ingest pending declaration {locator!r} must have explicit component accounting"
        for component in matches:
            assert component.get("lifecycle_state") == "CONFIRM_PENDING", (
                f"component {component.get('component_id')!r} for {locator!r} must remain CONFIRM_PENDING"
            )
            assert _is_pending_marker(component.get("version_or_snapshot")), (
                f"component {component.get('component_id')!r} must retain pending version metadata for {locator!r}"
            )
            assert _is_pending_marker(component.get("licence_status")), (
                f"component {component.get('component_id')!r} must retain pending licence metadata for {locator!r}"
            )

    core_record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    core_root = _load_root_yaml(id_to_root["frozen-core-annotation-bundle"])
    assert core_record.get("lifecycle_state") == "PINNED_HISTORICAL"
    assert core_root.get("status") == "pinned_historical_evidence"
    assert len(_components_with_locator_token(core_record, "data_sources")) == len(core_root.get("data_sources", [])) == 28
    assert _components_with_locator_token(core_record, "annotator"), "core runtime annotator pin must be accounted"
    assert _components_with_locator_token(core_record, "bias_version"), "core runtime BIAS version pin must be accounted"
    readiness = core_root.get("readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("reuse_readiness") != readiness.get("reannotation_readiness")
    reuse_path = (core_root.get("reuse_vs_reannotate") or {}).get("reuse_path", {})
    assert isinstance(reuse_path, dict)
    assert reuse_path.get("current_route") == "BLOCKED_POLICY_IMPLEMENTATION"
    core_licence = core_record.get("licence")
    assert isinstance(core_licence, dict), "frozen core bundle must carry structured licence state"
    permitted_use = str(core_licence.get("permitted_use", "")).lower().replace("-", "_")
    assert "policy_only_reuse" not in permitted_use or any(
        marker in permitted_use for marker in ("blocked", "pending", "historical", "reference_only")
    ), (
        "frozen core bundle cannot claim policy_only_reuse as currently permitted while route remains blocked"
    )

    pp3_record = _source_record_by_id(payload, "pp3bp4-shadow-source-register")
    pp3_root = _load_root_yaml(id_to_root["pp3bp4-shadow-source-register"])
    primary_components = _components_with_locator_token(pp3_record, "required_primary_sources")
    candidate_components = _components_with_locator_token(pp3_record, "candidates")
    assert len(primary_components) == len(pp3_root.get("required_primary_sources", {})) == 4
    assert len(candidate_components) == len(pp3_root.get("candidates", {})) == 5
    assert all(
        component.get("lifecycle_state") != "VERIFIED_ACTIVE" for component in candidate_components
    ), "shadow/candidate PP3/BP4 rows cannot be activated"

    mave_record = _source_record_by_id(payload, "tsc2-mave-source-register")
    mave_root = _load_root_yaml(id_to_root["tsc2-mave-source-register"])
    mave_components = _components_with_locator_token(mave_record, "sources")
    assert len(mave_components) == len(mave_root.get("sources", [])) == 4
    expected_verified = sum(
        1 for row in mave_root.get("sources", []) if isinstance(row, dict) and row.get("verification") == "verified"
    )
    expected_pending = sum(
        1
        for row in mave_root.get("sources", [])
        if isinstance(row, dict) and row.get("verification") == "confirm_pending"
    )
    observed_verified = sum(1 for row in mave_components if row.get("lifecycle_state") == "VERIFIED_ACTIVE")
    observed_pending = sum(1 for row in mave_components if row.get("lifecycle_state") == "CONFIRM_PENDING")
    assert observed_verified == expected_verified
    assert observed_pending == expected_pending

    forbidden_consumers = set((mave_root.get("circularity_guard") or {}).get("forbidden_consumers", []))
    consumer_map = {
        consumer.get("consumer_id"): consumer for consumer in payload.get("consumers", []) if isinstance(consumer, dict)
    }
    mapped = {
        "scorer": "scorer",
        "eval.benchmark": "eval-benchmark",
        "eval.gate": "eval-gate",
        "external.mave": "external-mave",
    }
    for marker, consumer_id in mapped.items():
        if any(marker in forbidden for forbidden in forbidden_consumers) and consumer_id in consumer_map:
            required = consumer_map[consumer_id].get("required_sources")
            assert isinstance(required, list)
            assert "tsc2-mave-source-register" not in required, (
                f"mave circularity_guard forbids {consumer_id} consumption of external MAVE register"
            )

    pack_record = _source_record_by_id(payload, "atlas-tsc2-pack-source-pins")
    pack_root = _load_root_yaml(id_to_root["atlas-tsc2-pack-source-pins"])
    pack_components = _components_with_locator_token(pack_record, "source_register_pins")
    assert len(pack_components) == len(pack_root.get("source_register_pins", [])) == 3
    assert all(component.get("source_role") == "provenance_only" for component in pack_components)

    catalog_record = _source_record_by_id(payload, "atlas-tsc2-catalog-template")
    catalog_root = _load_root_yaml(id_to_root["atlas-tsc2-catalog-template"])
    assert catalog_record.get("record_kind") == "METADATA_CATALOG_TEMPLATE"
    assert catalog_record.get("lifecycle_state") == "METADATA_ONLY"
    assert len(_components(catalog_record)) == len(catalog_root.get("sources", [])) == 0
    refs = catalog_record.get("declaration_refs")
    assert isinstance(refs, list) and refs
    for ref in refs:
        assert isinstance(ref, dict)
        path_value = ref.get("path")
        assert isinstance(path_value, str)
        lowered = path_value.lower()
        assert "://" not in lowered and not lowered.startswith(("file:", "http:", "https:"))

    acmg_record = _source_record_by_id(payload, "tsc-acmg-runtime-source-pins")
    acmg_root = _load_root_yaml(id_to_root["tsc-acmg-runtime-source-pins"])
    assert isinstance(acmg_root.get("bias_version"), str) and "confirm-pending" in acmg_root["bias_version"]
    assert isinstance(acmg_root.get("bias_data_version"), str) and "confirm-pending" in acmg_root["bias_data_version"]
    assert _components_with_locator_token(acmg_record, "bias_version"), "acmg bias_version pin must be accounted"
    assert _components_with_locator_token(acmg_record, "bias_data_version"), "acmg bias_data_version pin must be accounted"
    for component in _components_with_locator_token(acmg_record, "bias_"):
        assert component.get("lifecycle_state") == "CONFIRM_PENDING"
    assert isinstance(acmg_root.get("licensing"), dict) and acmg_root.get("licensing"), (
        "authoritative ACMG root must carry licensing tag metadata"
    )
    licence_metadata_views: list[str] = []
    top_level_licence = acmg_record.get("licence")
    if isinstance(top_level_licence, dict):
        licence_metadata_views.extend(
            str(value).lower() for value in top_level_licence.values() if isinstance(value, str)
        )
    for component in _components_with_locator_token(acmg_record, "licensing."):
        assert component.get("lifecycle_state") != "VERIFIED_ACTIVE", (
            "ACMG licensing-tag components must remain non-verified/fail-closed"
        )
        for key in ("licence_status", "display_name", "version_or_snapshot", "declaration_locator"):
            value = component.get(key)
            if isinstance(value, str):
                licence_metadata_views.append(value.lower())
    if not _components_with_locator_token(acmg_record, "licensing."):
        exclusions = payload.get("coverage_exclusions")
        assert isinstance(exclusions, list), "coverage_exclusions must be present when licensing tags are excluded"
        licensing_exclusions = [
            row
            for row in exclusions
            if isinstance(row, dict)
            and str(row.get("declaration_path", "")).replace("\\", "/") == "configs/acmg/tsc.yaml"
            and "licensing" in str(row.get("declaration_locator", "")).lower()
        ]
        assert licensing_exclusions, (
            "if ACMG licensing tags are not represented as components they must be explicitly excluded with review metadata"
        )
        for row in licensing_exclusions:
            reason = str(row.get("reason", "")).lower()
            assert any(term in reason for term in ("pending", "review", "confirm", "blocked")), (
                "ACMG licensing exclusions must stay fail-closed and review-bound"
            )
    assert licence_metadata_views, (
        "registry must carry ACMG licence metadata without requiring one component row per licensing tag"
    )
    assert any(_is_pending_marker(value) for value in licence_metadata_views), (
        "licensing metadata must remain fail-closed and review-bound until independently verified"
    )


def test_ac04_source_like_declarations_are_uniquely_accounted_or_excluded() -> None:
    payload = _load_registry_payload()
    accounted = _iter_accounted_declaration_locators(payload)

    # Source/version/pin/licensing declarations that materially define source identity
    # and readiness semantics across the seven authoritative roots.
    required_locators = [
        "configs/ingest/tsc.yaml#assembly_patch",
        "configs/ingest/tsc.yaml#normalizer.version",
        "configs/ingest/tsc.yaml#TSC1.protein_accession",
        "configs/ingest/tsc.yaml#TSC2.protein_accession",
        "configs/eval/core_annotation_bundle.yaml#runtime.annotator",
        "configs/eval/core_annotation_bundle.yaml#runtime.bias_version",
        "configs/eval/core_annotation_bundle.yaml#runtime.nirvana_data_version",
        "configs/external/mave_sources.yaml#sources[0]",
        "configs/atlas/packs/tsc2/pack.yaml#assembly_pins[0]",
        "configs/atlas/packs/tsc2/pack.yaml#transcript_pins[0]",
        "configs/acmg/tsc.yaml#genes.TSC1",
        "configs/acmg/tsc.yaml#genes.TSC2",
        "configs/acmg/tsc.yaml#licensing.revel",
    ]

    for locator in required_locators:
        count = sum(1 for item in accounted if item == locator)
        assert count == 1, (
            f"{locator} must be represented exactly once by a component locator or explicit coverage exclusion; "
            f"observed {count}"
        )


def test_ac04_declaration_fact_fidelity_preserves_authoritative_values_without_placeholder_substitution() -> None:
    payload = _load_registry_payload()
    permissive_states = {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}
    mismatches: list[str] = []

    concrete_value_probes = [
        ("configs/ingest/tsc.yaml#assembly_patch", ("version_or_snapshot",)),
        ("configs/ingest/tsc.yaml#normalizer.version", ("version_or_snapshot",)),
        ("configs/ingest/tsc.yaml#TSC1.protein_accession", ("version_or_snapshot",)),
        ("configs/ingest/tsc.yaml#TSC2.protein_accession", ("version_or_snapshot",)),
        ("configs/eval/core_annotation_bundle.yaml#runtime.nirvana_data_version", ("version_or_snapshot",)),
        ("configs/acmg/tsc.yaml#genes.TSC1", ("version_or_snapshot",)),
        ("configs/acmg/tsc.yaml#genes.TSC2", ("version_or_snapshot",)),
        ("configs/acmg/tsc.yaml#licensing.revel", ("version_or_snapshot", "licence_status")),
        ("configs/acmg/tsc.yaml#licensing.cadd", ("version_or_snapshot", "licence_status")),
        ("configs/acmg/tsc.yaml#licensing.splice_ai", ("version_or_snapshot", "licence_status")),
        ("configs/acmg/tsc.yaml#licensing.alpha_missense", ("version_or_snapshot", "licence_status")),
        ("configs/acmg/tsc.yaml#licensing.gnomad", ("version_or_snapshot", "licence_status")),
    ]
    for locator, fields in concrete_value_probes:
        matches = _components_for_exact_locator(payload, locator)
        if len(matches) != 1:
            mismatches.append(f"{locator} must map to exactly one component row; observed {len(matches)}")
            continue
        _, component = matches[0]
        declared_value = _resolve_declaration_locator_value(locator)
        declared_text = str(declared_value).strip()
        if _is_pending_marker(declared_text):
            mismatches.append(f"{locator} declaration is pending; probe requires concrete declaration fact")
            continue
        observed_values: list[str] = []
        for field in fields:
            value = component.get(field)
            if isinstance(value, str) and value.strip():
                observed_values.append(value.strip())
        if not observed_values:
            mismatches.append(f"{locator} component has no non-empty values in fields {fields}")
            continue
        if any(_is_pending_marker(value) for value in observed_values):
            mismatches.append(
                f"{locator} uses pending placeholder metadata {observed_values!r} despite concrete declaration {declared_text!r}"
            )
        if declared_text not in observed_values:
            mismatches.append(
                f"{locator} declaration value {declared_text!r} must be preserved in component metadata; got {observed_values!r}"
            )

    pending_value_probes = [
        "configs/ingest/tsc.yaml#clinvar_snapshot_id",
        "configs/acmg/tsc.yaml#bias_version",
        "configs/acmg/tsc.yaml#bias_data_version",
    ]
    for locator in pending_value_probes:
        matches = _components_for_exact_locator(payload, locator)
        if len(matches) != 1:
            mismatches.append(f"{locator} must map to exactly one component row; observed {len(matches)}")
            continue
        _, component = matches[0]
        declared_value = _resolve_declaration_locator_value(locator)
        declared_text = str(declared_value).strip()
        if not _is_pending_marker(declared_text):
            mismatches.append(f"{locator} probe expects authoritative confirm-pending declaration; got {declared_text!r}")
            continue
        lifecycle_state = component.get("lifecycle_state")
        if lifecycle_state in permissive_states:
            mismatches.append(
                f"{locator} is confirm-pending in declaration but component lifecycle is permissive {lifecycle_state!r}"
            )

    assert not mismatches, "Declaration-fact fidelity violations:\n" + "\n".join(mismatches)


def test_ac04_runtime_and_checksum_component_locators_resolve_authoritative_semantics() -> None:
    payload = _load_registry_payload()
    ingest_root = _load_root_yaml("configs/ingest/tsc.yaml")
    core_root = _load_root_yaml("configs/eval/core_annotation_bundle.yaml")
    runtime = core_root.get("runtime")
    checksums = ingest_root.get("reference_checksums")
    assert isinstance(runtime, dict) and isinstance(checksums, dict), (
        "authoritative runtime and checksum mappings must exist for semantic locator fidelity probes"
    )

    expected_targets = [
        (
            "frozen-core-annotation-bundle",
            "core-runtime-nirvana",
            "configs/eval/core_annotation_bundle.yaml",
            runtime.get("annotator"),
        ),
        (
            "frozen-core-annotation-bundle",
            "core-runtime-bias",
            "configs/eval/core_annotation_bundle.yaml",
            runtime.get("bias_version"),
        ),
        (
            "tsc-ingest-and-reference-declarations",
            "tsc-ingest-reference-checksum-NC_000016.10",
            "configs/ingest/tsc.yaml",
            checksums.get("NC_000016.10"),
        ),
        (
            "tsc-ingest-and-reference-declarations",
            "tsc-ingest-reference-checksum-NC_000009.12",
            "configs/ingest/tsc.yaml",
            checksums.get("NC_000009.12"),
        ),
        (
            "tsc-ingest-and-reference-declarations",
            "tsc-ingest-reference-checksum-NM_000548.5",
            "configs/ingest/tsc.yaml",
            checksums.get("NM_000548.5"),
        ),
        (
            "tsc-ingest-and-reference-declarations",
            "tsc-ingest-reference-checksum-NM_000368.5",
            "configs/ingest/tsc.yaml",
            checksums.get("NM_000368.5"),
        ),
    ]
    assert len(expected_targets) == 6

    mismatches: list[str] = []
    for source_id, component_id, expected_path, expected_declared_value in expected_targets:
        if expected_declared_value is None:
            mismatches.append(
                f"{source_id}/{component_id}: authoritative declaration value is missing for expected semantic target"
            )
            continue
        record = _source_record_by_id(payload, source_id)
        component = _component_by_id(record, component_id)
        locator = component.get("declaration_locator")
        if not isinstance(locator, str) or not locator.strip():
            mismatches.append(f"{source_id}/{component_id}: declaration_locator must be a non-empty string")
            continue

        normalized_locator = locator.replace("\\", "/").strip()
        declaration_path, sep, _ = normalized_locator.partition("#")
        if not sep:
            mismatches.append(f"{source_id}/{component_id}: locator must include '#': {locator!r}")
            continue
        if declaration_path != expected_path:
            mismatches.append(
                f"{source_id}/{component_id}: locator path must be {expected_path!r}; got {declaration_path!r}"
            )

        resolved, resolved_or_error = _try_resolve_declaration_locator_value(locator)
        if not resolved:
            mismatches.append(f"{source_id}/{component_id}: unresolved locator {locator!r}: {resolved_or_error}")
            continue

        declared_text = str(expected_declared_value).strip()
        resolved_text = str(resolved_or_error).strip()
        if resolved_text != declared_text:
            mismatches.append(
                f"{source_id}/{component_id}: locator resolves to {resolved_text!r}, expected {declared_text!r}"
            )

        stored_value = str(component.get("version_or_snapshot", "")).strip()
        if stored_value != declared_text:
            mismatches.append(
                f"{source_id}/{component_id}: stored version_or_snapshot must preserve declaration value "
                f"{declared_text!r}; got {stored_value!r}"
            )

    assert not mismatches, "Runtime/checksum locator-semantic fidelity violations:\n" + "\n".join(mismatches)


def test_ac04_recomputed_hash_cannot_launder_conflicting_declaration_fact(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    target_locator = "configs/ingest/tsc.yaml#assembly"
    matches = _components_for_exact_locator(payload, target_locator)
    if len(matches) != 1:
        pytest.fail(f"Expected exactly one component for locator {target_locator!r}, got {len(matches)}")
    _, component = matches[0]
    component["version_or_snapshot"] = "fabricated-assembly-pin-for-sourceops-probe"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / "ac04_conflicting_declaration_fact_with_recomputed_hash.yaml"
    _write_yaml(probe_path, payload)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    codes = _error_codes(report)
    assert codes, "conflicting declaration-fact metadata must emit typed validation errors"
    assert "REGISTRY_HASH_MISMATCH" not in codes, (
        "registry hash was recomputed; declaration-fact conflict must fail semantically, not via stale hash"
    )


def test_ac04_deliberate_omission_of_nested_declaration_locator_fails_validation(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    target_source_id = "frozen-core-annotation-bundle"
    target_marker = "annotator"
    mutated = copy.deepcopy(payload)

    removed = False
    records = mutated.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if not isinstance(record, dict) or record.get("source_id") != target_source_id:
            continue
        components = record.get("components")
        if not isinstance(components, list):
            continue
        kept: list[dict[str, Any]] = []
        for component in components:
            if not isinstance(component, dict):
                continue
            locator = str(component.get("declaration_locator", "")).replace("\\", "/").lower()
            if not removed and "runtime" in locator and target_marker in locator:
                removed = True
                continue
            kept.append(component)
        record["components"] = kept
    assert removed, f"Expected to remove runtime {target_marker!r} component locator for nested omission probe"
    mutated["registry_content_hash"] = _canonical_registry_hash(mutated)

    probe_path = tmp_path / "ac04_nested_locator_omission_probe.yaml"
    _write_yaml(probe_path, mutated)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report), "Nested declaration omission must produce typed validation errors"


def test_ac04_unique_inventory_accounting_and_omission_probe(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    expected_roots = set(_root_paths_from_spec())
    paths = _iter_declaration_paths(payload)
    for expected in expected_roots:
        count = sum(1 for path in paths if path == expected)
        assert count == 1, f"declaration root {expected} must be uniquely represented or excluded; observed {count}"

    for exclusion in payload.get("coverage_exclusions", []):
        if not isinstance(exclusion, dict):
            continue
        for key in ("owner", "reason", "review_condition"):
            value = exclusion.get(key)
            assert isinstance(value, str) and value.strip(), f"coverage exclusion missing non-empty {key}"

    mutated = copy.deepcopy(payload)
    target_root = next(iter(expected_roots))
    removed = False
    records = mutated.get("source_records", [])
    for record in records:
        if not isinstance(record, dict):
            continue
        refs = record.get("declaration_refs")
        if not isinstance(refs, list):
            continue
        kept = []
        for ref in refs:
            if (
                not removed
                and isinstance(ref, dict)
                and ref.get("path", "").replace("\\", "/") == target_root
            ):
                removed = True
                continue
            kept.append(ref)
        record["declaration_refs"] = kept
    assert removed, f"Could not remove declaration root {target_root} for omission probe"
    mutated["registry_content_hash"] = _canonical_registry_hash(mutated)

    probe_path = tmp_path / "ac04_omission_probe.yaml"
    _write_yaml(probe_path, mutated)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report), "Inventory omission must produce a typed error report"


def test_ac04_coverage_exclusion_metadata_rejects_blank_or_placeholder_values(tmp_path: Path) -> None:
    base = _load_registry_payload()
    invalid_cases = [
        ("owner-blank", "owner", " "),
        ("owner-placeholder", "owner", "pending"),
        ("reason-blank", "reason", ""),
        ("reason-placeholder", "reason", "tbd"),
        ("review-condition-blank", "review_condition", "   "),
        ("review-condition-placeholder", "review_condition", "placeholder"),
    ]

    violations: list[str] = []
    for case_id, field, bad_value in invalid_cases:
        payload = copy.deepcopy(base)
        exclusion = {
            "exclusion_id": f"ac04-exclusion-metadata-{case_id}",
            "declaration_path": "configs/ingest/tsc.yaml",
            "declaration_locator": "genes[0]",
            "owner": "sourceops-contract-test",
            "reason": "synthetic exclusion metadata validation probe",
            "review_condition": "replace with authoritative inventory row before promotion",
        }
        exclusion[field] = bad_value
        _append_coverage_exclusion(payload, **exclusion)
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe_path = tmp_path / f"ac04_exclusion_metadata_{case_id}.yaml"
        _write_yaml(probe_path, payload)

        result = _run_validate(probe_path)
        report = _parse_json(result)
        codes = _error_codes(report)
        if result.returncode != 2:
            violations.append(f"{case_id}: expected validate exit 2, got {result.returncode}")
        if report.get("registry_valid") is not False:
            violations.append(f"{case_id}: registry_valid must be false")
        if not codes.intersection({"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE"}):
            violations.append(
                f"{case_id}: expected schema/metadata failure for exclusion metadata, got {sorted(codes)}"
            )
        if "REGISTRY_HASH_MISMATCH" in codes:
            violations.append(f"{case_id}: failure must not depend on stale registry hash")

    assert not violations, "Coverage exclusion metadata closure violations:\n" + "\n".join(violations)


def test_ac06_coverage_exclusion_path_and_locator_file_identity_are_safe(tmp_path: Path) -> None:
    base = _load_registry_payload()
    ingest_abs = str((REPO_ROOT / "configs" / "ingest" / "tsc.yaml").resolve())
    invalid_cases: list[tuple[str, str, str]] = [
        ("absolute-path", ingest_abs, "genes[0]"),
        ("drive-path", "C:\\Windows\\System32\\drivers\\etc\\hosts", "genes[0]"),
        ("parent-traversal", "../outside/declaration.yaml", "genes[0]"),
        ("external-uri", "https://example.invalid/sourceops/declaration.yaml", "genes[0]"),
        ("missing-file", "configs/sourceops/definitely_missing.yaml", "genes[0]"),
        ("locator-absolute-file", "configs/ingest/tsc.yaml", f"{ingest_abs}#genes[0]"),
        ("locator-drive-file", "configs/ingest/tsc.yaml", "C:\\Windows\\System32\\drivers\\etc\\hosts#anything"),
        ("locator-parent-traversal", "configs/ingest/tsc.yaml", "../outside/declaration.yaml#genes[0]"),
        ("locator-external-uri", "configs/ingest/tsc.yaml", "https://example.invalid/sourceops/declaration.yaml#genes[0]"),
        ("locator-missing-file", "configs/ingest/tsc.yaml", "configs/sourceops/definitely_missing.yaml#synthetic"),
        ("locator-mismatched-file", "configs/ingest/tsc.yaml", "configs/eval/core_annotation_bundle.yaml#status"),
    ]

    violations: list[str] = []
    for case_id, declaration_path, declaration_locator in invalid_cases:
        payload = copy.deepcopy(base)
        _append_coverage_exclusion(
            payload,
            exclusion_id=f"ac06-exclusion-path-safety-{case_id}",
            declaration_path=declaration_path,
            declaration_locator=declaration_locator,
            owner="sourceops-contract-test",
            reason="synthetic exclusion path safety probe",
            review_condition="replace with repository-safe declaration reference before promotion",
        )
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe_path = tmp_path / f"ac06_exclusion_path_safety_{case_id}.yaml"
        _write_yaml(probe_path, payload)

        result = _run_validate(probe_path)
        report = _parse_json(result)
        codes = _error_codes(report)
        if result.returncode != 2:
            violations.append(f"{case_id}: expected validate exit 2, got {result.returncode}")
        if report.get("registry_valid") is not False:
            violations.append(f"{case_id}: registry_valid must be false")
        if not codes.intersection({"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"}):
            violations.append(
                f"{case_id}: expected declaration-reference safety failure, got {sorted(codes)}"
            )
        if "REGISTRY_HASH_MISMATCH" in codes:
            violations.append(f"{case_id}: failure must not depend on stale registry hash")

    assert not violations, "Coverage exclusion declaration-path safety violations:\n" + "\n".join(violations)


def test_ac04_coverage_exclusions_cannot_launder_mandatory_component_omissions(tmp_path: Path) -> None:
    target_source_id = "tsc-ingest-and-reference-declarations"
    target_locator = "configs/ingest/tsc.yaml#normalizer.version"
    invalid_cases = [
        (
            "blank-owner",
            {
                "declaration_path": "configs/ingest/tsc.yaml",
                "declaration_locator": "normalizer.version",
                "owner": " ",
                "reason": "synthetic omission laundering probe",
                "review_condition": "replace with concrete source record row",
            },
            {"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE"},
        ),
        (
            "unsafe-external-path",
            {
                "declaration_path": "https://example.invalid/sourceops/declaration.yaml",
                "declaration_locator": target_locator,
                "owner": "sourceops-contract-test",
                "reason": "synthetic omission laundering probe",
                "review_condition": "replace with repository-safe declaration exclusion",
            },
            {"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"},
        ),
    ]

    violations: list[str] = []
    for case_id, exclusion, expected_codes in invalid_cases:
        payload = _load_registry_payload()
        _remove_component_by_locator(payload, source_id=target_source_id, locator=target_locator)
        _append_coverage_exclusion(
            payload,
            exclusion_id=f"ac04-omission-launder-{case_id}",
            declaration_path=exclusion["declaration_path"],
            declaration_locator=exclusion["declaration_locator"],
            owner=exclusion["owner"],
            reason=exclusion["reason"],
            review_condition=exclusion["review_condition"],
        )
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe_path = tmp_path / f"ac04_omission_launder_{case_id}.yaml"
        _write_yaml(probe_path, payload)

        result = _run_validate(probe_path)
        report = _parse_json(result)
        codes = _error_codes(report)
        if result.returncode != 2:
            violations.append(f"{case_id}: expected validate exit 2, got {result.returncode}")
        if report.get("registry_valid") is not False:
            violations.append(f"{case_id}: registry_valid must be false")
        if not codes.intersection(expected_codes):
            violations.append(
                f"{case_id}: expected omission-laundering rejection codes {sorted(expected_codes)}, got {sorted(codes)}"
            )
        if "REGISTRY_HASH_MISMATCH" in codes:
            violations.append(f"{case_id}: failure must not depend on stale registry hash")

    assert not violations, "Omission-laundering exclusion violations:\n" + "\n".join(violations)

    positive_payload = _load_registry_payload()
    _remove_component_by_locator(positive_payload, source_id=target_source_id, locator=target_locator)
    _append_coverage_exclusion(
        positive_payload,
        exclusion_id="ac04-omission-positive-control",
        declaration_path="configs/ingest/tsc.yaml",
        declaration_locator="normalizer.version",
        owner="sourceops-contract-test",
        reason="normalizer pin omitted from source row and explicitly tracked as reviewed exclusion",
        review_condition="replace exclusion with restored component before next promotion",
    )
    positive_payload["registry_content_hash"] = _canonical_registry_hash(positive_payload)
    positive_path = tmp_path / "ac04_omission_positive_control.yaml"
    _write_yaml(positive_path, positive_payload)
    positive_result = _run_validate(positive_path)
    assert positive_result.returncode == 0, positive_result.stderr or positive_result.stdout
    positive_report = _parse_json(positive_result)
    assert positive_report.get("registry_valid") is True


def test_ac05_core_policy_only_reuse_claim_is_fail_closed_and_eval_gate_stays_historical_ready(
    tmp_path: Path,
) -> None:
    payload = _load_registry_payload()
    core_record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    core_record["lifecycle_state"] = "PINNED_HISTORICAL"
    core_licence = core_record.get("licence")
    if not isinstance(core_licence, dict):
        core_licence = {}
        core_record["licence"] = core_licence
    core_licence["permitted_use"] = "policy_only_reuse_permitted_now"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    invalid_path = tmp_path / "ac05_core_policy_only_reuse_claim.yaml"
    _write_yaml(invalid_path, payload)
    invalid_result = _run_validate(invalid_path)
    assert invalid_result.returncode == 2, invalid_result.stderr or invalid_result.stdout
    invalid_report = _parse_json(invalid_result)
    assert "SOURCE_METADATA_INCOMPLETE" in _error_codes(invalid_report), invalid_report

    historical_ready = copy.deepcopy(_load_registry_payload())
    historical_core = _source_record_by_id(historical_ready, "frozen-core-annotation-bundle")
    historical_core["lifecycle_state"] = "PINNED_HISTORICAL"
    historical_licence = historical_core.get("licence")
    if not isinstance(historical_licence, dict):
        historical_licence = {}
        historical_core["licence"] = historical_licence
    historical_licence["permitted_use"] = "historical_reference_only_blocked_policy_only_reuse"
    historical_ready["registry_content_hash"] = _canonical_registry_hash(historical_ready)
    historical_path = tmp_path / "ac05_eval_gate_historical_reference_ready.yaml"
    _write_yaml(historical_path, historical_ready)
    status_result = _run_status(historical_path, "eval-gate")
    assert status_result.returncode == 0, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "READY"


def test_ac05_acmg_licensing_tags_cannot_launder_to_verified_or_permitted_use(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    acmg_root = _load_root_yaml("configs/acmg/tsc.yaml")
    licensing = acmg_root.get("licensing")
    assert isinstance(licensing, dict) and licensing, "authoritative ACMG licensing tags must exist for mutation probe"

    acmg_record = _source_record_by_id(payload, "tsc-acmg-runtime-source-pins")
    components = acmg_record.get("components")
    if not isinstance(components, list):
        components = []
        acmg_record["components"] = components
    role = "licensing_tag"
    for idx, tag in enumerate(sorted(licensing), start=1):
        components.append(
            {
                "component_id": f"acmg-licensing-tag-{idx}",
                "display_name": f"ACMG licensing tag {tag}",
                "lifecycle_state": "VERIFIED_ACTIVE",
                "source_role": role,
                "version_or_snapshot": "licensing-tag-v1",
                "licence_status": "permitted_use_cleared_for_all_uses",
                "declaration_locator": f"licensing.{tag}",
            }
        )
    acmg_record["lifecycle_state"] = "VERIFIED_ACTIVE"
    licence = acmg_record.get("licence")
    if not isinstance(licence, dict):
        pytest.fail("acmg record must carry licence mapping")
    licence["permitted_use"] = "unknown_scope_not_independently_verified"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / "ac05_acmg_licensing_laundering_probe.yaml"
    _write_yaml(probe_path, payload)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    codes = _error_codes(report)
    assert {"SOURCE_METADATA_INCOMPLETE", "FORBIDDEN_ROLE_FLOW"}.intersection(codes), (
        f"expected fail-closed licensing semantics error, got {sorted(codes)}"
    )


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("permitted_use", "historical_attestation_does_not_authorize_new_reannotation_scope"),
        ("redistribution", "redistribution_authorized_for_new_derivative_exports"),
        ("cloud_egress", "cloud_egress_authorized_for_external_compute"),
    ],
    ids=["permitted-use", "redistribution", "cloud-egress"],
)
def test_ac05_historical_licensing_defaults_deny_unverified_authorization_claims(
    tmp_path: Path, field: str, new_value: str
) -> None:
    payload = _load_registry_payload()
    core_record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    core_record["lifecycle_state"] = "PINNED_HISTORICAL"
    licence = core_record.get("licence")
    if not isinstance(licence, dict):
        pytest.fail("frozen-core-annotation-bundle licence mapping required")
    licence[field] = new_value
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / f"ac05_historical_licensing_default_deny_{field}.yaml"
    _write_yaml(probe_path, payload)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    codes = _error_codes(report)
    assert codes.intersection({"SOURCE_METADATA_INCOMPLETE", "REGISTRY_SCHEMA_ERROR", "FORBIDDEN_ROLE_FLOW"}), (
        "historical licensing cannot be relabelled into new authorization scope"
    )


def test_ac07_readiness_truth_table_and_eval_gate_historical_binding() -> None:
    payload = _load_registry_payload()
    first_slice = _first_slice_spec()
    in_scope = set(first_slice.get("consumers_in_scope", []))
    assert in_scope, "consumers_in_scope must not be empty"

    records = payload.get("source_records")
    consumers = payload.get("consumers")
    assert isinstance(records, list) and isinstance(consumers, list)
    source_by_id = {
        record.get("source_id"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("source_id"), str)
    }

    blocked_by_pending: list[str] = []
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        consumer_id = consumer.get("consumer_id")
        if not isinstance(consumer_id, str) or consumer_id not in in_scope:
            continue
        required = consumer.get("required_sources")
        assert isinstance(required, list), f"{consumer_id} required_sources must be a list"
        for source_id in required:
            assert source_id in source_by_id, f"{consumer_id} references unknown source {source_id!r}"
        if any(
            source_by_id[source_id].get("lifecycle_state") in {"CONFIRM_PENDING", "ACCESS_BLOCKED"}
            for source_id in required
            if isinstance(source_id, str) and source_id in source_by_id
        ):
            blocked_by_pending.append(consumer_id)
    assert blocked_by_pending, "at least one real consumer must be BLOCKED by a real CONFIRM_PENDING declaration"
    status_probe_consumer = blocked_by_pending[0]
    status_result = _run_status(REGISTRY_PATH, status_probe_consumer)
    assert status_result.returncode == 3, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "BLOCKED"

    eval_gate = _consumer_by_id(payload, "eval-gate")
    assert eval_gate is not None, "eval-gate consumer must exist"
    required = eval_gate.get("required_sources")
    assert isinstance(required, list) and required, "eval-gate required_sources must be non-empty"
    assert "atlas-tsc2-catalog-template" not in required, (
        "METADATA_CATALOG_TEMPLATE must never satisfy grounding/evidence eval-gate requirements"
    )
    eval_sources = [source_by_id[source_id] for source_id in required if source_id in source_by_id]
    assert any(source.get("lifecycle_state") == "PINNED_HISTORICAL" for source in eval_sources), (
        "eval-gate READY must be anchored by immutable historical declaration"
    )
    forbidden_lifecycle = {"METADATA_ONLY", "RETIRED", "CONFIRM_PENDING", "ACCESS_BLOCKED"}
    assert all(source.get("lifecycle_state") not in forbidden_lifecycle for source in eval_sources), (
        "eval-gate must not launder metadata-only, retired, or blocked sources into READY"
    )
    for source in eval_sources:
        for component in _components(source):
            role = component.get("source_role")
            assert role not in {"provenance_only", "shadow", "proposed"}, (
                "eval-gate must not consume provenance_only or shadow component roles"
            )


def test_ac07_required_source_edges_do_not_contradict_forbidden_roles_on_baseline() -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    consumers = payload.get("consumers")
    assert isinstance(records, list) and isinstance(consumers, list)
    source_by_id = {
        record.get("source_id"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("source_id"), str)
    }

    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        consumer_id = consumer.get("consumer_id")
        required = consumer.get("required_sources")
        forbidden_roles = consumer.get("forbidden_source_roles")
        assert isinstance(required, list), f"{consumer_id!r} required_sources must be a list"
        assert isinstance(forbidden_roles, list), f"{consumer_id!r} forbidden_source_roles must be a list"
        forbidden = {role for role in forbidden_roles if isinstance(role, str)}
        if not forbidden:
            continue
        for source_id in required:
            if not isinstance(source_id, str):
                continue
            source = source_by_id.get(source_id)
            assert source is not None, f"{consumer_id!r} references unknown source {source_id!r}"
            roles = {component.get("source_role") for component in _components(source) if isinstance(component.get("source_role"), str)}
            overlap = sorted(role for role in roles if role in forbidden)
            assert not overlap, (
                f"consumer {consumer_id!r} required_sources contains forbidden roles {overlap} from source {source_id!r}"
            )


def test_ac07_metadata_catalog_template_cannot_satisfy_grounding_consumer(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumers = payload.get("consumers")
    assert isinstance(consumers, list)
    eval_gate = _consumer_by_id(payload, "eval-gate")
    assert eval_gate is not None, "eval-gate consumer must exist for grounding probe"
    required = eval_gate.get("required_sources")
    assert isinstance(required, list)
    assert "atlas-tsc2-catalog-template" not in required, (
        "METADATA_CATALOG_TEMPLATE cannot be a grounding/evidence required source"
    )

    mutated = copy.deepcopy(payload)
    catalog = _source_record_by_id(mutated, "atlas-tsc2-catalog-template")
    catalog["record_kind"] = "SINGLE_SOURCE"
    catalog["lifecycle_state"] = "VERIFIED_ACTIVE"
    catalog["components"] = []
    if not isinstance(catalog.get("consumers"), list):
        catalog["consumers"] = []
    if "eval-gate" not in catalog["consumers"]:
        catalog["consumers"].append("eval-gate")

    eval_gate_mut = _consumer_by_id(mutated, "eval-gate")
    assert eval_gate_mut is not None
    required_mut = eval_gate_mut.get("required_sources")
    assert isinstance(required_mut, list)
    if "atlas-tsc2-catalog-template" not in required_mut:
        required_mut.append("atlas-tsc2-catalog-template")
    payload_hash = _canonical_registry_hash(mutated)
    mutated["registry_content_hash"] = payload_hash

    probe_path = tmp_path / "ac07_metadata_catalog_grounding_probe.yaml"
    _write_yaml(probe_path, mutated)
    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    codes = _error_codes(validate_report)
    assert codes.intersection({"FORBIDDEN_ROLE_FLOW", "REGISTRY_SCHEMA_ERROR"}), (
        "metadata catalog template semantics cannot be laundered by relabelling record_kind/lifecycle for grounding use"
    )
    assert "DANGLING_CONSUMER_OR_SOURCE" not in codes, (
        "metadata-catalog relabelling probe must fail on template semantics, not dangling graph edges"
    )

    status_result = _run_status(probe_path, "eval-gate")
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID"


def test_ac07_metadata_catalog_template_cannot_be_promoted_to_satisfy_atlas(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    mutated = copy.deepcopy(payload)
    catalog = _source_record_by_id(mutated, "atlas-tsc2-catalog-template")
    catalog["record_kind"] = "METADATA_CATALOG_TEMPLATE"
    catalog["lifecycle_state"] = "VERIFIED_ACTIVE"
    catalog["components"] = []
    if not isinstance(catalog.get("consumers"), list):
        catalog["consumers"] = []
    if "atlas" not in catalog["consumers"]:
        catalog["consumers"].append("atlas")

    atlas = _consumer_by_id(mutated, "atlas")
    assert atlas is not None, "atlas consumer must exist"
    required = atlas.get("required_sources")
    assert isinstance(required, list), "atlas required_sources must be list"
    if "atlas-tsc2-catalog-template" not in required:
        required.append("atlas-tsc2-catalog-template")

    mutated["registry_content_hash"] = _canonical_registry_hash(mutated)
    probe_path = tmp_path / "ac07_metadata_catalog_atlas_promotion_probe.yaml"
    _write_yaml(probe_path, mutated)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    codes = _error_codes(validate_report)
    assert {"FORBIDDEN_ROLE_FLOW", "SOURCE_METADATA_INCOMPLETE"}.intersection(codes), (
        f"expected metadata-template promotion failure, got {sorted(codes)}"
    )

    status_result = _run_status(probe_path, "atlas")
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID"


def test_ac07_empty_required_sources_consumer_never_defaults_to_ready(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("consumers must be a list")
    probe_consumer = {
        "consumer_id": "empty-required-sources-probe",
        "owner": "sourceops-contract-test",
        "required_sources": [],
        "freshness_required": False,
        "on_blocked_source": "block",
        "forbidden_source_roles": [],
    }
    consumers.append(probe_consumer)
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac07_empty_required_sources_probe.yaml"
    _write_yaml(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode in {0, 2}, validate_result.stderr or validate_result.stdout
    if validate_result.returncode == 2:
        validate_report = _parse_json(validate_result)
        assert _error_codes(validate_report), validate_report

    status_result = _run_status(probe_path, "empty-required-sources-probe")
    assert status_result.returncode in {2, 3}, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) != "READY", "empty required_sources must not produce vacuous READY"


def test_ac07_forbidden_role_readiness_probe_fails_closed(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    mutated = copy.deepcopy(payload)
    target_source = _source_record_by_id(mutated, "frozen-core-annotation-bundle")
    components = target_source.get("components")
    assert isinstance(components, list) and components, (
        "forbidden-role probe requires an internally consistent source with concrete components"
    )
    first_component = next((row for row in components if isinstance(row, dict)), None)
    assert first_component is not None, "forbidden-role probe requires one mutable component row"
    first_component["source_role"] = "provenance_only"

    consumers = mutated.get("consumers")
    assert isinstance(consumers, list)
    consumer_id = "forbidden-role-intersection-probe"
    assert _consumer_by_id(mutated, consumer_id) is None, f"probe consumer id unexpectedly present: {consumer_id}"
    consumers.append(
        {
            "consumer_id": consumer_id,
            "owner": "sourceops-contract-test",
            "required_sources": ["frozen-core-annotation-bundle"],
            "freshness_required": False,
            "on_blocked_source": "block_consumer",
            "forbidden_source_roles": ["provenance_only"],
        }
    )
    if not isinstance(target_source.get("consumers"), list):
        target_source["consumers"] = []
    if consumer_id not in target_source["consumers"]:
        target_source["consumers"].append(consumer_id)

    mutated["registry_content_hash"] = _canonical_registry_hash(mutated)
    probe_path = tmp_path / "ac07_forbidden_role_intersection_probe.yaml"
    _write_yaml(probe_path, mutated)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    codes = _error_codes(validate_report)
    assert "FORBIDDEN_ROLE_FLOW" in codes, f"expected FORBIDDEN_ROLE_FLOW, got {sorted(codes)}"
    assert "DANGLING_CONSUMER_OR_SOURCE" not in codes, (
        "forbidden-role probe must keep source/consumer reciprocity and fail only on role-flow semantics"
    )
    assert "SOURCE_BLOCKED" not in codes, (
        "forbidden role intersection is a registry-invalid flow (exit 2), not a blocked-source status outcome (exit 3)"
    )

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID", (
        "forbidden-role intersection must invalidate the registry for status, not report a BLOCKED consumer"
    )
    assert "FORBIDDEN_ROLE_FLOW" in _error_codes(status_report), status_report


def test_ac07_retired_component_states_cannot_launder_eval_gate_ready(tmp_path: Path) -> None:
    invalid_cases = [
        ("single-component-retired", False),
        ("all-components-retired", True),
    ]

    violations: list[str] = []
    for case_id, retire_all in invalid_cases:
        payload = _load_registry_payload()
        eval_gate = _consumer_by_id(payload, "eval-gate")
        assert eval_gate is not None, "eval-gate consumer must exist for retired-component least-permissive probe"
        required_sources = eval_gate.get("required_sources")
        assert isinstance(required_sources, list) and "frozen-core-annotation-bundle" in required_sources, (
            "eval-gate must require frozen-core-annotation-bundle for retired-component laundering probe"
        )

        source = _source_record_by_id(payload, "frozen-core-annotation-bundle")
        assert source.get("lifecycle_state") in {"PINNED_HISTORICAL", "VERIFIED_ACTIVE"}, (
            "probe requires an admissible top-level lifecycle to test least-permissive component aggregation"
        )
        components = source.get("components")
        if not isinstance(components, list) or not components:
            pytest.fail("retired-component laundering probe requires frozen-core components")
        component_rows = [row for row in components if isinstance(row, dict)]
        if not component_rows:
            pytest.fail("retired-component laundering probe requires mutable component mappings")

        targets = component_rows if retire_all else component_rows[:1]
        for component in targets:
            component["lifecycle_state"] = "RETIRED"

        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe_path = tmp_path / f"ac07_retired_component_launder_{case_id}.yaml"
        _write_yaml(probe_path, payload)

        validate_result = _run_validate(probe_path)
        validate_report = _parse_json(validate_result)
        validate_codes = _error_codes(validate_report)
        if validate_result.returncode != 2:
            violations.append(f"{case_id}: expected validate exit 2, got {validate_result.returncode}")
        if validate_report.get("registry_valid") is not False:
            violations.append(f"{case_id}: registry_valid must be false")
        if "FORBIDDEN_ROLE_FLOW" not in validate_codes:
            violations.append(f"{case_id}: expected FORBIDDEN_ROLE_FLOW, got {sorted(validate_codes)}")
        if {"REGISTRY_HASH_MISMATCH", "DECLARATION_DRIFT"}.intersection(validate_codes):
            violations.append(
                f"{case_id}: failure must not depend on hash mismatch or declaration drift ({sorted(validate_codes)})"
            )

        status_result = _run_status(probe_path, "eval-gate")
        status_report = _parse_json(status_result)
        status_codes = _error_codes(status_report)
        if status_result.returncode != 2:
            violations.append(f"{case_id}: expected status exit 2, got {status_result.returncode}")
        if _consumer_state(status_report) != "INVALID":
            violations.append(
                f"{case_id}: consumer state must be INVALID for composite retired-component mismatch; "
                f"got {_consumer_state(status_report)!r}"
            )
        if "FORBIDDEN_ROLE_FLOW" not in status_codes:
            violations.append(f"{case_id}: status must report FORBIDDEN_ROLE_FLOW, got {sorted(status_codes)}")
        if "SOURCE_BLOCKED" in status_codes:
            violations.append(f"{case_id}: status must be INVALID/2, not BLOCKED/3")

    assert not violations, "Retired-component least-permissive readiness violations:\n" + "\n".join(violations)


def test_ac10_impact_routes_are_declared_with_human_approval_flags() -> None:
    payload = _load_registry_payload()
    first_slice = _first_slice_spec()
    allowed_actions = set(first_slice["registry_model"]["drift_policy_model"]["allowed_actions"])
    seen_actions: set[str] = set()
    material_actions = {
        "rebuild_benchmark",
        "review_policy",
        "invalidate_packets",
        "reground_atlas",
        "rerun_validation",
        "rollback",
    }

    records = payload.get("source_records")
    assert isinstance(records, list), "source_records must be a list"
    for record in records:
        assert isinstance(record, dict), "source record rows must be mappings"
        drift_policy = record.get("drift_policy")
        assert isinstance(drift_policy, dict), "drift_policy must be present for each source record"
        assert set(drift_policy.keys()) == {"materiality_basis", "actions", "approval_required"}
        actions = drift_policy.get("actions")
        assert isinstance(actions, list), "drift_policy.actions must be a list"
        approval_required = drift_policy.get("approval_required")
        assert isinstance(approval_required, bool), "drift_policy.approval_required must be boolean"
        action_set = {action for action in actions if isinstance(action, str)}
        assert action_set.issubset(allowed_actions), f"unknown drift actions: {sorted(action_set - allowed_actions)}"
        seen_actions.update(action_set)
        if action_set.intersection(material_actions):
            assert approval_required is True, "material actions require approval_required=true"

    missing = allowed_actions - seen_actions
    assert not missing, f"impact route declarations missing required actions: {sorted(missing)}"
    serialized = json.dumps(payload, sort_keys=True)
    for key in ("executed_actions", "applied_actions", "action_result", "action_execution"):
        assert key not in serialized, f"V2-S1 must not execute impact actions ({key} present)"


def test_ac11_reserved_consumer_firewall_and_non_activatability() -> None:
    payload = _load_registry_payload()
    reserved_ids = set(_first_slice_spec().get("consumers_reserved_but_not_activatable", []))
    source_ids = {record.get("source_id") for record in payload.get("source_records", []) if isinstance(record, dict)}
    assert reserved_ids.isdisjoint(source_ids), "reserved consumer identifiers cannot be source ids"

    for record in payload.get("source_records", []):
        if not isinstance(record, dict):
            continue
        linked_consumers = record.get("consumers")
        if isinstance(linked_consumers, list):
            for consumer_id in linked_consumers:
                assert consumer_id not in reserved_ids, (
                    f"reserved consumer {consumer_id!r} cannot be activated by source {record.get('source_id')!r}"
                )

    for reserved_id in sorted(reserved_ids):
        consumer = _consumer_by_id(payload, reserved_id)
        assert consumer is not None, f"reserved consumer {reserved_id!r} must be present to prevent collisions"
        required = consumer.get("required_sources")
        assert isinstance(required, list), f"{reserved_id} required_sources must be a list"
        assert not required, f"{reserved_id} must be reserved and non-activatable in V2-S1"

        result = _run_status(REGISTRY_PATH, reserved_id)
        assert result.returncode in {3, 4}, result.stderr or result.stdout
        if result.stdout.strip():
            report = _parse_json(result)
            assert _consumer_state(report) != "READY"


def test_fm4_rescuescreen_ready_claim_is_forbidden(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    assert isinstance(records, list) and records, "source_records must be non-empty"
    first_source_id = records[0].get("source_id")
    assert isinstance(first_source_id, str) and first_source_id

    rescuescreen = _consumer_by_id(payload, "rescuescreen")
    if rescuescreen is None:
        template = next(
            (
                copy.deepcopy(consumer)
                for consumer in payload.get("consumers", [])
                if isinstance(consumer, dict)
            ),
            None,
        )
        if template is None:
            pytest.fail("Expected at least one consumer row for FM4 probe template")
        template["consumer_id"] = "rescuescreen"
        template["owner"] = "sourceops-fm4-probe"
        template["required_sources"] = [first_source_id]
        template["freshness_required"] = False
        template["forbidden_source_roles"] = []
        payload.setdefault("consumers", []).append(template)
    else:
        rescuescreen["required_sources"] = [first_source_id]
        rescuescreen["freshness_required"] = False
        rescuescreen["forbidden_source_roles"] = []

    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "fm4_cross_lane_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    assert "FORBIDDEN_CROSS_LANE_CLAIM" in _error_codes(report)


def test_ac12_preservation_set_is_unchanged_by_sourceops_commands() -> None:
    preservation_set = _first_slice_spec()["preservation_set"]["files"]
    before_hashes: dict[str, str] = {}
    for rel_path in preservation_set:
        path = REPO_ROOT / Path(rel_path)
        assert path.exists(), f"preservation artifact missing: {rel_path}"
        before_hashes[rel_path] = hashlib.sha256(path.read_bytes()).hexdigest()

    validate_result = _run_validate(REGISTRY_PATH)
    assert validate_result.returncode == 0, validate_result.stderr or validate_result.stdout
    status_result = _run_status(REGISTRY_PATH, "eval-gate")
    assert status_result.returncode == 0, status_result.stderr or status_result.stdout

    for rel_path, before_hash in before_hashes.items():
        after_hash = hashlib.sha256((REPO_ROOT / Path(rel_path)).read_bytes()).hexdigest()
        assert after_hash == before_hash, f"preservation artifact mutated by SourceOps command: {rel_path}"

    diff_check = subprocess.run(
        ["git", "--no-pager", "diff", "--name-only", "--", *preservation_set],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert diff_check.returncode == 0, diff_check.stderr
    assert not diff_check.stdout.strip(), f"preservation files show diff:\n{diff_check.stdout}"
