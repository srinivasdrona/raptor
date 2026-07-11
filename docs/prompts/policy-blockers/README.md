# RAPTOR policy blockers — sequenced three-slot contracts

Planning-only prompt suite (`planner`: `claude-opus-4.8`). Each decision (A–D) is a three-slot
contract: `slot1-planner.md` (role/intent + source-grounded defect statement), `slot2-*-contract.md`
(probes, public API, config, acceptance criteria), `slot3-preservation.md` (preservation + inversion
guards). `manifest.json` is the top rollup; each decision carries its own `manifest.json` with per-slot
`sha256`.

| Decision | Topic | Dir |
|---|---|---|
| A | BIAS BP4/PP3 predictor-aggregation defect | `A-bp4-pp3-aggregation/` |
| B | BS2 penetrance/age/mosaicism policy | `B-bs2-policy/` |
| C | Transcript (.4 vs .5) + 30 NTHL1 reconciliation | `C-transcript-nthl1/` |
| D | Unapproved production candidate-direction policy | `D-production-candidate-policy/` |

Sequence: A, B, C run in parallel (mutually independent); D depends on all three.

## Rubber-duck NO-GO closure — r1 (2026-07-12)

Prior verdict: `rubber_duck_NO_GO`. Two MAJOR findings closed; **planning artifacts only** — no
production/config/test code, no commit, no shared PROGRAM/STRATEGY/DECISIONS/RISK docs touched.

### MAJOR-A (decision A) — false correct-idiom proof removed

- **Finding.** Slot 1/2 and the A manifest claimed `pathogenic_classifiers.py` **L405–433** was a
  `get_pp3` **phyloP-window helper** implementing the correct idiom, and used it as **direct proof** that
  the L944/L491 blocks are defects. This is false: **L405–433 is `get_pm1`** (starts L384) — a *different
  criterion's* generic **domain** max-aggregation (`if score > best_score: best_score = score` at
  L429–430). It is **not** a `get_pp3`/phyloP helper and is **not** proof by itself.
- **Correction.** The `get_pm1` idiom is now cited **only** as corroborating context (the authors knew the
  correct max-aggregation pattern). Defecthood is grounded **primarily** in the two defective blocks'
  **own** code and comments:
  - `get_pp3` **L944–954** and `get_bp4` **L491–503**: `best_score` is named/commented ("Identify the best
    score…") and **intended** to hold the max, but is initialized to `0` and **never reassigned** in the
    selection loop (dead sentinel).
  - Downstream strength/tie logic proves the intent: `get_bp4`'s `if len(best_algs) > 1 and best_score > 1`
    (L499–500) is **permanently dead** (BP4 never bumps); `get_pp3`'s "if multiple classifiers agree on the
    same max score, increment by one" (L952–953) cannot detect a tie-at-max under the `>=` loop; and
    `score = a_score` under `>=` yields the **last** tool, not the max.
- **Updated:** `A-bp4-pp3-aggregation/slot1-planner.md`, `slot2-aggregation-contract.md`, `manifest.json`;
  **AC-A1** re-worded (proof from the two blocks themselves; `get_pm1` L405–433 = corroboration only).

### MAJOR-C (decision C) — active committed production-path defect (not hypothetical)

- **Finding.** Slot 1/2 framed the `.4` vs `.5` transcript misroute hypothetically ("a naïve enable
  would…", "(if enabled)"). It is a **currently active committed defect**: `configs/acmg/tsc.yaml`
  **already** sets `edge_cases.non_mane_transcript: true` (L95) with a **TSC2-only** `genes:` map pinned
  `NM_000548.5`; `BiasTsvSource.records` (`src/raptor/scorer/bias_source.py`) yields the **raw `.4`**
  transcript; and `pipeline.py` runs `check_out_of_scope_gene` then `check_edge_cases`. Running the current
  production pipeline on real `.4` BIAS rows misroutes the **entire TSC2 corpus** to `EDGE_CASE_ROUTED`
  (`.4 ≠ .5`) and **every TSC1 row** to `OUT_OF_SCOPE_GENE`. The census **30 NTHL1 manual** figure is a
  **separate** census-level analysis, **not** proof the pipeline routes correctly.
- **Correction.** Restated as active/committed (never "hypothetical"). Added **AC-C7** and **Probe 4**: a
  **mandatory regression** loading the **real committed config** + **representative real `.4` BIAS rows**
  through the **actual `BiasTsvSource → policy → pipeline`** path — first **demonstrating the baseline
  misroute**, then the **corrected** behavior (TSC2 `.4` scored in-scope via `reconciled_version_delta`),
  while the **30 NTHL1 manual rows are preserved** (`OUT_OF_SCOPE_GENE`, `excluded_from_scorer=True`).
- **Updated:** `C-transcript-nthl1/slot1-planner.md`, `slot2-reconciliation-contract.md`,
  `slot3-preservation.md`, `manifest.json`; **AC-C7** added, plus
  `tests/scorer/test_committed_pipeline_transcript_regression.py` authorized.

### Hashes

Per-slot `sha256` in `A-bp4-pp3-aggregation/manifest.json` and `C-transcript-nthl1/manifest.json` were
recomputed for every edited slot, and the top `manifest.json` `manifest_sha256` values for A and C were
updated to the new sub-manifest hashes.
