# AAVC prior-art and TSC overlap audit (2026-07)

| Field | Value |
|---|---|
| Status | Reference / decision support, non-clinical, non-authoritative |
| AAVC code reviewed | `8da2b5ac7cf92830b792d521818a2ace50a0e2e1` |
| AAVC data reviewed | [ClinVar September 2024 classification release](https://doi.org/10.5281/zenodo.17201194) |
| RAPTOR corpus | ClinVar 2026-07-07, 6,618 TSC1/TSC2 VUS |
| Machine-readable aggregate | [`data/census/tsc_vus_aavc_overlap_2026-07-10.json`](../../data/census/tsc_vus_aavc_overlap_2026-07-10.json) |
| Reproducer | [`scripts/audit_aavc_overlap.py`](../../scripts/audit_aavc_overlap.py) |

> **Reading rule:** AAVC classes and RAPTOR candidate directions are machine outputs, not expert
> classifications. Agreement is not accuracy. Neither output may be used as the other's truth label
> or as ACMG evidence.

## 1. Executive conclusion

**AAVC is material prior art.** It falsifies any claim that population-scale deterministic ACMG
scoring or bulk VUS triage is novel. If RAPTOR stops at producing machine LP/LB queues, it is largely
replicating an established product category.

It does **not** show that RAPTOR's current TSC work is a row-for-row reproduction:

- AAVC's September-2024 release contains **4,532 TSC VUS** and machine-calls **808 (17.8%)** outside
  VUS.
- **4,010** of RAPTOR's July-2026 VUS match an AAVC row by exact GRCh38 VCF key; another **159**
  are equivalent after removing different VCF anchor bases. The combined, provisional overlap is
  **4,169/6,618 (63.0%)**.
- Only **342** matched variants receive a direction from both systems. **334 agree; eight conflict**
  (seven RAPTOR-LB/AAVC-LP, one RAPTOR-LP/AAVC-LB).
- AAVC leaves **601/943** matched RAPTOR LP/LB candidates in a VUS-* tier; RAPTOR leaves **366**
  AAVC-directional rows unresolved. The systems have materially different call surfaces.

The apparent **97.7% agreement when both call** is useful for selecting adversarial review cases,
but it is not independent validation: both systems use overlapping population, predictor and
ClinVar-derived resources, and AAVC does not publish a target-masking protocol.

The strategic consequence is restrictive: RAPTOR's defensible contribution must be the
**leakage-audited TSC evidence trail, TSC-specific policy, expert review, conflict resolution,
functional-evidence atlas and submission pathway**. The generic machine scorer is infrastructure,
not the product claim.

## 2. What happened to AAVC's TSC calls?

AAVC's downloadable table preserves a coarse VUS/BLB/PLP grouping of the source ClinVar
significance in `sig` and writes its machine result separately in `ACMG_class`. In the
September-2024 source:

| Scope | Source ClinVar VUS | AAVC P/LP/B/LB | Fraction outside VUS |
|---|---:|---:|---:|
| All genes | 1,354,015 | 750,318 | 55.4% |
| TSC1 | 1,865 | 435 | 23.3% |
| TSC2 | 2,667 | 373 | 14.0% |
| **TSC total** | **4,532** | **808** | **17.8%** |

Those machine results were published as a CC-BY Zenodo dataset. They are **not** ClinVar SCV
submissions and do not create a ClinGen expert-panel assertion. That is why a variant can remain VUS
in ClinVar even when AAVC emits LP or LB. AAVC demonstrates that computation alone does not clear the
review, submission, conflict-resolution or VCEP bottleneck.

The README's "`~710,000 of 1.38M`" claim does not reproduce exactly on the pinned release: the
download contains 1,354,015 source VUS and 750,318 machine P/LP/B/LB calls. This may reflect a
different run/version or rounding, but the repository provides no run manifest that resolves the
difference.

## 3. Repository audit

### 3.1 Practices worth retaining as requirements

| AAVC practice | RAPTOR disposition |
|---|---|
| Bulk VCF and pre-annotated offline mode | **Adopt/retain.** RAPTOR already has deterministic VCF export; keep scoring input label-free and snapshot-pinned. |
| Explicit criterion list plus structured caution flags | **Adopt.** Packet core should expose enumerated criteria and flags, not bury caveats in prose. |
| Point score and posterior probability are separate fields | **Partial adopt.** Keep the signed point total for audit. Do not emit posterior probability until it has TSC calibration and a declared prior. |
| CLI deactivates PM2 and PP5/BP6 unless explicitly enabled | **Adopt the explicit-policy principle, not the implementation.** RAPTOR keeps PP5/BP6/PS4 structurally forbidden and must pin PM2 strength in one tested policy source. |
| PVS1 considers NMD, terminal position, domains, splice effects, repeats and homopolymers | **Adopt as a test/requirements checklist using primary ClinGen guidance.** Do not copy AAVC code. |
| Transcript mismatch fails instead of silently selecting a replacement | **Retain.** RAPTOR already routes transcript/identity failures to manual review. |
| Full public result file has a DOI and checksum | **Adopt after validation.** A RAPTOR release must add code commit, source/policy hashes, run manifest, limitations and expert-review state. |
| Functional-evidence table and gene-specific rule adjustments | **Verticalise.** Build a TSC assay-validity atlas with source spans and applicability limits; do not use an opaque generic lookup. |

### 3.2 Controls RAPTOR must not inherit

1. **No AAVC output as truth or evidence.** It is an external comparator only.
2. **No code reuse.** The [PolyForm Strict 1.0.0 licence](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/LICENCE)
   permits noncommercial use but forbids distribution, modification and derivative software.
3. **No unmasked same-snapshot validation.** AAVC queries its `clinvar` table for the target's
   de-novo/in-trans fields and for PS1, PM5, PM1, PP2 and PP5/BP6 evidence
   ([target query](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L579-L603),
   [PS1/PM5/PP5-BP6](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L1518-L1686),
   [PM1/PP2](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L1799-L1852)).
   No published leave-out mask was found.
4. **No acceptance of the 99.3% claim as validated.** The
   [README](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/README.md#L1-L11)
   names an FDA concordance result but supplies no benchmark identities, protocol, confidence
   interval, code/data pin or peer-reviewed report.
5. **No success-shaped null output.** AAVC catches broad exceptions and emits rows with null
   classification fields
   ([run path](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L2384-L2424),
   [VCF path](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L2605-L2630)).
   RAPTOR must fail loud or emit a typed manual/error state.
6. **No ambiguous activation defaults.** AAVC's Python API activates PM2/PP5/BP6 by default, while
   its CLI deactivates them unless flags are supplied
   ([API defaults](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L2350-L2383),
   [CLI defaults](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L2682-L2722)).
   RAPTOR needs one policy source and an exact-set meta-test.
7. **No default PVS1 mechanism bypass.** `_PVS1(ignore_lof_check=True)` applies PVS1 without requiring
   the gene LoF-mechanism check unless the caller overrides the default
   ([implementation](https://github.com/OzcelikLab/AAVC/blob/8da2b5ac7cf92830b792d521818a2ace50a0e2e1/aavc.py#L1869-L1910)).
8. **No VUS-HIGH/MID/LOW as external classes.** They may be internal review-priority bins only;
   external status remains VUS until expert classification.
9. **No unpinned release reconstruction.** The AAVC data release does not identify the code commit,
   criterion flags or source-table versions used; repository bug fixes post-date the dataset.

## 4. Controls to incorporate into RAPTOR

| Control | Required implementation |
|---|---|
| **Frozen external comparator** | Pin AAVC DOI, archive checksum and repository commit. Store its result only under `external_comparators`; prohibit it from entering criterion evidence or the final combiner. |
| **Disagreement-first calibration** | Put all eight directional conflicts into the expert calibration batch, plus stratified samples where only AAVC calls, only RAPTOR calls and both abstain. **First-pass reviewers are blinded to both machine directions** and record decision/confidence before a logged reconciliation reveal. Do not estimate accuracy from this enriched batch. |
| **Comparator provenance** | Record exact/common-trim/full-SPDI match method, AAVC snapshot, machine class, criteria and flags in a reveal-only comparator envelope. Hide that envelope during independent first-pass review. Treat non-exact matches as provisional until reference-backed SPDI equivalence is confirmed. |
| **Single criterion policy** | Criterion activation, strength, lineage and source snapshot must resolve from one machine-readable policy. Unknown or unapproved criteria fail the run. |
| **Run reconstruction** | Every public artifact carries input identity hash, source hashes, code commit, policy hash, criterion activation set, error/manual counts and reviewer state. |
| **Structured caveats** | Packet flags cover transcript mismatch, overlapping gene, NMD/terminal-exon uncertainty, repeat/homopolymer context, source disagreement and comparator disagreement. LLM prose may only reference these structured fields. |
| **Primary-source PVS1/PS3 policy** | Use ClinGen guidance and TSC assay-validity evidence as the authority. AAVC is a requirements prompt, never the normative source. |
| **Claim discipline** | Cite AAVC's 99.3% and 50% figures only as project claims. Cite the reproducible release counts separately. |

## 5. Open questions for the AAVC authors

Before treating AAVC as more than a comparator, request:

1. the exact benchmark identities and FDA truth-source definition behind 99.3%;
2. held-out or target-removal procedures for every ClinVar-derived criterion;
3. the code commit, PM2/PP5/BP6 flags and database table versions used for the Zenodo release;
4. confidence intervals and class-stratified precision/recall, not concordance alone;
5. provenance and assay-validity rules for the `functional` table; and
6. whether any machine calls were expert-reviewed or submitted to ClinVar, and with what outcomes.

Until those answers exist, AAVC is valuable prior art and a disagreement baseline—not a validated
oracle.
