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
