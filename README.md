# RAPTOR

RAPTOR is a vertical **TSC1/TSC2 research-evidence program** for building
reproducible variant evidence packets, validation controls, and governed
ClinVar/VCEP preparation. It is not a clinical diagnostic system and does not
issue authoritative variant classifications.

## Current status

The complete TSC evidence census, the leakage-safe masked held-out rerun
(R2, ADR-0012), and the tiered v3 post-hoc re-adjudication (ADR-0013) have
run. R2 and its v1/v2 interpretation are frozen and unchanged; v3 re-reports
the same frozen R2 counts on independent axes and generates no new evidence.

| Milestone | Result |
|---|---|
| TSC VUS census (current, disabled_manual) | 6,618 variants; **157** candidate-LP review, **7** candidate-LB review, **6,424** unresolved, **30** annotation/manual — internal, non-authoritative review directions only |
| Frozen benchmark | 3,681 knowns; 2,577 held out |
| Mask integrity (R2) | 2,577/2,577 identities removed; zero survivors |
| R2 masked BIAS score (ADR-0012, `disabled_manual`) | 2,577 canonical rows; zero PP3/BP4 scored calls |
| v1/v2 frozen interpretation | `FAIL` (coarse missense gate) / `BLOCKED_POLICY`; `vus_authorized=false` (immutable) |
| v3 tiered re-adjudication (ADR-0013, post-hoc) | missense pathogenic `NO_CALLS`/`NOT_ESTIMABLE`; missense benign `UNDERPOWERED`/`NOT_ESTIMABLE`; truncating pathogenic `ADEQUATE`+`MET`/`SUPPORTED_POSTHOC`; full spectrum `NOT_VALIDATED`/`NOT_AUTHORIZED` |
| Prospective validation | `PENDING` — locked to the first NCBI ClinVar GRCh38 monthly archive dated on/after 2026-08-01, frozen before labels/scoring |
| VUS / research-scope authorization | **No** — canonical validated research-scope flag remains `false` |

v3 is a post-hoc semantic correction of the frozen R2 aggregate: it separates
run integrity, data sufficiency, conditional performance, policy parity and
authorization instead of collapsing them into one coarse pass/fail, but it
performs no new run, scoring, or evidence generation and authorizes nothing.

Source of record:
[`data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json`](data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json)
(R2, frozen) and
[`data/census/tsc_tiered_readjudication_2026-07-21.json`](data/census/tsc_tiered_readjudication_2026-07-21.json)
(v3, post-hoc). The earlier
[`data/census/tsc_masked_holdout_gate_2026-07-13.json`](data/census/tsc_masked_holdout_gate_2026-07-13.json)
run remains a superseded historical comparator, not the current approved
policy.

## What is built

- deterministic TSC1/TSC2 ClinVar ingestion and canonical GRCh38 SPDI identity;
- arm's-length Nirvana/BIAS evidence ingestion;
- criterion-lineage and ClinVar-circularity controls;
- upstream held-out masking and conservation ledgers;
- exact-set canonical BIAS adapter;
- arm's-length BP4/PP3 aggregation correction;
- exact per-direction Clopper-Pearson gate, plus a tiered v3 post-hoc
  re-adjudication (ADR-0013) that reports run integrity, data sufficiency,
  conditional performance, policy parity and authorization as independent
  axes over the same frozen R2 aggregate;
- a packet-free census aggregation package (`raptor.census`) producing the
  current, non-authoritative candidate-direction census under the
  PP3/BP4-disabled/manual policy (ADR-0012);
- immutable, first-pass-blinded candidate evidence packets;
- a 30-pattern internal calibration batch;
- ClinVar/VCEP schema and lifecycle preparation with submission disabled.

## Boundaries

- The current census's **157** candidate-LP-review and **7**
  candidate-LB-review directions are internal, eval-only triage signals—not
  reclassifications. The historical **238**/**1,333** counts were computed
  under the PP3/BP4-active policy later superseded by ADR-0012 and remain a
  labeled historical comparator only.
- The production criterion-strength/candidate-direction policy remains
  unapproved.
- PM1 was excluded from the R2 fixed evaluation after a zero-support audit and
  remains unvalidated for production; this exclusion is the reason v3 reports
  missense pathogenic as `NO_CALLS`, not as a passed or failed metric.
- v3's `truncating_pathogenic` scope evidence is `SUPPORTED_POSTHOC` only;
  its authorization is `PENDING_PROSPECTIVE` and no scope is authorized until
  the prospective, unseen-data validation locked by ADR-0013 completes.
- No external VUS worklist or ClinVar submission is authorized before a
  passed prospective validation and variant-level expert sign-off.
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
