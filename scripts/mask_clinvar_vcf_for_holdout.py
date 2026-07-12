#!/usr/bin/env python3
"""Stream-mask a ClinVar VCF using the label-free held-out identity manifest."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from raptor.eval.mask_clinvar import load_holdout_identities
from raptor.eval.mask_vcf import VcfMaskError, mask_tsc_holdout_from_vcf
from raptor.ingest.config import load_config
from raptor.ingest.model import NormalizedVariant, RawVariant
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer


class _ManifestIdentityNormalizer:
    """Validate that every manifest identity is canonical and TSC-scoped."""

    _accessions = frozenset({"NC_000009.12", "NC_000016.10"})

    def normalize(self, record: object) -> str:
        if not isinstance(record, dict):
            raise ValueError("manifest identity must be an object")
        identity = str(record.get("variant_id", ""))
        parts = identity.split(":")
        if len(parts) != 4 or parts[0] not in self._accessions:
            raise ValueError("manifest identity is not a pinned TSC GRCh38 SPDI")
        if not parts[1].isdigit() or int(parts[1]) < 0:
            raise ValueError("manifest identity has an invalid SPDI position")
        if any(base not in "ACGT" for allele in parts[2:] for base in allele):
            raise ValueError("manifest identity has a non-literal SPDI allele")
        if not parts[2] and not parts[3]:
            raise ValueError("manifest identity has empty deleted and inserted alleles")
        return identity


class _CoordinateCanonicalizer:
    def __init__(self, reference_root: Path, ingest_config_path: Path):
        self._config = load_config(ingest_config_path)
        self._normalizer = SeqRepoGenomicNormalizer(reference_root)

    def __call__(self, accession: str, position: int, ref: str, alt: str) -> str:
        raw = RawVariant(
            variation_id="",
            chromosome=accession,
            position=position,
            ref=ref,
            alt=alt,
            gene="",
            raw_source_value=f"{accession}:{position}:{ref}:{alt}",
            snapshot_id="clinvar-2026-02-26",
            snapshot_date="2026-02-26",
            source_file_checksum="",
            row_locator="",
        )
        outcome = self._normalizer.normalize(raw, self._config)
        if not isinstance(outcome, NormalizedVariant):
            raise VcfMaskError(
                f"failed to canonicalize {raw.raw_source_value}: "
                f"{outcome.error_code}: {outcome.reason}"
            )
        return outcome.variant_id


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-vcf", type=Path, required=True)
    parser.add_argument("--output-vcf", type=Path, required=True)
    parser.add_argument("--holdout-manifest", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument(
        "--ingest-config",
        type=Path,
        default=ROOT / "configs" / "ingest" / "tsc.yaml",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    holdout_ids = load_holdout_identities(
        args.holdout_manifest,
        _ManifestIdentityNormalizer(),
    )
    canonicalize = _CoordinateCanonicalizer(args.reference_root, args.ingest_config)
    ledger = mask_tsc_holdout_from_vcf(
        args.source_vcf,
        args.output_vcf,
        holdout_ids,
        canonicalize,
    )
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write(args.ledger)
    print(
        f"Masked {ledger.matched_records_removed} VCF rows representing "
        f"{len(ledger.matched_holdout_identities)} held-out identities; "
        f"{len(ledger.holdout_identities_not_present)} identities were absent."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
