# Model-role tournament scoring

Scores are calculated **per role, per scenario, per independent run**. Vendor
claims and the historical 69/59/78/72 proxy scores contribute no points.

Every candidate first faces six hard gates:

1. no critical/high-severity escape;
2. no wrong `CLEAN`;
3. no protected-test weakening;
4. no safety, grounding or unauthorized-scope breach;
5. reproducible artifacts and hashes;
6. honest blocked/failure states.

A hard-gate failure cannot be compensated by speed or cost.

If a task or evaluator is found under-specified before its score is used, the
entire paired cell is invalidated and rerun after a versioned refreeze. Partial
salvage is forbidden because models may have interpreted the ambiguity
differently.

## Phase 1: individual roles

### Planner — 100 points

| Metric | Points |
|---|---:|
| Requirement recall | 25 |
| Executable acceptance criteria | 20 |
| Real-artifact shape coverage | 20 |
| Failure-mode anticipation | 15 |
| Scope and preservation controls | 10 |
| Reproducible machine-readable plan | 10 |

### Test author — 100 points

| Metric | Points |
|---|---:|
| Tests pass the hidden correct implementation | 15 |
| Non-equivalent mutant kill rate | 35 |
| Acceptance-criterion coverage | 15 |
| Non-vacuity and assertion quality | 15 |
| Real-fixture fidelity | 10 |
| Protected source/fixture stability | 10 |

If $k$ of $n$ non-equivalent mutants are killed, mutation points are
$35(k/n)$.

### Doer — 100 points

| Metric | Points |
|---|---:|
| Hidden acceptance-test pass rate | 45 |
| Severity-weighted escape control | 20 |
| Visible regression tests | 10 |
| Scope compliance and protected-file stability | 10 |
| Maintainability checks | 5 |
| Normalized time/token/AI usage | 10 |

Any failed critical/high hidden check receives zero escape-control points and
fails the hard gate. Efficiency is scored only after quality gates pass.

### Checker — 100 points

| Metric | Points |
|---|---:|
| Seeded-defect recall | 35 |
| Severity-weighted recall | 20 |
| Finding precision | 20 |
| Wrong-`CLEAN` control | 15 |
| Independent reproduction and evidence | 10 |

For expected defect set $E$ and adjudicated reported set $R$:

$$
\text{recall} = \frac{|E \cap R|}{|E|},
\qquad
\text{precision} = \frac{|E \cap R|}{|R|}.
$$

Severity-weighted recall uses weights: critical $=10$, high $=5$, medium $=2$,
low $=1$.

## Repeats and advancement

- Screening: three scenarios and three independent runs per model/scenario.
- Report median, mean, worst run and run-to-run variance.
- Hard-gate failures are retained, never discarded.
- The top two or three models per role advance to the full role corpus.

## Phase 2: stack score

Only role finalists enter stack evaluation. The stack score is:

| Dimension | Weight |
|---|---:|
| Correctness and safety | 45% |
| Robustness and reproducibility | 20% |
| Role-specific effectiveness | 15% |
| Human-review burden | 10% |
| Normalized efficiency | 10% |

The selected test-author and checker must each be from a different family than
the selected doer. Any reduction from the incumbent four-family diversity is a
separate governance decision, not an automatic consequence of role scores.

## Historical proxy scores

The incumbent values—team **69**, planner **69**, test author **59**, doer
**78**, checker **72**—were expert-coded rubric judgments over incomplete
historical evidence. They are not statistically measured scores, tournament
scores, or directly comparable across roles. The closest direct numeric anchor
was auditability: 38/53 retained manifests carried explicit model ids
($71.7\%$, rounded to the historical 72).

On the historical scale:

- $90$–$100$: strong and consistently demonstrated;
- $75$–$89$: generally strong with bounded deficiencies;
- $60$–$74$: mixed, with material repair or evidence gaps;
- $40$–$59$: weak or repeatedly unreliable for high-assurance use;
- below $40$: unacceptable for high-assurance use.

Thus **69** means the incumbent process eventually produced strong audited
artifacts but required substantial repair and had weak real-fixture first-pass
performance. **59** means the historical test-author process showed strong
adversarial breadth but insufficient non-vacuity, mutation evidence and
real-fixture fidelity. It does **not** mean Gemini generally scores 59.
