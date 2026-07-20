# RAPTOR PP3/BP4 candidate predictor matrix (Slot 3, shadow-only)

| Field | Value |
|---|---|
| Status | **PROPOSED / UNAPPROVED / SHADOW ONLY** |
| Date | 2026-07-18 |
| Scope | TSC1/TSC2 missense computational evidence; research use only |
| Backing config | `configs/eval/pp3bp4_predictor_matrix.yaml` |
| Backing policy | `configs/eval/pp3bp4_candidate_policy.json` (`policy_id: tsc-pp3bp4-revel-shadow`, `status: proposed`) |

> **Reading rule.** This matrix records candidate predictor disposition for the shadow REVEL
> PP3/BP4 policy implementation (RAPTOR PP3/BP4 shadow policy, steps 2-7). It does not approve a
> predictor, activate a scorer, classify a variant, authorize a VUS worklist, or approve clinical
> use. It supersedes no primary source in
> `docs/reference/pp3-bp4-predictor-policy-recommendation-2026-07.md`.

> **Backing-config migration.** The comprehensive 16-tool + `bias_composite` decision matrix below
> is now backed by the new standalone canonical machine matrix
> `configs/eval/pp3bp4_predictor_matrix.yaml` (schema `pp3bp4-predictor-matrix/1`).
> `configs/eval/pp3bp4_source_register.yaml` remains, unchanged, the existing REVEL PP3/BP4
> shadow-policy **provenance register only** -- it is not the backing config for this comprehensive
> matrix and was not touched by this expansion.

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

| Candidate ID | Display name | Tool kind | Evidence role | Calibration source | Decision |
|---|---|---|---|---|---|
| `revel` | REVEL | meta_predictor | calibrated_missense | Pejaver 2022, Table 2 | **advance_shadow** |
| `bayesdel_noaf` | BayesDel (no allele frequency) | meta_predictor | calibrated_missense | Pejaver 2022, Table 2 | eligible_primary_candidate |
| `mutpred2` | MutPred2 | predictor | calibrated_missense | Pejaver 2022, Table 2 | eligible_primary_candidate |
| `vest4` | VEST4 | predictor | calibrated_missense | Pejaver 2022, Table 2 | eligible_primary_candidate |
| `alphamissense` | AlphaMissense | predictor | calibrated_missense | Bergquist 2025, Table 1 | eligible_primary_candidate |
| `esm1b` | ESM1b | predictor | calibrated_missense | Bergquist 2025, Table 1 | eligible_primary_candidate |
| `varity_r` | VARITY_R | predictor | calibrated_missense | Bergquist 2025, Table 1 | eligible_primary_candidate |
| `cadd` | CADD | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `evolutionary_action` | Evolutionary Action | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `fathmm` | FATHMM | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `gerp_plus_plus` | GERP++ | conservation | conservation_context | Pejaver 2022, Table 2 | shadow_comparator |
| `mpc` | MPC | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `phylop` | PhyloP | conservation | conservation_context | Pejaver 2022, Table 2 | shadow_comparator |
| `polyphen2_humvar` | PolyPhen-2 HumVar | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `primateai_original` | PrimateAI | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `sift` | SIFT | predictor | calibrated_missense | Pejaver 2022, Table 2 | shadow_comparator |
| `bias_composite` | BIAS composite (reconstructed max_plus_consensus) | composite | audit_only | none (audit reconstruction only) | audit_only_reject_authoritative |

Notes:

- This table is the human rendering of the canonical machine matrix
  `configs/eval/pp3bp4_predictor_matrix.yaml` (schema `pp3bp4-predictor-matrix/1`). Candidate IDs
  and dispositions above must match that file exactly; see the machine matrix for the full
  fact-object detail (status/value/source_ids/cp_ids) behind every cell.
- `gerp_plus_plus` and `phylop` carry `evidence_role: conservation_context` -- a distinct policy
  role within the calibrated set, not an extra independent PP3/BP4 vote and not a splice policy.
- Only `revel` carries `status: verified` calibrated score intervals; every other candidate's
  interval fields are `status: confirm_pending` with a resolving `cp_id` in the machine matrix's
  `confirm_pending_register`.
- REVEL is the sole candidate advanced into the shadow lane (`configs/eval/pp3bp4_candidate_policy.json`,
  `status: proposed`, `shadow_only: true`, `owner_approved: false`). This is **not** a production
  predictor selection -- every activation-checklist item in section 8 of
  `pp3-bp4-predictor-policy-recommendation-2026-07.md` remains unmet. No other candidate above is
  `advance_shadow`; the matrix adds 16-tool decision support, not 16 integrations.

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
