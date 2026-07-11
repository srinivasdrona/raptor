"""Reproduce the aggregate AAVC/RAPTOR TSC VUS prior-art comparison.

AAVC output is an external comparator only. This script never treats an AAVC
machine class as an ACMG criterion, truth label, or expert classification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from raptor.eval.combine import implied_direction
from raptor.eval.config import load_config as load_eval_config
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.parse import parse_rationale


AAVC_DIRECTIONAL_CLASSES = {
    "PATHOGENIC",
    "LIKELY_PATHOGENIC",
    "LIKELY_BENIGN",
    "BENIGN",
}
AAVC_CLASS_ORDER = (
    "PATHOGENIC",
    "LIKELY_PATHOGENIC",
    "VUS-HIGH",
    "VUS-MID",
    "VUS-LOW",
    "LIKELY_BENIGN",
    "BENIGN",
)
RAPTOR_DIRECTION_ORDER = ("LP", "LB", "no_call", "manual")
AAVC_DIRECTION_ORDER = ("LP", "LB", "no_call")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_aavc_key(key: str) -> tuple[str, int, str, str]:
    parts = key.split("-", 3)
    if len(parts) != 4:
        raise ValueError(f"invalid AAVC variant key {key!r}")
    chromosome, position, ref, alt = parts
    return chromosome, int(position), ref, alt


def common_trim_key(key: str) -> tuple[str, int, str, str]:
    """Remove shared VCF anchor bases without reference-backed repeat rolling."""
    chromosome, position, ref, alt = _parse_aavc_key(key)
    while ref and alt and ref[-1] == alt[-1]:
        ref = ref[:-1]
        alt = alt[:-1]
    while ref and alt and ref[0] == alt[0]:
        ref = ref[1:]
        alt = alt[1:]
        position += 1
    return chromosome, position, ref or "-", alt or "-"


def _manifest_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            row = json.loads(line)
            chromosome, position, ref, alt = row["vcf_key"].split(":", 3)
            key = f"{chromosome.removeprefix('chr')}-{position}-{ref}-{alt}"
            if key in records:
                raise ValueError(f"duplicate manifest VCF key {key!r} at line {line_number}")
            records[key] = row
    return records


def _raptor_directions(
    bias_path: Path,
    scorer_config_path: Path,
    eval_config_path: Path,
) -> dict[str, str]:
    scorer_config = load_scorer_config(scorer_config_path)
    eval_config = load_eval_config(eval_config_path)
    directions: dict[str, str] = {}

    for record in BiasTsvSource(bias_path).records():
        key = (
            f"{record.chromosome.removeprefix('chr')}-{record.position}-"
            f"{record.ref_allele}-{record.alt_allele}"
        )
        calls = parse_rationale(record.criteria, scorer_config.strength_map)
        implied = implied_direction(
            [
                (call.criterion, call.strength, call.direction)
                for call in calls
            ],
            eval_config,
        )
        direction = "manual" if record.gene_name not in {"TSC1", "TSC2"} else implied.implied
        if key in directions:
            raise ValueError(f"duplicate BIAS VCF key {key!r}")
        directions[key] = direction

    return directions


def _aavc_direction(classification: str) -> str:
    if classification in {"PATHOGENIC", "LIKELY_PATHOGENIC"}:
        return "LP"
    if classification in {"BENIGN", "LIKELY_BENIGN"}:
        return "LB"
    return "no_call"


def analyze(
    *,
    manifest_path: Path,
    bias_path: Path,
    aavc_path: Path,
    scorer_config_path: Path,
    eval_config_path: Path,
    aavc_repository_commit: str,
    aavc_release_doi: str,
    aavc_archive_file: str,
    aavc_archive_bytes: int,
    aavc_archive_md5: str,
    aavc_source_snapshot: str,
    raptor_source_snapshot: str,
) -> dict[str, Any]:
    manifest = _manifest_records(manifest_path)
    raptor_directions = _raptor_directions(
        bias_path,
        scorer_config_path,
        eval_config_path,
    )
    if set(manifest) != set(raptor_directions):
        raise ValueError(
            "manifest/BIAS identity sets differ: "
            f"manifest={len(manifest)}, BIAS={len(raptor_directions)}, "
            f"symmetric_difference={len(set(manifest) ^ set(raptor_directions))}"
        )

    normalized_manifest: dict[tuple[str, int, str, str], list[str]] = defaultdict(list)
    for key in manifest:
        normalized_manifest[common_trim_key(key)].append(key)
    collisions = {key: values for key, values in normalized_manifest.items() if len(values) > 1}
    if collisions:
        raise ValueError(f"common-trim collisions in RAPTOR manifest: {collisions!r}")

    release_rows = 0
    source_vus_rows = 0
    source_vus_directional = 0
    tsc_vus_rows = Counter()
    tsc_vus_directional = Counter()
    matches: dict[str, tuple[dict[str, str], str]] = {}

    with aavc_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            release_rows += 1
            classification = row["ACMG_class"] or "<EMPTY>"
            source_significance = row["sig"] or "<EMPTY>"
            gene = row["gene"] or "<EMPTY>"

            if source_significance == "VUS":
                source_vus_rows += 1
                if classification in AAVC_DIRECTIONAL_CLASSES:
                    source_vus_directional += 1
                if gene in {"TSC1", "TSC2"}:
                    tsc_vus_rows[gene] += 1
                    if classification in AAVC_DIRECTIONAL_CLASSES:
                        tsc_vus_directional[gene] += 1

            aavc_key = row["ID"]
            if aavc_key in manifest:
                target = aavc_key
                match_method = "exact_vcf_key"
            else:
                candidates = normalized_manifest.get(common_trim_key(aavc_key), [])
                if not candidates:
                    continue
                target = candidates[0]
                match_method = "common_trim_equivalent"

            if target in matches:
                prior_row, prior_method = matches[target]
                raise ValueError(
                    f"multiple AAVC rows map to RAPTOR key {target!r}: "
                    f"{prior_row['ID']!r} ({prior_method}) and "
                    f"{aavc_key!r} ({match_method})"
                )
            matches[target] = (row, match_method)

    method_counts = Counter()
    class_counts = Counter()
    cross_tab: dict[str, Counter[str]] = defaultdict(Counter)
    non_vus_source_matches = 0

    for key, (row, match_method) in matches.items():
        method_counts[match_method] += 1
        classification = row["ACMG_class"] or "<EMPTY>"
        class_counts[classification] += 1
        if row["sig"] != "VUS":
            non_vus_source_matches += 1
        cross_tab[raptor_directions[key]][_aavc_direction(classification)] += 1

    both_directional = sum(
        cross_tab[raptor_direction][aavc_direction]
        for raptor_direction in ("LP", "LB")
        for aavc_direction in ("LP", "LB")
    )
    agreements = cross_tab["LP"]["LP"] + cross_tab["LB"]["LB"]
    disagreements = cross_tab["LP"]["LB"] + cross_tab["LB"]["LP"]
    tsc_total = tsc_vus_rows["TSC1"] + tsc_vus_rows["TSC2"]
    tsc_directional = tsc_vus_directional["TSC1"] + tsc_vus_directional["TSC2"]
    combined_matches = len(matches)
    aavc_directional_matches = sum(
        class_counts[classification]
        for classification in AAVC_DIRECTIONAL_CLASSES
    )
    historical_sig_count = "One" if non_vus_source_matches == 1 else str(non_vus_source_matches)

    return {
        "status": "prior_art_comparison_non_authoritative",
        "comparison_date": "2026-07-10",
        "sources": {
            "aavc_repository": {
                "url": "https://github.com/OzcelikLab/AAVC",
                "commit": aavc_repository_commit,
            },
            "aavc_classification_release": {
                "doi": aavc_release_doi,
                "source_snapshot": aavc_source_snapshot,
                "archive_file": aavc_archive_file,
                "archive_bytes": aavc_archive_bytes,
                "archive_md5": aavc_archive_md5,
                "extracted_file_sha256": _sha256(aavc_path),
            },
            "raptor_corpus": {
                "source_snapshot": raptor_source_snapshot,
                "manifest_sha256": _sha256(manifest_path),
                "bias_output_sha256": _sha256(bias_path),
            },
        },
        "method": {
            "script": "scripts/audit_aavc_overlap.py",
            "primary_match": "exact GRCh38 VCF key: chromosome-position-reference-alternate",
            "secondary_match": "common-prefix/suffix-trim equivalence for differently anchored VCF indels",
            "secondary_match_limit": "not full reference-backed SPDI repeat normalization",
            "raptor_direction": "current eval-only Tavtigian point combiner; manual queue retained",
            "aavc_direction": "PATHOGENIC/LIKELY_PATHOGENIC -> LP; BENIGN/LIKELY_BENIGN -> LB; VUS-* -> no_call",
        },
        "aavc_release": {
            "rows": release_rows,
            "clinvar_vus_rows": source_vus_rows,
            "clinvar_vus_machine_called_non_vus": source_vus_directional,
            "clinvar_vus_machine_called_non_vus_fraction": round(
                source_vus_directional / source_vus_rows, 6
            ),
            "tsc1_vus_rows": tsc_vus_rows["TSC1"],
            "tsc2_vus_rows": tsc_vus_rows["TSC2"],
            "tsc_vus_rows": tsc_total,
            "tsc_vus_machine_called_non_vus": tsc_directional,
            "tsc_vus_machine_called_non_vus_fraction": round(
                tsc_directional / tsc_total, 6
            ),
        },
        "raptor_overlap": {
            "raptor_vus_rows": len(manifest),
            "exact_vcf_key_matches": method_counts["exact_vcf_key"],
            "common_trim_equivalent_matches": method_counts["common_trim_equivalent"],
            "combined_matches": combined_matches,
            "combined_match_fraction": round(combined_matches / len(manifest), 6),
            "unmatched": len(manifest) - combined_matches,
            "aavc_classes_on_combined_matches": {
                classification.replace("-", "_"): class_counts[classification]
                for classification in AAVC_CLASS_ORDER
            },
            "aavc_directional_calls": aavc_directional_matches,
            "aavc_directional_call_fraction": round(
                aavc_directional_matches / combined_matches, 6
            ),
            "direction_cross_tab": {
                "raptor_candidate_LP": {
                    f"aavc_{direction}": cross_tab["LP"][direction]
                    for direction in AAVC_DIRECTION_ORDER
                },
                "raptor_candidate_LB": {
                    f"aavc_{direction}": cross_tab["LB"][direction]
                    for direction in AAVC_DIRECTION_ORDER
                },
                "raptor_no_call": {
                    f"aavc_{direction}": cross_tab["no_call"][direction]
                    for direction in AAVC_DIRECTION_ORDER
                },
                "raptor_manual": {
                    f"aavc_{direction}": cross_tab["manual"][direction]
                    for direction in AAVC_DIRECTION_ORDER
                },
            },
            "both_systems_directional": both_directional,
            "direction_agreements": agreements,
            "direction_disagreements": disagreements,
            "agreement_fraction_when_both_directional": round(
                agreements / both_directional, 6
            ),
        },
        "interpretation_limits": [
            "RAPTOR candidate directions and AAVC machine classes are not expert classifications.",
            "Agreement is not accuracy because the systems use overlapping public sources and AAVC target-label masking is undocumented.",
            "The snapshots are 22 months apart; unmatched variants cannot be assumed to be absent from AAVC solely because of method differences.",
            f"{historical_sig_count} common-trim match was PLP in AAVC's September-2024 source but VUS in RAPTOR's July-2026 source.",
            "AAVC VUS-HIGH, VUS-MID and VUS-LOW remain VUS and are not standard external ClinVar classes.",
            "AAVC's software license does not permit redistribution, modification or derivative software; no AAVC code may be copied into RAPTOR.",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bias-output", type=Path, required=True)
    parser.add_argument("--aavc-release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scorer-config",
        type=Path,
        default=repository_root / "configs" / "acmg" / "tsc.yaml",
    )
    parser.add_argument(
        "--eval-config",
        type=Path,
        default=repository_root / "configs" / "eval" / "tsc2.yaml",
    )
    parser.add_argument(
        "--aavc-repository-commit",
        default="8da2b5ac7cf92830b792d521818a2ace50a0e2e1",
    )
    parser.add_argument("--aavc-release-doi", default="10.5281/zenodo.17201194")
    parser.add_argument(
        "--aavc-archive-file",
        default="AAVC_Classification_ClinVar_September2024.zip",
    )
    parser.add_argument("--aavc-archive-bytes", type=int, default=87193970)
    parser.add_argument(
        "--aavc-archive-md5",
        default="39308efd7694e2dacc9c1ac281f27a66",
    )
    parser.add_argument("--aavc-source-snapshot", default="ClinVar September 2024")
    parser.add_argument("--raptor-source-snapshot", default="ClinVar 2026-07-07")
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = analyze(
        manifest_path=args.manifest,
        bias_path=args.bias_output,
        aavc_path=args.aavc_release,
        scorer_config_path=args.scorer_config,
        eval_config_path=args.eval_config,
        aavc_repository_commit=args.aavc_repository_commit,
        aavc_release_doi=args.aavc_release_doi,
        aavc_archive_file=args.aavc_archive_file,
        aavc_archive_bytes=args.aavc_archive_bytes,
        aavc_archive_md5=args.aavc_archive_md5,
        aavc_source_snapshot=args.aavc_source_snapshot,
        raptor_source_snapshot=args.raptor_source_snapshot,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
