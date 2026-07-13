"""Tests for `configs/eval/bias_strength_ladder.yaml` — the real,
committed machine-readable ladder (track `strength-policy-2026-07`).

Asserts the file loads under the real `load_strength_ladder` loader and
that its content matches the reachable-strength facts this track's source
audit of pinned BIAS-3.0.0 (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`)
established -- a drift here (accidental edit) would silently change what
counts as "in-vocab"/"out-of-vocab" for every downstream reconciliation.
"""
from __future__ import annotations

from raptor.scorer.strength_policy import load_strength_ladder

LADDER_PATH = "configs/eval/bias_strength_ladder.yaml"


def test_bias_strength_ladder_loads_and_pins_bias_version():
    ladder = load_strength_ladder(LADDER_PATH)
    assert ladder.bias_version == "3.0.0"
    assert ladder.bias_commit == "ade13f206f3e2c2efe3ec92715d974645fc8da8f"


def test_bias_strength_ladder_matches_source_audit():
    ladder = load_strength_ladder(LADDER_PATH)
    expected = {
        "PS1": ("moderate",),
        "PM2": ("supporting", "moderate", "strong"),
        "PM4": ("supporting", "moderate", "strong"),
        "PM5": ("supporting", "moderate", "strong"),
        "BP3": ("supporting", "strong"),
        "BP4": ("supporting", "strong", "very_strong"),
        "BS1": ("supporting", "strong"),
    }
    assert dict(ladder.criteria) == expected


def test_bias_strength_ladder_ps1_has_no_moderate_free_lunch():
    """PS1's dead-code finding (pathogenic_classifiers.get_ps1 L179-187):
    only `moderate` is reachable -- `strong`/`supporting` must never
    appear, since that would silently contradict the source audit this
    ladder is supposed to encode."""
    ladder = load_strength_ladder(LADDER_PATH)
    assert ladder.criteria["PS1"] == ("moderate",)
    assert "strong" not in ladder.criteria["PS1"]
    assert "supporting" not in ladder.criteria["PS1"]


def test_bias_strength_ladder_no_criterion_has_moderate_and_bp3_bp4_bs1_missing_it():
    """BP3/BP4/BS1 (benign_classifiers.py) each structurally skip
    `moderate` at this pinned commit -- confirm the ladder never lists it
    for these three criteria."""
    ladder = load_strength_ladder(LADDER_PATH)
    for criterion in ("BP3", "BP4", "BS1"):
        assert "moderate" not in ladder.criteria[criterion]
