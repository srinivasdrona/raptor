from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHASE1_MATERIALIZER = ROOT.parent / "model_role_v1" / "materialize_task.py"
VARIANTS = ("DV-SONNET", "DV-MAI")
SCENARIOS = ("registry-bridge", "snapshot-publisher", "workspace-boundary")
IGNORED_PARTS = {".pytest_cache", "__pycache__"}


def included_file(path: Path, workspace: Path) -> bool:
    relative = path.relative_to(workspace)
    if path.name == "VERDICT.yaml" or path.suffix == ".pyc":
        return False
    return not any(part in IGNORED_PARTS for part in relative.parts)


def file_hashes(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and included_file(path, workspace)
    }


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def materialize_cell(source_cell: Path, target: Path, scenario: str) -> dict[str, object]:
    source_checker = source_cell / "checker"
    source_verdict = source_checker / "VERDICT.yaml"
    if not source_verdict.is_file():
        raise SystemExit(f"missing Grok verdict: {source_verdict}")
    if target.exists():
        raise SystemExit(f"target already exists: {target}")

    subprocess.run(
        [
            sys.executable,
            str(PHASE1_MATERIALIZER),
            "--scenario",
            scenario,
            "--role",
            "checker",
            "--output",
            str(target),
        ],
        check=True,
    )
    shutil.copy2(source_cell / "planner" / "PLAN.yaml", target / "PLAN.yaml")
    copy_tree(source_cell / "doer" / "src", target / "src")
    copy_tree(source_cell / "doer" / "tests", target / "tests")
    shutil.copy2(source_checker / "RUN.json", target / "RUN.json")

    post_run_source_hashes = file_hashes(source_checker)
    canonical_hashes = file_hashes(target)
    created_by_grok = sorted(set(post_run_source_hashes) - set(canonical_hashes))
    deleted_by_grok = sorted(set(canonical_hashes) - set(post_run_source_hashes))
    changed_by_grok = sorted(
        path
        for path in set(post_run_source_hashes) & set(canonical_hashes)
        if post_run_source_hashes[path] != canonical_hashes[path]
    )

    return {
        "source_checker_workspace": str(source_checker),
        "opus_workspace": str(target),
        "canonical_candidate_visible_file_sha256": canonical_hashes,
        "grok_post_run_file_sha256": post_run_source_hashes,
        "grok_input_mutations": {
            "created": created_by_grok,
            "deleted": deleted_by_grok,
            "changed": changed_by_grok,
        },
        "grok_verdict_sha256": hashlib.sha256(source_verdict.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    opus_root = output_root / "CC-OPUS"
    if opus_root.exists():
        raise SystemExit(f"Opus arm already exists: {opus_root}")

    cells: dict[str, dict[str, object]] = {}
    try:
        for variant in VARIANTS:
            for scenario in SCENARIOS:
                for run in range(1, 6):
                    cell_id = f"{variant}/{scenario}/run-{run:02d}"
                    source_cell = source_root / variant / scenario / f"run-{run:02d}"
                    target = opus_root / variant / scenario / f"run-{run:02d}"
                    cells[cell_id] = materialize_cell(source_cell, target, scenario)
    except BaseException:
        if opus_root.exists():
            shutil.rmtree(opus_root)
        raise

    manifest = {
        "schema": "raptor-model-role-checker-comparison-input-manifest-v1",
        "status": "MATERIALIZED_UNRUN",
        "comparison": "benchmarks/model_role_phase2/CHECKER_COMPARISON.yaml",
        "source_root": str(source_root),
        "output_root": str(output_root),
        "cell_count": len(cells),
        "cells": cells,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "INPUT_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
