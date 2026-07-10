# Deterministic evidence censuses

Aggregate, label-free run statistics only. Per-variant VUS identities, BIAS
outputs, and manifests remain outside the repository.

`tsc_vus_clinvar_2026-07-07_stats.json` records the first complete TSC1/TSC2
VUS deterministic evidence census. Candidate LP/LB directions are internal,
eval-only triage signals—not validated classifications.

`tsc_vus_aavc_overlap_2026-07-10.json` records the aggregate, non-authoritative
comparison with AAVC's ClinVar September-2024 classification release. AAVC
machine classes are an external prior-art comparator, never truth labels or
ACMG evidence. Reproduce the aggregate from the external release and RAPTOR
run artifacts with `scripts/audit_aavc_overlap.py`.

`tsc_bias_lineage_audit_2026-07-10.json` records the static BIAS-3.0.0 lineage
policy roll-up and aggregate incidence from the 6,618-VUS and 2,577-held-out
runs. Both runs fail closed on PS1/PM5. Dynamic firing counts never establish
lineage; detailed reports with bounded example identities remain outside the
repository.
