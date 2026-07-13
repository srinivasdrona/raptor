"""Slot 2 sec 1.4 `lineage_audit.py` — total audit + separate fail-closed gate.

`audit_lineage` is a TOTAL function: it always returns the complete
`LineageAuditReport` (including `blocked=True`) and never raises merely
because blockers exist. `enforce_lineage` is the ONLY place a gate
exception (`LineageGateError`) is raised, and only iff `report.blocked`.

Before building a report, `audit_lineage` calls
`lineage_registry.assert_registry_consistency` so a drifted scorer/eval
registry raises before any (potentially wrong) report is produced. Its
`would_be_scored` verdict is computed EXACTLY the way
`combine.implied_direction` derives its scored set (normalized
`eval_config.automatable_criteria` ∩ `VALID_CRITERIA`, minus
`FORBIDDEN_CRITERIA`) -- never independently re-derived from the scorer's
`included_criteria` -- so the audit can never diverge from what would
actually be scored (CP-1).

Reads the raw fired-criteria mapping of each `BiasRecord` directly (a
criterion is fired iff its `(score, text)` tuple has `score > 0`) --
classification of an unknown/stub code never depends on `parse_rationale`
succeeding on it (an unrecognized code must never abort the audit before it
can be reported). Incidence (`total_fired`, `example_variant_ids`) is
reported for every fired criterion; it never sets lineage/disposition --
those come only from the static `LineagePolicy`. Marker detection scans
EVERY fired rationale row across all records (PRD-08 FR-C1), not just the
bounded example bucket -- a hit is tracked as a per-criterion boolean and
each row's text is discarded immediately after the check, so no unbounded
rationale text is retained.

No `bias_2015`/AGPL import, no benchmark/held-out/label file is opened
here (ADR-0007/R-A2/H1) -- only `BiasRecord`s + the lineage policy + the
scorer/eval config registries.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .config import FORBIDDEN_CRITERIA, VALID_CRITERIA
from .lineage_registry import assert_registry_consistency

if TYPE_CHECKING:
    from raptor.eval.config import EvalConfig
    from raptor.scorer.config import ScorerConfig
    from raptor.scorer.model import BiasRecord

    from .lineage_policy import LineagePolicy

#: Dispositions that block a would-be-scored criterion (slot 2 sec 1.4.2,
#: rule (i)) unless explicitly Oracle-authorized (`oracle_allowed`).
_BLOCKING_DISPOSITIONS: frozenset[str] = frozenset({"forbidden", "requires_heldout_mask", "deferred"})

#: Bound on how many example variant ids a report carries per criterion --
#: deterministic (sorted), never unbounded.
_MAX_EXAMPLE_VARIANT_IDS = 5

#: `detection_source` advisory enum (slot 2 sec 1.4.1) -- separate from the
#: policy `lineage_class` taxonomy; never overrides a static disposition.
_DETECTION_MARKER = "marker_detected"
_DETECTION_TRANSITIVE = "transitive_suspect_only"
_DETECTION_STATIC = "static_lineage"

#: Fallback classification for a criterion that fired but is not a
#: canonical ACMG-2015 code at all (rule (iii)) -- fail-closed default
#: bucket (slot 2 sec 0.6, "any other | unknown").
_UNKNOWN_LINEAGE_CLASS = "unknown"
#: Fallback classification for a fired BIAS-internal stub code (rule (ii))
#: -- can only arrive via the external supplemental-call injection path.
_STUB_LINEAGE_CLASS = "manual_or_external_input"


class LineageGateError(Exception):
    """Raised by `enforce_lineage` iff `report.blocked` -- the only place
    this module raises on a well-formed-but-blocked audit report. Carries
    the full report so a caller can inspect/log/persist it."""

    def __init__(
        self,
        report: "LineageAuditReport",
        blocking_criteria: Iterable[str] | None = None,
    ) -> None:
        self.report = report
        self.blocking_criteria = tuple(
            sorted(blocking_criteria if blocking_criteria is not None else report.blocking_criteria)
        )
        super().__init__(
            "BIAS lineage gate blocked: " + ", ".join(self.blocking_criteria)
        )


@dataclass(frozen=True)
class LineageAuditItem:
    """One fired criterion's audit outcome (slot 2 sec 1.4.2). `disposition`
    is the criterion's `validation_disposition` (the eval-time gate this
    audit enforces); `detection_source` is advisory only and never a
    lineage-class value."""

    criterion: str
    total_fired: int
    would_be_scored: bool
    lineage_class: str
    disposition: str
    detection_source: str
    example_variant_ids: tuple[str, ...]
    blocks: bool

    def to_dict(self) -> dict:
        return {
            "criterion": self.criterion,
            "total_fired": self.total_fired,
            "would_be_scored": self.would_be_scored,
            "lineage_class": self.lineage_class,
            "disposition": self.disposition,
            "detection_source": self.detection_source,
            "example_variant_ids": list(self.example_variant_ids),
            "blocks": self.blocks,
        }


@dataclass(frozen=True)
class LineageAuditReport:
    """Total audit output (slot 2 sec 1.4.2): always produced, even when
    `blocked` is True. `content_hash()`/`to_dict()`/`render()` are
    deterministic -- a permutation of the same input record multiset (any
    row order) is hash-identical; duplicating a record changes its
    `total_fired` incidence count and therefore CAN change the hash, even
    though the disposition/blocked verdict itself never changes."""

    bias_version: str
    bias_commit: str
    items: tuple[LineageAuditItem, ...]
    blocked: bool
    blocking_criteria: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "bias_version": self.bias_version,
            "bias_commit": self.bias_commit,
            "items": [item.to_dict() for item in self.items],
            "blocked": self.blocked,
            "blocking_criteria": list(self.blocking_criteria),
        }

    def content_hash(self) -> str:
        """Deterministic sha256 over the canonical JSON body -- excludes no
        run metadata because this report carries none (a fresh report is
        rebuilt on every `audit_lineage` call, never mutated with a
        wall-clock stamp). A permutation of the same input record multiset
        always hashes identically; duplicating a record changes incidence
        (`total_fired`) and so may change the hash."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def render(self) -> str:
        """A deterministic, human-readable rendering of the report."""
        lines = [
            f"BIAS lineage audit -- bias_version={self.bias_version} bias_commit={self.bias_commit}",
            f"blocked={self.blocked} blocking_criteria={list(self.blocking_criteria)}",
        ]
        for item in self.items:
            lines.append(
                f"  {item.criterion}: total_fired={item.total_fired} "
                f"would_be_scored={item.would_be_scored} lineage_class={item.lineage_class} "
                f"disposition={item.disposition} detection_source={item.detection_source} "
                f"blocks={item.blocks} examples={list(item.example_variant_ids)}"
            )
        return "\n".join(lines)


def _fired_criteria(record: "BiasRecord") -> Iterable[tuple[str, str]]:
    """Yield `(CRITERION_UPPER, rationale_text)` for every entry in a
    `BiasRecord.criteria` flat mapping whose fired int is > 0. Reads the
    RAW mapping directly -- never depends on `parse_rationale` succeeding
    on an unknown/stub code (slot 2 sec 1.4.2)."""
    for key, value in record.criteria.items():
        fired_int, explanation = value[0], value[1]
        if int(fired_int) > 0:
            yield str(key).strip().upper(), str(explanation)


def _detection_source(criterion: str, marker_hit: bool, policy: "LineagePolicy") -> str:
    if marker_hit:
        return _DETECTION_MARKER
    if criterion in set(policy.transitive_suspect):
        return _DETECTION_TRANSITIVE
    return _DETECTION_STATIC


def audit_lineage(
    records: Iterable["BiasRecord"],
    policy: "LineagePolicy",
    scorer_config: "ScorerConfig",
    eval_config: "EvalConfig",
) -> LineageAuditReport:
    """Total audit over every fired criterion across `records` (slot 2 sec
    1.4.2). ALWAYS returns the complete report -- never raises merely
    because a criterion blocks; only `enforce_lineage` raises.

    Before anything else, `assert_registry_consistency` is called so a
    drifted scorer/eval registry raises `LineageRegistryMismatchError`
    before a (potentially wrong) report is ever built (CP-1: the audit
    must never silently diverge from `combine.implied_direction`'s
    scored set).

    Fail-closed block rule -- a fired criterion blocks iff:
      (i)   it would be scored -- computed EXACTLY as
            `combine.implied_direction` computes its scored set (its
            normalized code is in `eval_config.automatable_criteria`, is a
            canonical `VALID_CRITERIA` code, and is not in
            `FORBIDDEN_CRITERIA`) -- and its `validation_disposition` is
            `forbidden`/`requires_heldout_mask`/`deferred` and it is not in
            `policy.oracle_allowed`; or
      (ii)  it is a valid ACMG code that is a BIAS-internal stub (not
            can-fire) firing with a non-zero score (unauthorized
            supplemental injection); or
      (iii) it is not a canonical ACMG-2015 code at all.
    """
    assert_registry_consistency(policy, scorer_config, eval_config)

    automatable = {str(c).strip().upper() for c in eval_config.automatable_criteria}
    stub_codes = {stub.criterion for stub in policy.structurally_forbidden}
    oracle_allowed = set(policy.oracle_allowed)

    totals: dict[str, int] = {}
    variant_ids: dict[str, set[str]] = {}
    examples_by_criterion: dict[str, list[str]] = {}
    marker_hit: dict[str, bool] = {}

    for record in records:
        for criterion, text in _fired_criteria(record):
            totals[criterion] = totals.get(criterion, 0) + 1
            variant_ids.setdefault(criterion, set()).add(record.variant_id)
            bucket = examples_by_criterion.setdefault(criterion, [])
            if len(bucket) < _MAX_EXAMPLE_VARIANT_IDS:
                bucket.append(text)
            # Marker detection must scan EVERY fired rationale (PRD-08
            # FR-C1), not just the bounded example bucket above -- check
            # and discard this row's text immediately so no unbounded
            # rationale text is retained just to answer this question.
            if not marker_hit.get(criterion, False):
                lowered = text.lower()
                if any(marker in lowered for marker in policy.markers):
                    marker_hit[criterion] = True

    items: list[LineageAuditItem] = []
    blocking: list[str] = []

    for criterion in sorted(totals):
        total_fired = totals[criterion]
        examples = tuple(sorted(variant_ids[criterion])[:_MAX_EXAMPLE_VARIANT_IDS])

        if criterion not in VALID_CRITERIA:
            # Rule (iii): not a canonical ACMG-2015 code at all.
            item = LineageAuditItem(
                criterion=criterion,
                total_fired=total_fired,
                would_be_scored=False,
                lineage_class=_UNKNOWN_LINEAGE_CLASS,
                disposition="forbidden",
                detection_source=_DETECTION_STATIC,
                example_variant_ids=examples,
                blocks=True,
            )
        elif criterion in stub_codes:
            # Rule (ii): a BIAS-internal stub fired -- unauthorized
            # supplemental injection, fail-closed (never a no-op).
            item = LineageAuditItem(
                criterion=criterion,
                total_fired=total_fired,
                would_be_scored=False,
                lineage_class=_STUB_LINEAGE_CLASS,
                disposition="forbidden",
                detection_source=_DETECTION_STATIC,
                example_variant_ids=examples,
                blocks=True,
            )
        else:
            record = policy.records[criterion]
            would_be_scored = (
                criterion in automatable
                and criterion in VALID_CRITERIA
                and criterion not in FORBIDDEN_CRITERIA
            )
            disposition = record.validation_disposition
            blocks = (
                would_be_scored
                and disposition in _BLOCKING_DISPOSITIONS
                and criterion not in oracle_allowed
            )
            item = LineageAuditItem(
                criterion=criterion,
                total_fired=total_fired,
                would_be_scored=would_be_scored,
                lineage_class=record.lineage_class,
                disposition=disposition,
                detection_source=_detection_source(criterion, marker_hit.get(criterion, False), policy),
                example_variant_ids=examples,
                blocks=blocks,
            )

        items.append(item)
        if item.blocks:
            blocking.append(criterion)

    return LineageAuditReport(
        bias_version=policy.bias_version,
        bias_commit=policy.bias_commit,
        items=tuple(items),
        blocked=bool(blocking),
        blocking_criteria=tuple(sorted(blocking)),
    )


def enforce_lineage(
    report: LineageAuditReport,
    *,
    authorized_masked_criteria: Iterable[str] = (),
) -> None:
    """Raise on every blocker not covered by a verified held-out mask.

    The default remains fully fail-closed. A terminal caller may authorize
    only criteria whose static disposition is `requires_heldout_mask`, after
    separately verifying the mask attestation.
    """
    authorized = {str(value).strip().upper() for value in authorized_masked_criteria}
    disposition_by_criterion = {
        item.criterion: item.disposition for item in report.items
    }
    invalid_authorizations = {
        criterion
        for criterion in authorized
        if criterion in disposition_by_criterion
        and disposition_by_criterion[criterion] != "requires_heldout_mask"
    }
    if invalid_authorizations:
        raise ValueError(
            "only requires_heldout_mask criteria may be mask-authorized; got "
            f"{sorted(invalid_authorizations)!r}"
        )
    remaining = set(report.blocking_criteria) - authorized
    if remaining:
        raise LineageGateError(report, remaining)
