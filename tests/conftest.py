"""Repo-wide pytest/hypothesis infrastructure config (not a test-contract file).

`tests/scorer/test_ac3_determinism.py` and `test_ac4_no_double_count.py`
(locked) use `@given(...)` together with the `fake_bias_source` fixture
from `tests/scorer/conftest.py` (also locked). That fixture is
function-scoped but stateless/pure (it just wraps whatever record list the
test body passes in per Hypothesis-generated example) -- current Hypothesis
versions flag any function-scoped fixture usage under `@given` as a
`FailedHealthCheck` regardless of whether the fixture actually carries
cross-example state, purely as a "this is often surprising" heuristic. This
suppresses that specific heuristic check globally rather than editing
either locked file.
"""
from __future__ import annotations

from hypothesis import HealthCheck, settings

settings.register_profile(
    "raptor-default", suppress_health_check=[HealthCheck.function_scoped_fixture]
)
settings.load_profile("raptor-default")
