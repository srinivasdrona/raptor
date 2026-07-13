"""Criterion-strength reconciliation policy — fail-closed by construction.

ADR-0007 arm's-length boundary: this module never imports `bias_2015` and
never reads a label/benchmark/held-out file. It reconciles two DECLARED,
machine-readable inputs:

* a `StrengthLadder` (`configs/eval/bias_strength_ladder.yaml`) -- the
  strengths the PINNED BIAS-3.0.0 source can actually emit per criterion,
  cited by source anchor (file/symbol/line), never copied text; and
* a `StrengthPolicy` (`configs/acmg/strength_policy.yaml`) -- an owner
  decision, per (criterion, ladder-strength), of what RAPTOR does with a
  BIAS-emitted strength that may sit outside RAPTOR's CURRENT scorer
  vocabulary (`configs/acmg/*.yaml::acmg_criteria[*].strength_vocab`).

Every `records`/`gene_overrides` entry maps to exactly one of four
dispositions:

* ``accept``  -- emit the call UNCHANGED (`emit` must equal the ladder
  strength, and must already be in the current scorer vocab).
* ``cap``     -- DEMOTE the call to a strictly weaker `emit` strength that
  IS in the current scorer vocab (never inflate towards pathogenic/benign).
* ``manual``  -- route the WHOLE record to manual review (no emission).
* ``forbid``  -- silently drop only THIS criterion call (no emission, the
  rest of the record's calls are untouched).

A policy is only ever "active" (able to accept/cap/forbid) when BOTH
`status == "approved"` AND `owner_approved is True` -- otherwise every
call it sees, regardless of the record's own configured disposition,
fails closed to ``manual`` (owner has not signed off on auto-behavior).

`apply_strength_policy` returns a plain, JSON-serializable
`StrengthPolicyDecision` dataclass -- the same pure surface is consumed
by both eval and production call sites (no eval-only/prod-only branching
inside this module, see `test_eval_and_production_can_consume_the_same_pure_policy_surface`).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

#: BIAS-2015 / RAPTOR KB strength vocabulary + relative ordering (weakest
#: to strongest). `cap` is only ever allowed to move a call to a STRICTLY
#: lower rank than the ladder strength it was called at (never inflate).
STRENGTH_RANK: Mapping[str, int] = {
    "supporting": 1,
    "moderate": 2,
    "strong": 3,
    "very_strong": 4,
    "stand_alone": 5,
}

_LADDER_SCHEMA = "bias-strength-ladder"
_LADDER_REQUIRED_KEYS = frozenset({"schema", "bias_version", "bias_commit", "criteria"})

_POLICY_SCHEMA = "acmg-strength-policy"
_POLICY_REQUIRED_KEYS = frozenset(
    {
        "schema",
        "policy_id",
        "version",
        "status",
        "owner_approved",
        "default_disposition",
        "records",
        "gene_overrides",
    }
)
_VALID_STATUSES = frozenset({"unapproved", "approved"})
_VALID_DISPOSITIONS = frozenset({"accept", "cap", "manual", "forbid"})
_VALID_DEFAULT_DISPOSITIONS = frozenset({"manual", "forbid"})
_EMITTING_DISPOSITIONS = frozenset({"accept", "cap"})
_RECORD_REQUIRED_KEYS = frozenset({"disposition"})
#: `decision_dependency`/`recommended_disposition`/`recommended_emit`/`notes`
#: are OPTIONAL, purely-informational owner-decision metadata (never
#: consulted by `apply_strength_policy`) -- they let a still-`unapproved`
#: policy carry a planner's proposed future disposition + its named
#: unresolved dependency alongside the schema-valid, currently-effective
#: one, without ever letting that proposal silently become active.
_RECORD_ALLOWED_KEYS = frozenset(
    {"disposition", "emit", "decision_dependency", "recommended_disposition", "recommended_emit", "notes"}
)
#: Gene-override scope is deliberately pinned to RAPTOR's v1 gene set
#: (`configs/acmg/tsc.yaml::genes`) -- never a fixture/gene-of-convenience.
_ALLOWED_OVERRIDE_GENES = frozenset({"TSC1", "TSC2"})


class StrengthLadderError(ValueError):
    """Raised on a malformed/unknown-field/wrong-schema strength ladder."""


class StrengthPolicyError(ValueError):
    """Raised on a malformed/unapproved-shape strength policy (schema-time,
    not runtime -- a policy that fails to VALIDATE never loads, regardless
    of whether it would later be treated as active)."""


class UnknownStrengthPolicyPairError(KeyError):
    """Raised at apply-time for a (criterion, strength) pair that is not on
    the loaded `StrengthLadder` at all -- there is no `default_disposition`
    fallback for this: an unknown pair is a scorer/ladder drift bug, not a
    policy gap."""


@dataclass(frozen=True)
class StrengthLadder:
    """The ladder strengths the pinned BIAS-3.0.0 source can actually emit
    per criterion (`configs/eval/bias_strength_ladder.yaml`)."""

    bias_version: str
    bias_commit: str
    criteria: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class StrengthPolicyRecord:
    """One (criterion, ladder-strength) disposition entry.

    `recommended_disposition`/`recommended_emit`/`decision_dependency`/
    `notes` are OPTIONAL owner-decision metadata -- purely informational,
    never read by `apply_strength_policy`. A record's PROPOSED future
    disposition never activates itself; only `owner_approved=true` +
    `status="approved"` (and the corresponding `disposition`/`emit`
    fields actually being flipped) can do that.
    """

    disposition: str
    emit: str | None
    decision_dependency: str | None = None
    recommended_disposition: str | None = None
    recommended_emit: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class StrengthPolicy:
    """A schema-validated `configs/acmg/strength_policy.yaml` reconciled
    against a `StrengthLadder` + the current scorer strength vocabulary."""

    policy_id: str
    version: str
    status: str
    owner_approved: bool
    default_disposition: str
    records: Mapping[str, Mapping[str, StrengthPolicyRecord]]
    gene_overrides: Mapping[str, Mapping[str, Mapping[str, StrengthPolicyRecord]]]
    ladder: StrengthLadder
    scorer_strength_vocab: Mapping[str, tuple[str, ...]]

    @property
    def is_active(self) -> bool:
        """Only an EXPLICITLY approved + owner-approved policy may ever
        accept/cap/forbid a call; anything else fails closed to manual."""
        return self.status == "approved" and self.owner_approved is True


@dataclass(frozen=True)
class StrengthPolicyDecision:
    """The pure, JSON-serializable policy surface -- identical for eval and
    production call sites (never branch on caller identity inside this
    module)."""

    criterion: str
    requested_strength: str
    disposition: str
    emitted_call: dict[str, Any] | None
    manual_record: dict[str, Any] | None
    audit: Mapping[str, Any]


def _read_yaml_mapping(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StrengthLadderError(f"root must be a mapping, got {type(raw).__name__}")
    return raw


def _reject_unknown_keys(raw: Mapping[str, Any], allowed: frozenset[str], *, error: type, ctx: str) -> None:
    unexpected = set(raw) - allowed
    if unexpected:
        raise error(f"{ctx} has unexpected field(s): {sorted(unexpected)}")
    missing = allowed - set(raw)
    if missing:
        raise error(f"{ctx} is missing required field(s): {sorted(missing)}")


def load_strength_ladder(path: str | Path) -> StrengthLadder:
    """Load + fail-closed-validate a `bias-strength-ladder` YAML file
    (`configs/eval/bias_strength_ladder.yaml`).

    Exhaustive schema: any top-level key outside `_LADDER_REQUIRED_KEYS`
    raises, as does any `criteria[*]` strength name outside `STRENGTH_RANK`.
    """
    raw = _read_yaml_mapping(path)
    _reject_unknown_keys(raw, _LADDER_REQUIRED_KEYS, error=StrengthLadderError, ctx="strength ladder")

    if raw["schema"] != _LADDER_SCHEMA:
        raise StrengthLadderError(f"schema must be {_LADDER_SCHEMA!r}, got {raw['schema']!r}")

    bias_version = raw["bias_version"]
    bias_commit = raw["bias_commit"]
    if not isinstance(bias_version, str) or not bias_version.strip():
        raise StrengthLadderError("bias_version must be a non-blank string")
    if not isinstance(bias_commit, str) or not bias_commit.strip():
        raise StrengthLadderError("bias_commit must be a non-blank string")

    criteria_raw = raw["criteria"]
    if not isinstance(criteria_raw, dict) or not criteria_raw:
        raise StrengthLadderError("criteria must be a non-empty mapping")

    criteria: dict[str, tuple[str, ...]] = {}
    for criterion, strengths in criteria_raw.items():
        if not isinstance(strengths, list) or not strengths:
            raise StrengthLadderError(f"criteria[{criterion!r}] must be a non-empty list")
        seen: list[str] = []
        for strength in strengths:
            if strength not in STRENGTH_RANK:
                raise StrengthLadderError(
                    f"criteria[{criterion!r}] names unknown strength {strength!r} "
                    f"(known: {sorted(STRENGTH_RANK)})"
                )
            if strength in seen:
                raise StrengthLadderError(f"criteria[{criterion!r}] repeats strength {strength!r}")
            seen.append(strength)
        criteria[str(criterion)] = tuple(seen)

    return StrengthLadder(bias_version=bias_version, bias_commit=bias_commit, criteria=criteria)


def _validate_record_dict(
    criterion: str,
    strength: str,
    raw_record: Any,
    *,
    scorer_strength_vocab: Mapping[str, Sequence[str]],
) -> StrengthPolicyRecord:
    ctx = f"records[{criterion!r}][{strength!r}]"
    if not isinstance(raw_record, dict):
        raise StrengthPolicyError(f"{ctx} must be a mapping")

    unexpected = set(raw_record) - _RECORD_ALLOWED_KEYS
    if unexpected:
        raise StrengthPolicyError(f"{ctx} has unexpected field(s): {sorted(unexpected)}")

    disposition = raw_record.get("disposition")
    if disposition not in _VALID_DISPOSITIONS:
        raise StrengthPolicyError(
            f"{ctx}.disposition must be one of {sorted(_VALID_DISPOSITIONS)}, got {disposition!r}"
        )

    emit = raw_record.get("emit")
    if disposition in _EMITTING_DISPOSITIONS:
        if not isinstance(emit, str) or not emit.strip():
            raise StrengthPolicyError(f"{ctx}.emit is required (non-blank string) for disposition={disposition!r}")

        allowed_vocab = tuple(scorer_strength_vocab.get(criterion, ()))
        if emit not in allowed_vocab:
            raise StrengthPolicyError(
                f"{ctx}.emit={emit!r} is outside the current scorer vocab for {criterion!r} "
                f"({sorted(allowed_vocab)}) -- accept/cap emit must stay in-vocab"
            )

        if disposition == "accept" and emit != strength:
            raise StrengthPolicyError(
                f"{ctx} disposition=accept must emit the SAME strength it was called at "
                f"(emit={emit!r} != strength={strength!r})"
            )

        if disposition == "cap" and STRENGTH_RANK[emit] >= STRENGTH_RANK[strength]:
            raise StrengthPolicyError(
                f"{ctx} disposition=cap must emit a STRICTLY weaker strength than {strength!r} "
                f"(emit={emit!r} does not demote) -- cap must never inflate"
            )
    else:
        if emit is not None:
            raise StrengthPolicyError(f"{ctx}.emit must be absent/null for disposition={disposition!r}")

    decision_dependency = raw_record.get("decision_dependency")
    if decision_dependency is not None and not (isinstance(decision_dependency, str) and decision_dependency.strip()):
        raise StrengthPolicyError(f"{ctx}.decision_dependency must be a non-blank string or absent/null")

    notes = raw_record.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise StrengthPolicyError(f"{ctx}.notes must be a string or absent/null")

    recommended_disposition = raw_record.get("recommended_disposition")
    if recommended_disposition is not None and recommended_disposition not in _VALID_DISPOSITIONS:
        raise StrengthPolicyError(
            f"{ctx}.recommended_disposition must be one of {sorted(_VALID_DISPOSITIONS)} or absent/null, "
            f"got {recommended_disposition!r}"
        )

    recommended_emit = raw_record.get("recommended_emit")
    if recommended_emit is not None and recommended_emit not in STRENGTH_RANK:
        raise StrengthPolicyError(
            f"{ctx}.recommended_emit must be a known strength name {sorted(STRENGTH_RANK)} or absent/null, "
            f"got {recommended_emit!r}"
        )

    return StrengthPolicyRecord(
        disposition=disposition,
        emit=emit if disposition in _EMITTING_DISPOSITIONS else None,
        decision_dependency=decision_dependency,
        recommended_disposition=recommended_disposition,
        recommended_emit=recommended_emit,
        notes=notes,
    )


def load_strength_policy(
    path: str | Path,
    *,
    ladder: StrengthLadder,
    scorer_strength_vocab: Mapping[str, Sequence[str]],
) -> StrengthPolicy:
    """Load + fail-closed-validate an `acmg-strength-policy` YAML file
    against an already-loaded `StrengthLadder` + the CURRENT scorer's
    strength vocabulary (`configs/acmg/*.yaml::acmg_criteria`).

    Exhaustive schema: `records` must cover every ladder criterion with
    EXACTLY that criterion's ladder strengths (no missing, no extra);
    `gene_overrides` genes must be in RAPTOR's v1 scope (TSC1/TSC2 only);
    `default_disposition` must be `manual`/`forbid` (never an
    auto-accepting default); `cap` never inflates; `accept`/`cap` targets
    must already be in the current scorer vocab.
    """
    raw = _read_yaml_mapping(path)
    _reject_unknown_keys(raw, _POLICY_REQUIRED_KEYS, error=StrengthPolicyError, ctx="strength policy")

    if raw["schema"] != _POLICY_SCHEMA:
        raise StrengthPolicyError(f"schema must be {_POLICY_SCHEMA!r}, got {raw['schema']!r}")

    policy_id = raw["policy_id"]
    version = raw["version"]
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise StrengthPolicyError("policy_id must be a non-blank string")
    if not (isinstance(version, str) and version.strip()) and not isinstance(version, int):
        raise StrengthPolicyError("version must be a non-blank string or int")

    status = raw["status"]
    if status not in _VALID_STATUSES:
        raise StrengthPolicyError(f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}")

    owner_approved = raw["owner_approved"]
    if not isinstance(owner_approved, bool):
        raise StrengthPolicyError("owner_approved must be a boolean")

    default_disposition = raw["default_disposition"]
    if default_disposition not in _VALID_DEFAULT_DISPOSITIONS:
        raise StrengthPolicyError(
            f"default_disposition must be one of {sorted(_VALID_DEFAULT_DISPOSITIONS)} "
            f"(never auto-accepting), got {default_disposition!r}"
        )

    records_raw = raw["records"]
    if not isinstance(records_raw, dict):
        raise StrengthPolicyError("records must be a mapping")

    ladder_criteria = set(ladder.criteria)
    records_criteria = set(records_raw)
    if records_criteria != ladder_criteria:
        missing = ladder_criteria - records_criteria
        extra = records_criteria - ladder_criteria
        raise StrengthPolicyError(
            f"records criteria must exactly match the ladder's criteria "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )

    records: dict[str, dict[str, StrengthPolicyRecord]] = {}
    for criterion, ladder_strengths in ladder.criteria.items():
        strengths_raw = records_raw[criterion]
        if not isinstance(strengths_raw, dict):
            raise StrengthPolicyError(f"records[{criterion!r}] must be a mapping")

        ladder_set = set(ladder_strengths)
        record_set = set(strengths_raw)
        if record_set != ladder_set:
            missing = ladder_set - record_set
            extra = record_set - ladder_set
            raise StrengthPolicyError(
                f"records[{criterion!r}] strengths must exactly match its ladder strengths "
                f"(missing={sorted(missing)}, extra={sorted(extra)})"
            )

        records[criterion] = {
            strength: _validate_record_dict(
                criterion, strength, strengths_raw[strength], scorer_strength_vocab=scorer_strength_vocab
            )
            for strength in ladder_strengths
        }

    gene_overrides_raw = raw["gene_overrides"]
    if not isinstance(gene_overrides_raw, dict):
        raise StrengthPolicyError("gene_overrides must be a mapping")

    gene_overrides: dict[str, dict[str, dict[str, StrengthPolicyRecord]]] = {}
    for gene, per_gene_raw in gene_overrides_raw.items():
        if gene not in _ALLOWED_OVERRIDE_GENES:
            raise StrengthPolicyError(
                f"gene_overrides key {gene!r} is outside RAPTOR's v1 gene scope {sorted(_ALLOWED_OVERRIDE_GENES)}"
            )
        if not isinstance(per_gene_raw, dict):
            raise StrengthPolicyError(f"gene_overrides[{gene!r}] must be a mapping")

        per_gene: dict[str, dict[str, StrengthPolicyRecord]] = {}
        for criterion, strengths_raw in per_gene_raw.items():
            if criterion not in ladder.criteria:
                raise StrengthPolicyError(
                    f"gene_overrides[{gene!r}] names unknown criterion {criterion!r} (not on the ladder)"
                )
            if not isinstance(strengths_raw, dict):
                raise StrengthPolicyError(f"gene_overrides[{gene!r}][{criterion!r}] must be a mapping")

            ladder_set = set(ladder.criteria[criterion])
            per_criterion: dict[str, StrengthPolicyRecord] = {}
            for strength, raw_record in strengths_raw.items():
                if strength not in ladder_set:
                    raise StrengthPolicyError(
                        f"gene_overrides[{gene!r}][{criterion!r}] names strength {strength!r} "
                        f"not on {criterion!r}'s ladder"
                    )
                per_criterion[strength] = _validate_record_dict(
                    criterion, strength, raw_record, scorer_strength_vocab=scorer_strength_vocab
                )
            per_gene[criterion] = per_criterion
        gene_overrides[gene] = per_gene

    return StrengthPolicy(
        policy_id=policy_id,
        version=str(version),
        status=status,
        owner_approved=owner_approved,
        default_disposition=default_disposition,
        records=records,
        gene_overrides=gene_overrides,
        ladder=ladder,
        scorer_strength_vocab={k: tuple(v) for k, v in scorer_strength_vocab.items()},
    )


def _lookup_record(
    policy: StrengthPolicy, *, gene_name: str | None, criterion: str, strength: str
) -> tuple[StrengthPolicyRecord, bool]:
    """Resolve the effective `StrengthPolicyRecord` for a call: a gene
    override, if one is configured for this exact (gene, criterion,
    strength), always wins over the base `records` entry. Returns
    `(record, override_applied)`."""
    if gene_name is not None:
        per_gene = policy.gene_overrides.get(gene_name)
        if per_gene is not None:
            per_criterion = per_gene.get(criterion)
            if per_criterion is not None and strength in per_criterion:
                return per_criterion[strength], True

    per_criterion = policy.records.get(criterion)
    if per_criterion is not None and strength in per_criterion:
        return per_criterion[strength], False

    # Defensive fallback only -- load_strength_policy's exhaustive-schema
    # validation guarantees every ladder (criterion, strength) pair has a
    # `records` entry, so this should be unreachable in practice.
    return StrengthPolicyRecord(disposition=policy.default_disposition, emit=None), False


def apply_strength_policy(
    *, record: Mapping[str, Any], call: Mapping[str, Any], policy: StrengthPolicy
) -> StrengthPolicyDecision:
    """Reconcile one fired `call` (`{"criterion", "strength", "direction",
    "rationale", ...}`) against `policy`, returning a pure, deterministic
    `StrengthPolicyDecision`.

    Raises `UnknownStrengthPolicyPairError` if `(criterion, strength)` is
    not on the policy's `StrengthLadder` at all -- there is no
    `default_disposition` fallback for a scorer/ladder drift bug.

    Fails closed to `manual` for THE WHOLE `record` whenever the policy
    itself is not active (`status != "approved"` or `owner_approved is
    not True`), regardless of what disposition the record configures.
    """
    criterion = call["criterion"]
    strength = call["strength"]

    ladder_strengths = policy.ladder.criteria.get(criterion)
    if ladder_strengths is None or strength not in ladder_strengths:
        raise UnknownStrengthPolicyPairError(
            f"({criterion!r}, {strength!r}) is not on the strength ladder"
        )

    gene_name = record.get("gene_name") if isinstance(record, Mapping) else None
    configured_record, override_applied = _lookup_record(
        policy, gene_name=gene_name, criterion=criterion, strength=strength
    )

    if policy.is_active:
        disposition = configured_record.disposition
        emit = configured_record.emit
    else:
        # Owner has not approved this policy for auto-behavior -- every
        # call it sees routes the whole record to manual, no matter what
        # the (still schema-valid) configured disposition would have done.
        disposition = "manual"
        emit = None

    audit: dict[str, Any] = {
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "policy_status": policy.status,
        "owner_approved": policy.owner_approved,
        "criterion": criterion,
        "requested_strength": strength,
        "disposition": disposition,
        "gene_name": gene_name,
        "gene_override_applied": override_applied and policy.is_active,
    }

    if disposition in _EMITTING_DISPOSITIONS:
        emitted_call = {**call, "strength": emit}
        audit["emitted_strength"] = emit
        return StrengthPolicyDecision(
            criterion=criterion,
            requested_strength=strength,
            disposition=disposition,
            emitted_call=emitted_call,
            manual_record=None,
            audit=audit,
        )

    if disposition == "manual":
        return StrengthPolicyDecision(
            criterion=criterion,
            requested_strength=strength,
            disposition="manual",
            emitted_call=None,
            manual_record=dict(record),
            audit=audit,
        )

    # forbid: drop only this call -- the record's other calls are untouched.
    return StrengthPolicyDecision(
        criterion=criterion,
        requested_strength=strength,
        disposition="forbid",
        emitted_call=None,
        manual_record=None,
        audit=audit,
    )
