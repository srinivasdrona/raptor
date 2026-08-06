"""Protected RED tests for ``atlas-raw-identity-mapper-v1.yaml``.

Spec mapping:
IM-T001..T030 map one-for-one to ``test_im_t001`` .. ``test_im_t030``.
All identifiers and official-response shapes below are synthetic.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

import pytest
import yaml

try:
    from raptor.atlas.identity_map import (
        OfflineRawIdentityMapper,
        identity_map_content_hash,
        identity_map_lock_content_hash,
        load_identity_map,
    )
    from raptor.atlas.model import (
        AtlasIdentityMapError,
        RawIdentityMapper,
        RawIdentityReplay,
        DiseasePack,
    )
    from scripts.build_atlas_raw_identity_map import build_identity_map

    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    IMPLEMENTED = False


def test_red_identity_mapper_implementation_exists() -> None:
    assert IMPLEMENTED, "RED: Atlas raw identity mapper is not implemented"


requires_mapper = pytest.mark.skipif(not IMPLEMENTED, reason="RED: mapper not implemented")


def _canonical_hash(data: dict, self_key: str) -> str:
    payload = {key: value for key, value in data.items() if key != self_key}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bundle_hash(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
        total += len(raw)
    return digest.hexdigest(), len(files), total


def _synthetic_pack() -> "DiseasePack":
    return DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="a" * 64,
        allowed_genes=("SYNGENE99",),
        assembly_pins=("SYNASM1",),
        transcript_pins=(
            {"transcript": "SYN_TX001.1", "requires": "synthetic-verification"},
        ),
        reconciliation_policy={
            "alias_to_canonical_spdi_only": True,
            "no_fabrication": True,
        },
        ontology_extensions={
            "claim_kinds": [],
            "node_layers": [],
            "mechanism_classes": [],
            "context_vocabularies": {},
        },
        source_register_pins=(),
        prohibitions={},
        pilot_eval_metadata={},
    )


def _write_tree(
    tmp_path: Path,
    *,
    state: str = "resolved_unique_official_match",
    search_count: int = 1,
    title: str = "SYN_TX001.1(SYNGENE99):c.4A>G (p.Lys2Glu)",
    gene: str = "SYNGENE99",
    assembly: str = "SYNASM1",
    protein_change: str = "K2E",
    malformed_summary: bool = False,
) -> dict:
    root = tmp_path / "responses"
    search_path = root / "search" / "raw-1.json"
    search_path.parent.mkdir(parents=True)
    ids = [str(9001 + index) for index in range(search_count)]
    search = {"esearchresult": {"count": str(search_count), "idlist": ids}}
    search_path.write_text(json.dumps(search), encoding="utf-8")

    summaries: list[dict] = []
    for uid in ids:
        path = root / "summary" / "raw-1" / f"{uid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "result": {
                "uids": [uid],
                uid: {
                    "uid": uid,
                    "gene_sort": gene,
                    "genes": [{"symbol": gene}],
                    "title": title,
                    "protein_change": protein_change,
                    "molecular_consequence_list": ["missense variant"],
                    "variation_set": [
                        {
                            "variant_type": "single nucleotide variant",
                            "canonical_spdi": "SYN_NC001.1:3:A:G",
                            "variation_loc": [
                                {
                                    "status": "current",
                                    "assembly_name": assembly,
                                    "assembly_acc_ver": "SYN_ASM_ACC.1",
                                }
                            ],
                        }
                    ],
                },
            }
        }
        path.write_bytes(b"{" if malformed_summary else json.dumps(summary).encode("utf-8"))
        summaries.append(
            {
                "uid": uid,
                "relative_path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "byte_length": len(path.read_bytes()),
            }
        )

    current_cdna = title.split("):", 1)[1].split(" (p.", 1)[0]
    current_protein = title.split("(p.", 1)[1].rstrip(")")
    current_residue = int(re.search(r"(\d+)", current_protein).group(1))
    reference = [
        1,
        ["9001"],
        None,
        [[
            "9001",
            title,
            gene,
            "SYN_TX001.1:c.4A>G",
            f"SYN_PROT001.1:p.{current_protein}",
        ]],
    ]
    reference_path = root / "reference" / "protein.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    tool = root / "acquisition-tool.py"
    tool.write_text("# synthetic acquisition tool\n", encoding="utf-8")
    raw_inventory = tmp_path / "raw.yaml"
    raw_inventory.write_text(
        yaml.safe_dump(
            {
                "schema": "atlas.discovery_inventory.raw.v1",
                "record_count": 1,
                "rows": [
                    {
                        "raw_record_id": "raw-1",
                        "raw_identity_string": "p.Lys2Glu",
                        "source_reported_consequence_hint": "missense_substitution",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resolved = state == "resolved_unique_official_match"
    map_record = {
        "raw_record_id": "raw-1",
        "raw_identity_string": "p.Lys2Glu",
        "source_reported_consequence_hint": "missense_substitution",
        "search_term": "p.Lys2Glu[varname] AND SYNGENE99[gene]",
        "search_response_relative_path": "search/raw-1.json",
        "search_response_sha256": hashlib.sha256(search_path.read_bytes()).hexdigest(),
        "search_count": search_count,
        "summary_response_pins": summaries,
        "match_state": state,
        "normalization_outcome": "resolved_identity" if resolved else "unresolved_identity",
        "universe_key": (
            "SYN_NC001.1:3:A:G"
            if resolved
            else "UNRESOLVED:" + hashlib.sha256(b"p.Lys2Glu").hexdigest()
        ),
        "identity_state": "resolved" if resolved else "unresolved",
        "spdi_canonical": "SYN_NC001.1:3:A:G" if resolved else None,
        "hgvs_c": f"SYN_TX001.1:{current_cdna}" if resolved else None,
        "hgvs_p": f"SYN_PROT001.1:p.{current_protein}" if resolved else None,
        "transcript_pin": "SYN_TX001.1" if resolved else None,
        "residue_index": current_residue if resolved else None,
        "codon_index": current_residue if resolved else None,
        "consequence_class": "missense_substitution" if resolved else None,
        "scope_decision": "in_scope" if resolved else "unresolved",
        "exclusion_code": None if resolved else "X1",
    }
    bundle_hash, file_count, byte_count = _bundle_hash(root)
    manifest = {
        "schema": "atlas.raw_identity_map.v2",
        "map_id": "synthetic-map",
        "map_version": "1",
        "map_content_hash": "0" * 64,
        "created_at": "2026-01-01T00:00:00Z",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "a" * 64,
        },
        "reference_binding": {
            "provider": "SYNTHETIC",
            "database": "synthetic-variants",
            "transcript": "SYN_TX001.1",
            "protein": "SYN_PROT001.1",
            "assembly": "SYNASM1",
            "protein_reference_total_count": 1,
            "protein_reference_page_size": 500,
            "protein_reference_response_pins": [{
                "offset": 0,
                "count": 500,
                "relative_path": "reference/protein.json",
                "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                "byte_length": len(reference_path.read_bytes()),
            }],
        },
        "raw_inventory_binding": {
            "path": raw_inventory.name,
            "sha256": hashlib.sha256(raw_inventory.read_bytes()).hexdigest(),
            "record_count": 1,
        },
        "response_bundle": {
            "sha256": bundle_hash,
            "file_count": file_count,
            "byte_count": byte_count,
        },
        "acquisition_tool": {
            "relative_path": tool.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
        },
        "records": [map_record],
    }
    manifest["map_content_hash"] = _canonical_hash(manifest, "map_content_hash")
    map_path = tmp_path / "map.yaml"
    map_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    lock = {
        "schema": "atlas.raw_identity_map_lock.v2",
        "lock_id": "synthetic-map-lock",
        "lock_version": "1",
        "created_at": "2026-01-01T00:00:00Z",
        "map_id": "synthetic-map",
        "map_version": "1",
        "map_content_hash": manifest["map_content_hash"],
        "map_record_count": 1,
        "raw_inventory_content_hash": manifest["raw_inventory_binding"]["sha256"],
        "raw_inventory_record_count": 1,
        "response_bundle_hash": bundle_hash,
        "response_file_count": file_count,
        "response_byte_count": byte_count,
        "pack_binding": manifest["pack_binding"],
        "reference_binding": manifest["reference_binding"],
        "acquisition_tool_sha256": manifest["acquisition_tool"]["sha256"],
        "lock_content_hash": "0" * 64,
    }
    lock["lock_content_hash"] = _canonical_hash(lock, "lock_content_hash")
    lock_path = tmp_path / "lock.yaml"
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    return {
        "root": root,
        "raw": raw_inventory,
        "map": map_path,
        "lock": lock_path,
        "manifest": manifest,
        "lock_data": lock,
    }


def _load(tree: dict):
    return load_identity_map(
        tree["map"],
        response_root=tree["root"],
        lock_path=tree["lock"],
        disease_pack=_synthetic_pack(),
        raw_inventory_path=tree["raw"],
    )


@requires_mapper
def test_im_t001() -> None:
    """IM-T001-map-and-lock-hash-happy-path"""
    data = {"schema": "x", "map_content_hash": "0" * 64}
    assert identity_map_content_hash(data) == _canonical_hash(data, "map_content_hash")
    lock = {"schema": "x", "lock_content_hash": "0" * 64}
    assert identity_map_lock_content_hash(lock) == _canonical_hash(lock, "lock_content_hash")


@requires_mapper
def test_im_t002(tmp_path: Path) -> None:
    """IM-T002-response-bundle-hash-happy-path"""
    tree = _write_tree(tmp_path)
    assert isinstance(_load(tree), OfflineRawIdentityMapper)


@requires_mapper
def test_im_t003(tmp_path: Path) -> None:
    """IM-T003-resolved-unique-official-record"""
    replay = _load(_write_tree(tmp_path)).replay("raw-1", "p.Lys2Glu", "missense_substitution")
    assert isinstance(replay, RawIdentityReplay)
    assert replay.identity_state == "resolved"
    assert replay.spdi_canonical == "SYN_NC001.1:3:A:G"


@requires_mapper
def test_im_t004(tmp_path: Path) -> None:
    """IM-T004-zero-match-confirmed-unresolved"""
    mapper = _load(_write_tree(tmp_path, state="unresolved_official_zero_match", search_count=0))
    assert mapper.replay("raw-1", "p.Lys2Glu", "missense_substitution").identity_state == "unresolved"


@requires_mapper
def test_im_t005(tmp_path: Path) -> None:
    """IM-T005-multi-match-remains-ambiguous"""
    mapper = _load(_write_tree(tmp_path, state="unresolved_official_ambiguous_match", search_count=2))
    assert mapper.replay("raw-1", "p.Lys2Glu", "missense_substitution").identity_state == "unresolved"


@requires_mapper
def test_im_t006(tmp_path: Path) -> None:
    """IM-T006-first-result-is-never-selected"""
    tree = _write_tree(tmp_path, state="resolved_unique_official_match", search_count=2)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t007(tmp_path: Path) -> None:
    """IM-T007-three-to-one-alias-membership"""
    assert _load(_write_tree(tmp_path)).replay(
        "raw-1", "p.Lys2Glu", "missense_substitution"
    ).hgvs_p.endswith("p.Lys2Glu")


@requires_mapper
@pytest.mark.parametrize(
    ("field", "value"),
    [("title", "SYN_TX999.1(SYNGENE99):c.4A>G (p.Lys2Glu)"), ("gene", "OTHERGENE"), ("assembly", "OLDASM")],
)
def test_im_t008_t010(tmp_path: Path, field: str, value: str) -> None:
    """IM-T008-current-transcript-required
    IM-T009-tsc2-gene-required
    IM-T010-current-grch38-spdi-required
    """
    kwargs = {field: value}
    with pytest.raises(AtlasIdentityMapError):
        _load(_write_tree(tmp_path, **kwargs))


@requires_mapper
def test_im_t011(tmp_path: Path) -> None:
    """IM-T011-consequence-and-scope-recomputed"""
    replay = _load(_write_tree(tmp_path)).replay("raw-1", "p.Lys2Glu", "missense_substitution")
    assert (replay.consequence_class, replay.scope_decision) == ("missense_substitution", "in_scope")


def _mutate_yaml(path: Path, key: str, value) -> None:
    data = yaml.safe_load(path.read_text())
    data[key] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@requires_mapper
def test_im_t012(tmp_path: Path) -> None:
    """IM-T012-map-hash-drift"""
    tree = _write_tree(tmp_path)
    _mutate_yaml(tree["map"], "created_at", "2026-01-02T00:00:00Z")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t013(tmp_path: Path) -> None:
    """IM-T013-lock-hash-drift"""
    tree = _write_tree(tmp_path)
    _mutate_yaml(tree["lock"], "created_at", "2026-01-02T00:00:00Z")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t014(tmp_path: Path) -> None:
    """IM-T014-response-file-drift"""
    tree = _write_tree(tmp_path)
    (tree["root"] / "search/raw-1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t015(tmp_path: Path) -> None:
    """IM-T015-response-bundle-omission"""
    tree = _write_tree(tmp_path)
    (tree["root"] / "search/raw-1.json").unlink()
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t016(tmp_path: Path) -> None:
    """IM-T016-raw-inventory-binding-drift"""
    tree = _write_tree(tmp_path)
    tree["raw"].write_text("changed", encoding="utf-8")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t017(tmp_path: Path) -> None:
    """IM-T017-pack-binding-drift"""
    tree = _write_tree(tmp_path)
    tree["manifest"]["pack_binding"]["pack_content_hash"] = "b" * 64
    tree["manifest"]["map_content_hash"] = _canonical_hash(tree["manifest"], "map_content_hash")
    tree["map"].write_text(yaml.safe_dump(tree["manifest"], sort_keys=False), encoding="utf-8")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t018(tmp_path: Path) -> None:
    """IM-T018-tool-hash-drift"""
    tree = _write_tree(tmp_path)
    (tree["root"] / "acquisition-tool.py").write_text("changed", encoding="utf-8")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
@pytest.mark.parametrize("relative", ["../escape.json", "/absolute/escape.json"])
def test_im_t019(tmp_path: Path, relative: str) -> None:
    """IM-T019-path-traversal-and-absolute-path"""
    tree = _write_tree(tmp_path)
    tree["manifest"]["records"][0]["search_response_relative_path"] = relative
    tree["manifest"]["map_content_hash"] = _canonical_hash(tree["manifest"], "map_content_hash")
    tree["map"].write_text(yaml.safe_dump(tree["manifest"], sort_keys=False), encoding="utf-8")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t020(tmp_path: Path) -> None:
    """IM-T020-symlink-junction-escape"""
    tree = _write_tree(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    link = tree["root"] / "search/raw-1.json"
    link.unlink()
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t021(tmp_path: Path) -> None:
    """IM-T021-non-utf8-or-malformed-json"""
    tree = _write_tree(tmp_path, malformed_summary=True)
    with pytest.raises(AtlasIdentityMapError):
        _load(tree)


@requires_mapper
def test_im_t022() -> None:
    """IM-T022-runtime-module-has-no-network-import"""
    path = Path("src/raptor/atlas/identity_map.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"socket", "http", "urllib", "requests", "httpx", "aiohttp", "Bio"}
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
    }
    assert not imports.intersection(forbidden)


@requires_mapper
def test_im_t023(tmp_path: Path) -> None:
    """IM-T023-lookup-raw-string-mismatch"""
    with pytest.raises(AtlasIdentityMapError):
        _load(_write_tree(tmp_path)).replay("raw-1", "p.Other3Val", "missense_substitution")


@requires_mapper
def test_im_t024(tmp_path: Path) -> None:
    """IM-T024-lookup-hint-mismatch"""
    with pytest.raises(AtlasIdentityMapError):
        _load(_write_tree(tmp_path)).replay("raw-1", "p.Lys2Glu", "synonymous_substitution")


@requires_mapper
def test_im_t025(tmp_path: Path) -> None:
    """IM-T025-map-deep-immutable"""
    mapper = _load(_write_tree(tmp_path))
    with pytest.raises((TypeError, AttributeError)):
        mapper.records["raw-1"] = None


@requires_mapper
def test_im_t026(tmp_path: Path) -> None:
    """IM-T026-candidate-free-lock"""
    tree = _write_tree(tmp_path)
    text = tree["lock"].read_text(encoding="utf-8")
    assert "p.Lys2Glu" not in text
    assert "SYN_NC001" not in text
    assert "9001" not in text


class _FailingTransport:
    def __init__(self, result):
        self.result = result

    def get_json(self, endpoint, params):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _raw_inventory(tmp_path: Path) -> Path:
    path = tmp_path / "raw.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "atlas.discovery_inventory.raw.v1",
                "record_count": 1,
                "rows": [
                    {
                        "raw_record_id": "raw-1",
                        "raw_identity_string": "p.Lys2Glu",
                        "source_reported_consequence_hint": "missense_substitution",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@requires_mapper
def test_im_t027(tmp_path: Path) -> None:
    """IM-T027-acquisition-network-error-not-zero"""
    with pytest.raises(Exception):
        build_identity_map(
            _raw_inventory(tmp_path), "synthpack", tmp_path / "out", tmp_path / "lock.yaml",
            "operator@example.test", transport=_FailingTransport(TimeoutError("offline")),
        )
    assert not (tmp_path / "out").exists()


@requires_mapper
def test_im_t028(tmp_path: Path) -> None:
    """IM-T028-acquisition-rate-limit-fail-closed"""
    with pytest.raises(Exception):
        build_identity_map(
            _raw_inventory(tmp_path), "synthpack", tmp_path / "out", tmp_path / "lock.yaml",
            "operator@example.test", transport=_FailingTransport((429, b"{}")),
        )
    assert not (tmp_path / "out").exists()


@requires_mapper
def test_im_t029(tmp_path: Path) -> None:
    """IM-T029-exclusive-publication-collision"""
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "sentinel"
    sentinel.write_bytes(b"competing")
    with pytest.raises(Exception):
        build_identity_map(
            _raw_inventory(tmp_path), "synthpack", out, tmp_path / "lock.yaml",
            "operator@example.test", transport=_FailingTransport((500, b"{}")),
        )
    assert sentinel.read_bytes() == b"competing"


def test_im_t030() -> None:
    """IM-T030-no-candidate-identity-in-unit-fixtures"""
    text = Path(__file__).read_text(encoding="utf-8")
    forbidden = (
        "TS" + "C1",
        "TS" + "C2",
        "NM_" + "000548",
        "NC_" + "000016",
        "R611" + "Q",
        "VC" + "V0",
        "PM" + "ID:",
    )
    assert not any(token in text for token in forbidden)
