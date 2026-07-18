"""Slot 3 — `predictor_leakage_audit.py` — the direct/component training
manifest leakage audit (RAPTOR PP3/BP4 shadow policy, steps 2-7).

Reads benchmark `variant_id`s only (never labels or held-out criterion
outputs) plus every direct/component training-manifest the registry itself
declares required, hash-verifies each against that manifest registry, and
reports a fail-closed precedence status: `BLOCKED_DATA` > `FAIL` >
`UNKNOWN` > `PASS`. The required manifest set is derived from the
registry, never only from the paths the caller happened to supply -- a
caller path omission cannot erase a registry requirement: a registry entry
marked `available` with no supplied path is `BLOCKED_DATA`; an
unavailable/unverified required entry with no supplied path is `UNKNOWN`.
`PASS` is reachable only when every registry-required manifest is
available, hash-verified, and shows zero overlap.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

import yaml

#: Canonical SPDI variant identity, mirroring `pp3bp4_score_table._SPDI_RE`.
_SPDI_RE = re.compile(r"^[A-Za-z]{1,4}_\d+\.\d+:\d+:[ACGTNacgtn]*:[ACGTNacgtn]*$")


class LeakageStatus(Enum):
    """Closed, distinct precedence-ordered status set (T-D1):
    `BLOCKED_DATA` > `FAIL` > `UNKNOWN` > `PASS`."""

    BLOCKED_DATA = "BLOCKED_DATA"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"


class LeakageValidationError(ValueError):
    """Raised on a hash mismatch between a manifest's declared registry
    hash and its actual file bytes, or an unnormalizable variant_id under
    `force_normalization=True`. Fail-closed -- never silently ignored."""


@dataclass
class LeakageAuditResult:
    """Deterministic-content leakage audit result (T-D1).

    `content_hash` excludes nothing but itself and is computed only from
    benchmark variant IDs (never labels) plus overlap counts/status --
    changing a benchmark row's label alone never changes `content_hash`
    (label invariance)."""

    status: LeakageStatus
    direct_overlap: int
    component_overlap: int
    benchmark_id_set_sha256: str
    benchmark_n: int
    content_hash: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_benchmark_ids(path: Path, *, force_normalization: bool) -> list[str]:
    """Read ONLY `variant_id` from each benchmark row -- labels/review
    status/etc. are never read here (Rule 5)."""
    ids: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            variant_id = row["variant_id"]
            if force_normalization and not _SPDI_RE.match(variant_id):
                raise LeakageValidationError(
                    f"benchmark variant_id {variant_id!r} is not normalizable to canonical SPDI"
                )
            ids.append(variant_id)
    return ids


def _read_manifest_ids(path: Path) -> set[str]:
    """Read a plain-text (one-id-per-line) or JSONL training manifest as a
    set of variant IDs."""
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                row = json.loads(line)
                ids.add(row["variant_id"])
            else:
                ids.add(line)
    return ids


def _compute_id_set_hash(ids: list[str]) -> str:
    digest = hashlib.sha256()
    for variant_id in sorted(ids):
        digest.update(variant_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def evaluate_leakage_audit(
    *,
    benchmark_path: str | Path | None,
    direct_manifest_path: str | Path | None = None,
    component_manifest_paths: Mapping[str, str | Path] | None = None,
    registry_path: str | Path | None = None,
    force_normalization: bool = False,
) -> LeakageAuditResult:
    """Evaluate direct/component training-manifest leakage against a
    benchmark (T-D1/T-D2).

    `BLOCKED_DATA` when the benchmark or registry itself cannot be
    read/parsed. `LeakageValidationError` when a manifest's registry-
    declared hash does not match its actual bytes, or (with
    `force_normalization=True`) a benchmark id cannot be normalized to
    canonical SPDI. Otherwise: `FAIL` if any direct/component overlap is
    found; else `UNKNOWN` if any manifest this audit checked (or was asked
    to check but had none provided) is unavailable/unverified; else
    `PASS`."""
    benchmark_file = Path(benchmark_path) if benchmark_path is not None else None
    if benchmark_file is None or not benchmark_file.is_file():
        return LeakageAuditResult(
            status=LeakageStatus.BLOCKED_DATA,
            direct_overlap=0,
            component_overlap=0,
            benchmark_id_set_sha256="",
            benchmark_n=0,
            content_hash=_content_hash(LeakageStatus.BLOCKED_DATA, 0, 0, "", 0),
        )

    benchmark_ids = _read_benchmark_ids(benchmark_file, force_normalization=force_normalization)
    benchmark_id_set = set(benchmark_ids)
    benchmark_id_set_sha256 = _compute_id_set_hash(benchmark_ids)

    registry_file = Path(registry_path) if registry_path is not None else None
    if registry_file is None or not registry_file.is_file():
        return LeakageAuditResult(
            status=LeakageStatus.BLOCKED_DATA,
            direct_overlap=0,
            component_overlap=0,
            benchmark_id_set_sha256=benchmark_id_set_sha256,
            benchmark_n=len(benchmark_ids),
            content_hash=_content_hash(
                LeakageStatus.BLOCKED_DATA, 0, 0, benchmark_id_set_sha256, len(benchmark_ids)
            ),
        )

    try:
        registry = yaml.safe_load(registry_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LeakageValidationError(f"manifest registry is not valid YAML/JSON: {exc}") from exc
    if not isinstance(registry, dict):
        raise LeakageValidationError("manifest registry root must be a mapping")

    registry_direct_entry = registry.get("direct")
    registry_components = registry.get("components") or {}

    # Required manifest rule (Slot 2 Rule 4): the required set comes from the
    # registry, never only from the caller-supplied paths. A caller path
    # omission cannot erase a registry requirement.
    required_entries: list[tuple[str, dict]] = []
    if registry_direct_entry is not None:
        required_entries.append(("direct", registry_direct_entry))
    for comp_name, comp_entry in registry_components.items():
        required_entries.append((comp_name, comp_entry))

    supplied_paths: dict[str, Path] = {}
    if direct_manifest_path is not None:
        supplied_paths["direct"] = Path(direct_manifest_path)
    for name, path in (component_manifest_paths or {}).items():
        supplied_paths[name] = Path(path)

    required_names = {name for name, _ in required_entries}
    # Caller-supplied paths with no matching registry entry are checked but
    # can never be proven required/clean -- preserves prior best-effort
    # overlap accounting for non-registry paths.
    extra_supplied_names = [name for name in supplied_paths if name not in required_names]

    direct_overlap = 0
    component_overlap = 0
    blocked_data = False
    # Nothing was required and nothing was supplied: nothing has been proven
    # clean -- this can never read PASS (falls through to UNKNOWN below).
    any_unverified_or_unavailable = not required_entries and not extra_supplied_names

    for name, entry in required_entries:
        path = supplied_paths.get(name)
        if path is None or not path.is_file():
            # Available-but-missing input is BLOCKED_DATA; an
            # unavailable/unverified required input (with no path) is
            # UNKNOWN. Caller path omission cannot erase either status.
            if bool(entry.get("available", False)):
                blocked_data = True
            else:
                any_unverified_or_unavailable = True
            continue

        available = bool(entry.get("available", False))
        verified = bool(entry.get("verified", False))
        if available and verified:
            actual_sha256 = _sha256_file(path)
            declared_sha256 = entry.get("sha256")
            if declared_sha256 != actual_sha256:
                raise LeakageValidationError(
                    f"manifest {name!r} sha256 mismatch against registry: "
                    f"registry={declared_sha256!r} actual={actual_sha256!r}"
                )
        else:
            any_unverified_or_unavailable = True

        manifest_ids = _read_manifest_ids(path)
        overlap_count = len(benchmark_id_set & manifest_ids)
        if name == "direct":
            direct_overlap += overlap_count
        else:
            component_overlap += overlap_count

    for name in extra_supplied_names:
        # Not named in the registry: cannot be verified, so it is never
        # counted toward overlap -- only marked unverified (unchanged
        # behavior for non-registry paths).
        any_unverified_or_unavailable = True

    if blocked_data:
        status = LeakageStatus.BLOCKED_DATA
    elif direct_overlap > 0 or component_overlap > 0:
        status = LeakageStatus.FAIL
    elif any_unverified_or_unavailable:
        status = LeakageStatus.UNKNOWN
    else:
        status = LeakageStatus.PASS

    return LeakageAuditResult(
        status=status,
        direct_overlap=direct_overlap,
        component_overlap=component_overlap,
        benchmark_id_set_sha256=benchmark_id_set_sha256,
        benchmark_n=len(benchmark_ids),
        content_hash=_content_hash(
            status, direct_overlap, component_overlap, benchmark_id_set_sha256, len(benchmark_ids)
        ),
    )


def _content_hash(
    status: LeakageStatus, direct_overlap: int, component_overlap: int,
    benchmark_id_set_sha256: str, benchmark_n: int,
) -> str:
    payload = {
        "status": status.value,
        "direct_overlap": direct_overlap,
        "component_overlap": component_overlap,
        "benchmark_id_set_sha256": benchmark_id_set_sha256,
        "benchmark_n": benchmark_n,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
