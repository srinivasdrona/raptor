"""PRD-06 checker round-5 finding: the PP5/BP6 ClinVar-circularity ban must be robust
to WHITESPACE, not only casing.

`"PP5 "` (trailing space) uppercases to `"PP5 "` which != `"PP5"`, so it bypassed BOTH
the config ban and the combiner skip -- laundering a circular ClinVar signal into a
PASS. The canonical form must be `strip().upper()` everywhere, and a blank/whitespace-
only code must fail loud.
"""
from __future__ import annotations

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from conftest import make_eval_config


def _valid_raw() -> dict:
    return {
        "automatable_criteria": ["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        "tavtigian_points": {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8},
        "tavtigian_cutoffs": {"pathogenic_min": 10, "likely_pathogenic_min": 6, "vus_min": 0,
                              "vus_max": 5, "likely_benign_max": -1, "benign_max": -7},
        "min_count_per_class": 10,
        "split": {"seed": 42, "holdout_fraction": 0.3},
        "oracle_thresholds": {},
        "labels_snapshot": "clinvar_2026-07-01",
    }


def _write_config(tmp_path, **overrides) -> str:
    raw = _valid_raw()
    raw.update(overrides)
    p = tmp_path / "eval.yaml"
    p.write_text(yaml.safe_dump(raw))
    return str(p)


def test_config_forbids_circular_criteria_with_whitespace(tmp_path):
    """'PP5 ' / ' BP6' / 'pp5\\t' all canonicalize to a forbidden code -- the R-A2 ban
    must strip whitespace as well as normalize case."""
    for bad in (["PVS1", "PM2", "PP5 "], ["PVS1", "PM2", " BP6"], ["PVS1", "PM2", "pp5\t"]):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, automatable_criteria=bad))


def test_config_rejects_blank_criterion(tmp_path):
    """A blank/whitespace-only criterion code is malformed and must fail loud at load."""
    for bad in (["PVS1", "  "], ["PVS1", ""]):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, automatable_criteria=bad))


def test_combiner_never_scores_whitespace_forbidden():
    """Even a trailing-whitespace PP5/BP6 that a hand-built config lists in
    `automatable_criteria` must never be scored (the R-A2 ban is whitespace- AND
    case-insensitive)."""
    cfg = make_eval_config(automatable_criteria=["PVS1", "PM2", "PP5 ", "BP6 "])
    assert implied_direction([("PP5 ", "strong", "pathogenic")], cfg).points == 0
    assert implied_direction([("BP6 ", "strong", "benign")], cfg).points == 0
