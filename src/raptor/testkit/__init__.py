"""RAPTOR conformance kit — reusable, executable build-process invariants.

The recurring bug classes the checker keeps finding (silent drops, ungrounded
records, non-determinism, swallowed fail-loud, failed-run state mutation) are
encoded here ONCE as higher-order assertions + adversarial input generators.
Every data-pipeline module wires them via a `test_kit_conformance.py`, so the
checks run (and go red) automatically instead of relying on prompt-memory.

This is the "scoped closer" of the build-process hardening (todos:
kit-invariants, kit-generators, kit-retrofit, ci-gate). The findings registry +
promotion machinery + meta-tests + mypy gate are deferred (kit-catalog/
kit-promotion/kit-metatests/kit-mypy) until the module count grows.

Kept free of pytest imports so `src/` stays a clean library; assertions raise
plain `AssertionError`.
"""
from __future__ import annotations

from . import invariants

__all__ = ["invariants"]
