"""Decision B (BS2 policy) slot 2 sec 1.1 `probe_bs2_firings.py` — Probe 1.

The first of the three empirical probes that MUST run **before** any BS2
disposition is recorded (slot 1's non-negotiable ordering): characterizes
every BS2 firing the pinned BIAS-3.0.0 `benign_classifiers.get_bs2`
(L116-176) emitted in a real, committed 18-column `BiasTsvSource` output
TSV -- never a label/benchmark/held-out file (ADR-0007/R-A2/H1).

Reports ONLY aggregate, non-identifying rollups: total BS2 firings, the
gene distribution, any co-firing pathogenic-family criterion (a
BS2+PVS1/PS/PM/PP co-fire is a red flag worth a human look), and the
parsed population `healthy_individual_counts` signal that `get_bs2`
itself reports. No per-variant chromosome/position/ref/alt/variant_id row
is ever included in the report -- the committed report can never
re-identify a specific ClinVar record. Incidence characterizes the
firing; it never licenses inclusion (slot 1/slot 2 sec 0).

Usage::

    python scripts/probe_bs2_firings.py BIAS_TSV --output REPORT_JSON

Exits 0 on success. The report is fully deterministic: running the probe
twice against the same input TSV produces byte-identical JSON. This
script never scores, classifies, or promotes any variant -- it is a
characterization probe only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from raptor.scorer.bias_source import BiasTsvSource

#: BIAS's own pathogenic-family criterion-key prefixes (PVS/PS/PM/PP) --
#: generic over the exact code, never a hardcoded criterion list. The
#: benign-family codes (BA/BS/BP) never count as a "pathogenic co-fire".
_PATHOGENIC_PREFIXES: tuple[str, ...] = ("PVS", "PS", "PM", "PP")

#: `get_bs2`'s own rationale phrasing (benign_classifiers.py L116-176)
#: always names the healthy-individual/control count immediately after
#: "Observed", across all three fired shapes it emits: dominant
#: heterozygous ("Observed in {N} healthy individuals for autosomal
#: dominant disease ..."), recessive homozygous ("Observed as homozygous
#: ({N}) in healthy individuals for autosomal recessive disease ..."),
#: and X-linked ("Observed in healthy males (hemizygous: {N}) or females
#: (homozygous: {N}) for X-linked disease ..." -- the male hemizygous
#: count is captured first, a documented simplification since the pinned
#: TSC1/TSC2 corpus is autosomal dominant only). The first integer
#: following "Observed" is that count in every shape.
_HEALTHY_COUNT_RE = re.compile(r"Observed\D*?(\d+)", re.IGNORECASE)


class Bs2ProbeError(Exception):
    """Raised when a BS2-firing rationale does not match any known
    `get_bs2` phrasing -- fail loud rather than silently drop a firing
    from the aggregate (a probe that swallows a firing cannot reconcile
    to the census total)."""


def _parse_healthy_individual_count(rationale_text: str) -> int:
    match = _HEALTHY_COUNT_RE.search(rationale_text)
    if not match:
        raise Bs2ProbeError(
            f"BS2 firing rationale does not match any known get_bs2 phrasing: {rationale_text!r}"
        )
    return int(match.group(1))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe 1 (BS2 policy slot 2 sec 1.1): characterize every BS2 firing in a "
        "pinned BIAS-2015 output TSV. Aggregate/non-identifying only -- never persists "
        "per-variant chromosome/position/ref/alt rows."
    )
    parser.add_argument("bias_tsv", help="Path to a pinned BIAS-2015 output TSV (18-column contract).")
    parser.add_argument("--output", required=True, help="Path to write the canonical BS2 firing report JSON.")
    return parser.parse_args(argv)


def probe_bs2_firings(bias_tsv: str | Path) -> dict:
    """Run Probe 1 over `bias_tsv` and return the canonical, deterministic
    aggregate report. Never returns a per-variant row -- only rollups."""
    path = Path(bias_tsv)
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    total_rows = 0
    total_bs2_firings = 0
    gene_distribution: Counter[str] = Counter()
    pathogenic_cofires: Counter[str] = Counter()
    healthy_individual_counts: list[int] = []

    for record in BiasTsvSource(path).records():
        total_rows += 1
        bs2 = record.criteria.get("bs2", (0, ""))
        if bs2[0] == 0:
            continue

        total_bs2_firings += 1
        gene_distribution[record.gene_name] += 1
        healthy_individual_counts.append(_parse_healthy_individual_count(bs2[1]))

        for criterion_key, (fired, _explanation) in record.criteria.items():
            if fired == 0 or criterion_key.lower() == "bs2":
                continue
            if criterion_key.upper().startswith(_PATHOGENIC_PREFIXES):
                pathogenic_cofires[criterion_key.upper()] += 1

    return {
        "total_rows": total_rows,
        "total_bs2_firings": total_bs2_firings,
        "gene_distribution": dict(sorted(gene_distribution.items())),
        "pathogenic_cofires": dict(sorted(pathogenic_cofires.items())),
        "signals": {"healthy_individual_counts": sorted(healthy_individual_counts)},
        "source_sha256": source_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = probe_bs2_firings(args.bias_tsv)
    canonical_json = json.dumps(report, sort_keys=True, indent=2)
    Path(args.output).write_text(canonical_json, encoding="utf-8")
    print(canonical_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
