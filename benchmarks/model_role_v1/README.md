# RAPTOR model-role tournament corpus v1

This directory contains the **public, candidate-visible** half of the RAPTOR
model-role benchmark:

- the corpus manifest and scoring weights;
- three novel scenario families;
- role-specific task specifications, fixtures, starter code and seeded review
  candidates;
- the deterministic task materializer.

The benchmark runs in two phases:

1. **Individual-role evaluation.** Planner, test-author, doer and checker
   candidates are changed one role at a time. A repeated screen is followed by
   full-corpus runs for role finalists.
2. **Stack evaluation.** Only governance-valid combinations of role finalists
   are tested end to end.

## Embargoed evaluator

Reference implementations, mutants, hidden acceptance tests, answer keys and
the evaluator are deliberately **not present in the repository while candidate
runs are active**. A candidate able to read those files would invalidate the
benchmark.

After every candidate run is frozen, the evaluator bundle will be copied into
this directory with its pre-run hash manifest, and the blog will publish both
positive and negative results. Until then, every result record binds the
embargoed evaluator by SHA-256 without exposing its content.

See [`SCORING.md`](SCORING.md) for the exact scoring mechanism.

Phase 1 results are published in
[`docs/reference/model-role-phase1-results-2026-08.md`](../../docs/reference/model-role-phase1-results-2026-08.md)
with the machine record at
[`data/eval/model_role_phase1_result_2026-08-15.json`](../../data/eval/model_role_phase1_result_2026-08-15.json).
