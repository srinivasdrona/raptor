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

`tsc_calibration_batch_2026-07-11.json` records the non-identifying aggregate
for the real provisional calibration batch: 1,571 candidate-universe packets,
30 selected packets covering all 20 LP + 10 LB evidence patterns, both genes,
all observed variant classes and edge flags, and zero missing populated atoms.
Full packet/first-pass artifacts remain outside the repository.

The 2026-07-12 policy reports record the arm's-length BP4/PP3 correction
materiality, the 34-firing BS2 deferral analysis, and canonical
transcript/NTHL1 reconciliation. They are engineering/policy evidence, not
variant classifications.
