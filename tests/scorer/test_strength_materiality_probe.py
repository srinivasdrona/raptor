"""Tests for the label-free strength-policy materiality probe (track
`strength-policy-2026-07`). Uses a small, synthetic, in-memory BIAS TSV
(never the real 6,618-VUS corpus) so results are deterministic and the
test never depends on `D:\\AIProjects\\raptor-data`.

Confirms: (1) out-of-vocab tallying is correct against the real ladder +
real scorer vocab, (2) the report never includes a per-variant identity
key (chromosome/position/ref/alt/variant_id) at any level, (3) the
"effective" view is 100% manual under the real, unapproved policy, and
(4) the hypothetical `recommended_scenario` view is clearly separate and
never mutates the real, persisted policy file.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from raptor.scorer.strength_materiality import compute_materiality, load_materiality_inputs

_HEADER = [
    "chromosome", "position", "refAllele", "altAllele", "variantType", "consequence",
    "acmgClassification", "alleleFreq", "hgvsg", "hgvsc", "hgvsp", "aaChange", "geneName",
    "pubmedIds", "associatedDiseases", "dbSnpids", "transcript", "rationale",
]


def _rationale(**fired) -> str:
    body: dict = {}
    for criterion_key, score in fired.items():
        body.setdefault(criterion_key[:2], {})[criterion_key] = [score, "synthetic"]
    return json.dumps(body)


def _write_tsv(tmp_path: Path) -> Path:
    rows = [
        # TSC2 missense: PS1 out-of-vocab (moderate), PM2 in-vocab (moderate) -- not tallied.
        ["17", "100", "A", "G", "SNV", "missense_variant", "Uncertain_significance", "0.0001",
         "g.100A>G", "c.1A>G", "p.M1V", "M1V", "TSC2", "", "", "", "NM_000548.5",
         _rationale(ps1=2, pm2=2)],
        # TSC1 frameshift (truncating): PM4 out-of-vocab (strong -> cap moderate), BS1 out-of-vocab (supporting).
        ["9", "200", "C", "T", "SNV", "frameshift_variant", "Uncertain_significance", "0.0001",
         "g.200C>T", "c.2C>T", "p.fs", "fs", "TSC1", "", "", "", "NM_000368.5",
         _rationale(pm4=3, bs1=1)],
        # TSC2 missense: no out-of-vocab firing at all (BP4 supporting is in-vocab) -- must not be "affected".
        ["17", "300", "G", "A", "SNV", "missense_variant", "Uncertain_significance", "0.0001",
         "g.300G>A", "c.3G>A", "p.V3M", "V3M", "TSC2", "", "", "", "NM_000548.5",
         _rationale(bp4=1)],
    ]
    path = tmp_path / "synthetic.bias_output.tsv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(_HEADER)
        writer.writerows(rows)
    return path


def test_materiality_probe_tallies_out_of_vocab_calls_only(tmp_path):
    tsv_path = _write_tsv(tmp_path)
    inputs = load_materiality_inputs()
    report = compute_materiality(tsv_path, inputs)

    assert report["corpus"]["total_rows"] == 3
    assert report["corpus"]["affected_rows"] == 2

    out_of_vocab = report["out_of_vocab_emitted_by_criterion_strength"]
    assert out_of_vocab["PS1"] == {"moderate": 1}
    assert out_of_vocab["PM4"] == {"strong": 1}
    assert out_of_vocab["BS1"] == {"supporting": 1}
    assert "PM2" not in out_of_vocab  # PM2-moderate is in-vocab -- never tallied
    assert "BP4" not in out_of_vocab  # BP4-supporting is in-vocab -- row 3 is unaffected


def test_materiality_probe_effective_view_is_fully_manual_while_unapproved():
    inputs = load_materiality_inputs()
    assert inputs.policy.is_active is False


def test_materiality_probe_report_has_no_per_variant_identity(tmp_path):
    tsv_path = _write_tsv(tmp_path)
    inputs = load_materiality_inputs()
    report = compute_materiality(tsv_path, inputs)

    rendered = json.dumps(report)
    forbidden_substrings = ('"chromosome"', '"position"', '"refAllele"', '"altAllele"', '"variant_id"', "17:100", "9:200")
    for needle in forbidden_substrings:
        assert needle not in rendered


def test_materiality_probe_recommended_scenario_is_clearly_hypothetical_and_read_only(tmp_path):
    tsv_path = _write_tsv(tmp_path)
    inputs = load_materiality_inputs()
    real_status_before = inputs.policy.status
    real_owner_approved_before = inputs.policy.owner_approved

    report = compute_materiality(tsv_path, inputs)

    # The hypothetical scenario must not mutate the loaded, real policy object.
    assert inputs.policy.status == real_status_before
    assert inputs.policy.owner_approved == real_owner_approved_before

    scenario = report["recommended_scenario"]
    assert "hypothetical" in scenario["description"].lower()
    assert "not active" in scenario["description"].lower() or "never" in scenario["description"].lower()
    # PM4-strong recommends cap; PS1-moderate/BS1-supporting have no valid accept/cap
    # target even under the recommended metadata -- must stay manual.
    assert scenario["by_criterion_strength"]["PM4"] == {"cap": 1}
    assert scenario["by_criterion_strength"]["PS1"] == {"manual": 1}
    assert scenario["by_criterion_strength"]["BS1"] == {"manual": 1}


def test_materiality_probe_is_deterministic(tmp_path):
    tsv_path = _write_tsv(tmp_path)
    inputs = load_materiality_inputs()
    first = compute_materiality(tsv_path, inputs)
    second = compute_materiality(tsv_path, inputs)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
