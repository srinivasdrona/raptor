# RAPTOR

RAPTOR is a vertical **TSC1/TSC2 research-evidence program** for building
reproducible variant evidence packets, validation controls, and governed
ClinVar/VCEP preparation. It is not a clinical diagnostic system and does not
issue authoritative variant classifications.

> **Start with the engineering method:** [`METHOD.md`](METHOD.md) summarizes the
> model-separated plan/test/build/review loop, Definition-of-Done gates, evidence and
> authorization ladder, and failure modes that changed RAPTOR's implementation and conclusions.

## Current status

The complete TSC evidence census, the leakage-safe masked held-out rerun
(R2, ADR-0012), and the tiered v3 post-hoc re-adjudication (ADR-0013) have
run. R2 and its v1/v2 interpretation are frozen and unchanged; v3 re-reports
the same frozen R2 counts on independent axes and generates no new evidence.

Public progress posts:
[*Before the First Score*](docs/blog/2026-07-10-before-the-first-score.md) ·
[*After the First Rerun*](docs/blog/2026-07-23-after-the-first-rerun.md)

| Milestone | Result |
|---|---|
| TSC VUS census (current, disabled_manual) | 6,618 variants; **157** candidate-LP review, **7** candidate-LB review, **6,424** unresolved, **30** annotation/manual — internal, non-authoritative review directions only |
| Frozen benchmark | 3,681 knowns; 2,577 held out |
| Mask integrity (R2) | 2,577/2,577 identities removed; zero survivors |
| R2 masked BIAS score (ADR-0012, `disabled_manual`) | 2,577 canonical rows; zero PP3/BP4 scored calls |
| v1/v2 frozen interpretation | `FAIL` (coarse missense gate) / `BLOCKED_POLICY`; `vus_authorized=false` (immutable) |
| v3 tiered re-adjudication (ADR-0013, post-hoc) | missense pathogenic `NO_CALLS`/`NOT_ESTIMABLE`; missense benign `UNDERPOWERED`/`NOT_ESTIMABLE`; truncating pathogenic `ADEQUATE`+`MET`/`SUPPORTED_POSTHOC`; full spectrum `NOT_VALIDATED`/`NOT_AUTHORIZED` |
| Prospective validation | **`BLOCKED_DATA`** — the exact preregistered August archive URL returned 404; no archive bytes, labels, or scores were accessed, and the live alternate URL was not substituted |
| VUS / research-scope authorization | **No** — canonical validated research-scope flag remains `false` |
| Mechanism Atlas source catalog | Five resolver-verified grounding sources plus seven mechanically non-grounding leads; public identifiers, licences and hashes are committed |
| `$TSC2$` `$p.\mathrm{Arg611Gln}$` deterministic pass | Two exact spans passed Gates 1–7; Gate 8 blocked for missing named review; zero accepted claims |
| Six-variant gate-smoke cohort | 6/6 technical packages passed Gates 1–7 and blocked only at Gate 8; zero accepted claims; explicitly **not** the formal contrast panel |
| Formal Atlas contrast panel | **`INFEASIBLE_PANEL`** — the reviewed selector exhaustively completed 24 attempts across L0–R7 against universe/map v4 with no budget exhaustion; no panel or candidate was selected |

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

The real-source Atlas runs establish deterministic source identity, content
hashes, exact spans, ontology/context structure, and classification-leakage
controls. They do not establish scientific sufficiency: no claim is promoted
until named human Gate 8 review. Public run manifests are under
[`data/atlas/runs/2026-08-03/`](data/atlas/runs/2026-08-03/).

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
- a condition-agnostic Mechanism Atlas core, versioned `$TSC2$` disease pack,
  deterministic offline citation/exact-span resolver, hash-frozen
  post-discovery selection protocol, and candidate-free universe lock;
- public metadata-only source and gate-run manifests for the first real
  `$TSC2$` deterministic-verification runs;
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
- Atlas Gates 1–7 verify provenance and deterministic fidelity, not biological
  truth. The current eight spans across seven variants remain unaccepted at
  Gate 8; the six-variant cohort is engineering repeatability only.
- BIAS remains an external, separate-process dependency under the arm's-length
  boundary documented in ADR-0007.

## Repository guide

- [`METHOD.md`](METHOD.md) — engineering method, gates, evidence ladder, and failures caught
- [`docs/PROGRAM.md`](docs/PROGRAM.md) — live program status and priorities
- [`docs/STRATEGY.md`](docs/STRATEGY.md) — strategy + operating-model authority
- [`docs/EVALUATION.md`](docs/EVALUATION.md) — evaluation protocol + acceptance-rubric authority
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture and policy decisions
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture
- [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md) — failure modes and controls
- [`docs/prd/`](docs/prd/) — feature contracts
- [`data/census/`](data/census/) — committed non-identifying aggregate records
- [`data/atlas/runs/2026-08-03/`](data/atlas/runs/2026-08-03/) — public
  source licences/hashes, span locators, gate outcomes, and reconstruction boundary

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
