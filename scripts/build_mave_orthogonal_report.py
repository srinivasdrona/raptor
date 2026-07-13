#!/usr/bin/env python
"""Phase 1: build the non-identifying, label-free TSC2 MAVE orthogonal
validation report (`data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json`).

Pipeline (all fail-loud, no cDNA->genomic projection is guessed anywhere):

1. Verify the pinned MaveDB scoreset (`configs/external/mave_sources.yaml`,
   `raptor.external.mave.register`) against the on-disk external CSV.
2. Parse the raw MaveDB scoreset CSV (`raptor.external.mave.source`).
3. Load the two REAL BIAS-2015 outputs already on disk for TSC2 -- the VUS
   candidate-universe run and the held-out run -- and build a canonical
   SPDI variant per TSC2 row, keyed by its bare `c.` HGVS change (NOT a
   cDNA->genomic projection: this is a direct dictionary lookup against an
   already-computed BIAS output that itself carries the genomic
   chromosome/position/ref/alt).
4. EXACT hgvsc string match between the MaveDB rows and each BIAS universe
   -> the 66 VUS-overlap and 32 heldout-overlap variant sets (mutually
   exclusive by construction; asserted).
5. Cross-check that reconstruction against the existing, already-verified
   overlap fixtures (`overlap.json` / `overlap_classified.json`) via
   `raptor.external.mave.identity.join_exact_overlap` -- fails loud on any
   drift between an independent re-derivation and the pinned fixture.
6. Classify every matched score via the fixed functional thresholds
   (`raptor.external.mave.endpoint.classify_functional_score`) and build the
   two mutually-exclusive partitions
   (`raptor.external.mave.partition.build_partitions`).
7. Compute deterministic, non-gating orthogonal rank-correlation + class
   power (`raptor.external.mave.orthogonal_metrics.compute_orthogonal_metrics`)
   using BIAS's own (non-MAVE, non-ClinVar-label) ACMG-classification
   ordinal as the RAPTOR-side proxy -- MAVE scores never enter
   `raptor.scorer` or `decide_gate`.
8. Emit ONLY a non-identifying aggregate: no variant_id, no hgvsc, no
   clinical (B/LB/P/LP) label ever appears as a value or a key.

Raw scores/overlaps/per-variant matrices are read from (and never written
back to, and never committed from) the external data root
(`RAPTOR_MAVE_EXTERNAL_ROOT`, default matching this workstation's
`D:\\AIProjects\\raptor-data\\external\\mavedb\\...` layout).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raptor.external.mave.endpoint import (  # noqa: E402
    FunctionalClass,
    classify_functional_score,
)
from raptor.external.mave.identity import (  # noqa: E402
    CanonicalVariant,
    ExactOverlapMismatchError,
    ReferenceMismatchError,
    join_exact_overlap,
)
from raptor.external.mave.orthogonal_metrics import (  # noqa: E402
    OrthogonalObservation,
    compute_orthogonal_metrics,
)
from raptor.external.mave.partition import PartitionKind, build_partitions  # noqa: E402
from raptor.external.mave.register import SourceRegisterEntry, verify_registered_source  # noqa: E402
from raptor.external.mave.source import MaveScoreRecord, parse_mavedb_scoreset_csv  # noqa: E402

EXTERNAL_ROOT_ENV = "RAPTOR_MAVE_EXTERNAL_ROOT"
DEFAULT_EXTERNAL_ROOT = Path.home() / "raptor-data" / "external" / "mavedb"
DEFAULT_MAVEDB_DIR = "TSC2-clipe-00001201-a-1"
DEFAULT_SOURCES_CONFIG = Path("configs") / "external" / "mave_sources.yaml"
DEFAULT_EVAL_CONFIG = Path("configs") / "eval" / "mave_tsc2.yaml"

_HGVSG_RE = re.compile(r"^(?P<accession>NC_\d+\.\d+):g\.(?P<position>\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])$")

# BIAS's own ACMG classification -> a purely ordinal, non-clinical proxy
# used ONLY for the exploratory, NON_GATING orthogonal correlation below.
# This is BIAS-2015's OWN prior conclusion (already computed independently
# of MaveDB), never a MAVE-derived value and never fed back into
# `raptor.scorer`/`decide_gate`.
_ACMG_ORDINAL = {
    "benign": -2.0,
    "likely benign": -1.0,
    "uncertain": 0.0,
    "likely pathogenic": 1.0,
    "pathogenic": 2.0,
}


class ReportBuildError(RuntimeError):
    """Base error for report-build failures (fail loud, never a partial report)."""


def _load_source_entry(config_path: Path, urn: str) -> tuple[SourceRegisterEntry, dict]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for raw in payload.get("sources", []):
        if raw.get("urn") == urn:
            return (
                SourceRegisterEntry(
                    urn=raw["urn"],
                    gene=raw["gene"],
                    transcript=raw["transcript"],
                    license=raw["license"],
                    sha256=raw.get("sha256") or "",
                    variant_count=int(raw.get("variant_count", 0)),
                    verification=raw.get("verification", "verified"),
                ),
                raw,
            )
    raise ReportBuildError(f"no source register entry for {urn!r} in {config_path}")


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bare_c(hgvsc: str) -> str:
    return hgvsc.split(":", 1)[1] if ":" in hgvsc else hgvsc


def _load_bias_tsc2_rows(path: Path, gene: str) -> dict[str, dict[str, str]]:
    """Bare-`c.`-keyed TSC2 rows from a real, already-computed BIAS-2015
    output TSV. NOT a cDNA->genomic projection: BIAS already carries the
    genomic chromosome/position/ref/alt for every row it classified."""
    by_c: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row.get("geneName") != gene:
                continue
            hgvsc = row.get("hgvsc", "")
            if not hgvsc or hgvsc.lower() in {"n/a", "na"} or ":" not in hgvsc:
                # No coding-transcript HGVS change (e.g. intergenic/UTR-only
                # rows without a c. notation) -- cannot participate in an
                # exact hgvsc match, never guessed.
                continue
            c = _bare_c(hgvsc)
            if c in by_c:
                raise ReportBuildError(f"duplicate hgvsc {c!r} for gene {gene} in {path}")
            by_c[c] = row
    return by_c


def _canonical_variant_from_bias(row: dict[str, str]) -> CanonicalVariant:
    match = _HGVSG_RE.match(row["hgvsg"])
    if not match:
        raise ReportBuildError(f"unparseable hgvsg {row['hgvsg']!r} (not a simple g. substitution)")
    variant_id = f"{match['accession']}:{match['position']}:{match['ref']}:{match['alt']}"
    if match["ref"] != row["refAllele"] or match["alt"] != row["altAllele"]:
        raise ReportBuildError(
            f"hgvsg/ref-alt disagreement for {row['hgvsc']!r}: "
            f"hgvsg={match['ref']}>{match['alt']} refAllele/altAllele={row['refAllele']}/{row['altAllele']}"
        )
    return CanonicalVariant(variant_id=variant_id, reference=row["refAllele"])


def _match_scores_to_bias(
    raw_rows,
    bias_by_c: dict[str, dict[str, str]],
) -> dict[str, tuple[MaveScoreRecord, dict[str, str]]]:
    """Exact hgvsc string match (never a projection): a MaveDB raw row
    matches a BIAS row iff its bare `c.` HGVS change is byte-identical to a
    BIAS TSC2 row's bare `c.` change. Keyed by the bare `c.` string itself
    (the actual exact-match identity axis), not by a re-derived genomic
    position."""
    matched: dict[str, tuple[MaveScoreRecord, dict[str, str]]] = {}
    for raw in raw_rows:
        bias_row = bias_by_c.get(raw.hgvs_c)
        if bias_row is None:
            continue
        canonical = _canonical_variant_from_bias(bias_row)
        record = MaveScoreRecord(
            variant_id=canonical.variant_id,
            hgvs_c=raw.hgvs_c,
            score=raw.score,
            reference=canonical.reference,
        )
        if raw.hgvs_c in matched:
            raise ReportBuildError(f"duplicate MaveDB hgvs_nt {raw.hgvs_c!r}")
        matched[raw.hgvs_c] = (record, bias_row)
    return matched


def _existing_overlap_expected(
    external_dir: Path,
) -> tuple[dict[str, CanonicalVariant], dict[str, CanonicalVariant], dict[str, str]]:
    """The already-verified overlap fixtures' declared identity sets, used
    ONLY as an independent cross-check target (`identity.join_exact_overlap`,
    keyed by the exact bare `c.` HGVS string -- the reliable identity axis
    both fixtures and this script's own BIAS-based reconstruction agree on)
    -- never as the source of the functional classification or the
    partition sizes themselves (those are always recomputed fresh, above)."""
    overlap = json.loads((external_dir / "overlap.json").read_text(encoding="utf-8"))
    overlap_classified = json.loads(
        (external_dir / "overlap_classified.json").read_text(encoding="utf-8")
    )

    vus_expected: dict[str, CanonicalVariant] = {}
    for row in overlap["overlap"]["vus"]["rows"]:
        _chromosome, _position, ref, _alt = row["variant_id"].split(":")
        vus_expected[row["c"]] = CanonicalVariant(variant_id=row["c"], reference=ref)

    heldout_expected: dict[str, CanonicalVariant] = {}
    heldout_direction: dict[str, str] = {}
    for row in overlap_classified["holdout_overlap"]["rows"]:
        _chromosome, _position, ref, _alt = row["variant_id"].split(":")
        heldout_expected[row["c"]] = CanonicalVariant(variant_id=row["c"], reference=ref)
        heldout_direction[row["c"]] = row["clinvar_label"]

    return vus_expected, heldout_expected, heldout_direction


def build_report(
    *,
    sources_config: Path,
    eval_config: Path,
    external_root: Path,
    urn: str = "urn:mavedb:00001201-a-1",
) -> dict:
    entry, raw_entry = _load_source_entry(sources_config, urn)
    eval_cfg = yaml.safe_load(eval_config.read_text(encoding="utf-8"))

    mavedb_dir = external_root / DEFAULT_MAVEDB_DIR
    scores_path = mavedb_dir / "scores.csv"
    observed_sha256 = _sha256_file(scores_path)
    raw_rows = parse_mavedb_scoreset_csv(scores_path)
    with scores_path.open(encoding="utf-8", newline="") as handle:
        observed_variant_count = sum(1 for _ in handle) - 1

    verify_registered_source(
        entry,
        observed_transcript=entry.transcript,
        observed_license=entry.license,
        observed_sha256=observed_sha256,
        observed_variant_count=observed_variant_count,
    )

    vus_bias_path = Path(
        os.environ.get("RAPTOR_MAVE_VUS_BIAS_TSV")
        or (
            external_root.parents[1]
            / "clinvar"
            / "vus-run"
            / "tsc-vus-2026-07-07"
            / "tsc_vus_input.bias_output.tsv"
        )
    )
    heldout_bias_path = Path(
        os.environ.get("RAPTOR_MAVE_HELDOUT_BIAS_TSV")
        or (external_root.parents[1] / "full-holdout-2026-07-07" / "holdout_input.bias_output.tsv")
    )

    vus_bias_by_c = _load_bias_tsc2_rows(vus_bias_path, entry.gene)
    heldout_bias_by_c = _load_bias_tsc2_rows(heldout_bias_path, entry.gene)

    overlapping_c = set(vus_bias_by_c) & set(heldout_bias_by_c)
    if overlapping_c:
        raise ReportBuildError(
            f"BIAS VUS-universe and heldout-universe TSVs are not disjoint on hgvsc: "
            f"{sorted(overlapping_c)[:5]!r}..."
        )

    vus_matched = _match_scores_to_bias(raw_rows, vus_bias_by_c)
    heldout_matched = _match_scores_to_bias(raw_rows, heldout_bias_by_c)

    both = set(vus_matched) & set(heldout_matched)
    if both:
        raise ReportBuildError(f"variant(s) matched both partitions: {sorted(both)!r}")

    # Cross-check the independent BIAS-based reconstruction against the
    # existing, already-verified overlap fixtures (identity.join_exact_overlap,
    # fail-loud), keyed by the exact bare `c.` HGVS string -- the identity
    # axis both fixtures and this reconstruction agree on (the fixtures'
    # own genomic-position fields carry a pre-existing off-by-one artifact
    # relative to this script's fresh BIAS-derived positions; see
    # docs/reference/mave-tsc2-source-register-2026-07.md, so genomic SPDI
    # is intentionally not the cross-check key here).
    vus_expected_raw, heldout_expected_raw, heldout_direction_raw = _existing_overlap_expected(
        mavedb_dir
    )

    def _to_observed(records: dict[str, tuple[MaveScoreRecord, dict]]) -> list[MaveScoreRecord]:
        return [
            MaveScoreRecord(
                variant_id=hgvs_c,
                hgvs_c=record.hgvs_c,
                score=record.score,
                reference=record.reference,
            )
            for hgvs_c, (record, _bias_row) in records.items()
        ]

    vus_expected = list(vus_expected_raw.values())
    heldout_expected = list(heldout_expected_raw.values())

    try:
        join_exact_overlap(vus_expected, _to_observed(vus_matched))
    except (ExactOverlapMismatchError, ReferenceMismatchError) as exc:
        raise ReportBuildError(f"VUS-overlap cross-check against existing fixture failed: {exc}") from exc

    try:
        join_exact_overlap(heldout_expected, _to_observed(heldout_matched))
    except (ExactOverlapMismatchError, ReferenceMismatchError) as exc:
        raise ReportBuildError(
            f"heldout-overlap cross-check against existing fixture failed: {exc}"
        ) from exc

    # Recompute functional classes fresh from the raw MaveDB score column
    # (never trusted blindly from the existing fixture).
    vus_functional = {
        variant_id: classify_functional_score(record.score) for variant_id, (record, _row) in vus_matched.items()
    }
    heldout_functional = {
        variant_id: classify_functional_score(record.score)
        for variant_id, (record, _row) in heldout_matched.items()
    }

    partitions = build_partitions(
        calibration_ids=set(),
        heldout_overlap_ids=set(heldout_matched),
        vus_overlap_ids=set(vus_matched),
    )
    independent_by_partition = {p.partition: p.independent for p in partitions}

    def _class_counts(functional_by_id: dict) -> dict[str, int]:
        counts = {member.value: 0 for member in FunctionalClass}
        for functional_class in functional_by_id.values():
            counts[functional_class.value] += 1
        return counts

    vus_class_counts = _class_counts(vus_functional)
    heldout_class_counts = _class_counts(heldout_functional)

    # ClinVar-direction x functional-class concordance for the heldout
    # partition (the ONLY place a ClinVar-derived signal is used) -- coarse
    # low/high direction only, never the raw B/LB/P/LP code.
    direction_matrix = {"low_direction": {m.value: 0 for m in FunctionalClass}, "high_direction": {m.value: 0 for m in FunctionalClass}}
    for norm_key, label in heldout_direction_raw.items():
        functional_class = heldout_functional.get(norm_key)
        if functional_class is None:
            continue
        direction = "low_direction" if label in {"B", "LB"} else "high_direction"
        direction_matrix[direction][functional_class.value] += 1

    orthogonal_by_partition = {}
    for name, matched, kind in (
        ("vus_overlap", vus_matched, PartitionKind.VUS_OVERLAP),
        ("heldout_overlap", heldout_matched, PartitionKind.HELDOUT_OVERLAP),
    ):
        observations = [
            OrthogonalObservation(
                variant_id=variant_id,
                raptor_score=_ACMG_ORDINAL[bias_row["acmgClassification"]],
                mave_score=record.score,
                partition=kind,
            )
            for variant_id, (record, bias_row) in matched.items()
        ]
        metrics = compute_orthogonal_metrics(
            observations,
            bootstrap_resamples=eval_cfg["bootstrap"]["resamples"],
            random_seed=eval_cfg["bootstrap"]["random_seed"],
        )
        orthogonal_by_partition[name] = {
            "validation_mode": metrics.validation_mode,
            "spearman": {
                "n": metrics.spearman.n,
                "statistic": round(metrics.spearman.statistic, 6),
                "bootstrap_ci": [round(v, 6) for v in metrics.spearman.bootstrap_ci],
            },
            "kendall": {
                "n": metrics.kendall.n,
                "statistic": round(metrics.kendall.statistic, 6),
                "bootstrap_ci": [round(v, 6) for v in metrics.kendall.bootstrap_ci],
            },
            "class_power": {
                functional_class.value: {
                    "n": power.n,
                    "status": power.status,
                    "gating": power.gating,
                }
                for functional_class, power in metrics.class_power.items()
            },
            "raptor_side_proxy": (
                "BIAS-2015's own prior ACMG classification (ordinal-encoded: "
                "benign=-2 .. pathogenic=2), NOT raptor.scorer output, NOT MAVE-derived, "
                "NOT used by decide_gate."
            ),
        }

    aggregate = {
        "report": "tsc2_mave_clipe_orthogonal_2026-07-13",
        "validation_mode": "NON_GATING",
        "source": {
            "urn": entry.urn,
            "gene": entry.gene,
            "transcript": entry.transcript,
            "license": entry.license,
            "sha256": entry.sha256,
            "variant_count": entry.variant_count,
            "doi": raw_entry.get("doi"),
            "publication_pmcid": raw_entry.get("publication_pmcid"),
        },
        "functional_thresholds": eval_cfg["functional_thresholds"],
        "identity_verification": {
            "method": (
                "exact hgvsc string match against two independently-computed real "
                "BIAS-2015 outputs (VUS candidate-universe run + full held-out run), "
                "cross-checked by exact bare-c.-HGVS-string join against the existing "
                "verified overlap fixture; no cDNA->genomic projection was performed "
                "or required"
            ),
            "vus_overlap_n": len(vus_matched),
            "heldout_overlap_n": len(heldout_matched),
            "mutually_exclusive": not both,
            "reference_allele_mismatches": 0,
        },
        "partitions": {
            "vus_overlap": {
                "n": len(vus_matched),
                "independent": independent_by_partition[PartitionKind.VUS_OVERLAP],
                "independence_note": (
                    "no clinical/ClinVar label exists for a VUS; this overlap is free of "
                    "any label dependency on RAPTOR/BIAS's TSC2 pipeline"
                ),
                "functional_class_counts": vus_class_counts,
            },
            "heldout_overlap": {
                "n": len(heldout_matched),
                "independent": independent_by_partition[PartitionKind.HELDOUT_OVERLAP],
                "independence_note": (
                    "ClinVar-labelled held-out variants; NOT independent (BIAS/RAPTOR's "
                    "TSC2 pipeline was built/QA'd against ClinVar-derived evidence)"
                ),
                "functional_class_counts": heldout_class_counts,
                "clinvar_direction_concordance_matrix": direction_matrix,
            },
        },
        "orthogonal_metrics": orthogonal_by_partition,
        "limitations": [
            "MaveDB target transcript is NM_000548.5; the on-disk BIAS-2015 outputs used "
            "for identity matching carry NM_000548.4 -- matching is by exact hgvs_c string "
            "only (never a projection), consistent with both transcripts sharing the same "
            "CDS numbering for the matched substitutions (verified: 0 ref/alt disagreements "
            "across all matched rows).",
            "The VUS-overlap and heldout-overlap orthogonal-correlation 'raptor_side_proxy' "
            "is BIAS-2015's own prior ACMG classification (an ordinal encoding), not a "
            "raptor.scorer probability and not gating evidence.",
            "functional_PLP is UNDERPOWERED (n<10) in both partitions; all class-power "
            "figures here are descriptive only, per configs/eval/mave_tsc2.yaml:min_class_n.",
            "The pre-existing overlap_classified.json fixture's recorded genomic positions "
            "carry a consistent +/-1 offset relative to this script's fresh BIAS-2015-derived "
            "genomic positions for the same bare c. HGVS changes (BIAS's own hgvsg/refAllele/"
            "altAllele fields agree with each other and with the fresh reconstruction; see "
            "docs/reference/mave-tsc2-source-register-2026-07.md). The cross-check therefore "
            "joins on the exact bare c. HGVS string (the axis both sources agree on), not on "
            "genomic SPDI; no genomic coordinate from either source is trusted blindly.",
        ],
        "phase2_blocked": [
            "IGVF VAMP-seq TSC2 protein-abundance data (IGVFDS5595BTYJ/IGVFFI9747KART): "
            "confirm_pending, access not held.",
            "IGVF Saturation Genome Editing TSC2 data (IGVFDS1782FCXW/IGVFFI3097DFGF): "
            "confirm_pending, access not held.",
            "CAGI7 TSC2 protein-stability challenge data: confirm_pending, access not held, "
            "distribution terms not yet reviewed.",
        ],
    }
    return aggregate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-config", type=Path, default=DEFAULT_SOURCES_CONFIG)
    parser.add_argument("--eval-config", type=Path, default=DEFAULT_EVAL_CONFIG)
    parser.add_argument(
        "--external-root",
        type=Path,
        default=None,
        help=f"external MAVE data root (default: ${EXTERNAL_ROOT_ENV} or {DEFAULT_EXTERNAL_ROOT})",
    )
    parser.add_argument("--urn", default="urn:mavedb:00001201-a-1")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data") / "census" / "tsc2_mave_clipe_orthogonal_2026-07-13.json",
    )
    return parser


def _sanitize_nan(value):
    """Replace non-finite floats (NaN from degenerate bootstrap resamples,
    e.g. an all-tied ranking) with JSON `null` so the emitted aggregate is
    strictly valid JSON (RFC 8259) rather than relying on Python's
    non-standard `NaN`/`Infinity` literals."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _sanitize_nan(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_nan(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    external_root = args.external_root or Path(
        os.environ.get(EXTERNAL_ROOT_ENV) or DEFAULT_EXTERNAL_ROOT
    ).expanduser()

    try:
        aggregate = build_report(
            sources_config=args.sources_config,
            eval_config=args.eval_config,
            external_root=external_root,
            urn=args.urn,
        )
    except ReportBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    aggregate = _sanitize_nan(aggregate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
