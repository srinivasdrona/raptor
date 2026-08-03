from __future__ import annotations

import os
from pathlib import Path
import pytest


def resolve_raptor_data_root(repo_root: Path) -> Path:
    # 1. RAPTOR_DATA_ROOT env var
    env_root = os.environ.get("RAPTOR_DATA_ROOT")
    if env_root:
        p = Path(env_root)
        if p.exists():
            return p
    # 2. main layout: repo_root.parent/raptor-data
    p_main = repo_root.parent / "raptor-data"
    if p_main.exists():
        return p_main
    # 3. worktree layout: repo_root.parent.parent/raptor-data
    p_worktree = repo_root.parent.parent / "raptor-data"
    if p_worktree.exists():
        return p_worktree
    raise FileNotFoundError(
        f"Could not resolve raptor-data root via RAPTOR_DATA_ROOT, "
        f"main layout ({p_main}), or worktree layout ({p_worktree})"
    )


def require_raptor_data_root(repo_root: Path) -> Path:
    """Resolve reference data or skip explicitly in offline CI.

    An explicitly configured but missing root is a broken environment and
    fails instead of silently skipping.
    """
    env_root = os.environ.get("RAPTOR_DATA_ROOT")
    if env_root and not Path(env_root).exists():
        pytest.fail(f"RAPTOR_DATA_ROOT does not exist: {env_root}")
    try:
        return resolve_raptor_data_root(repo_root)
    except FileNotFoundError as exc:
        pytest.skip(f"requires_reference: {exc}")


def test_resolver_with_synthetic_paths(tmp_path):
    # Proves the resolver works for both main and worktree layouts
    
    # 1. Simulate main layout
    # D:\AIProjects\raptor -> D:\AIProjects\raptor-data
    synthetic_ai_projects = tmp_path / "AIProjects"
    synthetic_raptor_main = synthetic_ai_projects / "raptor"
    synthetic_raptor_main.mkdir(parents=True)
    synthetic_data = synthetic_ai_projects / "raptor-data"
    synthetic_data.mkdir()
    
    # Test resolve_raptor_data_root with main layout
    resolved = resolve_raptor_data_root(synthetic_raptor_main)
    assert resolved.resolve() == synthetic_data.resolve()
    
    # 2. Simulate worktree layout
    # D:\AIProjects\raptor-worktrees\pp3-bp4-policy -> D:\AIProjects\raptor-data
    synthetic_raptor_wt = synthetic_ai_projects / "raptor-worktrees" / "pp3-bp4-policy"
    synthetic_raptor_wt.mkdir(parents=True)
    
    # Test resolve_raptor_data_root with worktree layout
    resolved_wt = resolve_raptor_data_root(synthetic_raptor_wt)
    assert resolved_wt.resolve() == synthetic_data.resolve()
