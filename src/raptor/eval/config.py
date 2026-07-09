"""PRD-06 sec 10.2/10.3 `config.py` — the frozen eval-harness config.

`EvalConfig` pins the Tavtigian-2018 point system, category cutoffs,
min-count-per-class rule, the split seed, the (initially empty) Oracle
threshold block, and the labels snapshot id -- nothing hardcoded (GP-6).
`load_config` schema-validates a `configs/eval/*.yaml` file and raises
loudly (`ConfigError`, a `ValueError`) on a missing/blank required pin --
including an EMPTY `labels_snapshot` (GP-9): an empty `oracle_thresholds`
block is legitimate (AC5/H13 -- the gate must then read `UNVERIFIED`), but
an empty *labels_snapshot* is a provenance breach, not a policy choice.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

#: Top-level keys every eval config must define (PRD-06 sec 10.2).
_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "automatable_criteria",
    "tavtigian_points",
    "tavtigian_cutoffs",
    "min_count_per_class",
    "split",
    "oracle_thresholds",
    "labels_snapshot",
)

#: Required Tavtigian point-strength keys (PRD-06 sec 10.2). `stand_alone` is
#: required too -- BA1 uses it, so a config missing it must fail loud at
#: load time, never a `KeyError` deep in the combiner at runtime.
_REQUIRED_POINT_KEYS: tuple[str, ...] = ("supporting", "moderate", "strong", "very_strong", "stand_alone")

#: Whitelist of metric names an `oracle_thresholds` key may name (sec 10.3 --
#: `gate.py` only ever reads these off a `Metrics` instance). Any other key
#: is a bogus/laundered pin and must never reach the gate (BLOCKER 1).
_ORACLE_METRIC_KEYS: frozenset[str] = frozenset({"precision", "recall", "concordance"})

#: Required Tavtigian category-cutoff keys (PRD-06 sec 10.2/AC1).
_REQUIRED_CUTOFF_KEYS: tuple[str, ...] = (
    "pathogenic_min",
    "likely_pathogenic_min",
    "vus_min",
    "vus_max",
    "likely_benign_max",
    "benign_max",
)

#: PP5/BP6 derive from ClinVar assertions themselves (R-A2 circularity) --
#: structurally forbidden from `automatable_criteria` at load time, never
#: merely absent-by-convention (MAJOR-2).
FORBIDDEN_CRITERIA: frozenset[str] = frozenset({"PP5", "BP6"})

#: The exact canonical ACMG/AMP-2015 code set (28 codes). `strip().upper()`
#: alone does not remove hidden/internal whitespace (e.g. a zero-width space
#: `'\u200b'` is not `str.isspace()` in Python, so `'PP5\u200b'.strip()` is a
#: no-op) or reject a malformed/unknown code (`'P P5'`, `'ZZZ'`) -- such a
#: code must never be treated as automatable. Every criterion code, at
#: config-load time and at combine time, is validated against this exact
#: set (round-6 BLOCKER). Note PP5/BP6 ARE valid canonical codes -- they
#: remain separately banned via `FORBIDDEN_CRITERIA`.
VALID_CRITERIA: frozenset[str] = frozenset({
    "PVS1",
    "PS1", "PS2", "PS3", "PS4",
    "PM1", "PM2", "PM3", "PM4", "PM5", "PM6",
    "PP1", "PP2", "PP3", "PP4", "PP5",
    "BA1",
    "BS1", "BS2", "BS3", "BS4",
    "BP1", "BP2", "BP3", "BP4", "BP5", "BP6", "BP7",
})


class ConfigError(ValueError):
    """Raised on a missing/blank/malformed required eval-config pin (FR9)."""


def _require(mapping: Mapping[str, Any], key: str, *, ctx: str = "") -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required config key: {ctx}{key!r}")
    value = mapping[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"config key {ctx}{key!r} must not be blank")
    return value


@dataclass(frozen=True)
class EvalConfig:
    """Frozen, schema-validated PRD-06 eval config (sec 10.6: tests build
    variants via a factory -- `make_eval_config(**overrides)` -- never
    mutate an instance)."""

    automatable_criteria: Any  # list[str]
    tavtigian_points: Mapping[str, int]  # strength -> point magnitude
    tavtigian_cutoffs: Mapping[str, int]  # category cutoff name -> int
    min_count_per_class: int
    split: Mapping[str, Any]  # {"seed": int, "holdout_fraction": float}
    oracle_thresholds: Mapping[str, float]  # metric -> threshold; EMPTY until GP-3
    labels_snapshot: str
    #: PRD-07 sec 10.2/10.3 -- optional real sha256 pin for the ClinVar
    #: `variant_summary` snapshot the labels come from (benchmark-source
    #: provenance, co-located with `labels_snapshot`). Default "" means
    #: unpinned (no checksum guard); a non-hex-64 placeholder is likewise
    #: treated as unpinned (see `knowns.LabeledVariantReader`).
    clinvar_snapshot_file_checksum: str = ""


def _validate_points(points: Any) -> None:
    if not isinstance(points, dict):
        raise ConfigError("`tavtigian_points` must be a mapping")
    for key in _REQUIRED_POINT_KEYS:
        if key not in points:
            raise ConfigError(f"`tavtigian_points` missing required strength {key!r}")


def _validate_cutoffs(cutoffs: Any) -> None:
    if not isinstance(cutoffs, dict):
        raise ConfigError("`tavtigian_cutoffs` must be a mapping")
    for key in _REQUIRED_CUTOFF_KEYS:
        if key not in cutoffs:
            raise ConfigError(f"`tavtigian_cutoffs` missing required cutoff {key!r}")


def _validate_split(split: Any) -> None:
    if not isinstance(split, dict) or "seed" not in split or "holdout_fraction" not in split:
        raise ConfigError("`split` must be a mapping with `seed` and `holdout_fraction`")

    seed = split["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigError(f"`split.seed` must be an int, got {seed!r}")

    frac = split["holdout_fraction"]
    if isinstance(frac, bool) or not isinstance(frac, (int, float)):
        raise ConfigError(f"`split.holdout_fraction` must be a real number, got {frac!r}")
    frac = float(frac)
    if not math.isfinite(frac) or not (0.0 < frac < 1.0):
        raise ConfigError(
            f"`split.holdout_fraction` must be strictly between 0.0 and 1.0 (open interval), got {frac!r}"
        )


#: When `oracle_thresholds` is non-empty it MUST pin both of these metrics
#: (BLOCKER 1) -- concordance alone (or precision/recall alone) is a
#: cherry-picked, launderable gating target and must fail loud at load time,
#: never reach the gate.
_ORACLE_REQUIRED_METRIC_KEYS: frozenset[str] = frozenset({"precision", "recall"})


def _validate_oracle_thresholds(thresholds: Any) -> None:
    if not isinstance(thresholds, dict):
        raise ConfigError("`oracle_thresholds` must be a mapping (may be empty)")
    for key, value in thresholds.items():
        if key not in _ORACLE_METRIC_KEYS:
            raise ConfigError(
                f"`oracle_thresholds` key {key!r} is not a known metric "
                f"(must be one of {sorted(_ORACLE_METRIC_KEYS)})"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"`oracle_thresholds[{key!r}]` must be a real number, got {value!r}")
        value = float(value)
        if not math.isfinite(value) or not (0.0 < value <= 1.0):
            raise ConfigError(
                f"`oracle_thresholds[{key!r}]` must be a finite, strictly positive value in "
                f"(0.0, 1.0] -- 0.0/negative authorizes on zero performance, got {value!r}"
            )
    if thresholds:
        missing = _ORACLE_REQUIRED_METRIC_KEYS - thresholds.keys()
        if missing:
            raise ConfigError(
                "`oracle_thresholds` is non-empty and must pin both `precision` and "
                f"`recall` (concordance is optional-additional); missing: {sorted(missing)}"
            )


def load_config(path: str | Path) -> EvalConfig:
    """Load + schema-validate a `configs/eval/*.yaml` file (FR9).

    Raises `ConfigError` on any missing/blank required pin. `oracle_thresholds`
    is validated as present but MAY be an empty mapping (`{}`) -- that is the
    honest pre-Oracle state (AC5/H13), never an error.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

    for key in _REQUIRED_TOP_KEYS:
        if key == "oracle_thresholds":
            # legitimately empty (AC5) -- only check presence + mapping type,
            # not blank/None (an explicit {} must not raise).
            if key not in raw or raw[key] is None:
                raise ConfigError(f"missing required config key: {key!r}")
            continue
        _require(raw, key)

    automatable_criteria = raw["automatable_criteria"]
    if not isinstance(automatable_criteria, list) or not automatable_criteria:
        raise ConfigError("`automatable_criteria` must be a non-empty list")
    # MAJOR-1 / round-5: canonicalize to `strip().upper()` before the ban check
    # (and for storage) -- a lowercase 'pp5', a trailing-space 'PP5 ', or a
    # tab 'pp5\t' is still PP5 and must not bypass the structural R-A2 ban via
    # casing OR whitespace. A blank/whitespace-only code is malformed -> fail loud.
    normalized_criteria = [str(c).strip().upper() for c in automatable_criteria]
    # round-6 BLOCKER: `strip().upper()` alone does not remove hidden/internal
    # whitespace (e.g. a zero-width space is not `str.isspace()`) or reject a
    # malformed/unknown code -- validate against the exact canonical ACMG-2015
    # code set. This subsumes the old blank-code check (a blank string is
    # never in `VALID_CRITERIA`).
    non_canonical = [c for c in normalized_criteria if c not in VALID_CRITERIA]
    if non_canonical:
        raise ConfigError(
            "`automatable_criteria` contains a code that is not a canonical ACMG-2015 "
            f"code: {sorted(set(non_canonical))!r}"
        )
    forbidden_present = FORBIDDEN_CRITERIA.intersection(normalized_criteria)
    if forbidden_present:
        raise ConfigError(
            "`automatable_criteria` lists ClinVar-circular criteria that are "
            f"structurally forbidden (R-A2): {sorted(forbidden_present)}"
        )

    _validate_points(raw["tavtigian_points"])
    _validate_cutoffs(raw["tavtigian_cutoffs"])
    _validate_split(raw["split"])

    oracle_thresholds = raw["oracle_thresholds"]
    _validate_oracle_thresholds(oracle_thresholds)

    min_count = raw["min_count_per_class"]
    if not isinstance(min_count, int) or isinstance(min_count, bool) or min_count < 1:
        raise ConfigError("`min_count_per_class` must be a positive int (>= 1) -- 0 disables the FR5 floors")

    return EvalConfig(
        automatable_criteria=normalized_criteria,
        tavtigian_points={str(k): int(v) for k, v in raw["tavtigian_points"].items()},
        tavtigian_cutoffs={str(k): int(v) for k, v in raw["tavtigian_cutoffs"].items()},
        min_count_per_class=int(min_count),
        split=dict(raw["split"]),
        oracle_thresholds={str(k): float(v) for k, v in oracle_thresholds.items()},
        labels_snapshot=str(raw["labels_snapshot"]),
        clinvar_snapshot_file_checksum=str(raw.get("clinvar_snapshot_file_checksum", "") or ""),
    )
