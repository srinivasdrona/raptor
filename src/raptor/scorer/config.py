"""PRD-01 sec 10.3/10.4 `config.py` — FR7/AC7: policy + pins, nothing re-derived.

`ScorerConfig` is policy + pins over BIAS's own output (`bias_version`/
`bias_data_version` pin the arm's-length engine + its data, R-A11);
`acmg_criteria` is the generic ACMG rule vocabulary (criterion -> direction
+ allowed KB strengths) that seeds `evidence_kinds` at runtime (see
`pipeline.run_scorer`) -- never a re-derivation of BIAS's thresholds.
`load_config` schema-validates a `configs/acmg/*.yaml` file and raises
loudly on a missing/blank required pin (GP-6).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

#: Top-level keys every scorer config must define (PRD-01 sec 10.3).
_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "bias_version",
    "bias_data_version",
    "included_criteria",
    "strength_map",
    "acmg_criteria",
    "edge_cases",
    "genes",
    "licensing",
)

#: The KB `evidence.strength`/`.direction` enums (PRD-01 sec 10.3, matches
#: migration 0001's CHECK constraints exactly -- `stand_alone`, not
#: "standalone").
VALID_STRENGTHS: frozenset[str] = frozenset(
    {"stand_alone", "very_strong", "strong", "moderate", "supporting"}
)
VALID_DIRECTIONS: frozenset[str] = frozenset({"pathogenic", "benign"})

#: ACMG code-family prefixes -> the only `direction` they may be configured
#: with (PRD-01 sec 10.7): pathogenic-family codes (PVS/PS/PM/PP) must be
#: `pathogenic`, benign-family codes (BA/BS/BP) must be `benign` -- else the
#: `evidence_kinds` registration (pipeline.py) and the emitted evidence
#: direction (parse.py) could diverge for the same criterion.
_PATHOGENIC_FAMILY_PREFIXES: tuple[str, ...] = ("PVS", "PS", "PM", "PP")
_BENIGN_FAMILY_PREFIXES: tuple[str, ...] = ("BA", "BS", "BP")


class ConfigError(ValueError):
    """Raised on a missing/blank required scorer config pin (FR7/AC7)."""


def _require(mapping: Mapping[str, Any], key: str, *, ctx: str = "") -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required config key: {ctx}{key!r}")
    value = mapping[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"config key {ctx}{key!r} must not be blank")
    return value


@dataclass(frozen=True)
class ScorerConfig:
    """Frozen, schema-validated PRD-01 scorer config (FR7)."""

    bias_version: str
    bias_data_version: str
    included_criteria: Any  # list[str] -- which BIAS criteria RAPTOR emits as evidence
    strength_map: Mapping[str, str]  # BIAS fired-int (as str) -> KB strength vocab
    acmg_criteria: Mapping[str, Mapping[str, Any]]  # criterion -> {direction, strength_vocab}
    edge_cases: Mapping[str, Any]  # predicate name -> enabled (FR8)
    genes: Mapping[str, str]  # gene -> pinned MANE transcript
    licensing: Mapping[str, str]  # predictor field -> licensing tag (R-B2)

    def pins_dict(self) -> dict[str, Any]:
        """A JSON-serializable snapshot of the run-identifying pins -- used
        as `config_pins` in manual-queue records (FR8) so a routing
        decision is reproducible."""
        return {
            "bias_version": self.bias_version,
            "bias_data_version": self.bias_data_version,
            "included_criteria": list(self.included_criteria),
        }


def _acmg_family_direction(criterion: str) -> str | None:
    """Map a criterion code to its required `direction` by ACMG family
    prefix, or `None` if the code doesn't match a known family (PRD-01
    sec 10.7 doesn't constrain codes outside the standard PVS/PS/PM/PP/
    BA/BS/BP families)."""
    for prefix in _PATHOGENIC_FAMILY_PREFIXES:
        if criterion.startswith(prefix):
            return "pathogenic"
    for prefix in _BENIGN_FAMILY_PREFIXES:
        if criterion.startswith(prefix):
            return "benign"
    return None


def _validate_acmg_criteria(acmg_criteria: Any) -> None:
    if not isinstance(acmg_criteria, dict) or not acmg_criteria:
        raise ConfigError("`acmg_criteria` must be a non-empty mapping")
    for criterion, spec in acmg_criteria.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"acmg_criteria[{criterion!r}] must be a mapping")
        direction = spec.get("direction")
        if direction not in VALID_DIRECTIONS:
            raise ConfigError(
                f"acmg_criteria[{criterion!r}].direction must be one of {sorted(VALID_DIRECTIONS)}"
            )
        expected_direction = _acmg_family_direction(criterion)
        if expected_direction is not None and direction != expected_direction:
            raise ConfigError(
                f"acmg_criteria[{criterion!r}].direction={direction!r} disagrees with its "
                f"ACMG family (expected {expected_direction!r}) -- evidence_kinds "
                "registration and emitted direction must not diverge (PRD-01 sec 10.7)"
            )
        vocab = spec.get("strength_vocab")
        if not isinstance(vocab, list) or not vocab or any(s not in VALID_STRENGTHS for s in vocab):
            raise ConfigError(
                f"acmg_criteria[{criterion!r}].strength_vocab must be a non-empty list "
                f"drawn from {sorted(VALID_STRENGTHS)}"
            )


def load_config(path: str | Path) -> ScorerConfig:
    """Load + schema-validate a `configs/acmg/*.yaml` file (FR7/AC7).

    Raises `ConfigError` (a `ValueError` subclass) on any missing/blank
    required pin, including a malformed `acmg_criteria` vocabulary entry.
    """
    # NOTE: `Path.read_text()`, not the builtin file-open call -- mirrors
    # `raptor.ingest.config.load_config` (this is legitimate config
    # loading, not the ad-hoc file I/O the KB-package ban targets).
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

    for key in _REQUIRED_TOP_KEYS:
        _require(raw, key)

    included_criteria = raw["included_criteria"]
    if not isinstance(included_criteria, list) or not included_criteria:
        raise ConfigError("`included_criteria` must be a non-empty list")

    strength_map = raw["strength_map"]
    if not isinstance(strength_map, dict) or not strength_map:
        raise ConfigError("`strength_map` must be a non-empty mapping")

    _validate_acmg_criteria(raw["acmg_criteria"])

    edge_cases = raw["edge_cases"]
    if not isinstance(edge_cases, dict):
        raise ConfigError("`edge_cases` must be a mapping")

    genes = raw["genes"]
    if not isinstance(genes, dict) or not genes:
        raise ConfigError("`genes` must be a non-empty mapping")

    licensing = raw["licensing"]
    if not isinstance(licensing, dict):
        raise ConfigError("`licensing` must be a mapping")

    return ScorerConfig(
        bias_version=str(raw["bias_version"]),
        bias_data_version=str(raw["bias_data_version"]),
        included_criteria=[str(c) for c in included_criteria],
        strength_map={str(k): str(v) for k, v in strength_map.items()},
        acmg_criteria={
            str(k): {
                "direction": str(v["direction"]),
                "strength_vocab": [str(s) for s in v["strength_vocab"]],
            }
            for k, v in raw["acmg_criteria"].items()
        },
        edge_cases=dict(edge_cases),
        genes={str(k): str(v) for k, v in genes.items()},
        licensing={str(k): str(v) for k, v in licensing.items()},
    )
