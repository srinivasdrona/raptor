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
> the **leakage-safe masked rerun and PRD-06 gate are still pending**, so no candidate direction is
> authoritative and no externally usable VUS worklist may be released.

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
  BS2 fired 34× and is explicitly deferred pending a TSC penetrance/age/mosaicism decision; PS3 fired
  46× and is deferred pending assay-validity review; 30 TSC2-region inputs annotated as **NTHL1** need manual
  resolution; BIAS emits transcript `.4` while production pins `.5`; the production scorer currently
  scopes to TSC2 only. **No externally usable candidate worklist may be released before leakage-safe
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
> signed off**; the raw held-out set is **scored**, but the **leakage-safe masked rerun + gate have not
> yet been run**, so no VUS classification is authorized.

- Tier 1/2 (Deterministic): 🟡 **MODULE BUILT** (PRD-01 scorer `1d2444e`; arm's-length BIAS port) — *raw x64 held-out scoring done (2,577 records, full resources); leakage-safe masked rerun + gate pending*
- **Evidence census:** ✅ **COMPLETE** (internal · eval-only · non-authoritative) — 6,618 VUS scored on pinned Nirvana/BIAS; candidate directions **not** classifications (see census section above)
- Tier 3 (LLM Extraction): 🔴 NOT STARTED (Phase 2)
- Consensus/Adjudication: 🔴 NOT STARTED
- Validation Framework: 🟡 **BUILT + PRE-REGISTERED** (PRD-06 harness `e026422`, PRD-07 loader `499f479`, frozen benchmark `2e3477f`, thresholds `8662499`) — *raw held-out scored; masked rerun + gate not yet run*

## Operations (Current Run)

> The raw 2,577-variant held-out set **has been scored** on pinned Nirvana/BIAS (2,577 parsed unique
> records), but precision/recall stay **N/A** — they require the leakage-safe masked rerun + PRD-06 gate,
> not merely a raw score.

- Last Batch Size: N/A
- Precision: N/A
- Recall: N/A
- Suspended (Human Review): N/A

## Priorities (This Week) — validate the census, then build the candidate-packet contract

**Merged:** PR **#12** (Task A — label-free held-out export + pre-results checkpoint) at **`253c9fd`**.
The generic-platform roadmap is retired ([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy));
the vertical worklist below replaces it. **Census candidate directions stay non-authoritative until the
held-out gate PASSes.**

1. **BIAS criterion lineage — COMPLETE.** The pinned source-derived **28-slot / 19-can-fire / 9-internal-stub** policy, exact-set registry gate, total audit + fail-closed enforcement, and portable source-oracle fixture are implemented. Real 6,618-VUS and 2,577-held-out audits both block on **PS1/PM5**; zero firing does not clear the statically mask-required **PM1/PP2/BP1**. See `data/census/tsc_bias_lineage_audit_2026-07-10.json`.
2. **Held-out-masked BIAS validation bundle** — the label-free held-out VCF was already emitted and scored on the x64 worker (BIAS-2015 v3.0.0 + Nirvana; 2,577 parsed records; ADR-0008; H1 no-labels boundary) using the **full** comparator resources; what remains is **regenerating the ClinVar-derived comparator resources (PS1/PM5/PM1/PP2/BP1) with the held-out variants masked** and **re-scoring** on those masked resources.
3. **ClinVar audit — COMPLETE; ruling/masking pending.** The mechanized audit ran on the full held-out output: **PS1 116**, **PM5 13**, **PM1/PP2/BP1 0**; the report fails closed on PS1/PM5. Static lineage still requires masking all five. Remaining: masked-resource rerun + Oracle ruling (ADR-0009).
4. **Canonical adapter** — the arm's-length eval `EvidenceSource` adapter joining BIAS rows by canonical SPDI (not raw VCF strings).
5. **Clopper-Pearson gate** — make the PRD-06 gate compute the 95% CI lower bound, not just the point estimate (EVAL_RUBRIC §6).
6. **BS2 policy** — record a rationale for BS2 (fired 34× in the census, currently omitted from policy).
7. **Transcript / NTHL1 resolution** — reconcile BIAS `.4` vs production `.5` transcripts; resolve the 30 TSC2-region inputs mis-annotated as NTHL1.
8. **Production candidate policy** — pin the production candidate-direction policy (gene scope, combiner, criteria set) consistent with eval.
9. **PRD-04 output contract** — the **candidate evidence packet / output contract is active and unblocked now**; provisional representative (and even all-VUS) candidate packets may be generated **before** expert review; only the **full externally usable worklist** is gated on validation, policy correction, and expert sign-off.
10. **Expert validation + named adopter** — recruit the validating oracle (GP-3) and name a first TSC adopter (R-F1/R-F6).

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
| PRD-04 | **Candidate Evidence Packet / Output Contract** (per-variant candidate *direction* + full evidence trail; *contract active/unblocked now*; provisional representative/all-VUS packets may be built before expert review; the full **externally usable** worklist waits for a gate PASS + policy correction + expert sign-off) | 1/2 | **active — contract now** (external worklist release gated on PRD-06 PASS) |
| PRD-05 | Pipeline & Orchestration skeleton | 0 | **frozen** — generic orchestration out of scope (ADR-0010) |
| PRD-06 | **Benchmark & Evaluation Harness** (build known-variant benchmark + train/dev/held-out split + P/R/concordance, class-stratified; **gates any VUS run**) | 1 | **Signed off · module built ✓** (`e026422`, PR #1, 222 tests; 7-round cross-family checker sign-off) |
| PRD-07 | **ClinVar Knowns → Benchmark Labels Loader** (Track A1: label-side `variant_summary` → `LabeledVariant` for PRD-06; reuses PRD-02 contract+normalizer; keeps scorer label-blind, H1) | 1 | **Signed off · module built ✓** (`499f479`, PR #3, 274 tests; 7-round checker sign-off) |

> **Validation gate (binding):** no classification is run on the ~6,700 TSC VUS until PRD-06 shows
> Tier-1/2 clears pre-registered thresholds on the **held-out known-variant** set — reported
> **stratified by variant class** (missense gated separately; R-A2c). See EVAL_PLAN §1.1.

## Path to first VUS run

The three parallel tracks (A benchmark · B x64 scoring infra · C oracle thresholds) are **done**. What
remains is the **terminal join**: the raw label-free held-out scoring run on x64 is **done** (2,577
parsed records on full comparator resources); still pending are the held-out-masked comparator-resource
regeneration + masked rerun, the arm's-length `EvidenceSource` canonical adapter, the Oracle ruling,
the missense-stratified metrics, then the gated PRD-06 held-out eval. The static lineage gate and
full-output ClinVar-derivation audit are complete (ADR-0009).

| # | Track | Type | Status |
|---|---|---|---|
| A | **Benchmark data** — real ClinVar TSC1/TSC2 *knowns* → frozen labeled benchmark (excl. conflicting/single-submitter/low-review; label hierarchy) | data | **DONE ✓** — frozen snapshot `clinvar_2026-07-07`; **3,681** scoreable knowns → **2,577** held-out / **1,104** dev reserve at `holdout 0.7` (PR #7 `2e3477f`, Track A2; A1 loader PRD-07 `499f479`) |
| B | **x64 live-scoring infra** — BIAS-2015 (arm's-length, ADR-0007) + Nirvana (x64-only, ADR-0008) | infra | **Smoke-tested ✓ (operator-confirmed)** — BIAS-2015 v3.0.0 + Nirvana 3.18.1 produced an 8-record TSV that passed `BiasTsvSource`'s 18-column contract with identity preserved. Large external artifacts intentionally out of repo; versions/hashes live in the operator's external reports (handoff bundle PR #8 `3556548`) |
| C | **Oracle thresholds (GP-3)** — pre-register precision/recall targets into `configs/eval/tsc2.yaml` | governance | **DONE ✓** — `oracle_thresholds {precision: 0.90, recall: 0.85}` pre-registered *blind* to held-out results; `min_count_per_class: 35`, `split.holdout_fraction: 0.7` (PR #10 `8662499`) |
| J | **Terminal join** — raw label-free held-out VCF **emitted + scored** (2,577 parsed records, full resources); remaining: regenerate held-out-masked comparator resources (PS1/PM5/PM1/PP2/BP1) + masked rerun, build the canonical eval adapter + derivation guard, audit PS1/PM5/PM1/PP2/BP1 → Oracle ruling, compute missense-stratified metrics, run PRD-06 held-out eval; gate must `PASS` (missense-stratified, **both directions**) → authorizes the ~6,700-VUS run | code + eval | **RAW SCORE DONE; masked rerun + gate PENDING** — see *Priorities* above; A ∧ B ∧ C are met |

> A/B/C are complete and had **no code dependency on each other**. Thresholds are now pre-registered
> (C done), so the gate no longer reads `UNVERIFIED` for a missing target — the **raw** held-out score
> now exists, but the gate still **cannot `PASS`** until the leakage-safe **masked rerun** produces
> leakage-safe scores and the Oracle ruling on **PS1/PM5/PM1/PP2/BP1** lands; the derivation audit is
> complete and confirms the current unmasked held-out output must not proceed (ADR-0009).

## Active Decisions & Bottlenecks
- (Resolved 2026-07-10) **Strategy premise falsified → vertical TSC/mTOR reset** — generic-platform *uniqueness* premise withdrawn; horizontal/platform expansion **frozen**; RAPTOR repositioned as a vertical TSC/mTOR research-evidence product (candidate packets · atlas · gated mTOR hypotheses) — **ADR-0010**. Census (PR #12 `253c9fd`, `5a307df`) complete but **non-authoritative**; held-out gate still governs.
- (Resolved 2026-07-10) **AAVC prior-art boundary** — AAVC's September-2024 release contains 4,532 TSC VUS and 808 machine P/LP/B/LB calls. It is now a pinned **external disagreement comparator**, never a truth label or criterion source; all eight directional conflicts in the representation-matched overlap enter the expert calibration batch, with first-pass reviewers blinded to both machine directions until a logged reconciliation reveal. See [`reference/aavc-prior-art-audit-2026-07.md`](reference/aavc-prior-art-audit-2026-07.md).
- (Resolved 2026-07-08) Loop-engineering operating model → planner/doer/checker, see ADR-0003.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Resolved 2026-07-10) **ClinVar direct-copy circularity** → **PP5/BP6/PS4 banned** from `automatable_criteria` (eval == production; structurally rejected in `eval.config.FORBIDDEN_CRITERIA`); comparator-dependent **PS1/PM5/PM1/PP2/BP1 deferred** to the full-held-out audit (static criterion lineage — ADR-0009, PR #11 `2766e33`). Real BIAS v3.0.0 output showed PS4 falls back to counting ClinVar submitters for rare Mendelian variants.
- (Resolved 2026-07-10) **Full-output circularity audit** — machine-enforced 28/19/9 lineage policy + exact-set registry + fail-closed audit landed. Held-out incidence: PS1 116, PM5 13, PM1/PP2/BP1 0; the unmasked report blocks on PS1/PM5, while static lineage keeps all five in the masked-resource requirement. Oracle ruling + masked rerun remain on the terminal-join path (ADR-0009).
- (Open) **Gate fidelity — Clopper-Pearson lower bound** — the gate currently checks the **point estimate**, not the 95% CI lower bound the rubric frames; `min_count_per_class: 35` is the underpowered floor that approximates it. Making the gate compute the Clopper-Pearson lower bound is a tracked PRD-06 follow-up (EVAL_RUBRIC §6).
- (Open) **Per-stratum truncating 0.95 gate** — truncating ≥0.95 (210 held-out, powered) is **reported, not gated**; hard-gating it needs a PRD-06 per-stratum `oracle_thresholds` extension (EVAL_RUBRIC §5). Missense (≥0.90) is the binding constraint.
- (Open) **Loader GRCh38 assembly filter** — confirm the PRD-07 knowns loader strictly filters to the GRCh38 assembly (the freeze script already filters GRCh38+TSC1/TSC2; harden the loader-side guard).
- (Open) Cross-linkage oracle — recruit molecular geneticist before Phase 3 (STRATEGY.md GP-3; risk R-E1).
- (Open) Confirm worker vCPU allocation at deploy (EPYC/Xeon 8-vCPU VM vs full silicon).
- (Open) **Build core risk controls before trusting any automated output** — canary set, heartbeat/dead-man's switch, hard spend cap, source-contract tests, **answer-key/trace-cribbing lint, assertion-lock** (RISK_REGISTER.md §1; risks R-C1/R-A2/H1).
- (Open) ADR — reuse `biomcp` / `paper-search-mcp` MCP connectors for Tier-3 retrieval (ARCHITECTURE.md §8; gated on GP-10/GP-9).
- (Open) **PRD-04 (Candidate Evidence Packet / Output Contract)** — output contract *active/unblocked now*; provisional representative/all-VUS packets may be built before expert review; release the full **externally usable** worklist **only after** a gate PASS + policy correction + expert sign-off. **PRD-05 (pipeline & generic orchestration) frozen** as generic/out-of-scope (ADR-0010).
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
