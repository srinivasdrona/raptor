"""PRD-02 sec 10.3 `report.py` — FR7/AC2: deterministic content vs run metadata.

`IngestReport.content_hash()` is a function only of deterministic content
(sorted `variant_id`s, class histogram, counts, manual-queue summary) --
`run_id`/`generated_at` (run metadata) are excluded (AC2/R-A11).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

from .model import ManualQueueItem, NormalizedVariant


@dataclass(frozen=True)
class IngestReport:
    run_id: str
    generated_at: str
    total_input: int
    total_normalized: int
    total_manual_queue: int
    total_dropped: int
    variant_ids: tuple[str, ...]
    class_histogram: dict
    manual_queue_summary: tuple[dict, ...]

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        generated_at: str,
        total_input: int,
        normalized: Sequence[NormalizedVariant],
        manual_queue: Sequence[ManualQueueItem],
    ) -> "IngestReport":
        variant_ids = sorted({r.variant_id for r in normalized})

        class_histogram: dict[str, int] = {}
        for r in normalized:
            key = getattr(r.variant_class, "value", r.variant_class)
            class_histogram[key] = class_histogram.get(key, 0) + 1

        mq_counts: dict[tuple[str, str], int] = {}
        for m in manual_queue:
            key = (m.failure_stage, m.error_code)
            mq_counts[key] = mq_counts.get(key, 0) + 1
        manual_queue_summary = tuple(
            {"failure_stage": stage, "error_code": code, "count": count}
            for (stage, code), count in sorted(mq_counts.items())
        )

        total_normalized = len(normalized)
        total_manual_queue = len(manual_queue)
        total_dropped = total_input - (total_normalized + total_manual_queue)

        return cls(
            run_id=run_id,
            generated_at=generated_at,
            total_input=total_input,
            total_normalized=total_normalized,
            total_manual_queue=total_manual_queue,
            total_dropped=total_dropped,
            variant_ids=tuple(variant_ids),
            class_histogram=class_histogram,
            manual_queue_summary=manual_queue_summary,
        )

    def content_hash(self) -> str:
        """Deterministic-content hash (FR7/AC2): excludes `run_id` and
        `generated_at` -- two runs on identical inputs/config must produce
        an identical hash regardless of when/under-what-run-id they ran."""
        payload = {
            "total_input": self.total_input,
            "total_normalized": self.total_normalized,
            "total_manual_queue": self.total_manual_queue,
            "total_dropped": self.total_dropped,
            "variant_ids": sorted(self.variant_ids),
            "class_histogram": dict(sorted(self.class_histogram.items())),
            "manual_queue_summary": [dict(sorted(d.items())) for d in self.manual_queue_summary],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
