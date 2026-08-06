#!/usr/bin/env python
"""Thin CLI adapter for the Atlas Phase-2 contrast-panel selector.

Resolves argv/env into explicit ``pathlib.Path`` inputs, reads the wall
clock exactly once, calls :func:`raptor.atlas.panel.select_panel`, and
writes the resulting run record to disk. This script intentionally holds
ALL of the impure, caller-only concerns (argv, environment, the wall
clock, stdout/stderr, and the run-record write) so that
``src/raptor/atlas/panel.py`` itself stays statically pure (PS-X-001):
no selection logic, constraint evaluation, ordering, repair, retry,
relaxation or budget escalation lives here, and a typed error is never
suppressed or reformatted into a success exit code. This adapter never
constructs, stubs or substitutes a ``RawIdentityMapper`` -- it passes
PATHS only; the mapper is loaded and verified by core alone under V7.

Exit codes:
    0  PANEL_SELECTED; run record written.
    1  the ``--out`` path already exists; refused, nothing was written
       or overwritten (spec gap G4 -- no code is pinned for this case).
    2  INFEASIBLE_PANEL or UNDETERMINED_SEARCH_INCOMPLETE; run record
       still written.
    3  a typed ``AtlasPanelError`` was raised; no panel, no run record
       with a panel. The offending ``code``/``check_id`` is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from raptor.atlas.model import AnchorSpec, AtlasPanelError, SelectionInputs
from raptor.atlas.panel import render_run_record, select_panel

CONTENT_ROOT_ENV_VAR = "RAPTOR_ATLAS_CONTENT_ROOT"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", required=True,
        help=(
            "explicit tracked-artifact containment root; no default -- "
            "the CLI never derives this from the working directory, git, or a supplied child path"
        ),
    )
    parser.add_argument("--protocol", required=True, help="path to the frozen protocol markdown")
    parser.add_argument("--registration", required=True, help="path to the panel-selection registration YAML")
    parser.add_argument("--pack", required=True, help="path to the live disease-pack manifest (pack.yaml)")
    parser.add_argument("--universe", required=True, help="path to the candidate-universe YAML")
    parser.add_argument("--raw-inventory", required=True, help="path to the raw discovery inventory YAML")
    parser.add_argument(
        "--content-root", default=None,
        help=(
            "external content root used to resolve --identity-map / "
            f"--identity-map-response-root when they are not absolute "
            f"(default: ${CONTENT_ROOT_ENV_VAR} if set)"
        ),
    )
    parser.add_argument(
        "--identity-map", required=True,
        help="path to the raw identity map (external, candidate-bearing; never defaulted)",
    )
    parser.add_argument(
        "--identity-map-response-root", required=True,
        help="root directory of the pinned official identity-map response bundle",
    )
    parser.add_argument("--anchor-spdi", required=True, help="the caller-supplied canonical anchor SPDI (E3)")
    parser.add_argument(
        "--anchor-residue", required=True, type=int, help="the caller-supplied anchor residue index (E3)",
    )
    parser.add_argument(
        "--executor-identity", required=True,
        help="identity recorded in run-record provenance; no default -- always caller-supplied",
    )
    parser.add_argument(
        "--node-budget-override", default=None, type=int,
        help="may only LOWER the registration's search node budget; a higher value is an input fault",
    )
    parser.add_argument(
        "--out", required=True,
        help="run-record output path; the CLI refuses to overwrite an existing file",
    )
    return parser


def _resolve_relative(raw: str, content_root: Optional[Path]) -> Path:
    path = Path(raw)
    if not path.is_absolute() and content_root is not None:
        path = content_root / path
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    out_path = Path(args.out)
    if out_path.exists():
        print(f"refusing to overwrite an existing run record: {out_path}", file=sys.stderr)
        raise SystemExit(1)

    content_root_raw = args.content_root or os.environ.get(CONTENT_ROOT_ENV_VAR)
    content_root = Path(content_root_raw) if content_root_raw else None

    inputs = SelectionInputs(
        repo_root=Path(args.repo_root),
        protocol_path=Path(args.protocol),
        registration_path=Path(args.registration),
        pack_path=Path(args.pack),
        universe_path=Path(args.universe),
        raw_inventory_path=Path(args.raw_inventory),
        anchor=AnchorSpec(spdi_canonical=args.anchor_spdi, residue_index=args.anchor_residue),
        run_started_at=datetime.now(timezone.utc),
        executor_identity=args.executor_identity,
        identity_map_path=_resolve_relative(args.identity_map, content_root),
        identity_map_response_root=_resolve_relative(args.identity_map_response_root, content_root),
        node_budget_override=args.node_budget_override,
    )

    try:
        run = select_panel(inputs)
    except AtlasPanelError as exc:
        print(f"{exc.code} {exc.check_id or ''}: {exc}".strip(), file=sys.stderr)
        raise SystemExit(3) from exc

    record = render_run_record(run, inputs=inputs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, sort_keys=True, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")

    print(
        f"terminal_outcome={run.terminal_outcome} "
        f"n_target={run.n_target} n_selected={run.n_selected} "
        f"run_record={out_path}"
    )

    if run.terminal_outcome == "PANEL_SELECTED":
        raise SystemExit(0)
    raise SystemExit(2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
