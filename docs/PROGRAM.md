# RAPTOR PROGRAM STATUS

> Live status rollup. For *why* the project is shaped this way, see **[STRATEGY.md](STRATEGY.md)**
> (vision, scope, guiding policy), **[DECISIONS.md](DECISIONS.md)** (ADRs),
> **[ARCHITECTURE.md](ARCHITECTURE.md)** (runtime), and **[RISK_REGISTER.md](RISK_REGISTER.md)**
> (failure modes). This doc tracks *state*; those track *intent*.

> **Strategy status (2026-07-10 — vertical TSC/mTOR reset, [ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)).**
> The generic-platform *uniqueness* premise was falsified and horizontal/platform expansion is
> **frozen**; RAPTOR is now a **vertical TSC/mTOR research-evidence product** (candidate evidence
> packets · evidence/assay/contradiction atlas · gated mTOR hypothesis packets). The first complete
> **deterministic TSC1/TSC2 evidence census is done** (internal, eval-only, non-authoritative — below);
> the raw held-out benchmark has been **scored on pinned Nirvana/BIAS** (2,577 label-free records), but
> the **leakage-safe masked rerun and PRD-06 gate are complete**. The gate returned **FAIL** on the
> binding missense stratum (`vus_authorized=false`): pathogenic precision/recall lower bounds
> `0.6042/0.7131` and benign lower bounds `0.8378/0.7632` did not clear the pre-registered
> `0.90/0.85` thresholds. PM1 was excluded after a zero-support audit and remains unvalidated for
> production. No candidate direction is authoritative and no externally usable VUS worklist may be
> released.

## TSC VUS evidence census — COMPLETE (internal · eval-only · non-authoritative)

> Source of record: `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (snapshot `clinvar_2026-07-07`;
> pinned Nirvana **3.18.1** + BIAS-2015 **v3.0.0**). **These are candidate *directions* from the
> eval-only Tavtigian combiner, not classifications.** Do **not** call them reclassifications, and do
> **not** describe them as "24% VUS resolution."

- **Corpus:** **6,618** total VUS — **TSC1 2,249**, **TSC2 4,369**; by class **5,645 missense**,
  **893 other**, **80 truncating**.
- **Run integrity:** **6,618/6,618 scored** by the pinned Nirvana/BIAS pipeline; **zero** duplicate
  keys and **zero** parser-contract errors.
- **Current eval-only, internal, non-authoritative candidate directions:** **238** LP review ·
  **1,333** LB review · **5,017** unresolved · **30** annotation/manual. *(5,017 remain unresolved —
  the census resolves nothing on its own.)*
- **Missense-containing BIAS consequences:** 81 LP review · 1,196 LB review · 4,377 unresolved.
- **Predicted LoF:** 145 LP review · 2 unresolved.
- **Evidence-pattern compression (recorded in the census stats file under `candidate_pattern_compression`
  — a reproducible internal analysis, *not* validated truth, not a benchmark result):** the 238 LP candidates span **20** exact strength
  patterns, **six** of which cover 90%; the 1,333 LB candidates span **10** patterns, with
  **BP4 Strong + PM2 Supporting** covering **1,222 (92%)**.
- **Known gaps (from the stats file):** PS1/PM5 fired using ClinVar-derived comparator resources and — by
  static criterion lineage (ADR-0009) — PM1/PP2/BP1 depend on them too; all five need held-out masking for
  the leakage-safe validation bundle. *(The census itself used the **full** comparator resources —
  legitimate for non-authoritative VUS directions, but **not** leakage-safe for held-out validation.)*
  BS2 fired 34× and remains explicitly deferred with a cited penetrance/age/mosaicism rationale; PS3
  fired 46× and remains deferred pending assay-validity review. TSC1/TSC2 `.4→.5` transcript deltas now
  require manifest-supplied canonical SPDI proof; all 30 **NTHL1** records remain manual/out-of-scope.
  The BP4/PP3 aggregation defect has a deterministic arm's-length correction, but the joined production
  policy remains unapproved/null. **No externally usable candidate worklist may be released before leakage-safe
  validation + expert sign-off.**

## Operating Model — build loop

RAPTOR is built in a **design → build → review → eval → (back to design)** loop with a fixed
model-role split (see **[ADR-0003](DECISIONS.md#adr-0003--loop-operating-model-planner--doer--checker-across-three-model-families)**):

| Stage | Role | Model | Note |
|---|---|---|---|
| Design / plan | Planner | Claude Opus | writes task spec + acceptance criteria; no production code |
| Build | Doer | Claude Sonnet 5 | implements against the spec |
| Review / eval | Checker | GPT (5.x) | adversarial review vs acceptance criteria; pass or send back |

Rule: the **checker is always a different model family from the doer**; nothing is "done" until the
checker passes it against pre-stated acceptance criteria. *(Spec/verdict schema + gate automation are
pending `OPERATING_MODEL.md` — ADR-0003.)*

## Health Rollup

> *Module built ≠ live run executed.* The Tier-1/2 code path and the validation harness are **built and
> signed off**; the leakage-safe held-out set is **scored and gated**, and the gate returned **FAIL**,
> so no VUS classification is authorized.

- Tier 1/2 (Deterministic): 🟡 **MODULE BUILT; VALIDATION FAILED** (PRD-01 scorer `1d2444e`; arm's-length BIAS port) — *2,577-row masked gate completed; binding missense thresholds not met*
- **Evidence census:** ✅ **COMPLETE** (internal · eval-only · non-authoritative) — 6,618 VUS scored on pinned Nirvana/BIAS; candidate directions **not** classifications (see census section above)
- Tier 3 (LLM Extraction): 🔴 NOT STARTED (Phase 2)
- Consensus/Adjudication: 🔴 NOT STARTED
- Validation Framework: 🔴 **EXECUTED — FAIL** (canonical BIAS adapter; ClinVar masker/auditor;
  exact 95% Clopper-Pearson lower-bound, per-direction/per-stratum gate; fail-closed predictor-policy
  prerequisite) — *masked resources scored; missense lower bounds failed; `vus_authorized=false`*

## Operations (Current Run)

> The leakage-safe 2,577-variant held-out set has been scored and gated. Metrics below are
> evaluation-only; the binding result is **FAIL**.

- Last Batch Size: **2,577**
- Missense pathogenic precision: **0.8421** (95% lower bound **0.6042**, threshold **0.90**)
- Missense pathogenic recall: **0.9412** (95% lower bound **0.7131**, threshold **0.85**)
- Missense benign precision/recall lower bounds: **0.8378 / 0.7632**
- Suspended (Human Review): N/A

## Priorities (This Week) — validate the census, then build the candidate-packet contract

**Merged:** PR **#12** (Task A — label-free held-out export + pre-results checkpoint) at **`253c9fd`**.
The generic-platform roadmap is retired ([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy));
the vertical worklist below replaces it. **Census candidate directions stay non-authoritative until the
held-out gate PASSes.**

1. **BIAS criterion lineage — COMPLETE.** The pinned source-derived **28-slot / 19-can-fire / 9-internal-stub** policy, exact-set registry gate, total audit + fail-closed enforcement, and portable source-oracle fixture are implemented. Real 6,618-VUS and 2,577-held-out audits both block on **PS1/PM5**; zero firing does not clear the statically mask-required **PM1/PP2/BP1**. See `data/census/tsc_bias_lineage_audit_2026-07-10.json`.
2. **Held-out-masked BIAS validation bundle — COMPLETE; GATE FAIL.** Exact upstream masking removed
   2,577/2,577 identities with zero survivors; the canonical adapter joined 2,577/2,577 rows. Masked
   PS1/PM5/PP2/BP1 resources were regenerated and scored. PM1 had zero reachable rows in both published
   and reproduced resources, was explicitly skipped for this evaluation, and remains production-unvalidated.
3. **ClinVar audit — COMPLETE.** Direct-copy PS4/PP5/BP6 were suppressed; effective lineage blockers
   after the verified mask were zero. The terminal gate nevertheless failed the binding missense metrics.
4. **Canonical adapter — COMPLETE.** Arm's-length `BiasEvidenceSource` joins by canonical SPDI, enforces
   exact bijection/config parity/lineage preflight, and ignores BIAS's combined call.
5. **Clopper-Pearson gate — COMPLETE/EXECUTED: FAIL.** Exact 95% lower bounds; corrected zero-error
   floor 36; missense both directions and truncating-pathogenic hard-gated. The evaluation-only BP4/PP3
   policy was approved with pinned hashes; production policy remains unapproved.
6. **BS2 policy — COMPLETE/DEFERRED.** Real probe: 34 firings (TSC1 29/TSC2 5). Population-only BIAS
   evidence cannot satisfy a TSC-specific automated BS2 policy; BS2 remains deferred/not scored with
   a cited decision rationale. No approval invented.
7. **Transcript / NTHL1 resolution — COMPLETE WITH ADAPTER DEPENDENCY.** TSC1/TSC2 `.4→.5` version
   deltas reconcile only with verified canonical SPDI provenance; direct unenriched BIAS remains blocked.
   All 30 NTHL1 records stay `OUT_OF_SCOPE_GENE`.
8. **Production candidate policy — POPULATED, UNAPPROVED.** Corrected BP4/PP3 strengths plus allowed
   criteria are pinned; requires-mask/forbidden/deferred criteria are excluded. Cutoffs remain null,
   direction remains null, and packets remain `POLICY_BLOCKED`.
9. **PRD-04 evidence packet — BUILT.** The r3 contract and three sequenced implementations (core,
   deterministic render/queue/calibration surfaces, and state/decision/comparator workflow) are complete.
   Packets are immutable, direction-null/`POLICY_BLOCKED` while production policy is unapproved,
   first-pass double-blinded, and backed by a variant-scoped append-only decision log. Real calibration
   batch generation is complete: a real **30-packet / 30-pattern** calibration batch covers both genes,
   all observed classes and edge flags with no missing populated atoms. External use remains gated on validation, policy approval, and
   per-variant expert sign-off.
10. **Expert validation + named adopter** — recruit the validating oracle (GP-3) and name a first TSC adopter (R-F1/R-F6).
11. **ClinVar/VCEP preparation — COMPLETE (NO SUBMISSION).** PRD-09 pins the current
    `germlineSubmission/germlineClassification` shape, `clinvarDeletion` lifecycle, deny-list, schema
    freshness guard, institutional prerequisites, and an unreachable submission-authorization state.

> **Provisional packets now vs externally usable worklist after PASS:** items 1–8 and the PRD-04 output
> contract (item 9) proceed now, and provisional representative/all-VUS candidate packets may be built
> for internal review before expert sign-off; **releasing the full *externally usable* worklist waits
> for the PRD-06 held-out gate to return PASS** (missense-stratified, both directions ≥0.90 precision /
> ≥0.85 recall), the ADR-0009 policy correction, and leakage-safe expert sign-off.
>
> **Frozen (out of scope — ADR-0010):** **PRD-05** pipeline/generic orchestration and any **generic
> Tier-3 platform** work; generic ACMG-engine / literature-agent / NGS-platform expansion. *(TSC-specific,
> named-artifact Tier-3 work — e.g. TSC PS3/functional-assay extraction for the vertical atlas — is **not**
> frozen; it is permitted under GP-13.)*

## PRD backlog (feature specs — `docs/prd/`)

Per-feature PRDs, authored *just-in-time* for the feature about to be built (no speculative PRDs; no
index file until ≥3 exist).

| PRD | Feature | Phase | Status |
|---|---|---|---|
| PRD-01 | Tier-1/2 Deterministic ACMG Scorer | 1 | **Signed off · module built ✓** (`1d2444e`, 149 tests; arm's-length BIAS) |
| PRD-02 | Variant Ingestion & Normalization | 0 | **Signed off · module built ✓** (`a889710`, 125 tests) |
| PRD-03 | KB Schema & Provenance Ledger | 0 | **Signed off · module built ✓** (`b627073`) |
| PRD-04 | **Candidate Evidence Packet / Output Contract** (immutable evidence core; nullable candidate direction; deterministic first-pass render/queue; populated-atom calibration selector; variant-scoped review log; reveal-only comparator) | 1/2 | **Built ✓ — provisional/internal only** (42 packet tests; external worklist release gated on PRD-06 PASS + policy approval + per-variant sign-off) |
| PRD-05 | Pipeline & Orchestration skeleton | 0 | **frozen** — generic orchestration out of scope (ADR-0010) |
| PRD-06 | **Benchmark & Evaluation Harness** (build known-variant benchmark + train/dev/held-out split + P/R/concordance, class-stratified; **gates any VUS run**) | 1 | **Signed off · module built ✓** (`e026422`, PR #1, 222 tests; 7-round cross-family checker sign-off) |
| PRD-07 | **ClinVar Knowns → Benchmark Labels Loader** (Track A1: label-side `variant_summary` → `LabeledVariant` for PRD-06; reuses PRD-02 contract+normalizer; keeps scorer label-blind, H1) | 1 | **Signed off · module built ✓** (`499f479`, PR #3, 274 tests; 7-round checker sign-off) |
| PRD-09 | **ClinVar/VCEP Submission Preparation** (field/lifecycle mapping, source register, deny-list, no-submission controls; no network client/SCV) | external prep | **Prepared ✓ — no submission authorized** |

> **Validation gate (binding):** no classification is run on the ~6,700 TSC VUS until PRD-06 shows
> Tier-1/2 clears pre-registered thresholds on the **held-out known-variant** set — reported
> **stratified by variant class** (missense gated separately; R-A2c). See EVAL_PLAN §1.1.

## Path to first VUS run

The three parallel tracks (A benchmark · B x64 scoring infra · C oracle thresholds) are **done**. What
remains is the **terminal join**: the raw label-free held-out scoring run on x64 is **done** (2,577
parsed records on full comparator resources); still pending are the held-out-masked comparator-resource
regeneration + masked rerun and the Oracle/predictor-policy approvals, then the gated PRD-06 held-out
eval. Canonical adapter, exact statistical gate, static lineage gate, and full-output derivation audit
are complete (ADR-0009).

| # | Track | Type | Status |
|---|---|---|---|
| A | **Benchmark data** — real ClinVar TSC1/TSC2 *knowns* → frozen labeled benchmark (excl. conflicting/single-submitter/low-review; label hierarchy) | data | **DONE ✓** — frozen snapshot `clinvar_2026-07-07`; **3,681** scoreable knowns → **2,577** held-out / **1,104** dev reserve at `holdout 0.7` (PR #7 `2e3477f`, Track A2; A1 loader PRD-07 `499f479`) |
| B | **x64 live-scoring infra** — BIAS-2015 (arm's-length, ADR-0007) + Nirvana (x64-only, ADR-0008) | infra | **Smoke-tested ✓ (operator-confirmed)** — BIAS-2015 v3.0.0 + Nirvana 3.18.1 produced an 8-record TSV that passed `BiasTsvSource`'s 18-column contract with identity preserved. Large external artifacts intentionally out of repo; versions/hashes live in the operator's external reports (handoff bundle PR #8 `3556548`) |
| C | **Oracle thresholds (GP-3)** — pre-register precision/recall targets into `configs/eval/tsc2.yaml` | governance | **DONE ✓** — nested 95% lower-bound thresholds: missense 0.90/0.85 both directions; truncating 0.95 pathogenic; `min_count_per_class: 36`, `split.holdout_fraction: 0.7` |
| J | **Terminal join** — label-free held-out VCF masked, rescored, canonically joined, corrected and gated | code + eval | **DONE — FAIL** (`vus_authorized=false`; binding missense lower bounds below threshold; PM1 excluded/production-unvalidated) |

> A/B/C are complete and had **no code dependency on each other**. Thresholds are now pre-registered
> (C done), so the gate no longer reads `UNVERIFIED` for a missing target — the **raw** held-out score
> now exists. The leakage-safe masked rerun also exists and returned **FAIL**; the next step is
> missense error/abstention analysis and expert review, not threshold relaxation or VUS release.

## Active Decisions & Bottlenecks
- (Resolved 2026-07-10) **Strategy premise falsified → vertical TSC/mTOR reset** — generic-platform *uniqueness* premise withdrawn; horizontal/platform expansion **frozen**; RAPTOR repositioned as a vertical TSC/mTOR research-evidence product (candidate packets · atlas · gated mTOR hypotheses) — **ADR-0010**. Census (PR #12 `253c9fd`, `5a307df`) complete but **non-authoritative**; held-out gate still governs.
- (Resolved 2026-07-10) **AAVC prior-art boundary** — AAVC's September-2024 release contains 4,532 TSC VUS and 808 machine P/LP/B/LB calls. It is now a pinned **external disagreement comparator**, never a truth label or criterion source; all eight directional conflicts in the representation-matched overlap enter the expert calibration batch, with first-pass reviewers blinded to both machine directions until a logged reconciliation reveal. See [`reference/aavc-prior-art-audit-2026-07.md`](reference/aavc-prior-art-audit-2026-07.md).
- (Resolved 2026-07-08) Loop-engineering operating model → planner/doer/checker, see ADR-0003.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Resolved 2026-07-10) **ClinVar direct-copy circularity** → **PP5/BP6/PS4 banned** from `automatable_criteria` (eval == production; structurally rejected in `eval.config.FORBIDDEN_CRITERIA`); comparator-dependent **PS1/PM5/PM1/PP2/BP1 deferred** to the full-held-out audit (static criterion lineage — ADR-0009, PR #11 `2766e33`). Real BIAS v3.0.0 output showed PS4 falls back to counting ClinVar submitters for rare Mendelian variants.
- (Resolved 2026-07-10) **Full-output circularity audit** — machine-enforced 28/19/9 lineage policy + exact-set registry + fail-closed audit landed. Held-out incidence: PS1 116, PM5 13, PM1/PP2/BP1 0; the unmasked report blocks on PS1/PM5, while static lineage keeps all five in the masked-resource requirement. Oracle ruling + masked rerun remain on the terminal-join path (ADR-0009).
- (Resolved 2026-07-12) **Gate fidelity** — exact Clopper-Pearson lower bounds, corrected n=36 floor,
  pinned gating/direction semantics, and truncating-pathogenic 0.95 hard gate implemented.
- (Resolved 2026-07-13) **Masked terminal gate executed — FAIL** — 2,577/2,577 masked/canonical rows,
  zero effective lineage blockers, evaluation-only BP4/PP3 correction applied, PM1 explicitly excluded;
  binding missense lower bounds failed all four pre-registered pathogenic/benign precision/recall bars.
  No VUS scoring or external worklist is authorized.
- (Resolved 2026-07-12) **Policy blockers** — BP4/PP3 correction is fully decidable on both corpora;
  BS2 remains explicitly deferred; TSC1/TSC2 scope reconciles only with canonical proof; production
  point map is populated but unapproved/null.
- (Resolved 2026-07-12) **30-pattern calibration** — real 1,571-candidate universe compressed to 30
  first-pass packets covering every observed pattern/gene/class/edge flag; non-authoritative.
- (Resolved 2026-07-12) **ClinVar/VCEP preparation** — schema/lifecycle/source package complete;
  no contact, network submission, SCV, or authorization performed.
- (Open) **Loader GRCh38 assembly filter** — confirm the PRD-07 knowns loader strictly filters to the GRCh38 assembly (the freeze script already filters GRCh38+TSC1/TSC2; harden the loader-side guard).
- (Open) Cross-linkage oracle — recruit molecular geneticist before Phase 3 (STRATEGY.md GP-3; risk R-E1).
- (Open) Confirm worker vCPU allocation at deploy (EPYC/Xeon 8-vCPU VM vs full silicon).
- (Open) **Build core risk controls before trusting any automated output** — canary set, heartbeat/dead-man's switch, hard spend cap, source-contract tests, **answer-key/trace-cribbing lint, assertion-lock** (RISK_REGISTER.md §1; risks R-C1/R-A2/H1).
- (Open) ADR — reuse `biomcp` / `paper-search-mcp` MCP connectors for Tier-3 retrieval (ARCHITECTURE.md §8; gated on GP-10/GP-9).
- (Resolved 2026-07-11) **PRD-04 packet contract + implementation** — r3 contract passed two rubber-duck rounds; core/surfaces/workflow landed with first-pass double-blinding, exact lineage precedence, strict two-level provenance, immutable hash domains, populated-atom selection, variant-scoped append-only decisions, and decision-before-comparator-reveal. Real 30-pattern calibration generation remains next. **PRD-05 (pipeline & generic orchestration) stays frozen** as generic/out-of-scope (ADR-0010).
- (Resolved) **Reference-data reproducibility (R-A11):** committed `scripts/fetch_reference.py`
  fetch-and-verify utility (`a80f759`, PR #2) so a fresh clone can reproduce the local pinned
  reference (chr9 `NC_000009.12` + chr16 `NC_000016.10`), checksums pinned in `configs/ingest/tsc.yaml`.
  AC3 `requires_reference` tests still skip on CI without the local data (expected).
- (Open) **Build-process hardening (in progress):** conformance kit + **promotion machinery LIVE** —
  `tests/kit/catalog.yaml` (findings registry, rule-of-2/3) + promoted invariants C1 (strict-whitelist
  `assert_never_emits`) / C2 (label-blindness `assert_no_label_leak`) wired into modules +
  `tests/kit/test_catalog_meta.py` (checker-gate0: fails the build if a promoted invariant is unwired).
  **ClinVar/HGVS golden corpus** (`tests/fixtures/clinvar_hgvs_golden.yaml` + cited
  `docs/reference/clinvar-hgvs-golden-corpus.md`) is the full-vocabulary loader oracle — it caught a
  real bare-`p.` parser bug on wiring. Remaining: kit-mypy (type gate), strict-first spec standard,
  C3 provenance promotion. Turns recurring bug-classes into *enforced* gates.
- (Open) **Environment:** Python 3.12.10 on Windows; **WSL2 Ubuntu 24.04.4 LTS (aarch64) ready**, venv **`raptor`** at `~/raptor` (Python 3.12.3, pytest 9.1.1, gcc 13.3/make). Code lives at `/mnt/d/AIProjects/raptor`; venv on Linux fs. Modules built via plan/build/check: **PRD-03 ✓, PRD-02 ✓, PRD-01 ✓, PRD-06 ✓, PRD-07 ✓ (all signed
  off)**; CI gate live ✓; reference-fetch script ✓. The three parallel non-code tracks are now **done**
  — (A) real ClinVar knowns benchmark frozen (`2e3477f`), (B) BIAS-2015 v3.0.0 + Nirvana smoke-tested
  on the x64 devbox (operator-confirmed, ADR-0008), (C) Oracle thresholds pre-registered (`8662499`).
  Next: the **terminal join** (see *Path to first VUS run* / *Priorities*) — the raw label-free held-out
  VCF is already scored on x64 (2,577 parsed records, full resources); remaining are the held-out-masked
  comparator-resource regeneration + masked rerun, the canonical eval `EvidenceSource` adapter +
  ClinVar-derivation audit, the Oracle ruling on PS1/PM5/PM1/PP2/BP1, then the gated PRD-06 held-out eval.
  Deferred: conformance-kit
  *governance* (kit-mypy/strict-first/C3 provenance/gate-0); PRD-04/05; cross-machine fleet.
