# Before the First Score: Building an Honest TSC Variant Benchmark

> **Status: pre-results engineering checkpoint — 2026-07-10.**
> RAPTOR has built the measurement instrument and the label-free path to a held-out exam of known
> TSC1/TSC2 variants. It has **not** measured precision or recall, has **not** passed any gate, has
> **not** classified the ~6,700 TSC variants of uncertain significance (VUS), and produces **no**
> clinically or genetically meaningful classification today. This post is a timestamp, not a result.

## Why publish before scoring?

The temptation in any evaluation project is to run the benchmark first and write about it afterward.
That order quietly invites a specific failure: once you have seen the score, every threshold, every
exclusion, and every "reasonable" definition can be nudged — usually unconsciously — until the number
looks good. The published story then reads as principle when it was really post-hoc rationalization.

So we are doing the opposite. This post pre-registers the exam **before** the first score exists. The
thresholds, the held-out split, the anti-leakage decisions, and the conditions under which RAPTOR
would *fail* its own gate are all committed to the repository now, blind to any performance number.
When the score does arrive, you will be able to check it against what was written here, unedited.

This is a direct application of RAPTOR's first guiding rule — *every layer declares its validation
ceiling; no output ships without stating what would falsify it* ([STRATEGY.md §5, GP-1](../STRATEGY.md)).
The point of publishing early is not to make retrospective storytelling impossible, but to make
later drift **detectable, auditable, and harder** to disguise as principle.

## What RAPTOR is building

RAPTOR turns public genetic and literature evidence into **auditable, cited evidence packets** for
TSC1/TSC2 variants — the two genes behind Tuberous Sclerosis Complex — plus a VCEP-style triage
worklist for human curators. It is explicitly **not** a diagnostic, a treatment-recommendation system,
or a regulated medical device ([STRATEGY.md §1](../STRATEGY.md)). Every output is designed to *inform a
qualified human*, never to replace one.

The scope boundary is binding, not a footnote. Medication recommendations, clinical decision support
for individual patients, and — critically — **any "final classification" without human sign-off** are
all out of scope ([STRATEGY.md §9](../STRATEGY.md)). An operator can approve internal pipeline records;
only a qualified molecular geneticist or VCEP can produce an externally meaningful classification. This
post therefore claims *engineering artifacts built*, and nothing about biological correctness.

## What is complete

These modules are built and signed off through the project's plan → build → review loop. "Built" here
means the code path exists, its tests pass, and a different-model-family checker reviewed it — **not**
that a live scoring run has happened ([PROGRAM.md health rollup](../PROGRAM.md)).

| Component | State | Reference |
|---|---|---|
| PRD-01 Tier-1/2 deterministic ACMG scorer (arm's-length BIAS port) | module built | `1d2444e` |
| PRD-02 variant ingestion & normalization | module built | `a889710` |
| PRD-03 KB schema & provenance ledger | module built | `b627073` |
| PRD-06 benchmark & evaluation harness (gates any VUS run) | built + pre-registered | `e026422` |
| PRD-07 ClinVar knowns → benchmark labels loader | module built | `499f479` |
| Kit-promotion machinery + ClinVar/HGVS parser corpus | live | `tests/kit/`, [corpus](../../tests/fixtures/clinvar_hgvs_golden.yaml) |
| Frozen ClinVar 2026-07-07 benchmark | frozen | `2e3477f` |
| Pre-registered thresholds / holdout | committed blind | `8662499` |
| x64 8-variant BIAS/Nirvana smoke test | operator-confirmed | `3556548` |
| PRD-08 Task A label-free VCF export | on feature branch | `4965104` |

Three items deserve emphasis before you read them as more than they are. The
`tests/fixtures/clinvar_hgvs_golden.yaml` file is a **parser/vocabulary corpus** — it exercises the
HGVS/ClinVar loader's ability to *read* variant notation correctly; it is not the model-performance
benchmark. The 8-variant BIAS/Nirvana run is a **smoke test**: eight variants, operator-confirmed to
pass an 18-column contract with identity preserved ([PROGRAM.md, Track B](../PROGRAM.md)). It is not a
"validated x64 pipeline," and calling it one would be a lie of scale. And the PRD-08 Task A export
below lives on `feature/prd08-live-eval-bridge` — it is **not yet merged or pushed to main**.

## The benchmark we actually have

The frozen known-variant benchmark is derived deterministically from a pinned ClinVar snapshot
(`clinvar_2026-07-07`, sha256 `5fe4fe10…5f4f37f`) by `scripts/build_tsc_benchmark.py`, with seed
`20260701` and a held-out fraction of `0.7`
([tsc_clinvar_2026-07-07_stats.json](../../data/benchmark/tsc_clinvar_2026-07-07_stats.json)).

After exclusions (conflicting, single-submitter, and low-review labels are **excluded from the
scored benchmark before splitting**, to prevent leakage), it contains **3,681 scoreable knowns**,
split into **2,577 held-out** and a **1,104 development reserve**. In the held-out exam, the gating stratum — **missense** — holds **51** pathogenic
and 103 benign calls; the **truncating** stratum holds **210** pathogenic and just **1** benign
([EVAL_RUBRIC.md §3](../EVAL_RUBRIC.md)).

A 70% held-out fraction looks aggressive until you remember what RAPTOR's Tier-1/2 engine is: a
**deterministic rule engine**. It learns *nothing* from the benchmark — it has no parameters fit to
these labels — so there is no training set to starve and no overfitting to protect against. The 30%
reserve is only a development and sanity set. Raising the held-out to 0.7 puts 51 pathogenic missense
calls in the exam, which is exactly what powers the primary bar (see below — noting that the current
gate checks point estimates rather than the rubric's Clopper-Pearson lower bound). There is **no
model-training penalty** for this, because the Tier-1/2 engine learns no benchmark parameters; the
explicit trade-off is only the smaller **1,104-variant development/sanity reserve**
([tsc2.yaml `split`](../../configs/eval/tsc2.yaml); [EVAL_RUBRIC.md §3b](../EVAL_RUBRIC.md)).

The pre-registered thresholds themselves are already committed, blind to any result: **precision ≥ 0.90
and recall ≥ 0.85 on the missense stratum, in both directions**, with a minimum of **35 held-out calls
per class** before a stratum may gate ([tsc2.yaml `oracle_thresholds`](../../configs/eval/tsc2.yaml)).
The 0.90 bar is not arbitrary: ACMG/AMP 2015 *defines* Likely Pathogenic as >90% posterior, and a
0.99 lower-bound claim would need ≥367 clean, zero-error calls per stratum — statistically
indefensible on any realistic TSC benchmark ([EVAL_RUBRIC.md §§1–2](../EVAL_RUBRIC.md)).

## What nearly produced a hollow green

The most instructive part of this checkpoint is a leak we caught before it could inflate a score.

The benchmark's labels come from ClinVar. Several ACMG criteria that the BIAS-2015 scorer can emit are,
it turns out, *derived from ClinVar itself* — so grading them against ClinVar-derived labels would be
reading the answer key. Two kinds surfaced. **Direct copy**, confirmed by the 8-variant TSC x64 BIAS
smoke output: PP5 ("reported pathogenic in ClinVar"), BP6 ("reported benign in ClinVar"), and —
discovered from BIAS v3.0.0's own rationale text — **PS4**, which for a rare Mendelian disorder falls
back to *counting ClinVar submitters* when no case-control data exists. **Transitive / aggregate**,
demonstrated by the repository's frozen real-BIAS scorer fixture: PM1, PM5, and PP2, which read
*other* variants' ClinVar data ([DECISIONS.md ADR-0009](../DECISIONS.md)).

The ruling, recorded as ADR-0009: **ban PP5, BP6, and PS4 outright** — structurally, in both eval and
production, so the gate measures the same classifier that ships. The transitive trio (PM1/PM5/PP2) is
**deferred**, not cleared: their real firing counts on the full held-out output are **UNVERIFIED**
until a mechanized ClinVar-derivation audit runs and the domain owner rules on them with numbers in
hand. Until that audit and ruling land, the terminal eval **remains blocked** — by design
([PROGRAM.md, active decisions](../PROGRAM.md)). Removing these circular criteria may move precision
and recall in *different* directions — it is not guaranteed to push measured performance in a single
conservative direction. The justification is the **validity of the measurement**, not a guaranteed
numeric direction of bias.

## The label-free exam boundary

For the exam to mean anything, the labels must not cross to the machine that scores the variants. That
is the anti-circularity boundary, and it is now enforced by code.

PRD-08 Task A ([PRD-08](../prd/PRD-08-live-eval-evidence-adapter.md)) exports all **2,577** held-out
identities as a deterministic, all-shape SPDI→VCF 4.2 file, paired with a bijective identity manifest.
Every canonical SPDI id round-trips through the real normalizer; the VCF and the manifest each carry
exactly **2,577** rows and **no truth fields** — no pathogenic/benign label travels with them. The
recorded local export outputs are:

- VCF sha256 `4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d`
- manifest sha256 `9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4`

These hashes are recorded here and in the out-of-repo provenance sidecar; they are reproducible only
with the pinned external ClinVar snapshot and reference inputs, which are intentionally not committed.

The export config pins the two accessions and their VCF contig order — TSC1 (`NC_000009.12`) before
TSC2 (`NC_000016.10`) — so the sort is deterministic, not accidental lexical order
([export.yaml](../../configs/eval/export.yaml)). What has **not** happened yet: the full BIAS scoring of
this VCF. The exam has been *handed out*; it has not been *taken*.

## The build process also failed — and improved

It would be dishonest to present the model-driven build loop as inherently reliable, so here is what
actually went wrong and what we did about it.

The loop is a plan → build → review cycle where the reviewer is always a *different model family* from
the builder ([PROGRAM.md operating model](../PROGRAM.md)). Whatever value it has came from catching real
defects, not from being magically correct. Multi-round checker passes repeatedly surfaced genuine issues.
Monolithic "author all the tests" prompts produced recurring fixture and contract misses. What
measurably improved the builder's first-pass quality was switching to **persisted, hashed three-slot
prompts** — the same mechanism that produced this very post. On the anchor-handling spec, a GPT checker
found a short-anchor gap that was then promoted into the PRD and locked with an independent RED
regression test before the fix.

The durable lesson is mechanization: the kit-promotion machinery converts recurring bug-classes into
enforced gates (for example, label-blindness and strict-whitelist invariants wired into modules, with
a meta-test that fails the build if a promoted invariant is left unwired). But most of the operating
controls are still **conventions or planned, not automated** — the honest-state ledger in
[OPERATING_MODEL.md §10](../OPERATING_MODEL.md) says so plainly: only "checker ≠ doer family" is live
today; the trace-cribbing lint, mutation testing, and post-merge audits are `planned`, and the prompt
manifest itself is a convention not yet validated by tooling. For Task A specifically, the recorded
evidence is: 21 targeted tests and 399 full-suite tests passing (1 skipped), the checker CLEAN, and the
real pinned-reference export conserving all 2,577 identities (local commit `4965104`; [PRD-08](../prd/PRD-08-live-eval-evidence-adapter.md)).
That is a statement about tests and identity conservation — not about biology.

## What this does not prove — the adversarial ledger

Read this section as the counterweight to everything above.

- **No held-out precision or recall exists yet.** No gate has returned a verdict. Metrics are `N/A`
  ([PROGRAM.md operations](../PROGRAM.md)).
- **ClinVar is a best-available proxy, not TSC expert-panel ground truth.** There is no ClinGen 3★ TSC
  VCEP panel in the frozen set; the labels are a proxy, and the validation ceiling says so
  ([STRATEGY.md §6](../STRATEGY.md); [EVAL_RUBRIC.md §6](../EVAL_RUBRIC.md)).
- **The class imbalance is real.** The truncating stratum has 210 pathogenic held-out calls against a
  single benign one; truncating-benign simply cannot be validated and is report-only, never gated
  ([EVAL_RUBRIC.md §3a](../EVAL_RUBRIC.md)).
- **The gate checks a point estimate, not the Clopper-Pearson lower bound** the rubric frames;
  `min_count_per_class: 35` is an approximating floor. Closing that gap is a tracked follow-up
  ([EVAL_RUBRIC.md §6](../EVAL_RUBRIC.md)).
- **Full x64 scoring of all 2,577 variants is pending**, as is the PM1/PM5/PP2 transitive-ClinVar
  ruling ([DECISIONS.md ADR-0009](../DECISIONS.md)).
- **No VUS run has occurred. No clinical claim is made. A qualified human remains required** for any
  externally meaningful classification ([STRATEGY.md §9](../STRATEGY.md)).

Nothing in this post should be read as evidence that RAPTOR classifies variants correctly. It shows
that specific artifacts were built, that tests and checks ran, and that the label-free export conserved
2,577 identities. It does not — and cannot — infer biological correctness or clinical utility from
those facts.

## The next falsifiable milestone

The path from here is single-threaded and explicit ([PROGRAM.md, path to first VUS run](../PROGRAM.md)):
score the label-free VCF on the x64 devbox (BIAS-2015 v3.0.0 + Nirvana) → run the ClinVar-derivation
audit on the full output to get real PM5/PM1/PP2 firing counts → obtain the Oracle ruling on the
transitive bucket → join through the canonical-SPDI adapter → run the terminal
[PRD-06](../prd/PRD-06-benchmark-eval-harness.md) held-out eval, which returns **PASS** or **FAIL**.

Only a PASS — missense, both directions, precision ≥ 0.90 and recall ≥ 0.85 — authorizes the first
~6,700-VUS run. And here is the falsifier stated in advance: **a FAIL authorizes no VUS run at all**.
It sends us back to re-examine the engine. That is the whole point of writing this before the score
exists — so that the next post, whichever way it goes, has to be honest.

---

### Sources & reproducibility

Strategy and scope: [STRATEGY.md](../STRATEGY.md) (§§1, 5, 6, 7, 9). Live status:
[PROGRAM.md](../PROGRAM.md). Pre-registered rubric: [EVAL_RUBRIC.md](../EVAL_RUBRIC.md) (§§1–6).
Decisions: [DECISIONS.md](../DECISIONS.md) (ADR-0007, ADR-0008, ADR-0009). Harness and adapter:
[PRD-06](../prd/PRD-06-benchmark-eval-harness.md), [PRD-08](../prd/PRD-08-live-eval-evidence-adapter.md).
Frozen benchmark stats: [tsc_clinvar_2026-07-07_stats.json](../../data/benchmark/tsc_clinvar_2026-07-07_stats.json).
Config pins: [tsc2.yaml](../../configs/eval/tsc2.yaml), [export.yaml](../../configs/eval/export.yaml).
Build-loop honesty ledger: [OPERATING_MODEL.md §10](../OPERATING_MODEL.md). Relevant commit history runs
through local `4965104` (Task A export, feature branch) and merged `2766e33` (ADR-0009). The full
label-bearing benchmark and the large annotation artifacts are kept out of the repository by design;
only aggregate statistics, pinned snapshot hashes, and reproducible scripts are committed.
