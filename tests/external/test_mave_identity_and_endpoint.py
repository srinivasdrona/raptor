from __future__ import annotations

from importlib import import_module

import pytest


def _source_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.source")
    except ImportError as exc:
        pytest.fail(f"external MAVE source loader is not implemented: {exc}")
    return {
        "MaveScoreRecord": module.MaveScoreRecord,
    }


def _identity_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.identity")
    except ImportError as exc:
        pytest.fail(f"external MAVE identity module is not implemented: {exc}")
    return {
        "CanonicalVariant": module.CanonicalVariant,
        "ExactOverlapMismatchError": module.ExactOverlapMismatchError,
        "ProjectionUnavailableError": module.ProjectionUnavailableError,
        "ReferenceMismatchError": module.ReferenceMismatchError,
        "join_exact_overlap": module.join_exact_overlap,
        "map_cdna_to_spdi": module.map_cdna_to_spdi,
    }


def _endpoint_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.endpoint")
    except ImportError as exc:
        pytest.fail(f"external MAVE endpoint is not implemented: {exc}")
    return {
        "FunctionalClass": module.FunctionalClass,
        "classify_functional_score": module.classify_functional_score,
        "run_label_blind_validation": module.run_label_blind_validation,
    }


def _score_record(*, variant_id, score, hgvs_c=None, reference=None):
    api = _source_api()
    return api["MaveScoreRecord"](
        variant_id=variant_id,
        hgvs_c=hgvs_c,
        score=score,
        reference=reference,
    )


def _canonical_variant(*, variant_id, reference):
    api = _identity_api()
    return api["CanonicalVariant"](variant_id=variant_id, reference=reference)


def test_functional_thresholds_are_exact_and_not_clinical_labels() -> None:
    api = _endpoint_api()
    functional_class = api["FunctionalClass"]
    classify = api["classify_functional_score"]

    assert classify(0.241999) is functional_class.FUNCTIONAL_BLB
    assert classify(0.242) is functional_class.AMBIGUOUS
    assert classify(0.477) is functional_class.AMBIGUOUS
    assert classify(0.477001) is functional_class.FUNCTIONAL_PLP

    forbidden = {"B", "LB", "P", "LP", "Benign", "Likely benign", "Pathogenic", "Likely pathogenic"}
    for member in functional_class:
        assert member.value not in forbidden
        assert "clinical" not in str(member.value).lower()


def test_exact_overlap_join_fails_on_unknown_drop_and_reference_mismatch() -> None:
    api = _identity_api()

    expected = [
        _canonical_variant(variant_id="NC_000016.10:100:A:G", reference="A"),
        _canonical_variant(variant_id="NC_000016.10:200:C:T", reference="C"),
    ]
    observed = [
        _score_record(
            variant_id="NC_000016.10:100:A:G",
            score=0.200,
            hgvs_c="c.100A>G",
            reference="A",
        ),
        _score_record(
            variant_id="NC_000016.10:300:G:A",
            score=0.600,
            hgvs_c="c.300G>A",
            reference="G",
        ),
    ]

    with pytest.raises(api["ExactOverlapMismatchError"]) as exc:
        api["join_exact_overlap"](expected, observed)
    assert exc.value.unknown_variant_ids == {"NC_000016.10:300:G:A"}
    assert exc.value.missing_variant_ids == {"NC_000016.10:200:C:T"}

    with pytest.raises(api["ReferenceMismatchError"], match="reference"):
        api["join_exact_overlap"](
            [_canonical_variant(variant_id="NC_000016.10:100:A:G", reference="A")],
            [_score_record(variant_id="NC_000016.10:100:A:G", score=0.200, hgvs_c="c.100A>G", reference="C")],
        )


def test_full_cdna_projection_requires_projector_and_is_deterministic() -> None:
    api = _identity_api()
    rows = [
        _score_record(variant_id=None, hgvs_c="c.200C>T", score=0.600, reference="C"),
        _score_record(variant_id=None, hgvs_c="c.100A>G", score=0.200, reference="A"),
    ]

    with pytest.raises(api["ProjectionUnavailableError"]):
        api["map_cdna_to_spdi"](rows, transcript="NM_000548.5")

    class FakeProjector:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def project(self, transcript: str, hgvs_c: str) -> str:
            self.calls.append((transcript, hgvs_c))
            return {
                "c.100A>G": "NC_000016.10:100:A:G",
                "c.200C>T": "NC_000016.10:200:C:T",
            }[hgvs_c]

    projector = FakeProjector()
    forward = api["map_cdna_to_spdi"](rows, transcript="NM_000548.5", projector=projector)
    reverse = api["map_cdna_to_spdi"](list(reversed(rows)), transcript="NM_000548.5", projector=projector)

    assert [(row.variant_id, row.hgvs_c, row.score) for row in forward] == [
        ("NC_000016.10:100:A:G", "c.100A>G", 0.200),
        ("NC_000016.10:200:C:T", "c.200C>T", 0.600),
    ]
    assert [(row.variant_id, row.hgvs_c, row.score) for row in reverse] == [
        ("NC_000016.10:100:A:G", "c.100A>G", 0.200),
        ("NC_000016.10:200:C:T", "c.200C>T", 0.600),
    ]
    assert projector.calls.count(("NM_000548.5", "c.100A>G")) >= 1
    assert projector.calls.count(("NM_000548.5", "c.200C>T")) >= 1


def test_label_blind_endpoint_calls_scorer_with_variant_id_only_and_never_authorizes() -> None:
    api = _endpoint_api()
    rows = [
        _score_record(variant_id="SENTINEL_VARIANT_1", hgvs_c="c.100A>G", score=0.200, reference="A"),
        _score_record(variant_id="SENTINEL_VARIANT_2", hgvs_c="c.200C>T", score=0.600, reference="C"),
        _score_record(variant_id="SENTINEL_VARIANT_3", hgvs_c="c.300G>A", score=0.300, reference="G"),
    ]
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_scorer(*args, **kwargs) -> float:
        calls.append((args, kwargs))
        assert not kwargs
        assert len(args) == 1
        assert isinstance(args[0], str)
        return {
            "SENTINEL_VARIANT_1": 0.100,
            "SENTINEL_VARIANT_2": 0.700,
            "SENTINEL_VARIANT_3": 0.350,
        }[args[0]]

    report = api["run_label_blind_validation"](
        rows,
        fake_scorer,
        bootstrap_resamples=16,
        random_seed=11,
    )
    aggregate = report.aggregate()

    assert [args[0] for args, _ in calls] == [
        "SENTINEL_VARIANT_1",
        "SENTINEL_VARIANT_2",
        "SENTINEL_VARIANT_3",
    ]
    assert aggregate["validation_mode"] == "NON_GATING"
    assert "vus_authorized" not in aggregate
    assert "gate" not in aggregate
