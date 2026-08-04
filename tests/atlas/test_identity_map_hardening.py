"""Regression tests for independent checker findings on the identity mapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import raptor.atlas.identity_map as identity_map
from raptor.atlas.model import AtlasIdentityMapError
from tests.atlas.test_identity_map import _load, _synthetic_pack, _write_tree


def _rehash_map(tree: dict) -> None:
    tree["manifest"]["map_content_hash"] = identity_map.identity_map_content_hash(
        tree["manifest"]
    )
    tree["map"].write_text(
        yaml.safe_dump(tree["manifest"], sort_keys=False), encoding="utf-8"
    )


def _rehash_lock(tree: dict) -> None:
    tree["lock_data"]["lock_content_hash"] = identity_map.identity_map_lock_content_hash(
        tree["lock_data"]
    )
    tree["lock"].write_text(
        yaml.safe_dump(tree["lock_data"], sort_keys=False), encoding="utf-8"
    )


def test_lock_rejects_identity_bearing_extra_field(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path)
    tree["lock_data"]["raw_identity_string"] = "synthetic-secret"
    _rehash_lock(tree)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


def test_map_and_record_schemas_reject_extra_fields(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path)
    tree["manifest"]["unexpected"] = "value"
    _rehash_map(tree)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)

    tree = _write_tree(tmp_path / "record")
    tree["manifest"]["records"][0]["unexpected"] = "value"
    _rehash_map(tree)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


def test_stored_record_fields_are_immutable(tmp_path: Path) -> None:
    mapper = _load(_write_tree(tmp_path))
    stored = mapper.records["raw-1"]
    with pytest.raises((AttributeError, TypeError)):
        stored.raw_identity_string = "changed"


def test_reference_binding_must_match_pack_pins(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path)
    tree["manifest"]["reference_binding"]["transcript"] = "SYN_TX999.1"
    _rehash_map(tree)
    tree["lock_data"]["reference_binding"] = tree["manifest"]["reference_binding"]
    tree["lock_data"]["map_content_hash"] = tree["manifest"]["map_content_hash"]
    _rehash_lock(tree)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


def test_raw_inventory_declared_path_must_match_supplied_file(tmp_path: Path) -> None:
    for index, declared_path in enumerate(
        ("other.yaml", "nested/raw.yaml", "/raw.yaml", "\\raw.yaml")
    ):
        tree = _write_tree(tmp_path / f"case-{index}")
        tree["manifest"]["raw_inventory_binding"]["path"] = declared_path
        _rehash_map(tree)
        tree["lock_data"]["map_content_hash"] = tree["manifest"]["map_content_hash"]
        _rehash_lock(tree)
        with pytest.raises(AtlasIdentityMapError):
            _load(tree)


def test_reference_binding_accepts_string_transcript_pins(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path)
    pack = _synthetic_pack()
    string_pack = type(pack)(
        schema=pack.schema,
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        pack_content_hash=pack.pack_content_hash,
        allowed_genes=pack.allowed_genes,
        assembly_pins=pack.assembly_pins,
        transcript_pins=("SYN_TX001.1",),
        reconciliation_policy=pack.reconciliation_policy,
        ontology_extensions=pack.ontology_extensions,
        source_register_pins=pack.source_register_pins,
        prohibitions=pack.prohibitions,
        pilot_eval_metadata=pack.pilot_eval_metadata,
    )
    mapper = identity_map.load_identity_map(
        tree["map"],
        response_root=tree["root"],
        lock_path=tree["lock"],
        disease_pack=string_pack,
        raw_inventory_path=tree["raw"],
    )
    assert mapper.replay("raw-1", "p.Lys2Glu", "missense_substitution").identity_state == "resolved"


def test_response_root_rejects_windows_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "responses"
    root.mkdir()
    actual_lstat = Path.lstat
    real = actual_lstat(root)
    reparse_bit = 1024

    monkeypatch.setattr(identity_map.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_bit)

    def fake_lstat(path: Path):
        if path == root:
            return SimpleNamespace(
                st_mode=real.st_mode, st_file_attributes=reparse_bit
            )
        return actual_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(AtlasIdentityMapError):
        identity_map._resolve_response_root(root)


def test_bundle_hash_rejects_nested_windows_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "responses"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "response.json").write_text("{}", encoding="utf-8")
    actual_lstat = Path.lstat
    real = actual_lstat(nested)
    reparse_bit = 1024

    monkeypatch.setattr(identity_map.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_bit)

    def fake_lstat(path: Path):
        if path == nested:
            return SimpleNamespace(
                st_mode=real.st_mode, st_file_attributes=reparse_bit
            )
        return actual_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(AtlasIdentityMapError):
        identity_map._compute_bundle_hash(root)
