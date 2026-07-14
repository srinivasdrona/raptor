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

#: Gate-fidelity (Arm C, BREAKING nested-schema migration): the two ACMG
#: strata whose per-stratum threshold VALUES are Oracle-pre-registered
#: (`docs/EVAL_RUBRIC.md` §1) and therefore LOCKED -- a config that pins a
#: different value for a metric these name is rejected at load (R-A2
#: pre-registration; the `min_count_per_class` 35->36 power-floor correction
#: is the sole sanctioned exception, and it is NOT part of this per-stratum
#: value lock). `concordance` is not part of the nested per-stratum gating
#: schema at all -- precision/recall (both directions) are the only gated
#: metrics now (the old flat `concordance`-only threshold path is removed).
_PINNED_STRATUM_THRESHOLDS: Mapping[str, Mapping[str, float]] = {
    "missense": {"precision": 0.90, "recall": 0.85},
    "truncating": {"precision": 0.95, "recall": 0.95},
}

#: The gating stratum `decide_gate` binds on; a non-empty `oracle_thresholds`
#: block MUST define it (else it is functionally unset -- UNVERIFIED).
_REQUIRED_GATING_STRATUM = "missense"

#: The only directions a per-stratum `directions` list may name.
_VALID_DIRECTIONS: frozenset[str] = frozenset({"pathogenic", "benign"})

#: v2 scope-specific authorization gate (preregistration, additive):
#: `full_spectrum.requires` is semantics-locked to EXACTLY this pinned set
#: (anti-cherry-pick control, §3.6) -- a drift (dropping/adding/narrowing a
#: required scope after the fact) raises `ConfigError`. This is what a
#: "full-spectrum" VUS authorization means and it can never be quietly
#: narrowed post-hoc.
_PINNED_FULL_SPECTRUM_SCOPES: frozenset[str] = frozenset(
    {"missense:pathogenic", "missense:benign", "truncating:pathogenic"}
)

#: Checker finding 1 (research-scope mapping pin): the exact, closed set of
#: `research_scopes` keys a config may define, mapped to the EXACT
#: `requires` set each key must equal -- not merely a subset of registered
#: scopes. A renamed/additional/replacement research-scope key or a
#: widened/narrowed `requires` list would silently change what a research
#: scope authorizes, so both the key set AND each key's `requires` are
#: locked here (anti-cherry-pick / anti-retarget control, checked at
#: `load_config` time AND, defense-in-depth, again inside
#: `decide_scope_gate` for a hand-built `EvalConfig` that bypasses the
#: loader -- see `scope_gate._pinned_authorization_valid`).
_PINNED_RESEARCH_SCOPE_REQUIRES: Mapping[str, frozenset[str]] = {
    "truncating_pathogenic_research_scope_validated": frozenset({"truncating:pathogenic"}),
}

#: The 95% Clopper-Pearson confidence pinned in `tsc2.yaml` (R-A2
#: pre-registration) -- checked, defense-in-depth, against a hand-built
#: `EvalConfig.oracle_thresholds` inside `decide_scope_gate` (checker
#: finding 2) since such a config bypasses `_validate_oracle_thresholds`.
_PINNED_ORACLE_CONFIDENCE: float = 0.95

#: The user's exact governance statement, verbatim (never paraphrased/
#: reworded by a config author) -- the TRUNCATING_PATHOGENIC_ONLY state is
#: pinned because it is the one that could most easily be used to
#: over-claim (or under-claim) what the truncating-pathogenic-only research
#: scope authorizes.
_PINNED_TRUNCATING_PATHOGENIC_ONLY_STATEMENT = (
    "Full-spectrum VUS automation is not authorized. Evidence supports only "
    "the validated truncating-pathogenic scope; missense remains unvalidated."
)

#: Checker finding 1 (GPT-5.4): ALL THREE governance-state strings are
#: authorization surfaces, not just TRUNCATING_PATHOGENIC_ONLY -- pin
#: FULL_SPECTRUM and NONE_VALIDATED verbatim too so a config author cannot
#: quietly widen the FULL_SPECTRUM claim or weaken the most-restrictive
#: NONE_VALIDATED fallback statement.
_PINNED_FULL_SPECTRUM_STATEMENT = (
    "All pre-registered research scopes are validated for research-evidence "
    "use only; this authorizes no clinical classification, VUS worklist, or "
    "ClinVar submission."
)
_PINNED_NONE_VALIDATED_STATEMENT = (
    "Full-spectrum VUS automation is not authorized; no pre-registered "
    "research scope is currently validated."
)

#: Mandatory, non-blank, separate disclaimer (planner correction) -- kept
#: OUT of `governance_statement` (which stays the exact preregistered
#: string verbatim) and pinned to the exact safe text so a config author
#: cannot silently weaken it.
_PINNED_RESEARCH_USE_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical "
    "classification, VUS worklist, or ClinVar submission."
)

#: Checker finding 1 (GPT-5.4): the closed, exact map of all three
#: governance states to their pinned verbatim statement -- iterated by
#: `_validate_scope_authorization` (and cross-checked, defense-in-depth, by
#: `scope_gate._pinned_authorization_valid` for a hand-built `EvalConfig`).
_PINNED_GOVERNANCE_STATEMENTS: Mapping[str, str] = {
    "FULL_SPECTRUM": _PINNED_FULL_SPECTRUM_STATEMENT,
    "TRUNCATING_PATHOGENIC_ONLY": _PINNED_TRUNCATING_PATHOGENIC_ONLY_STATEMENT,
    "NONE_VALIDATED": _PINNED_NONE_VALIDATED_STATEMENT,
}

#: Checker finding 2 (GPT-5.4): the preregistered v2 min-count-per-class
#: floor is EXACTLY 36 (the 35->36 power-floor correction, see
#: `_PINNED_STRATUM_THRESHOLDS` above) -- once a config declares a v2
#: `scope_authorization` block, `min_count_per_class` must equal this
#: pinned value exactly (drift below OR above 36 is rejected). Legacy
#: (v1-only, no `scope_authorization`) configs/fixtures are unaffected --
#: they may use any positive `min_count_per_class` as before.
_PINNED_MIN_COUNT_PER_CLASS: int = 36

#: The three governance states `decide_scope_gate` can resolve to; every
#: `scope_authorization.governance_statements` block must carry a non-blank
#: string for each.
_REQUIRED_GOVERNANCE_STATES: tuple[str, ...] = (
    "FULL_SPECTRUM",
    "TRUNCATING_PATHOGENIC_ONLY",
    "NONE_VALIDATED",
)
_PINNED_STRATUM_SEMANTICS: Mapping[str, tuple[bool, tuple[str, ...]]] = {
    "missense": (True, ("pathogenic", "benign")),
    "truncating": (True, ("pathogenic",)),
}

#: Required Tavtigian category-cutoff keys (PRD-06 sec 10.2/AC1).
_REQUIRED_CUTOFF_KEYS: tuple[str, ...] = (
    "pathogenic_min",
    "likely_pathogenic_min",
    "vus_min",
    "vus_max",
    "likely_benign_max",
    "benign_max",
)

#: PP5/BP6/PS4 derive DIRECTLY from a variant's OWN ClinVar assertion (R-A2
#: circularity) -- PP5/BP6 are the reputable-source criteria (ClinGen-SVI-2018
#: deprecated), and BIAS-3.0.0's PS4 falls back to counting ClinVar submitters
#: ("No GWAS data found. N independent ClinVar submitters classify...") when no
#: GWAS/case-control data exists, which for a rare Mendelian disorder is nearly
#: always. Grading such a criterion against ClinVar-derived labels reads the
#: answer key (Oracle decision, real BIAS-3.0.0 devbox evidence 2026-07). All
#: are structurally forbidden from `automatable_criteria` at load time, never
#: merely absent-by-convention (MAJOR-2). NOTE: the TRANSITIVE ClinVar criteria
#: (PM5 same-residue, PM1 domain-rate, PP2 gene-rate) are a SEPARATE, deferred
#: ruling pending the full-held-out audit -- not banned here.
FORBIDDEN_CRITERIA: frozenset[str] = frozenset({"PP5", "BP6", "PS4"})

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
    #: Gate-fidelity (Arm C, BREAKING migration): nested per-stratum schema
    #: `{confidence: float, strata: {name: {precision, recall, gating,
    #: directions}}}` -- replaces the flat `{metric: float}` map. EMPTY `{}`
    #: until GP-3 pre-registers (AC5/H13 -> `UNVERIFIED`); the flat schema is
    #: no longer accepted (`load_config` rejects it structurally).
    oracle_thresholds: Mapping[str, Any]
    labels_snapshot: str
    #: PRD-07 sec 10.2/10.3 -- optional real sha256 pin for the ClinVar
    #: `variant_summary` snapshot the labels come from (benchmark-source
    #: provenance, co-located with `labels_snapshot`). Default "" means
    #: unpinned (no checksum guard); a non-hex-64 placeholder is likewise
    #: treated as unpinned (see `knowns.LabeledVariantReader`).
    clinvar_snapshot_file_checksum: str = ""
    #: v2 scope-specific authorization gate (ADDITIVE, preregistration,
    #: `raptor.eval.scope_gate.decide_scope_gate`) -- `None` is the fully
    #: v1-compatible default (absent block); schema-validated typed mapping
    #: `{schema_version, research_use_disclaimer, full_spectrum:
    #: {requires}, research_scopes: {name: {requires}}, governance_statements:
    #: {FULL_SPECTRUM, TRUNCATING_PATHOGENIC_ONLY, NONE_VALIDATED}}` when
    #: present. Never read by v1 `decide_gate`.
    scope_authorization: Mapping[str, Any] | None = None


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


#: Gate-fidelity (Arm C, BREAKING nested-schema migration): `oracle_thresholds`
#: is now `{confidence: float, strata: {name: {precision, recall, gating,
#: directions}}}`. Empty `{}` stays the honest pre-Oracle state (AC5/H13 ->
#: `UNVERIFIED`). A non-empty block MUST carry a valid `confidence` and a
#: non-empty `strata` map that includes the `missense` gating stratum; each
#: stratum MUST pin finite `precision`/`recall` in `(0.0, 1.0]`, a boolean
#: `gating`, and an optional `directions` subset of {pathogenic, benign}. A
#: stratum named in `_PINNED_STRATUM_THRESHOLDS` (missense/truncating) MUST
#: match the Oracle-pre-registered value exactly (R-A2 pre-registration
#: lock) -- no post-hoc threshold change, however small.
def _validate_oracle_thresholds(thresholds: Any) -> None:
    if not isinstance(thresholds, dict):
        raise ConfigError("`oracle_thresholds` must be a mapping (may be empty)")
    if not thresholds:
        return  # AC5/H13: empty is the honest pre-Oracle state -> UNVERIFIED

    confidence = thresholds.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ConfigError(f"`oracle_thresholds.confidence` must be a real number, got {confidence!r}")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not (0.0 < confidence < 1.0):
        raise ConfigError(
            f"`oracle_thresholds.confidence` must be strictly between 0.0 and 1.0, got {confidence!r}"
        )

    strata = thresholds.get("strata")
    if not isinstance(strata, dict) or not strata:
        raise ConfigError("`oracle_thresholds.strata` must be a non-empty mapping when oracle_thresholds is set")
    if _REQUIRED_GATING_STRATUM not in strata:
        raise ConfigError(
            f"`oracle_thresholds.strata` must include the gating {_REQUIRED_GATING_STRATUM!r} stratum"
        )

    for name, spec in strata.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"`oracle_thresholds.strata[{name!r}]` must be a mapping")

        for metric_key in ("precision", "recall"):
            if metric_key not in spec:
                raise ConfigError(
                    f"`oracle_thresholds.strata[{name!r}]` missing required {metric_key!r} "
                    "(precision and recall are both mandatory -- concordance is not part of "
                    "the per-stratum gating schema and can never substitute, BLOCKER 1)"
                )
            value = spec[metric_key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(
                    f"`oracle_thresholds.strata[{name!r}][{metric_key!r}]` must be a real number, "
                    f"got {value!r}"
                )
            value = float(value)
            if not math.isfinite(value) or not (0.0 < value <= 1.0):
                raise ConfigError(
                    f"`oracle_thresholds.strata[{name!r}][{metric_key!r}]` must be a finite value "
                    f"in (0.0, 1.0] -- 0.0/negative authorizes on zero performance, got {value!r}"
                )

        gating = spec.get("gating")
        if not isinstance(gating, bool):
            raise ConfigError(f"`oracle_thresholds.strata[{name!r}].gating` must be a bool, got {gating!r}")

        directions = spec.get("directions", [])
        if not isinstance(directions, list) or not all(isinstance(d, str) for d in directions):
            raise ConfigError(
                f"`oracle_thresholds.strata[{name!r}].directions` must be a list of strings"
            )
        bad_directions = set(directions) - _VALID_DIRECTIONS
        if bad_directions:
            raise ConfigError(
                f"`oracle_thresholds.strata[{name!r}].directions` names unknown direction(s): "
                f"{sorted(bad_directions)} (must be a subset of {sorted(_VALID_DIRECTIONS)})"
            )

        pinned = _PINNED_STRATUM_THRESHOLDS.get(name)
        if pinned is not None:
            for metric_key, pinned_value in pinned.items():
                actual = float(spec[metric_key])
                if not math.isclose(actual, pinned_value, rel_tol=0.0, abs_tol=1e-9):
                    raise ConfigError(
                        f"`oracle_thresholds.strata[{name!r}][{metric_key!r}]`={actual!r} does not "
                        f"match the pinned pre-registered rubric value {pinned_value!r} for stratum "
                        f"{name!r} (pre-registration lock, R-A2) -- changing a threshold post-hoc "
                        "breaks pre-registration; the min_count_per_class 35->36 power-floor "
                        "correction is the sole sanctioned exception and is not a per-stratum value"
                    )
        pinned_semantics = _PINNED_STRATUM_SEMANTICS.get(name)
        if pinned_semantics is not None:
            pinned_gating, pinned_directions = pinned_semantics
            if gating is not pinned_gating or tuple(directions) != pinned_directions:
                raise ConfigError(
                    f"`oracle_thresholds.strata[{name!r}]` gating/directions "
                    f"{gating!r}/{directions!r} do not match pinned pre-registered semantics "
                    f"{pinned_gating!r}/{list(pinned_directions)!r}"
                )


def _split_scope_key(scope_key: Any, *, ctx: str) -> tuple[str, str]:
    """Split a `"{stratum}:{direction}"` scope key; fail loud (ConfigError)
    on any non-string, malformed, or unknown-direction key."""
    if not isinstance(scope_key, str) or scope_key.count(":") != 1:
        raise ConfigError(f"{ctx} scope key must be a '{{stratum}}:{{direction}}' string, got {scope_key!r}")
    stratum, _, direction = scope_key.partition(":")
    if not stratum or direction not in _VALID_DIRECTIONS:
        raise ConfigError(
            f"{ctx} scope key {scope_key!r} names an unknown direction -- must be one of "
            f"{sorted(_VALID_DIRECTIONS)}"
        )
    return stratum, direction


def _registered_scopes(oracle_thresholds: Mapping[str, Any]) -> frozenset[str]:
    """Every `"{stratum}:{direction}"` scope a (schema-validated, but not
    yet type-coerced) `oracle_thresholds` block actually registers a
    threshold-eligible direction for (i.e. `direction in strata[name].directions`)."""
    strata = (oracle_thresholds or {}).get("strata") or {}
    scopes: set[str] = set()
    for name, spec in strata.items():
        for direction in spec.get("directions", []) or []:
            if direction in _VALID_DIRECTIONS:
                scopes.add(f"{name}:{direction}")
    return frozenset(scopes)


def _validate_requires_list(requires: Any, registered: frozenset[str], *, ctx: str) -> None:
    if not isinstance(requires, list) or not requires:
        raise ConfigError(f"{ctx}.requires must be a non-empty list of '{{stratum}}:{{direction}}' scope keys")
    for scope_key in requires:
        _split_scope_key(scope_key, ctx=ctx)
        if scope_key not in registered:
            raise ConfigError(
                f"{ctx}.requires names scope {scope_key!r} which is not a stratum/direction "
                "registered in `oracle_thresholds` (cannot authorize on an unregistered scope)"
            )


#: v2 scope-specific authorization gate (preregistration, additive):
#: `scope_authorization` is OPTIONAL -- absent/`None` keeps a config fully
#: v1-compatible (`EvalConfig.scope_authorization = None`). When present it
#: is schema-validated and fail-loud (`ConfigError`) on load, mirroring
#: `_validate_oracle_thresholds`'s style: never silently accept a malformed
#: or post-hoc-narrowed authorization policy.
def _validate_scope_authorization(scope_auth: Any, oracle_thresholds: Mapping[str, Any]) -> None:
    if not isinstance(scope_auth, dict):
        raise ConfigError("`scope_authorization` must be a mapping")

    schema_version = scope_auth.get("schema_version")
    if schema_version not in (2, "2"):
        raise ConfigError(
            f"`scope_authorization.schema_version` must be 2, got {schema_version!r}"
        )

    disclaimer = scope_auth.get("research_use_disclaimer")
    if not isinstance(disclaimer, str) or not disclaimer.strip():
        raise ConfigError("`scope_authorization.research_use_disclaimer` must be a non-blank string")
    if disclaimer != _PINNED_RESEARCH_USE_DISCLAIMER:
        raise ConfigError(
            "`scope_authorization.research_use_disclaimer` must match the mandatory pinned "
            f"safe text exactly, got {disclaimer!r}"
        )

    registered = _registered_scopes(oracle_thresholds)

    full_spectrum = scope_auth.get("full_spectrum")
    if not isinstance(full_spectrum, dict):
        raise ConfigError("`scope_authorization.full_spectrum` must be a mapping")
    _validate_requires_list(full_spectrum.get("requires"), registered, ctx="scope_authorization.full_spectrum")
    if frozenset(full_spectrum["requires"]) != _PINNED_FULL_SPECTRUM_SCOPES:
        raise ConfigError(
            "`scope_authorization.full_spectrum.requires` must equal exactly the pinned "
            f"pre-registered full-spectrum scope set {sorted(_PINNED_FULL_SPECTRUM_SCOPES)!r} "
            f"(anti-cherry-pick lock) -- got {sorted(full_spectrum['requires'])!r}"
        )

    research_scopes = scope_auth.get("research_scopes", {})
    if not isinstance(research_scopes, dict):
        raise ConfigError("`scope_authorization.research_scopes` must be a mapping")
    for name, spec in research_scopes.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"`scope_authorization.research_scopes[{name!r}]` must be a mapping")
        _validate_requires_list(
            spec.get("requires"), registered, ctx=f"scope_authorization.research_scopes[{name!r}]"
        )

    # Checker finding 1: pin BOTH the key set and each key's `requires` to
    # the exact pre-registered research-scope mapping -- a missing key, an
    # extra/renamed key, or a `requires` list that is merely a *subset* of
    # registered scopes (rather than exactly the pinned set) must never
    # silently gain authorization semantics.
    if frozenset(research_scopes.keys()) != frozenset(_PINNED_RESEARCH_SCOPE_REQUIRES.keys()):
        raise ConfigError(
            "`scope_authorization.research_scopes` keys must equal exactly the pinned "
            f"pre-registered research-scope set {sorted(_PINNED_RESEARCH_SCOPE_REQUIRES)!r} "
            f"(anti-cherry-pick lock) -- got {sorted(research_scopes)!r}"
        )
    for name, pinned_requires in _PINNED_RESEARCH_SCOPE_REQUIRES.items():
        actual_requires = frozenset(research_scopes[name]["requires"])
        if actual_requires != pinned_requires:
            raise ConfigError(
                f"`scope_authorization.research_scopes[{name!r}].requires` must equal exactly "
                f"{sorted(pinned_requires)!r} (pre-registration lock) -- got "
                f"{sorted(actual_requires)!r}"
            )

    governance_statements = scope_auth.get("governance_statements")
    if not isinstance(governance_statements, dict):
        raise ConfigError("`scope_authorization.governance_statements` must be a mapping")
    for state in _REQUIRED_GOVERNANCE_STATES:
        if state not in governance_statements:
            raise ConfigError(f"`scope_authorization.governance_statements` missing required state {state!r}")
        statement = governance_statements[state]
        if not isinstance(statement, str) or not statement.strip():
            raise ConfigError(f"`scope_authorization.governance_statements[{state!r}]` must be a non-blank string")

    # Checker finding 1 (GPT-5.4): pin ALL THREE governance-state strings,
    # not just TRUNCATING_PATHOGENIC_ONLY -- every state is an authorization
    # surface a config author could otherwise widen/weaken.
    for state, pinned_statement in _PINNED_GOVERNANCE_STATEMENTS.items():
        actual = governance_statements[state]
        if actual != pinned_statement:
            raise ConfigError(
                f"`scope_authorization.governance_statements[{state!r}]` must match the "
                f"mandatory pinned pre-registered statement verbatim, got {actual!r}"
            )


def _build_oracle_thresholds(thresholds: Mapping[str, Any]) -> Mapping[str, Any]:
    """Coerce a schema-validated nested `oracle_thresholds` block to its
    typed form -- `confidence`/`precision`/`recall` -> `float`, `gating` ->
    `bool`, `directions` -> `list[str]`. NEVER calls `float()` on a stratum
    dict (the bug this migration removes: the old flat builder's final
    `float(v)`-per-key comprehension would raise `TypeError: float()
    argument must be a string or a real number, not 'dict'` the instant a
    stratum value reached it)."""
    if not thresholds:
        return {}
    strata = {
        str(name): {
            "precision": float(spec["precision"]),
            "recall": float(spec["recall"]),
            "gating": bool(spec["gating"]),
            "directions": [str(d) for d in spec.get("directions", [])],
        }
        for name, spec in thresholds["strata"].items()
    }
    return {"confidence": float(thresholds["confidence"]), "strata": strata}


def _build_scope_authorization(scope_auth: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Coerce a schema-validated `scope_authorization` block to its typed
    form (str-keyed, list/str-coerced); `None` stays `None` (v1-compatible
    default -- absent block, `decide_scope_gate` fails closed)."""
    if not scope_auth:
        return None
    return {
        "schema_version": 2,
        "research_use_disclaimer": str(scope_auth["research_use_disclaimer"]),
        "full_spectrum": {"requires": [str(s) for s in scope_auth["full_spectrum"]["requires"]]},
        "research_scopes": {
            str(name): {"requires": [str(s) for s in spec["requires"]]}
            for name, spec in scope_auth.get("research_scopes", {}).items()
        },
        "governance_statements": {
            str(state): str(text) for state, text in scope_auth["governance_statements"].items()
        },
    }


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

    # v2 scope-specific authorization gate (ADDITIVE, preregistration): the
    # block is OPTIONAL, but checker finding 5 (GPT-5.4) requires STRICT
    # presence semantics -- only KEY ABSENCE means "legacy v1 config"
    # (`scope_authorization=None`). Any explicitly present value -- `null`,
    # `{}`, `[]`, `false`, `""` -- is a malformed v2 declaration and must
    # raise loud, never silently fall back to v1 via a truthiness check.
    if "scope_authorization" in raw:
        scope_authorization_raw = raw["scope_authorization"]
        _validate_scope_authorization(scope_authorization_raw, oracle_thresholds)
        # Checker finding 2 (GPT-5.4): once a config declares a v2
        # `scope_authorization` block, `min_count_per_class` is no longer a
        # free-standing pin -- it must equal exactly the preregistered v2
        # floor (36). Legacy v1-only configs (no `scope_authorization` key)
        # are unaffected -- existing fixtures using a different positive
        # `min_count_per_class` keep loading unchanged.
        if min_count != _PINNED_MIN_COUNT_PER_CLASS:
            raise ConfigError(
                "`min_count_per_class` must equal the pinned pre-registered v2 floor "
                f"{_PINNED_MIN_COUNT_PER_CLASS} once `scope_authorization` is present -- "
                f"got {min_count!r}"
            )
    else:
        scope_authorization_raw = None

    return EvalConfig(
        automatable_criteria=normalized_criteria,
        tavtigian_points={str(k): int(v) for k, v in raw["tavtigian_points"].items()},
        tavtigian_cutoffs={str(k): int(v) for k, v in raw["tavtigian_cutoffs"].items()},
        min_count_per_class=int(min_count),
        split=dict(raw["split"]),
        oracle_thresholds=_build_oracle_thresholds(oracle_thresholds),
        labels_snapshot=str(raw["labels_snapshot"]),
        clinvar_snapshot_file_checksum=str(raw.get("clinvar_snapshot_file_checksum", "") or ""),
        scope_authorization=_build_scope_authorization(scope_authorization_raw),
    )
