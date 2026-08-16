from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


CELLS = (
    ("DV-SONNET", "run-04"),
    ("DV-SONNET", "run-05"),
    ("DV-MAI", "run-02"),
    ("DV-MAI", "run-04"),
)
CANDIDATES = ("CC-OPUS-R2", "CC-GROK-R2")
IGNORED_PARTS = {".pytest_cache", "__pycache__"}


def included_file(path: Path, workspace: Path) -> bool:
    relative = path.relative_to(workspace)
    if path.name in {"VERDICT.yaml", "RUN.json"} or path.suffix in {".pyc", ".pyo"}:
        return False
    return not any(part in IGNORED_PARTS for part in relative.parts)


def file_hashes(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and included_file(path, workspace)
    }


def clean_copy(source: Path, target: Path, spec_path: Path, candidate: str, run: int) -> dict[str, str]:
    if target.exists():
        raise SystemExit(f"target already exists: {target}")
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("VERDICT.yaml", ".pytest_cache", "__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(spec_path, target / "SPEC.yaml")
    hashes = file_hashes(target)
    run_record = {
        "schema": "raptor-model-role-checker-comparison-rerun-stage-v1",
        "status": "MATERIALIZED_UNRUN",
        "comparison": "benchmarks/model_role_phase2/CHECKER_COMPARISON_RERUN.yaml",
        "candidate": candidate,
        "scenario": "registry-bridge",
        "run_number": run,
        "initial_file_sha256": hashes,
    }
    (target / "RUN.json").write_text(
        json.dumps(run_record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.v1_manifest.resolve().read_text(encoding="utf-8"))
    output_root = args.output_root.resolve()
    spec_path = args.spec.resolve()
    if output_root.exists():
        raise SystemExit(f"output root already exists: {output_root}")

    cells: dict[str, dict[str, object]] = {}
    try:
        for variant, run_name in CELLS:
            source_key = f"{variant}/registry-bridge/{run_name}"
            source = Path(manifest["cells"][source_key]["opus_workspace"])
            run = int(run_name.removeprefix("run-"))
            cell_record: dict[str, object] = {"source_v1_workspace": str(source)}
            expected_hashes: dict[str, str] | None = None
            for candidate in CANDIDATES:
                target = output_root / candidate / variant / "registry-bridge" / run_name
                hashes = clean_copy(source, target, spec_path, candidate, run)
                if expected_hashes is None:
                    expected_hashes = hashes
                elif hashes != expected_hashes:
                    raise SystemExit(f"candidate input mismatch: {source_key}")
                cell_record[candidate] = {
                    "workspace": str(target),
                    "candidate_visible_file_sha256": hashes,
                }
            cells[source_key] = cell_record
    except BaseException:
        if output_root.exists():
            shutil.rmtree(output_root)
        raise

    manifest_out = {
        "schema": "raptor-model-role-checker-comparison-rerun-input-manifest-v1",
        "status": "MATERIALIZED_UNRUN",
        "comparison": "benchmarks/model_role_phase2/CHECKER_COMPARISON_RERUN.yaml",
        "spec": "benchmarks/model_role_phase2/CHECKER_REGISTRY_SPEC_V2.yaml",
        "cell_count": len(cells),
        "candidate_count": len(CANDIDATES),
        "cells": cells,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "INPUT_MANIFEST.json"
    output.write_text(json.dumps(manifest_out, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
