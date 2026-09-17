"""R611Q package-v2 addendum: compose an append-only wrapper over the
immutable literature-v1, synthesis-v1 and structure-readiness-v1 RescueScreen
evidence pack, the unreviewed Atlas expert packet/form, and the reviewed
2026-09-16 literature delta bundle.

This module is pure standard-library plus PyYAML. It never performs network
I/O and never imports any scorer/eval/clinical/acmg module. Every function
that touches the immutable v1 repository package only opens files for
reading; no v1 byte is ever written.

See ``docs/project/specs/r611q-package-v2-addendum-v1.yaml`` for the frozen
contract this module implements.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, MutableMapping, Sequence

import yaml

from raptor.rescuescreen.model import RescueScreenError


class PackageV2Error(RescueScreenError):
    """Raised for any r611q-package-v2-addendum verification or composition failure.

    A single precise error type is used throughout this module. Every raise
    site includes an explicit, actionable message; there are no broad or
    silent ``except`` clauses anywhere in this module.
    """


__all__ = [
    "PackageV2Error",
    "build_r611q_package_v2_addendum",
    "verify_repository_v1_manifests",
    "validate_external_expert_inputs",
    "validate_delta_bundle",
    "select_boundary_observation",
    "compose_packet_v2",
    "compose_form_v2",
    "build_impact_record_v2",
    "render_external_package",
    "build_repository_summary",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([^\x00]+)$")
_TEXT_CHAR_LOCATOR_RE = re.compile(r"^text-char:(\d+):(\d+)$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_EXTERNAL_ARTIFACTS: tuple[str, ...] = (
    "R611Q_EXPERT_REVIEW_PACKET_V2.md",
    "R611Q_EXPERT_REVIEW_FORM_V2.yaml",
    "R611Q_PACKAGE_V2_IMPACT.json",
    "R611Q_PACKAGE_V2_SUMMARY.md",
    "package_manifest.json",
)

PACKAGE_MANIFEST_SCHEMA = "raptor.external.r611q_package_v2_addendum_manifest.v1"
REPOSITORY_SUMMARY_SCHEMA = "raptor.repository.r611q_package_v2_addendum_summary.v1"
IMPACT_SCHEMA = "raptor.rescuescreen.r611q_package_v2_addendum_impact.v1"
FORM_V2_SCHEMA = "atlas.expert_review_form.v2"

# The real v1 Atlas packet checkbox vocabulary (see
# data/atlas .../R611Q_EXPERT_REVIEW_PACKET.md "Claim A/B decision" blocks).
REAL_DECISION_OPTIONS: tuple[str, ...] = (
    "ACCEPT_AS_WRITTEN",
    "ACCEPT_WITH_NARROWER_WORDING",
    "REJECT",
    "REQUEST_MORE_EVIDENCE",
)

# Semantic boundary-selection constraint: DIRECT_ALLELE_EXPERIMENT +
# PRIMARY_R611Q_RESULT + NARROWS + NEW_PRIMARY_OBSERVATION + P_COMPLEX_BINDING.
_BOUNDARY_EXACT_FIELDS: Mapping[str, str] = {
    "source_role": "DIRECT_ALLELE_EXPERIMENT",
    "primary_result_state": "PRIMARY_R611Q_RESULT",
    "baseline_relation": "NARROWS",
}
# The real delta review-record schema names this field "delta_value"; the
# spec/tests' simpler synthetic shape names it "novelty". Both are accepted.
_BOUNDARY_NOVELTY_KEYS: tuple[str, ...] = ("novelty", "delta_value")
_BOUNDARY_NOVELTY_VALUE = "NEW_PRIMARY_OBSERVATION"
# The real schema carries this as membership in a "proposition_ids" list; the
# synthetic shape carries it as an exact "claim_kind" field. Both accepted.
_BOUNDARY_CLAIM_KIND_VALUE = "P_COMPLEX_BINDING"

# The registered narrow paraphrase (spec composition.expert_packet_v2.new_review_unit
# .proposed_statement). This is composed language, not a copy of the source quote.
PACKET_V2_PROPOSED_STATEMENT = (
    "In the reported HEK293T co-immunoprecipitation assay, a grouped set of "
    "GFP-tagged $TSC2$ constructs containing $R611Q$, $R905Q$ or $N1620S$ "
    "co-immunoprecipitated with V5-tagged $TSC2$; the source reported no "
    "effect of those substitutions on $TSC2$-$TSC2$ association."
)
PACKET_V2_REQUIRED_QUALIFIERS: tuple[str, ...] = (
    "the result is group-attributed and has no $R611Q$-specific magnitude",
    "the assay uses transient tagged overexpression in HEK293T cells",
    "preserved $TSC2$ self-association does not establish preserved $TSC1$ binding",
    "the result narrows but does not contradict the existing claim units",
)
PACKET_V2_RELATED_CLAIMS: tuple[str, ...] = ("r611q-claim-0", "r611q-claim-1")

_FORBIDDEN_SUMMARY_TOKENS: tuple[str, ...] = (
    "pmid",
    "pmcid",
    "doi",
    "title",
    "candidate_id",
    "locator",
    "patient",
)


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageV2Error(message)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _canonical_json_hash(mapping: Mapping[str, Any], *, drop_field: str) -> str:
    payload = copy.deepcopy(dict(mapping))
    payload.pop(drop_field, None)
    return _sha256_bytes(_canonical_json_bytes(payload))


def _reject_symlink(path: Path, description: str) -> None:
    _require(not path.is_symlink(), f"{description} must not be a symlink/reparse point: {path}")


def _reject_symlink_ancestry(path: Path, description: str) -> None:
    """Reject ``path`` or any of its ancestors being a symlink/reparse point.

    Walks from ``path`` up to the filesystem root. ``Path.is_symlink()``
    returns ``False`` (never raises) for a component that does not exist, so
    this is safe to call on paths that are not yet created.
    """

    current = Path(path)
    while True:
        _require(not current.is_symlink(), f"{description} must not be a symlink/reparse point: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _require_outside_repo(candidate: Path, repo_root: Path, description: str) -> Path:
    candidate_resolved = Path(candidate).resolve()
    repo_root_resolved = Path(repo_root).resolve()
    _require(
        candidate_resolved != repo_root_resolved,
        f"{description} must resolve outside the repository root: {candidate_resolved}",
    )
    try:
        candidate_resolved.relative_to(repo_root_resolved)
    except ValueError:
        return candidate_resolved
    raise PackageV2Error(f"{description} must resolve outside the repository root: {candidate_resolved}")


def _mkdir_tracked(path: Path) -> Path | None:
    """Create ``path`` and any missing parents.

    Returns the highest newly-created ancestor directory (the root of what
    this call created), so a failure elsewhere can roll back with a single
    targeted ``shutil.rmtree`` of exactly that directory -- never a broad or
    wildcard deletion. Returns ``None`` if ``path`` already existed.
    """

    if path.exists():
        return None
    to_create: list[Path] = []
    current = path
    while not current.exists():
        to_create.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for directory in reversed(to_create):
        directory.mkdir()
    return to_create[-1]


def _reject_escape(root: Path, path: Path, description: str) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    _require(
        resolved_path == resolved_root or str(resolved_path).startswith(str(resolved_root) + "\\")
        or str(resolved_path).startswith(str(resolved_root) + "/"),
        f"{description} escapes its root: {path}",
    )


def _safe_relative_path(context: str, relative_path: Any) -> None:
    _require(
        isinstance(relative_path, str) and relative_path,
        f"{context}: manifest path must be a nonblank string",
    )
    _require("\\" not in relative_path, f"{context}: manifest path uses backslash: {relative_path!r}")
    _require("\x00" not in relative_path, f"{context}: manifest path contains null byte: {relative_path!r}")
    pure = PurePosixPath(relative_path)
    _require(not pure.is_absolute(), f"{context}: manifest path must be relative: {relative_path!r}")
    _require(
        not relative_path.startswith(("./", "../")),
        f"{context}: manifest path traversal: {relative_path!r}",
    )
    _require(
        all(part not in {"", ".", ".."} for part in pure.parts),
        f"{context}: manifest path traversal: {relative_path!r}",
    )
    if pure.parts:
        _require(
            ":" not in pure.parts[0],
            f"{context}: manifest path must not include a drive letter: {relative_path!r}",
        )


def _parse_sha256_manifest(manifest_path: Path, manifest_bytes: bytes) -> list[tuple[str, str]]:
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageV2Error(f"{manifest_path} is not valid UTF-8: {exc}") from exc

    lines = text.splitlines()
    _require(bool(lines), f"{manifest_path} is empty")

    parsed: list[tuple[str, str]] = []
    for line_number, line in enumerate(lines, start=1):
        match = _MANIFEST_LINE_RE.fullmatch(line)
        _require(match is not None, f"{manifest_path}:{line_number} must match 'sha256  relative/path'")
        assert match is not None  # narrows type for static checkers
        digest, relative_path = match.group(1), match.group(2)
        _safe_relative_path(f"{manifest_path}:{line_number}", relative_path)
        parsed.append((digest, relative_path))

    listed_paths = [relative for _, relative in parsed]
    _require(listed_paths == sorted(listed_paths), f"{manifest_path} entries must be sorted by relative path")
    _require(len(listed_paths) == len(set(listed_paths)), f"{manifest_path} has duplicate relative paths")
    return parsed


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    _require(path.is_file(), f"required JSONL artifact missing: {path}")
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PackageV2Error(f"{path}:{line_number} is not valid JSON: {exc}") from exc
        _require(isinstance(row, dict), f"{path}:{line_number} must be a JSON object")
        rows.append(row)
    return rows


def _derive_source_identity(article_identity: Any) -> str | None:
    if not isinstance(article_identity, Mapping):
        return None
    for key, prefix in (("pmid", "PMID"), ("pmcid", "PMCID"), ("doi", "DOI")):
        value = article_identity.get(key)
        if value:
            return f"{prefix}:{value}"
    return None


def _require_nonblank_str(value: Any, message: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", message)
    return value


def _extract_delta_counts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the real and synthetic delta-manifest count shapes.

    The real ``raptor.external.r611q_literature_delta_review_bundle.v1``
    manifest carries ``counts`` / ``source_role_counts`` /
    ``baseline_relation_counts`` objects. The tests' simpler synthetic shape
    carries a single flat ``frozen_counts`` object. Both are normalized to
    the same flat key set used by ``inputs.literature_delta.frozen_counts``
    in the spec.
    """

    if isinstance(manifest.get("frozen_counts"), dict):
        return dict(manifest["frozen_counts"])

    counts: dict[str, Any] = {}
    top_counts = manifest.get("counts")
    if isinstance(top_counts, dict):
        for spec_key, manifest_key in (
            ("article_rows", "article_rows"),
            ("exact_alias_candidate_sources", "exact_alias_candidate_sources"),
            ("candidate_spans", "candidate_span_count"),
            ("accepted_claims", "accepted_claims"),
        ):
            if manifest_key in top_counts:
                counts[spec_key] = top_counts[manifest_key]

    source_role_counts = manifest.get("source_role_counts")
    if isinstance(source_role_counts, dict):
        counts["direct_grouped_experiments"] = source_role_counts.get("DIRECT_ALLELE_EXPERIMENT")
        counts["patient_621_model_contexts"] = source_role_counts.get("ALLELE_BEARING_MODEL_CONTEXT")
        counts["clinical_occurrences"] = source_role_counts.get("CLINICAL_CASE_IDENTITY")
        counts["secondary_reviews"] = source_role_counts.get("SECONDARY_REVIEW")

    baseline_relation_counts = manifest.get("baseline_relation_counts")
    if isinstance(baseline_relation_counts, dict):
        counts["narrowing_relations"] = baseline_relation_counts.get("NARROWS")
        counts["contradictions"] = baseline_relation_counts.get("CONTRADICTS")

    return counts


# ---------------------------------------------------------------------------
# 1. verify_repository_v1_manifests
# ---------------------------------------------------------------------------


def verify_repository_v1_manifests(
    repo_root: Path, v1_repository_package: Mapping[str, Any]
) -> dict[str, Any]:
    """Reverify every v1 manifest and every file it lists, read-only.

    ``v1_repository_package`` is the ``inputs.v1_repository_package`` mapping
    from the frozen spec/config: one pin block per group (``literature``,
    ``synthesis``, ``structure_readiness``) plus a ``readiness_summary`` pin.

    This function only opens files in read mode. It never writes, moves, or
    deletes anything under ``repo_root``.
    """

    repo_root = Path(repo_root)
    results: dict[str, Any] = {}

    for group_key in ("literature", "synthesis", "structure_readiness"):
        _require(group_key in v1_repository_package, f"config is missing v1_repository_package.{group_key}")
        pin = v1_repository_package[group_key]

        directory = (repo_root / pin["directory"]).resolve()
        _require(directory.is_dir(), f"v1 directory missing: {directory}")
        _reject_symlink(directory, "v1 directory")

        manifest_path = directory / "manifest.sha256"
        configured_manifest_path = (repo_root / pin["manifest_path"]).resolve()
        _require(
            configured_manifest_path == manifest_path,
            f"manifest_path pin is inconsistent with directory for {group_key}: {pin['manifest_path']}",
        )
        _require(manifest_path.is_file(), f"v1 manifest missing: {manifest_path}")
        _reject_symlink(manifest_path, "v1 manifest")

        manifest_bytes = manifest_path.read_bytes()
        _require(
            len(manifest_bytes) == pin["manifest_byte_length"],
            f"manifest byte length mismatch for {manifest_path}: "
            f"expected {pin['manifest_byte_length']}, found {len(manifest_bytes)}",
        )
        _require(
            _sha256_bytes(manifest_bytes) == pin["manifest_sha256"],
            f"manifest sha256 mismatch for {manifest_path}",
        )

        entries = _parse_sha256_manifest(manifest_path, manifest_bytes)
        _require(
            len(entries) == pin["files_listed"],
            f"manifest files_listed mismatch for {manifest_path}: "
            f"expected {pin['files_listed']}, found {len(entries)}",
        )

        actual_files = {
            candidate.relative_to(directory).as_posix()
            for candidate in directory.rglob("*")
            if candidate.is_file() and candidate.name != "manifest.sha256"
        }
        listed_files = {relative_path for _, relative_path in entries}
        _require(
            listed_files == actual_files,
            f"manifest file-set coverage mismatch for {directory}: "
            f"only-listed={sorted(listed_files - actual_files)}, "
            f"only-actual={sorted(actual_files - listed_files)}",
        )

        recomputed: dict[str, str] = {}
        for digest, relative_path in entries:
            file_path = directory / relative_path
            _require(file_path.is_file(), f"manifest-listed file missing: {file_path}")
            _reject_symlink(file_path, "manifest-listed file")
            _reject_escape(directory, file_path, "manifest-listed file")
            actual_digest = _sha256_file(file_path)
            _require(actual_digest == digest, f"content hash mismatch for {file_path}")
            recomputed[relative_path] = actual_digest

        results[group_key] = {
            "directory": directory,
            "manifest_sha256": pin["manifest_sha256"],
            "manifest_byte_length": pin["manifest_byte_length"],
            "files": recomputed,
        }

    _require("readiness_summary" in v1_repository_package, "config is missing v1_repository_package.readiness_summary")
    readiness_pin = v1_repository_package["readiness_summary"]
    readiness_path = (repo_root / readiness_pin["path"]).resolve()
    _require(readiness_path.is_file(), f"readiness summary missing: {readiness_path}")
    _reject_symlink(readiness_path, "readiness summary")

    readiness_bytes = readiness_path.read_bytes()
    _require(
        len(readiness_bytes) == readiness_pin["byte_length"],
        f"readiness summary byte length mismatch: expected {readiness_pin['byte_length']}, "
        f"found {len(readiness_bytes)}",
    )
    _require(
        _sha256_bytes(readiness_bytes) == readiness_pin["sha256"],
        "readiness summary sha256 mismatch",
    )
    results["readiness_summary"] = {
        "path": readiness_path,
        "sha256": readiness_pin["sha256"],
        "byte_length": readiness_pin["byte_length"],
    }
    return results


# ---------------------------------------------------------------------------
# 2. validate_external_expert_inputs
# ---------------------------------------------------------------------------


def validate_external_expert_inputs(
    packet_path: Path, form_path: Path, pins: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the external, explicit-input Atlas v1 packet/form exact bytes."""

    payloads: dict[str, bytes] = {}
    for key, path in (("packet", Path(packet_path)), ("form", Path(form_path))):
        _require(key in pins, f"config is missing atlas_expert_packet_v1.{key}")
        pin = pins[key]
        _require(path.is_file(), f"external v1 {key} missing: {path}")
        _reject_symlink(path, f"external v1 {key}")
        payload = path.read_bytes()
        _require(
            len(payload) == pin["byte_length"],
            f"external v1 {key} byte length mismatch for {path}: "
            f"expected {pin['byte_length']}, found {len(payload)}",
        )
        _require(
            _sha256_bytes(payload) == pin["sha256"],
            f"external v1 {key} sha256 mismatch for {path}",
        )
        payloads[key] = payload

    try:
        form_mapping = yaml.safe_load(payloads["form"].decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PackageV2Error(f"external v1 form is not valid UTF-8 YAML: {exc}") from exc
    _require(isinstance(form_mapping, dict), "external v1 form must parse to a mapping")
    claims = form_mapping.get("claims")
    _require(
        isinstance(claims, list) and len(claims) >= 2,
        "external v1 form must contain at least two claim records",
    )

    return {
        "packet_bytes": payloads["packet"],
        "form_bytes": payloads["form"],
        "form": form_mapping,
    }


# ---------------------------------------------------------------------------
# 3. validate_delta_bundle
# ---------------------------------------------------------------------------


def validate_delta_bundle(bundle_root: Path, pins: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the real (or synthetic) literature-delta review bundle.

    Verifies the manifest's own file hash/length, its schema, its canonical
    self-hash (the real bundle uses ``content_hash``; a synthetic bundle may
    use ``manifest_content_hash`` -- both are accepted), each required
    artifact's declared and actual hash/length, and cross-checks frozen
    counts where the manifest provides them.
    """

    bundle_root = Path(bundle_root)
    _require(bundle_root.is_dir(), f"delta bundle root missing: {bundle_root}")
    _reject_symlink(bundle_root, "delta bundle root")

    manifest_relative_path = pins.get("manifest_relative_path", "bundle_manifest.json")
    manifest_path = bundle_root / manifest_relative_path
    _require(manifest_path.is_file(), f"delta bundle manifest missing: {manifest_path}")
    _reject_symlink(manifest_path, "delta bundle manifest")

    manifest_bytes = manifest_path.read_bytes()
    _require(
        len(manifest_bytes) == pins["manifest_byte_length"],
        f"delta bundle manifest byte length mismatch: expected {pins['manifest_byte_length']}, "
        f"found {len(manifest_bytes)}",
    )
    _require(
        _sha256_bytes(manifest_bytes) == pins["manifest_file_sha256"],
        "delta bundle manifest sha256 mismatch",
    )

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageV2Error(f"delta bundle manifest is not valid UTF-8 JSON: {exc}") from exc
    _require(isinstance(manifest, dict), "delta bundle manifest must be a JSON object")
    _require(manifest.get("schema") == pins["schema"], "delta bundle manifest schema mismatch")

    canonical_field = "content_hash" if "content_hash" in manifest else "manifest_content_hash"
    _require(canonical_field in manifest, "delta bundle manifest is missing its canonical content-hash field")
    recomputed_hash = _canonical_json_hash(manifest, drop_field=canonical_field)
    _require(
        recomputed_hash == manifest[canonical_field],
        "delta bundle manifest canonical content-hash mismatch",
    )

    required_artifact_pins = pins["required_artifacts"]
    manifest_required = manifest.get("required_artifacts")
    manifest_artifact_list = manifest.get("artifacts")

    artifact_bytes: dict[str, bytes] = {}
    for key, descriptor_pin in required_artifact_pins.items():
        relative_path = descriptor_pin["relative_path"]
        _safe_relative_path(f"delta bundle required_artifacts.{key}", relative_path)

        descriptor: Mapping[str, Any] | None = None
        if isinstance(manifest_required, dict) and key in manifest_required:
            descriptor = manifest_required[key]
        elif isinstance(manifest_artifact_list, list):
            for item in manifest_artifact_list:
                if isinstance(item, dict) and item.get("relative_path") == relative_path:
                    descriptor = item
                    break
        _require(descriptor is not None, f"delta bundle manifest is missing required artifact descriptor: {key}")
        assert descriptor is not None
        _require(
            descriptor.get("relative_path") == relative_path,
            f"delta bundle manifest artifact path mismatch: {key}",
        )
        _require(
            descriptor.get("sha256") == descriptor_pin["sha256"],
            f"delta bundle manifest artifact sha256 pin mismatch: {key}",
        )
        _require(
            int(descriptor.get("byte_length", -1)) == descriptor_pin["byte_length"],
            f"delta bundle manifest artifact byte length pin mismatch: {key}",
        )

        artifact_path = bundle_root / relative_path
        _require(artifact_path.is_file(), f"delta bundle required artifact missing: {artifact_path}")
        _reject_symlink(artifact_path, "delta bundle required artifact")
        _reject_escape(bundle_root, artifact_path, "delta bundle required artifact")

        payload = artifact_path.read_bytes()
        _require(
            len(payload) == descriptor_pin["byte_length"],
            f"delta bundle artifact byte length mismatch for {relative_path}",
        )
        _require(
            _sha256_bytes(payload) == descriptor_pin["sha256"],
            f"delta bundle artifact sha256 mismatch for {relative_path}",
        )
        artifact_bytes[key] = payload

    _require("candidate_spans" in required_artifact_pins, "config is missing literature_delta.required_artifacts.candidate_spans")
    _require("review_records" in required_artifact_pins, "config is missing literature_delta.required_artifacts.review_records")
    candidate_spans = _parse_jsonl(bundle_root / required_artifact_pins["candidate_spans"]["relative_path"])
    review_records = _parse_jsonl(bundle_root / required_artifact_pins["review_records"]["relative_path"])

    frozen_counts_pin = pins.get("frozen_counts") or {}
    actual_counts = _extract_delta_counts(manifest)
    for key, expected_value in frozen_counts_pin.items():
        actual_value = actual_counts.get(key)
        if actual_value is not None:
            _require(
                actual_value == expected_value,
                f"delta bundle frozen count mismatch for {key}: expected {expected_value}, found {actual_value}",
            )

    return {
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "candidate_spans": candidate_spans,
        "review_records": review_records,
        "artifact_bytes": artifact_bytes,
    }


# ---------------------------------------------------------------------------
# 4. select_boundary_observation
# ---------------------------------------------------------------------------


def select_boundary_observation(
    review_records: Sequence[Mapping[str, Any]],
    candidate_spans: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select exactly one semantic boundary observation.

    Matches DIRECT_ALLELE_EXPERIMENT + PRIMARY_R611Q_RESULT + NARROWS +
    NEW_PRIMARY_OBSERVATION + P_COMPLEX_BINDING by semantic field content
    (never by hard-coded article/candidate identity), rejects zero or
    multiple matches, an accepted state, a contradiction relation/state, or
    any Gate 8 change, and cross-binds candidate_id/article_identity/
    source/quote/locator/quote-hash against the matching candidate span.

    For every review record considered: candidate_id and source_id must be
    nonblank strings; article_identity must be a nonempty mapping providing
    at least one canonical identity (PMID > PMCID > DOI precedence); the
    record's source_id must equal that canonical identity exactly;
    acceptance_state must equal ``PROPOSED_UNACCEPTED`` exactly (missing,
    null, or any other value rejects); and, where present, ``gate_effect``,
    ``gate_8_change``, and ``human_gate_8_effect`` must each equal ``NONE``
    exactly (a present-but-null value rejects).

    For the uniquely selected candidate span: its article_identity must be a
    nonempty mapping exactly equal to the record's article_identity; if it
    carries its own source_id, that must equal the canonical identity too;
    its exact_quote must be a nonblank string; its locator must have the
    exact ``text-char:<start>:<end>`` shape with ``start < end``; and its
    exact_quote_sha256/quote_sha256 must be valid lowercase 64-hex and match
    the sha256 of exact_quote. A synthetic record that duplicates
    exact_quote/locator/quote_sha256 must agree with the span exactly; a
    real record may omit those duplicate fields entirely.
    """

    span_by_candidate: dict[Any, list[Mapping[str, Any]]] = {}
    for span in candidate_spans:
        span_by_candidate.setdefault(span.get("candidate_id"), []).append(span)

    matches: list[Mapping[str, Any]] = []
    for record in review_records:
        candidate_id = _require_nonblank_str(
            record.get("candidate_id"), "delta review record is missing a nonblank candidate_id"
        )
        source_id = _require_nonblank_str(
            record.get("source_id"), f"delta review record is missing a nonblank source_id: {candidate_id}"
        )
        article_identity = record.get("article_identity")
        _require(
            isinstance(article_identity, Mapping) and len(article_identity) > 0,
            f"delta review record is missing a nonempty article_identity: {candidate_id}",
        )
        canonical_source_id = _derive_source_identity(article_identity)
        _require(
            canonical_source_id is not None,
            f"delta review record article_identity has no canonical PMID/PMCID/DOI: {candidate_id}",
        )
        _require(
            canonical_source_id == source_id,
            f"delta review record source_id does not match its canonical article_identity: {candidate_id}",
        )

        gate_8_state = record.get("gate_8_state")
        _require(
            gate_8_state is None or gate_8_state == "BLOCKED_HUMAN_REVIEW",
            f"delta review record Gate 8 effect must remain blocked: {candidate_id}",
        )
        if "gate_effect" in record:
            _require(
                record["gate_effect"] == "NONE",
                f"delta review record must not change Gate 8: {candidate_id}",
            )
        if "gate_8_change" in record:
            _require(
                record["gate_8_change"] == "NONE",
                f"delta review record must not change Gate 8: {candidate_id}",
            )
        if "human_gate_8_effect" in record:
            _require(
                record["human_gate_8_effect"] == "NONE",
                f"delta review record must not affect human Gate 8: {candidate_id}",
            )
        contradiction_state = record.get("contradiction_state")
        _require(
            contradiction_state is None or contradiction_state in {"NONE", "NO_CONTRADICTION"},
            f"delta review record contradiction is not allowed: {candidate_id}",
        )
        _require(
            record.get("baseline_relation") != "CONTRADICTS",
            f"delta review record baseline_relation must not contradict: {candidate_id}",
        )
        _require(
            record.get("acceptance_state") == "PROPOSED_UNACCEPTED",
            f"delta review record acceptance_state must be exactly PROPOSED_UNACCEPTED: {candidate_id}",
        )
        accepted_claim_count = record.get("accepted_claim_count")
        _require(
            accepted_claim_count is None or int(accepted_claim_count) == 0,
            f"delta review record accepted claim count must remain zero: {candidate_id}",
        )

        if not all(record.get(key) == value for key, value in _BOUNDARY_EXACT_FIELDS.items()):
            continue

        novelty_value = None
        for key in _BOUNDARY_NOVELTY_KEYS:
            if key in record:
                novelty_value = record[key]
                break
        if novelty_value != _BOUNDARY_NOVELTY_VALUE:
            continue

        claim_kind_ok = record.get("claim_kind") == _BOUNDARY_CLAIM_KIND_VALUE
        proposition_ids = record.get("proposition_ids")
        if not claim_kind_ok and isinstance(proposition_ids, (list, tuple, set)):
            claim_kind_ok = _BOUNDARY_CLAIM_KIND_VALUE in proposition_ids
        if not claim_kind_ok:
            continue

        matches.append(record)

    _require(len(matches) != 0, "expected exactly one semantic boundary match; found zero")
    _require(len(matches) == 1, f"expected exactly one semantic boundary match; found {len(matches)}")

    record = matches[0]
    candidate_id = record["candidate_id"]
    record_source_id = record["source_id"]
    record_article_identity = record["article_identity"]

    spans = span_by_candidate.get(candidate_id, [])
    _require(
        len(spans) == 1,
        f"selected review record candidate span identity is not unique: {candidate_id} ({len(spans)} spans)",
    )
    span = spans[0]

    span_article_identity = span.get("article_identity")
    _require(
        isinstance(span_article_identity, Mapping) and len(span_article_identity) > 0,
        f"selected candidate span is missing a nonempty article_identity: {candidate_id}",
    )
    _require(
        span_article_identity == record_article_identity,
        f"selected candidate span article_identity does not match the review record: {candidate_id}",
    )

    if "source_id" in span:
        _require(
            span["source_id"] == record_source_id,
            f"selected candidate span source_id does not match its canonical article_identity: {candidate_id}",
        )

    quote = _require_nonblank_str(
        span.get("exact_quote"), f"selected candidate span is missing a nonblank exact_quote: {candidate_id}"
    )
    locator = span.get("locator")
    _require(isinstance(locator, str), f"selected candidate span is missing a locator: {candidate_id}")
    locator_match = _TEXT_CHAR_LOCATOR_RE.fullmatch(locator)
    _require(
        locator_match is not None,
        f"selected candidate span locator must have the exact text-char:<start>:<end> shape: {candidate_id}",
    )
    assert locator_match is not None
    _require(
        int(locator_match.group(1)) < int(locator_match.group(2)),
        f"selected candidate span locator must have start < end: {candidate_id}",
    )

    quote_hash = span.get("exact_quote_sha256")
    if quote_hash is None:
        quote_hash = span.get("quote_sha256")
    _require(
        isinstance(quote_hash, str) and _SHA256_HEX_RE.fullmatch(quote_hash) is not None,
        f"selected candidate span quote hash must be valid lowercase 64-hex: {candidate_id}",
    )
    _require(
        _sha256_bytes(quote.encode("utf-8")) == quote_hash,
        f"candidate span quote hash does not match its quote text: {candidate_id}",
    )

    for record_field, span_value in (
        ("exact_quote", quote),
        ("locator", locator),
        ("quote_sha256", quote_hash),
    ):
        if record_field not in record:
            continue
        _require(
            record[record_field] == span_value,
            f"review record {record_field!r} does not match candidate span: {candidate_id}",
        )

    return {
        "candidate_id": candidate_id,
        "source_id": record_source_id,
        "source_role": record["source_role"],
        "primary_result_state": record["primary_result_state"],
        "baseline_relation": record["baseline_relation"],
        "article_identity": span_article_identity,
        "locator": locator,
        "quote_sha256": quote_hash,
        "related_claims": list(PACKET_V2_RELATED_CLAIMS),
        "record": dict(record),
        "span": dict(span),
    }


# ---------------------------------------------------------------------------
# 5. compose_packet_v2
# ---------------------------------------------------------------------------


def compose_packet_v2(v1_packet_bytes: bytes, *, boundary: Mapping[str, Any]) -> bytes:
    """Compose packet v2 as the exact v1 packet bytes plus a delimited,
    append-only addendum section. The addendum uses the registered narrow
    paraphrase, never the source's verbatim quote text.
    """

    _require(
        isinstance(v1_packet_bytes, (bytes, bytearray)) and len(v1_packet_bytes) > 0,
        "v1 packet bytes must be a nonblank byte string",
    )

    qualifiers_md = "\n".join(f"- {qualifier}." for qualifier in PACKET_V2_REQUIRED_QUALIFIERS)
    related_claims_md = ", ".join(f"`{claim_id}`" for claim_id in boundary["related_claims"])

    section = (
        "\n\n---\n\n"
        "## r611q-package-v2-addendum :: r611q-claim-2 (BOUNDARY_OBSERVATION)\n\n"
        "> This section is an append-only v2 addendum. It does not modify any byte "
        "above this delimiter.\n\n"
        f"**Claim ID:** `r611q-claim-2`  \n"
        f"**Related claims:** {related_claims_md}  \n"
        f"**Source role:** `{boundary['source_role']}` "
        f"(primary result state `{boundary['primary_result_state']}`)  \n"
        "**Baseline relation:** `NARROWS` (not `CONTRADICTS`)\n\n"
        "**Proposed candidate statement (registered narrow paraphrase; not the source quote):**\n\n"
        f"> {PACKET_V2_PROPOSED_STATEMENT}\n\n"
        "**Required qualifiers:**\n\n"
        f"{qualifiers_md}\n\n"
        "**Provenance (hash-only; the verbatim source quote is not reproduced here):**\n\n"
        f"- Source quote SHA-256: `{boundary['quote_sha256']}`\n"
        f"- Locator: `{boundary['locator']}`\n\n"
        "**Delta context (context only; no proposition support):**\n\n"
        "- 4 patient-621 model contexts: indirect, non-rescue, `CONTEXT_ONLY`.\n"
        "- 2 clinical occurrences: `OCCURRENCE_ONLY`, no genotype-specific treatment inference.\n"
        "- 3 secondary reviews: `NO_PROPOSITION_SUPPORT`.\n\n"
        "### Claim C (r611q-claim-2) decision\n\n"
        "- [ ] `ACCEPT_AS_WRITTEN`\n"
        "- [ ] `ACCEPT_WITH_NARROWER_WORDING`\n"
        "- [ ] `REJECT`\n"
        "- [ ] `REQUEST_MORE_EVIDENCE`\n\n"
        "**Acceptance state:** `PROPOSED_UNACCEPTED`\n\n"
        "**Final package state:** `accepted_claims=0`; `gate_8=BLOCKED_HUMAN_REVIEW`; "
        "`stage_execution_authorized=false`.\n"
    ).encode("utf-8")

    return bytes(v1_packet_bytes) + section


# ---------------------------------------------------------------------------
# 6. compose_form_v2
# ---------------------------------------------------------------------------

_EXPERT_FORM_TOP_LEVEL_REQUIRED: tuple[str, ...] = ("variant", "bindings", "reviewer", "claims")
_EXPERT_FORM_SCOPE_KEYS: tuple[str, ...] = ("scope_statement", "scope")


def compose_form_v2(
    v1_form: Mapping[str, Any],
    v1_form_bytes: bytes,
    *,
    boundary: Mapping[str, Any],
    base_packet_sha256: str,
    delta_manifest_hash: str,
) -> dict[str, Any]:
    """Deep-copy the real v1 form and append r611q-claim-2, decision-null.

    Preserves the v1 variant/bindings/reviewer fields, the scope statement,
    and the first two claim records exactly. Rejects a malformed v1 form.
    """

    _require(isinstance(v1_form, Mapping), "v1 form must be a mapping")
    missing = [key for key in _EXPERT_FORM_TOP_LEVEL_REQUIRED if key not in v1_form]
    _require(not missing, f"v1 form missing required fields: {missing}")
    claims = v1_form["claims"]
    _require(
        isinstance(claims, list) and len(claims) >= 2,
        "v1 form must contain at least two claim records",
    )

    original_claim_zero = copy.deepcopy(claims[0])
    original_claim_one = copy.deepcopy(claims[1])

    form_v2: dict[str, Any] = copy.deepcopy(dict(v1_form))
    form_v2["claims"] = [copy.deepcopy(claims[0]), copy.deepcopy(claims[1])]

    decision_options = claims[0].get("decision_options") if isinstance(claims[0], Mapping) else None
    if isinstance(decision_options, list) and decision_options:
        claim_two_decision_options = list(decision_options)
    else:
        claim_two_decision_options = list(REAL_DECISION_OPTIONS)

    claim_two = {
        "claim_id": "r611q-claim-2",
        "unit_type": "BOUNDARY_OBSERVATION",
        "source_role": boundary["source_role"],
        "primary_result_state": boundary["primary_result_state"],
        "baseline_relation": "NARROWS",
        "related_claims": list(boundary["related_claims"]),
        "source_id": boundary.get("source_id"),
        "locator": boundary.get("locator"),
        "extracted_text_sha256": boundary.get("quote_sha256"),
        "source_uses_classification_language": False,
        "source_classification_term": None,
        "proposed_statement": PACKET_V2_PROPOSED_STATEMENT,
        "required_qualifiers": list(PACKET_V2_REQUIRED_QUALIFIERS),
        "decision": None,
        "decision_options": claim_two_decision_options,
        "approved_wording": None,
        "approved_kind": None,
        "approved_directionality": None,
        "added_limitations": [],
        "contradiction_found": None,
        "contradiction_assessment": None,
        "rationale": None,
        "narrowing_rationale": None,
        "rejection_basis": None,
        "evidence_gap_description": None,
        "blocking_question": None,
        "acceptance_state": "PROPOSED_UNACCEPTED",
    }
    form_v2["claims"].append(claim_two)

    form_v2["schema"] = FORM_V2_SCHEMA
    form_v2["base_packet_sha256"] = base_packet_sha256
    form_v2["base_form_sha256"] = _sha256_bytes(v1_form_bytes)
    form_v2["delta_manifest_hash"] = delta_manifest_hash
    form_v2["accepted_claim_count"] = 0
    form_v2["gate_8_state"] = "BLOCKED_HUMAN_REVIEW"

    packet_status = str(v1_form.get("packet_status", "unreviewed"))
    _require(
        packet_status.strip().lower() == "unreviewed",
        "v1 form packet_status must be unreviewed to compose a v2 addendum",
    )
    form_v2["packet_status"] = v1_form.get("packet_status", "unreviewed")

    _require(form_v2["claims"][0] == original_claim_zero, "form v2 must preserve claim 0 exactly")
    _require(form_v2["claims"][1] == original_claim_one, "form v2 must preserve claim 1 exactly")
    _require(form_v2["variant"] == v1_form["variant"], "form v2 must preserve variant exactly")
    _require(form_v2["bindings"] == v1_form["bindings"], "form v2 must preserve bindings exactly")
    _require(form_v2["reviewer"] == v1_form["reviewer"], "form v2 must preserve reviewer exactly")
    for scope_key in _EXPERT_FORM_SCOPE_KEYS:
        if scope_key in v1_form:
            _require(
                form_v2[scope_key] == v1_form[scope_key],
                f"form v2 must preserve {scope_key} exactly",
            )

    return form_v2


# ---------------------------------------------------------------------------
# 7. build_impact_record_v2
# ---------------------------------------------------------------------------


def build_impact_record_v2(*, frozen_counts: Mapping[str, Any]) -> dict[str, Any]:
    """Build the bounded synthesis-impact record for the v2 addendum.

    v1 literature/synthesis/structure are IMMUTABLE; RH-2 stays
    PLAUSIBLE_NOT_DEMONSTRATED; TSC2-TSC2 co-IP is NON_DISCRIMINATING; AF-4
    remains TSC1-TSC2 with matched abundance; model/clinical/review counts
    are context/occurrence/no-support only; accepted claims and
    contradictions are 0; Gate 8 is blocked; stage execution is
    unauthorized; the historical 4,169-corpus expansion stays deferred.
    """

    for required_key in (
        "patient_621_model_contexts",
        "clinical_occurrences",
        "secondary_reviews",
        "contradictions",
        "accepted_claims",
    ):
        _require(required_key in frozen_counts, f"impact record is missing frozen_counts.{required_key}")

    return {
        "schema": IMPACT_SCHEMA,
        "literature_v1": "IMMUTABLE",
        "synthesis_v1": "IMMUTABLE",
        "structure_readiness_v1": "IMMUTABLE",
        "route_effect": {"RH-2": "PLAUSIBLE_NOT_DEMONSTRATED"},
        "coip_interpretation": "TSC2-TSC2_NON_DISCRIMINATING",
        "assay_falsifier": {"AF-4": "TSC1-TSC2_WITH_MATCHED_ABUNDANCE"},
        "model_contexts": {
            "count": int(frozen_counts["patient_621_model_contexts"]),
            "package_effect": "CONTEXT_ONLY",
        },
        "clinical_occurrences": {
            "count": int(frozen_counts["clinical_occurrences"]),
            "package_effect": "OCCURRENCE_ONLY",
        },
        "secondary_reviews": {
            "count": int(frozen_counts["secondary_reviews"]),
            "package_effect": "NO_PROPOSITION_SUPPORT",
        },
        "contradictions": int(frozen_counts["contradictions"]),
        "accepted_claims": int(frozen_counts["accepted_claims"]),
        "gate_8": "BLOCKED_HUMAN_REVIEW",
        "stage_execution_authorized": False,
        "historical_4169_expansion": False,
        "historical_tsc2_corpus_expansion": "deferred",
    }


def _render_package_summary_markdown(*, boundary: Mapping[str, Any], impact: Mapping[str, Any]) -> bytes:
    text = (
        "# R611Q package-v2 addendum summary\n\n"
        "This external artifact summarizes the v2 addendum composed over the immutable "
        "literature-v1, synthesis-v1 and structure-readiness-v1 RescueScreen evidence pack, "
        "the unreviewed Atlas expert packet/form, and the reviewed 2026-09-16 literature "
        "delta bundle.\n\n"
        "## New review unit\n\n"
        "- `claim_id`: `r611q-claim-2`\n"
        "- `unit_type`: `BOUNDARY_OBSERVATION`\n"
        f"- `source_role`: `{boundary['source_role']}`\n"
        f"- `primary_result_state`: `{boundary['primary_result_state']}`\n"
        f"- `baseline_relation`: `{boundary['baseline_relation']}` (not `CONTRADICTS`)\n"
        "- `acceptance_state`: `PROPOSED_UNACCEPTED`\n\n"
        "## Synthesis impact\n\n"
        f"- literature-v1 / synthesis-v1 / structure-readiness-v1: `{impact['literature_v1']}`\n"
        f"- RH-2 route effect: `{impact['route_effect']['RH-2']}`\n"
        f"- TSC2-TSC2 co-IP interpretation: `{impact['coip_interpretation']}`\n"
        f"- AF-4 assay falsifier: `{impact['assay_falsifier']['AF-4']}`\n"
        f"- model contexts: {impact['model_contexts']['count']} (`{impact['model_contexts']['package_effect']}`)\n"
        f"- clinical occurrences: {impact['clinical_occurrences']['count']} "
        f"(`{impact['clinical_occurrences']['package_effect']}`)\n"
        f"- secondary reviews: {impact['secondary_reviews']['count']} "
        f"(`{impact['secondary_reviews']['package_effect']}`)\n"
        f"- contradictions: {impact['contradictions']}\n"
        f"- accepted claims: {impact['accepted_claims']}\n"
        f"- Gate 8: `{impact['gate_8']}`\n"
        f"- stage execution authorized: `{impact['stage_execution_authorized']}`\n"
        f"- historical ~4,169-publication corpus expansion: `{impact['historical_tsc2_corpus_expansion']}`\n"
    )
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# 8. render_external_package
# ---------------------------------------------------------------------------


def render_external_package(
    output_root: Path,
    *,
    package_id: str,
    repository_summary_target: str,
    artifacts: Mapping[str, bytes],
    repo_root: Path | None = None,
) -> tuple[Path, tuple[str, ...]]:
    """Render the four payload artifacts plus package_manifest.json.

    ``output_root`` must be absolute and neither it nor any ancestor may be a
    symlink/reparse point. When ``repo_root`` is given (used by the CLI),
    ``output_root`` must additionally resolve outside it -- this keyword is
    optional and preserves compatibility with existing callers that omit it.
    The package directory (``output_root / package_id``) must not already
    exist (create-only). All payloads are written to a staging directory
    first, with ``package_manifest.json`` written last inside staging; the
    staging directory is then published with a single no-replace rename. Any
    failure removes only the staging directory this call created -- never a
    partial final package directory.
    """

    output_root = Path(output_root)
    _require(output_root.is_absolute(), "external render root must be absolute")
    _reject_symlink_ancestry(output_root, "external package output root")
    if repo_root is not None:
        _require_outside_repo(output_root, Path(repo_root), "external package output root")

    payload_names = EXPECTED_EXTERNAL_ARTIFACTS[:-1]
    _require(
        set(artifacts) == set(payload_names),
        "external render requires exactly the four payload artifacts",
    )

    package_dir = output_root / package_id
    _reject_symlink_ancestry(package_dir, "external package path")
    _require(
        not package_dir.exists(),
        f"external package path already exists (create-only contract): {package_dir}",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{package_id}.staging-", dir=str(output_root)))
    try:
        staging_dir_resolved = staging_dir.resolve()
        written_order: list[str] = []
        manifest_rows: list[dict[str, Any]] = []
        for name in payload_names:
            target = staging_dir / name
            _require(
                target.resolve().parent == staging_dir_resolved,
                f"artifact path escaped staging directory: {name}",
            )
            payload = artifacts[name]
            _require(isinstance(payload, (bytes, bytearray)), f"artifact payload must be bytes: {name}")
            target.write_bytes(payload)
            _reject_symlink(target, f"staged artifact {name}")
            written_order.append(name)
            manifest_rows.append(
                {"name": name, "sha256": _sha256_bytes(payload), "byte_length": len(payload)}
            )

        manifest: dict[str, Any] = {
            "schema": PACKAGE_MANIFEST_SCHEMA,
            "package_id": package_id,
            "create_only": True,
            "repository_summary_target": repository_summary_target,
            "artifacts": manifest_rows,
        }
        manifest["manifest_content_hash"] = _canonical_json_hash(manifest, drop_field="manifest_content_hash")
        (staging_dir / "package_manifest.json").write_bytes(_canonical_json_bytes(manifest))
        written_order.append("package_manifest.json")

        _require(
            not package_dir.exists(),
            f"external package path already exists (create-only contract): {package_dir}",
        )
        os.rename(staging_dir, package_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return package_dir, tuple(written_order)


# ---------------------------------------------------------------------------
# 9. build_repository_summary
# ---------------------------------------------------------------------------


def build_repository_summary(
    *,
    input_hashes: Mapping[str, str],
    output_hashes: Mapping[str, str],
    accepted_claim_count: int,
    gate_8_state: str,
    stage_execution_authorized: bool,
    package_update_warranted: bool = True,
    broader_historical_corpus_expansion_warranted: bool = False,
) -> tuple[dict[str, Any], str]:
    """Build the aggregate-only repository summary JSON + README.

    Contains only exact input/output hashes, aggregate counts, the accepted
    claim count, Gate 8 state, stage-execution state, and the explicit
    no-historical-expansion decision. It never carries a new PMID, PMCID,
    DOI, article title, source quote, locator, candidate identifier, or
    patient-level detail.
    """

    summary: dict[str, Any] = {
        "schema": REPOSITORY_SUMMARY_SCHEMA,
        "inputs": dict(input_hashes),
        "outputs": dict(output_hashes),
        "counts": {"accepted_claims": int(accepted_claim_count)},
        "state": {
            "gate_8": gate_8_state,
            "stage_execution_authorized": bool(stage_execution_authorized),
            "historical_tsc2_corpus_expansion": "deferred",
        },
        "decisions": {
            "package_update_warranted": bool(package_update_warranted),
            "broader_historical_corpus_expansion_warranted": bool(
                broader_historical_corpus_expansion_warranted
            ),
        },
    }
    readme = (
        "# R611Q package-v2 addendum repository summary\n\n"
        "This repository summary is an aggregate-only projection. It records exact input "
        "and output artifact hashes, aggregate counts, the accepted-claim count, the Gate 8 "
        "state, the stage-execution state, and the explicit no-historical-expansion decision. "
        "It carries no new source-identity, quotation, span, sample-level or record-level "
        "detail.\n"
    )

    serialized = json.dumps(summary, sort_keys=True).lower() + "\n" + readme.lower()
    for token in _FORBIDDEN_SUMMARY_TOKENS:
        _require(token not in serialized, f"repository summary leaked restricted identity content: {token!r}")

    return summary, readme


# ---------------------------------------------------------------------------
# 10. build_r611q_package_v2_addendum (top-level orchestrator)
# ---------------------------------------------------------------------------


def build_r611q_package_v2_addendum(
    *,
    config: Mapping[str, Any],
    repo_root: Path,
    v1_packet_path: Path,
    v1_form_path: Path,
    delta_bundle_root: Path,
) -> dict[str, Any]:
    """Verify every v1/external/delta input and compose the v2 package in memory.

    This is the pure composition engine: it never writes a file. Callers
    (the CLI operator) are responsible for optionally calling
    ``render_external_package`` and ``build_repository_summary`` to persist
    the result.
    """

    for required_key in ("v1_repository_package", "atlas_expert_packet_v1", "literature_delta"):
        _require(required_key in config, f"config is missing required section: {required_key}")

    v1_repository_package = config["v1_repository_package"]
    atlas_pins = config["atlas_expert_packet_v1"]
    delta_pins = config["literature_delta"]

    repo_verification = verify_repository_v1_manifests(Path(repo_root), v1_repository_package)
    expert_inputs = validate_external_expert_inputs(Path(v1_packet_path), Path(v1_form_path), atlas_pins)
    delta = validate_delta_bundle(Path(delta_bundle_root), delta_pins)

    boundary = select_boundary_observation(delta["review_records"], delta["candidate_spans"])

    manifest = delta["manifest"]
    input_hashes = manifest.get("input_hashes")
    if isinstance(input_hashes, dict):
        packet_hash = input_hashes.get("atlas_expert_packet_sha256")
        form_hash = input_hashes.get("atlas_expert_form_sha256")
        if packet_hash is not None:
            _require(
                packet_hash == atlas_pins["packet"]["sha256"],
                "delta bundle was not built against the pinned v1 expert packet",
            )
        if form_hash is not None:
            _require(
                form_hash == atlas_pins["form"]["sha256"],
                "delta bundle was not built against the pinned v1 expert form",
            )

    packet_v2_bytes = compose_packet_v2(expert_inputs["packet_bytes"], boundary=boundary)
    base_packet_sha256 = _sha256_bytes(expert_inputs["packet_bytes"])
    form_v2 = compose_form_v2(
        expert_inputs["form"],
        expert_inputs["form_bytes"],
        boundary=boundary,
        base_packet_sha256=base_packet_sha256,
        delta_manifest_hash=delta["manifest_sha256"],
    )
    form_v2_bytes = yaml.safe_dump(form_v2, sort_keys=False, allow_unicode=True).encode("utf-8")

    impact = build_impact_record_v2(frozen_counts=delta_pins["frozen_counts"])
    impact_bytes = (json.dumps(impact, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    summary_bytes = _render_package_summary_markdown(boundary=boundary, impact=impact)

    external_artifacts: dict[str, bytes] = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": packet_v2_bytes,
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": form_v2_bytes,
        "R611Q_PACKAGE_V2_IMPACT.json": impact_bytes,
        "R611Q_PACKAGE_V2_SUMMARY.md": summary_bytes,
    }

    input_hashes_summary = {
        "literature_manifest_sha256": v1_repository_package["literature"]["manifest_sha256"],
        "synthesis_manifest_sha256": v1_repository_package["synthesis"]["manifest_sha256"],
        "structure_readiness_manifest_sha256": v1_repository_package["structure_readiness"]["manifest_sha256"],
        "readiness_summary_sha256": v1_repository_package["readiness_summary"]["sha256"],
        "atlas_packet_v1_sha256": atlas_pins["packet"]["sha256"],
        "atlas_form_v1_sha256": atlas_pins["form"]["sha256"],
        "delta_manifest_sha256": delta["manifest_sha256"],
    }
    output_hashes_summary = {
        f"{name.rsplit('.', 1)[0].lower()}_sha256": _sha256_bytes(payload)
        for name, payload in external_artifacts.items()
    }

    return {
        "boundary": boundary,
        "packet_v2_bytes": packet_v2_bytes,
        "form_v2": form_v2,
        "form_v2_bytes": form_v2_bytes,
        "impact": impact,
        "impact_bytes": impact_bytes,
        "external_artifacts": external_artifacts,
        "input_hashes_summary": input_hashes_summary,
        "output_hashes_summary": output_hashes_summary,
        "repo_verification": repo_verification,
        "delta": delta,
    }
