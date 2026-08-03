# RAPTOR PROGRAM STATUS

> Live status rollup. For *why* the project is shaped this way, see **[STRATEGY.md](STRATEGY.md)**
> (strategy + operating-model authority), **[EVALUATION.md](EVALUATION.md)** (benchmark / rubric
> authority), **[DECISIONS.md](DECISIONS.md)** (ADRs), **[ARCHITECTURE.md](ARCHITECTURE.md)**
> (runtime), and **[RISK_REGISTER.md](RISK_REGISTER.md)** (failure modes). This doc tracks *state*;
> those track *intent*.

> **Strategy status (2026-07-22 — post-ADR-0013 reconciliation).**
> The generic-platform *uniqueness* premise was falsified and horizontal/platform expansion is
> **frozen** ([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy));
> RAPTOR is a **vertical TSC/mTOR research-evidence product** (candidate evidence packets ·
> evidence/assay/contradiction atlas · gated mTOR hypothesis packets). The complete deterministic
> TSC1/TSC2 evidence census, the leakage-safe masked held-out rerun (**R2**,
> [ADR-0012](DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)),
> and the **tiered gate v3 post-hoc re-adjudication**
> ([ADR-0013](DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock))
> are all complete. R2 and its v1/v2 interpretation remain **byte-identical and immutable**
> (`FAIL` on the coarse missense gate; v2 `BLOCKED_POLICY`; `vus_authorized=false`). v3 re-reports
> the same frozen R2 aggregate on independent axes — run integrity, data sufficiency, conditional
> performance, policy parity, correct-call coverage, scope evidence, authorization — generating
> **no new evidence**: missense pathogenic is `NO_CALLS`/`NOT_ESTIMABLE` (PM1-blocked), missense
> benign is `UNDERPOWERED`/`NOT_ESTIMABLE`, truncating pathogenic is `ADEQUATE`+`MET`/
> `SUPPORTED_POSTHOC`, and full-spectrum authorization is `NOT_VALIDATED`/`NOT_AUTHORIZED`.
> Truncating-pathogenic authorization is `PENDING_PROSPECTIVE`, locked to the first NCBI ClinVar
> GRCh38 monthly archive dated on/after 2026-08-01. The canonical validated research-scope flag
> remains `false`. No candidate direction is authoritative and no externally usable VUS worklist,
> clinical classification, or ClinVar submission is authorized.

## TSC VUS evidence census — COMPLETE (internal · eval-only · non-authoritative)

> Current source of record: `data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`
> (snapshot `clinvar_2026-07-07`; PP3/BP4-disabled/manual policy, [ADR-0012](DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun);
> canonical SHA-256 `45ff9f9abada7d5369c131bf7ffde28d0786eea41ff9bf7905f51da0cabd59ac`). **These are
> internal review directions from the packet-free `raptor.census` package, not classifications.** Do
> **not** call them reclassifications or resolutions, and do **not** describe them as "24% VUS
> resolution." The earlier `tsc_vus_clinvar_2026-07-07_stats.json` (PP3/BP4-active policy) is a
> **superseded historical comparator**, retained for the delta below, not the current policy.

- **Corpus:** **6,618** total VUS — **TSC1 2,249**, **TSC2 4,369**; by class **5,645 missense**,
  **893 other**, **80 truncating**.
- **Run integrity:** **6,618/6,618 scored** by the pinned Nirvana/BIAS pipeline; exact join; **zero**
  duplicate keys and **zero** parser-contract errors.
- **Current eval-only, internal, non-authoritative candidate directions (disabled_manual policy):**
  **157** candidate-LP review · **7** candidate-LB review · **6,424** unresolved · **30**
  annotation/manual. Zero PP3/BP4 calls were scored; suppression affected **5,474** variants (raw
  BP4 3,696; raw PP3 2,226). *(6,424 remain unresolved — the census resolves nothing on its own.)*
- **Superseded historical comparison (PP3/BP4-active policy, do not treat as current):** **238** LP
  review · **1,333** LB review · **5,017** unresolved · **30** annotation/manual — labeled delta only,
  per `historical_comparison_superseded` in the current stats record.
- **Evidence-pattern compression (recorded under `candidate_pattern_compression`
  — a reproducible internal analysis, *not* validated truth, not a benchmark result):** the 157
  candidate-LP directions span **7** exact strength patterns (1 pattern covers 90%); the 7
  candidate-LB directions span **2** patterns, with **BP3 Strong + PM2 Supporting** covering 6/7.
- **Known gaps (from the stats file):** PS1/PM5 fired using ClinVar-derived comparator resources and — by
  static criterion lineage (ADR-0009) — PM1/PP2/BP1 depend on them too; all five need held-out masking for
  the leakage-safe validation bundle. *(The census itself used the **full** comparator resources —
  legitimate for non-authoritative VUS directions, but **not** leakage-safe for held-out validation.)*
  The masked R2 gate (below) remains negative; neither the census directions nor their shares
  authorize a VUS worklist. TSC1/TSC2 `.4→.5` transcript deltas require manifest-supplied canonical
  SPDI proof; all 30 **NTHL1** records remain manual/out-of-scope. The BP4/PP3 aggregation defect has
  a deterministic arm's-length correction, but the joined production policy remains unapproved/null.
  **No externally usable candidate worklist may be released before a prospective, leakage-safe
  validation pass + expert sign-off.**

## R2 masked held-out gate (ADR-0012, frozen) and tiered v3 re-adjudication (ADR-0013, post-hoc)

> Source of record: `data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json` (R2;
> canonical SHA-256 `7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f`) and
> `data/census/tsc_tiered_readjudication_2026-07-21.json` (v3; SHA-256
> `1e36b2d07767fdd8e32fbf07dd42f60a2b4cae2ff9b21c7dfb9430d741c5bc5f`). **R2 is byte-identical and
> immutable; v3 performs no new run, scoring, annotation, benchmark read, network access, or data
> generation** — it re-interprets the same frozen aggregate under a versioned tiered rule.

- **R2 (frozen):** 2,577/2,577 identities masked with zero survivors; canonical join exact; zero PP3/BP4
  scored calls (raw suppression BP4 1,929 / PP3 134 across 2,043 variants). v1 legacy gate: `FAIL` on
  the binding missense stratum. v2: `full_spectrum_status=BLOCKED_POLICY`, `vus_authorized=false`,
  blocked on `evaluation_skipped_criteria:PM1`.
- **v3 (post-hoc, no new evidence):**
  - `missense:pathogenic` — 51 actual, 0 called → `NO_CALLS` / `NOT_ESTIMABLE`; `policy_parity=BLOCKED`
    (PM1 applies only to this scope).
  - `missense:benign` — 103 actual, 9 called (all correct) → `UNDERPOWERED` / `NOT_ESTIMABLE`
    (`min(103,9)=9 < min_count=36`).
  - `truncating:pathogenic` — 210 actual, 189 called, precision/recall lower bounds 0.9807/0.9807 vs
    0.95/0.95 thresholds → `ADEQUATE` + `MET`, evidence `SUPPORTED_POSTHOC`; authorization
    `PENDING_PROSPECTIVE`.
  - `full_spectrum_status=NOT_VALIDATED`, `full_spectrum_authorization=NOT_AUTHORIZED`;
    `research_scope_flags.truncating_pathogenic_research_scope_validated=false`.
- **Prospective validation (locked, not yet run):** the first eligible NCBI ClinVar GRCh38
  `variant_summary` monthly archive dated on/after 2026-08-01, frozen (URL/date/MD5/SHA-256) before
  labels or scoring. If unavailable/invalid, status is `BLOCKED_DATA` — no outcome-dependent
  substitute. `prospective_validation_status=PENDING`.
- **What this does and does not authorize:** v3 corrects how the frozen R2 result is *described*
  (separating insufficient-data from failure from policy-exclusion); it authorizes no clinical
  classification, VUS worklist, ClinVar submission, or research scope. Only a future prospective run
  plus a new owner decision can change that.

## Operating Model — build loop

RAPTOR is built in a **design → test-author → build → review → eval → (back to design)** loop with a fixed
model-role split (see **[ADR-0003](DECISIONS.md#adr-0003--loop-operating-model-planner--doer--checker-across-three-model-families)**
and **[ADR-0005](DECISIONS.md#adr-0005--test-strategy-separated-authorship-model-diversity-frameworks--domain-truth-data)**):

| Stage | Role | Model | Note |
|---|---|---|---|
| Design / plan | Planner | Claude Opus | writes task spec + acceptance criteria; no production code |
| Test authoring | Test author | Gemini | writes RED acceptance tests from the spec before implementation |
| Build | Doer | Claude Sonnet 5 | implements against the spec |
| Review / eval | Checker | GPT (5.x) | adversarial review vs acceptance criteria; pass or send back |

Rule: the **checker is always a different model family from the doer**; nothing is "done" until the
checker passes it against pre-stated acceptance criteria. *(Spec/verdict schema + gate automation are
pending `STRATEGY.md` Part II §10 — ADR-0003.)*

## Health Rollup

> *Module built ≠ live run executed.* The Tier-1/2 code path and the validation harness are **built
> and signed off**; R2 (the leakage-safe held-out set) is **scored and gated** (frozen, v1/v2
> `FAIL`/`BLOCKED_POLICY`); the **tiered v3 post-hoc re-adjudication (ADR-0013) is complete** and
> reports the same frozen result on independent axes. No VUS classification is authorized; the only
> scope with any positive evidence (`truncating:pathogenic`, `SUPPORTED_POSTHOC`) remains
> `PENDING_PROSPECTIVE`.

- Tier 1/2 (Deterministic): 🟡 **MODULE BUILT; R2 GATE FAIL, v3 TIERED RE-ADJUDICATION COMPLETE**
  (PRD-01 scorer `1d2444e`; arm's-length BIAS port) — *2,577-row masked gate completed; missense
  scopes `NO_CALLS`/`UNDERPOWERED`; truncating-pathogenic `SUPPORTED_POSTHOC`, not authorized*
- **Evidence census:** ✅ **COMPLETE** (internal · eval-only · non-authoritative, disabled_manual
  policy, ADR-0012) — 6,618 VUS scored; **157**/**7**/**6,424**/**30** current candidate directions
  (see census section above); candidate directions **not** classifications
- Tier 3 (LLM Extraction): 🔴 NOT STARTED (Phase 2)
- Consensus/Adjudication: 🔴 NOT STARTED
- Validation Framework: 🟡 **EXECUTED — R2 FAIL/BLOCKED_POLICY; v3 POST-HOC RE-ADJUDICATED**
  (canonical BIAS adapter; ClinVar masker/auditor; exact 95% Clopper-Pearson lower-bound,
  per-direction/per-stratum gate; fail-closed predictor-policy prerequisite; ADR-0013 tiered axes) —
  *masked resources scored once; v3 separates data sufficiency from failure but authorizes nothing;
  prospective validation `PENDING`*
- **Non-authoritative expert-review packet generation and molecular-geneticist recruitment:** 🟡
  **ACTIVE** — packet generation continues as internal review preparation only; oracle recruitment
  (GP-3) is open (see Active Decisions & Bottlenecks)
- **Mechanism Atlas:** 🟡 **PHASE 1 IMPLEMENTED / MERGED** — GPT-5.4-clean at merge `9709ec6`
  (tracker update `1134c2e`): generic condition-agnostic core + exactly one versioned `tsc2`
  pack + pack-bound hashes + static import/classification-leakage guards + synthetic-only
  promotion flow and out-of-process Discovery templates; `tests/atlas/` is a 35-test Phase 1
  suite. **Phase 2 real grounding has begun (non-authoritative).** The deterministic
  citation/source resolver is complete; a supervised, optional, out-of-process six-stage
  Discovery DAG (identity → literature → claims → {contradictions, context} → gaps) has
  reached `executionDone` for the R611Q anchor's identity and literature stages (GRCh38
  SPDI/ClinVar/dbSNP identity proposed; literature/licence survey confirms both older
  primary papers remain paywalled and PMC11185720 is CC BY-NC-ND 4.0, not CC-BY-4.0). The
  original Discovery claims stage was superseded by permitted external-source staging. A
  hash-bound external catalog now registers five resolver-verified grounding leaves (four
  CC-BY-4.0 publications and one CC0 MaveDB dataset) plus seven non-grounding leads. Two
  R611Q exact spans pass deterministic Gates 1-7; Gate 8 blocks because no named reviewer is
  engaged, and zero claims are accepted. A separate, hash-selected six-variant technical
  repeatability cohort also passed Gates 1-7 in all six cases and blocked only at Gate 8,
  with zero accepted claims; it is explicitly not the formal contrast panel or scientific
  validation. Identity-custody universe v1 commits a 35-entry discovery frame (31 missense
  alleles; 28 identities resolved, seven unresolved). Evidence-enriched universe v2 now
  carries 37 attributable observations across 32 records (15 near-reference, three
  intermediate and 19 substantial-deviation source categories), with three explicit
  evidence-absent records and no manufactured cross-source independence. Its candidate-free
  lock is committed, and administrative protocol/registration v1.0.3 now binds lock v2 while
  preserving the original seed and all selection rules. Formal selection is ready but has not
  run. Contradiction, context, gap synthesis, named human review, accepted Atlas profiles,
  classifications and second-disease support all remain pending. Discovery remains an
  optional out-of-process aid, never a runtime dependency of the core RAPTOR workflow.

## Source expansion roadmap — ordered and governed

> Source expansion is an evidence/provenance program, not a way to rescue the frozen R2 result.
> No new source changes R2, the ADR-0013 prospective dataset rule, an ACMG policy, or an existing
> packet without a separately versioned policy, material-drift decision and required revalidation.
> The durable dependency graph lives in `docs/project/TODOS.yaml` under
> `source-expansion-roadmap`.

**Baseline already complete:** the 16-predictor decision matrix and pinned historical
Nirvana/BIAS annotation bundle exist; ClinVar census/benchmark inputs are frozen; the verified
MaveDB cliPE dataset is available only as non-gating orthogonal evidence. These artifacts do not
constitute a live refresh system, and PP3/BP4 automation remains disabled.

| Order | Expansion layer | Durable tasks | Admission rule |
|---:|---|---|---|
| 1 | **Control plane** — source owner, authoritative URL, licence, release, checksum, acquisition, cadence, consumers, drift and rollback | `sourceops-version-refresh-registry`, `governance-data-rights-privacy` | No ingestion or activation before identity/licence/provenance are explicit. |
| 2 | **Open literature + functional evidence** — PubMed/LitVar/PMC citation stack; IGVF VAMP-seq/SGE, CAGI7 and legacy-assay access | `sources-add-literature-stack`, `assurance-expand-orthogonal-validation` | Claims remain span-grounded, non-gating and review-bound; access/licence gaps fail closed. |
| 3 | **Safe refresh machinery** — detect, download, verify, stage and diff; materiality, packet invalidation, benchmark rebuild and rollback | `sourceops-automated-refresh-validation`, `sourceops-drift-revalidation-gates` | Never silently replace a production or historical source. |
| 4 | **Current annotation refresh** — stage current ClinVar, gnomAD, dbNSFP, MANE, dbSNP and reference bundle on x64 | `sources-stage-annotation-refresh` | Promotion occurs only after the control-plane and drift gates; frozen R2 remains immutable. |
| 5 | **Separate evidence/modalities** — splice, difficult regions, SV/CNV | `sources-add-splice-track`, `sources-audit-difficult-regions`, `sources-design-sv-cnv-track` | Each receives its own consequence routing, calibration, benchmark and no-double-counting policy. |
| 6 | **Clinical/commercial sources** — phenotype/penetrance and licensed/vendor feeds | `clinical-phenotype-penetrance-track`, `sources-evaluate-commercial-sources` | Patient-level data waits for privacy/consent controls; commercial feeds require proven incremental value and permitted use. |

**Completion definition:** every admitted source is registered and reproducible; every refresh is
staged and diffed; every material change names its downstream invalidations and revalidation;
rollback is tested; literature/functional claims resolve to exact sources and spans; and no modality
is inserted into the small-variant scorer merely because its data is available.

## Operations (Current Run)

> R2 (the leakage-safe 2,577-variant held-out set) has been scored and gated once; it is frozen and
> immutable. Metrics below are evaluation-only. v1/v2 interpretation: **FAIL**/`BLOCKED_POLICY`. v3
> (ADR-0013) re-reports the same numbers as independent axes without rerunning anything.

- Last Batch Size: **2,577** (frozen; not re-run)
- `missense:pathogenic` — 51 actual, **0** called; precision/recall not estimable (v3:
  `NO_CALLS`/`NOT_ESTIMABLE`; `policy_parity=BLOCKED` on PM1)
- `missense:benign` — 103 actual, 9 called (all correct); precision/recall lower bound **0.6637**
  vs threshold **0.90/0.85** (v3: `UNDERPOWERED`/`NOT_ESTIMABLE`; coverage `9 < min_count 36`)
- `truncating:pathogenic` — 210 actual, 189 called; precision/recall lower bound **0.9807** vs
  threshold **0.95/0.95** (v3: `ADEQUATE`+`MET`/`SUPPORTED_POSTHOC`; authorization
  `PENDING_PROSPECTIVE`)
- Suspended (Human Review): N/A
- *(The 2026-07-13 pre-ADR-0012 run's point estimates — precision 0.8421/recall 0.9412 pathogenic,
  0.9688/0.9118 benign — are a superseded historical comparator under a different, since-disabled
  predictor policy; they are not the current binding record.)*

## Priorities (This Week) — prepare expert-review packets; keep prospective validation locked

**Merged:** PR **#12** (Task A — label-free held-out export + pre-results checkpoint) at **`253c9fd`**;
R2 masked rerun ([ADR-0012](DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun))
and tiered gate v3 ([ADR-0013](DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock))
are both merged and frozen. The generic-platform roadmap is retired
([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy));
the vertical worklist below replaces it. **Census candidate directions and the truncating-pathogenic
`SUPPORTED_POSTHOC` scope stay non-authoritative until the locked prospective validation PASSes.**

1. **BIAS criterion lineage — COMPLETE.** The pinned source-derived **28-slot / 19-can-fire / 9-internal-stub** policy, exact-set registry gate, total audit + fail-closed enforcement, and portable source-oracle fixture are implemented. Real 6,618-VUS and 2,577-held-out audits both block on **PS1/PM5**; zero firing does not clear the statically mask-required **PM1/PP2/BP1**. See `data/census/tsc_bias_lineage_audit_2026-07-10.json`.
2. **Held-out-masked BIAS validation bundle (R2) — COMPLETE; v1/v2 GATE FAIL/BLOCKED_POLICY; v3
   POST-HOC RE-ADJUDICATED.** Exact upstream masking removed 2,577/2,577 identities with zero
   survivors; the canonical adapter joined 2,577/2,577 rows. Masked PS1/PM5/PP2/BP1 resources were
   regenerated and scored once. PM1 had zero reachable rows in both published and reproduced
   resources, was explicitly skipped for this evaluation, and remains production-unvalidated. The
   frozen R2 aggregate is unchanged; [ADR-0013](DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)
   re-reports it as missense `NO_CALLS`/`UNDERPOWERED` and truncating-pathogenic
   `SUPPORTED_POSTHOC`/`PENDING_PROSPECTIVE` — see the R2/v3 section above.
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
10. **Expert validation + named adopter** — recruit the validating oracle (GP-3) and name a first TSC adopter (R-F1/R-F6). **Active:** molecular-geneticist recruitment is open; no oracle is yet engaged.
11. **ClinVar/VCEP preparation — COMPLETE (NO SUBMISSION).** PRD-09 pins the current
    `germlineSubmission/germlineClassification` shape, `clinvarDeletion` lifecycle, deny-list, schema
    freshness guard, institutional prerequisites, and an unreachable submission-authorization state.
12. **Tiered gate v3 post-hoc re-adjudication — COMPLETE.** [ADR-0013](DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)
    re-reports the frozen R2 aggregate on independent axes (run integrity, data sufficiency,
    conditional performance, policy parity, correct-call coverage, scope evidence, authorization)
    without any new run, scoring, or evidence generation. Prospective validation is locked to the
    first NCBI ClinVar GRCh38 monthly archive dated on/after 2026-08-01 (frozen before labels/scoring)
    and is `PENDING`.
13. **Non-authoritative expert-review packet generation — ACTIVE.** Provisional candidate packets
    (PRD-04 output, item 9) are being prepared for internal expert review as non-authoritative review
    preparation only; this may proceed in parallel with the pending prospective validation but cannot
    itself authorize any scope. **Mechanism Atlas Phase 1 is implemented and merged** (`9709ec6`;
    tracker `1134c2e`), GPT-5.4-clean: generic condition-agnostic core, exactly one versioned
    `tsc2` pack, pack-bound hashes, static import/classification-leakage guards, a synthetic-only
    promotion flow, and out-of-process Discovery templates, backed by the 35-test `tests/atlas/`
    suite. **Phase 2 real grounding has begun (non-authoritative).** The deterministic
    citation/source resolver is complete; a supervised, optional, out-of-process six-stage
    Discovery DAG has reached `executionDone` for the R611Q anchor's identity and literature
    stages (GRCh38 SPDI/ClinVar/dbSNP identity proposed; literature/licence survey confirms
    both older primary papers remain paywalled and PMC11185720 is CC BY-NC-ND 4.0, not
    CC-BY-4.0). The claims (exact-span extraction) stage is on hold pending permitted
    full-text access; only a MaveDB CC0 direct-dataset observation is staged, not an accepted
    claim, and downstream contradiction/context/gap stages remain blocked. No real mechanism
    claims, grounding spans, R611Q conclusions, classifications, or second-disease support
    are admitted — this is untrusted research staging pending named human/oracle review, and
    Discovery remains an optional out-of-process aid, never a runtime dependency.

> **Provisional packets now vs externally usable worklist after PASS:** items 1–8 and the PRD-04 output
> contract (item 9) proceed now, and provisional representative/all-VUS candidate packets may be built
> for internal review before expert sign-off; **releasing the full *externally usable* worklist waits
> for the locked prospective validation (ADR-0013) to PASS** on unseen data, the ADR-0009 policy
> correction, and leakage-safe expert sign-off. The frozen R2/v1/v2 result and the v3 post-hoc
> re-adjudication do **not** by themselves satisfy this — v3 generates no new evidence and
> `truncating:pathogenic` remains `PENDING_PROSPECTIVE`.
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
| PRD-04 | **Candidate Evidence Packet / Output Contract** (immutable evidence core; nullable candidate direction; deterministic first-pass render/queue; populated-atom calibration selector; variant-scoped review log; reveal-only comparator) | 1/2 | **Built ✓ — provisional/internal only** (42 packet tests; external worklist release gated on the locked prospective validation (ADR-0013) + policy approval + per-variant sign-off) |
| PRD-05 | Pipeline & Orchestration skeleton | 0 | **frozen** — generic orchestration out of scope (ADR-0010) |
| PRD-06 | **Benchmark & Evaluation Harness** (build known-variant benchmark + train/dev/held-out split + P/R/concordance, class-stratified; **gates any VUS run**) | 1 | **Signed off · module built ✓** (`e026422`, PR #1, 222 tests; 7-round cross-family checker sign-off) |
| PRD-07 | **ClinVar Knowns → Benchmark Labels Loader** (Track A1: label-side `variant_summary` → `LabeledVariant` for PRD-06; reuses PRD-02 contract+normalizer; keeps scorer label-blind, H1) | 1 | **Signed off · module built ✓** (`499f479`, PR #3, 274 tests; 7-round checker sign-off) |
| PRD-09 | **ClinVar/VCEP Submission Preparation** (field/lifecycle mapping, source register, deny-list, no-submission controls; no network client/SCV) | external prep | **Prepared ✓ — no submission authorized** |

> **Validation gate (binding):** no classification is run on the ~6,700 TSC VUS until the locked
> prospective validation (ADR-0013) PASSes on unseen data. PRD-06's held-out framework and
> Tier-1/2's frozen R2 run against pre-registered thresholds are complete and gated **FAIL**/
> `BLOCKED_POLICY`; the tiered v3 post-hoc re-adjudication (ADR-0013) reports that same result more
> precisely (per-scope, not pooled) but generates no new evidence and authorizes nothing — see
> See [EVALUATION.md Part I §1.1](EVALUATION.md#evaluation-validation-gate), [Part I §1.3](EVALUATION.md#evaluation-v3-posthoc-prospective), and [Part II §7](EVALUATION.md#evaluation-rubric-v3).

## Path to first VUS run

The three parallel tracks (A benchmark · B x64 scoring infra · C oracle thresholds) are **done**, the
**terminal join** (R2) is **done** (frozen, immutable), and the tiered v3 post-hoc re-adjudication
(ADR-0013) is **done**. What remains before any VUS run is the **locked prospective validation** —
the first eligible NCBI ClinVar GRCh38 monthly archive dated on/after 2026-08-01, frozen before
labels/scoring — plus a new owner decision. Canonical adapter, exact statistical gate, static lineage
gate, and full-output derivation audit are complete (ADR-0009).

| # | Track | Type | Status |
|---|---|---|---|
| A | **Benchmark data** — real ClinVar TSC1/TSC2 *knowns* → frozen labeled benchmark (excl. conflicting/single-submitter/low-review; label hierarchy) | data | **DONE ✓** — frozen snapshot `clinvar_2026-07-07`; **3,681** scoreable knowns → **2,577** held-out / **1,104** dev reserve at `holdout 0.7` (PR #7 `2e3477f`, Track A2; A1 loader PRD-07 `499f479`) |
| B | **x64 live-scoring infra** — BIAS-2015 (arm's-length, ADR-0007) + Nirvana (x64-only, ADR-0008) | infra | **Smoke-tested ✓ (operator-confirmed)** — BIAS-2015 v3.0.0 + Nirvana 3.18.1 produced an 8-record TSV that passed `BiasTsvSource`'s 18-column contract with identity preserved. Large external artifacts intentionally out of repo; versions/hashes live in the operator's external reports (handoff bundle PR #8 `3556548`) |
| C | **Oracle thresholds (GP-3)** — pre-register precision/recall targets into `configs/eval/tsc2.yaml` | governance | **DONE ✓** — nested 95% lower-bound thresholds: missense 0.90/0.85 both directions; truncating 0.95 pathogenic; `min_count_per_class: 36`, `split.holdout_fraction: 0.7` |
| J | **Terminal join (R2)** — label-free held-out VCF masked, rescored, canonically joined, corrected and gated | code + eval | **DONE — FAIL/BLOCKED_POLICY (frozen)** (`vus_authorized=false`; binding missense scopes not estimable/underpowered; PM1 excluded/production-unvalidated; truncating-pathogenic met but unauthorized) |
| K | **Tiered v3 post-hoc re-adjudication (ADR-0013)** — re-report the frozen R2 aggregate on independent axes; lock prospective validation | eval + governance | **DONE** — `NO_CALLS`/`UNDERPOWERED`/`SUPPORTED_POSTHOC` per scope; prospective validation `PENDING` |

> A/B/C are complete and had **no code dependency on each other**. Thresholds are now pre-registered
> (C done), so the gate no longer reads `UNVERIFIED` for a missing target — the **raw** held-out score
> now exists. The leakage-safe masked rerun (R2/J) also exists, is frozen, and returned
> `FAIL`/`BLOCKED_POLICY`; the tiered v3 re-adjudication (K) reports that result more precisely without
> rerunning anything. The next step is the **locked prospective validation** on unseen data (ADR-0013)
> plus continued non-authoritative expert-review packet preparation — not threshold relaxation or
> VUS release.

## Active Decisions & Bottlenecks
- (Resolved 2026-07-10) **Strategy premise falsified → vertical TSC/mTOR reset** — generic-platform *uniqueness* premise withdrawn; horizontal/platform expansion **frozen**; RAPTOR repositioned as a vertical TSC/mTOR research-evidence product (candidate packets · atlas · gated mTOR hypotheses) — **ADR-0010**. Census (PR #12 `253c9fd`, `5a307df`) complete but **non-authoritative**; the frozen R2 gate and locked prospective validation still govern.
- (Resolved 2026-07-10) **AAVC prior-art boundary** — AAVC's September-2024 release contains 4,532 TSC VUS and 808 machine P/LP/B/LB calls. It is now a pinned **external disagreement comparator**, never a truth label or criterion source; all eight directional conflicts in the representation-matched overlap enter the expert calibration batch, with first-pass reviewers blinded to both machine directions until a logged reconciliation reveal. See [`reference/aavc-prior-art-audit-2026-07.md`](reference/aavc-prior-art-audit-2026-07.md).
- (Resolved 2026-07-08) Loop-engineering operating model → planner/test-author/doer/checker,
  see ADR-0003 + ADR-0005.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Resolved 2026-07-10) **ClinVar direct-copy circularity** → **PP5/BP6/PS4 banned** from `automatable_criteria` (eval == production; structurally rejected in `eval.config.FORBIDDEN_CRITERIA`); comparator-dependent **PS1/PM5/PM1/PP2/BP1 deferred** to the full-held-out audit (static criterion lineage — ADR-0009, PR #11 `2766e33`). Real BIAS v3.0.0 output showed PS4 falls back to counting ClinVar submitters for rare Mendelian variants.
- (Resolved 2026-07-10) **Full-output circularity audit** — machine-enforced 28/19/9 lineage policy + exact-set registry + fail-closed audit landed. Held-out incidence: PS1 116, PM5 13, PM1/PP2/BP1 0; the unmasked report blocks on PS1/PM5, while static lineage keeps all five in the masked-resource requirement. Oracle ruling + masked rerun remain on the terminal-join path (ADR-0009).
- (Resolved 2026-07-12) **Gate fidelity** — exact Clopper-Pearson lower bounds, corrected n=36 floor,
  pinned gating/direction semantics, and truncating-pathogenic 0.95 hard gate implemented.
- (Resolved 2026-07-13) **Masked terminal gate executed — FAIL** — 2,577/2,577 masked/canonical rows,
  zero effective lineage blockers, evaluation-only BP4/PP3 correction applied, PM1 explicitly excluded;
  binding missense lower bounds failed all four pre-registered pathogenic/benign precision/recall bars.
  No VUS scoring or external worklist is authorized. *(This 2026-07-13 predictor-correction artifact is
  a superseded historical comparator; ADR-0012's disabled/manual R2 below is the current binding run.)*
- (Resolved 2026-07-21) **R2 masked rerun with PP3/BP4 automated emission disabled** — ADR-0012. The
  immutable 2,577-row BIAS evidence/mask artifacts were reused; 2,043 variants had 2,063 predictor
  calls suppressed (BP4 1,929; PP3 134); zero PP3/BP4 calls were scored. The binding missense gate
  returned `FAIL` and the v2 full-spectrum gate returned `BLOCKED_POLICY` (PM1 evaluation exclusion);
  `vus_authorized=false`. Under frozen v2 semantics PM1 was a global parity blocker. ADR-0013's
  additive v3 re-adjudication scopes PM1 to `missense:pathogenic`; truncating-pathogenic is
  `SUPPORTED_POSTHOC` with authorization `PENDING_PROSPECTIVE`, not PM1-blocked or authorized. R2 is
  frozen and byte-identical going forward.
- (Resolved 2026-07-21/22) **Corrected VUS census + tiered gate v3 post-hoc re-adjudication** —
  ADR-0012's `disabled_manual` census now reports **157**/**7**/**6,424**/**30** current candidate
  directions (superseding the earlier PP3/BP4-active **238**/**1,333**/**5,017**/**30** as a labeled
  historical comparator). ADR-0013's tiered v3 re-adjudication reports the same frozen R2 aggregate as
  missense `NO_CALLS`/`UNDERPOWERED` (both `NOT_ESTIMABLE`), truncating-pathogenic `ADEQUATE`+`MET`
  (`SUPPORTED_POSTHOC`), and full-spectrum `NOT_VALIDATED`/`NOT_AUTHORIZED`, with prospective
  validation locked to the first NCBI ClinVar GRCh38 monthly archive on/after 2026-08-01 (`PENDING`).
  No new evidence was generated; no scope is authorized.
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
  The **terminal join** (R2), the tiered v3 post-hoc re-adjudication (ADR-0013), and the current
  disabled_manual census are all now **done** and frozen (see *Path to first VUS run* / *Priorities*).
  Next: non-authoritative expert-review packet preparation, molecular-geneticist recruitment (GP-3),
  and the **locked prospective validation** (first NCBI ClinVar GRCh38 monthly archive on/after
  2026-08-01). Deferred: conformance-kit
  *governance* (kit-mypy/strict-first/C3 provenance/gate-0); PRD-05 (frozen, ADR-0010); cross-machine fleet.
