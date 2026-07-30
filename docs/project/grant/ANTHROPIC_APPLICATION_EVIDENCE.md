# RAPTOR — Anthropic Rare-Disease Application: Evidence Ledger

> **Status: application-support evidence record, prepared 2026-07-30.** This ledger cites only
> committed repository artifacts and git history at evidence-base commit
> `377abf1689a2c2658d23f61bdc80a9f9376de9cd` on public `main`; this ledger document
> is committed separately on branch `docs/grant-evidence-2026-07` at `b002cae`
> (public repository
> [`github.com/srinivasdrona/raptor`](https://github.com/srinivasdrona/raptor)). It does not read
> `.discovery`, local untracked notes, pre-build literature review, patient/private content, or any
> external `raptor-data` identities. Every commit, hash, and count below was independently
> re-verified against the working tree during preparation of this document (see §9).

## 1. Positioning

RAPTOR is a rare-disease research-evidence infrastructure project, currently implemented and
evaluated for a single vertical — **TSC1/TSC2** (tuberous sclerosis complex, mTOR pathway) — that
builds reproducible, hash-bound, provenance-complete variant-evidence artifacts (a frozen ClinVar
benchmark, a masked held-out validation gate, a deterministic non-authoritative VUS census, expert
-review packet scaffolding, and an early-stage, generic-core Mechanism Atlas with a versioned
disease-pack boundary) under an explicit research-only charter: RAPTOR is **not** a clinical
diagnostic system, issues **no** authoritative variant classification, and every artifact described
below is either evaluation-only, non-authoritative, post-hoc, or pending prospective validation —
none of it has cleared the pre-registered gate required before any classification, worklist, or
ClinVar-submission claim would be authorized (`docs/DECISIONS.md#adr-0011--scope-specific-research-authorization-gate-v2-truncating-pathogenic-research-scope-preregistered-separately-from-full-spectrum-vus`).

## 2. Fact ledger

All hashes below are the canonical **LF, no-BOM git-blob byte content** of the cited path at
evidence-base commit `377abf1689a2c2658d23f61bdc80a9f9376de9cd`, reproduced with
`git cat-file -p <evidence-base>:<path>` (see §9); a plain Windows
checkout of the same path is CRLF-translated and hashes differently — the repository's own specs
label that checkout hash `sha256_windows_crlf_checkout_do_not_pin` (e.g.
`docs/project/specs/corrected-review-packets-2026-07.yaml:531-533`) and it is **not** used here.

| # | Claim | Exact value / status | Source file / anchor | Commit(s) | Artifact SHA-256 | Limitation / what it does not prove |
|---|---|---|---|---|---|---|
| 1 | Frozen ClinVar benchmark snapshot | Snapshot `clinvar_2026-07-07`; `benchmark_size=3681`; `train_dev_size=1104`; `holdout_size=2577` | `data/benchmark/tsc_clinvar_2026-07-07_stats.json`; `docs/EVALUATION.md#evaluation-snapshot-provenance` | `2e3477f`, `8662499` | Snapshot `sha256=5fe4fe10783391d01dc414dc5583a3e63487b67f8cd3c8429d59227cd5f4f37f`; file `8492551f54840c7d7b544b05194c640b537350695aae5681277b27754153b8cd` | Proxy ClinVar labels, not expert-adjudicated ground truth; one dated snapshot, not a live feed |
| 2 | R2 masked held-out conservation | `bias_rows=2577`, `canonical_join_rows=2577`, `mask_removed_identities=2577`, `remask_survivors=0`, `returned_artifacts_verified=28` | `data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json` (`integrity` block); `docs/DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun` | `48dd0b4` (ADR), `ec34aba` (data freeze), `dfed3b9`/`d2d8053` (GPT-5.4 remediation) | `7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f` (self-described `content_hash` field is a separate, self-excluding internal hash: `2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2`) | Proves no held-out identity leaked/survived masking; proves nothing about classification accuracy |
| 3 | ADR-0012 `disabled_manual` PP3/BP4 mode | `policy.bp4pp3.mode="disabled_manual"`, `approved=true`; `pp3bp4_scored_calls=0`; `pp3bp4_suppressed_counts={BP4:1929, PP3:134}` | `docs/DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun`; `data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json` | `48dd0b4` | same as row 2 | Authorizes only the disabled/manual evidence mode — no VUS classification, worklist, research scope, or ClinVar submission |
| 4 | ADR-0013 tiered v3 post-hoc re-adjudication | `full_spectrum_status=NOT_VALIDATED`; `research_scope_authorization=PENDING_PROSPECTIVE`; `prospective_validation_status=PENDING`; `truncating:pathogenic` scope_evidence_status=`SUPPORTED_POSTHOC` | `data/census/tsc_tiered_readjudication_2026-07-21.json`; `docs/DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock` | `ea90921` (ADR + data), impl. commit `c56cb8914b8bf91b40a81f41fb7c5d8140e13f38` (recorded in-file) | `1e36b2d07767fdd8e32fbf07dd42f60a2b4cae2ff9b21c7dfb9430d741c5bc5f` (matches committed `tsc_tiered_readjudication_2026-07-21.sha256`); `source_canonical_lf_sha256=7c55cd4e...` independently verified equal to row 2's file hash | Re-interprets the frozen R2 aggregate on independent axes; performs **no new run, scoring, or data generation**; prospective validation still requires the first NCBI ClinVar GRCh38 monthly archive dated on/after 2026-08-01 |
| 5 | Current TSC1/TSC2 VUS census (`disabled_manual`) | `total_vus=6618`; `candidate_LP_review=157`; `candidate_LB_review=7`; `no_deterministic_resolution=6424`; `annotation_manual_review=30` (157+7+6424+30=6618) | `data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`; `docs/PROGRAM.md` | `ec34aba` | `45ff9f9abada7d5369c131bf7ffde28d0786eea41ff9bf7905f51da0cabd59ac` (matches `data/census/README.md`'s recorded certified hash) | The file's own `non_authoritative_boundary` field: "creates no public worklist, classification, research authorization, or clinical claim" — candidate LP/LB directions are eval-only triage signals |
| 6 | Corrected all-VUS review packets | External run `corrected-review-packets-2026-07-22-r1`: 6,618 operator packets, 6,618 blinded first-pass views, a 164-row priority (LP+LB) queue, and a hash-only 8-case Discovery sample | `docs/reference/corrected-review-packets-runbook.md`; `docs/project/specs/corrected-review-packets-2026-07.yaml` (hash pins, e.g. `manifest sha256=7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba`, `bias_tsv sha256=0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e`); `docs/project/TODOS.yaml` (`core-generate-review-packets`, status `done`) | `071111e33579ed1014b92cea77ab2eb7ca2312c0` (merge) | Packet-input hashes above are committed; the run's own packets/`aggregate_manifest.json` are written only to an external, non-repository `raptor-data` root and are not committed or cited here by path | Every packet keeps `candidate_direction=null`, `review_state=POLICY_BLOCKED`; authorizes no classification, worklist, or submission |
| 7 | Reviewer package (external adjudication) | No repository evidence found — omitted | — | — | — | — |
| 8 | Mechanism Atlas Phase 1 → citation resolver | Phase 1 generic core + `tsc2` pack merged with 35 tests (`9709ec6`, ADR-0014); citation/span resolver merged with 64 passing tests, GPT-5.4 checker **CLEAN** (`dc8826b`) | `docs/DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary`; `docs/project/TODOS.yaml` (`atlas-phase2-citation-resolver`, status `done`) | `9709ec6` (Phase 1 merge), `e55f9e6` (ADR-0014), `dc8826b` (resolver merge), `377abf1` (evidence-base TODO completion note) | — | Test counts independently reproduced: `git grep -c "def test_" 9709ec6 -- tests/atlas/` = 35; same command at evidence-base `377abf1` = 64; `python -m pytest tests/atlas -q` = **64 passed** locally. All fixtures are **fully synthetic**: no real PMID/PMCID/DOI, no real quote, no R611Q content (ADR-0016 item 7) |
| 9 | MaveDB TSC2 orthogonal validation (non-gating) | Scoreset `urn:mavedb:00001201-a-1`, CC0-1.0, **208** raw rows, transcript `NM_000548.5`; 66-variant VUS-independent overlap and 32-variant ClinVar-heldout (non-independent) overlap | `docs/reference/mave-tsc2-source-register-2026-07.md`; `data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json` | `9d15ef7`, `23211a7`, `e5bf3a5af325ba0a5263c238a84e714836fb5e92` (merge) | Pinned CSV `sha256=74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717` (recorded in the register doc) | Explicitly `NON_GATING`: no score/class/correlation here feeds `raptor.scorer`, PS3/BS3, or `decide_gate`; the 32-variant overlap is **not independent**; identity matching by exact `c.` HGVS string is an unverified-assumption bridge across `NM_000548.4`/`.5` (documented, not resolved) |
| 10 | Public blog / docs / strategy | Two public progress posts; public GitHub README mirrors the committed census/benchmark figures (independently fetched 2026-07-30) | `docs/blog/2026-07-10-before-the-first-score.md`; `docs/blog/2026-07-23-after-the-first-rerun.md`; `README.md`; `docs/STRATEGY.md`, `docs/EVALUATION.md`, `docs/DECISIONS.md`, `docs/PROGRAM.md`, `docs/ARCHITECTURE.md` | `253c9fd` (post 1), `aa2edfa`/`c8ec5ae` (post 2) | — | Both posts explicitly disclaim "validated"/"works"/"passed the benchmark" language (`docs/prompts/progress-blog/slot3-overclaim-guard.md`) |
| 11 | Team gap: molecular geneticist | `engagement-recruit-molecular-geneticist` status **`in_progress`** (not complete); `core-molecular-geneticist-adjudication` status **`pending`**, zero adjudications recorded | `docs/project/TODOS.yaml`; `docs/RISK_REGISTER.md` row **R-E1** ("No domain oracle is ever recruited") | — | — | No expert has reviewed any packet or Atlas claim; `atlas-phase2-human-span-review` and `engagement-submission-pilot` both depend on this and are `pending` |
| 12 | No prospective PASS / no accepted Phase 2 claim / no second disease | `validate-tiered-gate-prospectively` status `pending`; `atlas-phase2-r611q-anchor`, `atlas-phase2-contrast-panel`, `atlas-phase2-pilot-evaluation` all status `pending`; ADR-0014 explicit: "Core acceptance and a passing `tsc2` pack never imply another disease works" | `docs/project/TODOS.yaml`; `docs/DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary` | — | — | Prospective lock requires the first NCBI ClinVar GRCh38 monthly archive dated ≥2026-08-01, frozen URL/date/MD5/SHA-256 before scoring, else `BLOCKED_DATA` |

## 3. Preliminary assets

**Code** (all merged by evidence-base commit `377abf1`, none exposes real patient/clinical identities):
- `src/raptor/atlas/` — generic-core Mechanism Atlas: `model.py`, `hashing.py`, `identity.py`,
  `ontology.py`, `pack.py`, `profile.py`, `promote.py`, `registry.py`, `guards.py`, `export.py`
  (one-way `DisMechRecord` export), `citation.py` (ADR-0016 deterministic offline resolver).
- `src/raptor/census/` — `strata.py`, `aggregate.py`, `cli.py` (fail-closed census builder).
- `src/raptor/packet/` — `build.py`, `corrected_universe.py`, `git_provenance.py`.
- `src/raptor/external/mave/` — `identity.py`, `endpoint.py`, `metadata.py`, `register.py`,
  `partition.py`, `report.py`, `source.py` (MaveDB orthogonal, non-gating track).
- `src/raptor/eval/mask_clinvar.py` and `scripts/build_masked_holdout_gate_aggregate.py`,
  `scripts/build_corrected_review_packets.py`, `scripts/fetch_mave_scoreset.py`,
  `scripts/build_mave_orthogonal_report.py`, `scripts/build_tsc_benchmark.py`.

**Data contracts:**
- `configs/atlas/packs/tsc2/pack.yaml` (schema `atlas.disease_pack.v1`).
- `configs/atlas/catalogs/` (ADR-0016 catalog template — committed `sources: []` only).
- `configs/eval/*.yaml` (`tsc2.yaml`, `mave_tsc2.yaml`, `core_annotation_bundle.yaml`,
  `bp4pp3_predictor_policy.json`), `configs/external/mave_sources.yaml`.
- `docs/project/specs/*.yaml` — eight implementation-ready specs, including
  `atlas-citation-resolver-v1.yaml`, `mechanism-atlas-starter.yaml` (rev 6),
  `tiered-gate-v3-posthoc.yaml`, `vus-census-disabled-manual.yaml`,
  `pp3bp4-disabled-manual-policy.yaml`, `corrected-review-packets-2026-07.yaml`.

**Evaluations:**
- Frozen benchmark (`data/benchmark/`), full census/gate/audit history in `data/census/`
  (17 committed JSON records plus one `.sha256` manifest).
- Test suites: `tests/atlas/` — **64/64 passing** (`python -m pytest tests/atlas -q`, reproduced
  2026-07-30); `tests/packet/`, `tests/census/`, `tests/external/` together — **112 passed, 3
  skipped**; `tests/eval/` (excluding the `pysam`-dependent CLI contract test) — **668 passed, 6
  skipped**.

**Review artifacts:**
- `docs/reference/corrected-review-packets-runbook.md` (verification order, output layout, known
  limitations); `docs/project/atlas/ATLAS_RUNBOOK.md`, `docs/project/atlas/MECHANISM_ATLAS_HANDOFF.md`
  (explicitly context/query-seed only per ADR-0015).

**Public outputs:**
- `docs/blog/2026-07-10-before-the-first-score.md`, `docs/blog/2026-07-23-after-the-first-rerun.md`,
  and the public repository `README.md` — all on the public `main` branch at `github.com/srinivasdrona/raptor`.

## 4. Honest negative evidence and what changed

- **A named strategic premise was tested and falsified.** ADR-0010 records that RAPTOR's original
  "generic-platform uniqueness" framing did not survive a grounded competitor scan (multiple capable
  variant-interpretation/LLM-ACMG platforms were found); the project explicitly withdrew that claim
  from `STRATEGY.md` and narrowed to a vertical TSC/mTOR research-evidence strategy
  (`docs/DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy`).
- **The binding v1/v2 missense gate returned `FAIL`, not a passing result.** The legacy gate on the
  R2 masked rerun recorded `precision_lb=0.0`, `recall_lb=0.0` for missense
  (`data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json`, `legacy_v1_gate`); this
  is reported unchanged, not hidden.
- **ADR-0013 exists because the v1/v2 reporting overstated what the same frozen data could
  support** — missense pathogenic had 51 actual examples but zero calls, and calling that scope a
  flat `FAIL` alongside a genuinely-passing truncating-pathogenic scope conflated "no data" with
  "failed test." The correction is a post-hoc re-description of frozen numbers, not new evidence
  (`no_new_evidence_statement` embedded in `tsc_tiered_readjudication_2026-07-21.json`), and
  `docs/RISK_REGISTER.md` rows **R-A13/R-A14/R-A15** exist specifically to prevent this
  re-description from being misread as a new pass.
- **The Atlas citation resolver was hardened only after repeated adversarial-checker rejections.**
  Commit history (`2f16b72`, `892092b`, `37ea81d`, `b788525`, `90c400d`, and others) shows multiple
  "GPT-5.4 NOT CLEAN" findings — truthy-boolean resolver spoofing, whitespace-only pins, spoofed
  `text-char` locators, incomplete multi-alias source checks — fixed before the resolver merged
  clean at `dc8826b`.
- **A real data-quality bug was caught, not smoothed over, in the MaveDB overlap track.** A
  pre-existing "verified" overlap fixture was found to carry a consistent one-base-pair genomic
  offset relative to an independent BIAS-2015 reconstruction; the fix anchored identity matching on
  the axis both sources agree on (exact `c.` HGVS string) rather than loosening the fail-loud join
  (`docs/reference/mave-tsc2-source-register-2026-07.md` §2.2).
- **Full-spectrum VUS automation, `PM1`, and REVEL-backed PP3/BP4 all remain blocked**, not quietly
  dropped: `full_spectrum_status=BLOCKED_POLICY`/`NOT_VALIDATED`, `pm1_status=SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH`,
  and corrected PP3/BP4 remains `BLOCKED_POLICY` pending a new owner decision (ADR-0012).

## 5. Claude-specific acceleration opportunities (future work — not achieved)

ADR-0016 already establishes a **deterministic guard boundary** that any future LLM-assisted step
would sit behind, never replace: `src/raptor/atlas/citation.py` verifies source **fidelity and
identity** only (a normalized `PMID`/`PMCID`/`DOI`/`ACCESSION` resolves to a hash-verified,
`role=direct_evidence_leaf` local catalog entry; an `exact_quote` matches a recomputed-from-disk
extracted-text span at a precise character offset) — it does **not**, and is not designed to,
judge scientific sufficiency. A static AST guard (`assert_no_network_imports`) forbids network
imports anywhere in `src/raptor/atlas/`, and the named-human Gate 8 review always runs **after**
deterministic verification and is never replaced by it (ADR-0016 Consequences). Every item below is
a proposed use of that same fail-closed boundary, none of it built:

1. **Primary-source retrieval and span extraction** — populating the (currently `sources: []`)
   catalog with real, licensed PMC/PubMed/dataset content for the R611Q anchor and beyond
   (`atlas-phase2-r611q-anchor`, `tier3-literature-ingestion`, `sources-add-literature-stack`, all
   `pending`). Claude could accelerate candidate identification/extraction, but every candidate
   would still have to clear the existing Gate 3/4 catalog-hash and exact-span checks, and Gate 8
   human sign-off, before it could ground any claim.
2. **Contradiction search** — extracting supported/conflicting/unknown/empty outcomes per variant
   into the Mechanism Atlas schema (ADR-0015 explicitly permits all four outcomes and forbids
   manufacturing a narrative); tracked as `tier3-evidence-extraction-scoring` (`pending`).
3. **Assay-context normalization** — normalizing functional-assay metadata (VAMP-seq, SGE, legacy
   assays) beyond the current single, non-gating MaveDB scoreset; the three larger 2026 datasets
   (IGVF VAMP-seq, IGVF SGE, CAGI7) are registered `confirm_pending` with access not held
   (`assurance-expand-orthogonal-validation`, `pending`).
4. **Evaluations** — `atlas-phase2-pilot-evaluation` (`pending`) proposes measuring source recall,
   valid-span yield, contradiction capture, unsupported-claim rate, context completeness, and
   reproducibility across the R611Q anchor and a contrast panel; this evaluation design exists only
   as a TODO today.
5. **Public DisMech-compatible export** — `src/raptor/atlas/export.py` already implements a
   one-way, no-network `DisMechRecord` shape exercised only by synthetic Phase-1 fixtures
   (`tests/atlas/test_hashing_import_guards.py::test_one_way_dismech_export`); defining a real
   contribution route, schema/ontology/reference validation, and maintainer review is
   `grant-anthropic-dismech-integration-path` (`pending`) — no external contact or contribution has
   been made.

## 6. Six-month milestones (grounded in current TODOs — no projected results)

All items below are copied from `docs/project/TODOS.yaml` status fields at evidence-base
commit `377abf1`; none report a
result because none have run yet. No collaborator, institution, or partner beyond the operator
(`@dronasrinivas`) is named or implied.

| Order | Milestone | TODO id | Status | Depends on |
|---|---|---|---|---|
| 1 | Complete molecular-geneticist recruitment (COI, confidentiality, SLA, adjudication protocol) | `engagement-recruit-molecular-geneticist` | `in_progress` | — |
| 2 | Run molecular-geneticist adjudication of corrected packets | `core-molecular-geneticist-adjudication` | `pending` | #1, `core-generate-review-packets` (done) |
| 3 | Freeze and evaluate the first NCBI ClinVar GRCh38 monthly archive ≥2026-08-01 under the locked ADR-0013 axes | `validate-tiered-gate-prospectively` | `pending` | `revise-tiered-gate-semantics` (done) |
| 4 | Ground the first real R611Q Atlas anchor against primary sources via the merged resolver | `atlas-phase2-r611q-anchor` | `pending` | `atlas-phase2-citation-resolver` (done) |
| 5 | Run the Atlas Phase 2 contrast panel (pathogenic/benign/conflicting/VUS-with-functional-evidence/evidence-poor) | `atlas-phase2-contrast-panel` | `pending` | #4 |
| 6 | Obtain named human-oracle Atlas span review | `atlas-phase2-human-span-review` | `pending` | #1, #4 |
| 7 | Evaluate the bounded Atlas Phase 2 pilot (recall, span yield, contradiction capture, unsupported-claim rate) | `atlas-phase2-pilot-evaluation` | `pending` | #5, #6 |
| 8 | Add versioned open-literature source coverage and continuous Tier-3 ingestion | `sources-add-literature-stack`, `tier3-literature-ingestion` | `pending` | source/version registry + data-rights governance (both `pending`) |
| 9 | Expand independent multi-oracle validation beyond cliPE (legacy assays, phenotype/penetrance, CAGI7 if access obtained) | `assurance-expand-orthogonal-validation` | `pending` | — |
| 10 | Open protocol-compliant TSC Alliance / ClinGen VCEP contact (no fabricated endorsement or timeline) | `engagement-tsc-alliance-vcep-path` | `pending` | — |

## 7. Proposed public outputs (not yet built; no acceptance promised)

- **Evaluation dataset/rubric** — a versioned, public packaging of the existing frozen benchmark and
  scope-lattice thresholds (`docs/EVAL_RUBRIC.md`, `docs/EVAL_PLAN.md`, `docs/EVALUATION.md` Part
  II) for independent reuse. Not yet packaged as a standalone public release.
- **Source-grounded TSC mechanism profiles/hypotheses, after review** — Mechanism Atlas profiles
  released only after ADR-0016 deterministic grounding and named-human Gate 8 review clear
  (§6 items 4–7); framed explicitly as **hypotheses**, never as a claim of ontology stability from a
  single anchor (ADR-0014, ADR-0015).
- **A one-way DisMech-compatible export** — extending the existing internal synthetic
  `export_dismech()` scaffold into a documented, real, one-way export for the verified TSC2 entry,
  once `grant-anthropic-dismech-integration-path` defines the contribution route. This does **not**
  promise Monarch/DisMech maintainer acceptance, review outcome, or origin-branch access.
- **A methods/failure report** — a public report, in the spirit of the two existing blog posts,
  documenting what passed, what failed (§4), and what remains unresolved.

## 8. Limitations, team, dependencies, and exact pending tasks

**Team.** One operator (`@dronasrinivas`) directing a three-model-family planner/doer/checker loop
(`docs/STRATEGY.md#strategy-part-ii`); no molecular geneticist engaged yet (row 11, §2); no
institutional affiliation is claimed or implied.

**Dependencies before any authoritative claim:**
- The first NCBI ClinVar GRCh38 `variant_summary` monthly archive dated on/after 2026-08-01, with
  its URL/date/MD5/SHA-256 frozen before any scoring (ADR-0013); absence or invalidity is recorded
  as `BLOCKED_DATA` with no outcome-dependent substitute.
- Completed molecular-geneticist recruitment and adjudication (§6 items 1–2, 6).
- A live source/version/refresh registry and data-rights/privacy governance before literature
  ingestion expands (`sourceops-version-refresh-registry`, `governance-data-rights-privacy`, both
  `pending`).
- Optional, currently unheld access to IGVF VAMP-seq/SGE and the CAGI7 TSC2 challenge (registered
  `confirm_pending` in `configs/external/mave_sources.yaml`).
- Resolution of Anthropic program eligibility, public-output requirements, and data-licence terms
  before submission (`grant-anthropic-eligibility-data-terms`, `pending`).

**Exact pending tasks** (verbatim ids from `docs/project/TODOS.yaml`, all `pending` unless noted):
`core-molecular-geneticist-adjudication`, `validate-tiered-gate-prospectively`,
`atlas-phase2-r611q-anchor`, `atlas-phase2-contrast-panel`, `atlas-phase2-human-span-review`,
`atlas-phase2-pilot-evaluation`, `engagement-tsc-alliance-vcep-path`, `engagement-submission-pilot`,
`sources-add-literature-stack`, `tier3-literature-ingestion`, `tier3-evidence-extraction-scoring`,
`tier3-continuous-vus-monitoring`, `assurance-expand-orthogonal-validation`,
`sourceops-version-refresh-registry`, `sourceops-automated-refresh-validation`,
`sourceops-drift-revalidation-gates`, `governance-data-rights-privacy`,
`grant-anthropic-eligibility-data-terms`, `grant-anthropic-dismech-integration-path`,
`grant-anthropic-submission-package`, `evaluate-discovery-packet-auditor`; plus
`engagement-recruit-molecular-geneticist` (`in_progress`).

## 9. Verified commits, hashes, and reproducibility commands

Every commit below was confirmed present with `git cat-file -e <sha>` and confirmed an ancestor of
evidence-base commit `377abf1` with `git merge-base --is-ancestor <sha> 377abf1`
(exit code `0`) on 2026-07-30.

| Commit | Subject |
|---|---|
| `377abf1689a2c2658d23f61bdc80a9f9376de9cd` (**evidence base**) | docs(project): complete Atlas citation resolver |
| `dc8826b` | merge: add offline Atlas citation and span resolver |
| `c56cb8914b8bf91b40a81f41fb7c5d8140e13f38` | fix(eval): require clean tiered-gate provenance |
| `9709ec6` | merge: add portable Mechanism Atlas Phase 1 |
| `e55f9e6` | plan(atlas): rev6 generic Atlas core + versioned disease-pack boundary (ADR-0014) |
| `8669d31` | feat(atlas): use R611Q as the first grounded Phase 2 anchor (ADR-0015) |
| `338911e` | docs(atlas): plan Phase-2 offline citation & exact-span resolver (ADR-0016) |
| `ea90921` | data(eval): freeze tiered gate v3 re-adjudication (ADR-0013) |
| `48dd0b4` | docs(adr): accept disabled PP3/BP4 mode for masked rerun (ADR-0012) |
| `ec34aba` | data(census): freeze ADR-0012 VUS recomputation |
| `071111e33579ed1014b92cea77ab2eb7ca2312c0` | merge: generate corrected all-VUS review packets |
| `2e3477f` / `8662499` | benchmark freeze / holdout-0.7 adoption |
| `e5bf3a5af325ba0a5263c238a84e714836fb5e92` | merge: orthogonal TSC2 MAVE validation track |
| `253c9fd` / `aa2edfa` / `c8ec5ae` | first blog post / second blog post / post-rerun merge |
| `e6ee7f1` | docs(program): order the governed source-expansion roadmap |

**Reproducibility commands** (run from the repository root on a clean checkout of `377abf1`):

```powershell
# Confirm evidence base and commit ancestry
git rev-parse 377abf1
git merge-base --is-ancestor <sha> 377abf1   # exit 0 => ancestor confirmed

# Recompute a canonical (LF, no-BOM) artifact hash exactly as the repo pins it —
# do NOT hash the raw Windows/CRLF checkout, it differs (see spec files' own
# "sha256_windows_crlf_checkout_do_not_pin" fields)
git cat-file -p 377abf1:data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json > blob.tmp
python -c "import hashlib;print(hashlib.sha256(open('blob.tmp','rb').read()).hexdigest())"
Remove-Item blob.tmp

# Atlas test count and pass/fail (reproduced 2026-07-30: 64 passed)
git grep -c "def test_" 377abf1 -- tests/atlas/
python -m pytest tests/atlas -q

# Packet/census/external suites (reproduced 2026-07-30: 112 passed, 3 skipped)
python -m pytest tests/packet tests/census tests/external -q

# Eval suite excluding the optional pysam-dependent CLI contract test
# (reproduced 2026-07-30: 668 passed, 6 skipped; running the full repo test
# suite together surfaces two environment-specific issues unrelated to the
# claims in this ledger — a missing optional `pysam` dependency and a
# cross-directory pytest conftest name collision — neither reproduces when
# the affected suites are run in isolation as above)
python -m pytest tests/eval -q --ignore=tests/eval/test_live_eval_export.py
```

---

**Result summary:** 12 fact-ledger rows (§2), 15 verified commit rows / 18 distinct commits (§9),
10 six-month milestones
(§6, all grounded in existing `pending`/`in_progress` TODOs), zero projected results, zero
fabricated collaborators, zero use of "clinical validation," "reclassification," "first in world,"
"production-ready," or any funding-amount figure. Unresolved gaps carried forward: no molecular
geneticist yet engaged; no prospective ClinVar-archive validation run; no real (non-synthetic)
Atlas source grounded; Anthropic eligibility/data-terms and the DisMech contribution route both
remain undefined pending owner decisions.
