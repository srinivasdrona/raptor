#!/usr/bin/env python
"""ADR-0008 x64 worker operator utility — computes `resource_manifest_sha256`.

READ-ONLY. Reads ONLY the three pinned checksum-manifest text files named in
`raptor.eval.prospective_freeze.RESOURCE_MANIFEST_ENTRIES`
(`nirvana-grch38-full.sha256.txt`, `nirvana-grch38-updates.sha256.txt`,
`bias-hg38-data.sha256.txt`) under `--checksums-dir`. It never touches the
multi-GB Nirvana/BIAS annotation-data bundles those manifests describe,
never downloads or contacts ClinVar or any other network endpoint, never
runs BIAS-2015 or Nirvana, and never writes, mutates, or deletes anything —
it only prints a report to stdout. See `docs/ops/adr-0008-resource-manifest-
digest.md` for the full digest spec this wraps
(`raptor.eval.prospective_freeze.compute_resource_manifest_sha256`).

This script is meant to run on the ADR-0008-designated x64 worker itself
(never on the ARM Queen or in this repository's WSL2 dev venv — see
`docs/DECISIONS.md` ADR-0008). By default it refuses to run on a host whose
`platform.machine()` is not `x86_64`/`AMD64`; pass `--allow-non-x64-host`
only for offline testing of this script's own logic (e.g. this repository's
own test suite), never for a real ADR-0008 pin.

Copy-paste on the real x64 worker (PowerShell), once the three manifest
files are present under `D:\\raptor-x64\\CHECKSUMS`:

    cd D:\\raptor
    python scripts\\compute_adr0008_resource_manifest_sha256.py

The printed `resource_manifest_sha256` is the exact, and only, value a human
approver may paste into a `scoring_stage_approval` record's `x64_freeze` block —
never a fabricated or copied-from-elsewhere value (see the module docstring
of `raptor.eval.prospective_freeze` and its `assert_runtime_boundary`). This
value has no bearing on, and is never required for, `pre_data_approval` /
ClinVar archive acquisition.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raptor.eval.prospective_freeze import (  # noqa: E402
    RESOURCE_MANIFEST_DIGEST_SCHEMA,
    RESOURCE_MANIFEST_ENTRIES,
    compute_resource_manifest_sha256,
    resource_manifest_entries,
)

#: The ops-documented default location of the three pinned checksum-manifest
#: files on the ADR-0008 x64 worker (`docs/ops/masked-heldout-bias-rerun-
#: handoff.md` §4, `configs/eval/core_annotation_bundle.yaml`
#: `x64_handoff_requirements.items[*].x64_path`).
DEFAULT_CHECKSUMS_DIR = r"D:\raptor-x64\CHECKSUMS"

_X64_MACHINE_NAMES = {"x86_64", "amd64"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--checksums-dir",
        type=Path,
        default=Path(DEFAULT_CHECKSUMS_DIR),
        help=f"Directory containing the three pinned checksum-manifest files (default: {DEFAULT_CHECKSUMS_DIR}).",
    )
    parser.add_argument(
        "--allow-non-x64-host",
        action="store_true",
        help="Bypass the x86_64 host check. For testing this script's own logic only -- "
        "never use this to produce a real ADR-0008 x64_freeze.resource_manifest_sha256 pin.",
    )
    args = parser.parse_args(argv)

    machine = platform.machine()
    if not args.allow_non_x64_host and machine.lower() not in _X64_MACHINE_NAMES:
        print(
            f"REFUSED: this host's platform.machine() == {machine!r}, not x86_64/AMD64. "
            "ADR-0008 requires this computation to be performed on the designated x64 worker "
            "(docs/DECISIONS.md ADR-0008); pass --allow-non-x64-host only to test this "
            "script's own logic, never to produce a real x64_freeze pin.",
            file=sys.stderr,
        )
        return 2

    try:
        entries = resource_manifest_entries(args.checksums_dir)
    except FileNotFoundError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    digest = compute_resource_manifest_sha256(args.checksums_dir)

    report = {
        "schema": RESOURCE_MANIFEST_DIGEST_SCHEMA,
        "checksums_dir": str(args.checksums_dir),
        "pinned_entry_order": [entry_id for entry_id, _ in RESOURCE_MANIFEST_ENTRIES],
        "manifests": entries,
        "resource_manifest_sha256": digest,
        "host_platform_machine": machine,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
