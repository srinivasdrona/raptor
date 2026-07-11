# Slot 2 — Gate-fidelity contract: public API, config, outputs, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the slot-1
> surfaces only**, before the doer. The doer implements to pass (may add, not weaken). Every threshold /
> power number is derived from `docs/EVAL_RUBRIC.md` §1–§3; the gate consumes GP-3's pre-registered
> values and never fits them.

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 Clopper-Pearson lower bound (the statistic to add)
For `k` successes in `n` calls, the exact (Clopper-Pearson) two-sided 95% CI **lower** bound is the Beta
quantile `Beta.ppf(alpha/2; k, n-k+1)` (0 when `k=0`), `alpha = 0.05`. The **gate compares this lower
bound**, not `k/n`, to the threshold. **Independent oracle:** `scipy.stats.beta.ppf` (a distinct
implementation from any hand-rolled incomplete-beta) **and** the EVAL_RUBRIC §2 anchor points
(scipy-exact, **corrected** — see below) — a 0.90 lower bound needs **n≥36** at 0 errors
(`LB(35,35)=0.89996756 < 0.90`), **n≥54** at ≤1, **n≥70** at ≤2; 0.95 needs **n≥72 / 110 / 142**; 0.99
needs **n≥368** (`LB(367,367)=0.98999890 < 0.99`). A test asserting `LB(36,36) ≥ 0.90 > LB(35,35)`,
`LB(72,72) ≥ 0.95 > LB(71,71)`, and `LB(368,368) ≥ 0.99 > LB(367,367)` pins each boundary. These
anchors come **directly from `scipy.stats.beta.ppf(0.025, k, n-k+1)`** (planner-verified); the prior
`n≥35 / n≥367` values (and the `n≥53 / 90 / 109 / 175 / 555 / 880` follow-ons) were off-by-N Beta-quantile
errors and are **not** retained via any invented tolerance (EVAL_RUBRIC §2 gets the narrow correction — §6).

### 0.2 Pre-registered per-stratum thresholds (EVAL_RUBRIC §1; consumed, never fit)
| Stratum | Metric·direction | 95%-CI lower-bound threshold | Powered? |
|---|---|---|---|
| **missense** (gating) | precision — both directions | **≥0.90** | yes (51 held-out P) |
| **missense** (gating) | recall — both directions | **≥0.85** | yes |
| **truncating** (secondary, hard-gated) | precision/recall — pathogenic | **≥0.95** | yes (210 held-out P) |
| **truncating** | benign direction | — | n=1, **report-only**, never gated |
| all strata | min held-out per class else `UNDERPOWERED` | **≥36** | — |

### 0.3 Gate honesty (preserved from PRD-06 FR6/AC5)
Empty `oracle_thresholds` → `UNVERIFIED` (never invent a target). A stratum below `min_count_per_class`
→ `UNDERPOWERED`, **never** `PASS`. `vus_authorized == (status == PASS)`. `PASS` requires the **missense**
stratum to clear **both directions** on the **lower bound** and be above min-count.

---

## 1. Public API (the test contract) — extend existing eval modules (additive, frozen dataclasses)

- **`src/raptor/eval/stats.py` (NEW)** — `clopper_pearson_lower(k: int, n: int, confidence=0.95) ->
  float`: exact Beta-quantile lower bound; `k=0 → 0.0`; `k=n → the one-sided lower bound`; `n=0 →` raises
  `InsufficientCountError` (never a silent 0). Pure, deterministic, no label input.
- **`src/raptor/eval/metrics.py` (extend)** — `Metrics` gains
  `precision_lb`, `recall_lb` (95%-CI lower bounds) alongside the existing point estimates + counts;
  `compute_metrics` populates them per stratum per direction using `clopper_pearson_lower`. The point
  estimate, `total_called`, `abstain`, and `gating` flag are unchanged. A below-`min_count_per_class`
  stratum keeps `gating=False`.
- **`src/raptor/eval/gate.py` (extend)** — `decide_gate(metrics, config)` now:
  - reads a **per-stratum** `oracle_thresholds` map (§2); missing/empty for the gating stratum →
    `UNVERIFIED`;
  - compares the **lower bound** (`precision_lb`/`recall_lb`) to the per-stratum/per-direction threshold;
  - `PASS` iff the **missense** stratum clears **both directions** (precision_lb ≥ 0.90, recall_lb ≥ 0.85)
    **and** is above min-count; a hard-gated **truncating** stratum below its ≥0.95 lower bound → `FAIL`
    (only where powered — truncating-benign n=1 is report-only, never gates);
  - below min-count on a gating stratum → `UNDERPOWERED`; `vus_authorized == (status == PASS)`.
  - `GateDecision` gains `per_stratum: dict[str, StratumVerdict]` (each `{precision_lb, recall_lb,
    threshold, met, gating, powered}`); existing fields preserved.
- **`src/raptor/eval/report.py` (extend)** — `EvalReport.render()` states, per stratum, the point
  estimate **and** the 95%-CI lower bound, the per-stratum threshold, and met/not-met/not-set;
  `content_hash()` still excludes run metadata. When the terminal run is `BLOCKED_POLICY` it renders the
  block reason + policy provenance and **no metric body** (no stratum table).
- **`src/raptor/eval/config.py` (extend — BREAKING nested-schema migration)** — see §2.1; the flat
  `oracle_thresholds` schema is **removed** in favour of the nested per-stratum map, and the
  `float(v)`-per-key coercion is replaced so no `float(dict)` path exists.
- **`src/raptor/eval/predictor_policy.py` (NEW)** — the final-gate prerequisite loader.
  `PredictorPolicy` (frozen: `schema`, `status`, `predictor_source_hash`, `correction_hash`,
  `decision_reference`, `approved: bool`) + `load_predictor_policy(path) -> PredictorPolicy` +
  `PredictorPolicyError`. Exact schema id `bp4pp3-predictor-policy`; only a well-formed artifact with
  `status == "approved"`, 64-hex `predictor_source_hash`/`correction_hash`, and a non-blank
  `decision_reference` yields `approved=True`. **Fail-closed:** missing file / wrong schema id /
  blank/unknown field / non-sha256 hash raises `PredictorPolicyError`; a well-formed non-approved
  artifact yields `approved=False`. This module carries **only** the external policy decision +
  provenance hashes — never an evidence, label, or scorer path.
- **`src/raptor/eval/model.py` (extend)** — `GateDecision.status` docstring enum gains `BLOCKED_POLICY`
  (emitted **only** by the terminal harness when the predictor-policy artifact is
  missing/unapproved/malformed; `decide_gate` never emits it). `vus_authorized` stays `False` for it.

No behaviour is removed; every change is an additive field + a lower-bound comparison replacing the
point-estimate comparison **at the gate boundary only**.

---

## 2. Config schema migration → `configs/eval/tsc2.yaml` + `src/raptor/eval/config.py` (BREAKING; values are GP-3's, unchanged)

`oracle_thresholds` migrates from a **flat** `{precision, recall}` map (`Mapping[str, float]`) to a
**nested per-stratum** map. This is a **backward-incompatible** schema change: the flat form is
**removed**, and `configs/eval/tsc2.yaml` **and** `EvalConfig` are migrated together in one commit. The
migration is **value-preserving** (missense stays 0.90/0.85; truncating 0.95/0.95 was already the
rubric's reported target — §5).

New pinned shape (values identical to the rubric — no post-hoc change):
```yaml
oracle_thresholds:
  confidence: 0.95            # Clopper-Pearson lower bound
  strata:
    missense:   {precision: 0.90, recall: 0.85, gating: true, directions: [pathogenic, benign]}
    truncating: {precision: 0.95, recall: 0.95, gating: true, directions: [pathogenic]}
min_count_per_class: 36       # CORRECTED Clopper-Pearson power floor (was 35; see §0.1 + AC-G4)
```

### 2.1 `src/raptor/eval/config.py` migration (authorized surface; no `float(dict)` failure)
- **Type change:** `EvalConfig.oracle_thresholds` becomes a nested mapping
  `{confidence: float, strata: {name: {precision: float, recall: float, gating: bool,
  directions: list[str]}}}` (was `Mapping[str, float]`). Downstream readers (`gate.py`) are migrated in
  the same change (§1).
- **Builder fix (the explicit `float(dict)` failure this removes):** the current final line
  `oracle_thresholds={str(k): float(v) for k, v in oracle_thresholds.items()}` would raise
  `TypeError: float() argument must be a string or a real number, not 'dict'` the moment a stratum value
  (a dict) is coerced. It is **replaced** by a nested-aware builder that coerces `confidence` and each
  stratum's `precision`/`recall` to `float`, `gating` to `bool`, and `directions` to `list[str]` —
  **never** calling `float()` on a stratum dict.
- **Validator rewrite** (`_validate_oracle_thresholds`, `_ORACLE_METRIC_KEYS`,
  `_ORACLE_REQUIRED_METRIC_KEYS`): an **empty** `{}` stays legitimate → `UNVERIFIED` (AC5/H13 preserved,
  the honest pre-Oracle state). A **non-empty** block MUST carry `confidence ∈ (0,1)` and a non-empty
  `strata` map; each stratum MUST have finite `precision`/`recall ∈ (0,1]`, a boolean `gating`, and an
  optional `directions ⊆ {pathogenic, benign}`; the **missense** gating stratum MUST be present. A
  malformed/partial block fails loud at load (`ConfigError`), never reaches the gate.
- **Pre-registration lock (R-A2):** a per-stratum value differing from the pinned rubric value
  (missense 0.90/0.85, truncating 0.95/0.95) raises `ConfigError`.
- `min_count_per_class` keeps its positive-int type check; only its pinned **VALUE** becomes **36** (§0.1).

### 2.2 Dependency — `pyproject.toml` (declare regardless)
Add `scipy>=1.10` to `[project].dependencies` (the exact-Beta oracle is `scipy.stats.beta.ppf`). scipy is
verified importable in the current env (**1.18.0**), but the dependency is **declared regardless** so the
gate never relies on an undeclared transitive import (GP-6). Availability check ≠ declaration.

### 2.3 Affected test surfaces (all migrated in the same change; no flat-schema path survives)
- `tests/eval/conftest.py::make_eval_config` — the empty `oracle_thresholds={}` default is **unchanged**
  (still valid → `UNVERIFIED`); any override passing a **flat** non-empty map is migrated to the nested
  shape.
- `tests/eval/test_ac5_gate.py` + `tests/eval/test_eval_fixes*.py` — every construction of a non-empty
  flat `oracle_thresholds` (or a config that reaches `decide_gate`/`load_config` with one) is migrated to
  the nested per-stratum shape; the old flat-key rejection assertions are re-expressed against the nested
  validator (bogus key, non-finite value, missing `precision`/`recall`, missing gating stratum).
- `configs/eval/tsc2.yaml` — migrated to the nested shape above (value-preserving; `min_count_per_class:
  36`).
- New `tests/eval/test_clopper_pearson_gate.py` uses **only** the nested schema.
No flat-schema code path or test remains; `float(dict)` is unreachable.

---

## 3. Acceptance criteria (→ OPERATING_MODEL §4 gates)

- **AC-G1 (mechanical) — Clopper-Pearson oracle (corrected anchors).** `clopper_pearson_lower` matches
  `scipy.stats.beta.ppf(0.025, k, n-k+1)` across a fixture grid and reproduces the **corrected**
  EVAL_RUBRIC §2 zero-error anchors: `LB(36,36) ≥ 0.90 > LB(35,35)`, `LB(72,72) ≥ 0.95 > LB(71,71)`,
  `LB(368,368) ≥ 0.99 > LB(367,367)`; `k=0 → 0`; `n=0 →` raises. The retired `n≥35` / `n≥367` anchors are
  proven wrong (`LB(35,35)=0.8999676 < 0.90`, `LB(367,367)=0.9899989 < 0.99`) and are **not** reintroduced
  via any tolerance.
- **AC-G2 (mechanical) — Gate uses the lower bound, not the point estimate.** A stratum whose **point
  estimate** clears the threshold but whose **lower bound** does not (small n) yields `FAIL`/`UNDERPOWERED`,
  never `PASS`; a stratum clearing the lower bound passes. A hand-built confusion matrix is the oracle.
- **AC-G3 (mechanical) — Per-stratum gating; missense binds.** `PASS` requires the **missense** stratum
  to clear both directions on the lower bound and be above min-count; a truncating-pathogenic lower bound
  below 0.95 (where powered) → `FAIL`; truncating-benign (n=1) is **report-only** and never changes the
  verdict.
- **AC-G4 (mechanical) — Gate honesty preserved.** Empty/missing gating-stratum threshold →
  `UNVERIFIED`; below `min_count_per_class` (now **36**, the corrected zero-error 0.90 power floor;
  `LB(35,35) < 0.90 ≤ LB(36,36)`) → `UNDERPOWERED`; neither is ever `PASS`; `vus_authorized ==
  (status == PASS)`.
- **AC-G5 (mechanical) — Pre-registration lock.** A config whose per-stratum threshold differs from the
  pinned rubric value is rejected by schema validation (no post-hoc threshold change; R-A2).
- **AC-G6 (mechanical) — Determinism + report.** `EvalReport.render()` states point estimate, 95%-CI
  lower bound, per-stratum threshold, and status; identical inputs → identical report + `content_hash()`
  (run metadata excluded).
- **AC-G7 (evidence-form; preservation) — Additive, no behaviour removed.** Existing `Metrics`/
  `GateDecision` fields + the flat-config path still function; `run_eval`'s signature and the harness
  label-blindness are unchanged.
- **AC-G8 (domain-truth; build the gate now, run later) — Final runner requires an approved
  predictor-policy artifact.** The terminal harness `scripts/run_masked_holdout_eval.py` **requires** a
  `--predictor-policy PATH` argument. That artifact is a `bp4pp3-predictor-policy`-schema document
  **supplied by the policy track (Track C)** with exact fields `{schema: "bp4pp3-predictor-policy",
  status, predictor_source_hash, correction_hash, decision_reference}`, loaded via
  `predictor_policy.load_predictor_policy` (fail-closed). If the artifact is **missing**, `status !=
  approved`, or **malformed** (wrong `schema` id, blank/unknown field, non-sha256 hash), the runner
  emits `GateDecision(status="BLOCKED_POLICY", vus_authorized=False)` and computes **no metrics** (no
  scoring, no report body — the leaky/unmasked TSV is *also* rejected by Arm B's lineage gate, an
  independent guard). Built + tested **now** against synthetic *approved* / *unapproved* / *malformed*
  fixtures; the real approved artifact **and** the masked TSV arrive at the deferred final run. This arm
  never encodes a default-allow or default-ban for BP4/PP3 (README policy-track).
- **AC-G9 (mechanical) — Predictor-policy loader is fail-closed.** `load_predictor_policy` returns an
  `approved=True` `PredictorPolicy` **only** for a well-formed artifact whose `schema ==
  "bp4pp3-predictor-policy"`, `status == "approved"`, with 64-hex `predictor_source_hash` /
  `correction_hash` and a non-blank `decision_reference`. A **missing** file / wrong schema id /
  blank/unknown field / non-sha256 hash raises `PredictorPolicyError`; a well-formed **non-approved**
  artifact yields `approved=False`. No default-allow: an absent, silent, or partial policy **never**
  authorizes. `PredictorPolicy` carries no evidence/label/scorer path. This closes the R-E1
  buildable-vs-validated split — the *gate mechanism* is validated now against synthetic artifacts; the
  *policy ruling itself* stays external (Track C).

---

## 4. Independent oracles (never the implementation's own output)

- **`scipy.stats.beta.ppf`** + the **corrected EVAL_RUBRIC §2 power table** anchor points (AC-G1) — a
  distinct Clopper-Pearson authority. The §2 table itself is narrowly corrected (§6) so the rubric and
  the test oracle agree on `n≥36 / 72 / 368`.
- **Hand-computed confusion matrices** (AC-G2/G3) for precision/recall counts.
- **The pinned rubric threshold values** (AC-G5) as the pre-registration oracle.
- **A synthetic `bp4pp3-predictor-policy` approved/unapproved/malformed fixture triplet** (AC-G8/G9) as
  the fail-closed policy-gate oracle — never a real Track-C artifact (which arrives at the deferred run).

## 5. Build-now vs policy-gated (the load-bearing split)

- **Build now:** `stats.py`, the `metrics.py`/`gate.py`/`report.py`/`model.py` extensions, the
  `config.py` **nested-schema migration** (+ the `float(dict)` fix, §2.1), the `pyproject.toml` scipy
  declaration (§2.2), the **corrected anchors + `min_count_per_class: 36`** (§0.1), the
  `predictor_policy.py` loader + `BLOCKED_POLICY` wiring in the terminal harness (validated against
  synthetic policy fixtures), and the narrow EVAL_RUBRIC §2 correction (§6). AC-G1..G9. Fully offline
  against synthetic label-free fixtures + independent oracles.
- **Policy-gated terminal step (NOT built now):** the final masked-rerun report + `PASS` decision + VUS
  authorization. It waits on **both** (i) the ADR-0009 masked comparator resources (Arm A + operator) and
  (ii) the **Track-C-supplied approved `bp4pp3-predictor-policy` artifact** (the Oracle BP4/PP3
  predictor-circularity ruling). Until both land, the terminal harness is honestly
  `BLOCKED_POLICY`/`UNVERIFIED` — never `PASS`. Threshold values stay GP-3's; this arm never fits them,
  and encodes no default-allow/ban for BP4/PP3.

## 6. Narrow EVAL_RUBRIC §2 factual correction (for integration, not a PROGRAM/STRATEGY edit)

`docs/EVAL_RUBRIC.md` §2's power table and the §1/§3/§5 numbers that cite it are off-by-N Beta-quantile
errors. The integration doer applies a **narrow** correction (authorized output), leaving all policy /
threshold values untouched:
- §2 table → `≥0.90: 36 / 54 / 70`, `≥0.95: 72 / 110 / 142`, `≥0.99: 368 / 555 / 720` (from
  `scipy.stats.beta.ppf(0.025, k, n-k+1)`).
- §1 "≥367 clean calls … for 0.99" → **≥368**; §1 table "Min held-out count per class ≥35" → **≥36**.
- §3a "≥ the 35 needed for a 0-error 0.90 lower bound" → **36**; "a single false call would need n ≥ 53"
  → **54**; §3b "`min_count_per_class` raised to 35" → **36**; §5 "`min_count_per_class: 35`" → **36**.
The **51 held-out missense-pathogenic** still clears the corrected floor of 36 (§3a power verdict
unchanged: powered for 0.90, tight — one error needs 54 — and 0.95 still out of reach). This is a
**mathematical correction, blind to held-out outcomes** — it does not touch `docs/PROGRAM.md` or
`docs/STRATEGY.md`.
