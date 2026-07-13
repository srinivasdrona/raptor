# RAPTOR

RAPTOR is a vertical **TSC1/TSC2 research-evidence program** for building
reproducible variant evidence packets, validation controls, and governed
ClinVar/VCEP preparation. It is not a clinical diagnostic system and does not
issue authoritative variant classifications.

## Current status

The first complete TSC evidence census and leakage-safe held-out evaluation
have run.

| Milestone | Result |
|---|---|
| TSC VUS census | 6,618 variants scored; internal candidate directions only |
| Frozen benchmark | 3,681 knowns; 2,577 held out |
| Mask integrity | 2,577/2,577 identities removed; zero survivors |
| Masked BIAS score | 2,577 canonical rows; zero duplicates |
| PRD-06 gate | **FAIL — binding missense stratum** |
| VUS authorization | **No** |

The missense point estimates were pathogenic precision `0.8421`, recall
`0.9412`, benign precision `0.9688`, and benign recall `0.9118`. Their 95%
Clopper-Pearson lower bounds (`0.6042`, `0.7131`, `0.8378`, `0.7632`) did not
meet the pre-registered `0.90` precision / `0.85` recall thresholds. The high
overall metrics do not override the separately gated missense result.

Source of record:
[`data/census/tsc_masked_holdout_gate_2026-07-13.json`](data/census/tsc_masked_holdout_gate_2026-07-13.json).

## What is built

- deterministic TSC1/TSC2 ClinVar ingestion and canonical GRCh38 SPDI identity;
- arm's-length Nirvana/BIAS evidence ingestion;
- criterion-lineage and ClinVar-circularity controls;
- upstream held-out masking and conservation ledgers;
- exact-set canonical BIAS adapter;
- arm's-length BP4/PP3 aggregation correction;
- exact per-direction Clopper-Pearson gate;
- immutable, first-pass-blinded candidate evidence packets;
- a 30-pattern internal calibration batch;
- ClinVar/VCEP schema and lifecycle preparation with submission disabled.

## Boundaries

- The 238 LP-review and 1,333 LB-review census directions are provisional
  triage signals—not reclassifications.
- The production criterion-strength/candidate-direction policy remains
  unapproved.
- PM1 was excluded from this fixed evaluation after a zero-support audit and
  remains unvalidated for production.
- No external VUS worklist or ClinVar submission is authorized before a future
  gate pass and variant-level expert sign-off.
- BIAS remains an external, separate-process dependency under the arm's-length
  boundary documented in ADR-0007.

## Repository guide

- [`docs/PROGRAM.md`](docs/PROGRAM.md) — live program status and priorities
- [`docs/STRATEGY.md`](docs/STRATEGY.md) — vertical TSC/mTOR strategy
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture and policy decisions
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture
- [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md) — failure modes and controls
- [`docs/prd/`](docs/prd/) — feature contracts
- [`data/census/`](data/census/) — committed non-identifying aggregate records

Large ClinVar, Nirvana, BIAS, packet, and held-out artifacts remain outside the
repository. Their checksums and operator contracts are recorded under
[`docs/ops/`](docs/ops/).

## Development

The package requires Python 3.11+:

```bash
python -m pip install -e ".[dev]"
pytest
```

On ARM64 Windows, reference-backed tests run in the documented WSL environment;
Nirvana/BIAS execution remains on the isolated x64 worker.
