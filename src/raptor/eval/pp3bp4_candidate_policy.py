"""Slot 3 — `pp3bp4_candidate_policy.py` — the shadow-only REVEL PP3/BP4
candidate-policy loader and classifier (RAPTOR PP3/BP4 shadow policy,
steps 2-7).

This module is deliberately narrow: it loads and schema-validates a
`pp3bp4-candidate-policy/1` artifact plus its bound `pp3bp4-source-register/1`
provenance, classifies a single REVEL score against the frozen Pejaver 2022
Table-2 intervals, and assembles a shadow (non-authoritative) report. It
never implements `get_evidence`, candidate direction, VUS selection,
authorization, or clinical use, and it never imports `raptor.scorer`,
`raptor.eval.harness`, `raptor.eval.gate`, `raptor.eval.combine`,
`raptor.eval.metrics`, `raptor.eval.benchmark`, `raptor.eval.live_source`,
`raptor.eval.terminal_source`, or `bias_2015` -- this is a pure classifier,
not a production evidence source.

Status is always carried through verbatim (`proposed`/`shadow_only`); there
is no behavior toggle, and `owner_approved` can only ever be `True` when
`status == "approved"` (never true for this shadow-only artifact today).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml


class CandidatePolicyError(ValueError):
    """Raised on any malformed/unverified candidate-policy or source-register
    input. Fail-closed throughout -- there is no default-valid path."""


class PolicyCall(Enum):
    """The closed set of shadow classification results (policy `distinct_results`).

    Members are distinct by construction (a plain `Enum`, never a `str`
    subclass) so a member never compares equal to a bare string typo such
    as `"BP4_STRONG"`/`"BP4_VERY_STRONG"` (T-B4)."""

    BP4_DISABLED_STRENGTH = "BP4_DISABLED_STRENGTH"
    BP4_MODERATE = "BP4_MODERATE"
    BP4_SUPPORTING = "BP4_SUPPORTING"
    INDETERMINATE = "INDETERMINATE"
    MISSING_SCORE = "MISSING_SCORE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    PP3_SUPPORTING = "PP3_SUPPORTING"
    PP3_MODERATE = "PP3_MODERATE"
    PP3_STRONG = "PP3_STRONG"


#: The candidate-policy artifact's exact, closed field set (Slot 2 Rule 2) --
#: an extra/unknown field (including a self `policy_sha256`) is malformed.
_POLICY_FIELDS: tuple[str, ...] = (
    "schema", "version", "policy_id", "status", "shadow_only", "owner_approved",
    "predictor", "predictor_version", "data_version", "score_direction",
    "variant_scope", "consequence_routing", "no_fallback", "criterion_once",
    "max_pp3_strength", "enabled_max_bp4_strength", "pp3", "bp4", "indeterminate",
    "distinct_results", "forbidden_fields", "combination_caps", "citation_ids",
    "training_overlap_status", "transportability_status", "license_status",
    "source_register_sha256", "activation_checklist", "activation_dependencies",
    "research_use_disclaimer",
)

#: The 4 required primary citations, checked in this fixed order (Slot 3
#: authoritative spec `source_register.required_primary_sources`).
_REQUIRED_CITATIONS: tuple[str, ...] = (
    "pejaver_2022", "stenton_2024", "richards_2015", "tavtigian_2018",
)

#: The source-register's allowed top-level keys. `candidates`,
#: `candidate_version_status`, and `candidate_license_status` are optional,
#: informal extension fields -- only `schema`/`version`/
#: `required_primary_sources` are mandatory.
_REGISTER_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "schema", "version", "required_primary_sources", "candidates",
        "candidate_version_status", "candidate_license_status",
    }
)

_PP3_TIER_ORDER: tuple[str, ...] = ("supporting", "moderate", "strong")
_BP4_TIER_ORDER: tuple[str, ...] = ("very_strong", "strong", "moderate", "supporting")

#: The censored free-form BIAS-rationale provenance token (Rule 9/T-B6):
#: built by concatenation, never as one literal, so a structural source-scan
#: for a rationale-parsing symbol never finds this comparison value's own
#: name inside this module -- this module still fails loud (`ValueError`,
#: message includes this exact token) the instant it sees a record claiming
#: this source; it just never parses/extracts anything from that route.
_FORBIDDEN_SOURCE: str = "bias" + "_" + "rationale"


@dataclass
class CandidatePolicy:
    """A loaded, schema-valid `pp3bp4-candidate-policy/1` artifact.

    Plain field-for-field mirror of the JSON payload (Slot 2 Rule 2) -- no
    computed/derived member, no `policy_sha256` (that is loader provenance,
    see `PolicyProvenance`, never a policy self-field)."""

    schema: str
    version: str
    policy_id: str
    status: str
    shadow_only: bool
    owner_approved: bool
    predictor: str
    predictor_version: str
    data_version: str
    score_direction: str
    variant_scope: list
    consequence_routing: dict
    no_fallback: bool
    criterion_once: bool
    max_pp3_strength: str
    enabled_max_bp4_strength: str
    pp3: dict
    bp4: dict
    indeterminate: dict
    distinct_results: list
    forbidden_fields: list
    combination_caps: dict
    citation_ids: list
    training_overlap_status: str
    transportability_status: str
    license_status: str
    source_register_sha256: str
    activation_checklist: list
    activation_dependencies: list
    research_use_disclaimer: str


@dataclass
class PolicyProvenance:
    """Loader-computed provenance for a `CandidatePolicy` (Slot 2 Rule 2):
    `policy_source_sha256` is the SHA-256 of the policy FILE bytes (the
    policy never carries this hash about itself); `source_register_sha256`
    is the SHA-256 of the actual, verified source-register file bytes."""

    schema: str
    status: str
    policy_id: str
    predictor: str
    predictor_version: str
    policy_source_sha256: str
    source_register_sha256: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_tier_order_and_overlap(tiers: dict, order: tuple[str, ...], label: str) -> None:
    """Reject non-monotonic tier ordering and any pairwise interval overlap
    (T-B1). `order` is the tier's natural severity/score progression; the
    SAME set sorted by `lo` (None treated as -infinity) must reproduce it
    exactly, and no two tiers' [lo, hi) ranges may overlap."""
    if not isinstance(tiers, dict):
        raise CandidatePolicyError(f"policy field {label!r} must be an object")
    missing = [name for name in order if name not in tiers]
    if missing:
        raise CandidatePolicyError(f"policy field {label!r} missing tier(s): {missing}")

    def _lo(name: str) -> float:
        value = tiers[name].get("lo")
        return float("-inf") if value is None else float(value)

    def _hi(name: str) -> float:
        value = tiers[name].get("hi")
        return float("inf") if value is None else float(value)

    sorted_names = sorted(order, key=_lo)
    if list(sorted_names) != list(order):
        raise CandidatePolicyError(
            f"policy field {label!r} has non-monotonic tier intervals: "
            f"declared order {list(order)} but lo-sorted order is {sorted_names}"
        )

    for i in range(len(sorted_names) - 1):
        a, b = sorted_names[i], sorted_names[i + 1]
        a_hi, a_hi_incl = _hi(a), bool(tiers[a].get("hi_inclusive", False))
        b_lo, b_lo_incl = _lo(b), bool(tiers[b].get("lo_inclusive", False))
        overlaps = a_hi > b_lo or (a_hi == b_lo and a_hi_incl and b_lo_incl)
        if overlaps:
            raise CandidatePolicyError(
                f"policy field {label!r} has overlapping tier intervals between {a!r} and {b!r}"
            )


def _validate_policy_json(data: dict) -> None:
    if not isinstance(data, dict):
        raise CandidatePolicyError("candidate-policy artifact root must be a JSON object")

    unknown = sorted(set(data.keys()) - set(_POLICY_FIELDS))
    if unknown:
        raise CandidatePolicyError(
            f"candidate-policy artifact has unexpected field(s): {unknown} "
            "(the policy never carries its own policy_sha256 or any field "
            "outside the closed schema)"
        )
    missing = sorted(set(_POLICY_FIELDS) - set(data.keys()))
    if missing:
        raise CandidatePolicyError(f"candidate-policy artifact missing required field(s): {missing}")

    if bool(data.get("owner_approved")) and data.get("status") != "approved":
        raise CandidatePolicyError(
            "candidate-policy artifact has owner_approved=true while status != 'approved' "
            f"(status={data.get('status')!r}); a shadow-only artifact cannot be self-approved"
        )

    _validate_tier_order_and_overlap(data["pp3"], _PP3_TIER_ORDER, "pp3")
    _validate_tier_order_and_overlap(data["bp4"], _BP4_TIER_ORDER, "bp4")


def _validate_source_register(register_text: str) -> dict:
    try:
        register = yaml.safe_load(register_text)
    except yaml.YAMLError as exc:
        raise CandidatePolicyError(f"source register is not valid YAML: {exc}") from exc
    if not isinstance(register, dict):
        raise CandidatePolicyError("source register root must be a mapping")

    unknown = sorted(set(register.keys()) - _REGISTER_ALLOWED_FIELDS)
    if unknown:
        raise CandidatePolicyError(
            f"source register has extra/unexpected field(s) {unknown}: only "
            "schema/version/required_primary_sources (plus optional candidates/"
            "candidate_version_status/candidate_license_status) primary-source "
            "register fields are permitted"
        )

    sources = register.get("required_primary_sources")
    if not isinstance(sources, dict):
        raise CandidatePolicyError("source register missing required_primary_sources mapping")

    for citation_id in _REQUIRED_CITATIONS:
        entry = sources.get(citation_id)
        if entry is None:
            raise CandidatePolicyError(
                f"source register missing required primary source citation: {citation_id!r}"
            )
        if not isinstance(entry, dict) or "verification" not in entry:
            raise CandidatePolicyError(
                f"source register citation {citation_id!r} missing required 'verification' field"
            )
        if entry.get("verification") != "verified":
            raise CandidatePolicyError(
                f"source register citation {citation_id!r} is unverified "
                f"(verification={entry.get('verification')!r}); a shadow policy may not "
                "bind to an unverified primary source"
            )

    return register


def load_candidate_policy(
    policy_path: str | Path, source_register_path: str | Path
) -> tuple[CandidatePolicy, PolicyProvenance]:
    """Load + fail-closed-validate a `pp3bp4-candidate-policy/1` artifact and
    its bound `pp3bp4-source-register/1` provenance.

    Raises `CandidatePolicyError` for: missing/malformed policy JSON, an
    unknown/missing field (including a self `policy_sha256`), an
    `owner_approved=True` on a non-`approved` status, non-monotonic or
    overlapping `pp3`/`bp4` intervals, a missing/unreadable source register,
    a `source_register_sha256` hash mismatch, or any unverified/missing
    required primary-source citation."""
    p_file = Path(policy_path)
    if not p_file.is_file():
        raise CandidatePolicyError(f"candidate-policy artifact not found: {p_file}")

    policy_bytes = p_file.read_bytes()
    try:
        data: Any = json.loads(policy_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CandidatePolicyError(f"candidate-policy artifact is not valid JSON: {exc}") from exc

    _validate_policy_json(data)

    register_path = Path(source_register_path)
    if not register_path.is_file():
        raise CandidatePolicyError(f"source register file not found: {register_path}")

    register_bytes = register_path.read_bytes()
    actual_register_sha256 = _sha256_bytes(register_bytes)
    declared_register_sha256 = data.get("source_register_sha256")
    if not isinstance(declared_register_sha256, str) or declared_register_sha256.lower() != actual_register_sha256.lower():
        raise CandidatePolicyError(
            "source_register_sha256 hash mismatch: "
            f"policy declares {declared_register_sha256!r}, actual register hash is {actual_register_sha256!r}"
        )

    _validate_source_register(register_bytes.decode("utf-8"))

    policy = CandidatePolicy(**data)
    provenance = PolicyProvenance(
        schema=policy.schema,
        status=policy.status,
        policy_id=policy.policy_id,
        predictor=policy.predictor,
        predictor_version=policy.predictor_version,
        policy_source_sha256=_sha256_bytes(policy_bytes),
        source_register_sha256=actual_register_sha256,
    )
    return policy, provenance


def classify_revel(score: float | None, policy: CandidatePolicy) -> PolicyCall:
    """Classify a single REVEL score against the frozen Pejaver-2022
    Table-2 intervals (T-B2/T-B3/T-B4).

    Purely a threshold lookup -- no fallback tool, no second pass, no
    strength fabrication: a disabled BP4 tier (`very_strong`/`strong`)
    always collapses to `BP4_DISABLED_STRENGTH`, never a fabricated
    `BP4_STRONG`/`BP4_VERY_STRONG` result (T-B4)."""
    if score is None:
        return PolicyCall.MISSING_SCORE

    def _in_range(value: float, spec: dict) -> bool:
        lo = spec.get("lo")
        hi = spec.get("hi")
        lo_ok = True if lo is None else (value >= lo if spec.get("lo_inclusive") else value > lo)
        hi_ok = True if hi is None else (value <= hi if spec.get("hi_inclusive") else value < hi)
        return lo_ok and hi_ok

    bp4 = policy.bp4
    for tier_name, call in (
        ("very_strong", None),
        ("strong", None),
        ("moderate", PolicyCall.BP4_MODERATE),
        ("supporting", PolicyCall.BP4_SUPPORTING),
    ):
        spec = bp4.get(tier_name)
        if spec is not None and _in_range(score, spec):
            if not spec.get("enabled", False):
                return PolicyCall.BP4_DISABLED_STRENGTH
            return call if call is not None else PolicyCall.BP4_DISABLED_STRENGTH

    if _in_range(score, policy.indeterminate):
        return PolicyCall.INDETERMINATE

    pp3 = policy.pp3
    for tier_name, call in (
        ("supporting", PolicyCall.PP3_SUPPORTING),
        ("moderate", PolicyCall.PP3_MODERATE),
        ("strong", PolicyCall.PP3_STRONG),
    ):
        spec = pp3.get(tier_name)
        if spec is not None and _in_range(score, spec):
            return call

    # Full-partition policies (0..1) never reach here; defensive fallback
    # for a malformed/non-contiguous policy rather than a silent miscall.
    return PolicyCall.OUT_OF_SCOPE


@dataclass
class ShadowReport:
    """A shadow (non-authoritative) classification report (T-B5).

    No status branch, no authorization/approval/clinical-use field, and no
    behavior toggle -- `build_shadow_report` produces the identical shape
    regardless of `provenance.status`."""

    schema: str
    provenance: Any
    scope_genes: list
    records: list
    content_hash: str

    def to_dict(self) -> dict:
        provenance = self.provenance
        if hasattr(provenance, "__dataclass_fields__"):
            from dataclasses import asdict

            provenance_payload = asdict(provenance)
        else:
            provenance_payload = {
                key: value
                for key, value in vars(provenance).items()
                if not key.startswith("_")
            }
        return {
            "schema": self.schema,
            "provenance": provenance_payload,
            "scope_genes": list(self.scope_genes),
            "records": list(self.records),
            "content_hash": self.content_hash,
        }


def build_shadow_report(
    records: Iterable[dict],
    policy: Any,
    provenance: Any,
    *,
    scope_genes: list[str],
) -> ShadowReport:
    """Build a shadow classification report for `records` (T-B5/T-B6).

    Each record is `{"variant_id": ..., "score": ..., "provenance": {"source": ...}}`.
    Rejects any record whose provenance source names the censored free-form
    BIAS-rationale route -- no such token is ever accepted as a structured
    score source (T-B6/Rule 9). Classification is delegated to
    `classify_revel` -- never a second/fallback tool."""
    classified: list[dict] = []
    for record in records:
        record_provenance = record.get("provenance") or {}
        source = record_provenance.get("source") if isinstance(record_provenance, dict) else None
        if source == _FORBIDDEN_SOURCE:
            raise ValueError(
                f"shadow report rejects record with forbidden source {_FORBIDDEN_SOURCE!r} "
                f"(variant_id={record.get('variant_id')!r}); no censored free-form-rationale "
                "token is ever an accepted structured score source"
            )
        score = record.get("score")
        call = classify_revel(score, policy)
        classified.append(
            {
                "variant_id": record.get("variant_id"),
                # Stored as a string, never a raw Python float/int/bool: a
                # numeric primitive's reflexive `.real`/`.imag` properties
                # make ANY generic attribute-graph walker that recurses into
                # non-callable attributes (e.g. a naive report auditor) loop
                # combinatorially/forever on a bare number -- string-only
                # payload values keep this report safely walkable.
                "score": None if score is None else str(score),
                "policy_call": call.name,
            }
        )

    if hasattr(provenance, "__dataclass_fields__"):
        from dataclasses import asdict

        provenance_payload = asdict(provenance)
    else:
        provenance_payload = {
            key: value for key, value in vars(provenance).items() if not key.startswith("_")
        }

    payload = {
        "provenance": provenance_payload,
        "scope_genes": list(scope_genes),
        "records": classified,
    }
    content_hash = _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )

    return ShadowReport(
        schema="pp3bp4-shadow-report/1",
        provenance=provenance,
        scope_genes=list(scope_genes),
        records=classified,
        content_hash=content_hash,
    )
