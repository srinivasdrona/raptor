from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from raptor.scorer.contract import BiasOutputContract
from raptor.scorer.model import BiasRecord

try:
    from raptor.eval.lineage_audit import (
        LineageGateError,
        audit_lineage,
        enforce_lineage,
    )
    from raptor.eval.lineage_policy import load_lineage_policy
    from raptor.eval.lineage_registry import LineageRegistryMismatchError
    from raptor.eval.config import load_config as load_eval_config
    from raptor.scorer.config import load_config as load_scorer_config
except ImportError:
    LineageGateError = Exception
    LineageRegistryMismatchError = Exception
    audit_lineage = None
    enforce_lineage = None
    load_eval_config = None
    load_lineage_policy = None
    load_scorer_config = None


POLICY_PATH = Path("configs/eval/bias_lineage.yaml")
SCORER_CONFIG_PATH = Path("configs/acmg/tsc.yaml")
EVAL_CONFIG_PATH = Path("configs/eval/tsc2.yaml")
ALL_28 = {
    "pvs": ["pvs1"],
    "ps": ["ps1", "ps2", "ps3", "ps4"],
    "pm": ["pm1", "pm2", "pm3", "pm4", "pm5", "pm6"],
    "pp": ["pp1", "pp2", "pp3", "pp4", "pp5"],
    "ba": ["ba1"],
    "bs": ["bs1", "bs2", "bs3", "bs4"],
    "bp": ["bp1", "bp2", "bp3", "bp4", "bp5", "bp6", "bp7"],
}


def _configs() -> dict:
    if audit_lineage is None or enforce_lineage is None:
        pytest.fail("raptor.eval.lineage_audit is not implemented")
    if not POLICY_PATH.is_file():
        pytest.fail(f"{POLICY_PATH} is not implemented")
    return {
        "policy": load_lineage_policy(POLICY_PATH),
        "scorer_config": load_scorer_config(SCORER_CONFIG_PATH),
        "eval_config": load_eval_config(EVAL_CONFIG_PATH),
    }


def _record(variant_id: str, criteria: dict[str, tuple[int, str]]) -> BiasRecord:
    return BiasRecord(
        chromosome="chr9",
        position=100,
        ref_allele="A",
        alt_allele="T",
        variant_id=variant_id,
        variant_type="SNV",
        consequence="missense_variant",
        acmg_classification="uncertain",
        gene_name="TSC1",
        transcript="NM_000368.4",
        criteria=criteria,
        provenance={"raw_row": "test"},
    )


def _item(report, criterion: str):
    return next(item for item in report.items if item.criterion == criterion)


def _rationale(fired: str, text: str) -> str:
    nested = {
        family: {criterion: [0, ""] for criterion in criteria}
        for family, criteria in ALL_28.items()
    }
    family = next(
        family for family, criteria in ALL_28.items() if fired.lower() in criteria
    )
    nested[family][fired.lower()] = [1, text]
    return json.dumps(nested, sort_keys=True, separators=(",", ":"))


def _write_tsv(path: Path, criterion: str, rationale_text: str) -> None:
    row = {
        "chromosome": "chr9",
        "position": "100",
        "refAllele": "A",
        "altAllele": "T",
        "variantType": "SNV",
        "consequence": "missense_variant",
        "acmgClassification": "uncertain",
        "alleleFreq": "",
        "hgvsg": "NC_000009.12:g.100A>T",
        "hgvsc": "",
        "hgvsp": "",
        "aaChange": "",
        "geneName": "TSC1",
        "pubmedIds": "",
        "associatedDiseases": "tuberous sclerosis",
        "dbSnpids": "",
        "transcript": "NM_000368.4",
        "rationale": _rationale(criterion, rationale_text),
    }
    header = "\t".join(BiasOutputContract.REQUIRED_COLUMNS)
    values = "\t".join(row[column] for column in BiasOutputContract.REQUIRED_COLUMNS)
    path.write_text(f"{header}\n{values}\n", encoding="utf-8")


def test_ac_l5_bp1_blocks_without_marker() -> None:
    configs = _configs()
    report = audit_lineage(
        [_record("bp1", {"bp1": (1, "Pathogenic variants are truncating.")})],
        **configs,
    )
    item = _item(report, "BP1")

    assert report.blocked is True
    assert "BP1" in report.blocking_criteria
    assert item.would_be_scored is True
    assert item.lineage_class == "aggregate_clinvar"
    assert item.detection_source == "transitive_suspect_only"
    with pytest.raises(LineageGateError) as exc:
        enforce_lineage(report)
    assert exc.value.report is report


def test_prd08_frc1_marker_on_sixth_rationale_is_still_detected() -> None:
    """PRD-08 FR-C1: marker detection must scan EVERY fired rationale row,
    never just the first `_MAX_EXAMPLE_VARIANT_IDS` (5) bounded examples.
    Here the marker vocabulary token ("clinvar") appears ONLY on the sixth
    fired BP1 row -- a bounded-to-5 scan would miss it and misreport
    `transitive_suspect_only`."""
    configs = _configs()
    records = [
        _record(f"bp1-{i}", {"bp1": (1, "Pathogenic variants are truncating.")})
        for i in range(1, 6)
    ] + [_record("bp1-6", {"bp1": (1, "Reported in ClinVar as pathogenic.")})]

    report = audit_lineage(records, **configs)
    item = _item(report, "BP1")

    assert item.total_fired == 6
    assert item.detection_source == "marker_detected"


@pytest.mark.parametrize("criterion", ["PS1", "PM5", "PM1", "PP2", "BP1"])
def test_ac_l8_scored_requires_mask_reports_then_enforces(criterion: str) -> None:
    configs = _configs()
    report = audit_lineage(
        [_record(criterion, {criterion.lower(): (1, "No marker required.")})],
        **configs,
    )

    assert report.blocked is True
    assert criterion in report.blocking_criteria
    assert _item(report, criterion).would_be_scored is True
    with pytest.raises(LineageGateError) as exc:
        enforce_lineage(report)
    assert exc.value.report is report


def test_ac_l7_direct_copy_is_reported_not_scored_or_blocking() -> None:
    configs = _configs()
    criteria = {
        "ps4": (1, "Independent ClinVar submitters."),
        "pp5": (1, "Reported in ClinVar."),
        "bp6": (1, "Reported benign in ClinVar."),
    }
    report = audit_lineage([_record("direct", criteria)], **configs)

    assert report.blocked is False
    assert set(report.blocking_criteria) == set()
    for criterion in ("PS4", "PP5", "BP6"):
        item = _item(report, criterion)
        assert item.total_fired == 1
        assert item.would_be_scored is False
        assert item.disposition == "forbidden"
    enforce_lineage(report)


def test_cp1_registry_drift_is_rejected_before_report_and_direct_copy_stays_unscored() -> None:
    """CP-1: `combine.implied_direction`'s scored set is the sole
    would-be-scored predicate; `audit_lineage` must agree and never
    diverge. A scorer registry that smuggles a direct-copy criterion
    (PS4) into `included_criteria` without also declaring it in
    `eval_config.automatable_criteria` is a registry drift -- `audit_lineage`
    must call `assert_registry_consistency` and raise before it ever builds
    a report (never silently deriving `would_be_scored` from the corrupted
    `included_criteria`)."""
    configs = _configs()
    drifty_scorer_config = replace(
        configs["scorer_config"],
        included_criteria=tuple(configs["scorer_config"].included_criteria) + ("PS4",),
    )
    drifted_configs = {**configs, "scorer_config": drifty_scorer_config}

    with pytest.raises(LineageRegistryMismatchError) as exc:
        audit_lineage(
            [_record("drift", {"ps4": (1, "Independent ClinVar submitters.")})],
            **drifted_configs,
        )
    assert "included_automatable_drift" in exc.value.sets_by_kind

    # With the well-formed (non-drifted) registries, the direct-copy
    # criterion is never would-be-scored -- because it is absent from
    # `eval_config.automatable_criteria` (and separately forbidden), not
    # because of anything read off the scorer's `included_criteria`.
    assert "PS4" not in {
        str(c).strip().upper() for c in configs["eval_config"].automatable_criteria
    }
    report = audit_lineage(
        [_record("direct", {"ps4": (1, "Independent ClinVar submitters.")})], **configs
    )
    item = _item(report, "PS4")
    assert item.would_be_scored is False
    assert report.blocked is False
    enforce_lineage(report)


def test_ac_l6_l8_deferred_ps3_bs2_are_reported_not_scored() -> None:
    configs = _configs()
    report = audit_lineage(
        [_record("deferred", {"ps3": (1, "AVADA result."), "bs2": (1, "Controls.")})],
        **configs,
    )

    assert report.blocked is False
    for criterion in ("PS3", "BS2"):
        item = _item(report, criterion)
        assert item.total_fired == 1
        assert item.would_be_scored is False
        assert item.disposition == "deferred"
    enforce_lineage(report)


@pytest.mark.parametrize("criterion", ["zz99", "pm3"])
def test_ac_l9_unknown_or_stub_supplemental_firing_blocks(criterion: str) -> None:
    configs = _configs()
    report = audit_lineage(
        [_record(criterion, {criterion: (1, "Supplemental external call.")})],
        **configs,
    )

    assert report.blocked is True
    assert criterion.upper() in report.blocking_criteria
    with pytest.raises(LineageGateError):
        enforce_lineage(report)


def test_ac_l10_incidence_does_not_establish_lineage() -> None:
    configs = _configs()
    first = _record("first", {"bs1": (1, "Population evidence.")})
    second = _record("second", {"ba1": (1, "Population evidence.")})
    report = audit_lineage([first, second], **configs)
    permuted = audit_lineage([second, first], **configs)
    duplicated = audit_lineage([first, second, first], **configs)

    assert report.content_hash() == permuted.content_hash()
    assert report.blocked is False
    assert duplicated.blocked is False
    for item in report.items:
        duplicate_item = _item(duplicated, item.criterion)
        assert duplicate_item.lineage_class == item.lineage_class
        assert duplicate_item.disposition == item.disposition
        assert duplicate_item.would_be_scored == item.would_be_scored
    assert _item(duplicated, "BS1").total_fired == 2


@pytest.mark.parametrize(
    ("criterion", "expected_exit"),
    [("BS1", 0), ("PS1", 1)],
)
def test_ac_l11_cli_persists_and_prints_same_report(
    tmp_path: Path, criterion: str, expected_exit: int
) -> None:
    _configs()
    tsv_path = tmp_path / f"{criterion}.tsv"
    report_path = tmp_path / f"{criterion}.report.json"
    _write_tsv(tsv_path, criterion, "No label-side input.")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path("src").resolve()), env.get("PYTHONPATH", "")]
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/bias_lineage_audit.py",
            str(tsv_path),
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == expected_exit
    assert report_path.is_file()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    printed = json.loads(result.stdout)
    assert printed == persisted
    assert persisted["blocked"] is (expected_exit != 0)
