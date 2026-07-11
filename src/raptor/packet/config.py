"""PRD-04 Task A `config.py` — packet config + candidate-direction policy loaders.

Frozen, schema-validated config surfaces (sec 10.2/10.3): `PacketConfig` pins the
lineage policy + production candidate-direction policy loaded from
`configs/packet/schema.yaml`, and `CandidateDirectionPolicy` is the nullable
production candidate-direction policy loaded from
`configs/packet/candidate_direction.yaml` (FR5). Both loaders are strict: any
missing/unknown top-level key raises `PacketConfigError`; the loader records
the *real* SHA-256 of each referenced file (never a caller-declared pin).

This module never imports `raptor.eval.combine`/`harness`/`benchmark`/`knowns`
or `raptor.kb.store`; it consumes `load_lineage_policy` **output** only
(FR4.1) and never invents or edits lineage.

PRD-04 Task B extends this module (never Task-A behavior) with the frozen
render/narrative/selection config surfaces (sec 10.3): `NarrativeTemplate` +
`NarrativeCatalog` (FR7 approved template catalog), `RenderConfig` (FR10/FR14
render options + non-authoritative marker), and `SelectionConfig` (FR17
calibration selection policy). All three are strict, schema-validated, and
carry no hidden defaults; `render.yaml` references `narrative_templates.yaml`
by a repository-relative path resolved against the process working directory
(the repository root), mirroring the Task-A `load_packet_config` pattern.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

import yaml

from raptor.eval.lineage_policy import LineagePolicy, load_lineage_policy

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_SCHEMA_REQUIRED_KEYS = frozenset({
    "packet_schema_version",
    "config_version",
    "lineage_policy_path",
    "candidate_direction_policy_path",
    "primary_required_criteria",
})

_DIRECTION_REQUIRED_KEYS = frozenset({
    "policy_id",
    "version",
    "approval_status",
    "approved_by",
    "approval_ref",
    "criterion_strength_points",
    "candidate_lp_min",
    "candidate_lb_max",
})

_APPROVAL_STATUSES = frozenset({"unapproved", "approved"})

# --------------------------------------------------------------------------
# Task B (surfaces) schema keys
# --------------------------------------------------------------------------

_NARRATIVE_TEMPLATE_REQUIRED_KEYS = frozenset({"template_id", "body", "required_bindings"})

_NARRATIVE_CATALOG_REQUIRED_KEYS = frozenset({"config_version", "templates"})

_RENDER_REQUIRED_KEYS = frozenset({
    "config_version",
    "non_authoritative_marker",
    "first_pass_heading",
    "operator_heading",
    "reconciliation_heading",
    "narrative_templates_path",
})

_SELECTION_REQUIRED_KEYS = frozenset({
    "config_version",
    "census_snapshot_id",
    "seed",
    "required_dimensions",
    "expected_atoms",
})

# FR17: the exact, fixed set of independent coverage dimensions.
_SELECTION_REQUIRED_DIMENSIONS = ("pattern", "gene", "variant_class", "edge_flag")


class PacketConfigError(ValueError):
    """A malformed/unknown-field `configs/packet/*.yaml`, or an internally
    inconsistent `PacketConfig`/`CandidateDirectionPolicy` (Task A config
    loaders)."""


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_str(raw: Mapping[str, object], key: str, *, label: str) -> str:
    """Return `raw[key]` iff it is *already* a non-blank `str` in the raw YAML
    scalar (never coerced from `None`/int/bool/etc via `str(...)`); otherwise
    raise `PacketConfigError`. Prevents e.g. a YAML `null` silently rendering
    as the string `"None"`."""
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PacketConfigError(
            f"{label} {key!r} must be a non-blank string, got {value!r}"
        )
    return value


def _validate_str_seq(value: object, *, label: str) -> Tuple[str, ...]:
    """Return `value` as a tuple iff it is *already* a list/tuple of
    non-blank `str` scalars; raises `PacketConfigError` for `None`,
    non-list-or-tuple types, or any `None`/non-string/blank element (never
    silently coerces via `str(...)` or masks `None` via `value or ()`)."""
    if not isinstance(value, (list, tuple)):
        raise PacketConfigError(f"{label} must be a list, got {type(value).__name__}")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PacketConfigError(f"{label} entries must be non-blank strings, got {item!r}")
        result.append(item)
    return tuple(result)


def _require_str_seq(raw: Mapping[str, object], key: str, *, label: str) -> Tuple[str, ...]:
    """Return `raw[key]` as a tuple iff it is a list/tuple of non-blank
    `str` scalars; raises `PacketConfigError` for `None`, non-sequence types,
    or any non-string/blank element (never silently coerces via `str(...)`)."""
    return _validate_str_seq(raw.get(key), label=f"{label} {key!r}")


def _require_mapping(raw: Mapping[str, object], key: str, *, label: str) -> Mapping[str, object]:
    """Return `raw[key]` iff it is *already* a mapping; raises
    `PacketConfigError` for `None`/list/scalar/etc (never silently coerces
    `None` into `{}`)."""
    value = raw.get(key)
    if not isinstance(value, dict):
        raise PacketConfigError(
            f"{label} {key!r} must be a mapping, got {value!r}"
        )
    return value


@dataclass(frozen=True)
class CandidateDirectionPolicy:
    """FR5 production candidate-direction policy. `approval_status` is
    `unapproved | approved`. Unapproved requires null approval fields, empty
    points, and null cutoffs. Approved requires non-blank approval fields,
    non-empty points, integer cutoffs, and `candidate_lb_max < candidate_lp_min`."""

    policy_id: str
    version: str
    approval_status: str
    approved_by: Optional[str]
    approval_ref: Optional[str]
    criterion_strength_points: Mapping[str, Mapping[str, int]]
    candidate_lp_min: Optional[int]
    candidate_lb_max: Optional[int]

    def __post_init__(self) -> None:
        if not _non_blank(self.policy_id):
            raise PacketConfigError("CandidateDirectionPolicy.policy_id must be non-blank")
        if not _non_blank(self.version):
            raise PacketConfigError("CandidateDirectionPolicy.version must be non-blank")
        if self.approval_status not in _APPROVAL_STATUSES:
            raise PacketConfigError(
                f"CandidateDirectionPolicy.approval_status must be one of "
                f"{sorted(_APPROVAL_STATUSES)!r}; got {self.approval_status!r}"
            )

        points = {}
        for criterion, strengths in dict(self.criterion_strength_points).items():
            if not _non_blank(criterion):
                raise PacketConfigError(
                    f"CandidateDirectionPolicy.criterion_strength_points key must be a "
                    f"non-blank string, got {criterion!r}"
                )
            strength_points = {}
            for strength, pts in dict(strengths).items():
                if not _non_blank(strength):
                    raise PacketConfigError(
                        f"CandidateDirectionPolicy.criterion_strength_points[{criterion!r}] key "
                        f"must be a non-blank string, got {strength!r}"
                    )
                if isinstance(pts, bool) or not isinstance(pts, int):
                    raise PacketConfigError(
                        f"CandidateDirectionPolicy.criterion_strength_points[{criterion!r}]"
                        f"[{strength!r}] must be an int, got {pts!r}"
                    )
                strength_points[strength] = pts
            points[criterion] = MappingProxyType(strength_points)
        object.__setattr__(self, "criterion_strength_points", MappingProxyType(points))

        if self.approval_status == "unapproved":
            if self.approved_by is not None or self.approval_ref is not None:
                raise PacketConfigError(
                    "an unapproved CandidateDirectionPolicy must have null approved_by/approval_ref"
                )
            if self.criterion_strength_points:
                raise PacketConfigError(
                    "an unapproved CandidateDirectionPolicy must have empty criterion_strength_points"
                )
            if self.candidate_lp_min is not None or self.candidate_lb_max is not None:
                raise PacketConfigError("an unapproved CandidateDirectionPolicy must have null cutoffs")
        else:
            if not _non_blank(self.approved_by):
                raise PacketConfigError(
                    "an approved CandidateDirectionPolicy requires a non-blank approved_by"
                )
            if not _non_blank(self.approval_ref):
                raise PacketConfigError(
                    "an approved CandidateDirectionPolicy requires a non-blank approval_ref"
                )
            if not self.criterion_strength_points:
                raise PacketConfigError(
                    "an approved CandidateDirectionPolicy requires non-empty criterion_strength_points"
                )
            lp_min, lb_max = self.candidate_lp_min, self.candidate_lb_max
            if (
                isinstance(lp_min, bool) or not isinstance(lp_min, int)
                or isinstance(lb_max, bool) or not isinstance(lb_max, int)
            ):
                raise PacketConfigError(
                    "an approved CandidateDirectionPolicy requires integer "
                    "candidate_lp_min/candidate_lb_max"
                )
            if not lb_max < lp_min:
                raise PacketConfigError(
                    "an approved CandidateDirectionPolicy requires candidate_lb_max < candidate_lp_min"
                )


@dataclass(frozen=True)
class PacketConfig:
    """Task-A-owned packet config: pins the lineage policy + candidate
    direction policy loaded from `configs/packet/schema.yaml`."""

    packet_schema_version: str
    config_version: str
    lineage_policy: LineagePolicy
    lineage_policy_sha256: str
    candidate_direction_policy: CandidateDirectionPolicy
    candidate_policy_sha256: str
    primary_required_criteria: frozenset

    def __post_init__(self) -> None:
        if not _non_blank(self.packet_schema_version):
            raise PacketConfigError("PacketConfig.packet_schema_version must be non-blank")
        if not _non_blank(self.config_version):
            raise PacketConfigError("PacketConfig.config_version must be non-blank")
        if not isinstance(self.lineage_policy, LineagePolicy):
            raise PacketConfigError("PacketConfig.lineage_policy must be a LineagePolicy")
        if not _is_hex64(self.lineage_policy_sha256):
            raise PacketConfigError("PacketConfig.lineage_policy_sha256 must be lowercase hex-64")
        if not isinstance(self.candidate_direction_policy, CandidateDirectionPolicy):
            raise PacketConfigError(
                "PacketConfig.candidate_direction_policy must be a CandidateDirectionPolicy"
            )
        if not _is_hex64(self.candidate_policy_sha256):
            raise PacketConfigError("PacketConfig.candidate_policy_sha256 must be lowercase hex-64")
        object.__setattr__(
            self, "primary_required_criteria", frozenset(str(c) for c in self.primary_required_criteria)
        )


def _load_yaml_mapping(path: str | Path, *, required_keys: frozenset, label: str) -> dict:
    raw_path = Path(path)
    if not raw_path.is_file():
        raise PacketConfigError(f"{label} not found: {raw_path}")
    raw = yaml.safe_load(raw_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PacketConfigError(f"{label} root must be a mapping, got {type(raw).__name__}")
    keys = set(raw.keys())
    unknown = keys - required_keys
    if unknown:
        raise PacketConfigError(f"{label} has unknown key(s): {sorted(unknown)!r}")
    missing = required_keys - keys
    if missing:
        raise PacketConfigError(f"{label} is missing key(s): {sorted(missing)!r}")
    return raw


def load_candidate_direction_policy(path: str | Path) -> CandidateDirectionPolicy:
    """Load + strictly schema-validate `configs/packet/candidate_direction.yaml`
    (exactly `policy_id, version, approval_status, approved_by, approval_ref,
    criterion_strength_points, candidate_lp_min, candidate_lb_max`)."""
    raw = _load_yaml_mapping(
        path, required_keys=_DIRECTION_REQUIRED_KEYS, label="candidate direction policy"
    )
    label = "candidate direction policy"
    return CandidateDirectionPolicy(
        policy_id=_require_str(raw, "policy_id", label=label),
        version=_require_str(raw, "version", label=label),
        approval_status=_require_str(raw, "approval_status", label=label),
        approved_by=raw["approved_by"],
        approval_ref=raw["approval_ref"],
        criterion_strength_points=_require_mapping(raw, "criterion_strength_points", label=label),
        candidate_lp_min=raw["candidate_lp_min"],
        candidate_lb_max=raw["candidate_lb_max"],
    )


def load_packet_config(path: str | Path) -> PacketConfig:
    """Load + strictly schema-validate `configs/packet/schema.yaml` (exactly
    `packet_schema_version, config_version, lineage_policy_path,
    candidate_direction_policy_path, primary_required_criteria`). Paths
    resolve relative to the repository root (the process working directory);
    the loader records the *real* SHA-256 of both referenced files."""
    raw = _load_yaml_mapping(path, required_keys=_SCHEMA_REQUIRED_KEYS, label="packet config")
    label = "packet config"

    repo_root = Path.cwd()
    lineage_policy_path = repo_root / _require_str(raw, "lineage_policy_path", label=label)
    candidate_policy_path = repo_root / _require_str(
        raw, "candidate_direction_policy_path", label=label
    )

    if not lineage_policy_path.is_file():
        raise PacketConfigError(f"packet config lineage_policy_path not found: {lineage_policy_path}")
    if not candidate_policy_path.is_file():
        raise PacketConfigError(
            f"packet config candidate_direction_policy_path not found: {candidate_policy_path}"
        )

    lineage_policy = load_lineage_policy(lineage_policy_path)
    lineage_policy_sha256 = hashlib.sha256(lineage_policy_path.read_bytes()).hexdigest()

    candidate_direction_policy = load_candidate_direction_policy(candidate_policy_path)
    candidate_policy_sha256 = hashlib.sha256(candidate_policy_path.read_bytes()).hexdigest()

    primary_required_criteria = _require_str_seq(raw, "primary_required_criteria", label=label)

    return PacketConfig(
        packet_schema_version=_require_str(raw, "packet_schema_version", label=label),
        config_version=_require_str(raw, "config_version", label=label),
        lineage_policy=lineage_policy,
        lineage_policy_sha256=lineage_policy_sha256,
        candidate_direction_policy=candidate_direction_policy,
        candidate_policy_sha256=candidate_policy_sha256,
        primary_required_criteria=primary_required_criteria,
    )


# --------------------------------------------------------------------------
# Task B (surfaces) — frozen config models (extend only; never touches the
# Task-A models/loaders above).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NarrativeTemplate:
    """One approved narrative template (FR7): a `template_id`, a `body` with
    named `{field}` placeholders, and the exact set of binding names the
    plan must supply (no more, no fewer)."""

    template_id: str
    body: str
    required_bindings: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not _non_blank(self.template_id):
            raise PacketConfigError("NarrativeTemplate.template_id must be non-blank")
        if not _non_blank(self.body):
            raise PacketConfigError("NarrativeTemplate.body must be non-blank")
        bindings = _validate_str_seq(
            self.required_bindings, label="NarrativeTemplate.required_bindings"
        )
        if len(set(bindings)) != len(bindings):
            raise PacketConfigError("NarrativeTemplate.required_bindings must not contain duplicates")
        object.__setattr__(self, "required_bindings", bindings)


@dataclass(frozen=True)
class NarrativeCatalog:
    """The approved template catalog (FR7): `templates` maps `template_id ->
    NarrativeTemplate`; a narrative plan may reference only a `template_id`
    present here (else it fails loud in `render.py`, AC9)."""

    config_version: str
    templates: Mapping[str, NarrativeTemplate]

    def __post_init__(self) -> None:
        if not _non_blank(self.config_version):
            raise PacketConfigError("NarrativeCatalog.config_version must be non-blank")
        templates = dict(self.templates)
        if not templates:
            raise PacketConfigError("NarrativeCatalog.templates must be non-empty")
        normalized = {}
        for key, template in templates.items():
            if not isinstance(template, NarrativeTemplate):
                raise PacketConfigError(
                    "NarrativeCatalog.templates values must be NarrativeTemplate"
                )
            if str(key) != template.template_id:
                raise PacketConfigError(
                    f"NarrativeCatalog template key {key!r} must match its "
                    f"template_id {template.template_id!r}"
                )
            normalized[str(key)] = template
        object.__setattr__(self, "templates", MappingProxyType(normalized))


@dataclass(frozen=True)
class RenderConfig:
    """Deterministic-render options (FR10/FR14): the non-authoritative
    marker + the three view headings + the approved narrative catalog."""

    config_version: str
    non_authoritative_marker: str
    first_pass_heading: str
    operator_heading: str
    reconciliation_heading: str
    narrative_catalog: NarrativeCatalog

    def __post_init__(self) -> None:
        for name in (
            "config_version", "non_authoritative_marker", "first_pass_heading",
            "operator_heading", "reconciliation_heading",
        ):
            if not _non_blank(getattr(self, name)):
                raise PacketConfigError(f"RenderConfig.{name} must be non-blank")
        if not isinstance(self.narrative_catalog, NarrativeCatalog):
            raise PacketConfigError("RenderConfig.narrative_catalog must be a NarrativeCatalog")


@dataclass(frozen=True)
class SelectionConfig:
    """Calibration selection policy (FR17): a pinned `seed` + census snapshot
    id + the exact four independent coverage dimensions + optionally-declared
    `expected_atoms` (known catalog atoms; never a Cartesian product)."""

    config_version: str
    census_snapshot_id: str
    seed: int
    required_dimensions: Tuple[str, ...]
    expected_atoms: Mapping[str, Tuple[str, ...]]

    def __post_init__(self) -> None:
        if not _non_blank(self.config_version):
            raise PacketConfigError("SelectionConfig.config_version must be non-blank")
        if not _non_blank(self.census_snapshot_id):
            raise PacketConfigError("SelectionConfig.census_snapshot_id must be non-blank")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise PacketConfigError("SelectionConfig.seed must be an int")

        required_dimensions = _validate_str_seq(
            self.required_dimensions, label="SelectionConfig.required_dimensions"
        )
        if required_dimensions != _SELECTION_REQUIRED_DIMENSIONS:
            raise PacketConfigError(
                "SelectionConfig.required_dimensions must be exactly "
                f"{_SELECTION_REQUIRED_DIMENSIONS!r}; got {required_dimensions!r}"
            )
        object.__setattr__(self, "required_dimensions", required_dimensions)

        if not isinstance(self.expected_atoms, Mapping):
            raise PacketConfigError(
                "SelectionConfig.expected_atoms must be a mapping, got "
                f"{type(self.expected_atoms).__name__}"
            )
        expected_atoms = dict(self.expected_atoms)
        keys = frozenset(str(key) for key in expected_atoms.keys())
        if keys != frozenset(_SELECTION_REQUIRED_DIMENSIONS):
            raise PacketConfigError(
                "SelectionConfig.expected_atoms keys must be exactly "
                f"{set(_SELECTION_REQUIRED_DIMENSIONS)!r}; got {set(keys)!r}"
            )
        normalized = {
            str(key): _validate_str_seq(
                value, label=f"SelectionConfig.expected_atoms[{key!r}]"
            )
            for key, value in expected_atoms.items()
        }
        object.__setattr__(self, "expected_atoms", MappingProxyType(normalized))


def load_narrative_catalog(path: str | Path) -> NarrativeCatalog:
    """Load + strictly schema-validate `configs/packet/narrative_templates.yaml`
    (exactly `config_version, templates`; each template exactly `template_id,
    body, required_bindings`); unknown/missing/blank fields raise
    `PacketConfigError`."""
    raw = _load_yaml_mapping(
        path, required_keys=_NARRATIVE_CATALOG_REQUIRED_KEYS, label="narrative catalog"
    )
    templates_raw = raw["templates"]
    if not isinstance(templates_raw, dict) or not templates_raw:
        raise PacketConfigError("narrative catalog templates must be a non-empty mapping")

    templates = {}
    for key, template_raw in templates_raw.items():
        if not isinstance(template_raw, dict):
            raise PacketConfigError(f"narrative catalog template {key!r} must be a mapping")
        template_keys = set(template_raw.keys())
        unknown = template_keys - _NARRATIVE_TEMPLATE_REQUIRED_KEYS
        if unknown:
            raise PacketConfigError(
                f"narrative catalog template {key!r} has unknown key(s): {sorted(unknown)!r}"
            )
        missing = _NARRATIVE_TEMPLATE_REQUIRED_KEYS - template_keys
        if missing:
            raise PacketConfigError(
                f"narrative catalog template {key!r} is missing key(s): {sorted(missing)!r}"
            )
        template_label = f"narrative catalog template {key!r}"
        templates[str(key)] = NarrativeTemplate(
            template_id=_require_str(template_raw, "template_id", label=template_label),
            body=_require_str(template_raw, "body", label=template_label),
            required_bindings=_require_str_seq(
                template_raw, "required_bindings", label=template_label
            ),
        )

    return NarrativeCatalog(
        config_version=_require_str(raw, "config_version", label="narrative catalog"),
        templates=templates,
    )


def load_render_config(path: str | Path) -> RenderConfig:
    """Load + strictly schema-validate `configs/packet/render.yaml` (exactly
    the six source keys: the five `RenderConfig` scalar fields plus
    `narrative_templates_path`, a repository-relative path resolved against
    the process working directory / repository root, replacing the loaded
    `NarrativeCatalog` object)."""
    raw = _load_yaml_mapping(path, required_keys=_RENDER_REQUIRED_KEYS, label="render config")

    repo_root = Path.cwd()
    narrative_templates_path = _require_str(raw, "narrative_templates_path", label="render config")
    catalog_path = repo_root / narrative_templates_path
    if not catalog_path.is_file():
        raise PacketConfigError(
            f"render config narrative_templates_path not found: {catalog_path}"
        )
    narrative_catalog = load_narrative_catalog(catalog_path)

    return RenderConfig(
        config_version=_require_str(raw, "config_version", label="render config"),
        non_authoritative_marker=_require_str(
            raw, "non_authoritative_marker", label="render config"
        ),
        first_pass_heading=_require_str(raw, "first_pass_heading", label="render config"),
        operator_heading=_require_str(raw, "operator_heading", label="render config"),
        reconciliation_heading=_require_str(
            raw, "reconciliation_heading", label="render config"
        ),
        narrative_catalog=narrative_catalog,
    )


def load_selection_config(path: str | Path) -> SelectionConfig:
    """Load + strictly schema-validate `configs/packet/selection.yaml`
    (exactly `config_version, census_snapshot_id, seed, required_dimensions,
    expected_atoms`)."""
    raw = _load_yaml_mapping(path, required_keys=_SELECTION_REQUIRED_KEYS, label="selection config")

    required_dimensions = _require_str_seq(raw, "required_dimensions", label="selection config")
    expected_atoms_raw = raw.get("expected_atoms")
    if not isinstance(expected_atoms_raw, dict) or not expected_atoms_raw:
        raise PacketConfigError("selection config expected_atoms must be a non-empty mapping")
    expected_atoms = {}
    for key, value in expected_atoms_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise PacketConfigError(
                f"selection config expected_atoms key must be a non-blank string, got {key!r}"
            )
        expected_atoms[key] = _require_str_seq(
            {key: value}, key, label="selection config expected_atoms"
        )

    seed_raw = raw["seed"]
    if isinstance(seed_raw, bool) or not isinstance(seed_raw, int):
        raise PacketConfigError("selection config seed must be an int")

    return SelectionConfig(
        config_version=_require_str(raw, "config_version", label="selection config"),
        census_snapshot_id=_require_str(raw, "census_snapshot_id", label="selection config"),
        seed=seed_raw,
        required_dimensions=required_dimensions,
        expected_atoms=expected_atoms,
    )
