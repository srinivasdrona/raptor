"""Mutually-exclusive MAVE validation partitions with explicit independence.

Three partitions, by construction mutually exclusive (a variant may appear
in at most one):

* `CALIBRATION`      -- used to pick/tune the fixed functional thresholds
                        (or any future calibration step). NOT independent.
* `HELDOUT_OVERLAP`  -- the 32 ClinVar-labelled held-out variants that also
                        have a MaveDB functional score. NOT independent (the
                        pipeline was built/tuned against ClinVar).
* `VUS_OVERLAP`      -- the 66 current-VUS variants that also have a MaveDB
                        functional score. INDEPENDENT (no clinical label
                        informed RAPTOR's TSC2 pipeline for these).

`build_partitions` fails loud (`PartitionOverlapError`) if any variant_id is
supplied in more than one of the three id sets.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PartitionKind(Enum):
    CALIBRATION = "calibration"
    HELDOUT_OVERLAP = "heldout_overlap"
    VUS_OVERLAP = "vus_overlap"


#: Independence is a fixed property of the partition kind, never inferred
#: per-call -- only VUS_OVERLAP variants carry no clinical-label dependency.
_INDEPENDENT_BY_KIND = {
    PartitionKind.CALIBRATION: False,
    PartitionKind.HELDOUT_OVERLAP: False,
    PartitionKind.VUS_OVERLAP: True,
}


class PartitionOverlapError(ValueError):
    """Raised when a variant_id is supplied in more than one partition --
    partitions must be mutually exclusive by construction."""


@dataclass(frozen=True)
class PartitionRecord:
    variant_id: str
    partition: PartitionKind
    independent: bool


def build_partitions(
    *,
    calibration_ids: set[str],
    heldout_overlap_ids: set[str],
    vus_overlap_ids: set[str],
) -> list[PartitionRecord]:
    """Build the mutually-exclusive partition assignment. Raises
    `PartitionOverlapError` (fail loud, never a silent last-writer-wins
    resolution) if any id appears in more than one input set."""
    groups = {
        PartitionKind.CALIBRATION: calibration_ids,
        PartitionKind.HELDOUT_OVERLAP: heldout_overlap_ids,
        PartitionKind.VUS_OVERLAP: vus_overlap_ids,
    }

    seen: dict[str, PartitionKind] = {}
    overlaps: set[str] = set()
    for kind, ids in groups.items():
        for variant_id in ids:
            if variant_id in seen:
                overlaps.add(variant_id)
            else:
                seen[variant_id] = kind

    if overlaps:
        raise PartitionOverlapError(
            f"partitions must be mutually exclusive: variant_id(s) {sorted(overlaps)!r} "
            "appear in more than one partition"
        )

    return [
        PartitionRecord(
            variant_id=variant_id,
            partition=kind,
            independent=_INDEPENDENT_BY_KIND[kind],
        )
        for kind, ids in groups.items()
        for variant_id in sorted(ids)
    ]


__all__ = ["PartitionKind", "PartitionOverlapError", "PartitionRecord", "build_partitions"]
