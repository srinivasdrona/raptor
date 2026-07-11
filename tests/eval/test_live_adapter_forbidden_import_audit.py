from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_ac_b6_b9_live_source_has_no_label_kb_or_agpl_imports() -> None:
    path = Path("src/raptor/eval/live_source.py")
    if not path.is_file():
        pytest.fail("live_source.py is not implemented")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {
        "raptor.eval.knowns",
        "raptor.eval.benchmark",
        "raptor.kb.store",
        "bias_2015",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in imported
        for blocked in forbidden
    )
