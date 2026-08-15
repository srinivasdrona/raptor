from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCENARIOS = ROOT / "scenarios"


def copy_tree(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def materialize(scenario: str, role: str, output: Path) -> None:
    source = SCENARIOS / scenario
    if not source.is_dir():
        raise SystemExit(f"unknown scenario: {scenario}")
    if role not in {"planner", "test_author", "doer", "checker"}:
        raise SystemExit(f"unknown role: {role}")
    if output.exists():
        raise SystemExit(f"output already exists: {output}")

    output.mkdir(parents=True)
    copy_tree(source / "artifacts", output / "artifacts")

    if role == "planner":
        shutil.copy2(source / "planner" / "BRIEF.md", output / "BRIEF.md")
        shutil.copy2(source / "planner" / "OUTPUT_SCHEMA.yaml", output / "OUTPUT_SCHEMA.yaml")
    else:
        shutil.copy2(source / "common" / "SPEC.yaml", output / "SPEC.yaml")

    if role == "test_author":
        copy_tree(source / "starter" / "src", output / "src")
        (output / "tests").mkdir()
        shutil.copy2(source / "test_author" / "TASK.md", output / "TASK.md")
    elif role == "doer":
        copy_tree(source / "starter" / "src", output / "src")
        copy_tree(source / "visible_tests" / "tests", output / "tests")
        shutil.copy2(source / "doer" / "TASK.md", output / "TASK.md")
    elif role == "checker":
        copy_tree(source / "checker" / "src", output / "src")
        copy_tree(source / "checker" / "tests", output / "tests")
        shutil.copy2(source / "checker" / "TASK.md", output / "TASK.md")
        shutil.copy2(source / "checker" / "OUTPUT_SCHEMA.yaml", output / "OUTPUT_SCHEMA.yaml")

    hashes = {}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            relative = path.relative_to(output).as_posix()
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    run = {
        "schema": "raptor-model-role-run-v1",
        "scenario": scenario,
        "role": role,
        "status": "MATERIALIZED_UNRUN",
        "initial_file_sha256": hashes,
    }
    (output / "RUN.json").write_text(
        json.dumps(run, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    materialize(args.scenario, args.role, args.output.resolve())


if __name__ == "__main__":
    main()
