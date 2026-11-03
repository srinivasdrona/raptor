"""Independent integrity tests for the R611Q structure-readiness evidence pack."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACK = REPOSITORY_ROOT / "data" / "rescuescreen" / "r611q" / "structure-readiness-v1"
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_r611q_structure_readiness.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(relative_path: str) -> dict:
    return json.loads((PACK / relative_path).read_text(encoding="utf-8"))


def test_manifest_covers_exact_pack_file_set_and_hashes() -> None:
    manifest_lines = (PACK / "manifest.sha256").read_text(encoding="utf-8").splitlines()
    listed: dict[str, str] = {}
    for line in manifest_lines:
        digest, separator, relative_path = line.partition("  ")
        assert separator == "  "
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert relative_path not in listed
        listed[relative_path] = digest

    actual = {
        path.relative_to(PACK).as_posix()
        for path in PACK.rglob("*")
        if path.is_file() and path.name != "manifest.sha256"
    }
    assert list(listed) == sorted(listed)
    assert set(listed) == actual
    assert all(_sha256(PACK / relative_path) == digest for relative_path, digest in listed.items())
    for relative_path in (
        "README.md",
        "identity_mapping.json",
        "structure_contexts.json",
        "extracted/structure_evidence.txt",
        "claims.json",
        "contradiction_register.json",
        "evidence_gap_map.json",
        "readiness_assessment.json",
        "source_catalog.json",
        "manifest.sha256",
    ):
        content = (PACK / relative_path).read_bytes()
        assert b"\r\n" not in content
        content.decode("utf-8")


def test_source_catalog_hashes_raw_inputs_and_derived_artifacts() -> None:
    catalog = _json("source_catalog.json")
    stored_content_hash = catalog.pop("content_hash")
    canonical = json.dumps(
        catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == stored_content_hash

    source_paths = set()
    for source in catalog["sources"]:
        relative_path = source["relative_path"]
        source_paths.add(relative_path)
        path = PACK / relative_path
        assert path.is_file()
        assert source["raw_sha256"] == _sha256(path)
        assert source["raw_byte_length"] == path.stat().st_size
        assert source["source_url"]
        assert source["licence"]
        assert source["access"]

    expected_inputs = {
        path.relative_to(PACK).as_posix()
        for path in (PACK / "raw").rglob("*")
        if path.is_file()
    } | {
        "extracted/pdb-7dl2-validation.xml",
        "extracted/pdb-9ce3-validation.xml",
    }
    assert source_paths == expected_inputs

    derived_paths = set()
    for artifact in catalog["derived_artifacts"]:
        path = PACK / artifact["relative_path"]
        derived_paths.add(artifact["relative_path"])
        assert artifact["derived_sha256"] == _sha256(path)
        assert artifact["derived_byte_length"] == path.stat().st_size
    assert derived_paths == {
        "README.md",
        "claims.json",
        "contradiction_register.json",
        "evidence_gap_map.json",
        "extracted/structure_evidence.txt",
        "identity_mapping.json",
        "readiness_assessment.json",
        "structure_contexts.json",
    }


def test_claim_spans_are_exact_and_status_limited() -> None:
    evidence = (PACK / "extracted" / "structure_evidence.txt").read_text(encoding="utf-8")
    claims = _json("claims.json")
    assert claims["claim_status_vocabulary"] == ["SOURCE_REPORTED", "UNTRUSTED"]
    assert "\r\n" not in evidence

    for claim in claims["claims"]:
        match = re.fullmatch(r"text-char:(\d+):(\d+)", claim["locator"])
        assert match
        start, end = (int(value) for value in match.groups())
        assert evidence[start:end] == claim["exact_quote"] == claim["claim_text"]
        assert "\n" not in claim["exact_quote"]
        assert claim["verification_status"] in {"SOURCE_REPORTED", "UNTRUSTED"}
        assert claim["raw_source_refs"]
        assert all((PACK / source).is_file() for source in claim["raw_source_refs"])

    assert "OBSERVED" not in json.dumps(claims, sort_keys=True)
    assert "Q_score 0.303" in evidence
    assert "Q_score 0.483" in evidence


def test_identity_and_structure_context_facts() -> None:
    identity = _json("identity_mapping.json")
    assert identity["variant_crosswalk"] == {
        "gene": "TSC2",
        "spdi": "NC_000016.10:2070570:G:A",
        "refseq_transcript": "NM_000548.5:c.1832G>A",
        "refseq_protein": "NP_000539.2:p.Arg611Gln",
        "uniprot_accession": "P49815",
        "uniprot_residue": {"position": 611, "one_letter": "R", "three_letter": "ARG"},
        "uniprot_validation": {
            "fasta": "raw/uniprot-P49815.fasta",
            "json": "raw/uniprot-P49815.json",
        },
    }
    crosswalks = {item["pdb_id"]: item for item in identity["structure_crosswalks"]}
    assert [(copy["auth_asym_id"], copy["label_asym_id"], copy["label_seq_id"]) for copy in crosswalks["7DL2"]["copies"]] == [
        ("A", "B", 562),
        ("B", "C", 562),
    ]
    assert [(copy["auth_asym_id"], copy["label_asym_id"], copy["label_seq_id"]) for copy in crosswalks["9CE3"]["copies"]] == [
        ("A", "A", 619),
        ("B", "B", 619),
    ]
    assert "exact RefSeq-to-PDB-construct equivalence remains unverified" in " ".join(identity["limitations"])

    contexts = _json("structure_contexts.json")
    structures = {item["pdb_id"]: item for item in contexts["structures"]}
    seven, nine = structures["7DL2"], structures["9CE3"]
    assert (seven["method"], seven["repository_global_resolution_angstrom"], seven["emdb"]) == (
        "ELECTRON MICROSCOPY",
        "4.4",
        "EMD-30708",
    )
    assert (nine["method"], nine["repository_global_resolution_angstrom"], nine["emdb"]) == (
        "ELECTRON MICROSCOPY",
        "2.9",
        "EMD-45492",
    )
    assert seven["assembly"]["composition"] == "TSC1x2/TSC2x2/TBC1D7/unknown"
    assert nine["assembly"]["composition"] == "TSC2x2/TSC1x2/TBC1D7/WIPI3/unknown fragmentsx2"
    assert [target["validation"]["rotamer"] for target in seven["target_residues"]] == ["mpp80", "mtt180"]
    assert [target["validation"]["q_score"] for target in seven["target_residues"]] == ["0.303", "0.268"]
    assert [target["validation"]["residue_inclusion"] for target in seven["target_residues"]] == ["1.0000", "0.8182"]
    assert [target["validation"]["rotamer"] for target in nine["target_residues"]] == ["mtm180", "mtm180"]
    assert [target["validation"]["q_score"] for target in nine["target_residues"]] == ["0.454", "0.483"]
    assert [target["validation"]["residue_inclusion"] for target in nine["target_residues"]] == ["0.8182", "1.0000"]

    for structure in (seven, nine):
        assert structure["deposited_inventory"]["ligand_entities"] == 0
        assert structure["deposited_inventory"]["water_entities"] == 0
        for target in structure["target_residues"]:
            assert target["residue_name"] == "ARG"
            assert target["atom_record_count"] == 11
            assert target["alt_id"] == "."
            assert target["occupancy"] == "1.00"
            assert target["model"] == 1
    assert "average nominal resolution of 2.8 Å" in nine["publication_context"]["bounded_quote"]
    assert "locally refined" in seven["publication_context"]["bounded_quote"]
    assert "No Q-score average or pass/fail threshold is assigned." in contexts["limitations"]


def test_status_ceiling_and_evidence_gaps_remain_blocked() -> None:
    readiness = _json("readiness_assessment.json")
    assert readiness["readiness"] == "EVIDENCE_PACK_READY_FOR_HUMAN_REVIEW"
    assert set(readiness["gate_states"].values()) == {"NOT_SATISFIED"}
    assert readiness["first_blocker"] == {"gate_id": "EG-1", "fail_state": "MECHANISM_UNVERIFIED"}
    assert readiness["atlas_boundary"] == {
        "gate_8": "BLOCKED_HUMAN_REVIEW",
        "accepted_claim_count": 0,
        "changed_by_this_pack": False,
    }
    assert readiness["stage_execution_authorized"] is False
    assert readiness["authorization_ceiling"] == {
        "compound_screening_authorized": False,
        "docking_authorized": False,
        "treatment_authorized": False,
    }

    gaps = _json("evidence_gap_map.json")
    assert gaps["human_review_state"] == "PENDING"
    assert {(item["gate_id"], item["evidence_status"], item["gate_status"]) for item in gaps["gates"]} == {
        ("EG-2", "PACK_EVIDENCE_READY_FOR_HUMAN_REVIEW", "NOT_SATISFIED"),
        ("EG-3", "PACK_EVIDENCE_READY_FOR_HUMAN_REVIEW", "NOT_SATISFIED"),
    }
    contradictions = _json("contradiction_register.json")
    assert contradictions["true_contradiction_detected"] is False
    assert {item["classification"] for item in contradictions["entries"]} >= {
        "NUMBERING_HAZARD",
        "COPY_LEVEL_DISAGREEMENT",
        "CONTEXT_DIFFERENCE_NOT_CONTRADICTION",
        "EVIDENCE_LIMIT",
        "UNMEASURED",
    }


def test_primary_sources_and_check_mode_reproducibility() -> None:
    for article in ("pmc7804450.xml", "pmc11578170.xml"):
        text = (PACK / "raw" / article).read_text(encoding="utf-8")
        assert "R611" not in text
        assert "Arg611" not in text

    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--pack-dir", str(PACK), "--check"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "R611Q structure-readiness pack check: OK"
