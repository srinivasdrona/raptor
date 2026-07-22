"""`raptor.external.mave` — the orthogonal (non-gating) MAVE validation track.

PRD/EVALUATION Part I orthogonal-validation scope: MaveDB (and, pending access, IGVF
VAMP-seq/SGE and CAGI7) functional-assay scores are compared against RAPTOR's
own TSC2 calls purely as an *independent, exploratory* check -- never as
ACMG evidence. Nothing in this package may be imported by `raptor.scorer`,
feed `BiasEvidenceSource`, fire PS3/BS3, or reach `raptor.eval.gate.decide_gate`
(enforced by `tests/external/test_mave_audit_and_report.py`).

Modules:
  register.py           -- fail-closed source registration/verification.
  source.py              -- MAVE score record contract + CSV/TSV loader.
  identity.py             -- exact SPDI/hgvsc overlap join (fail-loud).
  endpoint.py             -- FunctionalClass thresholds + label-blind runner.
  partition.py            -- mutually-exclusive calibration/heldout/VUS split.
  orthogonal_metrics.py    -- deterministic non-gating rank correlation/power.
  report.py               -- identity-free, label-free aggregate + hashing.
"""
