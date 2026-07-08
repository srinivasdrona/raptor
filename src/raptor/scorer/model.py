"""PRD-01 sec 10.4 `model.py` — the record shapes flowing through the scorer.

`BiasRecord` is one parsed BIAS-2015 output row (the arm's-length data
boundary, ADR-0007): coordinates + the flattened `rationale` criterion
table + a handful of provenance fields. It carries no benchmark/label
field (AC6: no trace-cribbing) -- `acmg_classification` is BIAS's own
combined call, not an external oracle label.

`CriterionCall` is one fired criterion parsed from a `BiasRecord.criteria`
entry (parse.py). `EvidenceRecord` is a grounded criterion call ready for
the KB (post-policy, i.e. already filtered to `included_criteria`).
`ManualReviewItem` is FR8's route-out for an edge case.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BiasRecord:
    """One parsed BIAS-2015 output TSV row (PRD-01 sec 10.2).

    `criteria` is a FLAT mapping of BIAS's own lowercase criterion keys
    (e.g. ``"pvs1"``, ``"pm2"``, ``"bp6"``) to ``(fired_int, explanation)``
    -- the nested ``{"pvs": {"pvs1": [...]}, ...}`` shape of BIAS's raw
    `rationale` JSON, flattened one level (see `bias_source.py`).
    """

    chromosome: str
    position: int
    ref_allele: str
    alt_allele: str
    variant_id: str
    variant_type: str
    consequence: str
    acmg_classification: str
    gene_name: str
    transcript: str
    criteria: Mapping[str, tuple[int, str]]
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class CriterionCall:
    """One fired ACMG criterion, parsed from a `BiasRecord.criteria` entry
    (FR4). `strength`/`direction` are RAPTOR's normalized vocabulary
    (config `strength_map` + the PVS/PS/PM/PP-vs-BA/BS/BP ACMG naming
    convention), not re-derived thresholds -- BIAS already decided these."""

    criterion: str
    strength: str
    direction: str
    rationale: str


@dataclass(frozen=True)
class EvidenceRecord:
    """A grounded `CriterionCall`, filtered by policy to `included_criteria`
    and ready to be staged into the KB `evidence` table (FR5)."""

    variant_id: str
    tier: str
    criterion: str
    strength: str
    direction: str
    rationale: str
    gene_name: str
    transcript: str


@dataclass(frozen=True)
class ManualReviewItem:
    """FR8 route-out: a `BiasRecord` an edge-case predicate (`edge_cases.yaml`)
    says must never be silently auto-scored (R-A3). `manual_queue` has no
    `variant_id` column (PRD-03 schema) -- the identifier travels in
    `raw_input`/`attempted_coords` instead."""

    variant_id: str
    reason: str
    failure_stage: str
    error_code: str
    attempted_coords: str | None
    raw_input: str
