#!/usr/bin/env python
"""Execution-preparation harness for ADR-0020 / `docs/project/specs/
clinvar-2026-08-prospective-amendment-v2.yaml` stage 1/2 (transport freeze +
raw archive freeze), wrapping `raptor.eval.prospective_freeze
.execute_transport_and_raw_freeze`.

This script is INERT by construction, on every host, until ALL of the
following are true, checked in this exact order:

1. `--execute` is passed (default is a dry-run status report only -- no
   filesystem writes outside the freeze-record paths, no network calls, no
   transport resolution).
2. The running interpreter is the WSL2 `raptor` venv policy interpreter,
   `sys.executable == "/home/sdrona/raptor/bin/python"` -- checked here,
   unconditionally, before anything else (including argument completeness
   and the approval record), as this repository's standing RAPTOR
   execution-environment policy: every RAPTOR Python entry point runs
   inside that one WSL2 venv, never a native/Windows interpreter and never
   gated on host CPU architecture (stage 1/2 -- transport + raw archive
   freeze -- has no x86-only requirement; only the later BIAS-2015/Nirvana
   ADR-0008 stage does, and that stage is out of scope here).
3. Every required `--execute` option is present (`--approval-record`,
   `--allowed-external-root`). Finding #3 (independent review): production
   transport is HARD-WIRED to
   `raptor.eval.prospective_exact_source_transport.build_transport()` --
   there is no `--transport-factory` (or any other) CLI option, config
   value, or environment variable capable of substituting a different
   transport for a confirmed live `--execute` run. This closes the
   arbitrary-live-transport-substitution vulnerability: a caller can no
   longer point real execution at anything other than the one safe,
   redirect-refusing, exact-URL-only, TLS-always-on transport this
   repository ships. Finding #1 (independent review, round 5): the two
   metadata lookup ports are hard-wired the SAME way -- there is no
   `--published-archive-date-lookup`/`--official-md5-lookup` (or any
   other) CLI option, config value, or environment variable either;
   supplying either flag is now an "unrecognized arguments" argparse
   failure, checked before anything else in this script even runs.
4. `--approval-record <path>` points at a JSON file that
   `raptor.eval.prospective_freeze.validate_pre_data_approval` accepts --
   schema `raptor.eval.pre_data_approval.v1`, `decision ==
   "APPROVED_PRE_DATA"`, approver `@dronasrinivas`, matching spec/overlay
   hashes, non-vacuous `immutable_inputs_verified` /
   `protected_tests_verified`, and an all-`False`
   `pre_data_access_attestation`. This record deliberately has NO
   `x64_freeze` block and is never checked against
   `assert_runtime_boundary` -- consistent with item 2 above, ClinVar
   archive acquisition has no x86-only requirement. The separate, later
   x64/BIAS/Nirvana/resource-manifest gate
   (`raptor.eval.prospective_freeze.validate_scoring_stage_approval`) is
   out of scope for this script; it is required only before ADR-0020
   stage 4 (BIAS/Nirvana execution or label-dependent evaluation), which
   this script never performs.
5. `--allowed-external-root` passes preflight (see `_preflight_external_root`):
   it must already exist, be a plain directory (never a symlink/reparse
   point), resolve to itself, sit outside the repository root, and be
   writable. It is explicitly allowed to already contain content from
   unrelated prior runs -- only this run's own freshly generated
   run-scope destination is required to be unclaimed, and that freshness
   check lives in `raptor.eval.prospective_freeze
   .execute_transport_and_raw_freeze` itself, not here.
6. A real network transport is always the ONE hard-wired production
   implementation, `prospective_exact_source_transport.build_transport()`
   -- called with no arguments, so every hook (`connection_factory`,
   `socket_module`, `tls_context_factory`) is that function's own real
   default (`http.client.HTTPSConnection`, `ssl.create_default_context`
   with TLS verification always on). Both external lookups
   (`published_archive_date_lookup`/`official_md5_lookup`) are ALSO
   hard-wired -- to `raptor.eval.prospective_exact_source_metadata_lookups
   .published_archive_date_lookup`/`.official_md5_lookup`, the one
   production-owned module for both ports, imported statically at the top
   of this file. Neither port's production implementation performs a
   real NCBI query yet (both always raise
   `MetadataLookupNotYetImplementedError`, fail-closed, since neither
   port's real-world NCBI metadata source has ever been ratified by this
   contract -- see that module's docstring); a real implementation must
   land there via a dedicated, reviewed change, never via a CLI-selected
   substitute.

Independent review finding (live-transport-bypass, round 5): before this
round, the two lookup ports above were resolved from CLI-supplied
`--published-archive-date-lookup`/`--official-md5-lookup`
`"module:callable"` strings via `importlib.import_module`, run AFTER
`build_transport()` returned but BEFORE the real archive GET -- the only
window in this script where non-production-owned code executed at all.
Merely capturing a transport-identity pin afterward was an incomplete
defense: importing arbitrary caller-selected code is dangerous regardless
of what happens to `transport` specifically (that code could open its own
sockets, mutate unrelated module globals, replace
`prospective_freeze.execute_transport_and_raw_freeze` itself, etc.). Both
CLI options, and the `_resolve_import_target` dynamic-import helper that
served them, have been removed entirely -- confirmed live `--execute`
imports/executes ZERO caller-selected Python/plugin code before the real
GET. The transport-identity-pin defense described next is retained purely
as defense-in-depth, not as the primary answer to that vulnerability.

Transport-tamper defense-in-depth: this script still captures a
`capture_transport_identity_pin(transport)` identity pin IMMEDIATELY after
`build_transport()` returns and passes it to
`execute_transport_and_raw_freeze`, which re-verifies it twice (on entry,
and again immediately before the real streamed GET) and refuses with
`TRANSPORT_IDENTITY_TAMPERED` on any mismatch -- before any network call.
With both lookup ports now hard-wired (no caller-selected import path
remains at all), this guards only against a hypothetical future
regression, not a live vulnerability.

Even with every one of the above satisfied, this script never invokes
`label_reader`/`benchmark_builder`/`scoring_runner` -- stage 3+ (label
read, benchmark build, masking, scoring) is out of scope for stage 1/2 and
is a separate, later additive surface; both are always left unset.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import raptor.eval.prospective_exact_source_metadata_lookups as prospective_exact_source_metadata_lookups
import raptor.eval.prospective_exact_source_transport as prospective_exact_source_transport
import raptor.eval.prospective_freeze as prospective_freeze

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
DEFAULT_OVERLAY_PATH = REPO_ROOT / "configs" / "eval" / "tsc2_clinvar_2026_08_amendment_v2.overlay.yaml"
DEFAULT_BASE_CONFIG_PATH = REPO_ROOT / "configs" / "eval" / "tsc2.yaml"

#: This repository's standing RAPTOR Python execution-environment policy:
#: every RAPTOR CLI/module entry point runs inside the WSL2 `raptor` venv
#: at this exact interpreter path -- never a native Windows interpreter.
REQUIRED_WSL_PYTHON = "/home/sdrona/raptor/bin/python"


class HarnessEnvironmentError(RuntimeError):
    """Raised when the running interpreter is not the required WSL2
    `raptor` venv policy interpreter."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return loaded


def _assert_wsl_python_policy() -> None:
    if sys.executable != REQUIRED_WSL_PYTHON:
        raise HarnessEnvironmentError(
            "This is not the required WSL2 raptor venv interpreter: "
            f"sys.executable == {sys.executable!r}, required {REQUIRED_WSL_PYTHON!r}. "
            "Every RAPTOR execute entry point must run inside WSL2 at that exact "
            "venv path (see AGENTS.md RAPTOR Python execution environment policy). "
            "Refusing to proceed."
        )


def _preflight_external_root(candidate: Path, *, allowed_repo_root: Path) -> str | None:
    """Return `None` if `candidate` is an acceptable `--allowed-external-root`,
    else a human-readable refusal reason (always mentioning
    `--allowed-external-root` so it can never be confused with any other
    refusal path). Never asserts the root is empty of prior runs -- only
    that it exists, is a plain (non-symlink/reparse) directory, resolves to
    itself, sits outside the repository root, and is writable."""
    if not os.path.lexists(candidate):
        return f"--allowed-external-root does not exist: {candidate}"
    if candidate.is_symlink():
        return f"--allowed-external-root must not be a symlink: {candidate}"
    if not candidate.is_dir():
        return f"--allowed-external-root must be a plain directory: {candidate}"
    resolved = candidate.resolve()
    if resolved != candidate:
        return f"--allowed-external-root must resolve to itself (no reparse point anywhere in its path): {candidate}"
    try:
        resolved.relative_to(allowed_repo_root.resolve())
    except ValueError:
        pass
    else:
        return f"--allowed-external-root must be outside the repository root: {candidate}"
    if not os.access(candidate, os.W_OK):
        return f"--allowed-external-root is not writable: {candidate}"
    return None


def _dry_run_report(*, spec_path: Path, overlay_path: Path, base_config_path: Path, approval_record_path: Path | None) -> int:
    report: dict[str, Any] = {
        "mode": "DRY_RUN",
        "host_platform_machine": platform.machine(),
        "python_executable": sys.executable,
        "wsl_python_policy_satisfied": sys.executable == REQUIRED_WSL_PYTHON,
        "network_calls_made": False,
    }
    try:
        merge_result = prospective_freeze.merge_prospective_overlay(
            registration_spec_path=spec_path,
            prospective_overlay_path=overlay_path,
            base_eval_config_path=base_config_path,
        )
        report["overlay_merge_status"] = "OK"
        report["effective_labels_snapshot"] = merge_result["effective_eval_config"]["labels_snapshot"]
        report["overlay_canonical_lf_sha256"] = merge_result["overlay_canonical_lf_sha256"]
    except prospective_freeze.ProspectiveContractError as exc:
        report["overlay_merge_status"] = "REJECTED"
        report["overlay_merge_reason"] = str(exc)

    if approval_record_path is not None:
        try:
            approval_record = _load_json(approval_record_path)
            prospective_freeze.validate_pre_data_approval(
                registration_spec_path=spec_path,
                prospective_overlay_path=overlay_path,
                approval_record=approval_record,
            )
            report["approval_record_status"] = "VALID"
        except prospective_freeze.ProspectiveStopStateError as exc:
            report["approval_record_status"] = "REJECTED"
            report["approval_record_stop_state"] = exc.stop_state
            report["approval_record_reason"] = exc.reason
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report["approval_record_status"] = "UNREADABLE"
            report["approval_record_reason"] = str(exc)
    else:
        report["approval_record_status"] = "NOT_SUPPLIED"

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="Perform stage 1/2 execution. Default is dry-run only.")
    parser.add_argument("--approval-record", type=Path, default=None, help="Path to a raptor.eval.pre_data_approval.v1 JSON record.")
    parser.add_argument("--registration-spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY_PATH)
    parser.add_argument("--base-config", type=Path, default=DEFAULT_BASE_CONFIG_PATH)
    parser.add_argument("--allowed-repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--allowed-external-root",
        type=Path,
        default=None,
        help="Off-repo root for the raw archive GET destination (see docs/ops/"
        "clinvar-2026-08-amendment-v2-external-content-root.md). Required with --execute.",
    )
    parser.add_argument("--transport-freeze-record", type=Path, default=None)
    parser.add_argument("--raw-freeze-record", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.execute:
        return _dry_run_report(
            spec_path=args.registration_spec,
            overlay_path=args.overlay,
            base_config_path=args.base_config,
            approval_record_path=args.approval_record,
        )

    # Everything below only runs with --execute, strictly in this order:
    # (1) WSL python policy -- unconditional, before anything else is even
    #     inspected; (2) required-option completeness; (3) real approval
    #     validation; (4) external-root preflight; (5) transport
    #     construction (hard-wired; no caller-selected code runs here or
    #     anywhere else in this script before the real GET -- both metadata
    #     lookup ports are likewise hard-wired module-level references, not
    #     resolved from any CLI input); (6) execute_transport_and_raw_freeze
    #     itself.
    try:
        _assert_wsl_python_policy()
    except HarnessEnvironmentError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    missing_options: list[str] = []
    if args.approval_record is None:
        missing_options.append("--approval-record")
    if args.allowed_external_root is None:
        missing_options.append("--allowed-external-root")
    if missing_options:
        print(
            "REFUSED: --execute requires all of the following options, missing: " + ", ".join(missing_options),
            file=sys.stderr,
        )
        return 2

    approval_record_path = args.approval_record
    try:
        approval_record = _load_json(approval_record_path)
    except FileNotFoundError as exc:
        print(f"REFUSED: approval record not found (no such file): {approval_record_path}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"REFUSED: approval record unreadable: {approval_record_path}: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"REFUSED: approval record JSON decode failed: {approval_record_path}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"REFUSED: approval record invalid: {approval_record_path}: {exc}", file=sys.stderr)
        return 2

    try:
        prospective_freeze.validate_pre_data_approval(
            registration_spec_path=args.registration_spec,
            prospective_overlay_path=args.overlay,
            approval_record=approval_record,
        )
    except prospective_freeze.ProspectiveStopStateError as exc:
        print(f"REFUSED: {exc.stop_state}: {exc.reason}", file=sys.stderr)
        return 2

    root_refusal = _preflight_external_root(args.allowed_external_root, allowed_repo_root=args.allowed_repo_root)
    if root_refusal is not None:
        print(f"REFUSED: {root_refusal}", file=sys.stderr)
        return 2

    # Finding #3: production transport is HARD-WIRED to the one safe,
    # exact-source implementation -- no CLI option, environment variable,
    # or config value can select a different transport for a confirmed
    # live --execute run. `build_transport()` is called with no arguments,
    # so every hook is that function's own real default.
    transport = prospective_exact_source_transport.build_transport()

    # Transport-tamper defense-in-depth: the identity pin is captured HERE,
    # immediately after `build_transport()` returns. `execute_transport_
    # and_raw_freeze` re-verifies this pin twice (on entry, and again
    # immediately before the real streamed GET) and refuses with
    # TRANSPORT_IDENTITY_TAMPERED on any mismatch. This is defense-in-depth
    # only: independent review finding #1 (round 5) removed the underlying
    # vulnerability entirely -- neither metadata lookup port below is
    # resolved from any CLI input, module:callable string, or other
    # runtime-selectable source. Both are fixed, statically-imported
    # module-level references to raptor.eval.prospective_exact_source_
    # metadata_lookups (imported at the top of this file); no caller-
    # selected Python/plugin code executes anywhere in this script before
    # the real GET.
    transport_identity_pin = prospective_freeze.capture_transport_identity_pin(transport)
    published_archive_date_lookup = prospective_exact_source_metadata_lookups.published_archive_date_lookup
    official_md5_lookup = prospective_exact_source_metadata_lookups.official_md5_lookup

    try:
        overlay = prospective_freeze._load_yaml(args.overlay)  # noqa: SLF001 - read-only path resolution
    except prospective_freeze.ProspectiveContractError as exc:
        print(f"REFUSED: overlay {exc}", file=sys.stderr)
        return 2

    try:
        transport_freeze_record_path = args.transport_freeze_record or (
            args.allowed_repo_root / str(overlay["transport_freeze_record"])
        )
        raw_freeze_record_path = args.raw_freeze_record or (args.allowed_repo_root / str(overlay["raw_freeze_record"]))
    except KeyError as exc:
        print(f"REFUSED: overlay missing required key: {exc}", file=sys.stderr)
        return 2

    try:
        result = prospective_freeze.execute_transport_and_raw_freeze(
            registration_spec_path=args.registration_spec,
            prospective_overlay_path=args.overlay,
            approval_record=approval_record,
            allowed_repo_root=args.allowed_repo_root,
            allowed_external_root=args.allowed_external_root,
            transport_freeze_record_path=transport_freeze_record_path,
            raw_freeze_record_path=raw_freeze_record_path,
            transport=transport,
            published_archive_date_lookup=published_archive_date_lookup,
            official_md5_lookup=official_md5_lookup,
            label_reader=None,
            benchmark_builder=None,
            scoring_runner=None,
            transport_identity_pin=transport_identity_pin,
        )
    except prospective_freeze.ProspectiveContractError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except prospective_exact_source_transport.ExactSourceTransportError as exc:
        reason_code = getattr(exc, "reason_code", None)
        suffix = f" ({reason_code})" if reason_code else ""
        print(f"REFUSED: {type(exc).__name__}{suffix}: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("terminal_outcome") is None else 3


if __name__ == "__main__":
    raise SystemExit(main())
