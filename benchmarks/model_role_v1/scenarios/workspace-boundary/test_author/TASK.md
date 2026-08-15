# Test-author task

Author executable RED acceptance tests in `tests/` from `SPEC.yaml`. Do not
implement `src/solution.py`.

Your tests must distinguish resolved containment from lexical prefix checks,
exercise injected resolver escapes without creating real links, verify Windows
absolute/drive/UNC handling, and prove that every input receives exactly one
ordered disposition. Avoid platform-fragile assumptions.
