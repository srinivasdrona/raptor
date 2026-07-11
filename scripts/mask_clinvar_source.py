#!/usr/bin/env python3
"""masked-resources slot 2 sec 1.1 CLI — mask the upstream ClinVar source
(VCF + Nirvana JSON annotation + `variant_summary`/`submission_summary`
tables) so BIAS-3.0.0's own `generate_*.py` (arm's-length, x64 devbox,
ADR-0007/0008) can rebuild the five transitive comparator resources
(`PS1, PM5, PM1, PP2, BP1`) and the three direct-copy fallback inputs
(`PS4, PP5, BP6`) with the frozen held-out identities removed.

Reads ONLY `row["variant_id"]` from the held-out JSONL (never `label`/
`source`/`review_status`/`variant_class`); the benchmark snapshot id comes
from the explicit `--benchmark-snapshot` CLI arg, never from a labelled
row. Every ClinVar reader below extracts identity columns only (VariationID
+ coordinate) -- never `ClinicalSignificance`/`ReviewStatus` text.

Usage (mask mode)::

    python scripts/mask_clinvar_source.py \\
        --heldout HELDOUT.jsonl \\
        --clinvar-vcf CLINVAR.vcf \\
        --clinvar-nirvana-json NIRVANA.jsonl \\
        --variant-summary variant_summary.txt \\
        --submission-summary submission_summary.txt \\
        --out-dir OUT_DIR \\
        --benchmark-snapshot clinvar_2026-07-07 \\
        [--mask-config configs/eval/mask.yaml] \\
        [--ingest-config configs/ingest/tsc.yaml]

Usage (audit mode, run AFTER the operator's arm's-length BIAS-generator
rebuild on the masked inputs the mask-mode run above produced)::

    python scripts/mask_clinvar_source.py --audit MASKED_RESOURCE_DIR \\
        --out-dir OUT_DIR [--mask-config ...] [--ingest-config ...]

`MASKED_RESOURCE_DIR` must contain an `audit_input.json` with
`{"heldout_jsonl": PATH, "clinvar_records": {stream: [record, ...]},
"comparators": {criterion: resource}}` -- the canonical JSON contract this
CLI's audit mode consumes (translating BIAS's own rebuilt resource files
into this shape is a separate, arm's-length adapter step, out of scope
here -- ADR-0007/0008 defer the actual rebuild). Exits non-zero iff the
resulting conservation report is not clean.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any
import re

from raptor.eval.mask_clinvar import (
    MaskAmbiguityError,
    audit_mask_conservation,
    load_holdout_identities,
    load_mask_config,
    mask_clinvar_source,
)
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.contract import VariantSummaryContract
from raptor.ingest.model import ManualQueueItem, NormalizedVariant, RawVariant
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer
from raptor.ingest.reader import _open_text, _parse_position

#: Pinned code-version tag for the provenance sidecar (R-A11) -- repin when
#: this script's read/mask logic changes.
CODE_VERSION = "raptor.eval.mask_clinvar/1"
#: Arm's-length BIAS source pin (masked-resources README source-hash
#: registry) -- a citation only, never an import.
BIAS_SOURCE_COMMIT = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"

#: The one column `submission_summary.txt` rows are keyed by for this
#: tool's purposes -- its own-variant VariationID identity. The full
#: submission_summary column schema is BIAS-internal and out of scope;
#: this is a deliberately minimal contract (fail loud if even this much is
#: absent), never a guess at unread columns.
_SUBMISSION_SUMMARY_REQUIRED_COLUMN = "VariationID"


class ClinVarIdentityNormalizer:
    """The concrete `mask_clinvar.Normalizer` this CLI injects: dispatches
    on the shape of the record handed to it by `mask_clinvar_source`/
    `load_holdout_identities`/`audit_mask_conservation` --

      * `{"variant_id": <already-canonical SPDI string>}` -- the held-out
        identity shape (already GRCh38 SPDI, per the frozen benchmark
        contract); validated + passed through, never re-derived via the
        reference (there is no raw coordinate to re-derive it from).
      * a raw ClinVar VCF/Nirvana coordinate record (`chromosome`/
        `position`/`ref`/`alt`, + optional `VariationID`/`gene`) --
        normalized via the real, checksum-verified
        `SeqRepoGenomicNormalizer` (R-A10/R-A11), never a hand-rolled
        coordinate parser.
      * `{"VariationID": ...}` with no coordinate fields (a
        `submission_summary` row) -- resolved via the `variant_summary`-
        derived VariationID->SPDI map (the SAME upstream ClinVar file
        every BIAS generator reads for this identity), never guessed.

    Any other shape, or a lookup miss, raises `ValueError` -- wrapped by
    `mask_clinvar`'s public functions into the typed
    `MaskReferenceError`/`HoldoutIdentityError`.
    """

    def __init__(
        self,
        genomic_normalizer: SeqRepoGenomicNormalizer,
        ingest_config: Any,
        variation_id_to_spdi: dict[str, str],
    ):
        self._genomic_normalizer = genomic_normalizer
        self._ingest_config = ingest_config
        self._variation_id_to_spdi = variation_id_to_spdi

    def normalize(self, record: Any) -> str:
        if isinstance(record, dict) and "chromosome" in record and "position" in record:
            return self._normalize_coordinate(record)
        if isinstance(record, dict) and "VariationID" in record and "chromosome" not in record:
            return self._resolve_variation_id(str(record["VariationID"]))
        if isinstance(record, dict) and set(record.keys()) == {"variant_id"}:
            return self._validate_canonical(str(record["variant_id"]))
        raise ValueError(f"unrecognized ClinVar record shape for identity normalization: {record!r}")

    def _normalize_coordinate(self, record: dict[str, Any]) -> str:
        raw = RawVariant(
            chromosome=str(record["chromosome"]),
            position=record["position"],
            ref=str(record.get("ref", "")),
            alt=str(record.get("alt", "")),
            gene=str(record.get("gene", "")),
            variation_id=str(record.get("VariationID", "")),
            snapshot_id="",
            snapshot_date="",
            source_file_checksum="",
            row_locator=str(record.get("row_locator", "")),
            raw_source_value=(
                f"{record['chromosome']}\t{record['position']}\t"
                f"{record.get('ref', '')}\t{record.get('alt', '')}"
            ),
        )
        outcome = self._genomic_normalizer.normalize(raw, self._ingest_config)
        if isinstance(outcome, NormalizedVariant):
            return outcome.variant_id
        reason = outcome.reason if isinstance(outcome, ManualQueueItem) else "unknown normalization failure"
        raise ValueError(f"could not normalize ClinVar coordinate record to canonical SPDI: {record!r} ({reason})")

    def _resolve_variation_id(self, variation_id: str) -> str:
        spdi = self._variation_id_to_spdi.get(variation_id)
        if spdi is None:
            raise ValueError(
                f"VariationID {variation_id!r} has no known canonical SPDI mapping from the "
                "variant_summary identity map"
            )
        return spdi

    @staticmethod
    def _validate_canonical(variant_id: str) -> str:
        match = re.fullmatch(
            r"(NC_000009\.12|NC_000016\.10):([0-9]+):([ACGTN]*):([ACGTN]*)",
            variant_id,
        )
        if match is None or (not match.group(3) and not match.group(4)):
            raise ValueError(
                f"variant_id {variant_id!r} is not a pinned GRCh38 canonical SPDI"
            )
        return variant_id


def _read_clinvar_vcf(path: Path) -> list[dict[str, Any]]:
    """Minimal VCF 4.x reader: `CHROM`/`POS`/`REF`/`ALT` + optional INFO
    `CLNVID`/`GENEINFO`. Multi-allelic `ALT` is split into one record per
    allele (each normalized independently, R-A10-style -- never merged).
    No `CLNSIG`/label INFO key is ever extracted here."""
    records: list[dict[str, Any]] = []
    with _open_text(path) as f:
        for line in f:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                raise ValueError(f"malformed VCF data row in {path}: {line!r}")
            chrom, pos, _vcf_id, ref, alt_field = fields[0], fields[1], fields[2], fields[3], fields[4]
            info = fields[7] if len(fields) > 7 else ""
            info_map = dict(
                item.split("=", 1) if "=" in item else (item, "") for item in info.split(";") if item
            )
            variation_id = info_map.get("CLNVID", "")
            gene_info = info_map.get("GENEINFO", "")
            gene = gene_info.split(":")[0] if gene_info else ""
            for alt in alt_field.split(","):
                records.append(
                    {
                        "chromosome": chrom,
                        "position": int(pos),
                        "ref": ref,
                        "alt": alt,
                        "VariationID": variation_id,
                        "gene": gene,
                    }
                )
    return records


def _read_nirvana_json(path: Path) -> list[dict[str, Any]]:
    """Minimal Nirvana-annotation-shaped JSON-lines reader: each line is a
    JSON object with `chromosome`/`position`/`refAllele`/`altAllele` (+
    optional `variationId`) -- exactly the identity fields PS1/PM5/PP5/BP6
    masking needs. Any other shape fails loud (never guessed); ClinVar
    significance/review-status text is never read here."""
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            required = ("chromosome", "position", "refAllele", "altAllele")
            missing = [key for key in required if key not in row]
            if missing:
                raise ValueError(f"nirvana json row {line_no} in {path} missing required field(s) {missing!r}")
            records.append(
                {
                    "chromosome": str(row["chromosome"]),
                    "position": row["position"],
                    "ref": str(row["refAllele"]),
                    "alt": str(row["altAllele"]),
                    "VariationID": str(row.get("variationId", "")),
                }
            )
    return records


def _read_variant_summary(path: Path) -> list[dict[str, Any]]:
    """Every row of a ClinVar `variant_summary.txt`(.gz) snapshot (the
    pinned `VariantSummaryContract` column contract) -- deliberately NOT
    gene-filtered (masking must remove a held-out row regardless of gene).
    Reads only identity columns (`VariationID`, `ChromosomeAccession`,
    `PositionVCF`, `Reference/AlternateAlleleVCF`, `GeneSymbol`) -- never
    `ClinicalSignificance`/`ReviewStatus`."""
    records: list[dict[str, Any]] = []
    with _open_text(path) as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        VariantSummaryContract.assert_columns(header)
        idx = {name: i for i, name in enumerate(header)}
        for row in reader:
            if not row:
                continue
            records.append(
                {
                    "VariationID": row[idx["VariationID"]],
                    "chromosome": row[idx["ChromosomeAccession"]],
                    "position": _parse_position(row[idx["PositionVCF"]]),
                    "ref": row[idx["ReferenceAlleleVCF"]],
                    "alt": row[idx["AlternateAlleleVCF"]],
                    "gene": row[idx["GeneSymbol"]],
                }
            )
    return records


def _read_submission_summary(path: Path) -> list[dict[str, Any]]:
    """A `submission_summary.txt`(.gz) row carries no VCF coordinate of its
    own -- only the minimal identity contract this tool needs
    (`VariationID`) is read; identity is resolved via the
    `variant_summary`-derived VariationID->SPDI map, never guessed."""
    records: list[dict[str, Any]] = []
    with _open_text(path) as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        if _SUBMISSION_SUMMARY_REQUIRED_COLUMN not in header:
            raise ValueError(
                "submission_summary column contract violated -- missing required column "
                f"{_SUBMISSION_SUMMARY_REQUIRED_COLUMN!r} (got header: {header!r})"
            )
        idx = header.index(_SUBMISSION_SUMMARY_REQUIRED_COLUMN)
        for row in reader:
            if not row:
                continue
            records.append({"VariationID": row[idx]})
    return records


def _build_variation_id_to_spdi(
    variant_summary_records: list[dict[str, Any]],
    genomic_normalizer: SeqRepoGenomicNormalizer,
    ingest_config: Any,
) -> dict[str, str]:
    """Resolve every `variant_summary` row's own coordinate to canonical
    SPDI up front -- used only to resolve `submission_summary`'s
    coordinate-less `VariationID` rows (slot 2 sec 1: "resolves its
    VariationID->SPDI via the provided ClinVar identity map")."""
    mapping: dict[str, str] = {}
    for record in variant_summary_records:
        variation_id = record.get("VariationID")
        if not variation_id:
            continue
        raw = RawVariant(
            chromosome=str(record["chromosome"]),
            position=record["position"],
            ref=str(record["ref"]),
            alt=str(record["alt"]),
            gene=str(record.get("gene", "")),
            variation_id=str(variation_id),
            snapshot_id="",
            snapshot_date="",
            source_file_checksum="",
            row_locator="",
            raw_source_value=f"{record['chromosome']}\t{record['position']}\t{record['ref']}\t{record['alt']}",
        )
        outcome = genomic_normalizer.normalize(raw, ingest_config)
        if isinstance(outcome, NormalizedVariant):
            mapping[str(variation_id)] = outcome.variant_id
    return mapping


def _parse_args(argv: list[str] | None) -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--heldout", help="frozen held-out JSONL (label-bearing; only variant_id is read)")
    parser.add_argument("--clinvar-vcf", help="ClinVar VCF (source for PS1/PM5/PM1/PP2/BP1)")
    parser.add_argument("--clinvar-nirvana-json", help="ClinVar Nirvana JSON annotation (PS1/PM5/PP5/BP6)")
    parser.add_argument("--variant-summary", help="ClinVar variant_summary.txt(.gz) (PS4)")
    parser.add_argument("--submission-summary", help="ClinVar submission_summary.txt(.gz) (PS4)")
    parser.add_argument("--out-dir", required=True, help="output directory")
    parser.add_argument("--benchmark-snapshot", help="benchmark snapshot id, explicit CLI arg (never from a labeled row)")
    parser.add_argument("--mask-config", default="configs/eval/mask.yaml")
    parser.add_argument("--ingest-config", default="configs/ingest/tsc.yaml")
    parser.add_argument(
        "--audit",
        default=None,
        help="path to a masked_resource_dir (containing audit_input.json) to audit instead of masking",
    )
    return parser, parser.parse_args(argv)


def _run_mask_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    required = {
        "--heldout": args.heldout,
        "--clinvar-vcf": args.clinvar_vcf,
        "--clinvar-nirvana-json": args.clinvar_nirvana_json,
        "--variant-summary": args.variant_summary,
        "--submission-summary": args.submission_summary,
        "--benchmark-snapshot": args.benchmark_snapshot,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"mask mode requires {missing!r} (or use --audit for audit mode)")

    ingest_config = load_ingest_config(args.ingest_config)
    mask_config = load_mask_config(args.mask_config, ingest_config)

    genomic_normalizer = SeqRepoGenomicNormalizer()

    variant_summary_records = _read_variant_summary(Path(args.variant_summary))
    variation_id_to_spdi = _build_variation_id_to_spdi(variant_summary_records, genomic_normalizer, ingest_config)

    clinvar_records: dict[str, list[dict[str, Any]]] = {
        "clinvar_vcf": _read_clinvar_vcf(Path(args.clinvar_vcf)),
        "clinvar_nirvana_json": _read_nirvana_json(Path(args.clinvar_nirvana_json)),
        "variant_summary": variant_summary_records,
        "submission_summary": _read_submission_summary(Path(args.submission_summary)),
    }

    normalizer = ClinVarIdentityNormalizer(genomic_normalizer, ingest_config, variation_id_to_spdi)
    holdout_ids = load_holdout_identities(Path(args.heldout), normalizer)

    result = mask_clinvar_source(clinvar_records, holdout_ids, normalizer, mask_config)

    # Fail-loud consistency re-check (defense in depth -- `MaskLedger` holds
    # this invariant by construction already): a stream whose ledger
    # disagrees with itself must never be silently written.
    for stream, ledger in result.ledger.items():
        if ledger.remaining != ledger.input_total - ledger.matched_removed:
            print(f"FATAL: stream {stream!r} ledger is inconsistent: {ledger.to_dict()!r}", file=sys.stderr)
            return 1

    result.provenance.update(
        {
            "bias_source_commit": BIAS_SOURCE_COMMIT,
            "bias_version": mask_config.bias_version,
            "benchmark_snapshot": args.benchmark_snapshot,
            "code_version": CODE_VERSION,
            "heldout_identity_count": len(holdout_ids),
        }
    )
    result.write(args.out_dir)

    summary = {
        "content_hash": result.content_hash(),
        "ledger": {stream: ledger.to_dict() for stream, ledger in result.ledger.items()},
    }
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


def _run_audit_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    audit_path = Path(args.audit)
    audit_input_path = audit_path / "audit_input.json" if audit_path.is_dir() else audit_path
    if not audit_input_path.is_file():
        parser.error(f"--audit path has no audit_input.json: {audit_input_path}")
    masked_resources = json.loads(audit_input_path.read_text(encoding="utf-8"))

    ingest_config = load_ingest_config(args.ingest_config)
    mask_config = load_mask_config(args.mask_config, ingest_config)

    genomic_normalizer = SeqRepoGenomicNormalizer()
    variant_summary_records = masked_resources.get("clinvar_records", {}).get("variant_summary", [])
    variation_id_to_spdi = _build_variation_id_to_spdi(variant_summary_records, genomic_normalizer, ingest_config)
    mask_manifest_path = masked_resources.get("mask_manifest_jsonl")
    if mask_manifest_path:
        for line_number, line in enumerate(
            Path(mask_manifest_path).read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            variation_id = str(row.get("clinvar_variation_id") or "")
            variant_id = str(row.get("variant_id") or "")
            if variation_id and variant_id:
                prior = variation_id_to_spdi.get(variation_id)
                if prior is not None and prior != variant_id:
                    raise MaskAmbiguityError(
                        f"mask manifest line {line_number} maps VariationID {variation_id!r} "
                        f"to conflicting identities {prior!r}/{variant_id!r}"
                    )
                variation_id_to_spdi[variation_id] = variant_id
    normalizer = ClinVarIdentityNormalizer(genomic_normalizer, ingest_config, variation_id_to_spdi)

    heldout_path = masked_resources.get("heldout_jsonl")
    if not heldout_path:
        parser.error("audit_input.json must carry `heldout_jsonl` (path to the frozen held-out JSONL)")
    holdout_ids = load_holdout_identities(Path(heldout_path), normalizer)

    report = audit_mask_conservation(masked_resources, holdout_ids, normalizer, mask_config)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_json = json.dumps(report.to_dict(), sort_keys=True, indent=2)
    (out_dir / "mask_conservation_report.json").write_text(report_json + "\n", encoding="utf-8")
    print(report_json)

    return 0 if report.clean else 1


def main(argv: list[str] | None = None) -> int:
    parser, args = _parse_args(argv)
    if args.audit:
        return _run_audit_mode(parser, args)
    return _run_mask_mode(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
