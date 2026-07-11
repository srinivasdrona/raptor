# Slot 2 — BP4/PP3 aggregation-defect contract: probes, public API, config, output, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the source
> surfaces in slot 1 only**, before the doer. The doer implements to pass (may add, not weaken). Every
> fact below is derived from the pinned BIAS source (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`,
> version `3.0.0`); each row cites a source anchor. Census counts are materiality annotations, never the
> oracle for the corrected strength.

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 The defect, stated as a spec deviation

BIAS's **intended** per-tool aggregation for PP3 and BP4 (per the inline comments and the ACMG "use once"
caveat):

```
score  = max(alg_to_score.values())               # single strongest tool
if (count of tools tied at that max) > 1: score += 1   # consensus bump
score  = min(score, cap)                           # cap = 3 (PP3), 4 (BP4)
```

BIAS's **actual** emitted behavior (source anchors below):

| Function | Anchor | Actual behavior |
|---|---|---|
| `get_pp3` | `pathogenic_classifiers.py` L944–954 | `best_score=0` never reassigned ⇒ `if a_score >= best_score` always true ⇒ `best_algs` = **all** fired tools; `score` = **last** tool in `pp3_tools` order (`phylop,revel,absplice,alphamissense`); `if len(best_algs) > 1: score += 1` bumps on **any ≥2 tools**; `min(score,3)` |
| `get_bp4` | `benign_classifiers.py` L491–503 | same `best_score=0`; `score` = **last** tool in `bp4_tools` order (`phylop,revel,dann,gerp,absplice,alphamissense`); bump guard `len(best_algs)>1 and best_score>1` ⇒ `best_score>1` **always false** ⇒ **no bump ever**; `min(score,4)`; single-supporting guard L501–502 `if len(alg_to_score)<2 and score==1: return 0,""`; label branch remaps `score==2 → 3` |

**Proof it is a defect, not intent (grounded in the two blocks themselves):** defecthood is established
*inside* L944–954 / L491–503, **not** by analogy to another function. (1) The variable is named `best_score`
and the loop comment says "Identify the best score and its algorithm(s)", but `best_score` is initialized
to `0` and **never reassigned** in the loop — a dead sentinel. (2) The downstream strength/tie logic
depends on `best_score` being the max, which is what fixes the intent: `get_bp4`'s
`if len(best_algs) > 1 and best_score > 1` (L499–500) is **permanently dead** (always false ⇒ BP4 never
bumps), and `get_pp3`'s "If multiple classifiers agree on the same max score, increment by one" (L952–953)
cannot detect a tie-at-max under the `>=` loop. (3) `score = a_score` under `>=` with no reassignment yields
the **last** tool, contradicting the stated max intent. The correct idiom
`if score > best_score: best_score = score` exists at `get_pm1` L405–433 — a **different criterion's**
generic domain max-aggregation — cited **only** as corroboration that the authors knew the pattern; it is
**not** a `get_pp3`/phyloP-window helper and is **not** proof by itself.

**Net observable effects:** (a) emitted strength is the *last-iterated* tool's strength, not the max
(order-dependent); (b) PP3 over-bumps (+1 on any ≥2 tools, even disagreeing); (c) BP4 never bumps (agreeing
tools add nothing); (d) PP3 vs BP4 are asymmetric despite identical intent.

### 0.2 The observable surface is information-bearing

Each fired PP3/BP4 rationale is `PP3[_{strength}]: N line(s)…; {w1} {tool1} {v1} | {w2} {tool2} {v2} | …`
(BP4 analogously). The emitted strength label uses `score_to_hum_readable` (`constants.py` L13–…:
`1→''/'supporting'`, `2→'moderate'`, `3→'strong'`, `4→'very-strong'`, `5→'stand-alone'`), and each
`printout_text` token carries the per-tool weight word ∈ {supporting, moderate, strong, very strong} and
its numeric value. The weight→score inverse (`supporting→1, moderate→2, strong→3, very strong→4`) is total,
so the per-tool `alg_to_score` is reconstructable from the rationale text — **this is what makes an
arm's-length wrapper feasible and is what Probe 3 must prove per-corpus, not assume.**

### 0.3 Lineage/disposition is out of scope of this correction

BP4 and PP3 are `label_independent_reference_or_predictor`, disposition `allowed`
(`configs/eval/bias_lineage.yaml`; slot-2 lineage §0.6). The aggregation correction changes **strength
only** — never lineage class, never direction (PP3 pathogenic / BP4 benign), never can-fire membership,
never disposition. No clinical classification is produced.

---

## 1. Empirical probes (built and run BEFORE the correction is trusted)

### 1.1 Probe 1 — intended-aggregation oracle (synthetic, offline)
`tests/eval/test_predictor_aggregation_oracle.py` (test-author owned): an independent pure spec
`intended_strength(per_tool_scores: Mapping[str,int], cap: int) -> int` implementing §0.1's intended
formula, driven over hand-enumerated `alg_to_score` vectors (single tool; two agreeing at max; two
disagreeing; three mixed; caps). For each vector it asserts the **emitted** BIAS behavior (§0.1 actual)
diverges from `intended_strength` exactly where predicted (e.g. `{phylop:2, revel:3}` ⇒ PP3 emitted = 3
[last=revel] +1 = 4 → capped 3; intended = 3 [max, no tie]; `{revel:3, dann:3}` for BP4 ⇒ emitted = 3
[last=dann], no bump; intended = 4 [tie at 3, +1]). Reproduces the defect deterministically from L944–954 /
L491–503 without importing `bias_2015`.

### 1.2 Probe 2 — real-corpus emitted-vs-corrected diff
`scripts/probe_predictor_aggregation.py <bias_output.tsv> --output <report.json>` (doer owned; run by the
checker over the census + held-out TSVs). For each fired PP3/BP4 it parses `printout_text`, reconstructs
`per_tool_scores`, computes corrected strength via §2.1, compares to the emitted strength int, and emits:
`{criterion, n_fired, n_emitted_ne_corrected, inflated, deflated, category_flips:{to_LP,to_LB,to_no_call},
undecidable, example_variant_ids (bounded, sorted)}`. **Counts are derived and recorded — never asserted
against a magic constant.** The census annotation (PP3 2226, BP4 3696; BP4-Strong-driven 92% LB coverage)
frames why this matters.

### 1.3 Probe 3 — information-completeness / decidability proof
Over the same corpora, prove **every** fired PP3/BP4 is *decidable* (its `per_tool_scores` fully
reconstructable from the rationale tokens; the weight→score inverse never fails). The report's
`undecidable` count is the decision input for §3: `undecidable == 0` ⇒ the wrapper can be faithful;
`undecidable > 0` ⇒ those rows force the upstream route (an undecidable row must **fail loud**, never be
emitted as if corrected).

---

## 2. Public API / config / output (the exact surface the doer builds)

> Smallest coherent eval-side surface. The scorer package never imports it; `parse_rationale` output is
> not mutated. No `bias_2015` import. No labels/benchmark reachable.

### 2.1 Config — `configs/eval/predictor_aggregation.yaml` (single source of truth, schema-validated)
- `bias_version: "3.0.0"`, `bias_commit: "ade13f206f3e2c2efe3ec92715d974645fc8da8f"`.
- `weight_to_score:` total map `{supporting:1, moderate:2, strong:3, "very strong":4}` (the reconstruction
  inverse; case-insensitive; no wildcard — schema rejects an unknown weight).
- `rule:` `{aggregation: max_plus_consensus, consensus_bump: 1, pp3: {cap: 3, bump_min_score: 1},
  bp4: {cap: 4, bump_min_score: 1, single_supporting_floor: true}}` — the *intended* spec, pinned in
  config, never hardcoded in code. (`bump_min_score` and `single_supporting_floor` are stated explicitly so
  the corrected rule is a deliberate, reviewable choice, not an accident; the doer must not silently import
  BIAS's asymmetry.)
- `tools:` `{pp3: [phylop, revel, absplice, alphamissense], bp4: [phylop, revel, dann, gerp, absplice,
  alphamissense]}` — mirrors `constants.py` `pp3_tools`/`bp4_tools` for parse validation only.

### 2.2 `src/raptor/eval/predictor_aggregation.py`
- `load_aggregation_spec(path) -> AggregationSpec` — fail-closed schema validation (unknown weight, tool,
  or rule key raises `AggregationSpecError`).
- `parse_per_tool_scores(criterion, rationale_text, spec) -> dict[str,int]` — reconstructs
  `per_tool_scores` from the `printout_text` tokens; raises `AggregationUndecidableError` when a token's
  weight ∉ `weight_to_score` or the strength label cannot be parsed (**never guesses / never returns a
  partial silently**).
- `recompute_strength(criterion, rationale_text, spec) -> AggregationCorrection` with fields
  `{criterion, emitted_strength: int, corrected_strength: int, per_tool_scores, consensus_applied: bool,
  decidable: bool, note}`. `emitted_strength` is round-tripped from the label (fidelity check);
  `corrected_strength` applies §2.1's rule. Pure function of `rationale_text` + `spec`; imports no
  `bias_2015`; reads no labels.
- The module **annotates**; it never overwrites `parse_rationale`'s / the scorer's emitted strength. Its
  output is consumed by decision D (candidate policy) and by the probe — not wired into scoring here.

### 2.3 Output — the persisted materiality report
`scripts/probe_predictor_aggregation.py` writes the §1.2/§1.3 report JSON (deterministic, sorted). It is
the empirical record that justifies §3's route decision; it is committed as data, not asserted to a
constant.

---

## 3. The correction-route decision (recorded, empirically justified)

| Probe 3 result | Route | Rationale |
|---|---|---|
| `undecidable == 0` (**expected** — §0.2) | **RAPTOR-side wrapper (§2.2) is primary** | The observable output is information-complete; the corrected strength is derived arm's-length; the pinned BIAS commit and the AGPL boundary are unchanged; no re-score/re-pin churn. |
| `undecidable > 0` | **Upstream contribution required for the undecidable class** | The wrapper cannot be faithful for those rows; the only correct fix is a source patch. |

In **both** cases the doer additionally records a documented, good-citizen **upstream PR proposal** against
`bitscopic/BIAS-2015` (fix `best_score` assignment at L944–954 / L491–503) in the report/notes — but this
task **does not** edit the vendored copy, change the pin, or adopt the upstream fix (adoption is gated on a
separate re-pin + full re-score + re-validation). The recorded decision names the empirical basis (the
Probe 3 `undecidable` count and the Probe 2 flip counts).

---

## 4. Acceptance criteria (AC-A1…AC-A7)

- **AC-A1** (defect oracle): Probe 1 reproduces emitted ≠ intended deterministically from synthetic
  vectors, matching the §0.1 anchors (L944–954 / L491–503). Defecthood is asserted **from those two blocks'
  own code and comments** — the dead `best_score` sentinel (init `0`, never reassigned), the
  permanently-false `best_score > 1` BP4 consensus guard, and the `>=`-loop last-tool resolution vs the
  "best score" / "same max score" comments — **not** from an external counter-example. The `get_pm1`
  L405–433 `if score > best_score: best_score = score` idiom may be referenced **only** as a *different
  criterion's* generic max-aggregation idiom (corroborating that the authors knew the pattern), **never** as
  a `get_pp3`/phyloP helper and **never** as proof by itself.
- **AC-A2** (round-trip fidelity + correction): `recompute_strength` reproduces BIAS's **emitted** strength
  from a rationale (parser fidelity) **and** the **corrected** strength per §2.1, for PP3 and BP4, over the
  enumerated vectors.
- **AC-A3** (real materiality): the Probe 2 report over the census + held-out TSVs records the derived
  correction counts and Tavtigian-category flips (no magic-constant assertion); the numbers are persisted.
- **AC-A4** (decidability / fail-loud): every fired PP3/BP4 in the corpora is decidable, or the row fails
  loud via `AggregationUndecidableError`; an undecidable rationale is **never** emitted as if corrected.
- **AC-A5** (arm's-length): no `bias_2015` import anywhere on the eval path; no edit to the vendored AGPL
  source; the pinned BIAS commit is byte-unchanged; no labels/benchmark/held-out file is reachable from
  `predictor_aggregation.py`.
- **AC-A6** (scope invariance): PP3/BP4 stay `label_independent_reference_or_predictor` / `allowed`; the
  correction changes strength only — never lineage, direction, membership, or disposition; **no clinical
  classification is produced**.
- **AC-A7** (recorded decision): the wrapper-vs-upstream route is recorded with its empirical justification
  (Probe 3 `undecidable`, Probe 2 flips); the upstream PR proposal is documented as external-only and does
  **not** alter the pin or the vendored source in this task.

---

## 5. DoR task specs (sequence)

1. `predictor-aggregation-spec` — `configs/eval/predictor_aggregation.yaml` + `load_aggregation_spec` +
   Probe 1 oracle (RED first).
2. `predictor-aggregation-wrapper` — `parse_per_tool_scores` + `recompute_strength` (fail-loud on
   undecidable), passing AC-A2/A4.
3. `predictor-aggregation-probe` — `scripts/probe_predictor_aggregation.py`, run over census + held-out,
   persist the report; record the route decision (AC-A3/A7).

## 6. Dependencies

- **Upstream:** none — decision A is independent (may run in parallel with B and C).
- **Downstream:** decision D consumes `recompute_strength` (corrected PP3/BP4 strength feeds the
  candidate-direction point map). The corrected strength must exist before D pins its points.

## 7. Authorized outputs (production surfaces this task's implementation may touch)

- `configs/eval/predictor_aggregation.yaml`
- `src/raptor/eval/predictor_aggregation.py`
- `scripts/probe_predictor_aggregation.py`
- `tests/eval/test_predictor_aggregation_oracle.py`, `tests/eval/test_predictor_aggregation_wrapper.py`
- the persisted probe report under `data/census/` (e.g. `tsc_predictor_aggregation_report_<date>.json`)

No other production/config/test file is edited. No test fixture is patched to hide the defect.
