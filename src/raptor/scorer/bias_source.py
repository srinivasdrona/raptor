"""PRD-01 sec 10.1/10.4 `bias_source.py` — the arm's-length `BiasSource` port.

ADR-0007 (AGPL): RAPTOR never imports BIAS-2015. `BiasTsvSource` parses a
committed BIAS output TSV across a clean data boundary -- the *only* thing
RAPTOR consumes from BIAS. The live x64-worker adapter that PRODUCES this
TSV (ADR-0008) is deferred; tests inject a fake/fixture source instead.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Protocol, runtime_checkable

from .contract import BiasOutputContract
from .model import BiasRecord


@runtime_checkable
class BiasSource(Protocol):
    """Port: anything yielding `BiasRecord`s. Real impl = `BiasTsvSource`;
    tests inject a fake in-memory source (offline, no live BIAS pipeline)."""

    def records(self, run: object | None = None) -> Iterable[BiasRecord]:
        ...


def _flatten_rationale(rationale: Mapping[str, object]) -> dict[str, tuple[int, str]]:
    """Flatten BIAS's nested `rationale` JSON (`{"pvs": {"pvs1": [int, str]},
    "ps": {...}, ...}`) into a single-level `{criterion_key: (int, str)}`
    mapping. Generic over the category/criterion names actually present --
    no BIAS category or criterion code is hardcoded here."""
    flat: dict[str, tuple[int, str]] = {}
    for _category, entries in rationale.items():
        if not isinstance(entries, dict):
            continue
        for criterion_key, value in entries.items():
            fired_int, explanation = value[0], value[1]
            flat[criterion_key] = (int(fired_int), str(explanation))
    return flat


class BiasTsvSource:
    """Real `BiasSource` impl: parses a committed BIAS-2015 output TSV.

    Asserts `BiasOutputContract` on the header before parsing any row (a
    column drift is a source-contract breach -- fails loud, R-B1).
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def records(self, run: object | None = None) -> Iterator[BiasRecord]:
        with open(self.path, "rt", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            try:
                header = next(reader)
            except StopIteration:
                return
            BiasOutputContract.assert_columns(header)
            idx = {name: i for i, name in enumerate(header)}

            for row in reader:
                if not row:
                    continue
                chromosome = row[idx["chromosome"]]
                position = int(row[idx["position"]])
                ref_allele = row[idx["refAllele"]]
                alt_allele = row[idx["altAllele"]]
                variant_id = f"{chromosome}:{position}:{ref_allele}:{alt_allele}"
                rationale = json.loads(row[idx["rationale"]])
                criteria = _flatten_rationale(rationale)
                yield BiasRecord(
                    chromosome=chromosome,
                    position=position,
                    ref_allele=ref_allele,
                    alt_allele=alt_allele,
                    variant_id=variant_id,
                    variant_type=row[idx["variantType"]],
                    consequence=row[idx["consequence"]],
                    acmg_classification=row[idx["acmgClassification"]],
                    gene_name=row[idx["geneName"]],
                    transcript=row[idx["transcript"]],
                    criteria=criteria,
                    provenance={
                        "hgvsg": row[idx["hgvsg"]],
                        "hgvsc": row[idx["hgvsc"]],
                        "hgvsp": row[idx["hgvsp"]],
                        "raw_row": "\t".join(row),
                    },
                )
