"""PRD-06 sec 10.3 `split.py` — the no-leakage train/dev vs held-out split
(FR2). A pure function of the benchmark rows + `config.split` (seed,
holdout_fraction): sorting by `variant_id` before shuffling makes the split
independent of input row order (R-A11 determinism), and the same variant
identity never spans both halves (AC2). Union of the two halves always
equals the input set exactly -- no drop, no duplicate (R-A10).
"""
from __future__ import annotations

import random
from collections import Counter
from typing import List, Tuple

from .config import EvalConfig
from .model import BenchmarkRow


class BenchmarkError(ValueError):
    """Raised when the input to `split_benchmark` is a malformed benchmark
    (e.g. a duplicate `variant_id`) -- a source-contract breach, never
    silently leaked across the split (MAJOR fix)."""


def split_benchmark(
    rows: List[BenchmarkRow], config: EvalConfig
) -> Tuple[List[BenchmarkRow], List[BenchmarkRow]]:
    """Deterministically split `rows` into (train_dev, holdout) (FR2).

    Deterministic under `config.split["seed"]`; a pure function of the row
    set (sorted by `variant_id` first) -- so identical input rows produce an
    identical split regardless of input ordering or how many times it is
    called (AC2/AC7).

    A benchmark must have exactly one row per variant identity: a duplicate
    `variant_id` is a malformed (source-contract-breaching) benchmark and
    fails loud here rather than risking the same identity landing in BOTH
    halves (leakage).
    """
    dup_counts = Counter(r.variant_id for r in rows)
    dups = sorted(vid for vid, count in dup_counts.items() if count > 1)
    if dups:
        raise BenchmarkError(
            f"split_benchmark received duplicate variant_id(s) {dups!r} -- "
            "a benchmark must have exactly one row per variant identity "
            "(source-contract breach; refusing to risk split leakage)"
        )

    seed = config.split["seed"]
    holdout_fraction = config.split["holdout_fraction"]

    sorted_rows = sorted(rows, key=lambda r: r.variant_id)
    n = len(sorted_rows)
    indices = list(range(n))
    rng = random.Random(seed)
    rng.shuffle(indices)

    n_holdout = round(n * holdout_fraction)
    holdout_positions = set(indices[:n_holdout])

    train_dev = [sorted_rows[i] for i in range(n) if i not in holdout_positions]
    holdout = [sorted_rows[i] for i in range(n) if i in holdout_positions]

    return train_dev, holdout
