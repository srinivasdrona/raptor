from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import stat
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import yaml

from raptor.sourceops.drift_planning import (
    evaluate_materiality,
    load_materiality_policy,
    load_v2_s2_artifact_pair,
    plan_drift,
    rehearse_rollback,
    route_impact,
)
from raptor.sourceops.model import Registry
from raptor.sourceops.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-s3-drift-gates.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
POLICY_PATH = REPO_ROOT / "configs" / "sourceops" / "materiality_policy.yaml"
STAGING_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "staging"
STAGED_SNAPSHOT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "staged-snapshots"
DRIFT_OUTPUT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "drift-plans"
ROLLBACK_PARENT = REPO_ROOT / "configs" / "sourceops" / "rollbacks"
_RUNTIME_CLEANUP_ROOTS = (
    DRIFT_OUTPUT_PARENT,
    STAGED_SNAPSHOT_PARENT,
    STAGING_PARENT,
    ROLLBACK_PARENT,
)
_RUNTIME_ALWAYS_PRESERVED_ROOTS = frozenset(
    {
        DRIFT_OUTPUT_PARENT,
        STAGED_SNAPSHOT_PARENT,
        STAGING_PARENT,
    }
)
_RuntimeSnapshotEntry = tuple[str, bytes | str | None]


def _runtime_display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_runtime_paths_no_follow(root: Path) -> list[Path]:
    try:
        root.lstat()
    except FileNotFoundError:
        return []
    pending = [root]
    discovered: list[Path] = []
    while pending:
        current = pending.pop()
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            continue
        discovered.append(current)
        if stat.S_ISDIR(current_stat.st_mode):
            try:
                with os.scandir(current) as entries:
                    children = sorted((Path(entry.path) for entry in entries), key=lambda item: item.as_posix(), reverse=True)
            except FileNotFoundError:
                continue
            pending.extend(children)
    return discovered


def _snapshot_runtime_namespace() -> dict[Path, _RuntimeSnapshotEntry]:
    snapshot: dict[Path, _RuntimeSnapshotEntry] = {}
    for root in _RUNTIME_CLEANUP_ROOTS:
        for path in _iter_runtime_paths_no_follow(root):
            if path in snapshot:
                continue
            try:
                path_stat = path.lstat()
            except FileNotFoundError:
                continue
            mode = path_stat.st_mode
            if stat.S_ISDIR(mode):
                snapshot[path] = ("dir", None)
                continue
            if stat.S_ISLNK(mode):
                try:
                    snapshot[path] = ("symlink", os.readlink(path))
                except OSError as exc:
                    pytest.fail(f"unable to read symlink target for {_runtime_display(path)}: {exc}")
                continue
            if stat.S_ISREG(mode):
                try:
                    snapshot[path] = ("file", path.read_bytes())
                except OSError as exc:
                    pytest.fail(f"unable to read file bytes for {_runtime_display(path)}: {exc}")
                continue
            snapshot[path] = ("other", None)
    return snapshot


def _remove_created_runtime_paths(
    before: dict[Path, _RuntimeSnapshotEntry],
    after: dict[Path, _RuntimeSnapshotEntry],
) -> None:
    preserved_roots = set(_RUNTIME_ALWAYS_PRESERVED_ROOTS)
    for root in _RUNTIME_CLEANUP_ROOTS:
        if root in before:
            preserved_roots.add(root)
    created_paths = [path for path in after if path not in before and path not in preserved_roots]
    created_paths.sort(key=lambda item: (len(item.parts), item.as_posix()), reverse=True)
    failures: list[str] = []
    for path in created_paths:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        try:
            if stat.S_ISDIR(mode):
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{_runtime_display(path)}: {exc}")
    if failures:
        pytest.fail("V2-S3 runtime cleanup failed to remove test-owned paths:\n" + "\n".join(failures))


def _assert_preexisting_runtime_paths_unchanged(
    before: dict[Path, _RuntimeSnapshotEntry],
    after: dict[Path, _RuntimeSnapshotEntry],
) -> None:
    failures: list[str] = []
    for path, before_entry in sorted(before.items(), key=lambda row: row[0].as_posix()):
        after_entry = after.get(path)
        if after_entry is None:
            failures.append(f"{_runtime_display(path)} was removed")
            continue
        if after_entry[0] != before_entry[0]:
            failures.append(f"{_runtime_display(path)} changed type from {before_entry[0]} to {after_entry[0]}")
            continue
        if after_entry[1] != before_entry[1]:
            descriptor = "bytes" if before_entry[0] == "file" else "target"
            failures.append(f"{_runtime_display(path)} changed {descriptor}")
    if failures:
        pytest.fail("V2-S3 runtime cleanup detected mutation of pre-existing paths:\n" + "\n".join(failures))


@pytest.fixture(autouse=True)
def _v2s3_runtime_namespace_cleanup() -> Iterator[None]:
    before = _snapshot_runtime_namespace()
    yield
    after = _snapshot_runtime_namespace()
    _remove_created_runtime_paths(before, after)
    final = _snapshot_runtime_namespace()
    _assert_preexisting_runtime_paths_unchanged(before, final)


def _spec() -> dict[str, Any]:
    loaded = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("V2-S3 authority must parse into a mapping")
    return loaded


def _registry() -> dict[str, Any]:
    loaded = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")
    return loaded


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _self_excluding_hash(mapping: dict[str, Any], field: str) -> str:
    basis = copy.deepcopy(mapping)
    basis.pop(field, None)
    return _sha256_hex(_canonical_json_bytes(basis))


def _canonical_lf_bytes(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _canonical_text_checksum(raw: bytes) -> dict[str, Any]:
    canonical = _canonical_lf_bytes(raw)
    return {
        "mode": "CANONICAL_LF_TEXT",
        "raw_byte_size": None,
        "raw_sha256": None,
        "canonical_lf_utf8_bytes": len(canonical),
        "canonical_lf_sha256": _sha256_hex(canonical),
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _parse_json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "expected JSON stdout from CLI command.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        pytest.fail("CLI payload must be a JSON object")
    return payload


def _source_record(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    rows = registry.get("source_records")
    if not isinstance(rows, list):
        pytest.fail("registry source_records must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return copy.deepcopy(row)
    pytest.fail(f"source_id missing from registry: {source_id!r}")


def _source_record_hash(record: dict[str, Any]) -> str:
    return _sha256_hex(_canonical_json_bytes(record))


@dataclass(frozen=True, slots=True)
class PairFixture:
    case_id: str
    manifest_hash: str
    source_id: str
    observed_at: str
    verification_path: Path
    diff_path: Path
    verification: dict[str, Any]
    diff: dict[str, Any]
    verification_bytes: bytes
    diff_bytes: bytes


def _build_manifest_for_case(case_id: str) -> tuple[dict[str, Any], dict[str, bytes], str]:
    registry = _registry()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    snapshot_id = f"{case_id}-{uuid.uuid4().hex[:10]}"
    observed_at = "2026-08-19T00:00:00Z"

    declaration_rel = "candidate/configs/ingest/tsc.yaml"
    declaration_bytes = (REPO_ROOT / "configs" / "ingest" / "tsc.yaml").read_bytes()
    if case_id == "material-content":
        declaration_bytes = declaration_bytes + b"\n# v2s3-material-probe\n"

    retrieved_at = source["release"]["retrieved_at"]
    if case_id == "retrieved-at-only":
        retrieved_at = "2026-08-19T00:00:00Z"

    component_projection: Any = None
    if case_id in {"component-complete", "component-checksum-complete"}:
        source_components = source.get("components", [])
        if not isinstance(source_components, list):
            pytest.fail("current source components must be a list for component-complete fixture")
        component_projection = {
            "mode": "COMPLETE",
            "components": sorted(
                [
                    {
                        "component_id": row["component_id"],
                        "display_name": row["display_name"],
                        "source_role": row["source_role"],
                        "version_or_snapshot": row["version_or_snapshot"],
                        "licence_status": row["licence_status"],
                        "declaration_locator": row["declaration_locator"],
                    }
                    for row in source_components
                ],
                key=lambda row: row["component_id"],
            ),
        }

    staged_files: dict[str, bytes] = {declaration_rel: declaration_bytes}
    extra_files: list[dict[str, Any]] = []
    extra_bindings: list[dict[str, Any]] = []
    if case_id in {"component-checksum-not-provided", "component-checksum-complete"}:
        source_components = source.get("components", [])
        if not isinstance(source_components, list):
            pytest.fail("current source components must be a list for component-checksum fixture")

        valid_component: dict[str, Any] | None = None
        for row in source_components:
            if not isinstance(row, dict):
                continue
            component_id = row.get("component_id")
            role = str(row.get("source_role", ""))
            checksum_role = any(token.casefold() == "checksum" for token in role.replace("-", " ").replace("_", " ").split())
            version_or_snapshot = str(row.get("version_or_snapshot", ""))
            checksum_hash = len(version_or_snapshot) == 64 and all(ch in "0123456789abcdef" for ch in version_or_snapshot)
            if isinstance(component_id, str) and component_id and checksum_role and checksum_hash:
                valid_component = row
                break
        if valid_component is None:
            pytest.fail("component-checksum fixture requires one registry component with checksum role and 64-hex version_or_snapshot")

        component_rel = "candidate/components/component-checksum-probe.bin"
        component_raw = b"v2s3-component-checksum-probe\n"
        component_file_id = "component-checksum-probe-file"
        extra_files.append(
            {
                "file_id": component_file_id,
                "path": component_rel,
                "role": "SNAPSHOT_CONTENT",
                "media_type": "application/octet-stream",
                "checksum": {
                    "mode": "RAW_BYTES",
                    "raw_byte_size": len(component_raw),
                    "raw_sha256": _sha256_hex(component_raw),
                    "canonical_lf_utf8_bytes": None,
                    "canonical_lf_sha256": None,
                },
                "component_ids": [valid_component["component_id"]],
            }
        )
        extra_bindings.append(
            {
                "binding_id": "zz-bind-component-checksum-probe",
                "baseline_kind": "COMPONENT_CHECKSUM",
                "baseline_id": valid_component["component_id"],
                "candidate_file_id": component_file_id,
            }
        )
        staged_files[component_rel] = component_raw

    manifest = {
        "schema": "raptor.sourceops.staged_snapshot_manifest.v1",
        "manifest_content_hash": "0" * 64,
        "hash_basis": "raptor.sourceops.staged_snapshot_manifest_content_hash.v1",
        "observed_at": observed_at,
        "source_binding": {
            "source_id": source["source_id"],
            "registry_content_hash": registry["registry_content_hash"],
            "declaration_refs": copy.deepcopy(source["declaration_refs"]),
        },
        "candidate": {
            "snapshot_id": snapshot_id,
            "identity": {
                "display_name": source["display_name"],
                "record_kind": source["record_kind"],
                "owner": source["owner"],
                "authoritative_locator": source["authoritative_locator"],
            },
            "release": {
                "version_or_snapshot": source["release"]["version_or_snapshot"],
                "release_date": source["release"]["release_date"],
                "retrieved_at": retrieved_at,
                "content_pin_status": source["release"]["content_pin_status"],
            },
            "licence": copy.deepcopy(source["licence"]),
            "acquisition": copy.deepcopy(source["acquisition"]),
        },
        "files": [
            {
                "file_id": "decl-tsc-yaml",
                "path": declaration_rel,
                "role": "CANDIDATE_DECLARATION",
                "media_type": "application/x-yaml",
                "checksum": _canonical_text_checksum(declaration_bytes),
                "component_ids": [],
            }
        ],
        "content_bindings": [
            {
                "binding_id": "bind-declaration",
                "baseline_kind": "DECLARATION_REF",
                "baseline_id": "configs/ingest/tsc.yaml",
                "candidate_file_id": "decl-tsc-yaml",
            }
        ],
        "component_projection": component_projection,
    }
    manifest["files"].extend(extra_files)
    manifest["content_bindings"].extend(extra_bindings)
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"])
    manifest["content_bindings"] = sorted(manifest["content_bindings"], key=lambda row: row["binding_id"])
    manifest["manifest_content_hash"] = _self_excluding_hash(manifest, "manifest_content_hash")
    return manifest, staged_files, source["source_id"]


@contextmanager
def _stage_case(manifest: dict[str, Any], files: dict[str, bytes], *, case_id: str) -> Iterator[str]:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"v2s3-{case_id}-{uuid.uuid4().hex[:8]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        for rel_path, raw in files.items():
            target = stage_root / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage_root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
        yield f".raptor/sourceops/staging/{stage_name}"
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _cleanup_generated_leaf(manifest_hash: str) -> None:
    leaf = STAGED_SNAPSHOT_PARENT / manifest_hash
    if not leaf.exists():
        return
    parent = STAGED_SNAPSHOT_PARENT.resolve()
    resolved = leaf.resolve()
    assert str(resolved).startswith(str(parent) + os.sep), f"refusing to remove non-owned path: {leaf}"
    shutil.rmtree(leaf, ignore_errors=True)


@contextmanager
def _representative_pair(case_id: str) -> Iterator[PairFixture]:
    if case_id not in {
        "no-change",
        "retrieved-at-only",
        "material-content",
        "component-complete",
        "component-checksum-not-provided",
        "component-checksum-complete",
    }:
        pytest.fail(f"unsupported representative pair case: {case_id}")
    manifest, files, source_id = _build_manifest_for_case(case_id)
    with _stage_case(manifest, files, case_id=case_id) as staging_rel:
        result = _run_cli(
            "verify-stage",
            "--registry",
            "configs/sourceops/source_registry.yaml",
            "--staging-root",
            staging_rel,
        )
    if result.returncode != 0:
        pytest.fail(f"verify-stage fixture generation failed for {case_id}:\nstdout={result.stdout}\nstderr={result.stderr}")
    payload = _parse_json_stdout(result)
    verification_path = REPO_ROOT / payload["verification_artifact"]["path"]
    diff_path = REPO_ROOT / payload["diff_artifact"]["path"]
    verification_bytes = verification_path.read_bytes()
    diff_bytes = diff_path.read_bytes()
    verification = json.loads(verification_bytes.decode("utf-8"))
    diff = json.loads(diff_bytes.decode("utf-8"))
    pair = PairFixture(
        case_id=case_id,
        manifest_hash=manifest["manifest_content_hash"],
        source_id=source_id,
        observed_at=manifest["observed_at"],
        verification_path=verification_path,
        diff_path=diff_path,
        verification=verification,
        diff=diff,
        verification_bytes=verification_bytes,
        diff_bytes=diff_bytes,
    )
    try:
        yield pair
    finally:
        _cleanup_generated_leaf(pair.manifest_hash)


def _assert_exact_keys(mapping: Any, required: list[str], *, label: str) -> None:
    assert isinstance(mapping, dict), f"{label} must be a mapping"
    assert set(mapping.keys()) == set(required), f"{label} keys mismatch"


def _assert_canonical_artifact_bytes(artifact: dict[str, Any], raw: bytes, *, label: str) -> None:
    assert raw.endswith(b"\n"), f"{label} must end with exactly one LF byte"
    assert not raw.endswith(b"\r\n"), f"{label} must not end with CRLF"
    expected = _canonical_json_bytes(artifact) + b"\n"
    assert raw == expected, f"{label} bytes must be canonical JSON + one LF"


def _assert_pair_cross_bindings(pair: PairFixture) -> None:
    cross = _spec()["v2_s2_input_pair_contract"]["pair_cross_bindings"]
    for key in cross["exact_equal_between_artifacts"]:
        assert pair.verification[key] == pair.diff[key], f"cross-binding mismatch for field {key}"
    assert pair.verification["diff_artifact_content_hash"] == pair.diff["artifact_content_hash"], "diff content hash mismatch"
    assert pair.verification["manifest_content_hash"] == pair.manifest_hash
    assert pair.diff["manifest_content_hash"] == pair.manifest_hash
    assert pair.verification["observed_at"] == pair.observed_at
    assert pair.diff["observed_at"] == pair.observed_at


def _recompute_fact_classification(fact: dict[str, Any]) -> str:
    before = fact["before"]
    after = fact["after"]
    before_present = bool(before["present"])
    after_present = bool(after["present"])
    if not before_present and after_present:
        return "ADDED"
    if before_present and not after_present:
        return "REMOVED"
    if not before_present and not after_present:
        raise AssertionError("both before and after cannot be absent")
    before_bytes = _canonical_json_bytes(before["value"])
    after_bytes = _canonical_json_bytes(after["value"])
    return "UNCHANGED" if before_bytes == after_bytes else "CHANGED"


def _assert_pair_independently_valid(pair: PairFixture) -> None:
    spec = _spec()["v2_s2_input_pair_contract"]
    verification_spec = spec["verification_artifact"]
    diff_spec = spec["diff_artifact"]
    source_binding_spec = spec["common_source_binding_schema"]

    _assert_exact_keys(pair.verification, verification_spec["top_level_required_exact"], label="verification")
    _assert_exact_keys(pair.diff, diff_spec["top_level_required_exact"], label="diff")
    _assert_exact_keys(pair.verification["source_binding"], source_binding_spec["required_exact"], label="verification.source_binding")
    _assert_exact_keys(pair.diff["source_binding"], source_binding_spec["required_exact"], label="diff.source_binding")

    _assert_canonical_artifact_bytes(pair.verification, pair.verification_bytes, label="verification")
    _assert_canonical_artifact_bytes(pair.diff, pair.diff_bytes, label="diff")

    assert pair.verification["schema"] == verification_spec["schema"]
    assert pair.diff["schema"] == diff_spec["schema"]
    assert pair.verification["hash_basis"] == verification_spec["hash_basis"]
    assert pair.diff["hash_basis"] == diff_spec["hash_basis"]
    assert pair.verification["artifact_content_hash"] == _self_excluding_hash(pair.verification, "artifact_content_hash")
    assert pair.diff["artifact_content_hash"] == _self_excluding_hash(pair.diff, "artifact_content_hash")
    assert pair.verification_path.name == f"v-{pair.verification['artifact_content_hash']}.json"
    assert pair.diff_path.name == f"d-{pair.diff['artifact_content_hash']}.json"
    assert pair.verification_path.parent.name == pair.manifest_hash
    assert pair.diff_path.parent.name == pair.manifest_hash

    _assert_pair_cross_bindings(pair)

    input_tree = pair.verification["input_tree"]
    _assert_exact_keys(input_tree, verification_spec["input_tree_required_exact"], label="verification.input_tree")
    assert input_tree["hash_basis"] == verification_spec["input_tree_hash_basis"]
    files = input_tree["files"]
    assert isinstance(files, list) and files, "verification input_tree.files must be a non-empty list"
    recomputed_tree_hash = _sha256_hex(_canonical_json_bytes(files))
    assert input_tree["input_tree_content_hash"] == recomputed_tree_hash
    assert pair.diff["input_tree_content_hash"] == recomputed_tree_hash
    assert input_tree["total_bound_content_bytes"] == sum(int(item["content_byte_size"]) for item in files)

    facts = pair.diff["facts"]
    assert isinstance(facts, list) and facts, "diff facts must be a non-empty list"
    recomputed_counts = {key: 0 for key in diff_spec["summary_classification_keys"]}
    recomputed_diff_kind = {key: 0 for key in diff_spec["summary_difference_kind_keys"]}
    recomputed_fact_kind = {key: 0 for key in diff_spec["summary_fact_kind_keys"]}
    for fact in facts:
        _assert_exact_keys(fact, spec["diff_fact_validation"]["DiffFact_required_exact"], label="fact")
        recomputed = _recompute_fact_classification(fact)
        assert fact["classification"] == recomputed, "fact classification must be recomputed from before/after envelopes"
        recomputed_counts[recomputed] += 1
        recomputed_diff_kind[fact["difference_kind"]] += 1
        recomputed_fact_kind[fact["fact_kind"]] += 1

    summary = pair.diff["summary"]
    _assert_exact_keys(summary, diff_spec["summary_required_exact"], label="diff.summary")
    assert summary["total_facts"] == len(facts)
    assert summary["classifications"] == recomputed_counts
    assert summary["difference_kinds"] == recomputed_diff_kind
    assert summary["fact_kinds"] == recomputed_fact_kind
    derived_stage = "OBSERVED_NO_DIFFERENCE" if recomputed_counts["UNCHANGED"] == len(facts) else "OBSERVED_DIFFERENCE"
    assert pair.diff["stage_outcome"] == derived_stage
    assert pair.verification["stage_outcome"] == derived_stage


def _source_facts(diff: dict[str, Any]) -> list[dict[str, Any]]:
    return [fact for fact in diff["facts"] if fact["subject_type"] == "SOURCE"]


def _content_facts(diff: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_types = {"DECLARATION", "FILE", "COMPONENT"}
    return [fact for fact in diff["facts"] if fact["subject_type"] in allowed_types and fact["fact_path"].startswith("/content-bindings/")]


def _planned_policy_mapping() -> dict[str, Any]:
    return copy.deepcopy(_spec()["materiality_policy_contract"]["initial_checked_in_mapping"])


def _policy_hash(policy: dict[str, Any]) -> str:
    return _self_excluding_hash(policy, "policy_content_hash")


def _rule_match_list(value: str, selector_values: list[str]) -> bool:
    return selector_values == ["ANY"] or value in selector_values


def _rule_match_fact_path(fact_path: str, selector: dict[str, Any]) -> bool:
    mode = selector["mode"]
    values = selector["values"]
    if mode == "ANY":
        return values == []
    if mode == "EXACT":
        return fact_path in values
    if mode == "PREFIX":
        return any(fact_path.startswith(prefix) for prefix in values)
    raise ValueError(f"unknown fact_path mode: {mode!r}")


def _evaluate_fact(
    *,
    policy: dict[str, Any],
    classification: str,
    difference_kind: str,
    fact_kind: str,
    subject_type: str,
    fact_path: str,
    source_role: str,
    source_lifecycle: str,
    consumer_freshness_profile: str,
    record_kind: str,
) -> dict[str, Any]:
    allowed_classifications = set(_spec()["v2_s2_input_pair_contract"]["diff_fact_validation"]["classifications"])
    if classification not in allowed_classifications:
        raise ValueError(f"unknown classification: {classification}")
    for rule in sorted(policy["rules"], key=lambda row: row["priority"]):
        selectors = rule["selectors"]
        if not _rule_match_list(classification, selectors["classifications"]):
            continue
        if not _rule_match_list(difference_kind, selectors["difference_kinds"]):
            continue
        if not _rule_match_list(fact_kind, selectors["fact_kinds"]):
            continue
        if not _rule_match_list(subject_type, selectors["subject_types"]):
            continue
        if not _rule_match_fact_path(fact_path, selectors["fact_path"]):
            continue
        if not _rule_match_list(source_role, selectors["source_roles"]):
            continue
        if not _rule_match_list(source_lifecycle, selectors["source_lifecycles"]):
            continue
        if not _rule_match_list(consumer_freshness_profile, selectors["consumer_freshness_profiles"]):
            continue
        if not _rule_match_list(record_kind, selectors["record_kinds"]):
            continue
        return {
            "outcome": rule["outcome"],
            "rule_id": rule["rule_id"],
            "rationale_id": rule["rationale_id"],
            "conservative_default": rule["rationale_id"] == "CONSERVATIVE_DEFAULT",
        }
    return {
        "outcome": "MATERIAL_CHANGE",
        "rule_id": policy["evaluator"]["conservative_unmatched_rule_id"],
        "rationale_id": "CONSERVATIVE_DEFAULT",
        "conservative_default": True,
    }


def _aggregate_outcome(outcomes: list[str]) -> str:
    if "MATERIAL_CHANGE" in outcomes:
        return "MATERIAL_CHANGE"
    if "NON_MATERIAL_CHANGE" in outcomes:
        return "NON_MATERIAL_CHANGE"
    return "NO_OBSERVED_CHANGE"


def _derive_material_routes(source: dict[str, Any], *, aggregate_outcome: str, rollback_rehearsal: str) -> dict[str, dict[str, Any]]:
    allowed_actions = _spec()["impact_routing_contract"]["allowed_action_enum_in_order"]
    reserved = set(_spec()["planning_baseline"]["v2_s1"]["reserved_consumer_ids"])
    declared = list(source["drift_policy"]["actions"])
    consumers = [consumer for consumer in source["consumers"] if consumer not in reserved]

    def _record(action: str, disposition: str, reason_id: str, route_ids: list[str]) -> dict[str, Any]:
        return {"action": action, "disposition": disposition, "reason_id": reason_id, "route_ids": route_ids}

    out: dict[str, dict[str, Any]] = {}
    for action in allowed_actions:
        if action not in declared:
            out[action] = _record(action, "NOT_DECLARED_BY_SOURCE", "ACTION_NOT_DECLARED", [])
            continue
        if action == "stage_diff":
            out[action] = _record(action, "EVIDENCED_BY_VALIDATED_INPUT", "VALIDATED_V2_S2_DIFF_PRESENT", [])
            continue
        if action == "record_only":
            route = [f"record_only:SOURCE:{source['source_id']}"]
            out[action] = _record(action, "PROPOSED", "COMPLETED_ASSESSMENT_REQUIRES_RECORD", route)
            continue
        if aggregate_outcome == "NO_OBSERVED_CHANGE":
            out[action] = _record(action, "NOT_PROPOSED_NO_OBSERVED_CHANGE", "NO_OBSERVED_CHANGE", [])
            continue
        if aggregate_outcome == "NON_MATERIAL_CHANGE":
            out[action] = _record(action, "NOT_PROPOSED_NON_MATERIAL", "NON_MATERIAL_CHANGE", [])
            continue
        if action == "block_consumer":
            routes = [f"block_consumer:CONSUMER:{consumer_id}" for consumer_id in sorted(consumers)]
            out[action] = _record(action, "PROPOSED", "MATERIAL_ROUTE_CONDITION_MET", routes)
            continue
        if action == "rebuild_benchmark":
            routes = ["rebuild_benchmark:CONSUMER:eval-benchmark"] if "eval-benchmark" in consumers else []
            out[action] = _record(
                action,
                "PROPOSED" if routes else "NOT_PROPOSED_NO_TARGET_EDGE",
                "MATERIAL_ROUTE_CONDITION_MET" if routes else "TARGET_EDGE_ABSENT",
                routes,
            )
            continue
        if action == "invalidate_packets":
            routes = ["invalidate_packets:CONSUMER:packet"] if "packet" in consumers else []
            out[action] = _record(
                action,
                "PROPOSED" if routes else "NOT_PROPOSED_NO_TARGET_EDGE",
                "MATERIAL_ROUTE_CONDITION_MET" if routes else "TARGET_EDGE_ABSENT",
                routes,
            )
            continue
        if action == "reground_atlas":
            routes = ["reground_atlas:CONSUMER:atlas"] if "atlas" in consumers else []
            out[action] = _record(
                action,
                "PROPOSED" if routes else "NOT_PROPOSED_NO_TARGET_EDGE",
                "MATERIAL_ROUTE_CONDITION_MET" if routes else "TARGET_EDGE_ABSENT",
                routes,
            )
            continue
        if action == "rollback":
            if source["rollback"]["predecessor_source_id"] is None:
                out[action] = _record(action, "NOT_PROPOSED_NO_PREDECESSOR", "NO_PREDECESSOR", [])
            elif rollback_rehearsal != "READY_FOR_HUMAN_ADJUDICATION":
                out[action] = _record(action, "NOT_PROPOSED_REHEARSAL_BLOCKED", "ROLLBACK_REHEARSAL_BLOCKED", [])
            else:
                out[action] = _record(action, "PROPOSED", "MATERIAL_ROUTE_CONDITION_MET", [f"rollback:SOURCE:{source['source_id']}"])
            continue
        out[action] = _record(action, "PROPOSED", "MATERIAL_ROUTE_CONDITION_MET", [f"{action}:SOURCE:{source['source_id']}"])
    return out


def _validate_policy_shape(policy: dict[str, Any]) -> None:
    schema = _spec()["materiality_policy_contract"]["closed_policy_schema"]
    _assert_exact_keys(policy, schema["top_level_required_exact"], label="policy")
    assert policy["policy_content_hash"] == _policy_hash(policy), "policy hash must match canonical self-excluding hash"
    rules = policy["rules"]
    assert isinstance(rules, list) and rules, "policy.rules must be non-empty"
    priorities = [row["priority"] for row in rules]
    assert priorities == sorted(priorities), "policy rules must be strictly ascending by priority"
    assert len(set(priorities)) == len(priorities), "policy priorities must be unique"
    ids = [row["rule_id"].casefold() for row in rules]
    assert len(set(ids)) == len(ids), "policy rule_id values must be unique after casefold"
    rationale_ids = [row["rationale_id"].casefold() for row in rules]
    assert len(set(rationale_ids)) == len(rationale_ids), "policy rationale_id values must be unique after casefold"


def _require_drift_planning_module() -> Any:
    try:
        return importlib.import_module("raptor.sourceops.drift_planning")
    except ModuleNotFoundError as exc:
        pytest.fail(f"V2-S3 drift planning module is missing: {exc}")


def _production_registry() -> Any:
    return load_registry(str(REGISTRY_PATH))


def _run_plan_drift_cli(manifest_hash: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = _run_cli("plan-drift", "--manifest-hash", manifest_hash)
    payload = _parse_json_stdout(result)
    return result, payload


def _assert_fact_invariant_failure(manifest_hash: str, *, case_label: str) -> None:
    result, payload = _run_plan_drift_cli(manifest_hash)
    try:
        assert result.returncode == 2, f"{case_label}: plan-drift must fail with exit 2"
        assert payload["error"]["code"] == "DRIFT_FACT_INVARIANT_INVALID", f"{case_label}: wrong error code"
        assert payload["impact_plan"] is None, f"{case_label}: impact_plan must be null on fact invariant failure"
        assert payload["rollback_plan"] is None, f"{case_label}: rollback_plan must be null on fact invariant failure"
    finally:
        _cleanup_drift_output_from_cli_payload(payload)


_DIFFERENCE_KIND_ORDER = {"CONTENT": 0, "METADATA": 1, "DECLARATION": 2}
_FACT_KIND_ORDER = {"IDENTITY": 0, "VERSION": 1, "CHECKSUM": 2, "MANIFEST": 3, "COMPONENT": 4, "METADATA": 5}
_SUBJECT_TYPE_ORDER = {"SOURCE": 0, "FILE": 1, "COMPONENT": 2, "DECLARATION": 3}


def _fact_sort_key(fact: dict[str, Any]) -> tuple[int, int, int, str, str]:
    return (
        _DIFFERENCE_KIND_ORDER[fact["difference_kind"]],
        _FACT_KIND_ORDER[fact["fact_kind"]],
        _SUBJECT_TYPE_ORDER[fact["subject_type"]],
        fact["subject_id"],
        fact["fact_path"],
    )


def _recompute_diff_summary_and_outcome(diff: dict[str, Any]) -> None:
    facts = diff["facts"]
    summary = {
        "total_facts": len(facts),
        "classifications": {"ADDED": 0, "REMOVED": 0, "CHANGED": 0, "UNCHANGED": 0},
        "difference_kinds": {"CONTENT": 0, "METADATA": 0, "DECLARATION": 0},
        "fact_kinds": {"IDENTITY": 0, "VERSION": 0, "CHECKSUM": 0, "MANIFEST": 0, "COMPONENT": 0, "METADATA": 0},
    }
    for fact in facts:
        classification = _recompute_fact_classification(fact)
        fact["classification"] = classification
        summary["classifications"][classification] += 1
        summary["difference_kinds"][fact["difference_kind"]] += 1
        summary["fact_kinds"][fact["fact_kind"]] += 1
    diff["facts"] = sorted(facts, key=_fact_sort_key)
    diff["summary"] = summary
    diff["stage_outcome"] = "OBSERVED_NO_DIFFERENCE" if summary["classifications"]["UNCHANGED"] == len(facts) else "OBSERVED_DIFFERENCE"


def _rewrite_pair_leaf(
    pair: PairFixture,
    *,
    mutate_verification: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    mutate_diff: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    recompute_summary: bool = True,
    sync_cross_bindings: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification = copy.deepcopy(pair.verification)
    diff = copy.deepcopy(pair.diff)
    if mutate_verification is not None:
        mutate_verification(verification, diff)
    if mutate_diff is not None:
        mutate_diff(diff, verification)

    input_tree_files = verification["input_tree"]["files"]
    verification["input_tree"]["input_tree_content_hash"] = _sha256_hex(_canonical_json_bytes(input_tree_files))
    verification["input_tree"]["total_bound_content_bytes"] = sum(int(item["content_byte_size"]) for item in input_tree_files)
    diff["input_tree_content_hash"] = verification["input_tree"]["input_tree_content_hash"]

    if recompute_summary:
        _recompute_diff_summary_and_outcome(diff)
    diff["artifact_content_hash"] = _self_excluding_hash(diff, "artifact_content_hash")
    if sync_cross_bindings:
        verification["diff_artifact_content_hash"] = diff["artifact_content_hash"]
        verification["stage_outcome"] = diff["stage_outcome"]
    verification["artifact_content_hash"] = _self_excluding_hash(verification, "artifact_content_hash")

    leaf = pair.verification_path.parent
    for entry in list(leaf.iterdir()):
        if entry.is_file() or entry.is_symlink():
            entry.unlink(missing_ok=True)
        elif entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)

    verification_path = leaf / f"v-{verification['artifact_content_hash']}.json"
    diff_path = leaf / f"d-{diff['artifact_content_hash']}.json"
    verification_path.write_bytes(_canonical_json_bytes(verification) + b"\n")
    diff_path.write_bytes(_canonical_json_bytes(diff) + b"\n")
    return verification, diff


def _first_content_fact(diff: dict[str, Any]) -> dict[str, Any]:
    for fact in diff["facts"]:
        if fact["fact_path"].startswith("/content-bindings/"):
            return fact
    raise AssertionError("representative pair must carry at least one content fact")


def _component_checksum_content_facts(diff: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact
        for fact in diff["facts"]
        if fact["subject_type"] == "COMPONENT" and str(fact["fact_path"]).startswith("/content-bindings/")
    ]


ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS = "raptor.sourceops.rollback_source_record_binding_hash.v1"
ROLLBACK_SOURCE_RECORD_BINDING_SENTINEL = "__RAPTOR_ROLLBACK_ARTIFACT_CONTENT_ADDRESS_V1__"


@dataclass(frozen=True, slots=True)
class SyntheticRollbackFixture:
    registry: Registry
    raw_registry: dict[str, Any]
    current_record: dict[str, Any]
    predecessor_record: dict[str, Any]
    rollback_artifact_relpath: str
    rollback_artifact_path: Path
    rollback_artifact: dict[str, Any]
    rollback_artifact_bytes: bytes
    provisional_current_binding_hash: str
    current_rollback_binding_hash: str
    predecessor_rollback_binding_hash: str
    current_source_record_content_hash: str
    predecessor_source_record_content_hash: str
    synthetic_registry_content_hash: str
    created_file: bool
    created_parent_dir: bool


def _registry_content_hash(mapping: dict[str, Any]) -> str:
    return _self_excluding_hash(mapping, "registry_content_hash")


def _rollback_source_record_binding_hash(raw_source_record: dict[str, Any]) -> str:
    transformed = copy.deepcopy(raw_source_record)
    rollback = transformed.get("rollback")
    if not isinstance(rollback, dict) or "rollback_artifact" not in rollback:
        raise AssertionError("rollback.rollback_artifact is required before normalized binding hash")
    rollback["rollback_artifact"] = ROLLBACK_SOURCE_RECORD_BINDING_SENTINEL
    return _sha256_hex(_canonical_json_bytes(transformed))


def _canonical_lf_size_and_hash(repo_relpath: str) -> tuple[int, str]:
    canonical = _canonical_lf_bytes((REPO_ROOT / repo_relpath).read_bytes())
    return len(canonical), _sha256_hex(canonical)


def _build_algorithmic_non_null_ready_fixture(pair: PairFixture) -> SyntheticRollbackFixture:
    mapping = copy.deepcopy(_registry())
    records = mapping["source_records"]
    current_index = next(index for index, row in enumerate(records) if row["source_id"] == pair.source_id)
    baseline_current = copy.deepcopy(records[current_index])

    current = copy.deepcopy(baseline_current)
    predecessor = copy.deepcopy(baseline_current)
    predecessor["source_id"] = "synthetic-predecessor-tsc-ingest"
    predecessor["display_name"] = "Synthetic predecessor TSC ingest declaration"
    predecessor["lifecycle_state"] = "PINNED_HISTORICAL"
    predecessor["consumers"] = []
    predecessor["rollback"]["predecessor_source_id"] = None
    predecessor["rollback"]["rollback_artifact"] = "configs/sourceops/rollbacks/synthetic-predecessor-root.yaml"
    predecessor["rollback"]["origin_reason"] = "synthetic root predecessor"

    provisional_relpath = f"configs/sourceops/rollbacks/rb-{'0' * 64}.json"
    current["rollback"]["predecessor_source_id"] = predecessor["source_id"]
    current["rollback"]["rollback_artifact"] = provisional_relpath
    current["rollback"]["origin_reason"] = "synthetic non-null READY fixture"

    provisional_current_binding_hash = _rollback_source_record_binding_hash(current)
    predecessor_binding_hash = _rollback_source_record_binding_hash(predecessor)

    current_refs = copy.deepcopy(current["declaration_refs"])
    predecessor_refs = copy.deepcopy(predecessor["declaration_refs"])
    file_bindings: list[dict[str, Any]] = []
    for index, (current_ref, predecessor_ref) in enumerate(zip(current_refs, predecessor_refs), start=1):
        current_path = current_ref["path"]
        predecessor_path = predecessor_ref["path"]
        current_size, current_sha = _canonical_lf_size_and_hash(current_path)
        predecessor_size, predecessor_sha = _canonical_lf_size_and_hash(predecessor_path)
        file_bindings.append(
            {
                "binding_id": f"bind-{index:03d}",
                "predecessor_path": predecessor_path,
                "predecessor_content_byte_size": predecessor_size,
                "predecessor_canonical_lf_sha256": predecessor_sha,
                "current_path": current_path,
                "current_content_byte_size": current_size,
                "current_canonical_lf_sha256": current_sha,
            }
        )
    file_bindings = sorted(file_bindings, key=lambda row: row["binding_id"])

    preservation_bindings: list[dict[str, Any]] = []
    for row in mapping["preservation_rules"]:
        size, sha = _canonical_lf_size_and_hash(row["path"])
        preservation_bindings.append(
            {
                "rule_id": row["rule_id"],
                "path": row["path"],
                "content_byte_size": size,
                "canonical_lf_sha256": sha,
            }
        )

    rollback_artifact = {
        "schema": "raptor.sourceops.rollback_artifact.v1",
        "artifact_content_hash": "0" * 64,
        "hash_basis": "raptor.sourceops.rollback_artifact_content_hash.v1",
        "rollback_source_record_binding_hash_basis": ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS,
        "current_source_id": current["source_id"],
        "current_rollback_source_record_binding_hash": provisional_current_binding_hash,
        "predecessor_source_id": predecessor["source_id"],
        "predecessor_rollback_source_record_binding_hash": predecessor_binding_hash,
        "current_declaration_refs": current_refs,
        "predecessor_declaration_refs": predecessor_refs,
        "file_bindings": file_bindings,
        "preservation_bindings": preservation_bindings,
    }
    rollback_artifact["artifact_content_hash"] = _self_excluding_hash(rollback_artifact, "artifact_content_hash")
    rollback_artifact_relpath = f"configs/sourceops/rollbacks/rb-{rollback_artifact['artifact_content_hash']}.json"
    rollback_artifact_bytes = _canonical_json_bytes(rollback_artifact) + b"\n"

    current["rollback"]["rollback_artifact"] = rollback_artifact_relpath
    current_binding_hash = _rollback_source_record_binding_hash(current)
    assert current_binding_hash == provisional_current_binding_hash, "normalized rollback source-record binding hash must be path-stable"

    records[current_index] = current
    records.append(predecessor)
    mapping["registry_content_hash"] = _registry_content_hash(mapping)
    synthetic_registry_content_hash = mapping["registry_content_hash"]

    rollback_dir = REPO_ROOT / "configs" / "sourceops" / "rollbacks"
    created_parent_dir = False
    if not rollback_dir.exists():
        rollback_dir.mkdir(parents=True, exist_ok=False)
        created_parent_dir = True
    rollback_artifact_path = REPO_ROOT / rollback_artifact_relpath
    created_file = False
    if rollback_artifact_path.exists():
        if rollback_artifact_path.read_bytes() != rollback_artifact_bytes:
            pytest.fail(f"rollback fixture collision at {rollback_artifact_relpath}")
    else:
        rollback_artifact_path.write_bytes(rollback_artifact_bytes)
        created_file = True

    return SyntheticRollbackFixture(
        registry=Registry.from_mapping(mapping),
        raw_registry=mapping,
        current_record=current,
        predecessor_record=predecessor,
        rollback_artifact_relpath=rollback_artifact_relpath,
        rollback_artifact_path=rollback_artifact_path,
        rollback_artifact=rollback_artifact,
        rollback_artifact_bytes=rollback_artifact_bytes,
        provisional_current_binding_hash=provisional_current_binding_hash,
        current_rollback_binding_hash=current_binding_hash,
        predecessor_rollback_binding_hash=predecessor_binding_hash,
        current_source_record_content_hash=_source_record_hash(current),
        predecessor_source_record_content_hash=_source_record_hash(predecessor),
        synthetic_registry_content_hash=synthetic_registry_content_hash,
        created_file=created_file,
        created_parent_dir=created_parent_dir,
    )


@contextmanager
def _algorithmic_non_null_ready_fixture(pair: PairFixture) -> Iterator[SyntheticRollbackFixture]:
    fixture = _build_algorithmic_non_null_ready_fixture(pair)
    try:
        yield fixture
    finally:
        if fixture.created_file:
            fixture.rollback_artifact_path.unlink(missing_ok=True)
        if fixture.created_parent_dir:
            rollback_dir = fixture.rollback_artifact_path.parent
            try:
                rollback_dir.rmdir()
            except OSError:
                pass


@contextmanager
def _temporary_file_bytes(path: Path, replacement_bytes: bytes) -> Iterator[None]:
    original = path.read_bytes()
    path.write_bytes(replacement_bytes)
    try:
        yield
    finally:
        path.write_bytes(original)


def _mutated_registry_with_non_null_source(base_registry: Registry, base_raw_registry: dict[str, Any], current_record: dict[str, Any]) -> tuple[Registry, dict[str, Any]]:
    raw = copy.deepcopy(base_raw_registry)
    records = raw["source_records"]
    for index, row in enumerate(records):
        if row["source_id"] == current_record["source_id"]:
            records[index] = copy.deepcopy(current_record)
            break
    raw["registry_content_hash"] = _registry_content_hash(raw)
    return Registry.from_mapping(raw), raw


def _policy_with_registry_hash(registry_content_hash: str) -> Any:
    policy = load_materiality_policy()
    binding = dict(policy.registry_binding)
    binding["registry_content_hash"] = registry_content_hash
    raw_mapping = dict(policy.raw_mapping)
    raw_binding = dict(raw_mapping["registry_binding"])
    raw_binding["registry_content_hash"] = registry_content_hash
    raw_mapping["registry_binding"] = raw_binding
    return replace(policy, registry_binding=binding, raw_mapping=raw_mapping)


def _cleanup_drift_output_from_cli_payload(payload: dict[str, Any]) -> None:
    impact = payload.get("impact_plan")
    if not isinstance(impact, dict):
        return
    rel_path = impact.get("path")
    if not isinstance(rel_path, str):
        return
    impact_path = (REPO_ROOT / rel_path).resolve()
    root = (REPO_ROOT / ".raptor" / "sourceops" / "generated" / "drift-plans").resolve()
    if not str(impact_path).startswith(str(root) + os.sep):
        return
    diff_root = impact_path.parent.parent
    shutil.rmtree(diff_root, ignore_errors=True)


def test_v2s3_ac02_v2s2_artifacts_require_exact_canonical_schema_and_hashes() -> None:
    with _representative_pair("no-change") as pair:
        _assert_pair_independently_valid(pair)
        loaded = load_v2_s2_artifact_pair(pair.manifest_hash)
        assert loaded.manifest_content_hash == pair.manifest_hash
        assert loaded.verification_ref.content_hash == pair.verification["artifact_content_hash"]
        assert loaded.diff_ref.content_hash == pair.diff["artifact_content_hash"]


def test_v2s3_ac03_pair_cross_bindings_recompute_before_interpretation() -> None:
    with _representative_pair("no-change") as pair:
        _assert_pair_cross_bindings(pair)
        load_v2_s2_artifact_pair(pair.manifest_hash)
        _rewrite_pair_leaf(
            pair,
            mutate_verification=lambda verification, _diff: verification.__setitem__("diff_artifact_content_hash", "0" * 64),
            sync_cross_bindings=False,
        )
        result, payload = _run_plan_drift_cli(pair.manifest_hash)
        assert result.returncode == 2
        assert payload["error"]["code"] == "DRIFT_ARTIFACT_CROSS_BINDING_MISMATCH"
        assert payload["impact_plan"] is None
        assert payload["rollback_plan"] is None


def test_v2s3_ac04_source_content_component_fact_universe_is_independently_validated() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()

    def _probe_mutation(
        case_id: str,
        label: str,
        mutator: Callable[[dict[str, Any], dict[str, Any]], None],
    ) -> str | None:
        with _representative_pair(case_id) as pair:
            _assert_pair_independently_valid(pair)
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            evaluate_materiality(typed_pair, registry, policy)
            _rewrite_pair_leaf(pair, mutate_diff=mutator)
            try:
                _assert_fact_invariant_failure(pair.manifest_hash, case_label=label)
            except AssertionError as exc:
                return f"{label}: {exc}"
        return None

    def _set_invalid_baseline_hash(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        content = _first_content_fact(diff)
        content["before"]["value"] = "0" * 64
        content["after"]["value"] = "0" * 64

    def _remove_content_fact(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        diff["facts"] = [fact for fact in diff["facts"] if not fact["fact_path"].startswith("/content-bindings/")]

    def _change_after_hash(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        content = _first_content_fact(diff)
        content["after"]["value"] = "1" * 64

    def _unknown_baseline_target(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        content = _first_content_fact(diff)
        content["subject_id"] = "configs/ingest/unknown-declaration.yaml"

    def _duplicate_candidate_binding(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        content = copy.deepcopy(_first_content_fact(diff))
        content["fact_path"] = "/content-bindings/bind-duplicate/sha256"
        diff["facts"].append(content)

    def _inject_component_fact_when_not_provided(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        diff["facts"].append(
            {
                "difference_kind": "METADATA",
                "fact_kind": "COMPONENT",
                "subject_type": "COMPONENT",
                "subject_id": "synthetic-component",
                "fact_path": "/components/synthetic-component/display_name",
                "classification": "ADDED",
                "before": {"present": False, "value": None},
                "after": {"present": True, "value": "Synthetic"},
                "provenance": {"baseline_origin": "ABSENT", "candidate_origin": "MANIFEST_COMPONENT"},
            }
        )

    def _first_component_fact(diff: dict[str, Any]) -> dict[str, Any]:
        for fact in diff["facts"]:
            if fact["fact_kind"] == "COMPONENT":
                return fact
        raise AssertionError("expected component fact in component-complete pair")

    def _remove_component_fact(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        for index, fact in enumerate(diff["facts"]):
            if fact["fact_kind"] == "COMPONENT":
                del diff["facts"][index]
                return
        raise AssertionError("component fact missing in component-complete pair")

    def _forge_component_before_value(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        component_fact = _first_component_fact(diff)
        component_fact["before"]["value"] = "forged-component-before"

    def _duplicate_component_locator(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        cloned = copy.deepcopy(_first_component_fact(diff))
        cloned["fact_path"] = cloned["fact_path"] + "-duplicate"
        diff["facts"].append(cloned)

    failures = [
        _probe_mutation("no-change", "A-before-after-baseline-hash-mismatch", _set_invalid_baseline_hash),
        _probe_mutation("no-change", "B-missing-content-fact", _remove_content_fact),
        _probe_mutation("no-change", "C-after-hash-mismatch-with-input-tree", _change_after_hash),
        _probe_mutation("no-change", "D1-unknown-baseline-target", _unknown_baseline_target),
        _probe_mutation("no-change", "D2-duplicate-candidate-binding", _duplicate_candidate_binding),
        _probe_mutation("no-change", "E-component-fact-when-not-provided", _inject_component_fact_when_not_provided),
        _probe_mutation("component-complete", "F1-missing-component-fact", _remove_component_fact),
        _probe_mutation("component-complete", "F2-forged-component-before-value", _forge_component_before_value),
        _probe_mutation("component-complete", "F3-duplicate-component-locator", _duplicate_component_locator),
    ]

    blockers = [item for item in failures if item is not None]
    assert not blockers, "fact-universe drift invariants are not enforced by production:\n" + "\n".join(blockers)


def test_v2s3_ac04_complete_component_projection_without_file_anchors_is_accepted_and_evaluated() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()
    with _representative_pair("component-complete") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_verification=lambda verification, _diff: [
                file_row.__setitem__("component_ids", []) for file_row in verification["input_tree"]["files"]
            ],
            recompute_summary=True,
        )
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        assert all(list(file_row["component_ids"]) == [] for file_row in typed_pair.verification["input_tree"]["files"])
        assessment = evaluate_materiality(typed_pair, registry, policy)
        assert assessment.outcome in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code == 0
            assert payload["error"] is None
            assert payload["assessment_outcome"] in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
            assert payload["rollback_rehearsal_outcome"] in {"NOT_APPLICABLE", "READY_FOR_HUMAN_ADJUDICATION", "BLOCKED"}
        finally:
            _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_ac04_component_checksum_content_fact_is_projection_mode_independent() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()

    content_component_counts: dict[str, int] = {}
    projection_component_counts: dict[str, int] = {}
    for case_id in ("component-checksum-not-provided", "component-checksum-complete"):
        with _representative_pair(case_id) as pair:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            content_component_facts = _component_checksum_content_facts(typed_pair.diff)
            projection_component_facts = [fact for fact in typed_pair.diff["facts"] if str(fact["fact_path"]).startswith("/components/")]

            assert content_component_facts, f"{case_id}: expected COMPONENT-subject content-binding fact"
            assert all(str(fact["fact_path"]).startswith("/content-bindings/") for fact in content_component_facts)
            assert all(str(fact["fact_path"]).startswith("/components/") for fact in projection_component_facts)
            content_component_counts[case_id] = len(content_component_facts)
            projection_component_counts[case_id] = len(projection_component_facts)
            if case_id == "component-checksum-not-provided":
                assert projection_component_facts == [], "NOT_PROVIDED must not fabricate /components/ facts"
            else:
                assert projection_component_facts, "COMPLETE projection must include /components/ facts"

            assessment = evaluate_materiality(typed_pair, registry, policy)
            assert assessment.outcome in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
            matching_evaluations = [
                row
                for row in assessment.evaluations
                if row.fact_locator["subject_type"] == "COMPONENT" and str(row.fact_locator["fact_path"]).startswith("/content-bindings/")
            ]
            assert matching_evaluations, f"{case_id}: evaluator must include the content-binding COMPONENT fact"

            result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            try:
                assert result.exit_code == 0
                assert payload["error"] is None
                assert payload["assessment_outcome"] in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
            finally:
                _cleanup_drift_output_from_cli_payload(payload)

    assert content_component_counts["component-checksum-not-provided"] == content_component_counts["component-checksum-complete"]
    assert projection_component_counts["component-checksum-not-provided"] == 0
    assert projection_component_counts["component-checksum-complete"] > 0


def test_v2s3_ac08_per_fact_materiality_and_aggregate_precedence_are_exact() -> None:
    registry = _production_registry()
    policy = load_materiality_policy()

    with _representative_pair("no-change") as no_change:
        assessment = evaluate_materiality(load_v2_s2_artifact_pair(no_change.manifest_hash), registry, policy)
        assert assessment.outcome == "NO_OBSERVED_CHANGE"
    with _representative_pair("retrieved-at-only") as non_material:
        assessment = evaluate_materiality(load_v2_s2_artifact_pair(non_material.manifest_hash), registry, policy)
        assert assessment.outcome == "NON_MATERIAL_CHANGE"
    with _representative_pair("material-content") as material:
        assessment = evaluate_materiality(load_v2_s2_artifact_pair(material.manifest_hash), registry, policy)
        assert assessment.outcome == "MATERIAL_CHANGE"


def test_v2s3_ac09_unknown_unmatched_and_ambiguous_inputs_never_become_non_material() -> None:
    registry = _production_registry()
    policy = load_materiality_policy()

    with _representative_pair("no-change") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: diff["facts"].append(
                {
                    "difference_kind": "METADATA",
                    "fact_kind": "METADATA",
                    "subject_type": "SOURCE",
                    "subject_id": pair.source_id,
                    "fact_path": "/metadata/unlisted-path",
                    "classification": "CHANGED",
                    "before": {"present": True, "value": "before"},
                    "after": {"present": True, "value": "after"},
                    "provenance": {"baseline_origin": "REGISTRY_SOURCE_RECORD", "candidate_origin": "MANIFEST_CANDIDATE"},
                }
            ),
        )
        assessed = evaluate_materiality(load_v2_s2_artifact_pair(pair.manifest_hash), registry, policy)
        assert assessed.outcome == "MATERIAL_CHANGE"
        matched_rule_ids = {item.rule_id for item in assessed.evaluations if item.evaluation == "MATERIAL_CHANGE"}
        assert matched_rule_ids & {"MAT-METADATA-001", "MAT-CONSERVATIVE-DEFAULT-001"}

    with _representative_pair("no-change") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: _first_content_fact(diff).__setitem__("classification", "IMPOSSIBLE"),
            recompute_summary=False,
        )
        _assert_fact_invariant_failure(pair.manifest_hash, case_label="unknown-classification-is-invalid")


def test_v2s3_ac10_normative_no_change_non_material_material_and_historical_examples() -> None:
    registry = _production_registry()
    policy = load_materiality_policy()
    cases = {
        "no-change": "NO_OBSERVED_CHANGE",
        "retrieved-at-only": "NON_MATERIAL_CHANGE",
        "material-content": "MATERIAL_CHANGE",
    }
    for case_id, expected in cases.items():
        with _representative_pair(case_id) as pair:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            assert evaluate_materiality(typed_pair, registry, policy).outcome == expected
            result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            try:
                assert result.exit_code == 0
                assert result.cli_result.assessment_outcome == expected
            finally:
                _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_ac11_routes_follow_declared_actions_current_edges_dedupe_and_order() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        registry = _production_registry()
        policy = load_materiality_policy()
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing = route_impact(assessment, registry, rehearsal)
        dispositions = {item.action: item for item in routing.action_dispositions}
        assert dispositions["stage_diff"].disposition == "EVIDENCED_BY_VALIDATED_INPUT"
        assert dispositions["stage_diff"].route_ids == ()
        assert dispositions["rollback"].disposition == "NOT_PROPOSED_NO_PREDECESSOR"
        assert len(dispositions["block_consumer"].route_ids) == len(set(dispositions["block_consumer"].route_ids))
        assert all(route.proposal_only and route.approval_required and not route.executed for route in routing.routes)


def test_v2s3_ac12_all_routes_and_artifacts_are_unapproved_unexecuted_proposals() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        registry = _production_registry()
        policy = load_materiality_policy()
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing = route_impact(assessment, registry, rehearsal)
        assert all(route.proposal_only and route.approval_required and not route.executed for route in routing.routes)

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert payload["proposal_only"] is True
            assert payload["approval_required"] is True
            assert payload["approval_state"] == "NOT_GRANTED"
            assert payload["executed"] is False
            impact_path = REPO_ROOT / payload["impact_plan"]["path"]
            rollback_path = REPO_ROOT / payload["rollback_plan"]["path"]
            impact = json.loads(impact_path.read_text(encoding="utf-8"))
            rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
            assert impact["proposal_only"] is True and impact["approval_required"] is True and impact["executed"] is False
            assert rollback["proposal_only"] is True and rollback["approval_required"] is True and rollback["executed"] is False
        finally:
            _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_ac14_non_null_predecessor_lineage_and_record_bindings_are_exact() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            lineage = dict(rehearsal.lineage)
            required_lineage_keys = {
                "status",
                "rollback_source_record_binding_hash_basis",
                "current_source_id",
                "current_source_record_content_hash",
                "current_rollback_source_record_binding_hash",
                "current_declaration_refs",
                "predecessor_source_id",
                "predecessor_source_record_content_hash",
                "predecessor_rollback_source_record_binding_hash",
                "predecessor_declaration_refs",
                "chain",
            }
            assert set(lineage.keys()) == required_lineage_keys
            assert lineage["status"] == "PREDECESSOR_PRESENT"
            assert lineage["rollback_source_record_binding_hash_basis"] == ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS
            assert lineage["current_source_id"] == fixture.current_record["source_id"]
            assert lineage["current_source_record_content_hash"] == fixture.current_source_record_content_hash
            assert lineage["current_rollback_source_record_binding_hash"] == fixture.current_rollback_binding_hash
            assert lineage["predecessor_source_id"] == fixture.predecessor_record["source_id"]
            assert lineage["predecessor_source_record_content_hash"] == fixture.predecessor_source_record_content_hash
            assert lineage["predecessor_rollback_source_record_binding_hash"] == fixture.predecessor_rollback_binding_hash
            assert list(lineage["current_declaration_refs"]) == list(fixture.current_record["declaration_refs"])
            assert list(lineage["predecessor_declaration_refs"]) == list(fixture.predecessor_record["declaration_refs"])

            chain = list(lineage["chain"])
            assert [row["source_id"] for row in chain] == [fixture.current_record["source_id"], fixture.predecessor_record["source_id"]]
            assert chain[0]["source_record_content_hash"] == fixture.current_source_record_content_hash
            assert chain[1]["source_record_content_hash"] == fixture.predecessor_source_record_content_hash
            assert chain[0]["rollback_source_record_binding_hash"] == fixture.current_rollback_binding_hash
            assert chain[1]["rollback_source_record_binding_hash"] == fixture.predecessor_rollback_binding_hash


def test_v2s3_ac16_non_null_rollback_artifact_schema_hash_and_complete_bindings() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            artifact = fixture.rollback_artifact
            required_keys = _spec()["rollback_input_artifact_contract"]["schema"]["top_level_required_exact"]
            assert set(artifact.keys()) == set(required_keys)
            assert artifact["rollback_source_record_binding_hash_basis"] == ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS
            assert artifact["current_rollback_source_record_binding_hash"] == fixture.current_rollback_binding_hash
            assert artifact["predecessor_rollback_source_record_binding_hash"] == fixture.predecessor_rollback_binding_hash
            assert "registry_content_hash" not in artifact
            assert "current_source_record_content_hash" not in artifact
            assert "predecessor_source_record_content_hash" not in artifact
            assert fixture.rollback_artifact_path.name == f"rb-{artifact['artifact_content_hash']}.json"
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            assert rehearsal.rollback_artifact_status == "VERIFIED"
            assert rehearsal.rollback_artifact_registry_path == fixture.rollback_artifact_relpath
            assert rehearsal.rollback_artifact_content_hash == artifact["artifact_content_hash"]
            assert [row.status for row in rehearsal.integrity_checks] == ["PASS"] * 12
            assert [row.as_dict() for row in rehearsal.rollback_file_bindings] == artifact["file_bindings"]
            assert [row.as_dict() for row in rehearsal.rollback_preservation_bindings] == artifact["preservation_bindings"]


def test_v2s3_ac16_algorithmic_content_address_has_no_hash_fixpoint() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            assert fixture.current_rollback_binding_hash == fixture.provisional_current_binding_hash
            assert fixture.rollback_artifact_relpath == f"configs/sourceops/rollbacks/rb-{fixture.rollback_artifact['artifact_content_hash']}.json"
            assert fixture.rollback_artifact["artifact_content_hash"] == _self_excluding_hash(fixture.rollback_artifact, "artifact_content_hash")
            assert "current_source_record_content_hash" not in fixture.rollback_artifact
            assert "predecessor_source_record_content_hash" not in fixture.rollback_artifact
            assert "registry_content_hash" not in fixture.rollback_artifact

            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            assert rehearsal.rollback_artifact_registry_path == fixture.rollback_artifact_relpath
            assert rehearsal.rollback_artifact_content_hash == fixture.rollback_artifact["artifact_content_hash"]


def test_v2s3_ac16_normative_cycle_free_example_constants_reproduce_independently() -> None:
    normative = copy.deepcopy(
        _spec()["rollback_input_artifact_contract"]["rollback_source_record_binding"]["normative_cycle_free_example"]
    )
    base_registry = _registry()

    def _canonical_json_local(payload: Any) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

    def _self_hash_local(mapping: dict[str, Any], field: str) -> str:
        basis = copy.deepcopy(mapping)
        basis.pop(field, None)
        return hashlib.sha256(_canonical_json_local(basis)).hexdigest()

    def _canonical_lf_local(raw: bytes) -> bytes:
        text = raw.decode("utf-8")
        return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

    def _rollback_binding_hash_local(raw_source_record: dict[str, Any]) -> str:
        transformed = copy.deepcopy(raw_source_record)
        rollback = transformed.get("rollback")
        assert isinstance(rollback, dict), "rollback mapping is required"
        rollback["rollback_artifact"] = ROLLBACK_SOURCE_RECORD_BINDING_SENTINEL
        return hashlib.sha256(_canonical_json_local(transformed)).hexdigest()

    assert base_registry["registry_content_hash"] == normative["base_registry_content_hash"]

    source_records = copy.deepcopy(base_registry["source_records"])
    current_index = next(index for index, row in enumerate(source_records) if row["source_id"] == normative["base_current_source_id"])
    base_current = copy.deepcopy(source_records[current_index])
    current = copy.deepcopy(base_current)
    predecessor = copy.deepcopy(base_current)

    current["rollback"]["predecessor_source_id"] = normative["predecessor_source_id"]
    current["rollback"]["origin_reason"] = "synthetic non-null READY fixture"
    current["rollback"]["rollback_artifact"] = f"configs/sourceops/rollbacks/rb-{'0' * 64}.json"

    predecessor["source_id"] = normative["predecessor_source_id"]
    predecessor["display_name"] = normative["predecessor_display_name"]
    predecessor["lifecycle_state"] = "PINNED_HISTORICAL"
    predecessor["consumers"] = []
    predecessor["rollback"]["predecessor_source_id"] = None
    predecessor["rollback"]["rollback_artifact"] = "configs/sourceops/rollbacks/synthetic-predecessor-root.yaml"
    predecessor["rollback"]["origin_reason"] = "synthetic root predecessor"
    assert predecessor["rollback"]["immutable_predecessor_required"] is True

    current_declaration_refs = copy.deepcopy(normative["current_declaration_refs_exact"])
    predecessor_declaration_refs = copy.deepcopy(normative["predecessor_declaration_refs_exact"])
    current["declaration_refs"] = copy.deepcopy(current_declaration_refs)
    predecessor["declaration_refs"] = copy.deepcopy(predecessor_declaration_refs)
    assert current["declaration_refs"] == normative["current_declaration_refs_exact"]
    assert predecessor["declaration_refs"] == normative["predecessor_declaration_refs_exact"]

    provisional_current_binding_hash = _rollback_binding_hash_local(current)
    predecessor_binding_hash = _rollback_binding_hash_local(predecessor)
    assert provisional_current_binding_hash == normative["current_rollback_source_record_binding_hash"]
    assert predecessor_binding_hash == normative["predecessor_rollback_source_record_binding_hash"]

    file_bindings: list[dict[str, Any]] = []
    for index, (current_ref, predecessor_ref) in enumerate(zip(current_declaration_refs, predecessor_declaration_refs), start=1):
        current_path = current_ref["path"]
        predecessor_path = predecessor_ref["path"]
        current_canonical = _canonical_lf_local((REPO_ROOT / current_path).read_bytes())
        predecessor_canonical = _canonical_lf_local((REPO_ROOT / predecessor_path).read_bytes())
        file_bindings.append(
            {
                "binding_id": f"bind-{index:03d}",
                "predecessor_path": predecessor_path,
                "predecessor_content_byte_size": len(predecessor_canonical),
                "predecessor_canonical_lf_sha256": hashlib.sha256(predecessor_canonical).hexdigest(),
                "current_path": current_path,
                "current_content_byte_size": len(current_canonical),
                "current_canonical_lf_sha256": hashlib.sha256(current_canonical).hexdigest(),
            }
        )
    file_bindings = sorted(file_bindings, key=lambda row: row["binding_id"])
    assert file_bindings == normative["file_bindings_exact"]
    assert file_bindings[0]["binding_id"] == "bind-001"

    preservation_bindings: list[dict[str, Any]] = []
    for row in base_registry["preservation_rules"]:
        canonical = _canonical_lf_local((REPO_ROOT / row["path"]).read_bytes())
        preservation_bindings.append(
            {
                "rule_id": row["rule_id"],
                "path": row["path"],
                "content_byte_size": len(canonical),
                "canonical_lf_sha256": hashlib.sha256(canonical).hexdigest(),
            }
        )
    assert preservation_bindings == normative["preservation_bindings_exact"]

    artifact = {
        "schema": "raptor.sourceops.rollback_artifact.v1",
        "artifact_content_hash": "0" * 64,
        "hash_basis": "raptor.sourceops.rollback_artifact_content_hash.v1",
        "rollback_source_record_binding_hash_basis": ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS,
        "current_source_id": normative["base_current_source_id"],
        "current_rollback_source_record_binding_hash": provisional_current_binding_hash,
        "predecessor_source_id": normative["predecessor_source_id"],
        "predecessor_rollback_source_record_binding_hash": predecessor_binding_hash,
        "current_declaration_refs": current_declaration_refs,
        "predecessor_declaration_refs": predecessor_declaration_refs,
        "file_bindings": file_bindings,
        "preservation_bindings": preservation_bindings,
    }
    artifact["artifact_content_hash"] = _self_hash_local(artifact, "artifact_content_hash")
    assert artifact["artifact_content_hash"] == normative["artifact_content_hash"]

    for field_name, expected_value in normative["artifact_scalar_fields_exact"].items():
        assert artifact[field_name] == expected_value
    assert set(artifact.keys()) == set(_spec()["rollback_input_artifact_contract"]["schema"]["top_level_required_exact"])

    artifact_bytes_without_lf = _canonical_json_local(artifact)
    artifact_bytes_with_lf = artifact_bytes_without_lf + b"\n"
    assert len(artifact_bytes_without_lf) == normative["artifact_canonical_json_byte_size_without_trailing_lf"] == 3299
    assert len(artifact_bytes_with_lf) == normative["artifact_file_byte_size_with_one_trailing_lf"] == 3300

    final_registry_path = f"configs/sourceops/rollbacks/rb-{artifact['artifact_content_hash']}.json"
    assert final_registry_path == normative["final_registry_path"]
    current["rollback"]["rollback_artifact"] = final_registry_path
    final_current_binding_hash = _rollback_binding_hash_local(current)
    assert final_current_binding_hash == provisional_current_binding_hash == normative["current_rollback_source_record_binding_hash"]

    synthetic_registry = copy.deepcopy(base_registry)
    synthetic_records = synthetic_registry["source_records"]
    synthetic_records[current_index] = copy.deepcopy(current)
    synthetic_records.append(copy.deepcopy(predecessor))
    synthetic_registry["registry_content_hash"] = _self_hash_local(synthetic_registry, "registry_content_hash")

    current_source_record_hash = hashlib.sha256(_canonical_json_local(current)).hexdigest()
    predecessor_source_record_hash = hashlib.sha256(_canonical_json_local(predecessor)).hexdigest()
    assert current_source_record_hash == normative["current_source_record_content_hash_after_path"]
    assert predecessor_source_record_hash == normative["predecessor_source_record_content_hash"]
    assert synthetic_registry["registry_content_hash"] == normative["synthetic_registry_content_hash_after_path"]
    assert "registry_content_hash" not in artifact
    assert "current_source_record_content_hash" not in artifact
    assert "predecessor_source_record_content_hash" not in artifact

    rollback_path = REPO_ROOT / final_registry_path
    created_parent = False
    created_file = False
    if not rollback_path.parent.exists():
        rollback_path.parent.mkdir(parents=True, exist_ok=False)
        created_parent = True
    try:
        if rollback_path.exists():
            if rollback_path.read_bytes() != artifact_bytes_with_lf:
                pytest.fail(f"normative rollback fixture collision at {final_registry_path}")
        else:
            rollback_path.write_bytes(artifact_bytes_with_lf)
            created_file = True

        with _representative_pair("material-content") as pair:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            rehearsal = rehearse_rollback(typed_pair, Registry.from_mapping(synthetic_registry))
            expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
            assert rehearsal.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            assert rehearsal.rollback_artifact_registry_path == final_registry_path
            assert rehearsal.rollback_artifact_content_hash == artifact["artifact_content_hash"]
            assert [row.check for row in rehearsal.integrity_checks] == expected_checks
            assert [row.status for row in rehearsal.integrity_checks] == ["PASS"] * 12
    finally:
        if created_file:
            rollback_path.unlink(missing_ok=True)
        if created_parent:
            try:
                rollback_path.parent.rmdir()
            except OSError:
                pass


def test_v2s3_ac17_stable_rollback_blockers_publish_blocked_pair_and_exit_8(monkeypatch: pytest.MonkeyPatch) -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            fixture.rollback_artifact_path.unlink(missing_ok=True)
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome == "BLOCKED"
            assert rehearsal.reason_code == "ROLLBACK_ARTIFACT_MISSING"
            assert rehearsal.rollback_artifact_registry_path == fixture.rollback_artifact_relpath
            assert [row.check for row in rehearsal.integrity_checks] == _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
            assert [row.status for row in rehearsal.integrity_checks] == [
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
            ]

            drift_module = _require_drift_planning_module()
            source_record = next(item for item in fixture.registry.source_records if item.source_id == pair.source_id)
            monkeypatch.setattr(drift_module, "_load_and_validate_current_registry", lambda: (fixture.registry, fixture.raw_registry))
            monkeypatch.setattr(drift_module, "_validate_source_baseline", lambda _pair, _registry, _registry_dict: source_record)
            monkeypatch.setattr(
                drift_module,
                "load_materiality_policy",
                lambda: _policy_with_registry_hash(fixture.raw_registry["registry_content_hash"]),
            )
            plan_result = plan_drift(pair.manifest_hash)
            payload = plan_result.cli_result.as_dict()
            try:
                assert plan_result.exit_code == 8
                assert payload["run_status"] == "COMPLETED"
                assert payload["rollback_rehearsal_outcome"] == "BLOCKED"
                assert payload["error"] is None
                assert isinstance(payload["impact_plan"], dict)
                assert isinstance(payload["rollback_plan"], dict)
            finally:
                _cleanup_drift_output_from_cli_payload(payload)

        cli_result = _run_cli("plan-drift", "--manifest-hash", pair.manifest_hash)
        cli_payload = _parse_json_stdout(cli_result)
        assert cli_payload["command"] == "plan-drift"
        assert cli_result.returncode in {0, 2, 4, 5, 6, 7, 8, 70}


def test_v2s3_ac17_safe_blocker_fixtures_fail_only_at_targeted_integrity_check(monkeypatch: pytest.MonkeyPatch) -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            # Missing artifact on an otherwise valid non-null lineage.
            fixture.rollback_artifact_path.unlink(missing_ok=True)
            missing = rehearse_rollback(typed_pair, fixture.registry)
            assert missing.reason_code == "ROLLBACK_ARTIFACT_MISSING"
            assert [row.status for row in missing.integrity_checks] == [
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
            ]

            # Filename mismatch with safe canonical path and canonical bytes.
            filename_mismatch_relpath = f"configs/sourceops/rollbacks/rb-{'f' * 64}.json"
            filename_mismatch_path = REPO_ROOT / filename_mismatch_relpath
            filename_mismatch_path.write_bytes(fixture.rollback_artifact_bytes)
            try:
                current = copy.deepcopy(fixture.current_record)
                current["rollback"]["rollback_artifact"] = filename_mismatch_relpath
                filename_registry, filename_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, current)
                mismatch = rehearse_rollback(typed_pair, filename_registry)
                assert mismatch.reason_code == "ROLLBACK_ARTIFACT_FILENAME_HASH_MISMATCH"
                assert mismatch.rollback_artifact_registry_path == filename_mismatch_relpath

                # Binding mismatch after self-hash and filename are valid.
                tampered_artifact = copy.deepcopy(fixture.rollback_artifact)
                tampered_artifact["current_rollback_source_record_binding_hash"] = "1" * 64
                tampered_artifact["artifact_content_hash"] = _self_excluding_hash(tampered_artifact, "artifact_content_hash")
                tampered_relpath = f"configs/sourceops/rollbacks/rb-{tampered_artifact['artifact_content_hash']}.json"
                tampered_path = REPO_ROOT / tampered_relpath
                tampered_path.write_bytes(_canonical_json_bytes(tampered_artifact) + b"\n")
                try:
                    current_binding = copy.deepcopy(fixture.current_record)
                    current_binding["rollback"]["rollback_artifact"] = tampered_relpath
                    binding_registry, _binding_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, current_binding)
                    binding = rehearse_rollback(typed_pair, binding_registry)
                    assert binding.reason_code == "ROLLBACK_ARTIFACT_BINDING_MISMATCH"
                    assert [row.status for row in binding.integrity_checks][:7] == ["PASS"] * 6 + ["FAIL"]
                    assert all(row.status == "NOT_APPLICABLE" for row in binding.integrity_checks[7:])
                finally:
                    tampered_path.unlink(missing_ok=True)
            finally:
                filename_mismatch_path.unlink(missing_ok=True)

        # Full baseline mismatch is independent of rollback blocker partition.
        _rewrite_pair_leaf(
            pair,
            mutate_verification=lambda verification, _diff: verification["source_binding"].__setitem__("source_record_content_hash", "0" * 64),
            mutate_diff=lambda diff, _verification: diff["source_binding"].__setitem__("source_record_content_hash", "0" * 64),
            recompute_summary=False,
        )
        baseline = plan_drift(pair.manifest_hash)
        baseline_payload = baseline.cli_result.as_dict()
        assert baseline.exit_code == 5
        assert baseline_payload["error"] is not None
        assert baseline_payload["error"]["code"] == "DRIFT_BASELINE_BINDING_MISMATCH"
        assert baseline_payload["impact_plan"] is None
        assert baseline_payload["rollback_plan"] is None

        cli_result = _run_cli("plan-drift", "--manifest-hash", pair.manifest_hash)
        cli_payload = _parse_json_stdout(cli_result)
        assert cli_payload["command"] == "plan-drift"


def test_v2s3_ac18_ready_rehearsal_emits_only_inert_typed_operations() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            for op in rehearsal.proposed_operations:
                raw = op.as_dict()
                assert set(raw.keys()) == {
                    "operation_id",
                    "sequence",
                    "operation_type",
                    "source_path",
                    "target_path",
                    "expected_source_hash",
                    "expected_target_hash",
                    "preservation_rule_id",
                    "proposal_only",
                    "approval_required",
                    "approval_state",
                    "executed",
                }
                assert raw["proposal_only"] is True
                assert raw["approval_required"] is True
                assert raw["approval_state"] == "NOT_GRANTED"
                assert raw["executed"] is False
                forbidden = {"command", "shell", "script", "execute", "executable", "subprocess"}
                assert not forbidden.intersection(raw.keys())


def test_v2s3_ac18_algorithmic_ready_rehearsal_passes_all_checks_and_operation_types(monkeypatch: pytest.MonkeyPatch) -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
            assert [row.check for row in rehearsal.integrity_checks] == expected_checks
            assert [row.status for row in rehearsal.integrity_checks] == ["PASS"] * 12
            assert rehearsal.rollback_route_eligible is True

            file_binding_count = len(fixture.rollback_artifact["file_bindings"])
            expected_op_types = (
                ["REVALIDATE_INPUT_BINDINGS", "REVALIDATE_PRESERVATION_BOUNDARIES"]
                + ["RESTORE_DECLARATION_FROM_PREDECESSOR"] * file_binding_count
                + ["VERIFY_RESTORED_DECLARATION_HASH"] * file_binding_count
                + ["REQUEST_HUMAN_ADJUDICATION"]
            )
            assert [op.operation_type for op in rehearsal.proposed_operations] == expected_op_types

            drift_module = _require_drift_planning_module()
            source_record = next(item for item in fixture.registry.source_records if item.source_id == pair.source_id)
            monkeypatch.setattr(drift_module, "_load_and_validate_current_registry", lambda: (fixture.registry, fixture.raw_registry))
            monkeypatch.setattr(drift_module, "_validate_source_baseline", lambda _pair, _registry, _registry_dict: source_record)
            monkeypatch.setattr(
                drift_module,
                "load_materiality_policy",
                lambda: _policy_with_registry_hash(fixture.raw_registry["registry_content_hash"]),
            )
            result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            try:
                assert result.exit_code == 0
                assert payload["rollback_rehearsal_outcome"] == "READY_FOR_HUMAN_ADJUDICATION"
                impact = json.loads((REPO_ROOT / payload["impact_plan"]["path"]).read_text(encoding="utf-8"))
                rollback_disposition = next(item for item in impact["proposal"]["action_dispositions"] if item["action"] == "rollback")
                assert rollback_disposition["disposition"] == "PROPOSED"
                assert rollback_disposition["route_ids"] == [f"rollback:SOURCE:{pair.source_id}"]
            finally:
                _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_ac19_output_pair_schema_hash_path_cross_reference_and_observed_at() -> None:
    with _representative_pair("no-change") as pair:
        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code == 0
            impact_path = REPO_ROOT / payload["impact_plan"]["path"]
            rollback_path = REPO_ROOT / payload["rollback_plan"]["path"]
            impact_bytes = impact_path.read_bytes()
            rollback_bytes = rollback_path.read_bytes()
            assert impact_bytes == _canonical_json_bytes(json.loads(impact_bytes.decode("utf-8"))) + b"\n"
            assert rollback_bytes == _canonical_json_bytes(json.loads(rollback_bytes.decode("utf-8"))) + b"\n"

            impact = json.loads(impact_bytes.decode("utf-8"))
            rollback = json.loads(rollback_bytes.decode("utf-8"))
            source_binding = impact["input_binding"]["source"]
            assert "source_record_content_hash" in source_binding
            assert "rollback_source_record_binding_hash_basis" in source_binding
            assert "rollback_source_record_binding_hash" in source_binding
            assert source_binding["rollback_source_record_binding_hash_basis"] == ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS

            lineage = rollback["lineage"]
            assert "current_source_record_content_hash" in lineage
            assert "current_rollback_source_record_binding_hash" in lineage
            assert "rollback_source_record_binding_hash_basis" in lineage
            assert lineage["rollback_source_record_binding_hash_basis"] == ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS
            assert rollback["observed_at"] == pair.observed_at
            assert rollback["impact_plan_content_hash"] == impact["artifact_content_hash"]
            assert impact["artifact_content_hash"] == payload["impact_plan"]["content_hash"]
            assert rollback["artifact_content_hash"] == payload["rollback_plan"]["content_hash"]
            assert impact_path.name == f"impact-{impact['artifact_content_hash']}.json"
            assert rollback_path.name == f"rollback-{rollback['artifact_content_hash']}.json"
            assert impact["artifact_content_hash"] == _self_excluding_hash(impact, "artifact_content_hash")
            assert rollback["artifact_content_hash"] == _self_excluding_hash(rollback, "artifact_content_hash")
        finally:
            _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_ac22_public_models_api_errors_and_dependencies_are_closed_typed_immutable() -> None:
    policy = load_materiality_policy()
    model = importlib.import_module("raptor.sourceops.model")
    required_models = _spec()["typed_model_and_public_api_contract"]["required_public_models"]
    missing_models = [name for name in required_models if not hasattr(model, name)]
    assert not missing_models, f"missing required public models: {missing_models}"
    drift = _require_drift_planning_module()
    required_funcs = [entry["signature"].split("(", 1)[0] for entry in _spec()["typed_model_and_public_api_contract"]["required_public_functions"]]
    missing_funcs = [name for name in required_funcs if not hasattr(drift, name)]
    assert not missing_funcs, f"missing required public functions: {missing_funcs}"

    registry = _production_registry()
    with _representative_pair("no-change") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing = route_impact(assessment, registry, rehearsal)
        plan = plan_drift(pair.manifest_hash)
        payload = plan.cli_result.as_dict()
        try:
            assert assessment.outcome in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
            assert rehearsal.outcome in {"NOT_APPLICABLE", "READY_FOR_HUMAN_ADJUDICATION", "BLOCKED"}
            assert isinstance(routing.routes, tuple)
            assert plan.exit_code in {0, 8}
            assert payload["error"] is None
            cli_result = _run_cli("plan-drift", "--manifest-hash", pair.manifest_hash)
            cli_payload = _parse_json_stdout(cli_result)
            assert cli_payload["command"] == "plan-drift"
        finally:
            _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_fm03_artifact_byte_hash_and_filename_tampering_are_distinct() -> None:
    # Canonical-byte tamper.
    with _representative_pair("no-change") as pair:
        pair.verification_path.write_bytes(_canonical_json_bytes(pair.verification) + b" \n")
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_ARTIFACT_CANONICAL_BYTES_INVALID"

    # Filename/hash-segment tamper.
    with _representative_pair("no-change") as pair:
        renamed = pair.verification_path.with_name(f"v-{'f' * 64}.json")
        pair.verification_path.rename(renamed)
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) in {"DRIFT_ARTIFACT_FILENAME_HASH_MISMATCH", "DRIFT_INPUT_ARTIFACT_SET_INVALID"}

    # Declared hash tamper with matching filename.
    with _representative_pair("no-change") as pair:
        forged = copy.deepcopy(pair.verification)
        forged["artifact_content_hash"] = "f" * 64
        forged_path = pair.verification_path.with_name(f"v-{forged['artifact_content_hash']}.json")
        pair.verification_path.unlink(missing_ok=True)
        forged_path.write_bytes(_canonical_json_bytes(forged) + b"\n")
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_ARTIFACT_HASH_MISMATCH"


def test_v2s3_fm04_cross_paired_self_hashed_artifacts_are_rejected() -> None:
    with _representative_pair("no-change") as pair_a, _representative_pair("material-content") as pair_b:
        pair_a.diff_path.unlink(missing_ok=True)
        cross_paired_path = pair_a.diff_path.with_name(pair_b.diff_path.name)
        cross_paired_path.write_bytes(pair_b.diff_bytes)
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair_a.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_ARTIFACT_CROSS_BINDING_MISMATCH"


def test_v2s3_fm05_forged_fact_summary_tree_and_outcome_are_recomputed() -> None:
    with _representative_pair("material-content") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: (
                diff["summary"]["classifications"].__setitem__("UNCHANGED", diff["summary"]["total_facts"]),
                diff.__setitem__("stage_outcome", "OBSERVED_NO_DIFFERENCE"),
            ),
            recompute_summary=False,
        )
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_FACT_INVARIANT_INVALID"


def test_v2s3_fm09_policy_tamper_stale_binding_and_rule_ambiguity_exit_6() -> None:
    baseline = _planned_policy_mapping()
    with _representative_pair("no-change") as pair:
        manifest_hash = pair.manifest_hash

        tampered_hash = copy.deepcopy(baseline)
        tampered_hash["policy_version"] = "1.0.1"
        tampered_hash_bytes = yaml.safe_dump(tampered_hash, sort_keys=False, allow_unicode=True).encode("utf-8")
        with _temporary_file_bytes(POLICY_PATH, tampered_hash_bytes):
            with pytest.raises(Exception) as exc_info:
                load_materiality_policy()
            assert getattr(exc_info.value, "code", None) == "DRIFT_POLICY_HASH_MISMATCH"
            drift = plan_drift(manifest_hash)
            drift_payload = drift.cli_result.as_dict()
            assert drift.exit_code == 6
            assert drift_payload["error"] is not None
            assert drift_payload["error"]["code"] == "DRIFT_POLICY_HASH_MISMATCH"
            assert drift_payload["impact_plan"] is None
            assert drift_payload["rollback_plan"] is None

        stale_binding = copy.deepcopy(baseline)
        stale_binding["artifact_binding"]["diff_schema"] = "raptor.sourceops.forged_diff.v1"
        stale_binding["policy_content_hash"] = _policy_hash(stale_binding)
        stale_binding_bytes = yaml.safe_dump(stale_binding, sort_keys=False, allow_unicode=True).encode("utf-8")
        with _temporary_file_bytes(POLICY_PATH, stale_binding_bytes):
            with pytest.raises(Exception) as exc_info:
                load_materiality_policy()
            assert getattr(exc_info.value, "code", None) == "DRIFT_POLICY_BINDING_MISMATCH"
            drift = plan_drift(manifest_hash)
            drift_payload = drift.cli_result.as_dict()
            assert drift.exit_code == 6
            assert drift_payload["error"] is not None
            assert drift_payload["error"]["code"] == "DRIFT_POLICY_BINDING_MISMATCH"
            assert drift_payload["impact_plan"] is None
            assert drift_payload["rollback_plan"] is None

        ambiguous = copy.deepcopy(baseline)
        ambiguous["rules"][1]["priority"] = ambiguous["rules"][0]["priority"]
        ambiguous["policy_content_hash"] = _policy_hash(ambiguous)
        ambiguous_bytes = yaml.safe_dump(ambiguous, sort_keys=False, allow_unicode=True).encode("utf-8")
        with _temporary_file_bytes(POLICY_PATH, ambiguous_bytes):
            with pytest.raises(Exception) as exc_info:
                load_materiality_policy()
            assert getattr(exc_info.value, "code", None) == "DRIFT_POLICY_AMBIGUOUS"
            drift = plan_drift(manifest_hash)
            drift_payload = drift.cli_result.as_dict()
            assert drift.exit_code == 6
            assert drift_payload["error"] is not None
            assert drift_payload["error"]["code"] == "DRIFT_POLICY_AMBIGUOUS"
            assert drift_payload["impact_plan"] is None
            assert drift_payload["rollback_plan"] is None


def test_v2s3_fm10_unknown_fact_is_invalid_and_unfamiliar_valid_role_is_material() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()

    with _representative_pair("no-change") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: _first_content_fact(diff).__setitem__("classification", "UNKNOWN"),
            recompute_summary=False,
        )
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_FACT_INVARIANT_INVALID"

    with _representative_pair("component-complete") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_verification=lambda verification, _diff: [
                file_row.__setitem__("component_ids", []) for file_row in verification["input_tree"]["files"]
            ],
            mutate_diff=lambda diff, _verification: next(
                fact["after"].__setitem__("value", "UNFAMILIAR_COMPONENT_ROLE")
                for fact in diff["facts"]
                if fact["fact_kind"] == "COMPONENT" and fact["fact_path"].endswith("/source_role")
            ),
        )
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        assert all(list(file_row["component_ids"]) == [] for file_row in typed_pair.verification["input_tree"]["files"])
        assessment = evaluate_materiality(typed_pair, registry, policy)
        assert assessment.outcome == "MATERIAL_CHANGE"
        role_evaluations = [
            item
            for item in assessment.evaluations
            if item.fact_locator["fact_kind"] == "COMPONENT" and str(item.fact_locator["fact_path"]).endswith("/source_role")
        ]
        assert role_evaluations
        changed_role_evaluations = [item for item in role_evaluations if item.fact_locator["classification"] == "CHANGED"]
        assert changed_role_evaluations
        assert all(item.evaluation == "MATERIAL_CHANGE" for item in changed_role_evaluations)
        assert {item.rule_id for item in changed_role_evaluations} & {"MAT-COMPONENT-001", "MAT-CONSERVATIVE-DEFAULT-001"}


def test_v2s3_fm10_forged_component_checksum_content_baseline_is_rejected_for_both_projection_modes() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()

    projection_cases = ("component-checksum-not-provided", "component-checksum-complete")
    for case_id in projection_cases:
        with _representative_pair(case_id) as pair:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            assessment = evaluate_materiality(typed_pair, registry, policy)
            assert assessment.outcome in {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
            result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            try:
                assert result.exit_code == 0
                assert payload["error"] is None
            finally:
                _cleanup_drift_output_from_cli_payload(payload)

    def _mutate_baseline(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        fact = _component_checksum_content_facts(diff)[0]
        fact["before"]["value"] = "0" * 64

    def _mutate_after(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        fact = _component_checksum_content_facts(diff)[0]
        fact["after"]["value"] = "f" * 64

    def _mutate_unknown_component(diff: dict[str, Any], _verification: dict[str, Any]) -> None:
        fact = _component_checksum_content_facts(diff)[0]
        fact["subject_id"] = "unknown-component-checksum-target"

    for case_id in projection_cases:
        for mutation_name, mutator in (
            ("forged-baseline", _mutate_baseline),
            ("forged-after", _mutate_after),
            ("unknown-component", _mutate_unknown_component),
        ):
            with _representative_pair(case_id) as pair:
                _rewrite_pair_leaf(pair, mutate_diff=mutator)
                with pytest.raises(Exception) as exc_info:
                    load_v2_s2_artifact_pair(pair.manifest_hash)
                assert getattr(exc_info.value, "code", None) == "DRIFT_FACT_INVARIANT_INVALID"
                _assert_fact_invariant_failure(pair.manifest_hash, case_label=f"{case_id}:{mutation_name}")


def test_v2s3_fm11_no_change_and_non_material_change_remain_distinct() -> None:
    registry = _production_registry()
    policy = load_materiality_policy()
    with _representative_pair("no-change") as no_change_pair, _representative_pair("retrieved-at-only") as non_material_pair:
        no_change = evaluate_materiality(load_v2_s2_artifact_pair(no_change_pair.manifest_hash), registry, policy)
        non_material = evaluate_materiality(load_v2_s2_artifact_pair(non_material_pair.manifest_hash), registry, policy)
        assert no_change.outcome == "NO_OBSERVED_CHANGE"
        assert non_material.outcome == "NON_MATERIAL_CHANGE"
        assert no_change.outcome != non_material.outcome
        no_change_counts = dict(no_change.counts)
        non_material_counts = dict(non_material.counts)
        assert no_change_counts["NO_OBSERVED_CHANGE"] == len(no_change.evaluations)
        assert no_change_counts["NON_MATERIAL_CHANGE"] == 0
        assert no_change_counts["MATERIAL_CHANGE"] == 0
        assert non_material_counts["NO_OBSERVED_CHANGE"] == len(non_material.evaluations) - 1
        assert non_material_counts["NON_MATERIAL_CHANGE"] == 1
        assert non_material_counts["MATERIAL_CHANGE"] == 0
        assert {row.rule_id for row in no_change.evaluations} == {"OBS-UNCHANGED-001"}
        assert {row.rationale_id for row in no_change.evaluations} == {"OBSERVATION_EQUAL"}
        changed_retrieved_at = [
            row
            for row in non_material.evaluations
            if row.fact_locator["fact_path"] == "/release/retrieved_at" and row.evaluation == "NON_MATERIAL_CHANGE"
        ]
        assert len(changed_retrieved_at) == 1
        assert changed_retrieved_at[0].rule_id == "NONMAT-RETRIEVED-AT-001"
        assert changed_retrieved_at[0].rationale_id == "RETRIEVAL_TIMESTAMP_ONLY"


def test_v2s3_fm12_retrieved_at_truth_table_uses_freshness_and_historical_context() -> None:
    policy = load_materiality_policy()
    with _representative_pair("retrieved-at-only") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)

        base_mapping = _registry()
        base_registry = Registry.from_mapping(base_mapping)
        non_material = evaluate_materiality(typed_pair, base_registry, policy)

        freshness_mapping = copy.deepcopy(base_mapping)
        source = next(row for row in freshness_mapping["source_records"] if row["source_id"] == pair.source_id)
        linked_consumers = set(source["consumers"])
        toggle = True
        for consumer in freshness_mapping["consumers"]:
            if consumer["consumer_id"] in linked_consumers:
                consumer["freshness_required"] = toggle
                toggle = not toggle
        freshness_mapping["registry_content_hash"] = _registry_content_hash(freshness_mapping)
        freshness_registry = Registry.from_mapping(freshness_mapping)
        material_freshness = evaluate_materiality(typed_pair, freshness_registry, policy)

        historical_mapping = copy.deepcopy(base_mapping)
        historical_source = next(row for row in historical_mapping["source_records"] if row["source_id"] == pair.source_id)
        historical_source["lifecycle_state"] = "PINNED_HISTORICAL"
        historical_mapping["registry_content_hash"] = _registry_content_hash(historical_mapping)
        historical_registry = Registry.from_mapping(historical_mapping)
        material_historical = evaluate_materiality(typed_pair, historical_registry, policy)

        def _retrieved_at_eval(assessment: Any) -> Any:
            for row in assessment.evaluations:
                if row.fact_locator["fact_path"] == "/release/retrieved_at":
                    return row
            raise AssertionError("retrieved_at fact evaluation missing")

        non_material_row = _retrieved_at_eval(non_material)
        freshness_row = _retrieved_at_eval(material_freshness)
        historical_row = _retrieved_at_eval(material_historical)

        assert non_material.outcome == "NON_MATERIAL_CHANGE"
        assert material_freshness.outcome == "MATERIAL_CHANGE"
        assert material_historical.outcome == "MATERIAL_CHANGE"
        assert non_material_row.rule_id == "NONMAT-RETRIEVED-AT-001"
        assert non_material_row.rationale_id == "RETRIEVAL_TIMESTAMP_ONLY"
        assert freshness_row.rule_id == "MAT-FRESHNESS-RETRIEVAL-001"
        assert freshness_row.rationale_id == "FRESHNESS_CONTEXT_CHANGED"
        assert historical_row.rule_id == "MAT-PINNED-HISTORICAL-001"
        assert historical_row.rationale_id == "PINNED_HISTORY_CHANGED"


def test_v2s3_fm13_action_approval_execution_and_candidate_owner_laundering_fail() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()
    with _representative_pair("material-content") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: next(
                fact["after"].__setitem__("value", "candidate-owner-laundering-probe")
                for fact in diff["facts"]
                if fact["fact_path"] == "/identity/owner"
            ),
        )
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing = route_impact(assessment, registry, rehearsal)
        for route in routing.routes:
            assert route.proposal_only is True
            assert route.approval_required is True
            assert route.approval_state == "NOT_GRANTED"
            assert route.executed is False
            if route.target["type"] == "CONSUMER":
                expected_owner = next(item.owner for item in registry.consumers if item.consumer_id == route.target["id"])
                assert route.target["owner"] == expected_owner

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert payload["error"] is None
            impact_path = REPO_ROOT / payload["impact_plan"]["path"]
            impact_bytes = impact_path.read_bytes()
            assert impact_bytes == _canonical_json_bytes(json.loads(impact_bytes.decode("utf-8"))) + b"\n"
            impact = json.loads(impact_bytes.decode("utf-8"))
            assert all(route["approval_state"] == "NOT_GRANTED" and route["executed"] is False for route in impact["proposal"]["routes"])
            owners_by_consumer = {item.consumer_id: item.owner for item in registry.consumers}
            current_owner = next(item.owner for item in registry.source_records if item.source_id == pair.source_id)
            for route in impact["proposal"]["routes"]:
                target = route["target"]
                if target["type"] == "CONSUMER":
                    assert target["owner"] == owners_by_consumer[target["id"]]
                elif target["type"] == "SOURCE":
                    assert target["owner"] == current_owner
            assert "candidate-owner-laundering-probe" not in impact_bytes.decode("utf-8")
        finally:
            _cleanup_drift_output_from_cli_payload(payload)


def test_v2s3_fm15_route_reason_union_dedupe_and_order_are_byte_deterministic() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()
    with _representative_pair("material-content") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: next(
                fact["after"].__setitem__("value", "second-material-reason-owner")
                for fact in diff["facts"]
                if fact["fact_path"] == "/identity/owner"
            ),
        )
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing_a = route_impact(assessment, registry, rehearsal)
        perturbed_assessment = replace(assessment, evaluations=tuple(reversed(assessment.evaluations)))
        routing_b = route_impact(perturbed_assessment, registry, rehearsal)
        assert [route.route_id for route in routing_a.routes] == [route.route_id for route in routing_b.routes]
        for route, perturbed_route in zip(routing_a.routes, routing_b.routes):
            assert list(route.reason_fact_ids) == list(dict.fromkeys(route.reason_fact_ids))
            assert list(route.reason_rule_ids) == list(dict.fromkeys(route.reason_rule_ids))
            assert len(route.reason_rule_ids) >= 1
            assert route.reason_rule_ids == perturbed_route.reason_rule_ids
            assert set(route.reason_fact_ids) == set(perturbed_route.reason_fact_ids)


def test_v2s3_fm16_stage_diff_is_evidenced_not_executed_or_routed() -> None:
    policy = load_materiality_policy()
    registry = _production_registry()
    cases = {
        "no-change": "NO_OBSERVED_CHANGE",
        "retrieved-at-only": "NON_MATERIAL_CHANGE",
        "material-content": "MATERIAL_CHANGE",
    }
    for case_id, expected_outcome in cases.items():
        with _representative_pair(case_id) as pair:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            assessment = evaluate_materiality(typed_pair, registry, policy)
            rehearsal = rehearse_rollback(typed_pair, registry)
            routing = route_impact(assessment, registry, rehearsal)
            assert assessment.outcome == expected_outcome
            stage_diff = next(item for item in routing.action_dispositions if item.action == "stage_diff")
            assert stage_diff.disposition == "EVIDENCED_BY_VALIDATED_INPUT"
            assert stage_diff.reason_id == "VALIDATED_V2_S2_DIFF_PRESENT"
            assert stage_diff.route_ids == ()


def test_v2s3_fm18_missing_non_null_rollback_artifact_is_blocked_exit_8(monkeypatch: pytest.MonkeyPatch) -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            fixture.rollback_artifact_path.unlink(missing_ok=True)
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome == "BLOCKED"
            assert rehearsal.reason_code == "ROLLBACK_ARTIFACT_MISSING"
            assert rehearsal.rollback_artifact_registry_path == fixture.rollback_artifact_relpath
            assert rehearsal.rollback_artifact_status == "BLOCKED"
            assert rehearsal.rollback_artifact_content_hash is None
            expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
            assert [row.check for row in rehearsal.integrity_checks] == expected_checks
            assert [row.status for row in rehearsal.integrity_checks] == [
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
            ]

            drift_module = _require_drift_planning_module()
            source_record = next(item for item in fixture.registry.source_records if item.source_id == pair.source_id)
            monkeypatch.setattr(drift_module, "_load_and_validate_current_registry", lambda: (fixture.registry, fixture.raw_registry))
            monkeypatch.setattr(drift_module, "_validate_source_baseline", lambda _pair, _registry, _registry_dict: source_record)
            monkeypatch.setattr(
                drift_module,
                "load_materiality_policy",
                lambda: _policy_with_registry_hash(fixture.raw_registry["registry_content_hash"]),
            )
            planned = plan_drift(pair.manifest_hash)
            planned_payload = planned.cli_result.as_dict()
            try:
                assert planned.exit_code == 8
                assert planned_payload["rollback_rehearsal_outcome"] == "BLOCKED"
                assert planned_payload["impact_plan"] is not None
                assert planned_payload["rollback_plan"] is not None
            finally:
                _cleanup_drift_output_from_cli_payload(planned_payload)

        cli_result = _run_cli("plan-drift", "--manifest-hash", pair.manifest_hash)
        cli_payload = _parse_json_stdout(cli_result)
        assert cli_payload["command"] == "plan-drift"
        assert cli_result.returncode in {0, 2, 4, 5, 6, 7, 8, 70}


def test_v2s3_fm19_unsafe_tampered_or_unavailable_rollback_inputs_select_first_blocker() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]

            unsafe_current = copy.deepcopy(fixture.current_record)
            unsafe_current["rollback"]["rollback_artifact"] = "../unsafe/rb-0000000000000000000000000000000000000000000000000000000000000000.json"
            unsafe_registry, _unsafe_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, unsafe_current)
            unsafe = rehearse_rollback(typed_pair, unsafe_registry)
            assert unsafe.reason_code == "ROLLBACK_PATH_INVALID"
            assert [row.check for row in unsafe.integrity_checks] == expected_checks
            assert [row.status for row in unsafe.integrity_checks] == ["PASS", "PASS", "PASS", "FAIL"] + ["NOT_APPLICABLE"] * 8
            assert unsafe.proposed_operations == ()

            filename_mismatch_relpath = f"configs/sourceops/rollbacks/rb-{'e' * 64}.json"
            filename_mismatch_path = REPO_ROOT / filename_mismatch_relpath
            filename_mismatch_path.write_bytes(fixture.rollback_artifact_bytes)
            try:
                filename_current = copy.deepcopy(fixture.current_record)
                filename_current["rollback"]["rollback_artifact"] = filename_mismatch_relpath
                filename_registry, _filename_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, filename_current)
                filename = rehearse_rollback(typed_pair, filename_registry)
                assert filename.reason_code == "ROLLBACK_ARTIFACT_FILENAME_HASH_MISMATCH"
                assert [row.check for row in filename.integrity_checks] == expected_checks
                assert [row.status for row in filename.integrity_checks] == ["PASS"] * 5 + ["FAIL"] + ["NOT_APPLICABLE"] * 6
                assert filename.proposed_operations == ()
            finally:
                filename_mismatch_path.unlink(missing_ok=True)

            tampered = copy.deepcopy(fixture.rollback_artifact)
            tampered["current_rollback_source_record_binding_hash"] = "2" * 64
            tampered["artifact_content_hash"] = _self_excluding_hash(tampered, "artifact_content_hash")
            tampered_relpath = f"configs/sourceops/rollbacks/rb-{tampered['artifact_content_hash']}.json"
            tampered_path = REPO_ROOT / tampered_relpath
            tampered_path.write_bytes(_canonical_json_bytes(tampered) + b"\n")
            try:
                tampered_current = copy.deepcopy(fixture.current_record)
                tampered_current["rollback"]["rollback_artifact"] = tampered_relpath
                tampered_registry, _tampered_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, tampered_current)
                tampered_result = rehearse_rollback(typed_pair, tampered_registry)
                assert tampered_result.reason_code == "ROLLBACK_ARTIFACT_BINDING_MISMATCH"
                assert [row.check for row in tampered_result.integrity_checks] == expected_checks
                assert [row.status for row in tampered_result.integrity_checks] == ["PASS"] * 6 + ["FAIL"] + ["NOT_APPLICABLE"] * 5
                assert tampered_result.proposed_operations == ()
            finally:
                tampered_path.unlink(missing_ok=True)


def test_v2s3_fm20_preservation_overlap_blocks_every_restore_operation() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            preserved_path = fixture.rollback_artifact["preservation_bindings"][0]["path"]
            ancestor_path = str(Path(preserved_path).parent).replace("\\", "/")
            descendant_path = preserved_path + "/shadow/leaf.yaml"
            conflict_paths = (
                ("equal", preserved_path),
                ("ancestor", ancestor_path),
                ("descendant", descendant_path),
            )
            for _label, conflicted_path in conflict_paths:
                overlap = copy.deepcopy(fixture.rollback_artifact)
                overlap["file_bindings"][0]["current_path"] = conflicted_path
                overlap["artifact_content_hash"] = _self_excluding_hash(overlap, "artifact_content_hash")
                overlap_relpath = f"configs/sourceops/rollbacks/rb-{overlap['artifact_content_hash']}.json"
                overlap_path = REPO_ROOT / overlap_relpath
                overlap_path.write_bytes(_canonical_json_bytes(overlap) + b"\n")
                try:
                    overlap_current = copy.deepcopy(fixture.current_record)
                    overlap_current["rollback"]["rollback_artifact"] = overlap_relpath
                    overlap_registry, overlap_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, overlap_current)
                    rehearsal = rehearse_rollback(typed_pair, overlap_registry)
                    assert overlap_raw["source_records"][-1]["source_id"] == fixture.predecessor_record["source_id"]
                    assert rehearsal.reason_code == "ROLLBACK_PRESERVATION_CONFLICT"
                    assert rehearsal.rollback_artifact_registry_path == overlap_relpath
                    assert rehearsal.proposed_operations == ()
                finally:
                    overlap_path.unlink(missing_ok=True)


def test_v2s3_fm20_preservation_conflict_reports_exact_execution_status_vector() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            overlap = copy.deepcopy(fixture.rollback_artifact)
            overlap["file_bindings"][0]["current_path"] = overlap["preservation_bindings"][0]["path"]
            overlap["artifact_content_hash"] = _self_excluding_hash(overlap, "artifact_content_hash")
            overlap_relpath = f"configs/sourceops/rollbacks/rb-{overlap['artifact_content_hash']}.json"
            overlap_path = REPO_ROOT / overlap_relpath
            overlap_path.write_bytes(_canonical_json_bytes(overlap) + b"\n")
            try:
                overlap_current = copy.deepcopy(fixture.current_record)
                overlap_current["rollback"]["rollback_artifact"] = overlap_relpath
                overlap_registry, _overlap_raw = _mutated_registry_with_non_null_source(fixture.registry, fixture.raw_registry, overlap_current)
                rehearsal = rehearse_rollback(typed_pair, overlap_registry)
                assert rehearsal.reason_code == "ROLLBACK_PRESERVATION_CONFLICT"
                expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
                assert [row.check for row in rehearsal.integrity_checks] == expected_checks
                assert [row.status for row in rehearsal.integrity_checks] == [
                    "PASS",
                    "PASS",
                    "PASS",
                    "PASS",
                    "PASS",
                    "PASS",
                    "PASS",
                    "NOT_APPLICABLE",
                    "NOT_APPLICABLE",
                    "NOT_APPLICABLE",
                    "FAIL",
                    "NOT_APPLICABLE",
                ]
                assert rehearsal.proposed_operations == ()
            finally:
                overlap_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("blocker_code", "mutation_kind", "expected_statuses"),
    (
        (
            "ROLLBACK_FILE_BINDING_INVALID",
            "file_binding_invalid",
            (
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "PASS",
                "NOT_APPLICABLE",
            ),
        ),
        (
            "ROLLBACK_CURRENT_CONTENT_MISMATCH",
            "current_content_mismatch",
            (
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "NOT_APPLICABLE",
                "PASS",
                "NOT_APPLICABLE",
            ),
        ),
        (
            "ROLLBACK_PREDECESSOR_CONTENT_UNAVAILABLE",
            "predecessor_content_unavailable",
            (
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "NOT_APPLICABLE",
                "PASS",
                "NOT_APPLICABLE",
            ),
        ),
        (
            "ROLLBACK_PRESERVATION_BINDING_MISMATCH",
            "preservation_binding_mismatch",
            (
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "PASS",
                "FAIL",
                "PASS",
                "NOT_APPLICABLE",
            ),
        ),
    ),
)
def test_v2s3_fm20_post_preservation_target_gate_blockers_report_exact_12_row_vectors(
    blocker_code: str,
    mutation_kind: str,
    expected_statuses: tuple[str, ...],
) -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            baseline = rehearse_rollback(typed_pair, fixture.registry)
            assert baseline.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            assert [row.status for row in baseline.integrity_checks] == ["PASS"] * 12

            mutated_artifact = copy.deepcopy(fixture.rollback_artifact)
            assert mutated_artifact["file_bindings"], "synthetic rollback fixture must include at least one file binding"
            assert mutated_artifact["preservation_bindings"], "synthetic rollback fixture must include at least one preservation binding"
            if mutation_kind == "file_binding_invalid":
                mutated_artifact["file_bindings"][0]["binding_id"] = "zz-v2s3-fm20-invalid-binding-order"
            elif mutation_kind == "current_content_mismatch":
                mutated_artifact["file_bindings"][0]["current_content_byte_size"] += 1
            elif mutation_kind == "predecessor_content_unavailable":
                mutated_artifact["file_bindings"][0]["predecessor_content_byte_size"] += 1
            elif mutation_kind == "preservation_binding_mismatch":
                mutated_artifact["preservation_bindings"][0]["rule_id"] = "v2s3-fm20-preservation-binding-mismatch"
            else:
                pytest.fail(f"unsupported mutation kind: {mutation_kind!r}")

            mutated_artifact["artifact_content_hash"] = _self_excluding_hash(mutated_artifact, "artifact_content_hash")
            mutated_relpath = f"configs/sourceops/rollbacks/rb-{mutated_artifact['artifact_content_hash']}.json"
            mutated_path = REPO_ROOT / mutated_relpath
            prior_bytes = mutated_path.read_bytes() if mutated_path.exists() else None
            mutated_path.write_bytes(_canonical_json_bytes(mutated_artifact) + b"\n")
            try:
                mutated_current = copy.deepcopy(fixture.current_record)
                mutated_current["rollback"]["rollback_artifact"] = mutated_relpath
                mutated_registry, _mutated_raw = _mutated_registry_with_non_null_source(
                    fixture.registry,
                    fixture.raw_registry,
                    mutated_current,
                )
                rehearsal = rehearse_rollback(typed_pair, mutated_registry)
                expected_checks = _spec()["rollback_rehearsal_contract"]["performed_integrity_check"]["exact_checks"]
                assert rehearsal.outcome == "BLOCKED"
                assert rehearsal.reason_code == blocker_code
                assert rehearsal.rollback_route_eligible is False
                assert rehearsal.proposed_operations == ()
                assert rehearsal.rollback_artifact_registry_path == mutated_relpath
                assert rehearsal.rollback_artifact_status == "BLOCKED"
                assert rehearsal.rollback_artifact_content_hash == mutated_artifact["artifact_content_hash"]
                assert rehearsal.rollback_file_bindings == ()
                assert rehearsal.rollback_preservation_bindings == ()
                assert rehearsal.blocker is not None
                assert rehearsal.blocker.code == blocker_code
                assert [row.check for row in rehearsal.integrity_checks] == expected_checks
                assert [row.status for row in rehearsal.integrity_checks] == list(expected_statuses)
                status_by_check = {row.check: row.status for row in rehearsal.integrity_checks}
                assert status_by_check["PRESERVATION_TARGETS_CLEAR"] == "PASS"
                assert status_by_check["INPUTS_IMMUTABLE"] == "NOT_APPLICABLE"
                if blocker_code in {"ROLLBACK_FILE_BINDING_INVALID", "ROLLBACK_PRESERVATION_BINDING_MISMATCH"}:
                    assert rehearsal.blocker.subject == mutated_relpath
                elif blocker_code == "ROLLBACK_CURRENT_CONTENT_MISMATCH":
                    assert rehearsal.blocker.subject == mutated_artifact["file_bindings"][0]["current_path"]
                elif blocker_code == "ROLLBACK_PREDECESSOR_CONTENT_UNAVAILABLE":
                    assert rehearsal.blocker.subject == mutated_artifact["file_bindings"][0]["predecessor_path"]
            finally:
                if prior_bytes is None:
                    mutated_path.unlink(missing_ok=True)
                else:
                    mutated_path.write_bytes(prior_bytes)


def test_v2s3_fm22_explicit_null_omission_mapping_order_and_sequence_order_are_exact() -> None:
    policy = load_materiality_policy()
    assert policy.policy_id == "raptor-v2-s3-materiality-v1"
    assert policy.policy_content_hash == _policy_hash(_planned_policy_mapping())

    with _representative_pair("no-change") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        source_fact = next(fact for fact in pair.diff["facts"] if fact["subject_type"] == "SOURCE" and fact["fact_path"] == "/release/release_date")
        assert source_fact["before"]["present"] is True
        assert "value" in source_fact["before"]

        root_rehearsal = rehearse_rollback(typed_pair, _production_registry())
        assert root_rehearsal.outcome == "NOT_APPLICABLE"
        assert root_rehearsal.reason_code == "NO_PREDECESSOR"
        root_lineage = dict(root_rehearsal.lineage)
        assert root_lineage["predecessor_source_id"] is None
        assert root_lineage["predecessor_source_record_content_hash"] is None
        assert root_lineage["predecessor_rollback_source_record_binding_hash"] is None

        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert fixture.rollback_artifact["rollback_source_record_binding_hash_basis"] == ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS
            assert "current_source_record_content_hash" not in fixture.rollback_artifact
            assert rehearsal.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            assert [row.status for row in rehearsal.integrity_checks] == ["PASS"] * 12

            reordered = copy.deepcopy(fixture.rollback_artifact)
            reordered["preservation_bindings"] = list(reversed(reordered["preservation_bindings"]))
            reordered["artifact_content_hash"] = _self_excluding_hash(reordered, "artifact_content_hash")
            reordered_relpath = f"configs/sourceops/rollbacks/rb-{reordered['artifact_content_hash']}.json"
            reordered_path = REPO_ROOT / reordered_relpath
            reordered_path.write_bytes(_canonical_json_bytes(reordered) + b"\n")
            try:
                reordered_current = copy.deepcopy(fixture.current_record)
                reordered_current["rollback"]["rollback_artifact"] = reordered_relpath
                reordered_registry, _reordered_raw = _mutated_registry_with_non_null_source(
                    fixture.registry,
                    fixture.raw_registry,
                    reordered_current,
                )
                reordered_rehearsal = rehearse_rollback(typed_pair, reordered_registry)
                assert reordered_rehearsal.reason_code == "ROLLBACK_PRESERVATION_BINDING_MISMATCH"
                assert reordered_rehearsal.proposed_operations == ()
            finally:
                reordered_path.unlink(missing_ok=True)

        first = plan_drift(pair.manifest_hash)
        first_payload = first.cli_result.as_dict()
        second = plan_drift(pair.manifest_hash)
        second_payload = second.cli_result.as_dict()
        try:
            assert first_payload["error"] is None
            assert second_payload["error"] is None
            impact_bytes = (REPO_ROOT / first_payload["impact_plan"]["path"]).read_bytes()
            rollback_bytes = (REPO_ROOT / first_payload["rollback_plan"]["path"]).read_bytes()
            assert impact_bytes == _canonical_json_bytes(json.loads(impact_bytes.decode("utf-8"))) + b"\n"
            assert rollback_bytes == _canonical_json_bytes(json.loads(rollback_bytes.decode("utf-8"))) + b"\n"
            assert first_payload["impact_plan"]["content_hash"] == second_payload["impact_plan"]["content_hash"]
            assert first_payload["rollback_plan"]["content_hash"] == second_payload["rollback_plan"]["content_hash"]
        finally:
            _cleanup_drift_output_from_cli_payload(first_payload)
            _cleanup_drift_output_from_cli_payload(second_payload)

        _rewrite_pair_leaf(
            pair,
            mutate_diff=lambda diff, _verification: _first_content_fact(diff)["before"].pop("value", None),
            recompute_summary=False,
        )
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(pair.manifest_hash)
        assert getattr(exc_info.value, "code", None) == "DRIFT_FACT_INVARIANT_INVALID"
        failed = plan_drift(pair.manifest_hash)
        failed_payload = failed.cli_result.as_dict()
        assert failed.exit_code == 2
        assert failed_payload["error"] is not None
        assert failed_payload["error"]["code"] == "DRIFT_FACT_INVARIANT_INVALID"
        assert failed_payload["impact_plan"] is None
        assert failed_payload["rollback_plan"] is None
