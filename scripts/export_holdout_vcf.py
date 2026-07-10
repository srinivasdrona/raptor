#!/usr/bin/env python3
"""PRD-08 sec 10.3 CLI — export the frozen held-out JSONL to a deterministic
label-free GRCh38 VCF 4.2 + bijective identity manifest + provenance sidecar
(Task A). Supersedes `scripts/devbox/make_sample_vcf.py` (which leaks
`variant_class` into VCF `INFO=CLASS=...` -- structurally forbidden here,
FR-A4).

Reads ONLY `row["variant_id"]` from the held-out JSONL -- every other field
(`label`, `source`, `review_status`, `variant_class`, ...) is present in the
frozen file but never accessed (FR-A1, the label-free boundary). The
benchmark snapshot id is taken explicitly from `--benchmark-snapshot`, never
from a label-bearing row.

Reference discipline reuses `raptor.ingest.normalizer.SeqRepoGenomicNormalizer`
(checksum-verified FASTA access, R-A11/FR-A3) via a thin adapter exposing the
`ReferencePort.fetch(accession, start, end)` port `export.py` expects.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from raptor.eval.export import export_holdout, load_export_config
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer

#: Pinned code-version tag for the provenance sidecar (R-A11) -- repin when
#: this script's export logic changes.
CODE_VERSION = "raptor.eval.export/1"


class _NormalizerReference:
    """Adapts `SeqRepoGenomicNormalizer`'s checksum-verified FASTA access
    (`{reference_root}/{accession}.fasta`) to the `ReferencePort.fetch`
    port `export.spdi_to_vcf`/`export_holdout` expect -- reusing the same
    reference-read + checksum-verify discipline as ingestion (FR-A3),
    never a re-implemented FASTA reader."""

    def __init__(self, normalizer: SeqRepoGenomicNormalizer, ingest_config):
        self._normalizer = normalizer
        self._ingest_config = ingest_config

    def fetch(self, accession: str, start: int, end: int) -> str:
        fasta = self._normalizer._fasta_for(accession, self._ingest_config)
        if start >= end:
            return ""
        return fasta.fetch(accession, start, end)


def _read_variant_ids(heldout_path: Path) -> list[str]:
    """FR-A1: read ONLY `row["variant_id"]` -- every other key in the
    frozen held-out row (`label`, `source`, `review_status`,
    `variant_class`, ...) is never accessed."""
    variant_ids: list[str] = []
    with open(heldout_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            variant_ids.append(row["variant_id"])
    return variant_ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--heldout", required=True, type=Path, help="frozen held-out JSONL (label-bearing; only variant_id is read)")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--prefix", default="holdout_input")
    ap.add_argument("--benchmark-snapshot", required=True, help="benchmark snapshot id, explicit CLI arg (never from a labeled row)")
    ap.add_argument("--export-config", default="configs/eval/export.yaml", type=Path)
    ap.add_argument("--ingest-config", default="configs/ingest/tsc.yaml", type=Path)
    ap.add_argument("--reference-root", default=None, help="reference FASTA root (defaults to RAPTOR_SEQREPO_ROOT env / ~/raptor-refseq)")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    ingest_config = load_ingest_config(args.ingest_config)
    export_config = load_export_config(args.export_config, ingest_config)

    normalizer = SeqRepoGenomicNormalizer(reference_root=args.reference_root)
    reference = _NormalizerReference(normalizer, ingest_config)

    variant_ids = _read_variant_ids(args.heldout)

    provenance = {
        "benchmark_snapshot": args.benchmark_snapshot,
        "reference_checksums": dict(ingest_config.reference_checksums),
        "code_version": CODE_VERSION,
    }

    result = export_holdout(variant_ids, reference, export_config, provenance=provenance)
    result.write(args.out_dir, prefix=args.prefix)

    summary = {
        "conservation_count": result.conservation_count,
        "vcf_hash": result.vcf_hash,
        "manifest_hash": result.manifest_hash,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
