"""Regression tests for independent checker findings on the identity mapper."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
import yaml

import raptor.atlas.identity_map as identity_map
from scripts import build_atlas_raw_identity_map as acquisition
from raptor.atlas.model import AtlasIdentityMapError
from raptor.atlas.pack import pack_content_hash
from tests.atlas.test_identity_map import (
    _load,
    _raw_inventory,
    _synthetic_pack,
    _write_tree,
)


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


def test_legacy_alias_membership_derives_current_protein_hgvs(tmp_path: Path) -> None:
    tree = _write_tree(
        tmp_path,
        title="SYN_TX001.1(SYNGENE99):c.7A>G (p.Lys3Glu)",
        protein_change="K3E, K2E",
    )
    replay = _load(tree).replay("raw-1", "p.Lys2Glu", "missense_substitution")
    assert replay.hgvs_c == "SYN_TX001.1:c.7A>G"
    assert replay.hgvs_p == "SYN_PROT001.1:p.Lys3Glu"
    assert replay.residue_index == 3
    assert replay.codon_index == 3


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


def test_transport_accepts_clinical_tables_list_json() -> None:
    class Transport:
        def get_json(self, endpoint, params):
            return 200, b"[1, [], null, []]"

    clock = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    limiter = acquisition._RateLimiter(
        requests_per_second=3.0, now_utc=clock, sleep=lambda _: None
    )
    body = acquisition._call_transport(
        Transport(),
        "https://synthetic.invalid",
        {},
        sleep=lambda _: None,
        rate_limiter=limiter,
        what="synthetic clinical table",
    )
    assert body == b"[1, [], null, []]"


@pytest.mark.parametrize("wrong_endpoint", ["esearch", "esummary"])
def test_eutils_wrong_shape_is_typed_response_error(
    tmp_path: Path, wrong_endpoint: str
) -> None:
    class Transport:
        def get_json(self, endpoint, params):
            if "esearch" in endpoint:
                payload = (
                    []
                    if wrong_endpoint == "esearch"
                    else {"esearchresult": {"count": "1", "idlist": ["9001"]}}
                )
            else:
                payload = [] if wrong_endpoint == "esummary" else {}
            return 200, json.dumps(payload).encode("utf-8")

    clock = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    limiter = acquisition._RateLimiter(
        requests_per_second=3.0, now_utc=clock, sleep=lambda _: None
    )
    with pytest.raises(AtlasIdentityMapError):
        acquisition._acquire_row(
            {
                "raw_record_id": "raw-1",
                "raw_identity_string": "p.Lys2Glu",
                "source_reported_consequence_hint": "missense_substitution",
            },
            gene="SYNGENE99",
            transcript="SYN_TX001.1",
            protein_accession="SYN_PROT001.1",
            disease_pack=_synthetic_pack(),
            responses_root=tmp_path,
            transport=Transport(),
            email="operator@example.test",
            api_key=None,
            rate_limiter=limiter,
            sleep=lambda _: None,
        )


def test_injected_transport_builds_complete_map_and_lock(tmp_path: Path) -> None:
    pack_data = {
        "schema": "atlas.disease_pack.v1",
        "pack_id": "synthpack",
        "pack_version": "1.0.0",
        "pack_content_hash": "0" * 64,
        "allowed_genes": ["SYNGENE99"],
        "assembly_pins": ["SYNASM1"],
        "transcript_pins": [
            {"transcript": "SYN_TX001.1", "requires": "synthetic-verification"}
        ],
        "reconciliation_policy": {
            "alias_to_canonical_spdi_only": True,
            "no_fabrication": True,
        },
        "ontology_extensions": {
            "claim_kinds": [],
            "node_layers": [],
            "mechanism_classes": [],
            "context_vocabularies": {},
        },
        "source_register_pins": [],
        "prohibitions": {},
        "pilot_eval_metadata": {},
    }
    pack_data["pack_content_hash"] = pack_content_hash(pack_data)
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack_data, sort_keys=False), encoding="utf-8")

    class Transport:
        def get_json(self, endpoint, params):
            if "clinicaltables" in endpoint:
                payload = [
                    1,
                    ["9001"],
                    None,
                    [[
                        "9001",
                        "SYN_TX001.1(SYNGENE99):c.4A>G (p.Lys2Glu)",
                        "SYNGENE99",
                        "SYN_TX001.1:c.4A>G",
                        "SYN_PROT001.1:p.Lys2Glu",
                    ]],
                ]
            elif "esearch" in endpoint:
                payload = {"esearchresult": {"count": "1", "idlist": ["9001"]}}
            else:
                payload = {
                    "result": {
                        "uids": ["9001"],
                        "9001": {
                            "uid": "9001",
                            "gene_sort": "SYNGENE99",
                            "genes": [{"symbol": "SYNGENE99"}],
                            "title": "SYN_TX001.1(SYNGENE99):c.4A>G (p.Lys2Glu)",
                            "protein_change": "K2E",
                            "molecular_consequence_list": ["missense variant"],
                            "variation_set": [{
                                "variant_type": "single nucleotide variant",
                                "canonical_spdi": "SYN_NC001.1:3:A:G",
                                "variation_loc": [{
                                    "status": "current",
                                    "assembly_name": "SYNASM1",
                                }],
                            }],
                        },
                    }
                }
            return 200, json.dumps(payload).encode("utf-8")

    raw = _raw_inventory(tmp_path)
    out = tmp_path / "out"
    lock = tmp_path / "lock.yaml"
    map_path, lock_path = acquisition.build_identity_map(
        raw,
        pack_path,
        out,
        lock,
        "operator@example.test",
        transport=Transport(),
        now_utc=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        sleep=lambda _: None,
    )
    assert map_path.is_file()
    assert lock_path.is_file()
