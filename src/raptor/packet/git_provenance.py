"""Corrected all-VUS expert-review packet track (D6) -- shared git-provenance
helper.

Resolves the current code-commit provenance pin for the corrected run and
fails closed (never falls back to an `unknown`/abbreviated sentinel) on a
dirty working tree, a git invocation failure, or a non-full-40-hex commit.
Accepts an injected `run_cmd` callable (`run_cmd(cmd, **kwargs) ->
CompletedProcess`-like object with `.returncode`/`.stdout`) so tests can
exercise every failure mode without a real git repository.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Sequence

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")

#: This file's fixed location is `<repo>/src/raptor/packet/git_provenance.py`,
#: so the repo root is always this file's great-grandparent -- never the
#: caller's current working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class GitProvenanceError(RuntimeError):
    """`resolve_corrected_provenance` could not resolve a clean, full
    40-hex commit -- a dirty working tree, a git invocation failure, or an
    abbreviated/unresolvable commit. Never a silent `unknown` fallback."""


def resolve_corrected_provenance(
    *,
    run_cmd: Callable[..., object] = subprocess.run,
    cwd: str | Path | None = None,
) -> str:
    """Return the current commit as a lowercase full-40-hex string, or raise
    `GitProvenanceError`. Fails closed on: a dirty working tree (`git status
    --porcelain` produced any output), a failed git invocation
    (`returncode != 0`), or a resolved commit that is not exactly 40 lowercase
    hex characters (e.g. an abbreviated short SHA)."""
    resolved_cwd = Path(cwd) if cwd is not None else _REPO_ROOT

    status_cmd: Sequence[str] = ["git", "status", "--porcelain"]
    status_result = run_cmd(status_cmd, capture_output=True, text=True, cwd=resolved_cwd)
    if getattr(status_result, "returncode", 1) != 0:
        raise GitProvenanceError("failed to determine git working-tree status")
    if (getattr(status_result, "stdout", None) or "").strip():
        raise GitProvenanceError(
            "refusing to resolve code provenance on a dirty working tree "
            "(commit or stash local changes first)"
        )

    rev_cmd: Sequence[str] = ["git", "rev-parse", "HEAD"]
    rev_result = run_cmd(rev_cmd, capture_output=True, text=True, cwd=resolved_cwd)
    if getattr(rev_result, "returncode", 1) != 0:
        raise GitProvenanceError("failed to resolve the current git HEAD commit")

    commit = (getattr(rev_result, "stdout", None) or "").strip()
    if not _HEX40_RE.fullmatch(commit):
        raise GitProvenanceError(
            f"git HEAD did not resolve to a full lowercase 40-hex commit: {commit!r}"
        )
    return commit
