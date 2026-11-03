#!/usr/bin/env python3
"""Build the frozen R611Q structure-readiness evidence pack using only stdlib."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shlex
import tempfile
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any, Iterable


PACK_RELATIVE = Path("data/rescuescreen/r611q/structure-readiness-v1")
EXPECTED_ATOMS = ("N", "CA", "C", "O", "CB", "CG", "CD", "NE", "CZ", "NH1", "NH2")
INPUT_PATHS = (
    "raw/pdb-7dl2.cif",
    "raw/pdb-7dl2-assembly1.cif",
    "raw/pdb-7dl2-validation.xml.gz",
    "raw/pdb-9ce3.cif",
    "raw/pdb-9ce3-assembly1.cif",
    "raw/pdb-9ce3-validation.xml.gz",
    "raw/pdbe-7dl2-molecules.json",
    "raw/pdbe-7dl2-summary.json",
    "raw/pdbe-7dl2-uniprot.json",
    "raw/pdbe-9ce3-molecules.json",
    "raw/pdbe-9ce3-summary.json",
    "raw/pdbe-9ce3-uniprot.json",
    "raw/pmc7804450.xml",
    "raw/pmc11578170.xml",
    "raw/rcsb-7dl2-entry.json",
    "raw/rcsb-9ce3-entry.json",
    "raw/uniprot-P49815.json",
    "raw/uniprot-P49815.fasta",
    "extracted/pdb-7dl2-validation.xml",
    "extracted/pdb-9ce3-validation.xml",
)
DERIVED_PATHS = (
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
)


class SourceValidationError(ValueError):
    """Raised when a frozen input cannot establish a required pack fact."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _json_file_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceValidationError(f"cannot read JSON source {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceValidationError(f"JSON source {path} is not an object")
    return payload


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceValidationError(message)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_cif_loop(path: Path, category: str) -> list[dict[str, str]]:
    """Read a simple mmCIF loop needed by this pack without a CIF dependency."""

    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"_{category}."
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue
        index += 1
        tags: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("_"):
            tags.append(lines[index].split()[0])
            index += 1
        if not tags or not all(tag.startswith(prefix) for tag in tags):
            continue
        rows: list[dict[str, str]] = []
        values: list[str] = []
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped == "#" or stripped == "loop_" or stripped.startswith("_"):
                break
            if stripped:
                values.extend(shlex.split(line, posix=True))
                while len(values) >= len(tags):
                    row_values, values = values[: len(tags)], values[len(tags) :]
                    rows.append(dict(zip(tags, row_values)))
            index += 1
        if values:
            raise SourceValidationError(f"partial {category} row in {path}")
        return rows
    raise SourceValidationError(f"missing {category} loop in {path}")


def _read_cif_scalar(path: Path, key: str) -> str:
    expression = re.compile(rf"^{re.escape(key)}\s+(.+?)\s*$", re.MULTILINE)
    match = expression.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SourceValidationError(f"missing {key} in {path}")
    values = shlex.split(match.group(1), posix=True)
    if len(values) != 1:
        raise SourceValidationError(f"malformed {key} in {path}")
    return values[0]


def _coordinate_target(
    path: Path,
    *,
    pdb_id: str,
    entity_id: str,
    expected_chains: tuple[tuple[str, str, str], ...],
) -> list[dict[str, Any]]:
    rows = _read_cif_loop(path, "atom_site")
    result: list[dict[str, Any]] = []
    for auth_chain, asym_id, label_seq in expected_chains:
        selected = [
            row
            for row in rows
            if row["_atom_site.group_PDB"] == "ATOM"
            and row["_atom_site.label_entity_id"] == entity_id
            and row["_atom_site.auth_asym_id"] == auth_chain
            and row["_atom_site.label_asym_id"] == asym_id
            and row["_atom_site.label_seq_id"] == label_seq
            and row["_atom_site.auth_seq_id"] == "611"
        ]
        _require(selected, f"{pdb_id} lacks target atoms for {auth_chain}/{asym_id}")
        _require(
            all(row["_atom_site.label_comp_id"] == "ARG" for row in selected)
            and all(row["_atom_site.auth_comp_id"] == "ARG" for row in selected),
            f"{pdb_id} {auth_chain}/{asym_id} target is not wild-type ARG611",
        )
        atom_names = tuple(row["_atom_site.label_atom_id"] for row in selected)
        _require(
            len(selected) == len(EXPECTED_ATOMS) and set(atom_names) == set(EXPECTED_ATOMS),
            f"{pdb_id} {auth_chain}/{asym_id} does not have the expected ARG heavy atoms",
        )
        _require(
            all(row["_atom_site.label_alt_id"] == "." for row in selected),
            f"{pdb_id} {auth_chain}/{asym_id} has a non-dot alternate identifier",
        )
        _require(
            all(row["_atom_site.occupancy"] == "1.00" for row in selected),
            f"{pdb_id} {auth_chain}/{asym_id} does not have occupancy 1.00",
        )
        _require(
            all(row["_atom_site.pdbx_PDB_model_num"] == "1" for row in selected),
            f"{pdb_id} {auth_chain}/{asym_id} is not in model 1",
        )
        result.append(
            {
                "auth_asym_id": auth_chain,
                "label_asym_id": asym_id,
                "entity_id": int(entity_id),
                "label_seq_id": int(label_seq),
                "auth_seq_id": 611,
                "residue_name": "ARG",
                "model": 1,
                "atom_record_count": len(selected),
                "expected_heavy_atoms": list(EXPECTED_ATOMS),
                "observed_heavy_atoms": sorted(atom_names),
                "alt_id": ".",
                "occupancy": "1.00",
            }
        )
    return result


def _validation_target(
    path: Path,
    *,
    pdb_id: str,
    expected: tuple[tuple[str, str, str, str, str], ...],
) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        root = element_tree.parse(path).getroot()
    except (OSError, element_tree.ParseError) as exc:
        raise SourceValidationError(f"cannot read validation XML {path}: {exc}") from exc
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "ModelledSubgroup":
            continue
        values = element.attrib
        if values.get("resnum") != "611" or values.get("resname") != "ARG":
            continue
        key = (values.get("chain", ""), values.get("said", ""))
        result[key] = {
            "auth_asym_id": key[0],
            "label_asym_id": key[1],
            "label_seq_id": int(values["seq"]),
            "auth_seq_id": int(values["resnum"]),
            "residue_name": values["resname"],
            "model": int(values["model"]),
            "alt_id": values["altcode"],
            "q_score": values["Q_score"],
            "residue_inclusion": values["residue_inclusion"],
            "rotamer": values["rota"],
        }
    expected_keys = {(auth, asym) for auth, asym, _, _, _, _ in expected}
    _require(
        set(result) == expected_keys,
        f"{pdb_id} validation target copies differ from expected {sorted(expected_keys)}",
    )
    for auth, asym, seq, q_score, inclusion, rotamer in expected:
        observed = result[(auth, asym)]
        _require(
            observed == {
                "auth_asym_id": auth,
                "label_asym_id": asym,
                "label_seq_id": int(seq),
                "auth_seq_id": 611,
                "residue_name": "ARG",
                "model": 1,
                "alt_id": " ",
                "q_score": q_score,
                "residue_inclusion": inclusion,
                "rotamer": rotamer,
            },
            f"{pdb_id} validation facts do not match for {auth}/{asym}",
        )
    return result


def _article_text(path: Path) -> str:
    try:
        root = element_tree.parse(path).getroot()
    except (OSError, element_tree.ParseError) as exc:
        raise SourceValidationError(f"cannot read article XML {path}: {exc}") from exc
    return _normalise_text(" ".join(root.itertext()))


def _article_license(path: Path) -> str:
    root = element_tree.parse(path).getroot()
    snippets = [
        _normalise_text(" ".join(element.itertext()))
        for element in root.iter()
        if _local_name(element.tag) in {"license", "license-p"}
    ]
    snippets = [snippet for snippet in snippets if snippet]
    _require(snippets, f"{path} has no licence declaration")
    return max(snippets, key=len)


def _bounded_quote(text: str, start: str, end: str, source: str) -> str:
    first = text.find(start)
    _require(first >= 0, f"{source} is missing quote start {start!r}")
    last = text.find(end, first)
    _require(last >= 0, f"{source} is missing quote end {end!r}")
    return text[first : last + len(end)]


def _source_metadata(relative_path: str, article_licenses: dict[str, str]) -> dict[str, str]:
    pdb_id = "7DL2" if "7dl2" in relative_path else "9CE3"
    lower = relative_path.lower()
    if relative_path.startswith("raw/pdb-") and relative_path.endswith(".cif"):
        suffix = "-assembly1.cif" if "assembly1" in lower else ".cif"
        return {
            "source_url": f"https://files.rcsb.org/download/{pdb_id}{suffix}",
            "licence": "CC0-1.0",
            "access": "PUBLIC",
        }
    if relative_path.startswith("raw/pdb-") and relative_path.endswith(".xml.gz"):
        return {
            "source_url": (
                f"https://files.rcsb.org/pub/pdb/validation_reports/"
                f"{pdb_id.lower()[1:3]}/{pdb_id.lower()}/{pdb_id.lower()}_validation.xml.gz"
            ),
            "licence": "CC0-1.0",
            "access": "PUBLIC",
        }
    if relative_path.startswith("extracted/pdb-") and relative_path.endswith(".xml"):
        return {
            "source_url": (
                f"https://files.rcsb.org/pub/pdb/validation_reports/"
                f"{pdb_id.lower()[1:3]}/{pdb_id.lower()}/{pdb_id.lower()}_validation.xml.gz"
            ),
            "licence": "CC0-1.0",
            "access": "LOCAL_DERIVATIVE_OF_PUBLIC_WWPDB_VALIDATION",
        }
    if relative_path.startswith("raw/rcsb-"):
        return {
            "source_url": f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}",
            "licence": "CC0-1.0",
            "access": "PUBLIC",
        }
    if relative_path.startswith("raw/pdbe-"):
        if "uniprot" in relative_path:
            source_url = f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id.lower()}"
        else:
            endpoint = "molecules" if "molecules" in relative_path else "summary"
            source_url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/{endpoint}/{pdb_id.lower()}"
        return {
            "source_url": source_url,
            "licence": "CC0-1.0",
            "access": "PUBLIC",
        }
    if relative_path == "raw/uniprot-P49815.json":
        return {
            "source_url": "https://rest.uniprot.org/uniprotkb/P49815.json",
            "licence": "CC-BY-4.0",
            "access": "PUBLIC",
        }
    if relative_path == "raw/uniprot-P49815.fasta":
        return {
            "source_url": "https://rest.uniprot.org/uniprotkb/P49815.fasta",
            "licence": "CC-BY-4.0",
            "access": "PUBLIC",
        }
    if relative_path.startswith("raw/pmc"):
        pmcid = "PMC7804450" if "7804450" in relative_path else "PMC11578170"
        return {
            "source_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=xml",
            "licence": article_licenses[relative_path],
            "access": "PUBLIC_OPEN_ACCESS_XML",
        }
    raise SourceValidationError(f"no source metadata for {relative_path}")


def _source_catalog(
    source_root: Path,
    output_root: Path,
    *,
    article_licenses: dict[str, str],
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for relative_path in sorted(INPUT_PATHS):
        input_path = source_root / relative_path
        _require(input_path.is_file(), f"required source is missing: {input_path}")
        item = {
            "relative_path": relative_path,
            "raw_sha256": _sha256_file(input_path),
            "raw_byte_length": input_path.stat().st_size,
            **_source_metadata(relative_path, article_licenses),
        }
        if relative_path.startswith("extracted/"):
            item["derivation"] = "gzip-decompressed wwPDB validation XML"
        sources.append(item)
    derived = []
    for relative_path in DERIVED_PATHS:
        if relative_path in {"source_catalog.json", "manifest.sha256"}:
            continue
        path = output_root / relative_path
        _require(path.is_file(), f"missing generated artifact {path}")
        derived.append(
            {
                "relative_path": relative_path,
                "derived_sha256": _sha256_file(path),
                "derived_byte_length": path.stat().st_size,
            }
        )
    catalog = {
        "schema": "rescuescreen.r611q.structure_source_catalog.v1",
        "pack_id": "r611q-structure-readiness-v1",
        "hash_basis": "sha256(canonical JSON excluding content_hash)",
        "sources": sources,
        "derived_artifacts": sorted(derived, key=lambda item: item["relative_path"]),
    }
    catalog["content_hash"] = _sha256_bytes(_canonical_json_bytes(catalog))
    return catalog


def _manifest_bytes(source_root: Path, output_root: Path) -> bytes:
    paths = sorted(set(INPUT_PATHS) | (set(DERIVED_PATHS) - {"manifest.sha256"}))
    lines: list[str] = []
    for relative_path in paths:
        path = source_root / relative_path if relative_path in INPUT_PATHS else output_root / relative_path
        _require(path.is_file(), f"cannot manifest missing path {path}")
        lines.append(f"{_sha256_file(path)}  {relative_path}\n")
    return "".join(lines).encode("utf-8")


def _readme() -> bytes:
    return """# R611Q structure-readiness v1

This deterministic, hash-bound evidence pack records only wild-type experimental
structure context for $\text{TSC2}$ residue 611. It is an evidence product for
human review, not a mechanism finding, pocket analysis, docking result, compound
screen, treatment recommendation, or RescueScreen-stage authorization.

## Rebuild

From the repository root, run:

```bash
python scripts/build_r611q_structure_readiness.py --pack-dir data/rescuescreen/r611q/structure-readiness-v1
python scripts/build_r611q_structure_readiness.py --pack-dir data/rescuescreen/r611q/structure-readiness-v1 --check
```

The builder uses Python standard library modules only. `--check` rebuilds into a
temporary sibling directory and compares every generated artifact byte-for-byte
without mutating this pack. `manifest.sha256` covers every pack file other than
itself. `source_catalog.json` includes raw input hashes and a self-excluding
canonical content hash.

## Scope boundary

The package preserves `EG-1` through `EG-5` as `NOT_SATISFIED`. In particular,
the supplied mapping evidence does not establish exact RefSeq-to-construct
equivalence, and residue inclusion does not measure a direct $\text{Arg611}$-
$\text{TSC1}$ contact, a pocket, or ligandability.
""".replace("\r\n", "\n").encode("utf-8")


def _evidence_lines(
    *,
    structures: list[dict[str, Any]],
    quote_7dl2: str,
    quote_9ce3: str,
) -> list[tuple[str, str, list[str], str]]:
    seven = structures[0]["target_residues"]
    nine = structures[1]["target_residues"]
    return [
        (
            "E001",
            "UniProt P49815 sequence residue 611 is R (Arg).",
            ["raw/uniprot-P49815.fasta", "raw/uniprot-P49815.json"],
            "SOURCE_REPORTED",
        ),
        (
            "E002",
            "7DL2 model 1 TSC2 entity 2 auth A/asym B label_seq 562/auth_seq 611 is wild-type ARG with 11 expected heavy-atom records, alt_id '.', and occupancy 1.00.",
            ["raw/pdb-7dl2.cif"],
            "SOURCE_REPORTED",
        ),
        (
            "E003",
            "7DL2 model 1 TSC2 entity 2 auth B/asym C label_seq 562/auth_seq 611 is wild-type ARG with 11 expected heavy-atom records, alt_id '.', and occupancy 1.00.",
            ["raw/pdb-7dl2.cif"],
            "SOURCE_REPORTED",
        ),
        (
            "E004",
            f"7DL2 validation auth A/asym B label_seq 562 reports Q_score {seven[0]['validation']['q_score']}, residue_inclusion {seven[0]['validation']['residue_inclusion']}, and rotamer {seven[0]['validation']['rotamer']}.",
            ["extracted/pdb-7dl2-validation.xml"],
            "SOURCE_REPORTED",
        ),
        (
            "E005",
            f"7DL2 validation auth B/asym C label_seq 562 reports Q_score {seven[1]['validation']['q_score']}, residue_inclusion {seven[1]['validation']['residue_inclusion']}, and rotamer {seven[1]['validation']['rotamer']}.",
            ["extracted/pdb-7dl2-validation.xml"],
            "SOURCE_REPORTED",
        ),
        (
            "E006",
            "9CE3 model 1 TSC2 entity 1 auth A/asym A and auth B/asym B label_seq 619/auth_seq 611 are wild-type ARG with 11 expected heavy-atom records, alt_id '.', and occupancy 1.00.",
            ["raw/pdb-9ce3.cif"],
            "SOURCE_REPORTED",
        ),
        (
            "E007",
            f"9CE3 validation auth A/asym A label_seq 619 reports Q_score {nine[0]['validation']['q_score']}, residue_inclusion {nine[0]['validation']['residue_inclusion']}, and rotamer {nine[0]['validation']['rotamer']}; auth B/asym B reports Q_score {nine[1]['validation']['q_score']}, residue_inclusion {nine[1]['validation']['residue_inclusion']}, and rotamer {nine[1]['validation']['rotamer']}.",
            ["extracted/pdb-9ce3-validation.xml"],
            "SOURCE_REPORTED",
        ),
        (
            "E008",
            "PDBe deposited entry summaries report ligand=0 and water=0 for both 7DL2 and 9CE3; this is deposited inventory only and does not establish non-ligandability.",
            ["raw/pdbe-7dl2-summary.json", "raw/pdbe-9ce3-summary.json"],
            "SOURCE_REPORTED",
        ),
        (
            "E009",
            f'PMC7804450 reports: "{quote_7dl2}"',
            ["raw/pmc7804450.xml"],
            "SOURCE_REPORTED",
        ),
        (
            "E010",
            f'PMC11578170 reports: "{quote_9ce3}"',
            ["raw/pmc11578170.xml"],
            "SOURCE_REPORTED",
        ),
        (
            "E011",
            "The scoped primary-article XML contains no R611 or R611Q statement, and the scoped coordinates contain wild-type ARG611 rather than a GLN mutant structure.",
            [
                "raw/pmc7804450.xml",
                "raw/pmc11578170.xml",
                "raw/pdb-7dl2.cif",
                "raw/pdb-9ce3.cif",
            ],
            "SOURCE_REPORTED",
        ),
        (
            "E012",
            "No coordinate contact calculation is included in this pack; a direct Arg611-TSC1 contact or salt bridge, a pocket, and ligandability remain unsupported or unmeasured.",
            ["raw/pdb-7dl2.cif", "raw/pdb-9ce3.cif"],
            "UNTRUSTED",
        ),
    ]


def _claims_from_evidence(
    evidence: str, definitions: Iterable[tuple[str, str, list[str], str]]
) -> dict[str, Any]:
    claims = []
    for evidence_id, statement, raw_refs, status in definitions:
        start = evidence.find(statement)
        _require(start >= 0, f"evidence statement {evidence_id} was not emitted")
        end = start + len(statement)
        claims.append(
            {
                "claim_id": f"SR-{evidence_id}",
                "claim_text": statement,
                "evidence_id": evidence_id,
                "verification_status": status,
                "locator": f"text-char:{start}:{end}",
                "exact_quote": evidence[start:end],
                "raw_source_refs": raw_refs,
            }
        )
    return {
        "schema": "rescuescreen.r611q.structure_claims.v1",
        "claim_status_vocabulary": ["SOURCE_REPORTED", "UNTRUSTED"],
        "claims": claims,
    }


def _build_payloads(
    source_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    raw = source_root / "raw"
    extracted = source_root / "extracted"

    for pdb_id in ("7dl2", "9ce3"):
        compressed = raw / f"pdb-{pdb_id}-validation.xml.gz"
        decompressed = extracted / f"pdb-{pdb_id}-validation.xml"
        _require(compressed.is_file() and decompressed.is_file(), f"missing {pdb_id} validation pair")
        _require(
            gzip.decompress(compressed.read_bytes()) == decompressed.read_bytes(),
            f"{pdb_id} validation XML is not the exact gzip decompression",
        )

    uniprot_json = _load_json(raw / "uniprot-P49815.json")
    fasta_lines = (raw / "uniprot-P49815.fasta").read_text(encoding="utf-8").splitlines()
    fasta_sequence = "".join(line.strip() for line in fasta_lines if not line.startswith(">"))
    _require(uniprot_json.get("primaryAccession") == "P49815", "UniProt source is not P49815")
    _require(len(fasta_sequence) >= 611 and fasta_sequence[610] == "R", "P49815 residue 611 is not R")
    _require(
        uniprot_json.get("sequence", {}).get("value") == fasta_sequence,
        "UniProt JSON and FASTA sequences do not match",
    )

    rcsb_7 = _load_json(raw / "rcsb-7dl2-entry.json")
    rcsb_9 = _load_json(raw / "rcsb-9ce3-entry.json")
    _require(rcsb_7.get("entry", {}).get("id") == "7DL2", "RCSB entry source is not 7DL2")
    _require(rcsb_9.get("entry", {}).get("id") == "9CE3", "RCSB entry source is not 9CE3")
    _require(
        rcsb_7["rcsb_entry_info"]["resolution_combined"] == [4.4]
        and rcsb_9["rcsb_entry_info"]["resolution_combined"] == [2.9],
        "RCSB global resolutions do not match the frozen facts",
    )
    _require(
        rcsb_7["exptl"] == [{"method": "ELECTRON MICROSCOPY"}]
        and rcsb_9["exptl"] == [{"method": "ELECTRON MICROSCOPY"}],
        "RCSB experimental methods do not match the frozen facts",
    )

    pdbe_7_summary = _load_json(raw / "pdbe-7dl2-summary.json")["7dl2"][0]
    pdbe_9_summary = _load_json(raw / "pdbe-9ce3-summary.json")["9ce3"][0]
    for pdb_id, summary, assembly_name in (
        ("7DL2", pdbe_7_summary, "hexamer"),
        ("9CE3", pdbe_9_summary, "octamer"),
    ):
        inventory = summary["number_of_entities"]
        _require(
            inventory["ligand"] == 0 and inventory["water"] == 0,
            f"{pdb_id} PDBe deposited inventory is not ligand=0/water=0",
        )
        _require(
            summary["assemblies"] == [{"assembly_id": "1", "name": assembly_name, "form": "hetero", "preferred": True}],
            f"{pdb_id} PDBe preferred assembly is not {assembly_name}",
        )

    map_7 = _load_json(raw / "pdbe-7dl2-uniprot.json")["7dl2"]["UniProt"]["P49815"]["mappings"]
    map_9 = _load_json(raw / "pdbe-9ce3-uniprot.json")["9ce3"]["UniProt"]["P49815"]["mappings"]
    expected_map_7 = [
        ("A", "B", 2, 50, 1807, 1, 1692, 0.96),
        ("B", "C", 2, 50, 1807, 1, 1692, 0.96),
    ]
    expected_map_9 = [
        ("A", "A", 1, 2, 1807, 10, 1792, 0.99),
        ("B", "B", 1, 2, 1807, 10, 1792, 0.99),
    ]

    def mapping_rows(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [
            (
                row["chain_id"],
                row["struct_asym_id"],
                row["entity_id"],
                row["unp_start"],
                row["unp_end"],
                row["start"]["residue_number"],
                row["end"]["residue_number"],
                row["identity"],
            )
            for row in rows
        ]

    _require(mapping_rows(map_7) == expected_map_7, "7DL2 PDBe UniProt mappings differ")
    _require(mapping_rows(map_9) == expected_map_9, "9CE3 PDBe UniProt mappings differ")

    coordinate_7 = _coordinate_target(
        raw / "pdb-7dl2.cif",
        pdb_id="7DL2",
        entity_id="2",
        expected_chains=(("A", "B", "562"), ("B", "C", "562")),
    )
    coordinate_9 = _coordinate_target(
        raw / "pdb-9ce3.cif",
        pdb_id="9CE3",
        entity_id="1",
        expected_chains=(("A", "A", "619"), ("B", "B", "619")),
    )
    for cif_path, pdb_id, entity_id, chains in (
        (raw / "pdb-7dl2-assembly1.cif", "7DL2 assembly 1", "2", (("A", "B", "562"), ("B", "C", "562"))),
        (raw / "pdb-9ce3-assembly1.cif", "9CE3 assembly 1", "1", (("A", "A", "619"), ("B", "B", "619"))),
    ):
        _coordinate_target(cif_path, pdb_id=pdb_id, entity_id=entity_id, expected_chains=chains)

    validation_7 = _validation_target(
        extracted / "pdb-7dl2-validation.xml",
        pdb_id="7DL2",
        expected=(
            ("A", "B", "562", "0.303", "1.0000", "mpp80"),
            ("B", "C", "562", "0.268", "0.8182", "mtt180"),
        ),
    )
    validation_9 = _validation_target(
        extracted / "pdb-9ce3-validation.xml",
        pdb_id="9CE3",
        expected=(
            ("A", "A", "619", "0.454", "0.8182", "mtm180"),
            ("B", "B", "619", "0.483", "1.0000", "mtm180"),
        ),
    )

    for coordinate in coordinate_7:
        coordinate["validation"] = validation_7[(coordinate["auth_asym_id"], coordinate["label_asym_id"])]
    for coordinate in coordinate_9:
        coordinate["validation"] = validation_9[(coordinate["auth_asym_id"], coordinate["label_asym_id"])]

    molecules_7 = _load_json(raw / "pdbe-7dl2-molecules.json")["7dl2"]
    molecules_9 = _load_json(raw / "pdbe-9ce3-molecules.json")["9ce3"]
    molecule_signature_7 = [
        (item["entity_id"], item["molecule_name"], item["in_chains"], item["in_struct_asyms"])
        for item in molecules_7
    ]
    molecule_signature_9 = [
        (item["entity_id"], item["molecule_name"], item["in_chains"], item["in_struct_asyms"])
        for item in molecules_9
    ]
    _require(
        molecule_signature_7
        == [
            (1, ["Hamartin"], ["C", "D"], ["A", "D"]),
            (2, ["Tuberin"], ["A", "B"], ["B", "C"]),
            (3, ["TBC1 domain family member 7"], ["E"], ["E"]),
            (4, ["unknown protein"], ["F"], ["F"]),
        ],
        "7DL2 molecule inventory differs",
    )
    _require(
        molecule_signature_9
        == [
            (1, ["Tuberin"], ["A", "B"], ["A", "B"]),
            (2, ["Hamartin"], ["C", "D"], ["C", "D"]),
            (3, ["TBC1 domain family member 7"], ["E"], ["E"]),
            (4, ["WD repeat domain phosphoinositide-interacting protein 3"], ["F"], ["F"]),
            (5, ["Unknown fragment"], ["G", "H"], ["G", "H"]),
        ],
        "9CE3 molecule inventory differs",
    )

    cif_7 = raw / "pdb-7dl2.cif"
    cif_9 = raw / "pdb-9ce3.cif"
    _require(
        _read_cif_scalar(cif_7, "_pdbx_struct_assembly.details") == "author_defined_assembly"
        and _read_cif_scalar(cif_7, "_pdbx_struct_assembly.oligomeric_details") == "hexameric"
        and _read_cif_scalar(cif_7, "_pdbx_struct_assembly.oligomeric_count") == "6",
        "7DL2 assembly is not the expected author-defined hexamer",
    )
    _require(
        _read_cif_scalar(cif_9, "_pdbx_struct_assembly.details") == "author_defined_assembly"
        and _read_cif_scalar(cif_9, "_pdbx_struct_assembly.oligomeric_details") == "octameric"
        and _read_cif_scalar(cif_9, "_pdbx_struct_assembly.oligomeric_count") == "8",
        "9CE3 assembly is not the expected author-defined octamer",
    )
    _require(
        _read_cif_scalar(cif_7, "_pdbx_struct_assembly_gen.assembly_id") == "1"
        and _read_cif_scalar(cif_7, "_pdbx_struct_assembly_gen.asym_id_list") == "A,B,C,D,E,F",
        "7DL2 assembly members differ",
    )
    _require(
        _read_cif_scalar(cif_9, "_pdbx_struct_assembly_gen.assembly_id") == "1"
        and _read_cif_scalar(cif_9, "_pdbx_struct_assembly_gen.asym_id_list") == "A,B,C,D,E,F,G,H",
        "9CE3 assembly members differ",
    )

    article_7 = _article_text(raw / "pmc7804450.xml")
    article_9 = _article_text(raw / "pmc11578170.xml")
    for article_name, article in (("PMC7804450", article_7), ("PMC11578170", article_9)):
        _require("R611" not in article and "Arg611" not in article, f"{article_name} mentions R611/R611Q")
    quote_7 = _bounded_quote(
        article_7,
        "The structure was determined by cryo-EM single particle reconstruction",
        "respectively",
        "PMC7804450",
    )
    quote_9 = _bounded_quote(
        article_9,
        "Here, focused refinement and classification stepped along the 40 nm length",
        "2.8 Å",
        "PMC11578170",
    )
    _require("overall resolution of 4.4 Å" in quote_7 and "locally refined" in quote_7, "7DL2 article quote is incomplete")
    _require(
        "final composite reconstruction with an average nominal resolution of 2.8 Å" in quote_9,
        "9CE3 article quote is incomplete",
    )

    structures = [
        {
            "pdb_id": "7DL2",
            "method": "ELECTRON MICROSCOPY",
            "repository_global_resolution_angstrom": "4.4",
            "emdb": "EMD-30708",
            "construct_mapping": {
                "mapping_resource": "PDBe UniProt P49815 mapping",
                "entity_id": 2,
                "label_range": "1-1692",
                "uniprot_range": "50-1807",
                "reported_identity": 0.96,
                "target_display_offset": "+49",
                "offset_limit": "The range offset is descriptive only; it is not a residue-level RefSeq-to-construct equivalence proof.",
            },
            "entities_and_copies": [
                {"entity_id": item["entity_id"], "name": item["molecule_name"][0], "author_chains": item["in_chains"], "asym_ids": item["in_struct_asyms"]}
                for item in molecules_7
            ],
            "assembly": {
                "assembly_id": "1",
                "details": "author_defined_assembly",
                "oligomer": "hexamer",
                "asym_ids": ["A", "B", "C", "D", "E", "F"],
                "composition": "TSC1x2/TSC2x2/TBC1D7/unknown",
            },
            "target_residues": coordinate_7,
            "deposited_inventory": {
                "ligand_entities": 0,
                "water_entities": 0,
                "scope": "Deposited inventory only; it does not establish non-ligandability.",
            },
            "publication_context": {
                "pmcid": "PMC7804450",
                "bounded_quote": quote_7,
                "statement": "The article reports a 4.4 Å cryo-EM map and local refinements.",
            },
        },
        {
            "pdb_id": "9CE3",
            "method": "ELECTRON MICROSCOPY",
            "repository_global_resolution_angstrom": "2.9",
            "emdb": "EMD-45492",
            "construct_mapping": {
                "mapping_resource": "PDBe UniProt P49815 mapping",
                "entity_id": 1,
                "label_range": "10-1792",
                "uniprot_range": "2-1807",
                "reported_identity": 0.99,
                "target_display_offset": "-8",
                "offset_limit": "The range offset is descriptive only; it is not a residue-level RefSeq-to-construct equivalence proof.",
            },
            "entities_and_copies": [
                {"entity_id": item["entity_id"], "name": item["molecule_name"][0], "author_chains": item["in_chains"], "asym_ids": item["in_struct_asyms"]}
                for item in molecules_9
            ],
            "assembly": {
                "assembly_id": "1",
                "details": "author_defined_assembly",
                "oligomer": "octamer",
                "asym_ids": ["A", "B", "C", "D", "E", "F", "G", "H"],
                "composition": "TSC2x2/TSC1x2/TBC1D7/WIPI3/unknown fragmentsx2",
            },
            "target_residues": coordinate_9,
            "deposited_inventory": {
                "ligand_entities": 0,
                "water_entities": 0,
                "scope": "Deposited inventory only; it does not establish non-ligandability.",
            },
            "publication_context": {
                "pmcid": "PMC11578170",
                "bounded_quote": quote_9,
                "statement": "The article reports a final composite average nominal 2.8 Å resolution.",
            },
        },
    ]
    contexts = {
        "schema": "rescuescreen.r611q.structure_contexts.v1",
        "structures": structures,
        "limitations": [
            "No coordinate contact calculation is part of this pack.",
            "A direct Arg611-TSC1 contact or salt bridge is unsupported and unmeasured.",
            "A pocket and ligandability are unsupported and unmeasured.",
            "No Q-score average or pass/fail threshold is assigned.",
            "Neither scoped coordinate entry is an R611Q mutant structure.",
        ],
    }
    identity = {
        "schema": "rescuescreen.r611q.structure_identity_mapping.v1",
        "variant_crosswalk": {
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
        },
        "structure_crosswalks": [
            {
                "pdb_id": "7DL2",
                "entity_id": 2,
                "copies": [
                    {"auth_asym_id": "A", "label_asym_id": "B", "label_seq_id": 562, "auth_seq_id": 611},
                    {"auth_asym_id": "B", "label_asym_id": "C", "label_seq_id": 562, "auth_seq_id": 611},
                ],
                "pdbe_uniprot_mapping": {"uniprot_start": 50, "uniprot_end": 1807, "label_start": 1, "label_end": 1692, "reported_identity": 0.96},
                "target_display_offset": "+49",
            },
            {
                "pdb_id": "9CE3",
                "entity_id": 1,
                "copies": [
                    {"auth_asym_id": "A", "label_asym_id": "A", "label_seq_id": 619, "auth_seq_id": 611},
                    {"auth_asym_id": "B", "label_asym_id": "B", "label_seq_id": 619, "auth_seq_id": 611},
                ],
                "pdbe_uniprot_mapping": {"uniprot_start": 2, "uniprot_end": 1807, "label_start": 10, "label_end": 1792, "reported_identity": 0.99},
                "target_display_offset": "-8",
            },
        ],
        "limitations": [
            "PDBe mapping ranges and coordinate residue labels support a UniProt-context crosswalk but do not provide an explicit residue-by-residue RefSeq NP_000539.2-to-PDB-construct alignment; exact RefSeq-to-PDB-construct equivalence remains unverified.",
            "The construct/isoform display offsets are context only and must not be used as residue-offset arithmetic to claim exact RefSeq-to-construct equivalence.",
            "Human review remains required for EG-2.",
        ],
    }
    definitions = _evidence_lines(structures=structures, quote_7dl2=quote_7, quote_9ce3=quote_9)
    evidence = "".join(f"{evidence_id} | {statement}\n" for evidence_id, statement, _, _ in definitions)
    claims = _claims_from_evidence(evidence, definitions)
    contradiction_register = {
        "schema": "rescuescreen.r611q.structure_contradiction_register.v1",
        "true_contradiction_detected": False,
        "entries": [
            {
                "id": "CR-1",
                "classification": "NUMBERING_HAZARD",
                "statement": "Author chain identifiers and label asym identifiers differ in 7DL2 (A/B to B/C), and target label sequence numbers differ between entries.",
                "resolution": "Retain both author and label identifiers in every target record.",
            },
            {
                "id": "CR-2",
                "classification": "COPY_LEVEL_DISAGREEMENT",
                "statement": "7DL2 target copies have different reported rotamers: mpp80 for auth A/asym B and mtt180 for auth B/asym C.",
                "resolution": "Report copy-specific raw metrics; do not average Q-scores or assign a threshold.",
            },
            {
                "id": "CR-3",
                "classification": "CONTEXT_DIFFERENCE_NOT_CONTRADICTION",
                "statement": "9CE3 repository global resolution is 2.9 Å, while the publication reports a final composite average nominal resolution of 2.8 Å.",
                "resolution": "Retain both labels because they describe different reporting contexts.",
            },
            {
                "id": "CR-4",
                "classification": "EVIDENCE_LIMIT",
                "statement": "No R611Q mutant structure occurs in the scoped coordinate sources.",
                "resolution": "Wild-type context only.",
            },
            {
                "id": "CR-5",
                "classification": "UNMEASURED",
                "statement": "A direct Arg611-TSC1 contact or salt bridge, a pocket, and ligandability are not measured in this pack.",
                "resolution": "Do not infer contacts, pockets, or ligandability.",
            },
        ],
    }
    gap_map = {
        "schema": "rescuescreen.r611q.structure_evidence_gap_map.v1",
        "human_review_state": "PENDING",
        "gates": [
            {
                "gate_id": "EG-2",
                "evidence_status": "PACK_EVIDENCE_READY_FOR_HUMAN_REVIEW",
                "gate_status": "NOT_SATISFIED",
                "gap": "Exact RefSeq-to-PDB-construct equivalence remains unverified.",
            },
            {
                "gate_id": "EG-3",
                "evidence_status": "PACK_EVIDENCE_READY_FOR_HUMAN_REVIEW",
                "gate_status": "NOT_SATISFIED",
                "gap": "Human review is required for structure coverage and uncertainty assessment.",
            },
        ],
        "unresolved_evidence": [
            "No R611Q mutant structure in scoped sources.",
            "Direct Arg611-TSC1 contact or salt bridge unmeasured.",
            "Pocket and ligandability unmeasured.",
        ],
    }
    readiness = {
        "schema": "rescuescreen.r611q.structure_readiness_assessment.v1",
        "readiness": "EVIDENCE_PACK_READY_FOR_HUMAN_REVIEW",
        "gate_states": {
            "EG-1": "NOT_SATISFIED",
            "EG-2": "NOT_SATISFIED",
            "EG-3": "NOT_SATISFIED",
            "EG-4": "NOT_SATISFIED",
            "EG-5": "NOT_SATISFIED",
        },
        "first_blocker": {"gate_id": "EG-1", "fail_state": "MECHANISM_UNVERIFIED"},
        "atlas_boundary": {
            "gate_8": "BLOCKED_HUMAN_REVIEW",
            "accepted_claim_count": 0,
            "changed_by_this_pack": False,
        },
        "stage_execution_authorized": False,
        "authorization_ceiling": {
            "compound_screening_authorized": False,
            "docking_authorized": False,
            "treatment_authorized": False,
        },
    }
    return identity, contexts, evidence, claims, contradiction_register, gap_map, readiness


def build(source_root: Path, output_root: Path) -> list[Path]:
    """Validate frozen inputs and deterministically write derived pack artifacts."""

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    _require(source_root.is_dir(), f"source pack directory does not exist: {source_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    payloads = _build_payloads(source_root)
    identity, contexts, evidence, claims, contradiction_register, gap_map, readiness = payloads
    article_licenses = {
        "raw/pmc7804450.xml": _article_license(source_root / "raw/pmc7804450.xml"),
        "raw/pmc11578170.xml": _article_license(source_root / "raw/pmc11578170.xml"),
    }

    generated = {
        "README.md": _readme(),
        "identity_mapping.json": _json_file_bytes(identity),
        "structure_contexts.json": _json_file_bytes(contexts),
        "extracted/structure_evidence.txt": evidence.encode("utf-8"),
        "claims.json": _json_file_bytes(claims),
        "contradiction_register.json": _json_file_bytes(contradiction_register),
        "evidence_gap_map.json": _json_file_bytes(gap_map),
        "readiness_assessment.json": _json_file_bytes(readiness),
    }
    for relative_path, content in generated.items():
        _write_bytes(output_root / relative_path, content)

    catalog = _source_catalog(source_root, output_root, article_licenses=article_licenses)
    _write_bytes(output_root / "source_catalog.json", _json_file_bytes(catalog))
    _write_bytes(output_root / "manifest.sha256", _manifest_bytes(source_root, output_root))
    return [output_root / relative_path for relative_path in DERIVED_PATHS]


def check(pack_root: Path) -> None:
    """Rebuild to a temporary sibling and compare committed artifacts exactly."""

    pack_root = pack_root.resolve()
    expected_files = set(INPUT_PATHS) | set(DERIVED_PATHS)
    actual_files = {
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*")
        if path.is_file()
    }
    _require(
        actual_files == expected_files,
        f"pack file set differs from declared inputs/artifacts: {sorted(actual_files ^ expected_files)}",
    )
    with tempfile.TemporaryDirectory(
        prefix=".r611q-structure-readiness-check-", dir=pack_root.parent
    ) as temporary_directory:
        rebuilt_root = Path(temporary_directory)
        build(pack_root, rebuilt_root)
        for relative_path in DERIVED_PATHS:
            expected = (rebuilt_root / relative_path).read_bytes()
            actual = (pack_root / relative_path).read_bytes()
            _require(
                actual == expected,
                f"committed artifact differs from reproducible rebuild: {relative_path}",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack-dir",
        type=Path,
        default=PACK_RELATIVE,
        help="structure-readiness pack root (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify derived artifacts byte-for-byte without mutating the pack",
    )
    arguments = parser.parse_args()
    try:
        if arguments.check:
            check(arguments.pack_dir)
            print("R611Q structure-readiness pack check: OK")
        else:
            build(arguments.pack_dir, arguments.pack_dir)
            print("R611Q structure-readiness pack build: OK")
    except SourceValidationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
