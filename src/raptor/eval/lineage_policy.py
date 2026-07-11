"""Slot 2 sec 1.2 `lineage_policy.py` — the BIAS criterion lineage policy loader.

`configs/eval/bias_lineage.yaml` is the single machine-readable source of
truth for which of the 28 canonical ACMG-2015 codes the pinned BIAS-3.0.0
engine can actually fire (`can_fire`, statically derived -- never from
census incidence or RAPTOR's own included/automatable config), the 9
BIAS-internal stubs that never fire (`structurally_forbidden`), and the
per-criterion data-lineage classification + validation/production
disposition (ADR-0009 / PRD-08 Task C).

`load_lineage_policy` is fail-closed: an unknown lineage class, disposition,
or marker token, a duplicate/missing/unknown criterion code, a malformed
28/19/9 partition, a wildcard `oracle_allowed`, or a `deferred` record
missing its `decision_dependency` all raise `LineagePolicyError` at load
time. This module never imports `bias_2015`/AGPL BIAS code and never opens
a label/benchmark/held-out file (ADR-0007/R-A2/H1) -- it carries only
lineage facts + source citations (file/symbol/lines).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .config import VALID_CRITERIA

#: Schema metadata only (slot 2 sec 1.1) -- the exact BIAS version/commit
#: this policy file must be pinned to. A config claiming a different pin is
#: a version drift, not a new fact, and must raise. This is NOT a record of
#: *which* criteria can fire -- that fact lives only in
#: `configs/eval/bias_lineage.yaml` (single source of runtime policy truth)
#: and is independently locked by `tests/fixtures/bias_lineage_source_oracle.json`.
_BIAS_VERSION = "3.0.0"
_BIAS_COMMIT = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"

#: Exhaustive, fail-closed lineage-class taxonomy (slot 2 sec 0.6). The
#: policy file's `lineage_classes` list must equal this exact enum -- no
#: more, no less. Schema metadata only, not a per-criterion policy record.
_LINEAGE_CLASSES: frozenset[str] = frozenset({
    "label_independent_population",
    "label_independent_reference_or_predictor",
    "same_variant_clinvar",
    "cross_variant_clinvar",
    "aggregate_clinvar",
    "literature_unvalidated",
    "manual_or_external_input",
    "unknown",
})

#: Exhaustive, fail-closed disposition enum (slot 2 sec 1.1). The policy
#: file's `dispositions` list must equal this exact enum -- no more, no
#: less. Schema metadata only, not a per-criterion policy record.
_DISPOSITIONS: frozenset[str] = frozenset({"allowed", "requires_heldout_mask", "forbidden", "deferred"})

#: Partition CARDINALITY only (slot 2 sec 0.1/0.2/0.3): the 28 canonical
#: codes split into exactly 19 can-fire + 9 structurally-forbidden stubs.
#: This is a schema shape constraint on the fixed 28-code taxonomy -- it
#: never records *which* 19/9 codes those are (that is a policy fact owned
#: by the YAML file alone, never duplicated/hardcoded here).
_CAN_FIRE_COUNT = 19
_STRUCTURALLY_FORBIDDEN_COUNT = 9

_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "bias_version",
    "bias_commit",
    "lineage_classes",
    "dispositions",
    "all_criteria",
    "can_fire",
    "structurally_forbidden",
    "markers",
    "transitive_suspect",
    "oracle_allowed",
    "records",
)

#: A `deferred` disposition MUST name the decision it is waiting on --
#: never silently self-resolve (slot 3, D1/BS2).
_DEFERRING_DISPOSITION = "deferred"

#: No wildcard/regex/catch-all char is ever a legitimate criterion code or
#: marker token (slot 2 sec 1.1/1.2 -- schema rejects).
_WILDCARD_CHARS: frozenset[str] = frozenset({"*", "?", "[", "]", "(", ")", "{", "}", "^", "$", "."})


class LineagePolicyError(ValueError):
    """Raised on a malformed/fail-closed `configs/eval/bias_lineage.yaml` (slot 2 sec 1.2)."""


@dataclass(frozen=True)
class StructuralStub:
    """One BIAS-internal stub code (slot 2 sec 0.3): can never fire from
    BIAS's own evaluators; a non-zero firing can only arrive via the
    external supplemental-call injection path (fail-closed, not a no-op)."""

    criterion: str
    reason: str
    bias_anchor: str


@dataclass(frozen=True)
class SourceDependencies:
    """A can-fire criterion's direct vs transitive data-source dependency
    (slot 2 sec 0.6) -- which BIAS loader/generator built the comparator
    resource, not the rationale English text."""

    direct: tuple[str, ...] = field(default_factory=tuple)
    transitive: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LineageRecord:
    """One can-fire criterion's lineage classification + disposition (slot
    2 sec 0.6/1.1). `lineage_class` is the policy taxonomy (static, never
    overridden by marker corroboration); `validation_disposition` gates the
    ClinVar-labelled benchmark audit, `production_disposition` gates real
    VUS scoring (they legitimately differ for the transitive-ClinVar set,
    ADR-0009). A `deferred` disposition always carries a non-empty
    `decision_dependency` and a non-empty `decision_rationale`; every
    deferral must state both what decision is owed and why the criterion is
    not currently authorized."""

    criterion: str
    lineage_class: str
    source_dependencies: SourceDependencies
    bias_anchors: tuple[str, ...]
    data_artifacts: tuple[str, ...]
    validation_disposition: str
    production_disposition: str
    rationale_markers: tuple[str, ...]
    notes: str
    decision_dependency: str
    decision_rationale: str = ""


@dataclass(frozen=True)
class LineagePolicy:
    """Frozen, schema-validated BIAS criterion lineage policy (slot 2 sec 1.2)."""

    bias_version: str
    bias_commit: str
    lineage_classes: frozenset[str]
    dispositions: frozenset[str]
    all_criteria: frozenset[str]
    can_fire: frozenset[str]
    structurally_forbidden: tuple[StructuralStub, ...]
    markers: frozenset[str]
    transitive_suspect: tuple[str, ...]
    oracle_allowed: tuple[str, ...]
    records: Mapping[str, LineageRecord]
    forbidden: frozenset[str]

    def disposition_of(self, criterion: str) -> str:
        """The `validation_disposition` of a can-fire criterion -- the
        disposition the eval-time audit gates on (slot 2 sec 1.4)."""
        return self.records[criterion].validation_disposition

    def lineage_of(self, criterion: str) -> str:
        """The static `lineage_class` of a can-fire criterion."""
        return self.records[criterion].lineage_class


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise LineagePolicyError(f"missing required policy key: {key!r}")
    return mapping[key]


def _require_no_wildcard(value: str, *, ctx: str) -> None:
    if not value or value != value.strip():
        raise LineagePolicyError(f"{ctx} must be a non-blank, untrimmed-safe token, got {value!r}")
    if any(ch in _WILDCARD_CHARS for ch in value):
        raise LineagePolicyError(f"{ctx} must not contain a wildcard/regex character: {value!r}")


def _require_no_duplicates(values: list[str], *, ctx: str) -> None:
    if len(values) != len(set(values)):
        raise LineagePolicyError(f"{ctx} contains a duplicate entry: {values!r}")


def load_lineage_policy(path: str | Path) -> LineagePolicy:
    """Load + schema-validate `configs/eval/bias_lineage.yaml` (slot 2 sec
    1.2). Fail-closed on any unknown/missing/duplicate criterion, unknown
    lineage class/disposition/marker, an unpinned `bias_version`/
    `bias_commit`, a malformed 28/19/9 partition, wildcard `oracle_allowed`,
    or a `deferred` record missing its `decision_dependency`. The only
    hardcoded facts are SCHEMA metadata -- the pinned BIAS version/commit,
    the exhaustive lineage-class/disposition enums, and the 19/9 partition
    cardinality -- never *which* criteria can fire; that policy fact is
    owned solely by this YAML file (and locked independently, for tests,
    by `tests/fixtures/bias_lineage_source_oracle.json`).
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LineagePolicyError(f"policy root must be a mapping, got {type(raw).__name__}")

    for key in _REQUIRED_TOP_KEYS:
        _require(raw, key)

    bias_version = str(raw["bias_version"])
    if bias_version != _BIAS_VERSION:
        raise LineagePolicyError(
            f"`bias_version` must equal the exact pinned {_BIAS_VERSION!r}; got {bias_version!r}"
        )
    bias_commit = str(raw["bias_commit"])
    if bias_commit != _BIAS_COMMIT:
        raise LineagePolicyError(
            f"`bias_commit` must equal the exact pinned {_BIAS_COMMIT!r}; got {bias_commit!r}"
        )

    lineage_classes_list = [str(c) for c in raw["lineage_classes"]]
    _require_no_duplicates(lineage_classes_list, ctx="`lineage_classes`")
    lineage_classes = frozenset(lineage_classes_list)
    if lineage_classes != _LINEAGE_CLASSES:
        raise LineagePolicyError(
            f"`lineage_classes` must equal the exact schema enum {sorted(_LINEAGE_CLASSES)!r}; "
            f"got {sorted(lineage_classes)!r}"
        )

    dispositions_list = [str(d) for d in raw["dispositions"]]
    _require_no_duplicates(dispositions_list, ctx="`dispositions`")
    dispositions = frozenset(dispositions_list)
    if dispositions != _DISPOSITIONS:
        raise LineagePolicyError(
            f"`dispositions` must equal the exact schema enum {sorted(_DISPOSITIONS)!r}; "
            f"got {sorted(dispositions)!r}"
        )

    all_criteria_list = [str(c) for c in raw["all_criteria"]]
    _require_no_duplicates(all_criteria_list, ctx="`all_criteria`")
    all_criteria = frozenset(all_criteria_list)
    if all_criteria != VALID_CRITERIA:
        raise LineagePolicyError(
            "`all_criteria` must equal the exact 28 canonical ACMG-2015 codes; "
            f"got {sorted(all_criteria)!r}"
        )

    can_fire_list = [str(c) for c in raw["can_fire"]]
    _require_no_duplicates(can_fire_list, ctx="`can_fire`")
    can_fire = frozenset(can_fire_list)

    stub_entries = raw["structurally_forbidden"]
    if not isinstance(stub_entries, list):
        raise LineagePolicyError("`structurally_forbidden` must be a list")
    stubs: list[StructuralStub] = []
    stub_codes: list[str] = []
    for entry in stub_entries:
        criterion = str(_require(entry, "criterion"))
        reason = str(_require(entry, "reason"))
        bias_anchor = str(_require(entry, "bias_anchor"))
        stub_codes.append(criterion)
        stubs.append(StructuralStub(criterion=criterion, reason=reason, bias_anchor=bias_anchor))
    _require_no_duplicates(stub_codes, ctx="`structurally_forbidden`")
    stub_code_set = frozenset(stub_codes)

    if not can_fire.isdisjoint(stub_code_set):
        raise LineagePolicyError(
            f"`can_fire` and `structurally_forbidden` overlap: {sorted(can_fire & stub_code_set)!r}"
        )
    if can_fire | stub_code_set != all_criteria:
        raise LineagePolicyError(
            "`can_fire` (⊎) `structurally_forbidden` must exactly partition `all_criteria`; "
            f"union={sorted(can_fire | stub_code_set)!r} vs all_criteria={sorted(all_criteria)!r}"
        )
    if len(can_fire) != _CAN_FIRE_COUNT or len(stub_code_set) != _STRUCTURALLY_FORBIDDEN_COUNT:
        raise LineagePolicyError(
            "`can_fire`/`structurally_forbidden` must partition the 28 canonical codes into "
            f"exactly {_CAN_FIRE_COUNT}/{_STRUCTURALLY_FORBIDDEN_COUNT}; got "
            f"{len(can_fire)}/{len(stub_code_set)} (can_fire={sorted(can_fire)!r}, "
            f"structurally_forbidden={sorted(stub_code_set)!r})"
        )

    markers_raw = [str(m) for m in raw["markers"]]
    _require_no_duplicates([m.lower() for m in markers_raw], ctx="`markers`")
    for marker in markers_raw:
        if not marker or marker != marker.strip():
            raise LineagePolicyError(f"`markers` entry must be non-blank/trimmed: {marker!r}")
        if any(ch in _WILDCARD_CHARS for ch in marker):
            raise LineagePolicyError(f"`markers` entry must not contain a wildcard/regex character: {marker!r}")
    markers = frozenset(m.lower() for m in markers_raw)

    records_raw = raw["records"]
    if not isinstance(records_raw, dict):
        raise LineagePolicyError("`records` must be a mapping")
    record_codes = frozenset(str(c) for c in records_raw.keys())
    if record_codes != can_fire:
        raise LineagePolicyError(
            f"`records` keys must exactly equal `can_fire`; records={sorted(record_codes)!r} "
            f"vs can_fire={sorted(can_fire)!r}"
        )

    records: dict[str, LineageRecord] = {}
    for criterion, entry in records_raw.items():
        criterion = str(criterion)
        if not isinstance(entry, dict):
            raise LineagePolicyError(f"records[{criterion!r}] must be a mapping")

        lineage_class = str(_require(entry, "lineage_class"))
        if lineage_class not in lineage_classes:
            raise LineagePolicyError(
                f"records[{criterion!r}].lineage_class={lineage_class!r} is not one of "
                f"the declared `lineage_classes` {sorted(lineage_classes)!r}"
            )

        validation_disposition = str(_require(entry, "validation_disposition"))
        if validation_disposition not in dispositions:
            raise LineagePolicyError(
                f"records[{criterion!r}].validation_disposition={validation_disposition!r} is not one "
                f"of the declared `dispositions` {sorted(dispositions)!r}"
            )
        production_disposition = str(_require(entry, "production_disposition"))
        if production_disposition not in dispositions:
            raise LineagePolicyError(
                f"records[{criterion!r}].production_disposition={production_disposition!r} is not one "
                f"of the declared `dispositions` {sorted(dispositions)!r}"
            )

        rationale_markers = tuple(str(m) for m in entry.get("rationale_markers") or [])
        for token in rationale_markers:
            if token.lower() not in markers:
                raise LineagePolicyError(
                    f"records[{criterion!r}].rationale_markers token {token!r} is not in the "
                    "embedded `markers` vocabulary"
                )

        decision_dependency = str(entry.get("decision_dependency") or "").strip()
        is_deferred = _DEFERRING_DISPOSITION in (validation_disposition, production_disposition)
        if is_deferred and not decision_dependency:
            raise LineagePolicyError(
                f"records[{criterion!r}] carries a `deferred` disposition but no non-empty "
                "`decision_dependency` -- a deferral must name the decision it awaits"
            )

        decision_rationale = str(entry.get("decision_rationale") or "").strip()
        if is_deferred and not decision_rationale:
            raise LineagePolicyError(
                f"records[{criterion!r}] carries a `deferred` disposition but no non-empty "
                "`decision_rationale` -- every deferral must state why it is not authorized"
            )

        source_deps_raw = _require(entry, "source_dependencies")
        if not isinstance(source_deps_raw, dict):
            raise LineagePolicyError(f"records[{criterion!r}].source_dependencies must be a mapping")
        source_dependencies = SourceDependencies(
            direct=tuple(str(d) for d in source_deps_raw.get("direct") or []),
            transitive=tuple(str(d) for d in source_deps_raw.get("transitive") or []),
        )

        records[criterion] = LineageRecord(
            criterion=criterion,
            lineage_class=lineage_class,
            source_dependencies=source_dependencies,
            bias_anchors=tuple(str(a) for a in entry.get("bias_anchors") or []),
            data_artifacts=tuple(str(a) for a in entry.get("data_artifacts") or []),
            validation_disposition=validation_disposition,
            production_disposition=production_disposition,
            rationale_markers=rationale_markers,
            notes=str(entry.get("notes") or ""),
            decision_dependency=decision_dependency,
            decision_rationale=decision_rationale,
        )

    oracle_allowed_list = [str(c) for c in raw["oracle_allowed"]]
    for entry in oracle_allowed_list:
        if entry not in VALID_CRITERIA:
            raise LineagePolicyError(
                f"`oracle_allowed` entry {entry!r} is not a canonical ACMG-2015 code "
                "(wildcard/catch-all entries are rejected)"
            )
    _require_no_duplicates(oracle_allowed_list, ctx="`oracle_allowed`")
    oracle_allowed = tuple(oracle_allowed_list)

    transitive_suspect_list = [str(c) for c in raw["transitive_suspect"]]
    _require_no_duplicates(transitive_suspect_list, ctx="`transitive_suspect`")
    for criterion in transitive_suspect_list:
        if criterion not in can_fire:
            raise LineagePolicyError(
                f"`transitive_suspect` entry {criterion!r} is not a can-fire criterion"
            )
    transitive_suspect = tuple(transitive_suspect_list)

    forbidden = frozenset(
        criterion for criterion, record in records.items() if record.validation_disposition == "forbidden"
    )

    return LineagePolicy(
        bias_version=bias_version,
        bias_commit=bias_commit,
        lineage_classes=lineage_classes,
        dispositions=dispositions,
        all_criteria=all_criteria,
        can_fire=can_fire,
        structurally_forbidden=tuple(stubs),
        markers=markers,
        transitive_suspect=transitive_suspect,
        oracle_allowed=oracle_allowed,
        records=records,
        forbidden=forbidden,
    )
