from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHASE1 = ROOT.parent / "model_role_v1"
PHASE1_MATERIALIZER = PHASE1 / "materialize_task.py"


def copy_tree(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def materialize_base(scenario: str, role: str, output: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(PHASE1_MATERIALIZER),
            "--scenario",
            scenario,
            "--role",
            role,
            "--output",
            str(output),
        ],
        check=True,
    )


def update_run(output: Path, stack: str, scenario: str, run: int, stage: str) -> None:
    path = output / "RUN.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(
        {
            "schema": "raptor-model-role-phase2-stage-run-v1",
            "stack_id": stack,
            "scenario": scenario,
            "run_number": run,
            "stage": stage,
            "phase2_protocol": "benchmarks/model_role_phase2/RUN_PROTOCOL.yaml",
        }
    )
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument(
        "--stage", required=True, choices=["planner", "test_author", "doer", "checker"]
    )
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    cell = args.root.resolve() / args.stack / args.scenario / f"run-{args.run:02d}"
    output = cell / args.stage
    if output.exists():
        raise SystemExit(f"stage exists: {output}")
    materialize_base(args.scenario, args.stage, output)

    if args.stage == "test_author":
        shutil.copy2(cell / "planner" / "PLAN.yaml", output / "PLAN.yaml")
    elif args.stage == "doer":
        shutil.copy2(cell / "planner" / "PLAN.yaml", output / "PLAN.yaml")
        copy_tree(cell / "test_author" / "tests", output / "tests")
    elif args.stage == "checker":
        shutil.copy2(cell / "planner" / "PLAN.yaml", output / "PLAN.yaml")
        shutil.rmtree(output / "src")
        shutil.rmtree(output / "tests")
        copy_tree(cell / "doer" / "src", output / "src")
        copy_tree(cell / "doer" / "tests", output / "tests")

    update_run(output, args.stack, args.scenario, args.run, args.stage)
    print(output)


if __name__ == "__main__":
    main()
