# RAPTOR PP3/BP4 REVEL shadow policy preregistration (Slot 3)

| Field | Value |
|---|---|
| Status | **PROPOSED / UNAPPROVED / SHADOW ONLY** |
| Date | 2026-07-18 |
| Scope | TSC1/TSC2 missense computational evidence; research use only |
| Policy artifact | `configs/eval/pp3bp4_candidate_policy.json` (`policy_id: tsc-pp3bp4-revel-shadow`) |
| Source register | `configs/eval/pp3bp4_source_register.yaml` |

> **Reading rule.** This is a preregistration of the intended dev-only transportability check for
> the shadow REVEL PP3/BP4 policy. It fixes the metrics and thresholds a future run would be
> evaluated against BEFORE any dev REVEL score exists -- it activates no policy, changes no
> production threshold, and authorizes no clinical classification, VUS worklist, or ClinVar
> submission.

## 1. What is being preregistered

Once a dev REVEL score table is produced and attested
(`raptor.eval.pp3bp4_score_table.load_and_validate_score_table`), a future
`scripts/build_pp3bp4_transportability_report.py` run would evaluate REVEL's calibrated Pejaver-2022
PP3/BP4 intervals against the **dev partition only** (1,104 of 3,681 TSC1/TSC2 missense+truncating
benchmark variants; `raptor.eval.split.split_benchmark`, seed `20260701`, `holdout_fraction: 0.7`).
It would never read the held-out partition (2,577 variants) or any VUS criterion output.

## 2. Predeclared metrics and scope

- **Scope:** TSC1/TSC2 missense variants only (`consequence_routing.missense_variant: revel_policy`;
  splice/other consequences are `out_of_scope`).
- **Predeclared metrics:** precision, recall, concordance -- computed per PP3/BP4 call bucket
  against dev labels, never against held-out labels.
- **Dev missense composition** (derived from the real benchmark + `configs/eval/tsc2.yaml`, never
  hardcoded): pathogenic 24 (P 14 + LP 10), benign 49 (B 46 + LB 3).
- **Power floor:** 36 per direction (matching `configs/eval/tsc2.yaml`'s `min_count_per_class`).
  Dev pathogenic count (24) is below this floor -- the transportability assessment is predeclared
  **UNDERPOWERED** before any score is read, per Gary Klein pre-mortem discipline: this is not a
  result to be discovered later, it is a known structural limitation acknowledged now.

## 3. Known historical held-out outcome (acknowledged, never used for tuning)

The 2026-07-13 masked held-out terminal gate result
(`data/census/tsc_masked_holdout_gate_2026-07-13.json`, status `FAIL` on the binding missense
stratum under the prior BIAS/RAPTOR reconstruction) is acknowledged here explicitly. This
preregistration:

- fixes the REVEL intervals from the independently published Pejaver 2022 Table 2 -- it does not
  derive, adjust, or select any threshold from that or any other held-out/terminal result;
- fixes the dev/holdout split from the pre-existing, independently seeded `configs/eval/tsc2.yaml`
  split -- it does not carve a new split favorable to REVEL;
- commits, before any dev REVEL score is read, that an UNDERPOWERED dev pathogenic count will be
  reported as UNDERPOWERED, not silently omitted or reframed as inconclusive-but-promising.

## 4. Forbidden actions (hard boundaries)

- No held-out score, held-out criterion output, or VUS criterion output may be read by any step in
  this pipeline (`raptor.eval.pp3bp4_transportability.evaluate_transportability` fails loud on any
  held-out/extra id).
- No censored free-form BIAS-rationale token may be treated as a structured REVEL score
  (`source == "bias_rationale"` rows are rejected loudly in both
  `pp3bp4_candidate_policy.build_shadow_report` and `pp3bp4_score_table.load_and_validate_score_table`).
  ```yaml
  hard_boundaries:
    - No test or implementation may use held-out scores, held-out criterion outputs, or VUS criterion outputs.
    - No censored REVEL token parsed from BIAS rationale is an accepted score source.
    - No new shadow module is imported by existing production scorer, eval runner, gate, packet, or VUS paths.
    - MAVE values and functional classes never enter predictor policy or classifier arguments.
  ```
- No threshold in `configs/eval/pp3bp4_candidate_policy.json` may be tuned against any future dev or
  held-out result -- the Pejaver 2022 Table 2 intervals are frozen as published.
- MAVE functional class/value (`scripts/build_pp3bp4_revel_mave_concordance.py`) never reaches the
  REVEL policy or classifier arguments -- it is concordance-layer input only, non-gating.

## 5. Current status

No dev REVEL score table exists yet
(`data/census/tsc_pp3bp4_dev_score_acquisition_2026-07.json`, status `BLOCKED_DATA`). The
transportability artifact
(`data/census/tsc_pp3bp4_transportability_2026-07.json`, status `BLOCKED_DATA`,
`power_status: UNDERPOWERED`) records exactly the predeclared metrics/scope/power status above and
nothing more -- it is not itself a transportability result.
