# Scope-specific research authorization gate (v2) — preregistration, status: not run

| Field | Value |
|---|---|
| Status | **Preregistration only, non-clinical, non-authoritative.** No real gate has been executed under this rule. No `data/census/*.json` result exists for it. |
| Date | 2026-07-14 |
| Track | `track/scope-specific-gate-2026-07` |
| Decision record | [`docs/DECISIONS.md` § ADR-0011](../DECISIONS.md) |
| Rubric cross-reference | [`docs/EVAL_RUBRIC.md` § 5b](../EVAL_RUBRIC.md) |
| v1 gate (unchanged) | [`src/raptor/eval/gate.py`](../../src/raptor/eval/gate.py) — `decide_gate`, single binding stratum (`missense`), short-circuits |
| v2 gate (new, additive) | [`src/raptor/eval/scope_gate.py`](../../src/raptor/eval/scope_gate.py) — `decide_scope_gate`, evaluates every scope, no short-circuit |
| Config (additive block) | [`configs/eval/tsc2.yaml`](../../configs/eval/tsc2.yaml) → `scope_authorization` (`schema_version: 2`) |
| v1 artifact (frozen, never relabeled) | [`data/census/tsc_masked_holdout_gate_2026-07-13.json`](../../data/census/tsc_masked_holdout_gate_2026-07-13.json) |

> **Reading rule.** This memo preregisters a scope-specific authorization *rule* before a corrected
> masked-holdout rerun executes it. It does not run a gate, does not classify or score any variant, does
> not approve any evidence or predictor policy, and does not change any locked threshold, direction,
> confidence level, minimum count, split, or Tavtigian point/cutoff in `configs/eval/tsc2.yaml`. It makes
> no PASS/VALIDATED claim about the corrected rerun.

---

## 1. What this preregisters

The v1 masked held-out gate (`decide_gate`, PRD-06) binds VUS authorization to a single stratum
(`missense`) and short-circuits: if missense fails, no other stratum's verdict is even reported. The
2026-07-13 v1 run is `status=FAIL, binding_stratum=missense, vus_authorized=false`. That design cannot
express — let alone independently authorize — a narrower, research-only claim scoped to
truncating-pathogenic alone, even though that run's own numbers already show truncating-pathogenic
clearing its locked 0.95/0.95 threshold at adequate coverage.

This document preregisters the **rule** that will govern how a future corrected rerun computes and
reports scope-specific verdicts, **before** that rerun executes, so that the rule cannot be shaped by
its outcome after the fact.

## 2. Exact contract

- **Enumerate, never short-circuit.** Every configured `(stratum, direction)` scope — currently
  `missense:pathogenic`, `missense:benign`, `truncating:pathogenic`, `truncating:benign` — plus the
  metrics-only `other` stratum is evaluated independently. A failing or underpowered scope never hides
  or suppresses the verdict of any other scope.
- **Two orthogonal axes per scope.** `metric_status` (`MET` / `UNMET` / `NO_THRESHOLD`) — did the 95%
  Clopper-Pearson lower bound clear its Oracle-registered threshold — and `coverage_adequate`
  (`True`/`False`) — did held-out coverage clear `min_count_per_class` — are computed and reported
  separately; neither is allowed to silently overwrite or hide the other.
- **Resolution rule.** `NO_THRESHOLD` → `DESCRIPTIVE` (never a fabricated threshold, never an
  authorization). `MET` + adequate coverage → `VALIDATED`. `MET` + inadequate coverage →
  `UNDERPOWERED` (never silently promoted to `VALIDATED`). `UNMET` → `FAIL` regardless of coverage
  (inadequate coverage is preserved/reported alongside the `FAIL`, never used to soften it).
- **`truncating:pathogenic`** can be independently `VALIDATED` only on the locked 0.95/0.95 lower
  bounds **and** adequate actual/called coverage — never on a pooled/`overall` metric.
- **`truncating:benign`** has no registered threshold in this preregistration. It reports
  `NO_THRESHOLD`/`DESCRIPTIVE` plus its coverage adequacy (inadequate, n=1, in the 2026-07-13 run) —
  never a fabricated threshold, never an authorization.
- **`missense:pathogenic` and `missense:benign`** each expose `metric_status` and `coverage_adequate`
  simultaneously and independently — one axis is never used to paper over the other.
- **`other`** is descriptive only, computed from metrics with no registered threshold.
- **Full-spectrum VUS authorization is semantics-locked** to require exactly
  `missense:pathogenic`, `missense:benign`, and `truncating:pathogenic` all `VALIDATED`
  (`configs/eval/tsc2.yaml` → `scope_authorization.full_spectrum.requires`). This cannot be narrowed
  post-hoc to drop missense.
- **A narrow, independent research flag**, `truncating_pathogenic_research_scope_validated`, can be
  `True` on `truncating:pathogenic` alone, without implying full-spectrum authorization.
- **Authorization/governance derive only from scope verdicts, never pooled `overall` metrics.**

## 3. Exact governance statement (verbatim, pinned)

> "Full-spectrum VUS automation is not authorized. Evidence supports only the validated
> truncating-pathogenic scope; missense remains unvalidated."

This exact text is pinned in `src/raptor/eval/config.py`
(`_PINNED_TRUNCATING_PATHOGENIC_ONLY_STATEMENT`) and validated on config load
(`ConfigError` if altered). It is emitted verbatim, never paraphrased, when the governance state
resolves to `TRUNCATING_PATHOGENIC_ONLY` (truncating-pathogenic validated, full-spectrum not).

## 4. Mandatory research-use disclaimer (verbatim, pinned, kept separate from the statement above)

> "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or
> ClinVar submission."

This is a **separate, mandatory, non-blank field** (`research_use_disclaimer`) on the config block,
the `ScopeGateDecision` model, report rendering/payload/hash, and the v2 aggregate — it is never
appended to or merged into the governance statement text, so it can never be truncated away
independently of that statement.

## 5. Known-outcome / cherry-picking risk — acknowledged, not hidden

This preregistration is **not blind** to the truncating-pathogenic outcome: the 2026-07-13 v1 run
already showed truncating-pathogenic clearing 0.95/0.95 at adequate coverage before this rule was
written. An auditor can fairly call adopting a truncating-only research scope after seeing that number
a form of post-hoc rule-making. This is accepted as a real, named limitation. Defensibility rests on:

1. **No threshold changed.** The truncating 0.95/0.95 precision/recall pair, `gating: true`, and
   direction were preregistered before the v1 run and remain locked; this track adds no new threshold
   and alters no existing one (`git diff` on `configs/eval/tsc2.yaml` shows only the additive
   `scope_authorization` block).
2. **The rule only narrows what a pass can mean** — explicitly research-only, explicitly non-clinical,
   never full-spectrum, never a VUS worklist or ClinVar submission authorization (§4 disclaimer).
3. **Full-spectrum authorization still requires missense** — the narrow flag cannot be exploited to
   substitute for or bypass the hard full-spectrum requirement (§2).
4. **A corrected rerun is required before any real authorization.** No `data/census/*.json` result is
   created by this track; no real gate is executed; the 2026-07-13 v1 artifact is never relabeled and
   carries no v2 keys (enforced by `tests/eval/test_scope_gate_v1_preservation.py`). Any VALIDATED/
   authorization claim requires a genuine corrected rerun under this preregistered rule, not this memo.

## 6. What this document is not

- **Not a retroactive relabel.** `data/census/tsc_masked_holdout_gate_2026-07-13.json` is byte-unchanged
  and remains `status=FAIL, binding_stratum=missense, vus_authorized=false`, v1 schema only.
- **Not an evidence-policy or predictor-policy approval.** No change to
  `configs/acmg/strength_policy.yaml`, `configs/acmg/tsc.yaml`, or
  `configs/eval/bp4pp3_predictor_policy.json` (which remains `pending`).
- **Not a PASS claim.** No scope is asserted `VALIDATED` by this document; verdicts are only computed
  when a real (currently unexecuted) masked-holdout run under this configuration produces metrics.
- **Not a README/PROGRAM status update.** Those are updated only after the corrected rerun actually
  executes and produces a genuine result — out of scope for this track.
