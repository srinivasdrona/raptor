"""PRD-06 — Benchmark & Evaluation Harness.

This is RAPTOR's eval-integrity boundary (category H): it builds a frozen,
best-available-labels benchmark (EVAL_PLAN sec 2), splits it without
leakage, combines the scorer's criterion calls into an eval-only implied
direction (never authoritative -- STRATEGY sec 9), computes class-stratified
metrics (missense reported separately, R-A2c), and gates any VUS run on the
result against Oracle pre-registered thresholds (GP-3/GP-9). Labels flow
ONLY through the benchmark builder (`benchmark.py`) -- the evidence path
(`combine.py`/`checks.py`, and anything the scorer touches) never sees a
label (FR8/AC6/H1).
"""
