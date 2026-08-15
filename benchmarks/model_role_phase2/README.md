# RAPTOR model-role tournament: Phase 2

Phase 2 evaluates eight governance-valid finalist stacks end to end. Each stack
runs all three task families five times, producing 120 chained stack runs.

Within a run, stages are sequential because each consumes the prior artifact.
Different stack/scenario/run cells execute in parallel.

The checker receives the actual doer output. A `CLEAN` verdict is correct only
when the hidden implementation evaluator finds no material defect.

No Codex-doer stack is eligible because Codex did not pass the Phase 1 doer hard
gates reliably. A future sensitivity control may be registered separately, but
cannot win this tournament.
