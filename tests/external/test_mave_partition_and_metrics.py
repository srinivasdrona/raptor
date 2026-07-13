from __future__ import annotations

from importlib import import_module

import pytest


def _endpoint_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.endpoint")
    except ImportError as exc:
        pytest.fail(f"external MAVE endpoint is not implemented: {exc}")
    return {
        "FunctionalClass": module.FunctionalClass,
    }


def _partition_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.partition")
    except ImportError as exc:
        pytest.fail(f"external MAVE partition module is not implemented: {exc}")
    return {
        "PartitionKind": module.PartitionKind,
        "PartitionOverlapError": module.PartitionOverlapError,
        "build_partitions": module.build_partitions,
    }


def _metrics_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.orthogonal_metrics")
    except ImportError as exc:
        pytest.fail(f"external MAVE metrics module is not implemented: {exc}")
    return {
        "OrthogonalObservation": module.OrthogonalObservation,
        "compute_orthogonal_metrics": module.compute_orthogonal_metrics,
    }


def test_partitions_are_mutually_exclusive_and_independence_is_explicit() -> None:
    api = _partition_api()
    partition_kind = api["PartitionKind"]

    records = api["build_partitions"](
        calibration_ids={"cal-1", "cal-2"},
        heldout_overlap_ids={"hold-1"},
        vus_overlap_ids={"vus-1", "vus-2"},
    )
    by_id = {record.variant_id: record for record in records}

    assert by_id["cal-1"].partition is partition_kind.CALIBRATION
    assert by_id["cal-1"].independent is False
    assert by_id["hold-1"].partition is partition_kind.HELDOUT_OVERLAP
    assert by_id["hold-1"].independent is False
    assert by_id["vus-1"].partition is partition_kind.VUS_OVERLAP
    assert by_id["vus-1"].independent is True

    with pytest.raises(api["PartitionOverlapError"], match="mutually exclusive|overlap"):
        api["build_partitions"](
            calibration_ids={"dup"},
            heldout_overlap_ids={"dup"},
            vus_overlap_ids=set(),
        )


def test_rank_metrics_are_deterministic_non_gating_and_honest_at_small_n() -> None:
    endpoint_api = _endpoint_api()
    partition_api = _partition_api()
    metrics_api = _metrics_api()
    observation = metrics_api["OrthogonalObservation"]
    functional_class = endpoint_api["FunctionalClass"]
    partition_kind = partition_api["PartitionKind"]

    rows = [
        observation("plp-1", 0.800, 0.620, partition_kind.VUS_OVERLAP),
        observation("plp-2", 0.720, 0.610, partition_kind.VUS_OVERLAP),
        observation("plp-3", 0.700, 0.590, partition_kind.VUS_OVERLAP),
        observation("blb-1", 0.120, 0.100, partition_kind.VUS_OVERLAP),
        observation("blb-2", 0.180, 0.050, partition_kind.VUS_OVERLAP),
        observation("amb-1", 0.360, 0.300, partition_kind.VUS_OVERLAP),
    ]

    first = metrics_api["compute_orthogonal_metrics"](
        rows,
        bootstrap_resamples=32,
        random_seed=19,
    )
    second = metrics_api["compute_orthogonal_metrics"](
        list(reversed(rows)),
        bootstrap_resamples=32,
        random_seed=19,
    )

    assert first == second
    assert first.validation_mode == "NON_GATING"
    assert first.spearman.n == len(rows)
    assert first.kendall.n == len(rows)
    assert isinstance(first.spearman.statistic, float)
    assert isinstance(first.kendall.statistic, float)
    assert isinstance(first.spearman.bootstrap_ci, tuple)
    assert isinstance(first.kendall.bootstrap_ci, tuple)
    assert first.agreement_matrix[functional_class.FUNCTIONAL_PLP.value][functional_class.FUNCTIONAL_PLP.value] >= 1

    plp = first.class_power[functional_class.FUNCTIONAL_PLP]
    assert plp.n == 3
    assert plp.status == "UNDERPOWERED"
    assert plp.gating == "NON_GATING"
