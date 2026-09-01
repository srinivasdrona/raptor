"""ADR-0020 / `docs/project/specs/clinvar-2026-08-prospective-amendment-v2.yaml`
-- the ADR-0013 prospective amendment v2 PRE-DATA freeze/adjudication
boundary (`raptor.eval.prospective_freeze`).

This module is the ADDITIVE, later implementation the amendment planning
contract required before `APPROVED_PRE_DATA` could ever be recorded. It
never touches the terminal ADR-0013 `BLOCKED_DATA` artifact, the historical
`configs/eval/tiered_gate_v3.yaml#prospective_validation.dataset_rule`
locator, or `configs/eval/tsc2.yaml#labels_snapshot` in place -- dataset
identity for THIS registration flows only through the registered,
hash-pinned prospective eval-overlay (`merge_prospective_overlay`).

Four independent surfaces live here, all fail-closed and all sharing the
same typed error/stop-state vocabulary:

* `validate_pre_data_approval` / the internal approval gate inside
  `execute_transport_and_raw_freeze` -- a CLOSED-schema check of the
  `raptor.eval.pre_data_approval.v1` record. Any schema, approver, decision,
  hash-drift, unimplemented-protection, non-vacuous-attestation or
  approval-vs-first-GET timing breach raises a typed
  `ProspectiveStopStateError` (`.code`/`.stop_state` one of
  `PRE_DATA_STOP_STATES`) BEFORE any network call. This gate governs ONLY
  ADR-0020 stages 1-2 (transport freeze + raw archive acquisition) and
  requires exactly the prospective dataset/source identity (registration +
  overlay hash-pins), an approval timestamp strictly before the first
  archive GET, and the existing exact-source transport/hash-chain
  protections (stage-1 HEAD comparison, official MD5, raw SHA-256). It
  never requires, reads, or checks x64/BIAS/Nirvana identity -- ClinVar
  archive acquisition has no x86-only requirement (see
  `docs/ops/adr-0008-resource-manifest-digest.md` "Non-goals" and
  `scripts/run_clinvar_2026_08_prospective_freeze.py`'s module docstring).
* `execute_transport_and_raw_freeze` -- stage 1 (`HEAD` + published-date +
  official-MD5-source verification) and stage 2 (bounded streamed GET of
  ONLY the exact registered archive, raw hashing) of the contract's ordered
  execution sequence. It NEVER performs stage 3+ (label read, benchmark
  build, scoring) -- `label_reader`/`benchmark_builder`/`scoring_runner`
  are accepted for a future additive stage and are never invoked here. It
  is restart-idempotent (a byte-identical prior freeze is reused, never
  re-fetched), single-writer-safe (an in-process lock serializes concurrent
  callers for the same freeze-record pair), and every destination write is
  boundary-checked (no traversal, no symlink-follow, no special file) and
  atomic (temp-write + `os.replace`, crash leaves no partial artifact).
* `validate_scoring_stage_approval` / `assert_runtime_boundary` -- the
  SEPARATE, LATER gate for ADR-0020 stage 4 (`4_MASK_AND_LABEL_FREE_SCORE`):
  the mandatory ADR-0008 x64 worker / BIAS / Nirvana / resource-manifest
  identity check that MUST pass before any BIAS/Nirvana execution or
  label-dependent evaluation. It is deliberately independent of, and never
  consulted by, stages 1-2 above. It never trusts the approval record's
  claimed `x64_freeze` block, its claimed `immutable_inputs_verified` flag,
  or any caller-supplied "observed identity" mapping: it always calls
  `observe_runtime_identity` itself (worker designation/BIAS commit/Nirvana
  banner independently read from dedicated marker files under
  `DESIGNATED_X64_WORKER_ROOT`, architecture from `platform.machine()`),
  always independently RECOMPUTES `resource_manifest_sha256` from the
  actual manifest files at the one designated checksums location via
  `compute_resource_manifest_sha256`, and always independently RECOMPUTES
  every `immutable_inputs` entry's hash from the current repository file
  bytes -- never accepting any of these as a claim -- then requires the
  approval record's claimed pins to equal that observed/recomputed
  identity exactly. A merely well-formed but fabricated claimed digest
  (e.g. all-zero) is therefore always rejected, and a static pinned
  literal supplied on a non-designated runtime is rejected too, because
  that runtime's own independent observation genuinely differs. It also
  requires a mandatory, immutable `first_scoring_execution_at` timestamp
  strictly after `approved_at`; a missing, malformed, future-dated, or
  mistimed value is always rejected. A schema breach, wrong decision/
  approver, mistimed approval/execution timestamp, immutable-inputs
  mismatch, or any observed-vs-claimed identity mismatch raises
  `ProspectiveInvalidStateError` (`.code == "INVALID"`, an A0 run-integrity
  failure per the registration spec's stage 4 rule), never a `PRE_DATA_*`
  stop state.
* `adjudicate_prospective_outcomes` -- the ADR-0020 A0-A6 per-scope axis
  projection, the closed six-value terminal-outcome vocabulary, and the
  full-spectrum/narrow-scope precedence and authorization mapping. It
  trusts (never recomputes) each scope's pre-derived A1/A2/A3 verdict --
  it only validates the closed enum, derives A4/A5/A6, and applies the
  registered precedence -- so it can never itself read a label, a
  benchmark row, or a score. Its VERY FIRST action, unconditionally, is
  calling `validate_scoring_stage_approval`: no outcome dict of any kind
  (including `PASS`/`AUTHORIZED_RESEARCH_ONLY`) can ever be produced
  without a validated, anti-fabrication-checked scoring-stage approval and
  observed runtime identity.

Nothing in this module ever performs a real archive GET, HEAD, or lookup:
`transport`, `published_archive_date_lookup`, and `official_md5_lookup` are
always caller-injected ports (`transport=None` is a hard `INVALID`, never a
live-network fallback -- there is no default HTTP implementation here).
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import platform
import re
import stat
import subprocess
import threading
import uuid
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping

import yaml

__all__ = [
    "MAX_DOWNLOAD_CHUNK_BYTES",
    "PRE_DATA_STOP_STATES",
    "HEAD_REASON_CODES",
    "TERMINAL_OUTCOME_VOCAB",
    "A5_PRECEDENCE",
    "FULL_SPECTRUM_PRECEDENCE",
    "RESOURCE_MANIFEST_DIGEST_SCHEMA",
    "RESOURCE_MANIFEST_ENTRIES",
    "DESIGNATED_X64_WORKER_ROOT",
    "REQUIRED_IMPLEMENTATION_FREEZE_MODULES",
    "REQUIRED_IMPLEMENTATION_FREEZE_FILES",
    "ProspectiveContractError",
    "ProspectiveStopStateError",
    "ProspectiveInvalidStateError",
    "assert_runtime_boundary",
    "resource_manifest_entries",
    "compute_resource_manifest_sha256",
    "observe_runtime_identity",
    "capture_transport_identity_pin",
    "validate_scoring_stage_approval",
    "merge_prospective_overlay",
    "validate_pre_data_approval",
    "execute_transport_and_raw_freeze",
    "adjudicate_prospective_outcomes",
]

# ---------------------------------------------------------------------------
# Closed contract vocabulary (spec `pre_data_approval.stop_states`,
# `dataset_registration.stage_1_head_comparison`, `terminal_outcomes`).
# ---------------------------------------------------------------------------

#: A bounded per-request streaming chunk ceiling (spec "bounded streamed
#: external download abstraction") -- the archive is never buffered whole
#: in memory before being hashed/written.
MAX_DOWNLOAD_CHUNK_BYTES = 1_048_576

#: The five typed PRE-DATA stop states (`pre_data_approval.stop_states`).
PRE_DATA_STOP_STATES: tuple[str, ...] = (
    "PRE_DATA_REVIEW_REQUIRED",
    "PRE_DATA_REJECTED",
    "PRE_DATA_IMPLEMENTATION_NOT_READY",
    "PRE_DATA_DRIFT",
    "PRE_DATA_ATTESTATION_BREACH",
)

#: The ten typed stage-1 HEAD-comparison reason codes.
HEAD_REASON_CODES: tuple[str, ...] = (
    "HEAD_STATUS_MISMATCH",
    "HEAD_FINAL_URL_MISMATCH",
    "HEAD_LAST_MODIFIED_MISSING",
    "HEAD_LAST_MODIFIED_DUPLICATE",
    "HEAD_LAST_MODIFIED_MALFORMED",
    "HEAD_LAST_MODIFIED_MISMATCH",
    "HEAD_CONTENT_LENGTH_MISSING",
    "HEAD_CONTENT_LENGTH_DUPLICATE",
    "HEAD_CONTENT_LENGTH_MALFORMED",
    "HEAD_CONTENT_LENGTH_MISMATCH",
)

#: The closed six-value terminal-outcome vocabulary (`terminal_outcomes.vocabulary`).
TERMINAL_OUTCOME_VOCAB: tuple[str, ...] = (
    "PASS",
    "FAIL",
    "NOT_ESTIMABLE",
    "BLOCKED_POLICY",
    "BLOCKED_DATA",
    "INVALID",
)

#: Per-scope A5 precedence (`terminal_outcomes.axis_outputs.A5_precedence_preserved`).
A5_PRECEDENCE: tuple[str, ...] = (
    "INVALID",
    "NOT_APPLICABLE",
    "NO_CALLS",
    "UNDERPOWERED",
    "BLOCKED_POLICY",
    "NOT_SUPPORTED",
    "VALIDATED_PROSPECTIVE",
)

#: Full-spectrum precedence (`terminal_outcomes.full_spectrum_aggregation.precedence`).
FULL_SPECTRUM_PRECEDENCE: tuple[str, ...] = (
    "BLOCKED_DATA",
    "INVALID",
    "BLOCKED_POLICY",
    "FAIL",
    "NOT_ESTIMABLE",
    "PASS",
)

#: `terminal_outcomes.full_spectrum_aggregation.outcome_to_status_and_authorization`.
_OUTCOME_STATUS_AND_AUTH: dict[str, tuple[str, str]] = {
    "BLOCKED_DATA": ("NOT_VALIDATED", "NOT_AUTHORIZED"),
    "INVALID": ("INVALID", "NOT_AUTHORIZED"),
    "BLOCKED_POLICY": ("BLOCKED_POLICY", "NOT_AUTHORIZED"),
    "FAIL": ("NOT_VALIDATED", "NOT_AUTHORIZED"),
    "NOT_ESTIMABLE": ("NOT_VALIDATED", "NOT_AUTHORIZED"),
    "PASS": ("VALIDATED_PROSPECTIVE", "AUTHORIZED_RESEARCH_ONLY"),
}

#: Per-scope A5 -> scope-level terminal-outcome projection (narrow-scope
#: independence, `terminal_outcomes.narrow_scope_independence`).
_A5_TO_SCOPE_TERMINAL: dict[str, str] = {
    "VALIDATED_PROSPECTIVE": "PASS",
    "BLOCKED_POLICY": "BLOCKED_POLICY",
    "NOT_SUPPORTED": "FAIL",
    "NO_CALLS": "NOT_ESTIMABLE",
    "UNDERPOWERED": "NOT_ESTIMABLE",
    "NOT_APPLICABLE": "NOT_ESTIMABLE",
    "INVALID": "INVALID",
}

#: ADR-0008 pinned x64 worker/tool identity dimensions
#: (`scoring_stage_approval.approval_record_must_include`: "x64 BIAS 3.0.0
#: commit ..."; "Nirvana 3.18.1 runtime banner ...").
_RUNTIME_IDENTITY_KEYS = frozenset(
    {"worker_designation", "worker_arch", "bias_commit", "nirvana_banner", "resource_manifest_sha256"}
)
_PINNED_WORKER_DESIGNATION = "adr-0008-designated-x64-worker"
_PINNED_WORKER_ARCH = "x86_64"
_PINNED_BIAS_COMMIT = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"
_PINNED_NIRVANA_BANNER = "3.18.1-0-g05f88047"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_MD5_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")

#: The ops-documented root directory of the ADR-0008 designated x64 worker
#: (`docs/ops/devbox-bias-nirvana-handoff.md`,
#: `docs/ops/masked-heldout-bias-rerun-handoff.md` §4,
#: `configs/eval/core_annotation_bundle.yaml`
#: `x64_handoff_requirements.items[*].x64_path`,
#: `scripts/compute_adr0008_resource_manifest_sha256.py`
#: `DEFAULT_CHECKSUMS_DIR`). This is the ONE designated resource location
#: `observe_runtime_identity`'s default probes read from -- never a
#: caller-chosen directory -- so a caller cannot bind a scoring-stage
#: approval to manifests/markers copied to an arbitrary, non-designated
#: path.
DESIGNATED_X64_WORKER_ROOT = r"D:\raptor-x64"
_DEFAULT_RESOURCE_MANIFEST_CHECKSUMS_DIR = str(Path(DESIGNATED_X64_WORKER_ROOT) / "CHECKSUMS")

#: The three narrow, machine-readable marker files this module's default
#: probes read to independently OBSERVE worker designation / BIAS commit /
#: Nirvana runtime banner on the ADR-0008 designated x64 worker. These are a
#: minimal, explicit extension of the already-documented
#: `D:\raptor-x64\VERSIONS.md` free-form convention
#: (`docs/ops/devbox-bias-nirvana-handoff.md`) -- one small, single-purpose,
#: single-value text file per dimension, so each can be independently
#: probed by a plain file read with no markdown parsing. See
#: `docs/ops/adr-0008-resource-manifest-digest.md` "Independent
#: runtime-identity observation" for the full convention and how a human
#: operator populates them.
_WORKER_DESIGNATION_MARKER_FILENAME = "WORKER_DESIGNATION.txt"
_BIAS_COMMIT_MARKER_FILENAME = "BIAS_COMMIT.txt"
_NIRVANA_BANNER_MARKER_FILENAME = "NIRVANA_BANNER.txt"

#: The x64/AMD64 `platform.machine()` spellings this module treats as the
#: pinned x86_64 architecture (mirrors
#: `scripts/compute_adr0008_resource_manifest_sha256.py` `_X64_MACHINE_NAMES`
#: -- kept identical so the CLI utility and this module's own runtime-arch
#: observation can never silently diverge on what counts as "x64").
_X64_MACHINE_NAMES = frozenset({"x86_64", "amd64"})

#: A clearly-non-matching sentinel prefix `_default_*_probe` functions
#: return when their marker file is absent/unreadable/blank -- NEVER the
#: pinned expected value. This guarantees a non-designated host (this WSL2
#: dev/test environment included) can never silently "observe" the correct
#: answer merely because nothing was found; absence must fail the pin
#: comparison, not be treated as "cannot verify, so accept".
_UNOBSERVABLE_SENTINEL_PREFIX = "UNOBSERVABLE:"


def _default_worker_arch_probe() -> str:
    """Returns `platform.machine()` verbatim (never normalized/mapped to the
    pinned literal) -- `assert_runtime_boundary` compares this raw value
    against `_PINNED_WORKER_ARCH` exactly, so a non-x64 host's real,
    unmodified architecture string always fails that comparison closed."""
    return platform.machine()


def _read_marker_file_or_sentinel(path: Path, *, dimension: str) -> str:
    """Reads a single-line marker file and returns its stripped text, or a
    `_UNOBSERVABLE_SENTINEL_PREFIX`-prefixed sentinel (embedding `dimension`
    and `path` for a useful failure message) if the file is missing,
    unreadable, or blank. Never raises, and never falls back to any pinned
    literal -- an absent marker is observed as itself absent, not silently
    treated as a match."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return f"{_UNOBSERVABLE_SENTINEL_PREFIX} {dimension} marker file unreadable at {path}: {exc}"
    if not text:
        return f"{_UNOBSERVABLE_SENTINEL_PREFIX} {dimension} marker file is blank at {path}"
    return text


def _default_worker_designation_probe() -> str:
    return _read_marker_file_or_sentinel(
        Path(DESIGNATED_X64_WORKER_ROOT) / _WORKER_DESIGNATION_MARKER_FILENAME, dimension="worker_designation"
    )


def _default_bias_commit_probe() -> str:
    return _read_marker_file_or_sentinel(
        Path(DESIGNATED_X64_WORKER_ROOT) / _BIAS_COMMIT_MARKER_FILENAME, dimension="bias_commit"
    )


def _default_nirvana_banner_probe() -> str:
    return _read_marker_file_or_sentinel(
        Path(DESIGNATED_X64_WORKER_ROOT) / _NIRVANA_BANNER_MARKER_FILENAME, dimension="nirvana_banner"
    )


def _default_resource_manifest_location_probe() -> str:
    """Returns the ONE designated resource-manifest checksums directory
    (`_DEFAULT_RESOURCE_MANIFEST_CHECKSUMS_DIR`) -- never a caller-supplied
    path. Binding manifests to this fixed, documented location (rather than
    accepting an arbitrary directory argument) is what prevents a caller
    from recomputing `resource_manifest_sha256` from manifests copied to a
    non-designated path and having that count as observation of the real
    worker."""
    return _DEFAULT_RESOURCE_MANIFEST_CHECKSUMS_DIR


def observe_runtime_identity(
    *,
    worker_designation_probe: Callable[[], str] | None = None,
    worker_arch_probe: Callable[[], str] | None = None,
    bias_commit_probe: Callable[[], str] | None = None,
    nirvana_banner_probe: Callable[[], str] | None = None,
) -> dict[str, str]:
    """Independently OBSERVES `worker_designation`/`worker_arch`/
    `bias_commit`/`nirvana_banner` for the CURRENT run by calling each
    probe (defaulting to genuine system inspection: `platform.machine()`
    for `worker_arch`, and a read of one of the three narrow marker files
    under `DESIGNATED_X64_WORKER_ROOT` for the other three dimensions).

    This function -- not a caller-supplied plain mapping -- is what
    `validate_scoring_stage_approval` uses by default to obtain
    `observed_runtime_identity`. Unlike a plain caller-claimed value, a
    caller cannot make this function "observe" the pinned answer merely by
    asserting it: on any host that is not the real ADR-0008 designated x64
    worker, the default probes return the host's REAL `platform.machine()`
    value and/or an `_UNOBSERVABLE_SENTINEL_PREFIX`-prefixed sentinel (the
    marker files are simply absent), and `assert_runtime_boundary` then
    fails closed on that real mismatch. Explicit probe overrides exist only
    so this mechanism itself can be exercised in tests without requiring a
    real ADR-0008 worker filesystem; production/CLI callers must never
    override any of these four probes."""
    designation_probe = worker_designation_probe or _default_worker_designation_probe
    arch_probe = worker_arch_probe or _default_worker_arch_probe
    bias_probe = bias_commit_probe or _default_bias_commit_probe
    nirvana_probe = nirvana_banner_probe or _default_nirvana_banner_probe
    return {
        "worker_designation": designation_probe(),
        "worker_arch": arch_probe(),
        "bias_commit": bias_probe(),
        "nirvana_banner": nirvana_probe(),
    }


def capture_transport_identity_pin(transport: Any) -> dict[str, Any]:
    """Captures an identity "pin" for `transport` -- its concrete class and
    that class's currently-bound `head`/`stream_get` function objects --
    immediately after a transport is constructed (e.g. right after
    `raptor.eval.prospective_exact_source_transport.build_transport()`
    returns), before either lookup port is even called.

    `execute_transport_and_raw_freeze` re-verifies this pin against the
    SAME `transport` object at two later points (immediately on entry, and
    again immediately before the real streamed GET) via
    `_transport_identity_pin_mismatch`. If either check finds the
    transport's class or its `head`/`stream_get` methods no longer match
    this pin -- e.g. something monkeypatched `type(transport).stream_get`
    in between -- execution is refused with `TRANSPORT_IDENTITY_TAMPERED`
    before any network call. Independent review (round 5) additionally
    closed the specific vulnerability this pin was originally layered on
    top of: confirmed live `--execute` no longer imports ANY
    caller-selected Python/plugin code at all before the real GET (the
    `--published-archive-date-lookup`/`--official-md5-lookup`
    `"module:callable"` CLI options were removed; both ports are now
    hard-wired to `raptor.eval.prospective_exact_source_metadata_lookups`,
    a single production-owned, statically-imported module -- see that
    module's docstring). This pin therefore remains purely as
    defense-in-depth against any future regression, not as the primary
    defense against a live import vulnerability."""
    transport_type = type(transport)
    return {
        "transport_type": transport_type,
        "head": transport_type.head,
        "stream_get": transport_type.stream_get,
    }


def _transport_identity_pin_mismatch(transport: Any, pin: Mapping[str, Any]) -> bool:
    transport_type = type(transport)
    return (
        transport_type is not pin.get("transport_type")
        or transport_type.head is not pin.get("head")
        or transport_type.stream_get is not pin.get("stream_get")
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS_RE = re.compile(r"^[0-9]+$")

#: Schema id for the `resource_manifest_sha256` canonical digest envelope
#: (`docs/ops/adr-0008-resource-manifest-digest.md`). Domain-separated and
#: versioned: this literal string is itself bound into the hashed bytes, so
#: a future, deliberate change to the envelope shape is made by bumping this
#: string (a new schema id can never collide with a v1 digest) rather than
#: by silently reinterpreting an existing `resource_manifest_sha256` value.
RESOURCE_MANIFEST_DIGEST_SCHEMA = "raptor.eval.adr0008_resource_manifest_digest.v1"

#: The three pinned checksum-manifest files `resource_manifest_sha256` binds,
#: as `(id, filename)` pairs in this EXACT pinned order. Sourced from
#: `configs/eval/core_annotation_bundle.yaml`
#: `x64_handoff_requirements.items` (`nirvana_full_manifest`,
#: `nirvana_updates_manifest`, `bias_data_manifest`) and
#: `docs/ops/masked-heldout-bias-rerun-handoff.md` §4/§9, which together
#: identify these as the frozen baselines for the ADR-0008 x64 worker's
#: Nirvana GRCh38 data root and BIAS hg38 data root. This tuple's order is
#: itself part of the contract (see `compute_resource_manifest_sha256`).
RESOURCE_MANIFEST_ENTRIES: tuple[tuple[str, str], ...] = (
    ("nirvana_full_manifest", "nirvana-grch38-full.sha256.txt"),
    ("nirvana_updates_manifest", "nirvana-grch38-updates.sha256.txt"),
    ("bias_data_manifest", "bias-hg38-data.sha256.txt"),
)


# ---------------------------------------------------------------------------
# Closed, typed exceptions.
# ---------------------------------------------------------------------------


class ProspectiveContractError(Exception):
    """Base class for every typed ADR-0020 prospective-freeze contract failure."""


class ProspectiveStopStateError(ProspectiveContractError):
    """A closed PRE-DATA stop state (`PRE_DATA_STOP_STATES`). `.code` and
    `.stop_state` are always identical; `.reason` is always a non-blank
    human-readable string (spec `stop_rule`: no in-place waiver)."""

    def __init__(self, stop_state: str, reason: str) -> None:
        if stop_state not in PRE_DATA_STOP_STATES:
            raise ValueError(f"unknown PRE-DATA stop_state: {stop_state!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("ProspectiveStopStateError requires a non-blank reason")
        self.code = stop_state
        self.stop_state = stop_state
        self.reason = reason
        super().__init__(f"{stop_state}: {reason}")


class ProspectiveInvalidStateError(ProspectiveContractError):
    """A0 run-integrity / structural / boundary `INVALID` -- never a
    performance `FAIL` (spec: "an A0 run-integrity failure is INVALID, not
    FAIL"). `.code` is always the literal string `"INVALID"`."""

    code = "INVALID"

    def __init__(self, reason: str, *, reason_code: str | None = None) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("ProspectiveInvalidStateError requires a non-blank reason")
        self.reason = reason
        self.reason_code = reason_code
        super().__init__(f"INVALID: {reason}")


# ---------------------------------------------------------------------------
# Small pure helpers (hashing/canonicalization/YAML/JSON -- production-owned,
# independent of the test helpers module).
# ---------------------------------------------------------------------------


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_lf_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _canonical_lf_sha256_bytes(raw: bytes) -> str:
    return _sha256_hex(_canonical_lf_bytes(raw))


def _canonical_lf_sha256_path(path: Path) -> str:
    return _canonical_lf_sha256_bytes(Path(path).read_bytes())


def _git_blob_sha1(raw: bytes) -> str:
    """Canonical (cross-EOL-correct) git blob SHA-1: canonicalizes `raw` to
    LF line endings BEFORE applying the `git hash-object` blob-header
    formula. A raw-bytes-only formula would diverge from the real
    committed git blob identity the moment a checkout's line endings
    differ from the committed content's own EOL convention (e.g. a CRLF
    Windows checkout of a file whose repository blob is CRLF-normalized
    on `git add`/commit), producing a false PRE_DATA_DRIFT purely from EOL
    style. Canonicalizing first makes the check EOL-style-independent
    while still catching every real (semantic) content drift, since only
    the line-ending bytes are normalized away -- everything else that
    changes still changes the canonical bytes, and therefore this hash."""
    canonical = _canonical_lf_bytes(raw)
    return hashlib.sha1(b"blob " + str(len(canonical)).encode("utf-8") + b"\0" + canonical).hexdigest()


#: This module's own repository root (`src/raptor/eval/prospective_freeze.py`
#: is three directories below it) -- used only as a LAST-RESORT git-metadata
#: discovery fallback when `GIT_DIR`/`GIT_WORK_TREE` are not explicitly set
#: (e.g. a plain, non-worktree checkout of the real repository, unlike this
#: repo's linked-worktree layout whose `.git` FILE cannot otherwise be
#: resolved by a bare `-C <path>` invocation).
_THIS_MODULE_REPO_ROOT = Path(__file__).resolve().parents[3]

_COMMIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_MODULE_HASH_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Every acquisition-critical module must be pinned. Editing one after
#: approval is intentionally a hard stop requiring a fresh approval.
REQUIRED_IMPLEMENTATION_FREEZE_MODULES: tuple[str, ...] = (
    "raptor.eval.prospective_freeze",
    "raptor.eval.prospective_exact_source_transport",
    "raptor.eval.prospective_exact_source_metadata_lookups",
)

#: The operator entry point controls which production callables reach the
#: acquisition API, so its exact committed and on-disk bytes are part of the
#: same implementation freeze.
REQUIRED_IMPLEMENTATION_FREEZE_FILES: tuple[str, ...] = (
    "scripts/run_clinvar_2026_08_prospective_freeze.py",
)


def _git_command_prefix() -> list[str]:
    git_dir = os.environ.get("GIT_DIR")
    git_work_tree = os.environ.get("GIT_WORK_TREE")
    if git_dir and git_work_tree:
        return ["git", "--git-dir", git_dir, "--work-tree", git_work_tree]
    return ["git", "-C", str(_THIS_MODULE_REPO_ROOT)]


def _run_git(*args: str) -> "subprocess.CompletedProcess[bytes] | None":
    """Runs a read-only git subprocess, never raising. Returns `None` only
    when git itself could not even be invoked (a genuinely unusable
    environment) -- never conflated with a real, negative git verdict (a
    resolvable object that is simply absent, or the wrong content)."""
    try:
        return subprocess.run(
            [*_git_command_prefix(), "--no-pager", *args],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None


def _module_relative_path(module_name: str) -> Path:
    return (Path("src") / Path(*module_name.split("."))).with_suffix(".py")


def _freeze_file_relative_path(file_path: str) -> Path | None:
    if not isinstance(file_path, str) or not file_path or "\\" in file_path:
        return None
    pure_path = PurePosixPath(file_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        return None
    if pure_path.as_posix() != file_path:
        return None
    return Path(*pure_path.parts)


def _implementation_freeze_module_hash_failure(commit: str, module_hashes: Mapping[str, Any]) -> str | None:
    """Verifies every `module_hashes` entry against the ACTUAL committed
    blob content at `commit` -- always read via `git show <commit>:<path>`,
    NEVER the ambient worktree's own files, so a checked-out-but-uncommitted
    edit can never masquerade as a frozen, approved implementation. Only
    called once `commit` itself has already been confirmed reachable."""
    for module_name, expected_hash in module_hashes.items():
        module_rel = _module_relative_path(module_name)
        shown = _run_git("show", f"{commit}:{module_rel.as_posix()}")
        if shown is None or shown.returncode != 0:
            return f"implementation_freeze module {module_name!r} is not present in the committed tree at {commit}"
        if _canonical_lf_sha256_bytes(shown.stdout) != expected_hash:
            return f"implementation_freeze module {module_name!r} canonical-LF sha256 does not match commit {commit}"
    return None


def _implementation_freeze_file_hash_failure(commit: str, file_hashes: Mapping[str, Any]) -> str | None:
    for file_path, expected_hash in file_hashes.items():
        file_rel = _freeze_file_relative_path(file_path)
        if file_rel is None:
            return f"implementation_freeze file path {file_path!r} is not a normalized repository-relative path"
        shown = _run_git("show", f"{commit}:{file_rel.as_posix()}")
        if shown is None or shown.returncode != 0:
            return f"implementation_freeze file {file_path!r} is not present in the committed tree at {commit}"
        if _canonical_lf_sha256_bytes(shown.stdout) != expected_hash:
            return f"implementation_freeze file {file_path!r} canonical-LF sha256 does not match commit {commit}"
    return None


def _read_executing_module_bytes(module_name: str) -> bytes:
    """Reads the CURRENTLY LOADED/EXECUTING file bytes for `module_name` in
    THIS process, via `importlib.import_module` + `Path(module.__file__)
    .read_bytes()`. This is a deliberately narrow seam (tests may monkeypatch
    this exact function to simulate "the actually running code differs from
    what is registered", independent of real git/commit state) -- production
    code never overrides it."""
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ImportError(f"module {module_name!r} has no resolvable __file__ in this process")
    return Path(module_file).read_bytes()


def _read_executing_file_bytes(file_path: str) -> bytes:
    file_rel = _freeze_file_relative_path(file_path)
    if file_rel is None:
        raise OSError(f"file path {file_path!r} is not a normalized repository-relative path")
    candidate = _THIS_MODULE_REPO_ROOT / file_rel
    if candidate.is_symlink():
        raise OSError(f"file path {file_path!r} must not be a symlink")
    resolved_root = _THIS_MODULE_REPO_ROOT.resolve()
    resolved_candidate = candidate.resolve(strict=True)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise OSError(f"file path {file_path!r} resolves outside the repository root") from exc
    if not resolved_candidate.is_file():
        raise OSError(f"file path {file_path!r} is not a regular file")
    return resolved_candidate.read_bytes()


def _implementation_freeze_executing_code_failure(module_hashes: Mapping[str, Any]) -> str | None:
    """Verifies every `module_hashes` entry against the bytes ACTUALLY
    loaded/executing in THIS process right now (`_read_executing_module_bytes`),
    independent of the `_implementation_freeze_module_hash_failure` git-commit
    check above. Both checks must pass: `implementation_freeze.commit` names
    a real, reachable commit whose committed content matches the declared
    hash, AND the code genuinely running in this process right now ALSO
    matches that same declared hash. This closes the gap where an approval
    could pin a real, historical commit that used to be correct, while the
    file was edited afterward without a fresh approval -- the previous
    git-only check could never detect that divergence, because it never
    looked at what code is actually executing."""
    for module_name, expected_hash in module_hashes.items():
        try:
            actual_bytes = _read_executing_module_bytes(module_name)
        except (ImportError, OSError) as exc:
            return f"implementation_freeze module {module_name!r} could not be loaded from the running process: {exc}"
        if _canonical_lf_sha256_bytes(actual_bytes) != expected_hash:
            return (
                f"implementation_freeze module {module_name!r} canonical-LF sha256 does not match the code "
                "ACTUALLY executing in this process right now (registered implementation differs from what "
                "is running)"
            )
    return None


def _implementation_freeze_executing_file_failure(file_hashes: Mapping[str, Any]) -> str | None:
    for file_path, expected_hash in file_hashes.items():
        try:
            actual_bytes = _read_executing_file_bytes(file_path)
        except OSError as exc:
            return f"implementation_freeze file {file_path!r} could not be read from the running checkout: {exc}"
        if _canonical_lf_sha256_bytes(actual_bytes) != expected_hash:
            return (
                f"implementation_freeze file {file_path!r} canonical-LF sha256 does not match the file "
                "ACTUALLY used by the running checkout right now"
            )
    return None


def _implementation_freeze_failure_reason(implementation_freeze: Mapping[str, Any]) -> str | None:
    """Returns a human-readable `PRE_DATA_IMPLEMENTATION_NOT_READY` reason,
    or `None` if `implementation_freeze` is acceptable.

    `commit == "NOT_YET_COMMITTED"` is always rejected here -- an
    `APPROVED_PRE_DATA` decision can never be backed by a not-yet-committed
    implementation. A `commit` that fails the closed 40-hex-lowercase
    format, or whose `module_hashes` fail the closed 64-hex-lowercase
    format, is likewise rejected outright (neither is one of the two
    schema-level allowed shapes: `NOT_YET_COMMITTED`, or a real commit
    id). Verification is fail-closed throughout: a commit this git
    metadata cannot resolve, and a git invocation that could not even be
    made (git itself unavailable/unusable), are both rejected exactly
    like a resolvable commit whose committed tree is missing or
    mismatched -- there is no "cannot verify, so accept" branch anywhere
    in this path, and no ambient-worktree fallback either (content is
    always read via `git show <commit>:<path>`, never the live checkout's
    own files). `module_hashes` must additionally include an entry for
    EVERY module named in `REQUIRED_IMPLEMENTATION_FREEZE_MODULES` (round
    6) -- omitting the metadata-lookups module (or any other required
    module) is rejected exactly like a malformed hash, never silently
    accepted as a partial freeze."""
    commit = implementation_freeze.get("commit")
    module_hashes = implementation_freeze.get("module_hashes")
    file_hashes = implementation_freeze.get("file_hashes")
    if commit == "NOT_YET_COMMITTED":
        return (
            "implementation_freeze.commit is NOT_YET_COMMITTED; APPROVED_PRE_DATA requires a "
            "committed, verifiable implementation"
        )
    if not isinstance(commit, str) or not _COMMIT_SHA1_RE.match(commit):
        return "implementation_freeze.commit must be NOT_YET_COMMITTED or a 40-hex lowercase commit id"
    if not isinstance(module_hashes, Mapping) or not module_hashes:
        return "implementation_freeze.module_hashes must be a non-empty mapping"
    if not isinstance(file_hashes, Mapping) or not file_hashes:
        return "implementation_freeze.file_hashes must be a non-empty mapping"
    for module_name, expected_hash in module_hashes.items():
        if not isinstance(module_name, str) or not module_name.strip():
            return "implementation_freeze.module_hashes has a blank module name"
        if not isinstance(expected_hash, str) or not _MODULE_HASH_SHA256_RE.match(expected_hash):
            return f"implementation_freeze.module_hashes[{module_name!r}] must be a 64-hex lowercase sha256 string"
    missing_required = [name for name in REQUIRED_IMPLEMENTATION_FREEZE_MODULES if name not in module_hashes]
    if missing_required:
        return (
            "implementation_freeze.module_hashes is missing required module(s) "
            f"{missing_required!r}; every module in REQUIRED_IMPLEMENTATION_FREEZE_MODULES must be "
            "pinned -- this is never an optional freeze-record omission"
        )
    for file_path, expected_hash in file_hashes.items():
        if _freeze_file_relative_path(file_path) is None:
            return (
                f"implementation_freeze.file_hashes key {file_path!r} must be a normalized "
                "repository-relative POSIX path"
            )
        if not isinstance(expected_hash, str) or not _MODULE_HASH_SHA256_RE.match(expected_hash):
            return f"implementation_freeze.file_hashes[{file_path!r}] must be a 64-hex lowercase sha256 string"
    missing_required_files = [name for name in REQUIRED_IMPLEMENTATION_FREEZE_FILES if name not in file_hashes]
    if missing_required_files:
        return (
            "implementation_freeze.file_hashes is missing required file(s) "
            f"{missing_required_files!r}; every file in REQUIRED_IMPLEMENTATION_FREEZE_FILES must be pinned"
        )

    commit_probe = _run_git("cat-file", "-e", f"{commit}^{{commit}}")
    if commit_probe is None:
        return (
            f"implementation_freeze.commit {commit!r} could not be verified: git is unavailable or "
            "the configured git metadata is unusable"
        )
    if commit_probe.returncode != 0:
        return f"implementation_freeze.commit {commit!r} is not a reachable commit in the configured git metadata"
    git_failure = _implementation_freeze_module_hash_failure(commit, module_hashes)
    if git_failure is not None:
        return git_failure
    git_file_failure = _implementation_freeze_file_hash_failure(commit, file_hashes)
    if git_file_failure is not None:
        return git_file_failure
    # Binds approval to the code ACTUALLY executing right now, not merely to
    # a historical commit reference: a technically-valid, reachable commit
    # whose committed tree matches is not sufficient on its own if the file
    # has since been edited in the running checkout without a fresh
    # approval (independent review finding).
    executing_module_failure = _implementation_freeze_executing_code_failure(module_hashes)
    if executing_module_failure is not None:
        return executing_module_failure
    return _implementation_freeze_executing_file_failure(file_hashes)


def _content_hash(payload: Mapping[str, Any], *, key: str = "content_hash") -> str:
    basis = {k: v for k, v in payload.items() if k != key}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_hex(canonical)


def _projection_sha256_excluding_labels_snapshot(eval_config: Mapping[str, Any]) -> str:
    basis = {k: v for k, v in eval_config.items() if k != "labels_snapshot"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_hex(canonical)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise ProspectiveInvalidStateError(f"unable to read/parse YAML at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ProspectiveInvalidStateError(f"expected a YAML mapping at {path}")
    return loaded


def _parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_http_date_to_utc_iso(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("blank HTTP-date header value")
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _header_values(raw_headers: Any, name: str) -> list[Any]:
    name_lower = name.lower()
    values: list[Any] = []
    if not isinstance(raw_headers, list):
        return values
    for entry in raw_headers:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
            continue
        key, value = entry
        if isinstance(key, str) and key.lower() == name_lower:
            values.append(value)
    return values


# ---------------------------------------------------------------------------
# No-follow destination-boundary safety (path traversal / symlink / special
# file / TOCTOU-adjacent boundary check for every freeze-record write).
# ---------------------------------------------------------------------------


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _validate_destination_boundary(path: Path, *, allowed_root: Path) -> str | None:
    """Returns `None` if `path` is safely addressable inside `allowed_root`
    (no traversal, no symlink anywhere along the relative chain, no special
    leaf file); otherwise returns a reason code. Never follows a symlink to
    decide safety (`os.lstat`, not `os.stat`). A literal `..` component in
    the RAW (pre-normalization) path is rejected outright, before any
    `os.path.normpath` collapsing: lexical normalization cannot know that an
    earlier component is a symlink, so `allowed/evil-link/../pwned.json`
    (where `evil-link` is a symlink to somewhere outside `allowed_root`)
    would lexically collapse to the harmless-looking `allowed/pwned.json`
    while the real, symlink-respecting filesystem resolution of that same
    path escapes the root entirely. Refusing every raw `..` unconditionally
    closes both the plain `repo_root/../escaped.json` traversal and this
    symlink+dotdot combination in one rule."""
    raw_path = Path(path)
    if ".." in raw_path.parts:
        return "DESTINATION_OUTSIDE_ALLOWED_ROOT"
    path = Path(os.path.normpath(str(raw_path)))
    allowed_root = Path(os.path.normpath(str(Path(allowed_root))))
    try:
        relative = path.relative_to(allowed_root)
    except ValueError:
        return "DESTINATION_OUTSIDE_ALLOWED_ROOT"
    if not relative.parts or ".." in relative.parts:
        return "DESTINATION_OUTSIDE_ALLOWED_ROOT"
    current = allowed_root
    last_index = len(relative.parts) - 1
    for index, part in enumerate(relative.parts):
        current = current / part
        st = _lstat_or_none(current)
        if st is None:
            continue
        if stat.S_ISLNK(st.st_mode):
            return "DESTINATION_PATH_SYMLINK"
        if index == last_index:
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                return "DESTINATION_PATH_SPECIAL_FILE"
        elif not stat.S_ISDIR(st.st_mode):
            return "DESTINATION_PATH_ANCESTOR_NOT_DIRECTORY"
    return None


def _validate_leaf_filename(name: Any) -> str | None:
    """Returns a reason code if `name` (the dataset registration's
    `filename` field) is not a safe single-path-segment leaf name; `None`
    if it is safe to join under a fresh `run_scope_id` directory."""
    if not isinstance(name, str) or not name.strip():
        return "DATASET_FILENAME_INVALID"
    if name in (".", ".."):
        return "DATASET_FILENAME_TRAVERSAL"
    if "/" in name or "\\" in name or "\x00" in name:
        return "DATASET_FILENAME_TRAVERSAL"
    return None


# ---------------------------------------------------------------------------
# Atomic JSON write (temp-write + fsync + os.replace; crash leaves no
# partial artifact). Referenced by bare name everywhere below so a test
# monkeypatch of the module attribute is observed.
# ---------------------------------------------------------------------------


def _atomic_write_json(path: "str | Path", payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    tmp_path = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _content_hash_valid(payload: Mapping[str, Any]) -> bool:
    stored = payload.get("content_hash")
    return isinstance(stored, str) and stored == _content_hash(payload)


def _check_existing_freeze(
    *, transport_freeze_record_path: Path, raw_freeze_record_path: Path, current_registration_id: str
) -> dict[str, Any] | None:
    """Restart-idempotence + hash-chain distinction (spec: "Freeze-record
    data mismatch is BLOCKED_DATA; freeze-record schema/hash-chain
    corruption is INVALID."). Beyond each record's own self-hash, this also
    verifies the transport->raw hash-chain link and that both records'
    `registration_id`/`run_scope_id` identity fields agree with each other
    and with the currently-registered `registration_id` -- any chain or
    identity corruption is INVALID, never a silent reuse. Returns `None`
    when nothing usable exists yet (proceed fresh)."""
    if not Path(transport_freeze_record_path).exists() or not Path(raw_freeze_record_path).exists():
        return None
    transport_record = _load_json_or_none(transport_freeze_record_path)
    if transport_record is None or not _content_hash_valid(transport_record):
        return {"kind": "CORRUPT", "reason_code": "TRANSPORT_RECORD_CORRUPT"}
    raw_record = _load_json_or_none(raw_freeze_record_path)
    if raw_record is None or not _content_hash_valid(raw_record):
        return {"kind": "CORRUPT", "reason_code": "RAW_RECORD_CORRUPT"}
    if raw_record.get("transport_record_content_hash") != transport_record.get("content_hash"):
        return {"kind": "CORRUPT", "reason_code": "TRANSPORT_RAW_LINK_MISMATCH"}
    if raw_record.get("registration_id") != transport_record.get("registration_id"):
        return {"kind": "CORRUPT", "reason_code": "REGISTRATION_ID_CHAIN_MISMATCH"}
    if raw_record.get("run_scope_id") != transport_record.get("run_scope_id"):
        return {"kind": "CORRUPT", "reason_code": "RUN_SCOPE_ID_CHAIN_MISMATCH"}
    if transport_record.get("registration_id") != current_registration_id:
        return {"kind": "CORRUPT", "reason_code": "REGISTRATION_ID_DRIFT"}
    if raw_record.get("computed_md5") != raw_record.get("official_md5"):
        return {"kind": "DATA_MISMATCH", "reason_code": "OFFICIAL_MD5_MISMATCH"}
    return {"kind": "REUSE", "transport_record": transport_record, "raw_record": raw_record}


# ---------------------------------------------------------------------------
# In-process single-writer serialization. Keyed by the run-scope identity
# (`registration_id` + `exact_url`), never by the caller-chosen destination
# record paths -- two concurrent callers writing to DIFFERENT record paths
# for the SAME underlying registration/archive are still the same logical
# run scope and must still serialize to a single real GET (a path-keyed
# lock would be a loophole: different destinations, same archive, two GETs).
# No OS lock FILE is ever left behind -- only in-memory locks.
# ---------------------------------------------------------------------------

_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: dict[str, threading.Lock] = {}


def _run_scope_lock_key(*, registration_id: str, exact_url: str) -> str:
    return f"{registration_id}::{exact_url}"


def _lock_for(key: str) -> threading.Lock:
    with _LOCK_REGISTRY_GUARD:
        lock = _LOCK_REGISTRY.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCK_REGISTRY[key] = lock
        return lock


# ---------------------------------------------------------------------------
# ADR-0008 runtime-boundary identity check.
# ---------------------------------------------------------------------------


def assert_runtime_boundary(*, runtime_identity: Mapping[str, Any]) -> None:
    """Verify `runtime_identity` against the ADR-0008 pinned x64 worker/BIAS/
    Nirvana identity dimensions. Raises `ProspectiveInvalidStateError`
    (`.code == "INVALID"`) on any missing/extra key or any dimension
    mismatch; returns `None` on success.

    This is the ADR-0020 stage 4 (`4_MASK_AND_LABEL_FREE_SCORE`) gate --
    the mandatory pre-condition for any BIAS/Nirvana execution or
    label-dependent evaluation. It is called by `validate_scoring_stage_approval`
    (below) and is deliberately NEVER called by `validate_pre_data_approval`
    or `execute_transport_and_raw_freeze` (ADR-0020 stages 1-2, ClinVar
    archive acquisition): archive acquisition has no x86-only requirement
    and never needs, reads, or checks x64/BIAS/Nirvana identity. Keeping
    this a standalone function (rather than inlining it into either gate)
    is what lets the two governance boundaries stay independently callable,
    independently testable, and impossible to accidentally conflate.

    `resource_manifest_sha256` is checked here only for FORMAT (64-character
    lowercase hex) -- unlike `bias_commit`/`nirvana_banner`, its concrete
    pinned VALUE is not known in this repository, because it can only be
    produced by actually reading the three resource-bundle checksum-manifest
    files that live solely on the ADR-0008 x64 worker (never checked into,
    or copied into, this repository). `compute_resource_manifest_sha256`
    (below) defines EXACTLY how that value must be computed, and
    `docs/ops/adr-0008-resource-manifest-digest.md` is the human-readable
    spec; a human approver runs it on the real worker and pins the result
    into a `scoring_stage_approval` record's `x64_freeze` block -- this
    function never invents or accepts a value it cannot independently
    verify."""
    if not isinstance(runtime_identity, Mapping) or set(runtime_identity.keys()) != _RUNTIME_IDENTITY_KEYS:
        raise ProspectiveInvalidStateError(
            f"runtime_identity must define exactly {sorted(_RUNTIME_IDENTITY_KEYS)!r}"
        )
    if runtime_identity.get("worker_designation") != _PINNED_WORKER_DESIGNATION:
        raise ProspectiveInvalidStateError(
            "runtime_identity.worker_designation does not match the ADR-0008 designated x64 worker"
        )
    if runtime_identity.get("worker_arch") != _PINNED_WORKER_ARCH:
        raise ProspectiveInvalidStateError("runtime_identity.worker_arch does not match the pinned x64 architecture")
    if runtime_identity.get("bias_commit") != _PINNED_BIAS_COMMIT:
        raise ProspectiveInvalidStateError("runtime_identity.bias_commit does not match the pinned BIAS 3.0.0 commit")
    if runtime_identity.get("nirvana_banner") != _PINNED_NIRVANA_BANNER:
        raise ProspectiveInvalidStateError(
            "runtime_identity.nirvana_banner does not match the pinned Nirvana runtime banner"
        )
    resource_hash = runtime_identity.get("resource_manifest_sha256")
    if not isinstance(resource_hash, str) or not _HEX64_RE.fullmatch(resource_hash):
        raise ProspectiveInvalidStateError(
            "runtime_identity.resource_manifest_sha256 must be a 64-character lowercase hex SHA-256"
        )


def resource_manifest_entries(checksums_dir: Path | str) -> list[dict[str, str]]:
    """Reads the three `RESOURCE_MANIFEST_ENTRIES` files under
    `checksums_dir`, in their pinned order, and returns one
    `{"id", "filename", "sha256"}` dict per entry. `sha256` is the RAW-BYTE
    SHA-256 of that exact file: `Path.read_bytes()` is a binary read that
    never applies any text-mode newline translation, so this value is
    identical on Windows and Linux for byte-identical files -- the digest
    contract never depends on which OS recomputed it, only on the bytes
    themselves. READ-ONLY: opens nothing but these three small
    checksum-manifest text files -- never the multi-GB Nirvana/BIAS
    annotation-data bundles the manifests describe, and never anything
    outside `checksums_dir`.

    Fails closed with a plain `FileNotFoundError` the instant any one of the
    three pinned filenames is absent from `checksums_dir` -- a rename of a
    pinned file is indistinguishable from, and rejected exactly like, a
    missing file (there is no fuzzy/best-effort filename match)."""
    base = Path(checksums_dir)
    entries: list[dict[str, str]] = []
    for entry_id, filename in RESOURCE_MANIFEST_ENTRIES:
        path = base / filename
        if not path.is_file():
            raise FileNotFoundError(f"resource manifest file missing for {entry_id!r}: expected {path}")
        entries.append({"id": entry_id, "filename": filename, "sha256": _sha256_hex(path.read_bytes())})
    return entries


def compute_resource_manifest_sha256(checksums_dir: Path | str) -> str:
    """Computes the ADR-0008 `x64_freeze.resource_manifest_sha256` digest
    (full spec: `docs/ops/adr-0008-resource-manifest-digest.md`) from the
    three pinned checksum-manifest files under `checksums_dir`.

    Builds the canonical envelope
    `{"schema": RESOURCE_MANIFEST_DIGEST_SCHEMA, "manifests":
    resource_manifest_entries(checksums_dir)}`, serializes it with this
    module's standard canonical-JSON convention (`sort_keys=True,
    separators=(",", ":")`, `ensure_ascii=False`, UTF-8 -- see
    `_content_hash`), and returns the SHA-256 hex digest of those exact
    canonical bytes.

    This single value binds, together, the three manifests':
    - IDENTITY -- each entry's fixed `id` (`RESOURCE_MANIFEST_ENTRIES`);
    - ORDER -- `manifests` is a JSON array, and `json.dumps` never reorders
      array elements even under `sort_keys=True` (that flag only sorts each
      object's own keys), so the pinned tuple order is preserved verbatim
      into the hashed bytes;
    - CONTENT -- each entry's raw-byte SHA-256 (`resource_manifest_entries`).

    A rename, a reorder (impossible here without also renaming, since the
    id -> filename mapping is fixed), a swap of which manifest's bytes sit
    behind which identity, or any single changed byte in any one manifest
    all change this digest. This function only READS the three manifest
    text files; it never touches the (multi-GB) Nirvana/BIAS data bundles
    those manifests describe, never contacts a network, and never runs BIAS
    or Nirvana -- preserving this module's fail-closed, no-live-I/O posture
    (see the module docstring)."""
    envelope = {
        "schema": RESOURCE_MANIFEST_DIGEST_SCHEMA,
        "manifests": resource_manifest_entries(checksums_dir),
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_hex(canonical)


# ---------------------------------------------------------------------------
# ADR-0020 stage 4 scoring-stage gate: SEPARATE from, and later than,
# pre_data_approval / execute_transport_and_raw_freeze (stages 1-2). This is
# the sole place x64/BIAS/Nirvana identity is required or checked.
# ---------------------------------------------------------------------------

#: Schema id for the `scoring_stage_approval` record (see
#: `docs/ops/adr-0008-resource-manifest-digest.md` and
#: `docs/project/specs/clinvar-2026-08-prospective-amendment-v2.yaml`
#: `scoring_stage_approval`). Deliberately a DIFFERENT schema id from
#: `raptor.eval.pre_data_approval.v1` -- these are two independent
#: approvals gating two independent, non-overlapping stages, and a record
#: of one schema can never be mistaken for, or silently accepted as, the
#: other.
_SCORING_STAGE_APPROVAL_SCHEMA_ID = "raptor.eval.scoring_stage_approval.v1"
_SCORING_STAGE_APPROVAL_TOP_KEYS = frozenset(
    {"schema", "registration_id", "decision", "approver", "approved_at", "x64_freeze", "immutable_inputs_verified"}
)

#: The runtime-identity dimensions `observe_runtime_identity` returns
#: (worker designation/arch, and the BIAS/Nirvana identity that process
#: itself reports). Deliberately EXCLUDES `resource_manifest_sha256`: that
#: dimension is never accepted as a claim at all -- it is always
#: independently recomputed by this function from the designated resource
#: location via `compute_resource_manifest_sha256`, never trusted from any
#: input.
_OBSERVED_RUNTIME_IDENTITY_KEYS = frozenset({"worker_designation", "worker_arch", "bias_commit", "nirvana_banner"})


def _immutable_inputs_failure_reason(*, spec: Mapping[str, Any], allowed_repo_root: "str | Path") -> str | None:
    """Independently RECOMPUTES every `immutable_inputs` entry's
    canonical-LF SHA-256 and git-blob SHA-1 from the actual current file
    bytes under `allowed_repo_root`, and compares each against the
    registration spec's own pinned values. Returns the first mismatch
    reason, or `None` when every entry matches.

    These are SCORING-stage inputs (evaluation criteria/thresholds/points,
    ACMG criterion/strength policy, BIAS strength ladder/lineage,
    masking/predictor-aggregation policy, ...) -- this check belongs solely
    to `validate_scoring_stage_approval`, never to the acquisition-stage
    `pre_data_approval` gate, because ClinVar archive acquisition never
    reads or depends on any of them. A merely claimed
    `immutable_inputs_verified: true` schema flag is never trusted on its
    own; this recomputation is what that claim must actually match."""
    immutable_inputs = spec.get("immutable_inputs")
    if not isinstance(immutable_inputs, Mapping) or not immutable_inputs:
        return "registration spec immutable_inputs must be a non-empty mapping"
    root = Path(allowed_repo_root)
    for rel_path, expected in immutable_inputs.items():
        if not isinstance(expected, Mapping):
            return f"registration spec immutable_inputs[{rel_path!r}] must be a mapping"
        expected_lf_sha256 = expected.get("canonical_lf_sha256")
        expected_blob_sha1 = expected.get("git_blob_sha1")
        candidate = root / str(rel_path)
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            return f"immutable_inputs[{rel_path!r}] file is missing or unreadable at {candidate}: {exc}"
        if _canonical_lf_sha256_bytes(raw) != expected_lf_sha256:
            return f"immutable_inputs[{rel_path!r}] canonical_lf_sha256 does not match the current file bytes"
        if _git_blob_sha1(raw) != expected_blob_sha1:
            return f"immutable_inputs[{rel_path!r}] git_blob_sha1 does not match the current file bytes"
    return None


def validate_scoring_stage_approval(
    *,
    registration_id: str,
    registration_spec_path: "str | Path",
    approval_record: Mapping[str, Any],
    allowed_repo_root: "str | Path",
    first_scoring_execution_at: str,
    worker_designation_probe: Callable[[], str] | None = None,
    worker_arch_probe: Callable[[], str] | None = None,
    bias_commit_probe: Callable[[], str] | None = None,
    nirvana_banner_probe: Callable[[], str] | None = None,
    resource_manifest_location_probe: Callable[[], "str | Path"] | None = None,
) -> dict[str, Any]:
    """Validate `approval_record` against the closed
    `raptor.eval.scoring_stage_approval.v1` schema for `registration_id`,
    AND cross-check its claimed `x64_freeze` pins against an INDEPENDENTLY
    OBSERVED runtime identity for the CURRENT run. This is the MANDATORY
    gate before any BIAS/Nirvana execution or label-dependent evaluation
    (ADR-0020 stage 4 `4_MASK_AND_LABEL_FREE_SCORE`) -- it is a separate,
    later gate from `validate_pre_data_approval` /
    `execute_transport_and_raw_freeze` (stages 1-2, ClinVar archive
    acquisition), which never require or check x64/BIAS/Nirvana identity.

    Deliberately never trusts the approval record's `x64_freeze` block, nor
    any caller-supplied "observed identity" value, on its own -- a claimed
    value, however well-formed (including an all-zero or otherwise
    fabricated `resource_manifest_sha256`, or a static pinned literal
    supplied by a caller on a non-designated host), is only EVIDENCE to be
    checked, never a source of truth:

    * `worker_designation`/`worker_arch`/`bias_commit`/`nirvana_banner` are
      always independently OBSERVED by `observe_runtime_identity` -- via
      `platform.machine()` and a read of the three narrow marker files
      under `DESIGNATED_X64_WORKER_ROOT` by default -- never accepted as a
      plain input mapping. The `*_probe` parameters exist ONLY so this
      mechanism can be exercised in tests without a real ADR-0008 worker
      filesystem; production/CLI callers must never override them.
    * `resource_manifest_sha256` is never accepted as a claim at all: it is
      always recomputed here, from scratch, against the three pinned
      checksum-manifest files' actual current bytes at the ONE designated
      resource location (`resource_manifest_location_probe`, defaulting to
      `DESIGNATED_X64_WORKER_ROOT`/CHECKSUMS -- never a caller-chosen
      directory).
    * `immutable_inputs_verified` is likewise never accepted as a bare
      claim: `_immutable_inputs_failure_reason` independently recomputes
      every scoring-stage config input's hash against `allowed_repo_root`'s
      actual current bytes.
    * The combined observed+recomputed identity is checked against the
      ADR-0008 pinned constants via `assert_runtime_boundary`, and then the
      approval record's claimed `x64_freeze` must equal that observed
      identity EXACTLY -- a mismatch in any single dimension fails closed.
    * `first_scoring_execution_at` is a MANDATORY, immutable timestamp (not
      optional): absent/blank, malformed, future-dated, or at/after
      `approved_at` all fail closed -- a post-scoring or future-dated
      approval can never pass.

    Any schema breach, wrong/missing `decision` (a `REJECTED_SCORING_STAGE`
    decision is rejected explicitly and distinctly), wrong approver, blank
    or mistimed `approved_at`/`first_scoring_execution_at`, or any identity
    mismatch raises `ProspectiveInvalidStateError` (`.code == "INVALID"`) --
    matching the registration spec's stage 4 rule that manifest/tool/
    resource identity drift is an A0 run-integrity failure, never a
    `PRE_DATA_*` stop state and never reported as a performance FAIL.
    Returns a shallow copy of `approval_record` on success."""
    if not isinstance(approval_record, Mapping) or set(approval_record.keys()) != _SCORING_STAGE_APPROVAL_TOP_KEYS:
        raise ProspectiveInvalidStateError(
            f"scoring_stage_approval record top-level keys must be exactly {sorted(_SCORING_STAGE_APPROVAL_TOP_KEYS)!r}"
        )
    if approval_record.get("schema") != _SCORING_STAGE_APPROVAL_SCHEMA_ID:
        raise ProspectiveInvalidStateError(
            f"scoring_stage_approval schema must be {_SCORING_STAGE_APPROVAL_SCHEMA_ID!r}, "
            f"got {approval_record.get('schema')!r}"
        )
    if approval_record.get("registration_id") != registration_id:
        raise ProspectiveInvalidStateError(
            "scoring_stage_approval registration_id does not match the registration this scoring run is for"
        )

    spec = _load_yaml(Path(registration_spec_path))
    stage_spec = spec["scoring_stage_approval"]
    allowed_decisions = set(stage_spec["allowed_decisions"])
    approver_required = stage_spec["approver_required"]

    decision = approval_record.get("decision")
    if decision == "REJECTED_SCORING_STAGE":
        raise ProspectiveInvalidStateError("scoring_stage_approval owner recorded REJECTED_SCORING_STAGE")
    if decision != "APPROVED_SCORING_STAGE" or decision not in allowed_decisions:
        raise ProspectiveInvalidStateError(
            f"scoring_stage_approval decision must be APPROVED_SCORING_STAGE, got {decision!r}"
        )

    approver = approval_record.get("approver")
    if not isinstance(approver, str) or not approver.strip():
        raise ProspectiveInvalidStateError("scoring_stage_approval approver must be a non-blank string")
    if approver != approver_required:
        raise ProspectiveInvalidStateError(f"scoring_stage_approval approver must be exactly {approver_required!r}")

    approved_at = approval_record.get("approved_at")
    if not isinstance(approved_at, str) or not approved_at.strip():
        raise ProspectiveInvalidStateError("scoring_stage_approval approved_at must be a non-blank timestamp")
    try:
        approved_at_dt = _parse_iso_utc(approved_at)
    except ValueError as exc:
        raise ProspectiveInvalidStateError(
            f"scoring_stage_approval approved_at is not a valid timestamp: {approved_at!r}"
        ) from exc

    # Mandatory, immutable first-scoring-execution timestamp (independent
    # review finding): absent/blank, malformed, future-dated, or at/after
    # `approved_at` all fail closed. There is no optional/None branch here
    # -- a caller cannot omit this timestamp to skip the timing check.
    if not isinstance(first_scoring_execution_at, str) or not first_scoring_execution_at.strip():
        raise ProspectiveInvalidStateError(
            "first_scoring_execution_at is mandatory and must be a non-blank immutable timestamp"
        )
    try:
        first_execution_dt = _parse_iso_utc(first_scoring_execution_at)
    except ValueError as exc:
        raise ProspectiveInvalidStateError(
            f"first_scoring_execution_at is not a valid timestamp: {first_scoring_execution_at!r}"
        ) from exc
    if first_execution_dt > datetime.now(timezone.utc):
        raise ProspectiveInvalidStateError(
            "first_scoring_execution_at must not be in the future"
        )
    if approved_at_dt >= first_execution_dt:
        raise ProspectiveInvalidStateError(
            "scoring_stage_approval approved_at must be strictly before first_scoring_execution_at"
        )

    x64_freeze = approval_record.get("x64_freeze")
    if not isinstance(x64_freeze, Mapping) or set(x64_freeze.keys()) != _RUNTIME_IDENTITY_KEYS:
        raise ProspectiveInvalidStateError("scoring_stage_approval x64_freeze block schema invalid")

    if approval_record.get("immutable_inputs_verified") is not True:
        raise ProspectiveInvalidStateError(
            "scoring_stage_approval immutable_inputs_verified must be True"
        )
    immutable_inputs_failure = _immutable_inputs_failure_reason(spec=spec, allowed_repo_root=allowed_repo_root)
    if immutable_inputs_failure is not None:
        raise ProspectiveInvalidStateError(
            f"scoring_stage_approval immutable_inputs_verified claim does not match recomputation: "
            f"{immutable_inputs_failure}"
        )

    # `observed_runtime_identity` is NEVER accepted as a caller-supplied
    # plain mapping -- it is always produced by `observe_runtime_identity`,
    # whose default probes genuinely inspect this process/host. A caller
    # cannot make this "observe" the pinned answer merely by asserting it.
    observed_runtime_identity = observe_runtime_identity(
        worker_designation_probe=worker_designation_probe,
        worker_arch_probe=worker_arch_probe,
        bias_commit_probe=bias_commit_probe,
        nirvana_banner_probe=nirvana_banner_probe,
    )
    if set(observed_runtime_identity.keys()) != _OBSERVED_RUNTIME_IDENTITY_KEYS:
        raise ProspectiveInvalidStateError(
            f"observed_runtime_identity must define exactly {sorted(_OBSERVED_RUNTIME_IDENTITY_KEYS)!r}"
        )

    resource_manifest_checksums_dir = (resource_manifest_location_probe or _default_resource_manifest_location_probe)()
    try:
        observed_resource_manifest_sha256 = compute_resource_manifest_sha256(resource_manifest_checksums_dir)
    except OSError as exc:
        raise ProspectiveInvalidStateError(
            f"could not recompute resource_manifest_sha256 from {resource_manifest_checksums_dir!r}: {exc}"
        ) from exc

    full_observed_identity = dict(observed_runtime_identity)
    full_observed_identity["resource_manifest_sha256"] = observed_resource_manifest_sha256

    # `assert_runtime_boundary` checks this INDEPENDENTLY OBSERVED/RECOMPUTED
    # identity -- never the approval record's claimed `x64_freeze` -- against
    # the pinned worker/BIAS/Nirvana constants and the resource digest's hex
    # format.
    assert_runtime_boundary(runtime_identity=full_observed_identity)

    # The anti-fabrication binding: the approval record's CLAIMED x64_freeze
    # pins must equal THIS run's independently observed/recomputed identity,
    # byte-for-byte. A merely well-formed but fabricated claimed digest (an
    # all-zero digest, or any other 64-hex value not actually produced by
    # recomputation), OR a static pinned literal supplied on a
    # non-designated runtime (whose OWN observation will genuinely differ),
    # is rejected here, because it can never equal the real recomputed
    # value.
    if dict(x64_freeze) != full_observed_identity:
        raise ProspectiveInvalidStateError(
            "scoring_stage_approval x64_freeze does not match the independently observed/recomputed runtime identity"
        )

    return dict(approval_record)


# ---------------------------------------------------------------------------
# Prospective eval-overlay merge (dataset-identity partition only).
# ---------------------------------------------------------------------------


def _overlay_required_values_reason(*, spec: Mapping[str, Any], overlay: Mapping[str, Any]) -> str | None:
    """Every `prospective_eval_overlay_lifecycle.required_values` field
    (schema, registration_id, base_config_path, both pinned hashes,
    effective_labels_snapshot, exact_archive_url, and the transport/raw
    freeze-record paths) must match the spec's pinned value EXACTLY. This
    is the single generic check shared by `merge_prospective_overlay` and
    the executor's pre-network coherence gate -- it rejects, among other
    drifts, a historical/July `effective_labels_snapshot` value and a
    rogue `transport_freeze_record`/`raw_freeze_record` path substitution.
    Returns a reason code on the first mismatch, `None` when every
    required value matches."""
    required_values = spec["prospective_eval_overlay_lifecycle"]["required_values"]
    for key, expected in required_values.items():
        if overlay.get(key) != expected:
            return "OVERLAY_REQUIRED_VALUE_DRIFT"
    return None


def _overlay_coherence_reason(*, spec: Mapping[str, Any], overlay: Mapping[str, Any]) -> str | None:
    """Cheap, side-effect-free pre-check of the overlay/spec coherence
    invariants `execute_transport_and_raw_freeze` must reject BEFORE any
    network call (every registered required-value pin, plus 3-way exact-URL
    equality across overlay/dataset_registration/stage_1). Returns a reason
    code on drift, `None` when coherent.

    Deliberately checks ONLY dataset/URL identity -- never scoring-semantics
    or base-eval-config hashes. Acquisition (ADR-0020 stages 1-2) never
    reads or depends on scoring semantics; that verification belongs solely
    to `merge_prospective_overlay`, invoked only when the effective eval
    config is actually built for ADR-0020 stage 3+ scoring, never as a
    precondition for archive acquisition."""
    required_values_reason = _overlay_required_values_reason(spec=spec, overlay=overlay)
    if required_values_reason is not None:
        return required_values_reason
    if overlay.get("registration_id") != spec["registration"]["id"]:
        return "OVERLAY_REGISTRATION_ID_DRIFT"
    dataset_registration = spec["dataset_registration"]
    stage1 = dataset_registration["stage_1_head_comparison"]
    overlay_url = overlay.get("exact_archive_url")
    dataset_url = dataset_registration.get("exact_url")
    request_url = stage1.get("request_url_must_equal")
    if overlay_url != dataset_url or dataset_url != request_url:
        return "EXACT_URL_COHERENCE_DRIFT"
    return None


def merge_prospective_overlay(
    *,
    registration_spec_path: "str | Path",
    prospective_overlay_path: "str | Path",
    base_eval_config_path: "str | Path",
) -> dict[str, Any]:
    """Load the exact base eval config, verify its whole-file hash and
    scoring-semantics projection against the overlay's pins, then return
    the effective config with ONLY `labels_snapshot` replaced (spec
    `prospective_eval_overlay_lifecycle.merge_rule`). Raises
    `ProspectiveInvalidStateError` on any pin mismatch or malformed input --
    no other base key is ever added, removed, or changed."""
    spec_path = Path(registration_spec_path)
    overlay_path = Path(prospective_overlay_path)
    base_path = Path(base_eval_config_path)

    spec = _load_yaml(spec_path)
    overlay = _load_yaml(overlay_path)

    allowed_keys = frozenset(spec["prospective_eval_overlay_lifecycle"]["allowed_top_level_keys_exact"])
    if set(overlay.keys()) != allowed_keys:
        raise ProspectiveInvalidStateError(
            "prospective overlay top-level keys do not match the registered exact key set"
        )

    required_values_reason = _overlay_required_values_reason(spec=spec, overlay=overlay)
    if required_values_reason is not None:
        raise ProspectiveInvalidStateError(
            f"prospective overlay required value drift: {required_values_reason}"
        )

    base_raw = base_path.read_bytes()
    try:
        base_config = yaml.safe_load(base_raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ProspectiveInvalidStateError(f"base eval config is not valid YAML: {exc}") from exc
    if not isinstance(base_config, dict):
        raise ProspectiveInvalidStateError("base eval config must parse to a mapping")

    if overlay.get("base_config_canonical_lf_sha256") != _canonical_lf_sha256_bytes(base_raw):
        raise ProspectiveInvalidStateError("base eval config canonical_lf_sha256 does not match the overlay pin")

    base_projection_sha256 = _projection_sha256_excluding_labels_snapshot(base_config)
    if overlay.get("base_scoring_semantics_projection_sha256") != base_projection_sha256:
        raise ProspectiveInvalidStateError(
            "base eval config scoring-semantics projection does not match the overlay pin"
        )

    effective_labels_snapshot = overlay.get("effective_labels_snapshot")
    if not isinstance(effective_labels_snapshot, str) or not effective_labels_snapshot.strip():
        raise ProspectiveInvalidStateError("overlay effective_labels_snapshot must be a non-blank string")

    effective_eval_config = dict(base_config)
    effective_eval_config["labels_snapshot"] = effective_labels_snapshot

    return {
        "effective_eval_config": effective_eval_config,
        "overlay_path": str(overlay_path),
        "overlay_canonical_lf_sha256": _canonical_lf_sha256_path(overlay_path),
        "base_projection_sha256": base_projection_sha256,
    }


# ---------------------------------------------------------------------------
# PRE-DATA approval: closed schema + non-vacuous-value validation.
#
# This gates ONLY ADR-0020 stages 1-2 (transport freeze + raw archive
# acquisition). It deliberately does NOT require or check x64/BIAS/Nirvana
# identity -- ClinVar archive acquisition has no x86-only requirement. That
# boundary is enforced later, and separately, by `validate_scoring_stage_approval`
# / `assert_runtime_boundary` above, before ADR-0020 stage 4.
# ---------------------------------------------------------------------------

_APPROVAL_SCHEMA_ID = "raptor.eval.pre_data_approval.v1"

_APPROVAL_TOP_KEYS = frozenset(
    {
        "schema",
        "decision",
        "approver",
        "approved_at",
        "registration",
        "adr",
        "overlay",
        "implementation_freeze",
        "protected_tests_verified",
        "scope",
        "pre_data_access_attestation",
    }
)
_APPROVAL_REGISTRATION_KEYS = frozenset({"id", "path", "git_blob_sha1", "canonical_lf_sha256"})
_APPROVAL_ADR_KEYS = frozenset({"id", "decision_ref"})
_APPROVAL_OVERLAY_KEYS = frozenset({"path", "canonical_lf_sha256"})
_APPROVAL_IMPLEMENTATION_FREEZE_KEYS = frozenset({"commit", "module_hashes", "file_hashes"})
_APPROVAL_SCOPE_KEYS = frozenset(
    {
        "allow_transport_freeze",
        "allow_exact_registered_archive_get",
        "allow_substitute_archive",
        "allow_threshold_change",
        "allow_label_dependent_implementation_change",
        "allow_clinical_use",
        "allow_label_inspection",
        "allow_scoring",
    }
)
_APPROVAL_SCOPE_REQUIRED_VALUES: dict[str, bool] = {
    "allow_transport_freeze": True,
    "allow_exact_registered_archive_get": True,
    "allow_substitute_archive": False,
    "allow_threshold_change": False,
    "allow_label_dependent_implementation_change": False,
    "allow_clinical_use": False,
    "allow_label_inspection": False,
    "allow_scoring": False,
}
_APPROVAL_ATTESTATION_KEYS = frozenset(
    {
        "archive_get_requested",
        "archive_content_downloaded",
        "archive_bytes_hashed",
        "archive_decompressed",
        "labels_inspected",
        "rows_inspected",
        "benchmark_derived",
        "scoring_performed",
    }
)


def _validate_approval_record(
    *,
    spec: Mapping[str, Any],
    spec_path: Path,
    overlay_path: Path,
    approval_record: Any,
    first_archive_get_at: str | None,
) -> Mapping[str, Any]:
    if not isinstance(approval_record, Mapping):
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "pre-data approval record is missing or not a mapping")
    if set(approval_record.keys()) != _APPROVAL_TOP_KEYS:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED",
            f"approval record top-level keys must be exactly {sorted(_APPROVAL_TOP_KEYS)!r}",
        )
    if approval_record.get("schema") != _APPROVAL_SCHEMA_ID:
        raise ProspectiveStopStateError(
            "PRE_DATA_DRIFT", f"approval schema must be {_APPROVAL_SCHEMA_ID!r}, got {approval_record.get('schema')!r}"
        )

    allowed_decisions = set(spec["pre_data_approval"]["allowed_decisions"])
    decision = approval_record.get("decision")
    if decision == "REJECTED_PRE_DATA":
        raise ProspectiveStopStateError("PRE_DATA_REJECTED", "owner recorded REJECTED_PRE_DATA")
    if decision != "APPROVED_PRE_DATA" or decision not in allowed_decisions:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", f"approval decision must be APPROVED_PRE_DATA, got {decision!r}"
        )

    approver_required = spec["pre_data_approval"]["approver_required"]
    if approval_record.get("approver") != approver_required:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", f"approval approver must be {approver_required!r}"
        )

    registration = approval_record.get("registration")
    if not isinstance(registration, Mapping) or set(registration.keys()) != _APPROVAL_REGISTRATION_KEYS:
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval registration block schema invalid")
    if registration.get("id") != spec["registration"]["id"]:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", "approval registration id does not match the registration spec"
        )
    spec_raw = Path(spec_path).read_bytes()
    if registration.get("git_blob_sha1") != _git_blob_sha1(spec_raw):
        raise ProspectiveStopStateError(
            "PRE_DATA_DRIFT", "approval registration git_blob_sha1 does not match the current registration spec bytes"
        )
    if registration.get("canonical_lf_sha256") != _canonical_lf_sha256_bytes(spec_raw):
        raise ProspectiveStopStateError(
            "PRE_DATA_DRIFT", "approval registration canonical_lf_sha256 does not match the current registration spec bytes"
        )

    adr = approval_record.get("adr")
    if not isinstance(adr, Mapping) or set(adr.keys()) != _APPROVAL_ADR_KEYS:
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval adr block schema invalid")
    if adr.get("id") != "ADR-0020" or adr.get("decision_ref") != spec["registration"]["decision"]:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", "approval adr identity does not match the registration spec"
        )

    overlay = approval_record.get("overlay")
    if not isinstance(overlay, Mapping) or set(overlay.keys()) != _APPROVAL_OVERLAY_KEYS:
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval overlay block schema invalid")
    overlay_raw = Path(overlay_path).read_bytes()
    if overlay.get("canonical_lf_sha256") != _canonical_lf_sha256_bytes(overlay_raw):
        raise ProspectiveStopStateError(
            "PRE_DATA_DRIFT", "approval overlay canonical_lf_sha256 does not match the current overlay bytes"
        )

    # Deliberately NO scoring-semantics/base-eval-config verification here --
    # PRE_DATA approval gates ONLY ClinVar archive acquisition (ADR-0020
    # stages 1-2), which never reads or depends on scoring semantics. That
    # concern is enforced exclusively by `merge_prospective_overlay`'s own
    # pins against the overlay document (`base_config_canonical_lf_sha256`,
    # `base_scoring_semantics_projection_sha256`), invoked only when the
    # effective eval config is actually built for ADR-0020 stage 3+ scoring
    # -- never here, and never as a precondition for archive acquisition.

    implementation_freeze = approval_record.get("implementation_freeze")
    if (
        not isinstance(implementation_freeze, Mapping)
        or set(implementation_freeze.keys()) != _APPROVAL_IMPLEMENTATION_FREEZE_KEYS
    ):
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval implementation_freeze block schema invalid")
    if (
        not implementation_freeze.get("commit")
        or not isinstance(implementation_freeze.get("module_hashes"), Mapping)
        or not isinstance(implementation_freeze.get("file_hashes"), Mapping)
    ):
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval implementation_freeze content invalid")
    implementation_freeze_failure = _implementation_freeze_failure_reason(implementation_freeze)
    if implementation_freeze_failure is not None:
        raise ProspectiveStopStateError("PRE_DATA_IMPLEMENTATION_NOT_READY", implementation_freeze_failure)

    # Deliberately NO `immutable_inputs_verified` check here -- the spec's
    # `immutable_inputs` list (tsc2.yaml, ACMG/BIAS/masking/predictor-
    # aggregation policy, ...) is entirely SCORING-stage input identity.
    # ClinVar archive acquisition never reads or depends on any of it, so
    # acquisition-stage (pre_data) approval never requires or verifies it;
    # that check belongs solely to `validate_scoring_stage_approval` (see
    # `_immutable_inputs_failure_reason`), gating ADR-0020 stage 4.

    if approval_record.get("protected_tests_verified") is not True:
        raise ProspectiveStopStateError(
            "PRE_DATA_IMPLEMENTATION_NOT_READY", "protected_tests_verified must be True before PRE-DATA approval"
        )

    # Deliberately NO x64/BIAS/Nirvana identity check here -- PRE_DATA
    # approval gates ONLY ClinVar archive acquisition (ADR-0020 stages 1-2),
    # which has no x86-only requirement. See `validate_scoring_stage_approval`
    # for the separate, later gate that governs ADR-0020 stage 4.

    scope = approval_record.get("scope")
    if not isinstance(scope, Mapping) or set(scope.keys()) != _APPROVAL_SCOPE_KEYS:
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval scope block schema invalid")
    for key, required_value in _APPROVAL_SCOPE_REQUIRED_VALUES.items():
        if scope.get(key) is not required_value:
            raise ProspectiveStopStateError(
                "PRE_DATA_REVIEW_REQUIRED", f"approval scope[{key!r}] must be {required_value!r}"
            )

    attestation = approval_record.get("pre_data_access_attestation")
    if not isinstance(attestation, Mapping) or set(attestation.keys()) != _APPROVAL_ATTESTATION_KEYS:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", "approval pre_data_access_attestation block schema invalid"
        )
    for key in _APPROVAL_ATTESTATION_KEYS:
        if attestation.get(key) is not False:
            raise ProspectiveStopStateError(
                "PRE_DATA_ATTESTATION_BREACH",
                f"pre_data_access_attestation[{key!r}] must remain False before archive access",
            )

    approved_at_raw = approval_record.get("approved_at")
    if not isinstance(approved_at_raw, str) or not approved_at_raw.strip():
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "approval approved_at must be a non-blank timestamp")
    try:
        approved_at_dt = _parse_iso_utc(approved_at_raw)
    except ValueError as exc:
        raise ProspectiveStopStateError(
            "PRE_DATA_REVIEW_REQUIRED", f"approval approved_at is not a valid timestamp: {approved_at_raw!r}"
        ) from exc

    if first_archive_get_at is not None:
        try:
            first_get_dt = _parse_iso_utc(first_archive_get_at)
        except ValueError as exc:
            raise ProspectiveStopStateError(
                "PRE_DATA_REVIEW_REQUIRED", f"first_archive_get_at is not a valid timestamp: {first_archive_get_at!r}"
            ) from exc
        if approved_at_dt >= first_get_dt:
            raise ProspectiveStopStateError(
                "PRE_DATA_DRIFT", "approval approved_at must be strictly before the first archive GET"
            )

    return approval_record


def validate_pre_data_approval(
    *,
    registration_spec_path: "str | Path",
    prospective_overlay_path: "str | Path",
    approval_record: Mapping[str, Any],
    first_archive_get_at: str | None = None,
) -> dict[str, Any]:
    """Validate `approval_record` against the closed
    `raptor.eval.pre_data_approval.v1` schema and the registration/overlay
    files' current bytes. Raises `ProspectiveStopStateError` on any breach;
    returns the (unchanged) validated approval mapping on success."""
    spec_path = Path(registration_spec_path)
    overlay_path = Path(prospective_overlay_path)
    spec = _load_yaml(spec_path)
    validated = _validate_approval_record(
        spec=spec,
        spec_path=spec_path,
        overlay_path=overlay_path,
        approval_record=approval_record,
        first_archive_get_at=first_archive_get_at,
    )
    return dict(validated)


# ---------------------------------------------------------------------------
# Stage 1 HEAD verification + published-date/checksum-source verification.
# ---------------------------------------------------------------------------


def _verify_head(head_payload: Any, stage1: Mapping[str, Any]) -> tuple[str, str] | None:
    if not isinstance(head_payload, Mapping):
        return ("INVALID", "HEAD_RESPONSE_MALFORMED")

    if head_payload.get("status_code") != int(stage1["http_status_must_equal"]):
        return ("BLOCKED_DATA", "HEAD_STATUS_MISMATCH")
    if head_payload.get("final_url") != stage1["final_url_must_equal"]:
        return ("BLOCKED_DATA", "HEAD_FINAL_URL_MISMATCH")

    raw_headers = head_payload.get("raw_headers")
    if not isinstance(raw_headers, list):
        return ("INVALID", "HEAD_RESPONSE_MALFORMED")

    last_modified_values = _header_values(raw_headers, "last-modified")
    if len(last_modified_values) == 0:
        return ("BLOCKED_DATA", "HEAD_LAST_MODIFIED_MISSING")
    if len(last_modified_values) > 1:
        return ("INVALID", "HEAD_LAST_MODIFIED_DUPLICATE")
    try:
        parsed_last_modified = _parse_http_date_to_utc_iso(last_modified_values[0])
    except ValueError:
        return ("BLOCKED_DATA", "HEAD_LAST_MODIFIED_MALFORMED")
    if parsed_last_modified != stage1["last_modified_must_equal"]:
        return ("BLOCKED_DATA", "HEAD_LAST_MODIFIED_MISMATCH")

    content_length_values = _header_values(raw_headers, "content-length")
    if len(content_length_values) == 0:
        return ("BLOCKED_DATA", "HEAD_CONTENT_LENGTH_MISSING")
    if len(content_length_values) > 1:
        return ("INVALID", "HEAD_CONTENT_LENGTH_DUPLICATE")
    raw_content_length = content_length_values[0]
    if not isinstance(raw_content_length, str) or not _DIGITS_RE.fullmatch(raw_content_length):
        return ("BLOCKED_DATA", "HEAD_CONTENT_LENGTH_MALFORMED")
    if int(raw_content_length) != int(stage1["content_length_bytes_must_equal"]):
        return ("BLOCKED_DATA", "HEAD_CONTENT_LENGTH_MISMATCH")

    return None


def _verify_published_date(result: Any) -> tuple[str, str] | None:
    if not isinstance(result, Mapping):
        return ("BLOCKED_DATA", "PUBLISHED_ARCHIVE_DATE_MISSING")
    source_identity = result.get("source_identity")
    if not isinstance(source_identity, str) or not source_identity.strip():
        return ("BLOCKED_DATA", "PUBLISHED_ARCHIVE_DATE_SOURCE_MISSING")
    value = result.get("published_archive_date")
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return ("BLOCKED_DATA", "PUBLISHED_ARCHIVE_DATE_MALFORMED")
    try:
        date.fromisoformat(value)
    except ValueError:
        return ("BLOCKED_DATA", "PUBLISHED_ARCHIVE_DATE_MALFORMED")
    return None


def _verify_official_md5_source(result: Any) -> tuple[str, str] | None:
    if not isinstance(result, Mapping):
        return ("BLOCKED_DATA", "OFFICIAL_MD5_SOURCE_MISSING")
    source_identity = result.get("source_identity")
    if not isinstance(source_identity, str) or not source_identity.strip():
        return ("BLOCKED_DATA", "OFFICIAL_MD5_SOURCE_MISSING")
    official_md5 = result.get("official_md5")
    if not isinstance(official_md5, str) or not _MD5_HEX_RE.fullmatch(official_md5):
        return ("BLOCKED_DATA", "OFFICIAL_MD5_MALFORMED")
    return None


def _stream_download_and_hash(
    transport: Any, url: str, chunk_bytes: int, destination_path: Path, *, expected_length: int
) -> tuple[Path, int, str, str]:
    """Streams `url` into a `.part-<uuid>` temp file under
    `destination_path`'s parent, hashing as it goes. Aborts the moment the
    running total exceeds `expected_length` (never reads a chunk past
    overflow-detection) -- the bounded streamed-download abstraction never
    trusts a HEAD-pinned length by continuing to consume an over-length
    body. Deliberately does NOT commit (`os.replace`) the temp file into
    place -- the caller must run every post-download validation (length,
    MD5, TOCTOU) BEFORE committing, and discard the temp file on any
    non-success so no partial artifact is ever left in the destination."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination_path.with_name(destination_path.name + f".part-{uuid.uuid4().hex}")
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    total = 0
    try:
        with open(tmp_path, "wb") as handle:
            for chunk in transport.stream_get(url, chunk_bytes):
                handle.write(chunk)
                sha256.update(chunk)
                md5.update(chunk)
                total += len(chunk)
                if total > expected_length:
                    break
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path, total, sha256.hexdigest(), md5.hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def execute_transport_and_raw_freeze(
    *,
    registration_spec_path: "str | Path",
    prospective_overlay_path: "str | Path",
    approval_record: Mapping[str, Any] | None,
    allowed_repo_root: "str | Path",
    allowed_external_root: "str | Path",
    transport_freeze_record_path: "str | Path",
    raw_freeze_record_path: "str | Path",
    transport: Any,
    published_archive_date_lookup: Callable[[str], Any],
    official_md5_lookup: Callable[[str], Any],
    cli_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    label_reader: Any = None,
    benchmark_builder: Any = None,
    scoring_runner: Any = None,
    first_archive_get_at: str | None = None,
    transport_identity_pin: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 1 (`HEAD` + published-date + official-MD5-source verification)
    and stage 2 (bounded streamed GET of only the exact registered archive +
    raw hashing) of the ADR-0020 ordered execution sequence. Never invokes
    `label_reader`/`benchmark_builder`/`scoring_runner` (stage 3+ is a
    separate, later additive surface). NEVER requires, reads, or checks
    x64/BIAS/Nirvana identity -- there is no `runtime_identity` parameter
    and no `assert_runtime_boundary` call anywhere in this function, by
    design: ClinVar archive acquisition has no x86-only requirement. That
    boundary is enforced later, and separately, by
    `validate_scoring_stage_approval` before ADR-0020 stage 4.

    Likewise NEVER reads a base eval config and NEVER verifies
    scoring-semantics/base-config hashes -- there is no
    `base_eval_config_path` parameter and no `merge_prospective_overlay`
    call anywhere in this function, by design: acquisition never depends on
    scoring semantics. That verification belongs solely to
    `merge_prospective_overlay`, called only when the effective eval config
    is actually built for ADR-0020 stage 3+ scoring. See module docstring
    for the full fail-closed contract.

    `transport_identity_pin` (optional; from `capture_transport_identity_pin`,
    captured by the caller immediately after constructing `transport` and
    before either lookup port has run) is re-verified against `transport`
    TWICE if supplied: immediately on entry (catching tampering that
    happened between pin capture and this call), and again immediately
    before the real streamed GET (catching tampering performed by
    `published_archive_date_lookup`/`official_md5_lookup` themselves,
    which both run after `transport.head()` but before the GET). Either
    mismatch returns `TRANSPORT_IDENTITY_TAMPERED` before any network
    call. `None` (the default) skips this check entirely, for callers
    that never claim to be a confirmed-live execution path. This pin is
    defense-in-depth: confirmed live `--execute` (see
    `scripts/run_clinvar_2026_08_prospective_freeze.py` and
    `raptor.eval.prospective_exact_source_metadata_lookups`) no longer
    imports any caller-selected Python/plugin code at all before the real
    GET -- both lookup ports are hard-wired to one production-owned,
    statically-imported module, closing the underlying vulnerability this
    pin was originally layered on top of.

    Either lookup port raising any exception is a typed, fail-closed
    `BLOCKED`/`INVALID` result (`PUBLISHED_ARCHIVE_DATE_LOOKUP_FAILED`/
    `OFFICIAL_MD5_LOOKUP_FAILED`), never a raw propagated exception."""
    cli_overrides = cli_overrides or {}
    env_overrides = env_overrides or {}
    if cli_overrides or env_overrides:
        raise ProspectiveInvalidStateError(
            "no CLI, environment-variable, or ad hoc mapping override may replace the registered overlay"
        )
    if transport is None:
        raise ProspectiveInvalidStateError(
            "execute_transport_and_raw_freeze requires an injected transport; there is no default live transport"
        )
    if transport_identity_pin is not None and _transport_identity_pin_mismatch(transport, transport_identity_pin):
        return {
            "stage_status": "BLOCKED",
            "terminal_outcome": "INVALID",
            "reason_code": "TRANSPORT_IDENTITY_TAMPERED",
        }

    spec_path = Path(registration_spec_path)
    overlay_path = Path(prospective_overlay_path)
    allowed_repo_root = Path(allowed_repo_root)
    allowed_external_root = Path(allowed_external_root)
    transport_freeze_record_path = Path(transport_freeze_record_path)
    raw_freeze_record_path = Path(raw_freeze_record_path)

    # Item 1/2: destination-boundary validation for BOTH freeze-record paths
    # runs FIRST -- before the spec/overlay are even loaded and before either
    # path is read or peeked for anything. An out-of-root, symlinked, or
    # special-file record path must never have its content trusted for
    # ANYTHING (not the first_archive_get_at peek below, not approval
    # timing): it is typed INVALID right here, unconditionally.
    for candidate in (transport_freeze_record_path, raw_freeze_record_path):
        boundary_reason = _validate_destination_boundary(candidate, allowed_root=allowed_repo_root)
        if boundary_reason is not None:
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": boundary_reason,
            }

    spec = _load_yaml(spec_path)
    overlay = _load_yaml(overlay_path)
    dataset_registration = spec["dataset_registration"]
    stage1 = dataset_registration["stage_1_head_comparison"]

    # Item 5: overlay/spec coherence (dataset/URL identity ONLY -- never
    # scoring-semantics or base-eval-config hashes, which are out of scope
    # for acquisition) MUST be rejected before any network call.
    coherence_reason = _overlay_coherence_reason(spec=spec, overlay=overlay)
    if coherence_reason is not None:
        return {"stage_status": "BLOCKED", "terminal_outcome": "INVALID", "reason_code": coherence_reason}
    exact_url = str(overlay["exact_archive_url"])

    # Item 4: the caller-supplied transport/raw record paths must be exactly
    # the overlay's OWN registered paths ("write only registered paths"). A
    # caller passing a different (even if otherwise safely in-root) path is
    # rejected before any network call, never silently redirected.
    registered_transport_path = Path(
        os.path.normpath(str(allowed_repo_root / str(overlay["transport_freeze_record"])))
    )
    registered_raw_path = Path(os.path.normpath(str(allowed_repo_root / str(overlay["raw_freeze_record"]))))
    if Path(os.path.normpath(str(transport_freeze_record_path))) != registered_transport_path:
        return {
            "stage_status": "BLOCKED",
            "terminal_outcome": "INVALID",
            "reason_code": "TRANSPORT_RECORD_PATH_NOT_REGISTERED",
        }
    if Path(os.path.normpath(str(raw_freeze_record_path))) != registered_raw_path:
        return {
            "stage_status": "BLOCKED",
            "terminal_outcome": "INVALID",
            "reason_code": "RAW_RECORD_PATH_NOT_REGISTERED",
        }

    initial_overlay_hash = _canonical_lf_sha256_path(overlay_path)
    initial_spec_hash = _canonical_lf_sha256_path(spec_path)
    registration_id = str(spec["registration"]["id"])

    # Item 2: when the caller doesn't supply `first_archive_get_at`, peek any
    # existing transport freeze record's own persisted value so a SECOND run
    # (e.g. a stale/backdated approval on restart) still gets validated
    # against the ORIGINAL first-GET time, not a blank slate. The path was
    # already boundary-validated above; its CONTENT is only trusted once it
    # decodes and passes its own self-hash check. A record that exists but
    # fails that check is a typed INVALID stop right here -- it must never
    # be silently treated as "no candidate" (which could let it be
    # overwritten later) and its data must never reach approval-timing logic.
    effective_first_archive_get_at = first_archive_get_at
    if effective_first_archive_get_at is None and transport_freeze_record_path.exists():
        peeked_transport_record = _load_json_or_none(transport_freeze_record_path)
        if peeked_transport_record is None or not _content_hash_valid(peeked_transport_record):
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "TRANSPORT_RECORD_CORRUPT",
            }
        candidate_first_get_at = peeked_transport_record.get("first_archive_get_at")
        if isinstance(candidate_first_get_at, str) and candidate_first_get_at.strip():
            effective_first_archive_get_at = candidate_first_get_at

    # Item 3: even on a first run with nothing to peek, the approval must
    # predate THIS run's own imminent first GET -- derive that boundary as
    # "now" so a future-dated approval is PRE_DATA_DRIFT before any HEAD/GET,
    # rather than a silent pass-through for lack of a prior recorded value.
    if effective_first_archive_get_at is None:
        effective_first_archive_get_at = _utcnow_iso()

    if approval_record is None:
        raise ProspectiveStopStateError("PRE_DATA_REVIEW_REQUIRED", "pre-data approval record is missing")
    validated_approval = _validate_approval_record(
        spec=spec,
        spec_path=spec_path,
        overlay_path=overlay_path,
        approval_record=approval_record,
        first_archive_get_at=effective_first_archive_get_at,
    )
    timeline: list[dict[str, str]] = [{"event": "approval_verified", "at": _utcnow_iso()}]

    # Item 9: the concurrency-control lock is keyed by the run-scope identity
    # (registration_id + exact_url), never by the caller-chosen destination
    # paths -- two concurrent callers targeting DIFFERENT record paths for
    # the SAME registration/archive are still one logical run scope and must
    # still cause only one real GET. Non-blocking: a losing concurrent call
    # gets an immediate typed INVALID/CONCURRENT_WRITE stop rather than
    # silently queuing behind another caller's in-flight download.
    run_scope_lock = _lock_for(_run_scope_lock_key(registration_id=registration_id, exact_url=exact_url))
    if not run_scope_lock.acquire(blocking=False):
        raise ProspectiveInvalidStateError(
            "a concurrent execute_transport_and_raw_freeze run is already in progress for this registration/exact_url",
            reason_code="CONCURRENT_WRITE",
        )
    try:
        existing = _check_existing_freeze(
            transport_freeze_record_path=transport_freeze_record_path,
            raw_freeze_record_path=raw_freeze_record_path,
            current_registration_id=registration_id,
        )
        if existing is not None:
            kind = existing["kind"]
            if kind == "REUSE":
                transport_record = existing["transport_record"]
                raw_record = existing["raw_record"]
                return {
                    "stage_status": "TRANSPORT_AND_RAW_FROZEN",
                    "terminal_outcome": None,
                    "transport_metadata_not_content_identity": True,
                    "download_chunk_bytes": MAX_DOWNLOAD_CHUNK_BYTES,
                    "raw_archive_path": raw_record.get("raw_archive_path"),
                    "run_scope_id": raw_record.get("run_scope_id"),
                    "idempotent_reuse": True,
                    "transport_record_content_hash": transport_record.get("content_hash"),
                    "raw_record_content_hash": raw_record.get("content_hash"),
                }
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "BLOCKED_DATA" if kind == "DATA_MISMATCH" else "INVALID",
                "reason_code": existing["reason_code"],
            }

        head_outcome = _verify_head(transport.head(exact_url), stage1)
        if head_outcome is not None:
            terminal, reason_code = head_outcome
            return {"stage_status": "BLOCKED", "terminal_outcome": terminal, "reason_code": reason_code}

        # Either lookup port may legitimately raise -- a spec-configuration
        # defect, an unregistered/mismatched URL, or (for the official-MD5
        # port) a network/redirect/size/parse/filename policy rejection
        # (see `raptor.eval.prospective_exact_source_metadata_lookups`'s
        # own docstring for the full closed policy). A raised exception
        # must never propagate out of this function as a raw, untyped
        # traceback: it is always a typed, fail-closed BLOCKED/INVALID
        # result instead, exactly like every other acquisition-readiness
        # gap in this function.
        try:
            published_result = published_archive_date_lookup(exact_url)
        except Exception:  # noqa: BLE001 - any lookup-port failure fails closed, typed, never a raw traceback
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "PUBLISHED_ARCHIVE_DATE_LOOKUP_FAILED",
            }
        published_outcome = _verify_published_date(published_result)
        if published_outcome is not None:
            terminal, reason_code = published_outcome
            return {"stage_status": "BLOCKED", "terminal_outcome": terminal, "reason_code": reason_code}

        try:
            md5_result = official_md5_lookup(exact_url)
        except Exception:  # noqa: BLE001 - any lookup-port failure fails closed, typed, never a raw traceback
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "OFFICIAL_MD5_LOOKUP_FAILED",
            }
        md5_outcome = _verify_official_md5_source(md5_result)
        if md5_outcome is not None:
            terminal, reason_code = md5_outcome
            return {"stage_status": "BLOCKED", "terminal_outcome": terminal, "reason_code": reason_code}

        # Item 1: reject a malicious/unsafe dataset filename before any
        # destination path is built or written.
        filename_reason = _validate_leaf_filename(dataset_registration.get("filename"))
        if filename_reason is not None:
            return {"stage_status": "BLOCKED", "terminal_outcome": "INVALID", "reason_code": filename_reason}

        run_scope_id = uuid.uuid4().hex
        chunk_bytes = MAX_DOWNLOAD_CHUNK_BYTES
        raw_archive_dir = allowed_external_root / run_scope_id
        raw_archive_path = raw_archive_dir / str(dataset_registration["filename"])
        raw_boundary_reason = _validate_destination_boundary(raw_archive_path, allowed_root=allowed_external_root)
        if raw_boundary_reason is not None:
            return {"stage_status": "BLOCKED", "terminal_outcome": "INVALID", "reason_code": raw_boundary_reason}

        # Run-scope destination freshness: `allowed_external_root` is
        # explicitly permitted to already hold content from unrelated prior
        # runs (it is never required to be globally empty) -- but THIS
        # run's own freshly minted `run_scope_id` subdirectory must be
        # unclaimed. Anything already present there (a directory or the
        # exact archive leaf path) is never reused or silently overwritten;
        # it is a typed INVALID, checked (and any real GET refused) before
        # the transport freeze record is even written, and before the
        # archive is ever requested.
        if _lstat_or_none(raw_archive_dir) is not None or _lstat_or_none(raw_archive_path) is not None:
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "RUN_SCOPE_DESTINATION_NOT_FRESH",
            }

        first_archive_get_at_value = _utcnow_iso()
        timeline.append({"event": "archive_get_started", "at": first_archive_get_at_value})

        transport_record = {
            "schema": "raptor.eval.prospective_transport_freeze.v1",
            "status": "TRANSPORT_FROZEN",
            "registration_id": registration_id,
            "run_scope_id": run_scope_id,
            "exact_url": exact_url,
            "final_url": stage1["final_url_must_equal"],
            "http_status": int(stage1["http_status_must_equal"]),
            "last_modified_utc": stage1["last_modified_must_equal"],
            "content_length_bytes": int(stage1["content_length_bytes_must_equal"]),
            "transport_metadata_not_content_identity": True,
            "published_archive_date": published_result["published_archive_date"],
            "published_archive_date_source_identity": published_result["source_identity"],
            "official_md5": str(md5_result["official_md5"]).lower(),
            "official_md5_source_identity": md5_result["source_identity"],
            "approval_content_hash": _content_hash(dict(validated_approval)),
            "approval_approver": validated_approval["approver"],
            "approval_approved_at": validated_approval["approved_at"],
            "first_archive_get_at": first_archive_get_at_value,
            "timeline": list(timeline),
            "recorded_at": _utcnow_iso(),
        }
        transport_record["content_hash"] = _content_hash(transport_record)
        try:
            _atomic_write_json(transport_freeze_record_path, transport_record)
        except ProspectiveContractError:
            raise
        except Exception as exc:
            raise ProspectiveInvalidStateError(f"transport freeze record write failed: {exc}") from exc

        # Item 1 (independent review): re-verify the transport identity pin
        # immediately before the real streamed GET -- this is the point
        # that specifically catches tampering performed by
        # `published_archive_date_lookup`/`official_md5_lookup` themselves
        # (both already invoked above, between `transport.head()` and
        # here). A mismatch refuses the GET outright; nothing above this
        # point performed a real archive download.
        if transport_identity_pin is not None and _transport_identity_pin_mismatch(transport, transport_identity_pin):
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "TRANSPORT_IDENTITY_TAMPERED",
            }

        expected_length = int(stage1["content_length_bytes_must_equal"])
        tmp_path, byte_length, raw_sha256, computed_md5 = _stream_download_and_hash(
            transport, exact_url, chunk_bytes, raw_archive_path, expected_length=expected_length
        )

        def _discard_tmp_download() -> None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)

        if byte_length != expected_length:
            _discard_tmp_download()
            return {"stage_status": "BLOCKED", "terminal_outcome": "BLOCKED_DATA", "reason_code": "RAW_LENGTH_MISMATCH"}

        official_md5 = str(md5_result["official_md5"]).lower()
        if computed_md5 != official_md5:
            _discard_tmp_download()
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "BLOCKED_DATA",
                "reason_code": "OFFICIAL_MD5_MISMATCH",
            }

        # Item 6: the TOCTOU overlay/spec re-check must itself be treated as
        # fail-closed -- if the overlay or spec became unreadable (deleted,
        # replaced by a directory, permission loss) DURING the GET, that is
        # typed INVALID, not an uncaught OSError.
        try:
            overlay_unchanged = _canonical_lf_sha256_path(overlay_path) == initial_overlay_hash
            spec_unchanged = _canonical_lf_sha256_path(spec_path) == initial_spec_hash
        except (OSError, UnicodeDecodeError):
            _discard_tmp_download()
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "OVERLAY_OR_SPEC_UNREADABLE_DURING_RUN",
            }
        if not overlay_unchanged or not spec_unchanged:
            _discard_tmp_download()
            return {
                "stage_status": "BLOCKED",
                "terminal_outcome": "INVALID",
                "reason_code": "OVERLAY_MUTATED_DURING_RUN",
            }

        # Only now -- after every post-download validation has passed -- is
        # the temp file committed into the destination (atomic rename); a
        # failure on any check above leaves zero files under the external
        # root (item 2: abort/cleanup on every non-success).
        raw_archive_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, raw_archive_path)

        raw_record = {
            "schema": "raptor.eval.prospective_raw_freeze.v1",
            "status": "RAW_ARCHIVE_FROZEN",
            "registration_id": registration_id,
            "run_scope_id": run_scope_id,
            "raw_archive_path": str(raw_archive_path.resolve()),
            "byte_length": byte_length,
            "computed_md5": computed_md5,
            "official_md5": official_md5,
            "raw_sha256": raw_sha256,
            "transport_record_content_hash": transport_record["content_hash"],
            "recorded_at": _utcnow_iso(),
        }
        raw_record["content_hash"] = _content_hash(raw_record)
        try:
            _atomic_write_json(raw_freeze_record_path, raw_record)
        except ProspectiveContractError:
            raise
        except Exception as exc:
            raise ProspectiveInvalidStateError(f"raw freeze record write failed: {exc}") from exc

        return {
            "stage_status": "TRANSPORT_AND_RAW_FROZEN",
            "terminal_outcome": None,
            "transport_metadata_not_content_identity": True,
            "download_chunk_bytes": chunk_bytes,
            "raw_archive_path": raw_record["raw_archive_path"],
            "run_scope_id": run_scope_id,
            "idempotent_reuse": False,
            "transport_record_content_hash": transport_record["content_hash"],
            "raw_record_content_hash": raw_record["content_hash"],
        }
    finally:
        run_scope_lock.release()


# ---------------------------------------------------------------------------
# A0-A6 per-scope adjudication + terminal-outcome/authorization mapping.
# ---------------------------------------------------------------------------

_SCOPE_REQUIRED_KEYS = frozenset(
    {
        "actual_count",
        "called_count",
        "correct_calls",
        "min_count",
        "data_sufficiency",
        "conditional_performance",
        "policy_parity",
        "reasons",
    }
)
_A1_VALUES = frozenset({"ADEQUATE", "UNDERPOWERED", "NO_CALLS"})
_A2_VALUES = frozenset({"MET", "UNMET", "NOT_ESTIMABLE", "NOT_APPLICABLE"})
_A3_VALUES = frozenset({"CLEAR", "BLOCKED"})
_RUN_INTEGRITY_VALUES = frozenset({"PASS", "INVALID"})


def _valid_nonneg_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _resolve_a5(*, run_integrity: str, a1: str, a2: str, a3: str) -> str:
    if run_integrity == "INVALID":
        return "INVALID"
    if a2 == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if a1 == "NO_CALLS":
        return "NO_CALLS"
    if a1 == "UNDERPOWERED":
        return "UNDERPOWERED"
    if a3 == "BLOCKED":
        return "BLOCKED_POLICY"
    if a2 == "UNMET":
        return "NOT_SUPPORTED"
    if a1 == "ADEQUATE" and a2 == "MET" and a3 == "CLEAR":
        return "VALIDATED_PROSPECTIVE"
    raise ProspectiveInvalidStateError(
        f"inconsistent adjudication axis combination: run_integrity={run_integrity!r} A1={a1!r} A2={a2!r} A3={a3!r}"
    )


def _compute_scope_axes(scope: Any, *, run_integrity: str) -> dict[str, Any]:
    if not isinstance(scope, Mapping) or set(scope.keys()) != _SCOPE_REQUIRED_KEYS:
        raise ProspectiveInvalidStateError(
            f"adjudicated scope must define exactly {sorted(_SCOPE_REQUIRED_KEYS)!r}"
        )
    for key in ("actual_count", "called_count", "correct_calls", "min_count"):
        if not _valid_nonneg_int(scope[key]):
            raise ProspectiveInvalidStateError(f"scope[{key!r}] must be a non-bool non-negative int")

    a1 = scope["data_sufficiency"]
    a2 = scope["conditional_performance"]
    a3 = scope["policy_parity"]
    if a1 not in _A1_VALUES:
        raise ProspectiveInvalidStateError(f"unknown data_sufficiency value: {a1!r}")
    if a2 not in _A2_VALUES:
        raise ProspectiveInvalidStateError(f"unknown conditional_performance value: {a2!r}")
    if a3 not in _A3_VALUES:
        raise ProspectiveInvalidStateError(f"unknown policy_parity value: {a3!r}")

    reasons = scope["reasons"]
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise ProspectiveInvalidStateError("scope['reasons'] must be a list of strings")

    a4 = f"{scope['correct_calls']}/{scope['actual_count']}"
    a5 = _resolve_a5(run_integrity=run_integrity, a1=a1, a2=a2, a3=a3)
    a6 = "AUTHORIZED_RESEARCH_ONLY" if a5 == "VALIDATED_PROSPECTIVE" else "NOT_AUTHORIZED"

    return {
        "A0": run_integrity,
        "A1": a1,
        "A2": a2,
        "A3": a3,
        "A4": a4,
        "A5": a5,
        "A6": a6,
        "reasons": list(reasons),
    }


def _scope_terminal_for_aggregation(axes: Mapping[str, Any]) -> str:
    """Full-spectrum/narrow-scope terminal-outcome PROJECTION for a single
    scope. This is distinct from the reported per-scope `A5` value itself
    (`A5` keeps its own precedence -- e.g. NO_CALLS/UNDERPOWERED/
    NOT_APPLICABLE can still be reported even when policy_parity is
    BLOCKED). For AGGREGATION purposes only, an A3==BLOCKED policy-parity
    verdict on a run-integrity-PASS scope always forces BLOCKED_POLICY,
    regardless of whether A1/A2 would otherwise have been decisive."""
    if axes["A0"] == "INVALID":
        return "INVALID"
    if axes["A3"] == "BLOCKED":
        return "BLOCKED_POLICY"
    return _A5_TO_SCOPE_TERMINAL[axes["A5"]]


def adjudicate_prospective_outcomes(
    *,
    registration_id: str,
    registration_spec_path: "str | Path",
    scoring_stage_approval_record: Mapping[str, Any],
    allowed_repo_root: "str | Path",
    first_scoring_execution_at: str,
    run_integrity: str,
    stage12_outcome: str | None,
    scopes: Mapping[str, Any],
    required_scopes: Iterable[str],
    narrow_scope: str,
    cli_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    transport_metadata_not_content_identity: bool = True,
    worker_designation_probe: Callable[[], str] | None = None,
    worker_arch_probe: Callable[[], str] | None = None,
    bias_commit_probe: Callable[[], str] | None = None,
    nirvana_banner_probe: Callable[[], str] | None = None,
    resource_manifest_location_probe: Callable[[], "str | Path"] | None = None,
) -> dict[str, Any]:
    """ADR-0020 A0-A6 per-scope adjudication. Trusts (never recomputes) each
    scope's pre-derived A1/A2/A3 verdict; derives A4 (`"{correct}/{actual}"`),
    A5 (`A5_PRECEDENCE`) and A6, then the closed six-value terminal-outcome/
    full-spectrum/narrow-scope precedence and authorization mapping. Raises
    `ProspectiveInvalidStateError` on any override input, missing metadata
    note, missing/unknown axis value, or unresolvable axis combination.

    MANDATORY scoring-stage gate: the very first thing this function does,
    unconditionally and before any other input is even inspected, is call
    `validate_scoring_stage_approval` with `scoring_stage_approval_record`
    -- never trusting it on its own -- which independently OBSERVES the
    runtime identity (via the `*_probe` parameters, forwarded verbatim; see
    `observe_runtime_identity`) and independently RECOMPUTES the
    resource-manifest digest and the scoring-stage `immutable_inputs`
    hashes, rather than accepting any caller-claimed value. A missing,
    fabricated, or mismatched scoring-stage approval/runtime-identity/
    immutable-input, or a missing/future/mistimed `first_scoring_execution_at`,
    raises `ProspectiveInvalidStateError` here and NO outcome dict of any
    kind (including `BLOCKED_DATA`/`FAIL`/`INVALID`, and in particular
    never `PASS` or `AUTHORIZED_RESEARCH_ONLY`) is ever returned. This is a
    hard structural precondition, not a conditional check keyed off the
    eventual outcome -- there is no code path in this function that can
    produce a result without first passing this gate."""
    validate_scoring_stage_approval(
        registration_id=registration_id,
        registration_spec_path=registration_spec_path,
        approval_record=scoring_stage_approval_record,
        allowed_repo_root=allowed_repo_root,
        first_scoring_execution_at=first_scoring_execution_at,
        worker_designation_probe=worker_designation_probe,
        worker_arch_probe=worker_arch_probe,
        bias_commit_probe=bias_commit_probe,
        nirvana_banner_probe=nirvana_banner_probe,
        resource_manifest_location_probe=resource_manifest_location_probe,
    )

    cli_overrides = cli_overrides or {}
    env_overrides = env_overrides or {}
    if cli_overrides or env_overrides:
        raise ProspectiveInvalidStateError(
            "no CLI, environment-variable, or ad hoc mapping override may replace the registered overlay"
        )
    if transport_metadata_not_content_identity is not True:
        raise ProspectiveInvalidStateError(
            "transport_metadata_not_content_identity must remain True (HEAD metadata never proves content identity)"
        )
    if run_integrity not in _RUN_INTEGRITY_VALUES:
        raise ProspectiveInvalidStateError(f"unknown run_integrity value: {run_integrity!r}")
    if stage12_outcome is not None and stage12_outcome != "BLOCKED_DATA":
        raise ProspectiveInvalidStateError(f"unsupported stage12_outcome value: {stage12_outcome!r}")
    if not isinstance(scopes, Mapping):
        raise ProspectiveInvalidStateError("scopes must be a mapping")

    required_scopes = list(required_scopes)
    for scope_name in required_scopes:
        if scope_name not in scopes:
            raise ProspectiveInvalidStateError(f"missing required scope: {scope_name!r}")
    if narrow_scope not in scopes:
        raise ProspectiveInvalidStateError(f"missing narrow scope: {narrow_scope!r}")

    resolved_scopes = {
        name: _compute_scope_axes(payload, run_integrity=run_integrity) for name, payload in scopes.items()
    }

    if stage12_outcome == "BLOCKED_DATA":
        full_spectrum_terminal = "BLOCKED_DATA"
    elif run_integrity == "INVALID":
        full_spectrum_terminal = "INVALID"
    else:
        required_terminals = [_scope_terminal_for_aggregation(resolved_scopes[name]) for name in required_scopes]
        if any(value == "BLOCKED_POLICY" for value in required_terminals):
            full_spectrum_terminal = "BLOCKED_POLICY"
        elif any(value == "FAIL" for value in required_terminals):
            full_spectrum_terminal = "FAIL"
        elif any(value == "NOT_ESTIMABLE" for value in required_terminals):
            full_spectrum_terminal = "NOT_ESTIMABLE"
        elif all(value == "PASS" for value in required_terminals):
            full_spectrum_terminal = "PASS"
        else:
            raise ProspectiveInvalidStateError("required scopes produced an unresolvable full-spectrum outcome")

    full_spectrum_status, full_spectrum_authorization = _OUTCOME_STATUS_AND_AUTH[full_spectrum_terminal]

    if stage12_outcome == "BLOCKED_DATA":
        narrow_terminal = "BLOCKED_DATA"
        narrow_auth = "NOT_AUTHORIZED"
    elif run_integrity == "INVALID":
        narrow_terminal = "INVALID"
        narrow_auth = "NOT_AUTHORIZED"
    else:
        narrow_terminal = _scope_terminal_for_aggregation(resolved_scopes[narrow_scope])
        narrow_auth = "AUTHORIZED_RESEARCH_ONLY" if narrow_terminal == "PASS" else "NOT_AUTHORIZED"

    return {
        "scopes": resolved_scopes,
        "full_spectrum_terminal_outcome": full_spectrum_terminal,
        "full_spectrum_status": full_spectrum_status,
        "full_spectrum_authorization": full_spectrum_authorization,
        "narrow_scope": {
            "scope": narrow_scope,
            "terminal_outcome": narrow_terminal,
            "authorization_status": narrow_auth,
        },
    }
