"""raptor.census.strata — packet-free census-selection core (ADR-0012 D1).

Extracted VERBATIM from `scripts/build_tsc_calibration_batch.py`:
`ManifestEntry`, `StratumEntry`, `STRENGTH_MAP`, `ManifestError`,
`ConservationError`, `load_manifest`, `reproduce_census_strata`, and the
consequence-grouping helpers (`_split_consequence_terms`, `_variant_class_for`).
This module imports only `raptor.scorer` + `raptor.eval` -- NEVER
`raptor.packet` (D1/P7): the census path must never make packet code
authoritative.

`reproduce_census_strata` additionally enforces an EXACT one-to-one
manifest<->BIAS-row join in both directions: a BIAS row with no manifest
entry fails loud (as before), and a manifest entry with no matching BIAS
row now ALSO fails loud (tightened invalid-input conservation -- both
missing and extra manifest/BIAS keys fail closed).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from raptor.eval.combine import implied_direction
from raptor.eval.config import EvalConfig
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.parse import parse_rationale

#: The eval-only, non-authoritative basis token recorded on every reproduced
#: `StratumEntry` (CAL-AC7). `implied_direction` is used only to reproduce the
#: already-recorded census selection stratum -- never a production policy.
BASIS = "eval_only_census_selection_metadata"

#: STRENGTH-LABELING PIN: the generic BIAS fired-int -> RAPTOR strength-vocab
#: convention (1..5), exactly `configs/acmg/tsc.yaml::strength_map`.
#: `reproduce_census_strata` asserts the injected `ScorerConfig.strength_map`
#: matches this pin exactly -- any drift is a blocker, never a silent re-label.
STRENGTH_MAP: Mapping[str, str] = {
    "1": "supporting",
    "2": "moderate",
    "3": "strong",
    "4": "very_strong",
    "5": "stand_alone",
}

#: SO consequence terms that resolve to the `truncating` variant class.
_TRUNCATING_CONSEQUENCE_TERMS = frozenset({
    "frameshift_variant",
    "stop_gained",
    "stop_lost",
    "start_lost",
    "splice_donor_variant",
    "splice_acceptor_variant",
    "transcript_ablation",
})

#: SO consequence terms that resolve to the `missense` variant class.
_MISSENSE_CONSEQUENCE_TERMS = frozenset({"missense_variant", "protein_altering_variant"})

_VALID_STRATA = frozenset({
    "candidate_LP_review",
    "candidate_LB_review",
    "no_deterministic_resolution",
    "manual_review",
})

_VARIANT_ID_RE = re.compile(r"^[^:]+:[0-9]+:[ACGTN]*:[ACGTN]*$")
_VCF_KEY_RE = re.compile(r"^[^:]+:[0-9]+:[ACGTN]+:[ACGTN]+$")


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------
# Typed failures
# --------------------------------------------------------------------------


class ConservationError(RuntimeError):
    """The reproduced strata / manifest / BIAS rows no longer conserve the
    exact identity/row/join invariants -- raised before any output."""


class ManifestError(ValueError):
    """A `configs`/raptor-data manifest row fails strict `ManifestEntry`
    validation, or the manifest carries a duplicate `variant_id`/`vcf_key`."""


# --------------------------------------------------------------------------
# 0. Exact input value objects
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestEntry:
    """One strict manifest identity row: `variant_id` is the canonical GRCh38
    SPDI; `vcf_key` (`chr:pos:ref:alt`) is the exact BIAS raw-row join key."""

    variant_id: str
    vcf_key: str

    def __post_init__(self) -> None:
        if not _VARIANT_ID_RE.fullmatch(self.variant_id or ""):
            raise ManifestError(f"ManifestEntry.variant_id is not a canonical SPDI: {self.variant_id!r}")
        if not _VCF_KEY_RE.fullmatch(self.vcf_key or ""):
            raise ManifestError(f"ManifestEntry.vcf_key is not chr:pos:ref:alt: {self.vcf_key!r}")


@dataclass(frozen=True)
class StratumEntry:
    """One reproduced census-selection stratum row (eval-only -- never a
    production candidate direction)."""

    variant_id: str
    stratum: str
    pattern_id: str
    pattern_signature: tuple[str, ...]
    signed_points: int
    basis: str

    def __post_init__(self) -> None:
        if not _non_blank(self.variant_id):
            raise ValueError("StratumEntry.variant_id must be non-blank")
        if self.stratum not in _VALID_STRATA:
            raise ValueError(f"StratumEntry.stratum must be one of {sorted(_VALID_STRATA)!r}")
        object.__setattr__(self, "pattern_signature", tuple(self.pattern_signature))
        if isinstance(self.signed_points, bool) or not isinstance(self.signed_points, int):
            raise ValueError("StratumEntry.signed_points must be an int")
        if self.basis != BASIS:
            raise ValueError(f"StratumEntry.basis must be {BASIS!r}; got {self.basis!r}")


def load_manifest(path: str | Path) -> tuple[ManifestEntry, ...]:
    """Strictly parse the `raptor-data` manifest JSONL (one `{variant_id,
    vcf_key, ...}` object per line); rejects a duplicate `variant_id` or
    `vcf_key` (never silently deduplicated)."""
    entries: list[ManifestEntry] = []
    seen_variant_ids: set[str] = set()
    seen_vcf_keys: set[str] = set()
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            raw = json.loads(line)
            entry = ManifestEntry(variant_id=str(raw["variant_id"]), vcf_key=str(raw["vcf_key"]))
            if entry.variant_id in seen_variant_ids:
                raise ManifestError(f"manifest line {line_no}: duplicate variant_id {entry.variant_id!r}")
            if entry.vcf_key in seen_vcf_keys:
                raise ManifestError(f"manifest line {line_no}: duplicate vcf_key {entry.vcf_key!r}")
            seen_variant_ids.add(entry.variant_id)
            seen_vcf_keys.add(entry.vcf_key)
            entries.append(entry)
    return tuple(entries)


# --------------------------------------------------------------------------
# 1. Census-stratum reproduction (eval-only, packet-free)
# --------------------------------------------------------------------------


def reproduce_census_strata(
    bias_rows: Sequence[BiasRecord],
    manifest_by_vcf_key: Mapping[str, ManifestEntry],
    scorer_config: ScorerConfig,
    eval_config: EvalConfig,
) -> tuple[StratumEntry, ...]:
    """Join each BIAS row to its canonical SPDI (exact `vcf_key` join), score
    only `eval_config.automatable_criteria` via the eval-only
    `implied_direction` combiner, and map the implied call to the recorded
    census stratum token. NTHL1-annotated rows are pre-routed to
    `manual_review` and never scored (never enter LP/LB).

    Conserves an EXACT one-to-one join: a BIAS row with no manifest entry,
    or a manifest entry with no matching BIAS row, both fail loud with
    `ConservationError` before any stratum is returned.
    """
    if dict(scorer_config.strength_map) != dict(STRENGTH_MAP):
        raise ConservationError(
            "scorer_config.strength_map does not match the pinned strength-labeling tuple "
            f"required to reproduce the census pattern catalog: expected {dict(STRENGTH_MAP)!r}, "
            f"got {dict(scorer_config.strength_map)!r}"
        )

    automatable = frozenset(str(c).strip().upper() for c in eval_config.automatable_criteria)

    entries: list[StratumEntry] = []
    consumed_vcf_keys: set[str] = set()
    for row in bias_rows:
        manifest_entry = manifest_by_vcf_key.get(row.variant_id)
        if manifest_entry is None:
            raise ConservationError(
                f"BIAS row {row.variant_id!r} has no manifest entry (vcf_key join miss)"
            )
        consumed_vcf_keys.add(row.variant_id)
        variant_id = manifest_entry.variant_id

        if row.gene_name == "NTHL1":
            entries.append(
                StratumEntry(
                    variant_id=variant_id,
                    stratum="manual_review",
                    pattern_id="",
                    pattern_signature=(),
                    signed_points=0,
                    basis=BASIS,
                )
            )
            continue

        all_calls = parse_rationale(row.criteria, STRENGTH_MAP)
        automatable_calls = [call for call in all_calls if call.criterion in automatable]
        implied = implied_direction(
            [(call.criterion, call.strength, call.direction) for call in automatable_calls],
            eval_config,
        )

        if implied.implied == "LP":
            stratum = "candidate_LP_review"
        elif implied.implied == "LB":
            stratum = "candidate_LB_review"
        else:
            stratum = "no_deterministic_resolution"

        if stratum in ("candidate_LP_review", "candidate_LB_review"):
            signature = tuple(sorted(
                f"{call.criterion} {call.strength.replace('_', ' ').title()}"
                for call in automatable_calls
            ))
            pattern_id = "|".join(signature)
        else:
            signature = ()
            pattern_id = ""

        entries.append(
            StratumEntry(
                variant_id=variant_id,
                stratum=stratum,
                pattern_id=pattern_id,
                pattern_signature=signature,
                signed_points=implied.points,
                basis=BASIS,
            )
        )

    extra_vcf_keys = set(manifest_by_vcf_key.keys()) - consumed_vcf_keys
    if extra_vcf_keys:
        sample = sorted(extra_vcf_keys)[:5]
        raise ConservationError(
            f"manifest has {len(extra_vcf_keys)} extra entry/entries with no matching BIAS row "
            f"(exact one-to-one locus join failed): {sample!r}"
        )

    return tuple(entries)


# --------------------------------------------------------------------------
# 2. Consequence-grouping helpers
# --------------------------------------------------------------------------


def _split_consequence_terms(consequence: str) -> tuple[str, ...]:
    """Split a raw BIAS `consequence` cell on `,` and strip surrounding
    whitespace only -- every raw SO token is preserved verbatim (exact case,
    no spelling/lowercasing/re-encoding)."""
    return tuple(
        stripped for term in consequence.split(",") if (stripped := term.strip())
    )


def _variant_class_for(consequence: str) -> str:
    terms = set(_split_consequence_terms(consequence))
    if terms & _TRUNCATING_CONSEQUENCE_TERMS:
        return "truncating"
    if terms & _MISSENSE_CONSEQUENCE_TERMS:
        return "missense"
    return "other"
