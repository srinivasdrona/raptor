# Slot 1 — PRD-04 real TSC provisional calibration-batch planner (Opus)

You are the **Claude Opus 4.8 planner** for one authorized, minimal increment on top of the completed
PRD-04 packet library (source commit `7e03ca4`, branch `strategy/tsc-mtor-reset`). Plan a **real,
deterministic, provisional calibration batch** assembled from the pinned `clinvar_2026-07-07` TSC VUS
run and conforming to the PRD-04 packet schema. This is **selection / evidence review only, never
classification**. Do not write production code or executable tests; author the build/test contract
(slots 2/3 + manifest) only.

Emit an `INTENT` block before the contract that names the five GP-13 elements and points at existing
surfaces (`src/raptor/packet/**`, `src/raptor/scorer/**`, `src/raptor/eval/**`) rather than redesigning
them.

## INTENT (GP-13 named five)

| Element | This increment |
|---|---|
| **(a) TSC/mTOR user** | The TSC VCEP curator / qualified molecular geneticist (QMG) who needs a **calibration batch** — a small, provenance-complete, pattern-representative set of TSC1/TSC2 VUS packets — to calibrate the review workflow before any worklist is authorized. |
| **(b) Artifact** | A deterministic **real provisional calibration batch**: canonical packet JSONs + `FIRST_PASS` Markdown + queue CSV/JSONL + coverage JSON + a batch manifest (all source/code/config hashes + explicit limitations), written **outside the repo** under a required `--output-dir`; plus one **aggregate, non-identifying** source-of-record JSON committed under `data/census` after the real run. |
| **(c) Expert validator** | Mechanical checks (schema/hash/state/conservation/redaction) validate *form*; a QMG validates any externally meaningful disposition. This increment authorizes the **batch build**, never a release (STRATEGY Part I §9 two-sign-off). |
| **(d) Falsifier** | Any packet emits a candidate direction (must be `null` / `POLICY_BLOCKED`); OR source-of-record conservation drifts (≠ 6,618 manifest identities / BIAS rows, ≠ 238 LP + 1,333 LB queue, ≠ 20 LP + 10 LB = 30 patterns) without failing loud; OR the BIAS BP4/PP3 aggregation defect is silently corrected instead of pinned as a limitation; OR a BIAS row is emitted as primary evidence; OR the `FIRST_PASS` output or queue exposes a RAPTOR direction / census stratum / AAVC field; OR `implied_direction` is imported inside `src/raptor/packet`; OR a benchmark label / knowns / submission worklist is read; OR any output is non-deterministic, or a re-run is not byte-identical; OR patient data or a per-variant identity leaks into the `data/census` aggregate. |
| **(e) Why a generic product cannot supply it** | A generic ACMG/interpretation product emits calls; this batch is a TSC-calibrated, criterion-lineage-aware, leakage-safe, **direction-blinded**, conservation-asserted evidence-assembly artifact bound to the measured `clinvar_2026-07-07` census strata and the two-sign-off boundary — evidence *assembly + auditability*, not classification. |

## Hard boundaries (carry verbatim into slots 2/3)

1. **Direction stays null.** Every calibration packet keeps `candidate_direction = null`,
   `null_reason = production_policy_unapproved`, `review_state = POLICY_BLOCKED`. The script may reuse
   `raptor.eval.combine.implied_direction` **only outside `src/raptor/packet`** to reproduce the pinned
   census selection stratum + exact-strength pattern catalog; record the basis token
   `eval_only_census_selection_metadata`, never production policy.
2. **Conservation is asserted, fail-loud.** Before any output: exactly **6,618** manifest identities and
   BIAS rows; queue **238** `candidate_LP_review` + **1,333** `candidate_LB_review`; exactly **20** LP +
   **10** LB exact-strength patterns (**30** total). Any deviation raises and aborts. The known BIAS
   **BP4/PP3 aggregation defect** is an explicit, recorded batch **limitation/pin** — preserved as a
   contradiction + edge flag, **never silently corrected**.
3. **Every packet is provenance-complete.** Each packet carries every fired BIAS criterion, the
   machine-read lineage/disposition (from `configs/eval/bias_lineage.yaml`), exact `ScorerProvenance`
   with **real** input/output/raw-row sha256 + pinned BIAS/Nirvana versions, explicit **primary
   grounding = absent** (PS3/literature required but not present), canonical GRCh38 SPDI from the
   manifest, the MANE `.5` production identity, the raw BIAS transcript recorded in provenance, and the
   observed quality/edge flags. A BIAS row is **never** a `PrimaryEvidenceRef`.
4. **Selection via PRD-04.** Use `raptor.packet.queue.select_calibration_batch` over the full **1,571**
   candidate universe (238 LP + 1,333 LB packets). Coverage must prove all **30** patterns plus every
   observed gene / variant class / edge flag as **independent per-dimension** atoms — never a Cartesian
   product of empty cells. The batch may exceed 30 only to cover remaining atoms.
5. **Outputs outside repo.** Full artifacts go under a **required `--output-dir`** outside the repository,
   with **no patient data**: canonical packet JSONs, `FIRST_PASS` Markdown, queue CSV/JSONL, coverage
   JSON, and a batch manifest with all source/code/config hashes + limitations. Only an **aggregate,
   non-identifying** source-of-record JSON is committed under `data/census` after the real run.
6. **AAVC omitted from first batch** unless a separately pinned comparator input is provided; **no hidden
   web/network call**. The first-pass output contains neither a RAPTOR direction/stratum nor any AAVC
   field. The **operator** manifest may carry `census_selection_stratum`.
7. **No leakage.** No benchmark labels/knowns are read; no submission or public worklist is produced.

## Minimal authorized implementation (to be built later via the loop, not by this planner)

- `scripts/build_tsc_calibration_batch.py` — the only new script surface.
- `tests/packet/test_tsc_calibration_batch.py` — an independent synthetic oracle + an optional,
  env/path-gated real integration test.
- Optionally `configs/packet/calibration.yaml` — **only** if a genuinely separate config pin is needed
  (run-artifact paths / BIAS+Nirvana version pins); prefer reusing the existing `configs/packet/*.yaml`,
  `configs/acmg/tsc.yaml`, `configs/eval/tsc2.yaml`, and `configs/eval/bias_lineage.yaml`.

**Do not edit packet modules** unless a demonstrated missing reusable API blocks the script (record any
such gap as a blocker in slot 2, do not silently patch). Roles: **Gemini 3.1 Pro** authors tests first;
**Claude Sonnet 5** implements to pass them (may add, not weaken); **GPT-5.5** checks. The real run
occurs **after** the checker. Finish with a `VERIFICATION` block and exact diff scope. Do not stage,
commit, push, or modify unrelated files during planning.
