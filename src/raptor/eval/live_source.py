"""PRD-08 §3.B / §10.3 / §11.2 `live_source.py` — the arm's-length live-eval
evidence adapter (canonical-adapter slot 2 contract, leakage-safe framing).

`BiasEvidenceSource` preflights -- manifest + BIAS load, canonical-SPDI
reverse-map + normalize + join, exact-set/bijection, config parity, and the
completed BIAS lineage gate (`audit_lineage` -> `enforce_lineage`) -- BEFORE
serving anything, then satisfies the `EvidenceSource` Protocol
`raptor.eval.harness.run_eval` expects:
``get_evidence(variant_id) -> Iterable[(criterion, strength, direction)]``.

Evidence is built ONLY from `raptor.scorer.parse.parse_rationale`'s FIRED
calls (reused verbatim, never re-implemented). `BiasRecord.acmg_classification`
(BIAS's own combined call) is parsed by `BiasTsvSource` -- the column is
contractually required -- but this module never reads it to build evidence
(FR-B4): mutating/blanking that column value leaves `get_evidence` output
byte-identical.

Label-free by construction (FR-B6): the only inputs are a committed BIAS
TSV, a label-free identity manifest, the scorer/eval configs, and an
injected `CanonicalBiasNormalizer` -- no benchmark/held-out/label file is
ever opened here, and no `bias_2015`/AGPL import crosses the boundary
(ADR-0007).

The join key is canonical GRCh38 SPDI, never BIAS's raw echoed
`chromosome/position/refAllele/altAllele` string (ADR-0007 M1 -- indels
silently mis-join on a raw-string join). Each BIAS row's `chromosome` is
reverse-mapped to its RefSeq accession via the manifest's own
`{contig: accession}` pins (every manifest row already carries both), then
re-normalized through the injected `CanonicalBiasNormalizer` -- a reference
disagreement / normalization failure fails loud, never swallowed.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Tuple

from raptor.eval.config import EvalConfig, FORBIDDEN_CRITERIA
from raptor.eval.lineage_audit import audit_lineage, enforce_lineage
from raptor.eval.lineage_policy import load_lineage_policy
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.parse import parse_rationale

#: The completed BIAS lineage gate (ADR-0009) -- a pinned path, not a
#: constructor parameter (slot 2 sec 1): every preflight consumes the same
#: single source of gate-policy truth, never a caller-supplied variant.
_LINEAGE_POLICY_PATH = Path("configs/eval/bias_lineage.yaml")

#: The identity manifest's per-row field-set (slot 2 sec 1, preflight step
#: 1) -- exactly these four keys, no more, no fewer.
_MANIFEST_REQUIRED_FIELDS = frozenset({"variant_id", "vcf_key", "accession", "contig"})

#: One evidence tuple as `EvidenceSource.get_evidence` yields it
#: (`raptor.eval.combine.CriterionCall`'s shape) -- `(criterion, strength, direction)`.
CriterionCall = Tuple[str, str, str]


class CanonicalBiasNormalizer(Protocol):
    """Injected port (slot 2 sec 1): normalizes one BIAS-echoed coordinate to
    canonical GRCh38 SPDI. Returns the SPDI string or raises -- a reference
    disagreement / normalization failure is never caught here, only
    propagated (fail loud). Tests inject a deterministic fake; a future
    runtime wrapper adapts `SeqRepoGenomicNormalizer`/the pinned reference
    to this protocol."""

    def normalize(self, chromosome: str, position: int, ref: str, alt: str, accession: str) -> str: ...


class MalformedManifestError(ValueError):
    """Raised when a manifest row's field set is not exactly
    `{variant_id, vcf_key, accession, contig}`, or the manifest's own
    embedded `{contig: accession}` pins are internally inconsistent."""


class ManifestBijectionError(ValueError):
    """Raised when the manifest itself is not a bijection over its own
    `variant_id`s -- a duplicate identity within the manifest, independent
    of any BIAS join (`kind` names the specific breach)."""

    def __init__(self, kind: str, message: str | None = None) -> None:
        self.kind = kind
        super().__init__(message or f"manifest bijection breach: {kind}")


class ExactSetMismatchError(ValueError):
    """Raised on any join-completeness breach (slot 2 sec 1/3 -- no silent
    row loss). `sets_by_kind` always carries all four kinds
    (`duplicate_bias_row`, `duplicate_canonical_bias_row`, `unknown_bias_row`,
    `missing_holdout_row`), each a `frozenset[str]` (possibly empty). A
    semantic coordinate mismatch surfaces as `unknown_bias_row` +
    `missing_holdout_row` together, never a bespoke coordinate error."""

    def __init__(self, sets_by_kind: Mapping[str, "frozenset[str]"]) -> None:
        self.sets_by_kind = dict(sets_by_kind)
        breaches = {kind: sorted(ids) for kind, ids in self.sets_by_kind.items() if ids}
        super().__init__(f"exact-set join breach: {breaches}")


class ConfigConsistencyError(ValueError):
    """Raised when `eval_config.automatable_criteria` != `scorer_config.
    included_criteria` (both excluding `FORBIDDEN_CRITERIA`) -- eval must
    equal production (R-A2); never a second, independently-drifting filter."""


class UnknownVariantError(KeyError):
    """Raised when `get_evidence` is asked for a variant_id absent from the
    joined set -- never a silent empty list (fail loud)."""


def _normalized_criteria_set(criteria: Iterable[str]) -> "frozenset[str]":
    return frozenset(str(c).strip().upper() for c in criteria) - FORBIDDEN_CRITERIA


def _load_manifest(manifest_path: Path) -> list[dict[str, str]]:
    """Load + shape-validate the label-free identity manifest (JSON Lines,
    one row per held-out identity). Any row whose field-set is not exactly
    `_MANIFEST_REQUIRED_FIELDS` fails loud -- never silently coerced/dropped."""
    rows: list[dict[str, str]] = []
    text = Path(manifest_path).read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedManifestError(
                f"manifest line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(row, dict) or set(row.keys()) != _MANIFEST_REQUIRED_FIELDS:
            got = sorted(row.keys()) if isinstance(row, dict) else row
            raise MalformedManifestError(
                f"manifest row field-set must be exactly {sorted(_MANIFEST_REQUIRED_FIELDS)!r}; got {got!r}"
            )
        rows.append({str(k): str(v) for k, v in row.items()})
    return rows


def _contig_to_accession(manifest_rows: list[dict[str, str]]) -> dict[str, str]:
    """Build the BIAS `chromosome` -> RefSeq accession reverse map straight
    from the manifest's own per-row `{contig, accession}` pins (every held-out
    identity already carries both) -- no separate config file needed, and a
    contig pinned to two different accessions is a manifest-shape breach."""
    mapping: dict[str, str] = {}
    for row in manifest_rows:
        contig, accession = row["contig"], row["accession"]
        existing = mapping.get(contig)
        if existing is not None and existing != accession:
            raise MalformedManifestError(
                f"manifest contig {contig!r} maps to multiple accessions: {existing!r} and {accession!r}"
            )
        mapping[contig] = accession
    return mapping


class BiasEvidenceSource:
    """PRD-08 §3.B arm's-length live-eval `EvidenceSource` (canonical-adapter
    slot 2). Preflights at construction (fail-fast, G5); nothing is served on
    any preflight failure."""

    def __init__(
        self,
        bias_tsv_path: str | Path,
        manifest_path: str | Path,
        eval_config: EvalConfig,
        scorer_config: ScorerConfig,
        normalizer: CanonicalBiasNormalizer,
        *,
        authorized_masked_criteria: Iterable[str] = (),
    ) -> None:
        self._scorer_config = scorer_config

        # --- Step 1: load + validate the identity manifest. -----------------
        manifest_rows = _load_manifest(Path(manifest_path))
        manifest_ids = [row["variant_id"] for row in manifest_rows]
        dup_manifest_ids = {vid for vid, count in Counter(manifest_ids).items() if count > 1}
        if dup_manifest_ids:
            raise ManifestBijectionError(
                "duplicate_manifest_variant_id",
                f"manifest is not a bijection over its own variant_ids -- duplicates: {sorted(dup_manifest_ids)!r}",
            )
        manifest_id_set: frozenset[str] = frozenset(manifest_ids)
        contig_to_accession = _contig_to_accession(manifest_rows)

        # --- Step 2: load BIAS rows (reused 18-column contract parser). -----
        all_records: list[BiasRecord] = list(BiasTsvSource(bias_tsv_path).records())

        # Raw-level duplicate rows (same echoed chromosome:position:ref:alt,
        # BEFORE canonicalization) -- a straightforward TSV-level duplicate,
        # distinct from two DIFFERENT raw rows collapsing onto one canonical id.
        raw_key_counts = Counter(record.variant_id for record in all_records)
        duplicate_bias_row = {key for key, count in raw_key_counts.items() if count > 1}

        # --- Step 3: reverse-map + canonical-SPDI normalize (never a raw
        # `vcf_key` string join -- ADR-0007 M1). ----------------------------
        seen_raw_keys: set[str] = set()
        canonical_counts: Counter[str] = Counter()
        canonical_by_record: dict[str, BiasRecord] = {}
        unresolved_bias_row: set[str] = set()

        for record in all_records:
            if record.variant_id in seen_raw_keys:
                continue  # already accounted for in duplicate_bias_row above
            seen_raw_keys.add(record.variant_id)

            accession = contig_to_accession.get(record.chromosome)
            if accession is None:
                # No held-out identity ever uses this contig -- structurally
                # cannot join to any manifest row; report as unaccounted,
                # never guessed at an accession.
                unresolved_bias_row.add(record.variant_id)
                continue

            # Reference disagreement / normalization failure fails loud --
            # never caught, never routed around (slot 2 sec 1, AC-B7(b)).
            canonical_id = normalizer.normalize(
                record.chromosome, record.position, record.ref_allele, record.alt_allele, accession
            )
            canonical_counts[canonical_id] += 1
            canonical_by_record[canonical_id] = record

        # --- Step 4: exact-set + bijection over all manifest ids. -----------
        duplicate_canonical_bias_row = {cid for cid, count in canonical_counts.items() if count > 1}
        canonical_id_set: frozenset[str] = frozenset(canonical_counts.keys())
        unknown_bias_row = unresolved_bias_row | (canonical_id_set - manifest_id_set)
        missing_holdout_row = manifest_id_set - canonical_id_set

        sets_by_kind = {
            "duplicate_bias_row": frozenset(duplicate_bias_row),
            "duplicate_canonical_bias_row": frozenset(duplicate_canonical_bias_row),
            "unknown_bias_row": frozenset(unknown_bias_row),
            "missing_holdout_row": frozenset(missing_holdout_row),
        }
        if any(sets_by_kind.values()):
            raise ExactSetMismatchError(sets_by_kind)

        # --- Step 5: config parity (eval == production). --------------------
        automatable = _normalized_criteria_set(eval_config.automatable_criteria)
        included = _normalized_criteria_set(scorer_config.included_criteria)
        if automatable != included:
            raise ConfigConsistencyError(
                f"eval_config.automatable_criteria {sorted(automatable)!r} != "
                f"scorer_config.included_criteria {sorted(included)!r} (both excluding "
                "FORBIDDEN_CRITERIA) -- eval must equal production, never a second drifting filter"
            )

        # --- Step 6: the completed BIAS lineage gate (fail-closed). ---------
        policy = load_lineage_policy(_LINEAGE_POLICY_PATH)
        report = audit_lineage(all_records, policy, scorer_config, eval_config)
        enforce_lineage(
            report,
            authorized_masked_criteria=authorized_masked_criteria,
        )

        self.variant_ids: Tuple[str, ...] = tuple(sorted(manifest_id_set))
        self._by_canonical: Mapping[str, BiasRecord] = dict(canonical_by_record)
        self.lineage_report = report

    def get_evidence(self, variant_id: str) -> Tuple[CriterionCall, ...]:
        """Canonical SPDI id -> joined BIAS record -> every FIRED
        `parse_rationale` call as `(criterion.upper(), strength, direction)`.
        Never reads `acmg_classification` (FR-B4). An id absent from the
        joined set fails loud (`UnknownVariantError`), never a silent empty
        list."""
        record = self._by_canonical.get(variant_id)
        if record is None:
            raise UnknownVariantError(variant_id)
        calls = parse_rationale(record.criteria, self._scorer_config.strength_map)
        return tuple((call.criterion, call.strength, call.direction) for call in calls)

    def get_predictor_correction(self, variant_id: str, criterion: str, spec):
        """Return the auditable emitted-vs-corrected PP3/BP4 strength."""
        from .predictor_aggregation import recompute_strength

        record = self._by_canonical.get(variant_id)
        if record is None:
            raise UnknownVariantError(variant_id)
        normalized = str(criterion).strip().upper()
        entry = record.criteria.get(normalized.lower())
        if entry is None or int(entry[0]) <= 0:
            raise ValueError(
                f"criterion {normalized} did not fire for variant {variant_id}"
            )
        return recompute_strength(normalized, str(entry[1]), spec)
