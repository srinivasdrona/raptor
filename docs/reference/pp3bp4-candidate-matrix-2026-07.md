# RAPTOR PP3/BP4 candidate predictor matrix (Slot 3, shadow-only)

| Field | Value |
|---|---|
| Status | **PROPOSED / UNAPPROVED / SHADOW ONLY** |
| Date | 2026-07-18 |
| Scope | TSC1/TSC2 missense computational evidence; research use only |
| Backing config | `configs/eval/pp3bp4_source_register.yaml` |
| Backing policy | `configs/eval/pp3bp4_candidate_policy.json` (`policy_id: tsc-pp3bp4-revel-shadow`, `status: proposed`) |

> **Reading rule.** This matrix records candidate predictor disposition for the shadow REVEL
> PP3/BP4 policy implementation (RAPTOR PP3/BP4 shadow policy, steps 2-7). It does not approve a
> predictor, activate a scorer, classify a variant, authorize a VUS worklist, or approve clinical
> use. It supersedes no primary source in
> `docs/reference/pp3-bp4-predictor-policy-recommendation-2026-07.md`.

## 1. Verified facts vs confirm-pending values

The following are **verified** (source register `required_primary_sources`, `verification: verified`):

- Pejaver et al. 2022 (DOI 10.1016/j.ajhg.2022.10.013; PMID 36413997; PMC9748256) publishes REVEL's
  calibrated PP3/BP4 score intervals (Table 2) this policy's `pp3`/`bp4`/`indeterminate` thresholds
  reproduce exactly (`configs/eval/pp3bp4_candidate_policy.json`).
- Stenton et al. 2024 (PMID 39030733; PMC11560577, Box 1) documents single-tool, preselected,
  cherry-pick-free implementation guidance.
- Richards et al. 2015 (DOI 10.1038/gim.2015.30; PMID 25741868; PMC4544753) defines PP3/BP4 as
  computational evidence, applied once per variant.
- Tavtigian et al. 2018 (DOI 10.1038/gim.2017.210) defines the Bayesian evidence-strength model the
  PP3/BP4 strength ladder (supporting/moderate/strong) is drawn from.

The following are **confirm-pending** (not yet independently verified against a pinned release):

- REVEL `predictor_version`/`data_version` (currently `confirm-pending-revel-dbnsfp-release` /
  `confirm-pending-dbnsfp-release`).
- REVEL license/permitted-use record (`license_status: confirm_pending`).
- Structured REVEL/dbNSFP annotation runtime availability (none is currently provisioned).
- Training-overlap status against the TSC1/TSC2 benchmark (`training_overlap_status: UNKNOWN`).
- Transportability to TSC1/TSC2 (`transportability_status: BLOCKED_DATA`, predeclared
  `UNDERPOWERED` -- dev missense pathogenic count is 24, below the 36-count power floor).

## 2. Candidate matrix

| Candidate | Kind | Calibration source | Version status | License status | Structured score availability | Training-manifest status | TSC-specific evidence | Decision |
|---|---|---|---|---|---|---|---|---|
| REVEL | meta_predictor | Pejaver 2022 | confirm_pending | confirm_pending | blocked_data | unavailable | none_identified | **advance_shadow** |
| BayesDel-noAF | meta_predictor | Pejaver 2022 | confirm_pending | confirm_pending | unavailable | unavailable | none_identified | blocked_shadow_comparator |
| MutPred2 | predictor | Pejaver 2022 | confirm_pending | confirm_pending | unavailable | unavailable | none_identified | blocked_shadow_comparator |
| VEST4 | predictor | Pejaver 2022 | confirm_pending | confirm_pending | unavailable | unavailable | none_identified | blocked_shadow_comparator |
| BIAS composite | composite | none | pinned_bias_3_0_0_commit_ade13f2 | arm_length_agpl | reconstructed_only | inherited_unknown | none_identified | audit_only_reject_authoritative |

REVEL is the sole candidate advanced into the shadow lane (`configs/eval/pp3bp4_candidate_policy.json`,
`status: proposed`, `shadow_only: true`, `owner_approved: false`). This is **not** a production
predictor selection -- every activation-checklist item in section 8 of
`pp3-bp4-predictor-policy-recommendation-2026-07.md` remains unmet.

## 3. Known historical held-out outcome (acknowledged, not used for choice/tuning)

The 2026-07-13 masked held-out terminal gate
(`data/census/tsc_masked_holdout_gate_2026-07-13.json`) returned **FAIL** on the binding missense
stratum under the prior BIAS/RAPTOR `max_plus_consensus` reconstruction; `vus_authorized` is
`false`. This shadow REVEL policy implementation:

- does not read that held-out result, any held-out score, or any VUS criterion output;
- does not tune a threshold, interval, or predictor choice against that outcome;
- does not reinterpret or supersede that historical record.

## 4. Current generated artifacts (all BLOCKED_DATA/UNKNOWN)

| Artifact | Schema | Status |
|---|---|---|
| `data/census/tsc_predictor_leakage_audit_2026-07.json` | `tsc-predictor-leakage-audit/1` | `UNKNOWN` |
| `data/census/tsc_pp3bp4_dev_score_acquisition_2026-07.json` | `tsc-pp3bp4-dev-score-acquisition/1` | `BLOCKED_DATA` |
| `data/census/tsc_pp3bp4_transportability_2026-07.json` | `tsc-pp3bp4-transportability/1` | `BLOCKED_DATA` (`power_status: UNDERPOWERED`) |
| `data/census/tsc2_pp3bp4_revel_mave_concordance_2026-07.json` | `tsc2-pp3bp4-revel-mave-concordance/1` | `BLOCKED_DATA` (`validation_mode: NON_GATING`) |

None of these artifacts constitutes transportability validation, leakage clearance, clinical
classification, VUS worklist authorization, or ClinVar submission evidence.
