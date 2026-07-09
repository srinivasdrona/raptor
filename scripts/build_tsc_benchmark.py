"""Freeze the TSC1/TSC2 known-variant benchmark from a pinned ClinVar snapshot (Track A2).

Pipeline (all deterministic, provenanced -- R-A11):
  1. verify the pinned RAW snapshot sha256 (fail loud on mismatch);
  2. pre-filter to GRCh38 + TSC1/TSC2 rows (the raw file carries BOTH GRCh37 and
     GRCh38 -- scoring both would double-count identities and crash the GRCh38-only
     normalizer on GRCh37 accessions);
  3. run the real PRD-07 loader (`load_known_labels`) with the real genomic-SPDI
     normalizer (identity join key) + PRD-07 label/class/review mapping;
  4. `build_benchmark` (exclusions + label hierarchy) -> `split_benchmark`;
  5. write the frozen benchmark + train/held-out split + a stratified stats report.

Usage:
  python scripts/build_tsc_benchmark.py \
      --snapshot /path/to/variant_summary.txt.gz \
      --out /path/to/out-dir
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from raptor.eval.config import load_config as load_eval_config
from raptor.eval.knowns import load_known_labels
from raptor.eval.benchmark import build_benchmark
from raptor.eval.split import split_benchmark
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.contract import VariantSummaryContract
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer

# --- pinned snapshot provenance (R-A11) ------------------------------------
SNAPSHOT_ID = "clinvar_2026-07-07"
SNAPSHOT_DATE = "2026-07-07"
SNAPSHOT_SHA256 = "5fe4fe10783391d01dc414dc5583a3e63487b67f8cd3c8429d59227cd5f4f37f"
SNAPSHOT_MD5 = "bd3720834b62733a6a1c81d7e1eef941"

_ASSEMBLY = "GRCh38"
_TARGET = {"TSC1", "TSC2"}
_PATHOGENIC = {"P", "LP"}
_BENIGN = {"B", "LB"}


class _RefConfigNormalizer:
    """Adapter: the PRD-07 reader calls ``normalize(raw, eval_config)``, but the
    genomic normalizer needs the INGEST config for reference-FASTA checksums --
    inject it here so R-A11 reference verification actually runs."""

    def __init__(self, inner, ingest_config):
        self._inner = inner
        self._ingest_config = ingest_config

    def normalize(self, raw, config):
        return self._inner.normalize(raw, self._ingest_config)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gene_match(field: str) -> bool:
    for g in _TARGET:
        if field == g:
            return True
        if ":" in field and g in [t.strip() for t in field.split(":")]:
            return True
    return False


def _prefilter_grch38_tsc(snapshot: Path, out: Path) -> tuple[int, int]:
    """Stream the raw snapshot -> a small gz of GRCh38 TSC1/TSC2 rows, preserving
    the exact header (so the loader's column contract still holds)."""
    total = kept = 0
    with gzip.open(snapshot, "rt", encoding="utf-8", newline="") as fin, \
            gzip.open(out, "wt", encoding="utf-8", newline="") as fout:
        reader = csv.reader(fin, delimiter="\t")
        header = next(reader)
        VariantSummaryContract.assert_columns(header)
        idx = {n: i for i, n in enumerate(header)}
        writer = csv.writer(fout, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        ai, gi = idx["Assembly"], idx["GeneSymbol"]
        for row in reader:
            total += 1
            if len(row) <= max(ai, gi):
                continue
            if row[ai] == _ASSEMBLY and _gene_match(row[gi]):
                writer.writerow(row)
                kept += 1
    return total, kept


def _strata(rows) -> Counter:
    c: Counter = Counter()
    for r in rows:
        direction = "pathogenic" if r.label in _PATHOGENIC else ("benign" if r.label in _BENIGN else "other")
        c[(r.variant_class, direction, r.label)] += 1
    return c


def _direction_totals(rows) -> dict:
    path = sum(1 for r in rows if r.label in _PATHOGENIC)
    benign = sum(1 for r in rows if r.label in _BENIGN)
    return {"pathogenic": path, "benign": benign, "total": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--eval-config", default="configs/eval/tsc2.yaml")
    ap.add_argument("--ingest-config", default="configs/ingest/tsc.yaml")
    ap.add_argument("--skip-verify", action="store_true", help="skip the raw-snapshot sha256 pin check")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] verifying pinned snapshot sha256 ({SNAPSHOT_ID}) ...")
    if not args.skip_verify:
        actual = _sha256(args.snapshot)
        if actual.lower() != SNAPSHOT_SHA256:
            raise SystemExit(f"snapshot sha256 mismatch: {actual} != pinned {SNAPSHOT_SHA256}")
        print("      OK -- matches pin")

    filtered = args.out / "variant_summary_tsc_grch38.txt.gz"
    print(f"[2/5] pre-filtering to {_ASSEMBLY} + TSC1/TSC2 -> {filtered.name} ...")
    total, kept = _prefilter_grch38_tsc(args.snapshot, filtered)
    print(f"      {total} rows scanned; {kept} GRCh38 TSC rows kept")

    eval_config = load_eval_config(args.eval_config)
    ingest_config = load_ingest_config(args.ingest_config)
    normalizer = _RefConfigNormalizer(SeqRepoGenomicNormalizer(), ingest_config)

    print("[3/5] loading known labels (real genomic-SPDI normalizer) ...")
    from raptor.eval.knowns import LabeledVariantReader
    reader = LabeledVariantReader(filtered, eval_config, normalizer,
                                  snapshot_id=SNAPSHOT_ID, snapshot_date=SNAPSHOT_DATE)
    labels = list(reader)
    skipped = list(reader.skipped)
    print(f"      {len(labels)} labels emitted; {len(skipped)} rows skipped (imprecise/non-ACGT)")

    print("[4/5] build_benchmark (exclusions + label hierarchy) + split ...")
    benchmark = build_benchmark(labels, eval_config)
    train_dev, holdout = split_benchmark(benchmark, eval_config)

    # --- write artifacts ---------------------------------------------------
    def _dump(name, rows):
        p = args.out / name
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(asdict(r), sort_keys=True) + "\n")
        return p

    _dump("benchmark.jsonl", benchmark)
    _dump("train_dev.jsonl", train_dev)
    _dump("holdout.jsonl", holdout)

    report = {
        "snapshot": {"id": SNAPSHOT_ID, "date": SNAPSHOT_DATE, "sha256": SNAPSHOT_SHA256, "md5": SNAPSHOT_MD5},
        "raw_rows_scanned": total,
        "grch38_tsc_rows": kept,
        "labels_emitted": len(labels),
        "rows_skipped_unnormalizable": len(skipped),
        "benchmark_size": len(benchmark),
        "train_dev_size": len(train_dev),
        "holdout_size": len(holdout),
        "benchmark_by_direction": _direction_totals(benchmark),
        "holdout_by_direction": _direction_totals(holdout),
        "holdout_by_class_direction": {
            f"{cls}|{d}|{lab}": n for (cls, d, lab), n in sorted(_strata(holdout).items())
        },
        "benchmark_by_class_direction": {
            f"{cls}|{d}|{lab}": n for (cls, d, lab), n in sorted(_strata(benchmark).items())
        },
        "holdout_missense": _direction_totals([r for r in holdout if r.variant_class == "missense"]),
        "holdout_truncating": _direction_totals([r for r in holdout if r.variant_class == "truncating"]),
    }
    (args.out / "benchmark_stats.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("[5/5] done. Key numbers:")
    print(json.dumps({k: report[k] for k in (
        "benchmark_size", "holdout_size", "holdout_missense", "holdout_truncating", "holdout_by_direction",
    )}, indent=2))


if __name__ == "__main__":
    main()
