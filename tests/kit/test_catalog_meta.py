"""Kit-promotion meta-test (checker-gate0).

Enforces the promotion catalog (`tests/kit/catalog.yaml`): a finding CLASS that has
recurred across >=2 modules is `promote`d to a kit invariant, and this test FAILS the
build if that invariant is missing or not wired into every module it applies to. This is
the machinery that stops recurring structural gates from being re-discovered at review:
once promoted, a gate is a permanent, enforced, cross-module invariant.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from raptor.testkit import invariants

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG = _REPO_ROOT / "tests" / "kit" / "catalog.yaml"


def _catalog() -> dict:
    return yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))


def _enforced_classes() -> list[dict]:
    return [c for c in _catalog()["classes"] if c["status"] in ("promote", "mandatory")]


def test_catalog_parses_and_defines_rule():
    cat = _catalog()
    assert cat["promotion_rule"]["promote"] == 2
    assert cat["promotion_rule"]["mandatory"] == 3
    assert {"scorer", "ingest", "eval", "knowns"} <= set(cat["kit_modules"])


def test_baseline_invariants_exist():
    for name in _catalog()["baseline_invariants"]:
        assert hasattr(invariants, name), (
            f"baseline invariant {name!r} is missing from raptor.testkit.invariants"
        )


@pytest.mark.parametrize("cls", _enforced_classes(), ids=lambda c: c["id"])
def test_promoted_class_invariant_exists(cls):
    """A promoted/mandatory class must name an invariant that exists in the kit."""
    inv = cls.get("invariant")
    assert inv, f"{cls['id']} is {cls['status']} but names no invariant"
    assert hasattr(invariants, inv), (
        f"{cls['id']} names invariant {inv!r} not defined in raptor.testkit.invariants"
    )


@pytest.mark.parametrize("cls", _enforced_classes(), ids=lambda c: c["id"])
def test_promoted_class_wired_in_all_applicable_modules(cls):
    """checker-gate0: a promoted class's invariant must be WIRED (referenced) in every
    `applies_to` module's conformance test -- a recurring gate can never be silently
    forgotten in a module it applies to."""
    cat = _catalog()
    inv = cls["invariant"]
    for module in cls["applies_to"]:
        rel = cat["kit_modules"].get(module)
        assert rel, f"{cls['id']} applies_to unknown module {module!r} (not in kit_modules)"
        path = _REPO_ROOT / rel
        assert path.is_file(), f"{cls['id']} applies_to {module} but conformance test {path} is missing"
        assert inv in path.read_text(encoding="utf-8"), (
            f"{cls['id']} ({cls['name']}) is {cls['status']} and applies_to {module}, but "
            f"{path.name} does not wire {inv!r} -- promoted invariants MUST be wired (checker-gate0)"
        )


@pytest.mark.parametrize("cls", _catalog()["classes"], ids=lambda c: c["id"])
def test_status_consistent_with_occurrences(cls):
    """Rule-of-2/3: `promote` needs >=2 independent module occurrences; `mandatory` >=3."""
    rule = _catalog()["promotion_rule"]
    n = len(set(cls["occurrences"]))
    if cls["status"] == "promote":
        assert n >= rule["promote"], f"{cls['id']} is promote but has {n} occurrence(s) (<{rule['promote']})"
    if cls["status"] == "mandatory":
        assert n >= rule["mandatory"], f"{cls['id']} is mandatory but has {n} occurrence(s) (<{rule['mandatory']})"
