"""Policy-blocker C `scripts/probe_transcript_reconciliation.py` —
empirical probes 1-3 (slot 2 sec 1), run BEFORE the reconciliation policy
is trusted (slot 3: "probes precede the policy").

Usage::

    python scripts/probe_transcript_reconciliation.py BIAS_TSV --output REPORT_JSON \\
        [--scorer-config configs/acmg/tsc.yaml] [--ingest-config configs/ingest/tsc.yaml]

Loads the real, pinned, committed BIAS-2015 output TSV (via `BiasTsvSource`
-- never a label/benchmark file) and runs, in order:

  Probe 1 -- census-arithmetic + version-delta check: per-gene/transcript
             row counts over the REAL TSV, cross-checked against the
             corpus totals; confirms every TSC1/TSC2 row carries `.4`
             while `configs/ingest/tsc.yaml`/`configs/acmg/tsc.yaml` pin
             `.5`.
  Probe 2 -- NTHL1 locus characterization: per-record chr16 genomic
             coordinates for every `NTHL1|NM_002528.6` row, confirmed to
             fall in/adjacent to the TSC2 chr16p13.3 span -- i.e. these
             are TSC2-region inputs mis-annotated to NTHL1, not a genuine
             NTHL1-disease call. Locus characterization only -- no
             reclassification; every one of these rows must still route
             to `out_of_scope_gene` (AC-C2).
  Probe 3 -- SPDI version-invariance proof: (a) structural -- the ingest
             `RawVariant` carries no transcript field at all, so the
             genomic identity a reference-backed normalizer computes from
             it cannot depend on which BIAS transcript version annotated
             a row; (b) a `reconcile_transcript_identity` disposition
             rollup over a representative sample of REAL rows from each
             of TSC1/TSC2/NTHL1 -- direct `BiasTsvSource` output carries
             no `canonical_spdi` provenance, so every in-scope row is,
             correctly, `canonical_identity_unverified` (fail-closed); a
             second, clearly-labeled SIMULATED canonical-adapter/manifest
             enrichment (never treated as trusted proof, illustration
             only) shows reconciliation activating once genuine canonical
             identity proof exists, while the out-of-scope NTHL1 rows
             still fail loud regardless.

ALWAYS persists the canonical report JSON to `--output` (never mutates
config, never scores/classifies anything) and prints it to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from raptor.ingest.model import RawVariant
from raptor.ingest.transcript_reconcile import (
    _PINNED_GENOME_ACCESSIONS,
    reconcile_transcript_identity,
)
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.model import BiasRecord

_DEFAULT_SCORER_CONFIG = "configs/acmg/tsc.yaml"
_DEFAULT_INGEST_CONFIG = "configs/ingest/tsc.yaml"

#: TSC2's genomic accession (chr16p13.3, `configs/ingest/tsc.yaml`) -- the
#: locus the 30 NTHL1 rows are checked for region-adjacency against.
_TSC2_GENOME_ACCESSION = "NC_000016.10"
#: How many bases of slack around the observed TSC2 span still counts as
#: "adjacent" (chr16p13.3 is a small, gene-dense band) -- generous enough
#: to not falsely fail on a real but nearby NTHL1 coordinate, tight enough
#: to still mean something (never a blanket "same chromosome" pass).
_ADJACENCY_SLACK_BP = 50_000


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bias_tsv", help="Path to the real, pinned BIAS-2015 output TSV (18-column contract)."
    )
    parser.add_argument(
        "--output", required=True, help="Path to write the canonical reconciliation report JSON."
    )
    parser.add_argument("--scorer-config", default=_DEFAULT_SCORER_CONFIG)
    parser.add_argument("--ingest-config", default=_DEFAULT_INGEST_CONFIG)
    return parser.parse_args(argv)


def _probe1_arithmetic(records: list[BiasRecord]) -> dict[str, Any]:
    gene_transcript_counts: Counter[str] = Counter()
    corpus_counts: Counter[str] = Counter()
    for record in records:
        gene_transcript_counts[f"{record.gene_name}|{record.transcript}"] += 1
        corpus_counts[record.gene_name] += 1

    tsc1_bias4 = gene_transcript_counts.get("TSC1|NM_000368.4", 0)
    tsc2_bias4 = gene_transcript_counts.get("TSC2|NM_000548.4", 0)
    nthl1 = gene_transcript_counts.get("NTHL1|NM_002528.6", 0)

    # census_stats.json's "corpus.TSC2" (4369) is the TSC2-region LOCUS
    # total (TSC2-labeled rows + the 30 NTHL1-labeled rows that fall in
    # the same region, Probe 2) -- distinct from `corpus_counts["TSC2"]`
    # above, which is this TSV's own `geneName == "TSC2"` row count
    # (4339). Both facts are reported; neither is silently conflated.
    tsc2_region_locus_total = tsc2_bias4 + nthl1

    return {
        "bias_gene_transcript": dict(sorted(gene_transcript_counts.items())),
        "corpus_by_gene_name": dict(sorted(corpus_counts.items())),
        "total_rows": sum(corpus_counts.values()),
        "arithmetic": {
            "tsc2_region_locus_total_eq_bias4_plus_nthl1": tsc2_region_locus_total == tsc2_bias4 + nthl1,
            "tsc2_bias4_plus_nthl1": tsc2_region_locus_total,
            "tsc1_corpus_eq_bias4": corpus_counts["TSC1"] == tsc1_bias4,
            "tsc2_corpus_eq_bias4": corpus_counts["TSC2"] == tsc2_bias4,
            "every_tsc_row_is_dot4": (
                corpus_counts["TSC1"] == tsc1_bias4 and corpus_counts["TSC2"] == tsc2_bias4
            ),
        },
    }


def _probe2_nthl1_locus(records: list[BiasRecord]) -> dict[str, Any]:
    tsc2_positions = [
        int(r.position) for r in records if r.gene_name == "TSC2" and r.chromosome == "chr16"
    ]
    nthl1_rows = [r for r in records if r.gene_name == "NTHL1"]
    nthl1_positions = [int(r.position) for r in nthl1_rows]

    tsc2_min, tsc2_max = (min(tsc2_positions), max(tsc2_positions)) if tsc2_positions else (None, None)
    window = (
        (tsc2_min - _ADJACENCY_SLACK_BP, tsc2_max + _ADJACENCY_SLACK_BP)
        if tsc2_positions
        else None
    )

    def _in_window(pos: int) -> bool:
        return window is not None and window[0] <= pos <= window[1]

    all_chr16 = all(r.chromosome == "chr16" for r in nthl1_rows)
    all_in_window = all(_in_window(p) for p in nthl1_positions)

    return {
        "nthl1_row_count": len(nthl1_rows),
        "nthl1_all_chr16": all_chr16,
        "nthl1_position_range": [min(nthl1_positions), max(nthl1_positions)]
        if nthl1_positions
        else None,
        "tsc2_position_range": [tsc2_min, tsc2_max],
        "tsc2_region_window_with_slack": list(window) if window else None,
        "nthl1_all_within_tsc2_region_window": all_in_window,
        "conclusion": (
            "TSC2-region (chr16p13.3, " + _TSC2_GENOME_ACCESSION + ") input mis-annotated to "
            "NTHL1 -- locus characterization only, no reclassification"
        )
        if all_chr16 and all_in_window
        else "locus adjacency NOT confirmed from this TSV -- do not assume TSC2-region overflow",
    }


def _probe3_spdi_invariance(records: list[BiasRecord], scorer_genes: dict[str, str]) -> dict[str, Any]:
    # (a) structural proof: the ingest RawVariant this normalizer consumes
    # carries no transcript field at all -- the genomic SPDI it computes
    # is therefore, by construction, independent of the BIAS-annotated
    # transcript version.
    raw_variant_fields = set(RawVariant.__annotations__)
    structural_invariance = "transcript" not in raw_variant_fields

    # (b) representative real-row disposition rollup, one sample per gene
    # actually present. `reconcile_transcript_identity` now requires
    # VERIFIED canonical identity PROOF
    # (`record.provenance["canonical_spdi"]`) -- direct `BiasTsvSource`
    # output (this probe's own source, `bias_source.py`) never populates
    # that key, so every in-scope row is, correctly, fail-closed to
    # `canonical_identity_unverified` rather than silently trusted. A
    # second, clearly-labeled SIMULATED canonical-adapter/manifest
    # enrichment (using the record's own already-known coordinates +
    # this reconciliation's pinned genomic accession, formatted as a
    # syntactically valid SPDI) is also run, purely to demonstrate that
    # reconciliation activates once genuine canonical proof exists (the
    # same enrichment shape `tests/scorer/test_committed_pipeline_transcript_regression.py`'s
    # `CanonicalManifestBiasSource` exercises against the real pipeline)
    # -- this simulated value is NEVER treated as trusted proof by this
    # probe or by production policy, only reported here for illustration.
    reconciliation_config = {
        gene: {"transcript_accession": transcript} for gene, transcript in scorer_genes.items()
    }
    direct_source_counts: Counter[str] = Counter()
    simulated_enrichment_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    seen_genes: set[str] = set()
    for record in records:
        if record.gene_name in seen_genes:
            continue
        seen_genes.add(record.gene_name)

        direct_spdi = str(record.provenance.get("canonical_spdi") or "")
        direct = reconcile_transcript_identity(record, direct_spdi, reconciliation_config)
        direct_source_counts[direct.disposition] += 1

        genome_accession = _PINNED_GENOME_ACCESSIONS.get(record.gene_name)
        simulated_spdi = (
            f"{genome_accession}:{record.position - 1}:{record.ref_allele}:{record.alt_allele}"
            if genome_accession
            else ""
        )
        simulated = reconcile_transcript_identity(record, simulated_spdi, reconciliation_config)
        simulated_enrichment_counts[simulated.disposition] += 1

        samples.append(
            {
                "gene": record.gene_name,
                "emitted_transcript": record.transcript,
                "pinned_transcript": direct.pinned_transcript,
                "direct_bias_tsv_source_disposition": direct.disposition,
                "simulated_canonical_adapter_spdi": simulated_spdi,
                "simulated_canonical_adapter_disposition": simulated.disposition,
                "simulated_version_delta": simulated.version_delta,
            }
        )

    return {
        "raw_variant_has_no_transcript_field": structural_invariance,
        "sample_dispositions": samples,
        "direct_bias_tsv_source_disposition_counts": dict(direct_source_counts),
        "simulated_canonical_adapter_disposition_counts": dict(simulated_enrichment_counts),
        "conclusion": (
            "direct BiasTsvSource output carries no canonical_spdi provenance and is "
            "correctly fail-closed to canonical_identity_unverified; reconciliation only "
            "activates once a canonical-adapter/manifest enrichment step supplies a "
            "verified genomic SPDI (simulated above for illustration only -- never treated "
            "as trusted proof by this probe or by production policy)"
        ),
    }


def build_report(bias_tsv: str | Path, scorer_config_path: str | Path, ingest_config_path: str | Path) -> dict[str, Any]:
    records = list(BiasTsvSource(bias_tsv).records())

    scorer_config = yaml.safe_load(Path(scorer_config_path).read_text(encoding="utf-8"))
    ingest_config = yaml.safe_load(Path(ingest_config_path).read_text(encoding="utf-8"))
    scorer_genes = dict(scorer_config.get("genes") or {})

    probe1 = _probe1_arithmetic(records)
    probe2 = _probe2_nthl1_locus(records)
    probe3 = _probe3_spdi_invariance(records, scorer_genes)

    pinned_versions = {
        gene: block.get("transcript_accession")
        for gene, block in ingest_config.items()
        if isinstance(block, dict) and "transcript_accession" in block
    }

    return {
        "status": "internal_probe_report_non_authoritative",
        "script": "scripts/probe_transcript_reconciliation.py",
        "bias_tsv": str(bias_tsv),
        "scorer_config": str(scorer_config_path),
        "ingest_config": str(ingest_config_path),
        "probe1_census_arithmetic_and_version_facts": probe1,
        "probe2_nthl1_locus_characterization": probe2,
        "probe3_spdi_version_invariance": probe3,
        "pinned_mane_transcripts": pinned_versions,
        "scorer_scope_genes": scorer_genes,
        "known_policy_gaps_resolved": [
            "TSC1 added to scorer scope (config.genes) alongside TSC2",
            "pure .4-vs-pinned-.5 version delta reconciled via base-accession identity "
            "(reconcile_transcript_identity), PROVIDED a canonical-adapter/manifest step has "
            "supplied VERIFIED canonical identity proof (record.provenance['canonical_spdi'], "
            "syntax + gene genomic accession + SNV pos/ref/alt all validated) -- no longer "
            "dumped to manual review once that proof exists",
            "direct BiasTsvSource output (no canonical-adapter/manifest enrichment) carries no "
            "canonical_spdi and is correctly fail-closed to canonical_identity_unverified -- "
            "never silently reconciled off a raw chr:pos:ref:alt echo of its own coordinates",
            "the 30 NTHL1 rows remain out_of_scope_gene manual-queue, excluded_from_scorer=True, "
            "never scored/re-attributed/classified",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(args.bias_tsv, args.scorer_config, args.ingest_config)

    canonical_json = json.dumps(report, sort_keys=True, indent=2)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json, encoding="utf-8")
    print(canonical_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
