# RAPTOR's First Prospective ClinVar Test: Strong on Truncating Variants, Not Ready for Missense VUS

> **Status: research-only progress report - 2026-09-03.**
> RAPTOR does not issue authoritative variant classifications, support diagnosis or treatment
> decisions, authorize general VUS automation, or authorize a ClinVar submission. The narrow
> result described below applies only to research-evidence use.

RAPTOR has now completed its first prospective test against a ClinVar snapshot that the scorer
had not seen.

The result is mixed, and that is the most useful thing about it.

The run supported one narrow claim: the frozen scorer met its preregistered conditional
performance thresholds for `truncating:pathogenic` variants. It did not support the broader
claim that RAPTOR is ready for missense VUS interpretation. Full-spectrum validation remained
blocked, pathogenic missense variants received no automated calls, and benign missense coverage
was too small to support the registered threshold.

That is not a partial success rewritten as a victory. It is a boundary: one part of the system
now has prospective evidence, and the part most relevant to difficult $TSC2$ missense VUS still
needs better sources and better evidence.

## What was prospective this time

The earlier July evaluation was a leakage-safe held-out rerun, but its tiered interpretation was
post-hoc. It showed that `truncating:pathogenic` performance looked promising while missense
remained `NO_CALLS` or `UNDERPOWERED`. It could not authorize even the narrow truncating result,
because the tiered interpretation was written after the score existed.

This run used a new registration and the August 2026 ClinVar monthly archive:

| Dataset property | Frozen value |
|---|---|
| Exact URL | `variant_summary_2026-08.txt.gz` in the NCBI ClinVar monthly archive |
| Bytes | 441,792,560 |
| SHA-256 | `230ba6d...7bf500` |
| MD5 | `2d6b8f...3fa4500` |

The archive was independently downloaded twice on the x64 worker. Both downloads matched each
other and the earlier acquisition hash. The content identity was frozen before decompression,
label parsing or scoring.

The benchmark pipeline then:

- scanned 9,035,842 archive rows;
- retained 18,223 GRCh38 $TSC1$/$TSC2$ rows;
- emitted 18,119 normalizable label rows;
- built a 3,725-variant benchmark;
- assigned 1,117 variants to train/dev and 2,608 to the held-out set using the frozen seed and
  0.7 holdout fraction.

The x64 scoring path received only the 2,608 label-free holdout identities.

## The scorer stayed frozen

Prospective evaluation is not useful if the model is quietly updated from the exam answers.

The August archive supplied labels and the new holdout split. The scorer itself remained the
pinned BIAS 3.0.0 and Nirvana 3.18.1 stack. Its ClinVar-derived comparator resources were rebuilt
from the previously proven March source after removing all 2,608 new holdout identities.

The integrity results were:

- 2,608 of 2,608 holdout identities removed from the comparator source;
- zero holdout survivors;
- 2,608 unique BIAS result rows;
- zero duplicate raw keys;
- zero scored PP3/BP4 calls under the approved `disabled_manual` policy;
- PM1 withheld after both the published and reproduced PM1 resources had zero reachable holdout
  rows.

The model was not updated on August labels, and the labels were not joined until the BIAS output
had been frozen.

## The outcome by scope

| Scope | Actual | Called | Correct-call coverage | Prospective result |
|---|---:|---:|---:|---|
| `missense:pathogenic` | 53 | 0 | 0/53 | `NO_CALLS`; not estimable; not authorized |
| `missense:benign` | 110 | 10 | 10/110 | `UNDERPOWERED`; lower bounds unmet; not authorized |
| `truncating:pathogenic` | 237 | 219 | 219/237 | `VALIDATED_PROSPECTIVE`; research-only authorization |

For the 219 called truncating-pathogenic variants, conditional precision and recall were both
1.0. Their exact 95% Clopper-Pearson lower bounds were both `0.9833`, above the preregistered
`0.95` thresholds.

That conditional result must be read alongside abstention. The scorer made correct calls for
219 of 237 actual truncating-pathogenic holdout variants, an end-to-end correct-call coverage of
approximately 92.4%. Eighteen variants were not called.

For benign missense variants, all 10 calls were correct, but 10 calls are not enough to support a
strong performance claim. The 95% lower bounds were `0.6915`, below the registered precision and
recall thresholds, and the called count was below the minimum floor of 36.

For pathogenic missense variants, the result was simpler: 53 actual examples and zero calls.

## Why full spectrum did not pass

The full-spectrum terminal result is `BLOCKED_POLICY`, and no full-spectrum VUS use is
authorized. PM1 remains excluded because its production path is not validated.

But PM1 is not the whole story. Even if that policy issue disappeared, this run would not justify
a broad missense claim:

- pathogenic missense produced no calls;
- benign missense was underpowered;
- the registered missense lower-bound thresholds were not met.

The correct conclusion is not "RAPTOR passed except for a gate." The correct conclusion is:

> The current deterministic scorer has prospective support for one narrow truncating-pathogenic
> research scope and does not yet have prospective support for missense VUS interpretation.

## What `AUTHORIZED_RESEARCH_ONLY` means

For `truncating:pathogenic`, RAPTOR may use the prospectively validated result as internal
research evidence. It may support prioritization, method development and preparation of
expert-review material.

It does not authorize:

- an authoritative pathogenic classification;
- patient-specific interpretation;
- a public VUS worklist;
- automatic packet promotion;
- a ClinVar submission;
- or clinical use.

Individual variants still require complete evidence review and qualified human adjudication.

## Why this result changes the next build

The project does not need another round of threshold tuning. The missense problem is primarily
one of evidence coverage.

RAPTOR v2 is therefore focused on:

- live PubMed, LitVar and PMC source acquisition;
- the expanded $TSC2$ VAMP-seq, SGE and cliPE functional datasets;
- current MANE and annotation sources;
- calibrated, assay-specific $PS3/BS3$ evidence;
- cautious, variant-specific $PM5$ handling;
- contradiction and calibration-overlap analysis;
- and refreshed evidence packets that show exactly what changed from v1.

These sources also feed the Mechanism Atlas. The already-expanded $R611Q$ corpus illustrates the
second path: classification evidence and mechanism evidence remain separate, but both benefit
from better source coverage. Reviewed Atlas mechanism profiles can later become inputs to the
separate RescueScreen evidence-generation track.

## Reproduce and inspect

- [Compact prospective result](../../data/census/tsc_prospective_validation_2026-08_amendment_v3_result.json)
- [Stage 3-6 operator](../../scripts/run_clinvar_2026_08_prospective_stages.py)
- [x64 execution handoff](../ops/clinvar-2026-08-v3-x64-execution-handoff.md)
- [ADR-0022](../DECISIONS.md#adr-0022--clinvar-august-2026-amendment-v3-freezes-local-digests-because-ncbi-does-not-publish-archive-checksums)
- Implementation commit: `6329f406fa01e5e4f70d491b252e5d7689f33c33`
- External evidence SHA-256:
  `145f3ea2146cbc6cf3a1657d7bc30a1aa9698290ed8124acfe9b8b87354c6c10`

The full 1.30-GB evidence bundle remains outside Git. The committed result record pins its
benchmark, holdout, BIAS, terminal-evaluation and return-manifest hashes.

## The useful result is the boundary

A validation system earns trust by making it possible for a result to be narrower than the
project hoped.

This run did that. It upgraded the truncating-pathogenic result from promising post-hoc evidence
to prospective research evidence. It also made the missense gap impossible to hide behind pooled
accuracy or overall concordance.

The next milestone is not to explain that gap away. It is to close it with better functional,
literature and annotation evidence, then take the next frozen test.
