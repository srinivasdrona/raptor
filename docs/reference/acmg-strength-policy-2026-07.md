# ACMG criterion-strength policy reconciliation — status: unapproved (2026-07)

| Field | Value |
|---|---|
| Status | Reference / decision support, **non-clinical, non-authoritative, planning-only** |
| Decision | **Unapproved.** `configs/acmg/strength_policy.yaml`: `status: unapproved`, `owner_approved: false` — every call this policy sees resolves to `manual` (fail-closed) regardless of the schema-valid `disposition` a record configures (`raptor.scorer.strength_policy.apply_strength_policy`). Not wired into production or eval in this track. |
| Track | `strength-policy-2026-07` (this DOER never self-approves; approval is an explicit owner action, out of scope here) |
| BIAS pin reviewed | commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f` (`bias_version: 3.0.0`), local clone `D:\AIProjects\raptor-data\sources\BIAS-2015` |
| RAPTOR corpus (materiality only) | ClinVar 2026-07-07, 6,618 TSC1/TSC2 VUS (`tsc_vus_input.bias_output.tsv`) — **label-free**, no ClinVar/held-out truth read |
| Ladder | [`configs/eval/bias_strength_ladder.yaml`](../../configs/eval/bias_strength_ladder.yaml) |
| Policy (unapproved) | [`configs/acmg/strength_policy.yaml`](../../configs/acmg/strength_policy.yaml) |
| Loader/apply | [`src/raptor/scorer/strength_policy.py`](../../src/raptor/scorer/strength_policy.py) |
| Materiality probe | [`scripts/run_strength_materiality_probe.py`](../../scripts/run_strength_materiality_probe.py), [`src/raptor/scorer/strength_materiality.py`](../../src/raptor/scorer/strength_materiality.py) |
| Machine-readable aggregate | [`data/census/tsc_strength_policy_materiality_2026-07-13.json`](../../data/census/tsc_strength_policy_materiality_2026-07-13.json) |

> **Reading rule.** This memo characterizes a schema/config reconciliation and a label-free materiality
> probe; it does not classify, score, or promote any variant, and it does not activate any policy. Every
> `accept`/`cap` disposition below is currently schema-valid but **inert** — `status: unapproved` forces
> `manual` for every call until an owner explicitly flips `status`/`owner_approved` (a separate act from
> anything in this track).

---

## 1. What problem this reconciles

The pinned, arm's-length BIAS-3.0.0 rule engine (ADR-0007: RAPTOR never imports it, only reads its
committed TSV output) internally computes a **strength** (supporting/moderate/strong/very_strong) for
several criteria using its own thresholds — a mechanical implementation detail of BIAS's own code, not an
ACMG/ClinGen guideline value. RAPTOR's current scorer (`configs/acmg/tsc.yaml::acmg_criteria`) only
recognizes a **fixed subset** of strengths per criterion (its "vocab"). Reading BIAS's classifier source
(`pathogenic_classifiers.py`, `benign_classifiers.py`, pinned commit above) shows 7 criteria — **PS1, PM2,
PM4, PM5, BP3, BP4, BS1** — where BIAS can structurally emit a strength **outside** that current vocab.
`strength_policy.py` gives every such (criterion, strength) pair an explicit, typed, fail-closed
disposition (`accept` / `cap` / `manual` / `forbid`) instead of letting it silently drop or silently
inflate. This document cites the primary/official sources this reconciliation is grounded in, and states
plainly what authority does — and does not — exist for it.

## 2. Primary/official sources

| # | Source | Type | What it grounds here |
|---|---|---|---|
| 2.1 | Richards S, Aziz N, Bale S, et al. "Standards and guidelines for the interpretation of sequence variants: a joint consensus recommendation of ACMG and AMP." *Genetics in Medicine*. 2015;17(5):405–424. doi:10.1038/gim.2015.30. PMC4544753. | PRIMARY-OFFICIAL | Defines the five ACMG/AMP strength tiers (supporting/moderate/strong/very_strong, plus stand-alone for PVS1/BA1) that both BIAS's internal scoring and RAPTOR's `strength_map`/`VALID_STRENGTHS` (`raptor.scorer.config`) already encode. This is the *only* normative source for what a "strength tier" means; it does not define BIAS's internal thresholds or RAPTOR's vocab. |
| 2.2 | Tavtigian SV, Greenblatt MS, Harrison SM, et al. "Modeling the ACMG/AMP variant classification guidelines as a Bayesian classification framework." *Genetics in Medicine*. 2018;20(9):1054–1060. doi:10.1038/gim.2017.210. | PRIMARY-OFFICIAL | The published point system (`tavtigian_points`/`tavtigian_cutoffs`, `configs/eval/tsc2.yaml`) reused **unmodified, read-only** by this track's materiality probe to report an eval-only, label-free implied LP/LB/no-call pattern for rows carrying an out-of-vocab strength — never used to select or justify a disposition. |
| 2.3 | Pejaver V, Byrne AB, Feng B-J, et al. "Calibrating the ClinGen/ClinVar Pathogenicity Guidelines Using a Quantitative Bayesian Framework." *Genetics in Medicine*. 2022;24(1):51–63. doi:10.1016/j.gim.2021.09.012. | PRIMARY-OFFICIAL | Independent confirmation that the five ACMG strength tiers carry monotonically increasing calibrated odds — i.e. why `cap` may only ever demote to a *strictly weaker*, never a stronger or equal, in-vocab tier ("cap never inflates" is not an arbitrary RAPTOR rule; it follows from the tiers' own calibrated ordering). |
| 2.4 | Symonds JD, et al. "ClinGen TSC1/TSC2 Variant Curation Expert Panel specifications for the ACMG/AMP variant classification guidelines." *Genetics in Medicine*. 2022;24(9):1907–1919. doi:10.1016/j.gim.2022.06.001. PMID: 35654857. (already cited: `docs/reference/eval-rubric-evidence-base.md` §1.4) | PRIMARY-OFFICIAL | The one published, gene/disease-specific ClinGen VCEP specification for TSC1/TSC2 — see §3 below for exactly what it does and does not cover. |
| 2.5 | `pathogenic_classifiers.py`, `benign_classifiers.py`, `constants.py` — pinned BIAS-3.0.0, commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`, `D:\AIProjects\raptor-data\sources\BIAS-2015` | INTERNAL (arm's-length, read-only, never imported/copied) | The exact reachable-strength facts, cited by file/symbol/line in `configs/eval/bias_strength_ladder.yaml` — the ladder this policy reconciles against. |

## 3. No ClinGen authority governs *this specific* reconciliation

A published ClinGen TSC1/TSC2 VCEP specification **does exist** (Symonds et al. 2022, §2.4) — it defines
gene/disease-specific calibrations for population-frequency thresholds, PVS1 transcript caveats, PP2, and
functional-assay criteria for TSC1/TSC2, validated on a ~50-variant pilot set. It is a real, citable
authority for *how TSC1/TSC2 ACMG criteria should be interpreted*.

**It does not, however, address the question this document and policy answer.** Symonds 2022 is silent on
what a *rule-engine implementation's own internal strength computation* (BIAS-3.0.0's mechanical
thresholds) should do when it disagrees with a *particular downstream tool's* (RAPTOR's) configured
strength vocabulary — that is an engineering/config reconciliation problem, not an ACMG-strength-assignment
guideline question. No ClinGen TSC VCEP or SVI document specifies, approves, or is aware of BIAS-3.0.0's
exact reachable-strength ladder (§2.5 above — several of these facts, e.g. PS1's dead-code moderate-only
behavior, are not documented anywhere outside this track's own source audit). **No ClinGen-approved
specification exists for this specific strength-ladder/current-vocab reconciliation**, and none is
fabricated or implied here. This absence of authority is exactly why `configs/acmg/strength_policy.yaml`
stays `status: unapproved` — every disposition it configures is schema-valid and activatable, but
activation itself requires an explicit, cited, out-of-band owner decision, never a default in this file.

**No production approval of any kind has occurred in this track.** The policy is not wired into
`src/raptor/eval/` or any production packet/candidate-direction path (`src/raptor/packet/direction.py`);
that wiring and the parallel, purely-mechanical current-vocab enforcement belong to a separate parity
track and to an explicit owner decision, neither of which this track performs.

## 4. Reconciliation summary (current-vocab vs. BIAS-3.0.0 ladder)

| Criterion | Current scorer vocab (`configs/acmg/tsc.yaml`) | BIAS-3.0.0 reachable ladder | Disposition per strength (schema-valid, **inert** while unapproved) |
|---|---|---|---|
| PS1 | `[strong]` | `[moderate]` (supporting/strong are dead code — `pathogenic_classifiers.get_ps1` L179-187) | moderate → **manual** (no valid accept/cap target exists at all: moderate not in vocab, and there is nothing weaker to cap to) |
| PM2 | `[supporting, moderate]` | `[supporting, moderate, strong]` | supporting/moderate → **accept**; strong → **cap → moderate** |
| PM4 | `[moderate]` | `[supporting, moderate, strong]` | supporting → **manual** (unresolved fork, §5); moderate → **accept**; strong → **cap → moderate** |
| PM5 | `[moderate, strong]` | `[supporting, moderate, strong]` | supporting → **manual**; moderate/strong → **accept** |
| BP3 | `[supporting]` | `[supporting, strong]` (no moderate — code jumps supporting→strong) | supporting → **accept**; strong → **cap → supporting** |
| BP4 | `[supporting]` | `[supporting, strong, very_strong]` (no moderate; very_strong genuinely reachable via REVEL/multi-tool agreement, not just "elevated" shorthand) | supporting → **accept**; strong/very_strong → **cap → supporting** (unresolved fork, §5) |
| BS1 | `[moderate, strong]` | `[supporting, strong]` (no moderate — `elif` skips it) | supporting → **manual**; strong → **accept** |

Full per-record rationale (including gene-override scope, currently empty) is in
`configs/acmg/strength_policy.yaml`; full source-line citations are in
`configs/eval/bias_strength_ladder.yaml`.

## 5. Unresolved owner forks (this DOER does not decide these)

1. **PM4 supporting** (`decision_dependency: pm4-supporting-vocab-widening-or-forbid`): either (a) widen
   PM4's scorer vocab to admit `supporting` and then `accept` it, or (b) leave PM4-supporting firings
   permanently `forbid`-dropped below the current 1-tier vocab floor. `manual` (never silently dropped) is
   the safer placeholder until an owner picks (a) or (b).
2. **BP4 elevated (strong/very_strong)** (`decision_dependency: bp4-elevated-cap-vs-forbid`): either (a) cap
   both down to `supporting` (preserves a benign-direction signal at lower confidence), or (b) `forbid` them
   outright, given BP4's own aggregation defect (`bias_bp4_pp3_aggregation_defect`,
   `configs/eval/bias_lineage.yaml`) may already inflate its strength beyond what the underlying per-tool
   evidence supports. `manual` (never silently dropped/promoted) is the safer placeholder until an owner
   picks (a) or (b) — same treatment as PM4 supporting above; this file does not pre-select cap or forbid.

## 6. Corrections vs. the planner's summary card text

The originating task's planner-card shorthand differs from this DOER's own rigorous BIAS-source audit in
three places; the policy file implements the audited, source-grounded behavior and documents the
discrepancy explicitly (never silently overriding the planner without a note):

- **PS1** — planner said "moderate/supporting accept after mask." Supporting is **not reachable at all**
  in the pinned source (dead code, §4); there is no supporting decision to make, and moderate stays
  `manual` (out-of-vocab with no valid cap target), never `accept`, pending a vocab-widening decision this
  track does not make.
- **BS1** — planner said "supporting accept." This is schema-**impossible** under the current vocab:
  `accept` requires the emitted strength to already equal the requested (in-vocab) strength, and `cap` can
  never promote supporting up to moderate/strong. Corrected to `manual`.
- **PM2 strong** — planner text loosely suggested "cap to supporting"; the tester's own contract fixture
  (authoritative, passing) and this policy both cap PM2-strong to **moderate** (the nearest in-vocab,
  strictly-weaker tier — less lossy than jumping to supporting).

## 7. Materiality headline (label-free, 6,618 VUS)

See `data/census/tsc_strength_policy_materiality_2026-07-13.json` for the full aggregate. Headline:

- **1,791 / 6,618 rows (27.1%)** carry ≥1 out-of-vocab (criterion, strength) firing among the 7 tracked
  criteria; **effectively 100% of the out-of-vocab calls on those rows currently route to `manual`**
  (`by_effective_disposition.manual = 1968` calls), because the policy is unapproved — this is the trivial,
  expected fail-closed fact, reported for completeness, not as a finding.
- By criterion/strength (out-of-vocab emission counts): BP4-strong 1,365; PM2-strong 338; PM4-supporting
  137; PS1-moderate 110; PM4-strong 9; BP3-strong 7; PM5-supporting 2.
- By gene: TSC2 1,075; TSC1 713; NTHL1 3 (an off-target/adjacent-gene row present in the source TSV, not a
  TSC1/TSC2 v1-scope gene).
- By variant class: missense 1,457; other 324; truncating 10.
- Eval-only, label-free implied pattern among affected rows (non-authoritative,
  `raptor.eval.combine.implied_direction`, reused read-only): LB 1,277; no_call 463; LP 51.
- **Hypothetical-only** hypothetical-recommended-scenario (simulating every record's
  `recommended_disposition`/`recommended_emit` as if approved — never active): 1,719 calls would resolve
  via `cap`, 249 would remain `manual` (110 PS1-moderate + 137 PM4-supporting + 2 PM5-supporting — exactly
  the pairs with no schema-valid accept/cap target even under the recommended metadata). This is a planning
  aid only, computed in-memory by the probe, never persisted as an active policy.

## 8. Non-goals / scope boundary

- This track does not wire `strength_policy.py`/`strength_policy.yaml` into `src/raptor/eval/` or
  `src/raptor/packet/` — a separate parity track handles mechanical current-vocab enforcement, and
  activation of this policy waits for an explicit owner decision (`status: approved` + `owner_approved:
  true`), never a self-approval.
- No external BIAS source, threshold, production candidate policy, or current gate aggregate/doc was
  edited to produce this reconciliation.
- The materiality probe (`scripts/run_strength_materiality_probe.py`) never reads a ClinVar/held-out truth
  label, never selects a disposition based on one, and never persists a per-variant identity (chromosome/
  position/ref/alt/variant_id) — only the aggregates above.
