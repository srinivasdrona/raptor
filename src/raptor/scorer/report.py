"""PRD-01 sec 10.4 `report.py` — FR6/AC3: deterministic content vs run metadata.

`ScorerReport.content_hash()` is a function only of deterministic content
(sorted per-criterion evidence summary, histograms, manual-queue summary)
-- `run_id`/`generated_at` (run metadata) are excluded, matching the
`IngestReport` pattern (PRD-02) this mirrors.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

from .model import EvidenceRecord, ManualReviewItem


@dataclass(frozen=True)
class ScorerReport:
    run_id: str
    generated_at: str
    total_input: int
    total_scored: int
    total_evidence: int
    total_manual_queue: int
    manual_review_count: int
    criterion_histogram: dict
    manual_queue_summary: tuple[dict, ...]
    evidence_summary: tuple[dict, ...]
    variant_outcomes: tuple[dict, ...]

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        generated_at: str,
        total_input: int,
        evidence_records: Sequence[EvidenceRecord],
        manual_queue: Sequence[ManualReviewItem],
        variant_outcomes: Sequence[dict] = (),
    ) -> "ScorerReport":
        evidence_summary = tuple(
            sorted(
                (
                    {
                        "variant_id": e.variant_id,
                        "criterion": e.criterion,
                        "strength": e.strength,
                        "direction": e.direction,
                    }
                    for e in evidence_records
                ),
                key=lambda d: (d["variant_id"], d["criterion"]),
            )
        )

        criterion_histogram: dict[str, int] = {}
        for e in evidence_records:
            criterion_histogram[e.criterion] = criterion_histogram.get(e.criterion, 0) + 1

        mq_counts: dict[tuple[str, str], int] = {}
        for m in manual_queue:
            key = (m.failure_stage, m.error_code)
            mq_counts[key] = mq_counts.get(key, 0) + 1
        manual_queue_summary = tuple(
            {"failure_stage": stage, "error_code": code, "count": count}
            for (stage, code), count in sorted(mq_counts.items())
        )

        scored_variant_ids = {e.variant_id for e in evidence_records}

        variant_outcomes_tuple = tuple(
            sorted(
                (
                    {"variant_id": str(o["variant_id"]), "outcome": str(o["outcome"])}
                    for o in variant_outcomes
                ),
                key=lambda d: (d["variant_id"], d["outcome"]),
            )
        )

        return cls(
            run_id=run_id,
            generated_at=generated_at,
            total_input=total_input,
            total_scored=len(scored_variant_ids),
            total_evidence=len(evidence_records),
            total_manual_queue=len(manual_queue),
            manual_review_count=len(manual_queue),
            criterion_histogram=criterion_histogram,
            manual_queue_summary=manual_queue_summary,
            evidence_summary=evidence_summary,
            variant_outcomes=variant_outcomes_tuple,
        )

    def content_hash(self) -> str:
        """Deterministic-content hash (FR6/AC3): excludes `run_id` and
        `generated_at` -- two runs on identical pinned inputs/config must
        produce an identical hash regardless of when/under-what-run-id
        they ran (R-A11)."""
        payload = {
            "total_input": self.total_input,
            "total_scored": self.total_scored,
            "total_evidence": self.total_evidence,
            "total_manual_queue": self.total_manual_queue,
            "criterion_histogram": dict(sorted(self.criterion_histogram.items())),
            "manual_queue_summary": [dict(sorted(d.items())) for d in self.manual_queue_summary],
            "evidence_summary": [dict(sorted(d.items())) for d in self.evidence_summary],
            "variant_outcomes": [dict(sorted(d.items())) for d in self.variant_outcomes],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
