# Slot 3 — Real TSC calibration-batch preservation and inversion

## Preserve (byte-unchanged; the checker fails any diff that touches these)

- **PRD-04 packet library is frozen and reused, not edited.** `src/raptor/packet/**` (schema, `model.py`,
  `build.py`, `direction.py`, `hashing.py`, `render.py`, `queue.py`, `state.py`, `decisions.py`,
  `comparator.py`) and its tests remain byte-unchanged. The calibration script **imports** these public
  surfaces; it does not modify them. A demonstrated missing reusable API is a **blocker** recorded in
  slot 2, never a silent patch to a frozen module.
- **PRD-01 scorer stays criterion-level.** `src/raptor/scorer/**` is reused read-only
  (`BiasTsvSource`, `parse_rationale`, `load_config`); the script never re-derives ACMG thresholds or
  re-tiers the scorer.
- **PRD-06 combiner stays eval-only.** `src/raptor/eval/**` (esp. `combine.py::implied_direction`) is
  imported **only at script scope, outside `src/raptor/packet`**, and only to reproduce the census
  selection stratum / pattern catalog (basis `eval_only_census_selection_metadata`). It never becomes a
  production candidate-direction policy; the packet path imports no `eval.*` combiner, and every packet
  keeps `candidate_direction = null`.
- **BIAS lineage policy is read-only.** `configs/eval/bias_lineage.yaml` +
  `src/raptor/eval/lineage_policy.py` are consumed via `load_lineage_policy`; the script never edits the
  policy or invents lineage.
- **Benchmark/label/knowns files remain unreachable.** No PRD-06/PRD-07 held-out, labels, or knowns file
  is opened by the calibration path; inputs are the VUS-run manifest + BIAS output + provenance + census
  aggregates only. No submission or public worklist is produced.
- **Existing configs are reused, not rewritten.** `configs/acmg/tsc.yaml`, `configs/eval/tsc2.yaml`,
  `configs/packet/*.yaml` stay byte-unchanged; a **new** `configs/packet/calibration.yaml` is added only
  if a genuinely separate run-artifact/version pin is required.
- **No production, program, strategy, decisions, risk, or existing-PRD doc is modified** by this planning
  task. New code lands later, via the loop, only under `scripts/build_tsc_calibration_batch.py`,
  `tests/packet/test_tsc_calibration_batch.py`, and optionally `configs/packet/calibration.yaml`. The
  only in-repo data write is one **aggregate, non-identifying** JSON under `data/census`, committed after
  the real run + checker.

## Failure modes (invert every one in tests)

1. **False authority via a leaked direction.** A packet, `FIRST_PASS` render, or queue row exposes a
   RAPTOR `candidate_LP/LB` direction, signed points, policy id, or the `census_selection_stratum`, so a
   calibration artifact reads as a classification. **Fix:** every packet is `candidate_direction=null` /
   `null_reason=production_policy_unapproved` / `POLICY_BLOCKED`; the `FIRST_PASS` projection + queue are
   built via `redact_for_first_pass` and carry no direction/stratum/comparator; the census stratum lives
   only in the operator packet JSON + batch manifest. `implied_direction` is used **only** outside
   `src/raptor/packet` to reproduce the stratum, never to set a packet direction.
2. **Silent conservation drift.** The batch is emitted even though the reproduced strata no longer match
   the pinned census (row count ≠ 6,618, LP ≠ 238, LB ≠ 1,333, patterns ≠ 20 + 10), so a changed corpus
   is laundered as "the calibration batch." **Fix:** `assert_source_of_record_conservation` runs **before
   any output** and raises `ConservationError` (naming expected vs actual) on any drift; source
   hashes/versions are re-checked against census + provenance + audit pins.
3. **Silent BP4/PP3 correction.** The known BIAS aggregation defect (PP3 + BP4 both firing from correlated
   computational predictors) is quietly de-duplicated or one side dropped, hiding a real contradiction.
   **Fix:** both criteria are preserved with a `contradiction` + `bp4_pp3_computational_aggregation` edge
   flag and pinned as an explicit batch **limitation**; the defect is surfaced, never corrected.
4. **Provenance laundering.** (a) A BIAS raw row is passed off as **primary** evidence, or (b) primary
   grounding is silently marked present/not-required to unblock external readiness. **Fix:** every
   criterion carries exactly one real `ScorerProvenance` (a BIAS row, never a `PrimaryEvidenceRef`) with
   **real** input/output/raw-row sha256 + pinned BIAS/Nirvana versions + the raw BIAS transcript, and
   `primary_grounding=absent` (PS3/literature required-but-absent) — recorded, never hidden, and it keeps
   external readiness blocked.
5. **Coverage theater.** The selector "covers" impossible/unpopulated Cartesian cells, or misses an
   observed pattern/gene/class/edge flag, so the batch falsely claims full representativeness. **Fix:**
   `select_calibration_batch` covers **populated observed atoms per independent dimension only**;
   `assert_batch_coverage` fails loud unless all 30 patterns + every observed gene/class/edge flag are
   covered with an empty `missing` set and no impossible cell selected.
6. **Boundary/leakage breach.** Outputs land inside the repo, a per-variant SPDI or patient datum leaks
   into the committed `data/census` aggregate, an AAVC/network call is made without a pinned input, or a
   label/knowns file is read. **Fix:** `--output-dir` is required and refused inside the repo; the only
   in-repo write is the aggregate non-identifying JSON (no per-variant SPDI, no patient data); AAVC is
   omitted unless `--aavc-comparator` is given (no network); no benchmark/label/knowns file is opened.
7. **Non-determinism.** A re-run reorders packets, re-hashes, or emits differing bytes, so the batch is
   not reproducible. **Fix:** canonical JSON serialization (`sort_keys`, compact separators, UTF-8,
   trailing newline), packet-id ordering, and a pinned selection seed make every re-run byte-identical
   and input-order-invariant.
