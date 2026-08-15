# Test-author task

Author executable RED acceptance tests in `tests/` from `SPEC.yaml`. Do not
implement `src/solution.py`.

Your tests must distinguish a correct implementation from implementations that
skip the second source verification, write directly to the destination, emit
non-canonical JSON, overwrite an existing output on failure, or omit audit
fields/checks. Keep tests deterministic and standard-library-only apart from
pytest.
