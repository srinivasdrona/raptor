"""ADR-0009 / masked-resources slot 2 `mask_clinvar.py` — the ClinVar-source
masking tool + independent mask-conservation audit.

This module masks the upstream ClinVar source (VCF/Nirvana JSON annotation
+ `variant_summary`/`submission_summary` tables) so the five transitive
comparator resources BIAS-3.0.0 builds from ClinVar (`PS1, PM5, PM1, PP2,
BP1`) and the three direct-copy fallback inputs (`PS4, PP5, BP6`) can be
regenerated with the 2,577 frozen held-out identities removed -- masking
the upstream once masks every downstream resource at once (masked-resources
slot 1 leakage table). It never rebuilds a BIAS comparator resource itself:
the operator re-runs BIAS's *own* `generate_*.py` (arm's-length, ADR-0007/
0008) on the masked inputs this module emits, and `audit_mask_conservation`
independently re-verifies the operator's rebuilt output -- never trusting
the generator as its own oracle.

Boundaries (non-negotiable, slot 1/3):
  * Never imports `bias_2015`/BIAS preprocessing code and never opens a
    benchmark/held-out `label`/`source`/`review_status`/`variant_class`
    file or field -- only `row["variant_id"]` (already canonical GRCh38
    SPDI) and ClinVar record IDENTITY (coordinate or VariationID) are read.
  * Masking is by canonical GRCh38 SPDI identity, never raw coordinate
    string equality (an indel echo/shift must not survive unmasked).
  * A held-out id matching zero ClinVar records is an expected no-op
    (recorded, not an error); a held-out id matching MULTIPLE
    non-equivalent raw ClinVar records is fatal (`MaskAmbiguityError`) --
    never silently merged.
  * Masked outputs are written to a separate namespace; the full VUS
    comparator resources are never touched (`MaskConfig` refuses an
    overlapping `masked_namespace`/`full_resource_paths` pair at
    construction time).
  * `audit_mask_conservation` is TOTAL (never raises merely because a
    survivor/mismatch is found -- only on malformed input); it always
    independently RE-DERIVES every referenced identity and RE-COMPUTES
    every domain/gene aggregate from the masked ClinVar handed to it, never
    trusting a resource's own stored aggregate/cached total as its oracle
    (masked-resources slot 3, inversion failure 5, "aggregate laundering").
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

#: The five ClinVar-derived transitive comparator resources (slot 2 sec
#: 0.1) whose stored value is a DIRECT per-variant reference (one entry ==
#: one ClinVar record's own identity) rather than a recomputed aggregate.
#: `PS4`/`PP5`/`BP6` (direct-copy own-variant fallbacks) are audited the
#: same way -- a stored entry's own identity must not be held-out.
_DIRECT_REFERENCE_CRITERIA: frozenset[str] = frozenset({"PS1", "PM5", "PS4", "PP5", "BP6"})

#: The three aggregate ClinVar comparator resources (slot 2 sec 0.1) --
#: `PM1` (domain-level pathogenic rate) and `PP2`/`BP1` (gene-level
#: missense/truncating proportion). `group_field` names the per-record
#: attribute the audit groups by; `indicator_field` names the boolean
#: per-record attribute the audit sums; `count_key` is the stored
#: aggregate's field name for that sum (its `total` field is the group
#: size). These are audit-recomputation facts about the *aggregate shape*
#: each resource carries (masked-resources slot 1), never a copy of BIAS's
#: own aggregation code.
_AGGREGATE_CRITERIA_FIELDS: dict[str, dict[str, str]] = {
    "PM1": {"group_field": "domain", "indicator_field": "pathogenic", "count_key": "pathogenic_count"},
    "PP2": {"group_field": "gene", "indicator_field": "missense_pathogenic", "count_key": "missense_path"},
    "BP1": {"group_field": "gene", "indicator_field": "truncating_pathogenic", "count_key": "trunc_path"},
}


class MaskConfigError(ValueError):
    """Raised on a malformed/drifted `configs/eval/mask.yaml` or an invalid
    `MaskConfig` construction (blank/duplicate pin, unknown resource key,
    an `assembly` mismatch, or a `masked_namespace` overlapping a
    `full_resource_paths` entry -- invariant 5, never allowed to construct)."""


class HoldoutIdentityError(ValueError):
    """Raised on a held-out JSONL row missing `variant_id`, an
    un-normalizable `variant_id`, or a duplicate canonical identity --
    always fatal, never silently dropped (slot 2 sec 1)."""


class MaskReferenceError(ValueError):
    """Raised when a ClinVar record (or a comparator-resource entry, during
    audit) fails to normalize to a canonical identity -- never silently
    kept or dropped (slot 2 sec 1)."""


class MaskAmbiguityError(ValueError):
    """Raised when a single held-out canonical identity matches multiple
    non-equivalent raw ClinVar records within one input stream -- fatal,
    never silently merged/removed (slot 2 sec 1, slot 3 highest-risk
    inversion guard)."""


class Normalizer(Protocol):
    """The lightweight identity-normalization port this module depends on
    (distinct from `raptor.ingest.normalizer.Normalizer`, which needs a
    `RawVariant` + ingest config): `normalize(record) -> canonical GRCh38
    SPDI str`, raising on any record it cannot resolve. A real CLI wires a
    concrete adapter over `SeqRepoGenomicNormalizer` (coordinate rows) and
    a ClinVar VariationID->SPDI identity map (summary-table rows); tests
    inject a trivial fake."""

    def normalize(self, record: Any) -> str: ...


def _require_str(value: Any, *, ctx: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MaskConfigError(f"{ctx} must not be blank")
    return str(value)


def _reject_duplicates(values: Iterable[str], *, ctx: str) -> None:
    values = list(values)
    if len(values) != len(set(values)):
        raise MaskConfigError(f"{ctx} contains a duplicate entry: {values!r}")


def _paths_overlap(path_a: Path, path_b: Path) -> bool:
    """`True` iff `path_a` and `path_b` name the same location or one is
    nested inside the other (either direction) -- the AC-M7 output-path
    containment guard. Resolved (not merely string-compared) so `a/b/../c`
    vs `a/c` are correctly recognized as identical; `resolve(strict=False)`
    tolerates a not-yet-created masked-namespace directory."""
    a = path_a.resolve()
    b = path_b.resolve()
    if a == b:
        return True
    try:
        b.relative_to(a)
        return True
    except ValueError:
        pass
    try:
        a.relative_to(b)
        return True
    except ValueError:
        pass
    return False


@dataclass(frozen=True)
class MaskConfig:
    """Frozen, schema-validated view of `configs/eval/mask.yaml` (slot 2
    sec 2). Tests may construct this directly. Validation (at construction,
    via `__post_init__`, so a bad config can never be built and used):

      * `assembly`/`masked_namespace`/`bias_version` must not be blank.
      * `mask_criteria`/`direct_copy_fallbacks` must not contain a
        duplicate entry.
      * each `clinvar_inputs` entry names a non-blank, unique `stream` and
        a `resources` list that is a SUBSET of `mask_criteria` (union)
        `direct_copy_fallbacks` -- an unknown resource key is fail-closed.
      * `masked_namespace` must not equal or nest inside/around any
        `full_resource_paths` entry (invariant 5 -- AC-M7).
    """

    assembly: str
    mask_criteria: list[str]
    direct_copy_fallbacks: list[str]
    clinvar_inputs: list[dict[str, Any]]
    full_resource_paths: list[str]
    masked_namespace: str
    bias_version: str

    def __post_init__(self) -> None:
        _require_str(self.assembly, ctx="`assembly`")
        _require_str(self.masked_namespace, ctx="`masked_namespace`")
        _require_str(self.bias_version, ctx="`bias_version`")

        if not isinstance(self.mask_criteria, (list, tuple)):
            raise MaskConfigError("`mask_criteria` must be a list")
        if not isinstance(self.direct_copy_fallbacks, (list, tuple)):
            raise MaskConfigError("`direct_copy_fallbacks` must be a list")

        mask_criteria = [str(c).strip().upper() for c in self.mask_criteria]
        _reject_duplicates(mask_criteria, ctx="`mask_criteria`")
        direct_copy_fallbacks = [str(c).strip().upper() for c in self.direct_copy_fallbacks]
        _reject_duplicates(direct_copy_fallbacks, ctx="`direct_copy_fallbacks`")
        known_resources = frozenset(mask_criteria) | frozenset(direct_copy_fallbacks)

        if not isinstance(self.clinvar_inputs, list):
            raise MaskConfigError("`clinvar_inputs` must be a list")
        seen_streams: set[str] = set()
        normalized_inputs: list[dict[str, Any]] = []
        for entry in self.clinvar_inputs:
            if not isinstance(entry, dict):
                raise MaskConfigError(f"`clinvar_inputs` entry must be a mapping, got {entry!r}")
            stream = _require_str(entry.get("stream"), ctx="`clinvar_inputs[].stream`")
            if stream in seen_streams:
                raise MaskConfigError(f"duplicate `clinvar_inputs` stream pin: {stream!r}")
            seen_streams.add(stream)
            resources_raw = entry.get("resources")
            if resources_raw is None or not isinstance(resources_raw, (list, tuple)):
                raise MaskConfigError(f"`clinvar_inputs[{stream!r}].resources` must be a list")
            resources = [str(r).strip().upper() for r in resources_raw]
            unknown = sorted(set(resources) - known_resources)
            if unknown:
                raise MaskConfigError(
                    f"`clinvar_inputs[{stream!r}].resources` references unknown resource "
                    f"key(s) {unknown!r} -- must be a subset of `mask_criteria` "
                    "+ `direct_copy_fallbacks`"
                )
            normalized_inputs.append({"stream": stream, "resources": tuple(resources)})

        if not isinstance(self.full_resource_paths, (list, tuple)):
            raise MaskConfigError("`full_resource_paths` must be a list")
        full_resource_paths = [_require_str(p, ctx="`full_resource_paths[]`") for p in self.full_resource_paths]

        masked_path = Path(self.masked_namespace)
        for full_resource_path in full_resource_paths:
            if _paths_overlap(masked_path, Path(full_resource_path)):
                raise MaskConfigError(
                    f"`masked_namespace` {self.masked_namespace!r} overlaps a "
                    f"`full_resource_paths` entry {full_resource_path!r} -- refusing to write "
                    "masked output inside/over a full VUS comparator resource (invariant 5)"
                )

        # Frozen dataclass: normalize via `object.__setattr__` (never
        # reassign directly) so downstream code always sees the
        # canonicalized (stripped/upper-cased/deduped) values.
        object.__setattr__(self, "assembly", str(self.assembly))
        object.__setattr__(self, "mask_criteria", tuple(mask_criteria))
        object.__setattr__(self, "direct_copy_fallbacks", tuple(direct_copy_fallbacks))
        object.__setattr__(self, "clinvar_inputs", tuple(normalized_inputs))
        object.__setattr__(self, "full_resource_paths", tuple(full_resource_paths))
        object.__setattr__(self, "masked_namespace", str(self.masked_namespace))
        object.__setattr__(self, "bias_version", str(self.bias_version))


_REQUIRED_MASK_CONFIG_KEYS: tuple[str, ...] = (
    "assembly",
    "mask_criteria",
    "direct_copy_fallbacks",
    "clinvar_inputs",
    "full_resource_paths",
    "masked_namespace",
    "bias_version",
)

#: Single machine-readable pin for the requires-heldout-mask policy this
#: config's `mask_criteria` must stay a subset of (slot 2 sec 2) -- loaded
#: lazily (only inside `load_mask_config`) so this module never imports the
#: lineage policy loader merely to define `MaskConfig`/`mask_clinvar_source`.
_DEFAULT_LINEAGE_POLICY_PATH = "configs/eval/bias_lineage.yaml"


def load_mask_config(path: str | Path, ingest_config: Any) -> MaskConfig:
    """Load + schema-validate `configs/eval/mask.yaml` (slot 2 sec 2).

    Rejects an `assembly` other than `ingest_config.assembly`, and a
    `mask_criteria` set that is not a subset of the `requires_heldout_mask`
    criteria in `configs/eval/bias_lineage.yaml` (a config authored to mask
    fewer/different criteria than the static lineage policy requires is a
    silent mask-set shrink -- slot 3 highest-risk inversion failure 1).
    """
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MaskConfigError(f"mask config root must be a mapping, got {type(raw).__name__}")
    for key in _REQUIRED_MASK_CONFIG_KEYS:
        if key not in raw or raw[key] is None:
            raise MaskConfigError(f"missing required mask config key: {key!r}")

    assembly = _require_str(raw["assembly"], ctx="`assembly`")
    ingest_assembly = getattr(ingest_config, "assembly", None)
    if assembly != ingest_assembly:
        raise MaskConfigError(
            f"mask config `assembly` {assembly!r} != ingest config assembly {ingest_assembly!r}"
        )

    config = MaskConfig(
        assembly=assembly,
        mask_criteria=list(raw["mask_criteria"]),
        direct_copy_fallbacks=list(raw["direct_copy_fallbacks"]),
        clinvar_inputs=list(raw["clinvar_inputs"]),
        full_resource_paths=list(raw.get("full_resource_paths") or []),
        masked_namespace=_require_str(raw["masked_namespace"], ctx="`masked_namespace`"),
        bias_version=_require_str(raw["bias_version"], ctx="`bias_version`"),
    )

    from .lineage_policy import load_lineage_policy

    policy = load_lineage_policy(_DEFAULT_LINEAGE_POLICY_PATH)
    if policy.bias_version != config.bias_version:
        raise MaskConfigError(
            f"mask config `bias_version` {config.bias_version!r} != lineage policy "
            f"`bias_version` {policy.bias_version!r}"
        )
    requires_heldout_mask = frozenset(
        criterion
        for criterion, record in policy.records.items()
        if record.validation_disposition == "requires_heldout_mask"
    )
    extra = set(config.mask_criteria) - requires_heldout_mask
    if extra:
        raise MaskConfigError(
            f"mask config `mask_criteria` {sorted(extra)!r} is not a subset of the "
            f"`requires_heldout_mask` policy set {sorted(requires_heldout_mask)!r} -- static "
            "lineage governs, never a dynamically-shrunk mask set"
        )

    return config


@dataclass(frozen=True)
class MaskLedger:
    """One input stream's exact-set removal ledger (slot 2 sec 1, AC-M1/M2):
    `remaining == input_total - matched_removed` holds BY CONSTRUCTION (a
    record is either kept or removed, exactly once) -- never separately
    recomputed/asserted after the fact. `removed_ids` is the canonical SPDI
    of every removed record, in removal order (a held-out identity with
    multiple legitimately-removed raw rows -- e.g. several ClinVar
    submission rows for the same `VariationID` -- appears once per removed
    row, not deduplicated)."""

    input_total: int
    matched_removed: int
    remaining: int
    removed_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "input_total": self.input_total,
            "matched_removed": self.matched_removed,
            "remaining": self.remaining,
            "removed_ids": list(self.removed_ids),
        }


def _raw_identity_key(record: Any) -> Any:
    """A record's pre-normalization identity key, used only to detect
    ambiguity (slot 2 sec 1, AC-M9): a `VariationID`-bearing record is
    keyed by that id (many legitimate rows -- e.g. multiple submitters --
    naturally share one `VariationID`, never ambiguous); any other record
    is keyed by its full (sorted, stably-repr'd) field content, so two
    genuinely distinct raw ClinVar rows that happen to normalize to the
    same canonical identity are detected as non-equivalent."""
    if isinstance(record, dict):
        if "VariationID" in record:
            return ("variation_id", record["VariationID"])
        return ("record", tuple(sorted((k, _stable_repr(v)) for k, v in record.items())))
    return ("record", repr(record))


def _stable_repr(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _variation_id_of(record: Any) -> str:
    if isinstance(record, dict):
        for key in ("VariationID", "clinvar_variation_id", "variation_id"):
            if record.get(key):
                return str(record[key])
    return ""


@dataclass
class MaskResult:
    """The core `mask_clinvar_source` output (slot 2 sec 1): one masked
    stream + ledger per ClinVar input stream. `provenance` is attached by
    the caller (e.g. the CLI) AFTER construction -- run metadata (benchmark
    snapshot, code version, source-hash pins) is never part of
    `content_hash()`, which is a pure function of the masked data + ledger
    only (AC-M8)."""

    masked_streams: dict[str, list[Any]]
    ledger: dict[str, MaskLedger]
    removed_rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    masked_namespace: str = "masked"
    full_resource_paths: tuple[str, ...] = ()

    def content_hash(self) -> str:
        body = {
            "masked_streams": self.masked_streams,
            "ledger": {stream: ledger.to_dict() for stream, ledger in self.ledger.items()},
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def write(self, out_dir: str | Path) -> None:
        """Emit `{out_dir}/masked/{stream}.json` per input stream,
        `{out_dir}/mask.manifest.jsonl` (one row per removed record, fields
        exactly `{variant_id, clinvar_variation_id, input_stream}` --
        AC-M6), and `{out_dir}/mask.provenance.json` (source hashes,
        benchmark snapshot, code version, counts, per-stream hashes --
        AC-M8). Never writes into a full-resource path -- `MaskConfig`
        already refused an overlapping `masked_namespace` at construction."""
        out_dir = Path(out_dir).resolve()
        namespace = Path(self.masked_namespace)
        masked_dir = (namespace if namespace.is_absolute() else out_dir / namespace).resolve()
        for full_resource in self.full_resource_paths:
            full_path = Path(full_resource).resolve()
            if (
                masked_dir == full_path
                or full_path in masked_dir.parents
                or masked_dir in full_path.parents
            ):
                raise MaskConfigError(
                    f"actual masked output root {masked_dir} overlaps full resource path {full_path}"
                )
        masked_dir.mkdir(parents=True, exist_ok=True)

        stream_hashes: dict[str, str] = {}
        for stream, records in self.masked_streams.items():
            if (
                not isinstance(stream, str)
                or not stream
                or stream in {".", ".."}
                or "/" in stream
                or "\\" in stream
            ):
                raise MaskConfigError(f"unsafe masked stream name {stream!r}")
            destination = (masked_dir / f"{stream}.json").resolve()
            if masked_dir not in destination.parents:
                raise MaskConfigError(
                    f"masked stream destination escapes output root: {destination}"
                )
            for full_resource in self.full_resource_paths:
                full_path = Path(full_resource).resolve()
                if (
                    destination == full_path
                    or full_path in destination.parents
                    or destination in full_path.parents
                ):
                    raise MaskConfigError(
                        f"masked stream destination {destination} overlaps full resource {full_path}"
                    )
            stream_json = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
            destination.write_text(stream_json, encoding="utf-8")
            stream_hashes[stream] = hashlib.sha256(stream_json.encode("utf-8")).hexdigest()

        manifest_rows: list[dict[str, str]] = []
        for stream in sorted(self.removed_rows):
            manifest_rows.extend(self.removed_rows[stream])
        manifest_text = "\n".join(
            json.dumps(row, sort_keys=True) for row in manifest_rows
        ) + ("\n" if manifest_rows else "")
        manifest_path = out_dir / "mask.manifest.jsonl"
        manifest_path.write_text(manifest_text, encoding="utf-8")

        sidecar = dict(self.provenance)
        sidecar["ledger"] = {stream: ledger.to_dict() for stream, ledger in self.ledger.items()}
        sidecar["stream_hashes"] = stream_hashes
        sidecar["manifest_hash"] = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        sidecar["content_hash"] = self.content_hash()
        provenance_path = out_dir / "mask.provenance.json"
        provenance_path.write_text(
            json.dumps(sidecar, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8"
        )


def mask_clinvar_source(
    clinvar_records: Mapping[str, Iterable[Any]],
    holdout_ids: frozenset[str],
    normalizer: Normalizer,
    config: MaskConfig,
) -> MaskResult:
    """Mask every ClinVar input stream in `clinvar_records` by removing
    exactly the records whose canonical identity is in `holdout_ids` (slot
    2 sec 1). For each stream:

      * every record is normalized to its canonical identity via
        `normalizer.normalize(record)`; a normalization failure raises
        `MaskReferenceError` (never silently kept/dropped);
      * a record whose canonical identity is in `holdout_ids` is removed;
        a held-out id matching MULTIPLE raw records with different raw
        identity keys (`_raw_identity_key`) is `MaskAmbiguityError` (never
        silently merged) -- a held-out id matching zero records is a
        legitimate no-op (the variant is simply absent from this stream);
      * `remaining == input_total - matched_removed` holds by
        construction -- every record is kept XOR removed, exactly once.

    Never mutates `clinvar_records`; never imports/reimplements a BIAS
    generator's aggregation.
    """
    masked_streams: dict[str, list[Any]] = {}
    ledgers: dict[str, MaskLedger] = {}
    removed_rows: dict[str, list[dict[str, str]]] = {}

    for stream_name, records in clinvar_records.items():
        records = list(records)
        input_total = len(records)
        kept: list[Any] = []
        removal_groups: dict[str, list[Any]] = {}
        removed_order: list[tuple[str, Any]] = []

        for record in records:
            try:
                canonical_id = normalizer.normalize(record)
            except Exception as exc:
                raise MaskReferenceError(
                    f"ClinVar record in stream {stream_name!r} failed to normalize to a "
                    f"canonical identity: {record!r}"
                ) from exc

            if canonical_id in holdout_ids:
                removal_groups.setdefault(canonical_id, []).append(_raw_identity_key(record))
                removed_order.append((canonical_id, record))
            else:
                kept.append(record)

        for canonical_id, raw_keys in removal_groups.items():
            distinct_keys = set(raw_keys)
            if len(distinct_keys) > 1:
                raise MaskAmbiguityError(
                    f"held-out id {canonical_id!r} matches {len(distinct_keys)} non-equivalent "
                    f"raw ClinVar records in stream {stream_name!r} -- refusing to mask "
                    "ambiguously (raw identity keys must agree for a single removal)"
                )

        masked_streams[stream_name] = kept
        ledgers[stream_name] = MaskLedger(
            input_total=input_total,
            matched_removed=len(removed_order),
            remaining=len(kept),
            removed_ids=tuple(cid for cid, _rec in removed_order),
        )
        removed_rows[stream_name] = [
            {"variant_id": cid, "clinvar_variation_id": _variation_id_of(rec), "input_stream": stream_name}
            for cid, rec in removed_order
        ]

    return MaskResult(
        masked_streams=masked_streams,
        ledger=ledgers,
        removed_rows=removed_rows,
        masked_namespace=config.masked_namespace,
        full_resource_paths=tuple(config.full_resource_paths),
    )


@dataclass(frozen=True)
class ConservationReport:
    """Total, independent post-rebuild audit result (slot 2 sec 1, AC-M3/
    M4). `clean` is `False` on any survivor/mismatch -- the audit itself
    never raises merely because the rebuild is unclean; only a malformed
    input (an unrecognized criterion, a non-normalizable reference, a
    non-mapping resource) raises."""

    clean: bool
    transitive_survivors: dict[str, tuple[str, ...]]
    aggregate_mismatches: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "transitive_survivors": {k: list(v) for k, v in self.transitive_survivors.items()},
            "aggregate_mismatches": list(self.aggregate_mismatches),
        }

    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _records_feeding(criterion: str, clinvar_records: Mapping[str, Any], config: MaskConfig) -> list[Any]:
    streams = [entry["stream"] for entry in config.clinvar_inputs if criterion in entry.get("resources", ())]
    out: list[Any] = []
    for stream in streams:
        out.extend(clinvar_records.get(stream) or [])
    return out


def _audit_direct_reference(
    criterion: str, resource: Any, holdout_ids: frozenset[str], normalizer: Normalizer
) -> list[str]:
    if not isinstance(resource, dict):
        raise MaskConfigError(f"comparator resource for {criterion!r} must be a mapping")
    survivors: set[str] = set()
    for entry_key, entry in resource.items():
        try:
            canonical_id = normalizer.normalize(entry)
        except Exception as exc:
            raise MaskReferenceError(
                f"comparator resource entry {entry_key!r} for {criterion!r} failed to normalize "
                f"to a canonical identity: {entry!r}"
            ) from exc
        if canonical_id in holdout_ids:
            survivors.add(canonical_id)
    return sorted(survivors)


def _audit_aggregate(
    criterion: str,
    resource: Any,
    clinvar_records: Mapping[str, Any],
    config: MaskConfig,
    spec: Mapping[str, str],
) -> list[str]:
    if not isinstance(resource, dict):
        raise MaskConfigError(f"comparator resource for {criterion!r} must be a mapping")

    group_field = spec["group_field"]
    indicator_field = spec["indicator_field"]
    count_key = spec["count_key"]

    records = _records_feeding(criterion, clinvar_records, config)
    tagged = [r for r in records if isinstance(r, dict) and group_field in r]
    recomputed: dict[Any, dict[str, int]] = {}
    for record in tagged:
        key = record[group_field]
        bucket = recomputed.setdefault(key, {"total": 0, count_key: 0})
        bucket["total"] += 1
        if record.get(indicator_field):
            bucket[count_key] += 1

    mismatches: list[str] = []
    for group_key, stored in resource.items():
        if not isinstance(stored, dict):
            raise MaskConfigError(
                f"{criterion!r} aggregate entry for {group_key!r} must be a mapping, got {stored!r}"
            )
        computed = recomputed.get(group_key, {"total": 0, count_key: 0})
        if stored.get("total") != computed["total"] or stored.get(count_key) != computed[count_key]:
            mismatches.append(
                f"{criterion}:{group_key}: stored total={stored.get('total')!r} "
                f"{count_key}={stored.get(count_key)!r} != recomputed (from masked ClinVar) "
                f"total={computed['total']!r} {count_key}={computed[count_key]!r}"
            )
    return mismatches


def audit_mask_conservation(
    masked_resources: Mapping[str, Any],
    holdout_ids: frozenset[str],
    normalizer: Normalizer,
    config: MaskConfig,
) -> ConservationReport:
    """Independent, post-rebuild mask-conservation audit (slot 2 sec 1,
    AC-M3/M4). `masked_resources` = `{"clinvar_records": {stream: [record,
    ...]}, "comparators": {criterion: resource}}` -- the operator's
    rebuilt masked ClinVar + comparator resources.

    For each `criterion` present in `masked_resources["comparators"]`:
      * a DIRECT-reference criterion (`PS1, PM5, PS4, PP5, BP6`) has every
        entry's own identity re-normalized and checked against
        `holdout_ids` -- any hit is a `transitive_survivors[criterion]`
        entry, even if that variant never fires (the zero-incidence case,
        AC-M3);
      * an AGGREGATE criterion (`PM1, PP2, BP1`) has its domain/gene
        aggregate independently RECOMPUTED from `masked_resources
        ["clinvar_records"]` (via `config.clinvar_inputs`, never from the
        resource's own stored total) and compared against the resource's
        stored aggregate -- any disagreement is an `aggregate_mismatches`
        entry (AC-M4).

    Never raises merely because the rebuild is unclean (`clean=False` is a
    legitimate total result); only a criterion outside `config`'s known
    mask set, a non-mapping resource, or a non-normalizable reference
    raises.
    """
    clinvar_records = masked_resources.get("clinvar_records") or {}
    comparators = masked_resources.get("comparators") or {}

    known_criteria = frozenset(config.mask_criteria) | frozenset(config.direct_copy_fallbacks)
    transitive_survivors: dict[str, list[str]] = {}
    aggregate_mismatches: list[str] = []

    for criterion, resource in comparators.items():
        if criterion not in known_criteria:
            raise MaskConfigError(
                f"audit received an unrecognized criterion {criterion!r} not in the config's "
                "mask_criteria + direct_copy_fallbacks"
            )

        if criterion in _AGGREGATE_CRITERIA_FIELDS:
            aggregate_mismatches.extend(
                _audit_aggregate(criterion, resource, clinvar_records, config, _AGGREGATE_CRITERIA_FIELDS[criterion])
            )
        else:
            survivors = _audit_direct_reference(criterion, resource, holdout_ids, normalizer)
            if survivors:
                transitive_survivors[criterion] = survivors

    clean = not transitive_survivors and not aggregate_mismatches
    return ConservationReport(
        clean=clean,
        transitive_survivors={k: tuple(v) for k, v in transitive_survivors.items()},
        aggregate_mismatches=tuple(aggregate_mismatches),
    )


def load_holdout_identities(heldout_jsonl: str | Path, normalizer: Normalizer) -> frozenset[str]:
    """Read ONLY `row["variant_id"]` from the frozen held-out JSONL (never
    `label`/`source`/`review_status`/`variant_class` -- AC-M6), normalize
    each to canonical GRCh38 SPDI via `normalizer` (handed a fresh
    `{"variant_id": raw_id}` object, never the raw row, so an injected
    normalizer can never see a label field even if it inspected its input
    beyond `variant_id`), and return the frozen identity set.

    A row missing `variant_id`, a `variant_id` that fails to normalize, or
    a duplicate canonical identity is always fatal (`HoldoutIdentityError`)
    -- never silently dropped.
    """
    path = Path(heldout_jsonl)
    seen: set[str] = set()
    ids: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or "variant_id" not in row:
                raise HoldoutIdentityError(
                    f"held-out row {line_no} in {path} is missing the required `variant_id` field"
                )
            raw_id = row["variant_id"]
            try:
                canonical_id = normalizer.normalize({"variant_id": raw_id})
            except Exception as exc:
                raise HoldoutIdentityError(
                    f"held-out row {line_no} in {path} carries an un-normalizable "
                    f"variant_id {raw_id!r}"
                ) from exc
            if canonical_id in seen:
                raise HoldoutIdentityError(
                    f"held-out row {line_no} in {path} is a duplicate canonical identity "
                    f"{canonical_id!r} -- fatal, never silently dropped"
                )
            seen.add(canonical_id)
            ids.append(canonical_id)

    return frozenset(ids)
