# Anthropic AI for Science rare-disease Track One submission draft

Submission checklist

- Deadline: August 2, 2026, 11:59 PM PST (Anthropic's stated timezone)
- Official rare-disease call: https://www.anthropic.com/news/rare-disease-research-grants
- Official application form: https://docs.google.com/forms/d/e/1FAIpQLSfwDGfVg2lHJ0cc0oF_ilEnjvr_r4_paYi7VLlr5cLNXASdvA/viewform
- Recommended track: Track One
- Recommended disease answer: Tuberous sclerosis complex (TSC), currently implemented and evaluated for TSC1/TSC2, with this proposal focused on TSC2 mechanism evidence
- Proposal boundary: public-data-only research; no clinical classification, treatment, or prescribing claims
- Fill every [OWNER INPUT: ...] placeholder before submission
- Do not submit confidential, proprietary, patient, private, or paywalled material
- If applying independently, keep the eligibility-uncertainty note truthful; do not imply confirmed eligibility
- Confirm willingness to make Track One outputs public through Monarch if awarded
- Confirm requested credits against Anthropic's current pricing and eligible SKUs before submission
- Word-count method for bounded fields: \b\w[\w'-]*\b; each bounded answer was independently counted twice, and the count notes are outside the paste blocks

Owner inputs still required

- [OWNER INPUT: submission email]
- [OWNER INPUT: applicant legal name]
- Organization wording: Independent researcher
- Position/title: Independent researcher and open-source maintainer
- Public project/profile: https://github.com/srinivasdrona/raptor and https://github.com/srinivasdrona
- [OWNER INPUT: Anthropic Organization ID and controlling entity]
- [OWNER INPUT: genuine collaborators and approved roles or affiliations, or None]
- [OWNER INPUT: approve the recommended credit amount or replace it]
- [OWNER INPUT: confirm the biosecurity answer is accurate for the planned use]
- [OWNER INPUT: confirm willingness to make Track One outputs public through Monarch]
- [OWNER INPUT: review program-data, survey or interview, and publicity terms before accepting any award]

Form fields in official order

## 1. Email

Paste:

```text
[OWNER INPUT: submission email]
```

## 2. Primary contact

Paste:

```text
[OWNER INPUT: applicant legal name]
```

## 3. Organization or research institution

```text
Independent researcher
```

## 4. Position or title

```text
Independent researcher and open-source maintainer
```

## 5. Organization, research-group, Google Scholar, or GitHub link

Recommended project link:

```text
https://github.com/srinivasdrona/raptor
```

## 6. Track One or Track Two

Paste:

```text
Track One
```

## 7. Project title

Paste:

```text
Claude-assisted, source-grounded TSC2 mechanism evidence
```

## 8. Rare disease or disease class

Paste:

```text
Tuberous sclerosis complex (TSC), currently implemented and evaluated for TSC1/TSC2, with this proposal focused on TSC2 mechanism evidence
```

## 9. Anthropic Console Organization ID

Paste:

```text
[OWNER INPUT: Anthropic Organization ID and controlling entity]
```

## 10. Team and credentials (limit: 100 words)

```text
Independent researcher and open-source maintainer building RAPTOR, a public-data-only TSC1/TSC2 research-evidence program. Current assets include a frozen TSC benchmark, a negative masked held-out rerun that remains non-authorizing, a 6,618-variant census with 164 priority review packets, and a merged Mechanism Atlas core with deterministic citation/span checks. We have initiated outreach to qualified molecular geneticists and prepared the evidence-review materials. No reviewer is yet formally engaged; scientific onboarding and review may extend beyond the application deadline.
```

Word count: 77/100. Independent check: 77.

## 11. Professional or academic profiles

Paste:

```text
Project repository: https://github.com/srinivasdrona/raptor
GitHub: https://github.com/srinivasdrona
Google Scholar: N/A
Website or institutional profile: N/A
```

## 12. Project question, methods, outcomes, deliverables, and timeline (limit: 500 words)

Paste:

```text
RAPTOR is a public-data-only rare-disease research-evidence infrastructure currently implemented and evaluated for TSC1/TSC2. This proposal asks whether Claude-assisted primary-source retrieval, exact-span extraction, and contradiction surfacing can improve completeness, context, and expert efficiency for TSC2 variant-mechanism evidence while deterministic RAPTOR guards prevent unsupported claims and classification leakage.

Current starting assets are real but incomplete. RAPTOR has a frozen TSC benchmark with 3,681 scoreable knowns and 2,577 held out, a 6,618-variant TSC1/TSC2 VUS census, corrected review-packet generation for all 6,618 variants with a 164-item priority queue, a merged generic Mechanism Atlas core with a versioned TSC2 pack, and a deterministic offline citation/span resolver with 64 Atlas tests at the evidence snapshot. Negative evidence is explicit: the masked held-out R2 rerun remains non-authorizing, PP3/BP4 automated emission is disabled/manual, there is no prospective PASS, no accepted real Phase 2 Atlas claim, no second-disease support, and no engaged molecular geneticist yet.

Methods: use Claude only behind deterministic gates. Claude will help identify open primary sources, propose candidate evidence spans, extract mechanistic statements and contradictions, and normalize assay context. RAPTOR will then require local cataloging, source hashing, citation identity checks, exact-span verification, classification-leakage guards, and named expert review before any promoted mechanism statement. The work is research-only and will not generate clinical classifications, treatment advice, or prescribing claims. The workflow does not depend on Microsoft Discovery.

Six-month plan: Month 1 builds the open source catalog and acquires openly accessible primary content. Month 2 grounds the first R611Q anchor through Gates 1-7. Month 3 obtains named expert span review and revises failures. Month 4 runs a contrast panel spanning pathogenic, benign, conflicting, functionally studied, and evidence-poor cases. Month 5 evaluates Claude-assisted extraction against source recall, exact-span precision and yield, contradiction detection, unsupported-claim rate, context completeness, reproducibility, and expert time. Month 6 stages refreshes, regenerates changed-evidence packets, and publishes methods, evaluation, failure analysis, source-grounded TSC mechanism profiles after human review, and a DisMech-compatible export path without promising external acceptance.

Deliverables: a versioned source catalog, reviewed TSC2 mechanism evidence records, a public evaluation benchmark and rubric package, a methods and failure report, a staged refresh and change-detection workflow, and a one-way export compatible with DisMech-style downstream use.
```

Word count: 367/500. Independent check: 367.

## 13. How Claude will be used (limit: 200 words)

Paste:

```text
Claude will be used for bounded research tasks where language models add recall or synthesis but do not determine truth on their own: surfacing candidate open-access TSC2 sources; expanding gene, variant, assay, and mechanism synonyms; proposing candidate exact spans; drafting structured contradiction tables; normalizing assay and context descriptions across papers; triaging changed-evidence packets; and drafting source-grounded mechanism summaries for expert review. Claude Code can also speed evaluation scripting and report assembly.

Claude will not be the acceptance gate. Deterministic RAPTOR controls will still decide whether a claim can enter the Atlas: local source registration, hash pinning, source-identity resolution, exact-span verification, import and network restrictions, classification-leakage guards, reproducible exports, and named human review. In short, Claude will widen search and reduce expert reading time, while RAPTOR's deterministic gates prevent unsupported claims or promotion of unverified mechanism statements.
```

Word count: 136/200. Independent check: 136.

## 14. Scientific impact (limit: 200 words)

Paste:

```text
If successful, this project would show a practical way to use frontier models in rare-disease mechanism research without asking them to act as classifiers or clinical authorities. For tuberous sclerosis complex, the immediate impact would be better source-grounded TSC2 mechanism evidence: higher recall of relevant primary literature, clearer contradiction capture, more complete assay and context reporting, and faster expert review of difficult variants. For the field, the main contribution is methodological: an auditable pattern for combining LLM-assisted retrieval and extraction with deterministic evidence gates, exact-span verification, and explicit abstention when support is missing. Because outputs are planned as a public benchmark and rubric, a methods and failure report, reviewed mechanism profiles, and a DisMech-compatible export path, others could inspect both successes and failures rather than only positive claims.
```

Word count: 128/200. Independent check: 128.

## 15. Success measures (limit: 100 words)

Paste:

```text
Success will be measured on a human-reviewed TSC2 anchor plus contrast panel. Core metrics are source recall, exact-span precision, valid-span yield, unsupported-claim rate, contradiction detection rate, context completeness, rerun reproducibility, and expert time per reviewed evidence item. We will also track how often deterministic gates reject Claude-proposed content and whether staged refreshes correctly surface changed evidence. Success means better completeness and lower expert effort without increasing unsupported or irreproducible claims.
```

Word count: 70/100. Independent check: 70.

## 16. Requested API, Claude Science, or Claude Code credits

Owner approval required:

```text
[OWNER INPUT: approve the recommended $25,000 request, replace it, or provide a range if the form allows one]
```

Paste if the field accepts explanation:

```text
Requested credits: $25,000 over six months, not the $50,000 award maximum. Proposed workload: approximately 200-300 Opus-grade reasoning sessions for study design and failure review, 3,000-6,000 extraction or triage jobs on other approved models, 100-200 Claude Code sessions for evaluation, reporting, and tooling, and optional Claude Science usage for long-context scientific workflows. This request is workload-based rather than price-assumed; final dollar conversion should use Anthropic's current pricing and the eligible SKUs available at submission time.
```

If the field accepts only one number, paste:

```text
$25,000
```

Range if the form permits one: $20,000-$30,000.

## 17. Biosecurity categories and safeguards where applicable

Owner confirmation required:

```text
[OWNER INPUT: confirm the recommended "No applicable biosecurity category" answer is accurate for the planned use]
```

Recommended selection:

```text
No applicable biosecurity category
```

If a safeguards text box appears anyway, paste:

```text
This project uses only public rare-disease literature and public variant and assay resources to build source-grounded TSC mechanism evidence. It does not design, optimize, or operationalize pathogens, toxins, wet-lab protocols, or biological agents, and it does not generate treatment or prescribing guidance.
```

## 18. Additional information

Core text:

```text
RAPTOR development began on July 8, 2026 and is conducted in public at https://github.com/srinivasdrona/raptor. The short development history demonstrates execution speed but also means the project is early-stage. This application intentionally includes negative evidence as well as positive milestones: the masked held-out R2 rerun did not authorize deployment, PP3/BP4 automated emission remains disabled/manual, prospective validation is still pending, and no real grounded Phase 2 mechanism claim has yet been accepted. The requested work is therefore a bounded research-evidence project, not a clinical or therapeutic program. Planned public outputs are a benchmark and rubric package, a methods and failure report, source-grounded TSC mechanism profiles released only after human review, and a one-way DisMech-compatible export path without promising Monarch or DisMech acceptance. We have initiated outreach to qualified molecular geneticists and prepared the evidence-review materials. No reviewer is yet formally engaged; scientific onboarding and review may extend beyond the application deadline.
```

Optional final sentence if applying independently:

```text
Independent-applicant eligibility for Track One is not clearly confirmed in the published materials, so this submission is intentionally truthful about affiliation and asks to be evaluated on that basis.
```

## 19. Acceptance of terms

Field action:

```text
[OWNER INPUT: check the acceptance box only after reviewing the checklist below]
```

Owner review checklist before accepting terms

- Proposal contains no confidential, proprietary, patient, private, or paywalled material.
- Applicant is willing to make Track One outputs public through Monarch if awarded.
- Applicant has reviewed the Program Rules and any award terms for possible program-data collection, research use or training use of inputs or outputs, required surveys or interviews, and publicity or release language.
- Applicant has authority and consent to apply under the stated identity, affiliation, title, collaborator list, and Anthropic Organization ID.
- Applicant understands credits are non-cash, non-transferable, and still subject to Anthropic's Usage Policy.

Public-output plan

- Public evaluation benchmark and rubric package
- Public methods and failure report
- Source-grounded TSC mechanism profiles after human review
- DisMech-compatible export path without promising external acceptance

Verified public GitHub links

- Repository: https://github.com/srinivasdrona/raptor
- README: https://github.com/srinivasdrona/raptor/blob/main/README.md
- Program status: https://github.com/srinivasdrona/raptor/blob/main/docs/PROGRAM.md
- Strategy: https://github.com/srinivasdrona/raptor/blob/main/docs/STRATEGY.md
- Evaluation: https://github.com/srinivasdrona/raptor/blob/main/docs/EVALUATION.md
- Decisions: https://github.com/srinivasdrona/raptor/blob/main/docs/DECISIONS.md
- Architecture: https://github.com/srinivasdrona/raptor/blob/main/docs/ARCHITECTURE.md
- Risk register: https://github.com/srinivasdrona/raptor/blob/main/docs/RISK_REGISTER.md
- Blog post 1: https://github.com/srinivasdrona/raptor/blob/main/docs/blog/2026-07-10-before-the-first-score.md
- Blog post 2: https://github.com/srinivasdrona/raptor/blob/main/docs/blog/2026-07-23-after-the-first-rerun.md
- Atlas runbook: https://github.com/srinivasdrona/raptor/blob/main/docs/project/atlas/ATLAS_RUNBOOK.md
- Atlas handoff: https://github.com/srinivasdrona/raptor/blob/main/docs/project/atlas/MECHANISM_ATLAS_HANDOFF.md
- Citation resolver code: https://github.com/srinivasdrona/raptor/blob/main/src/raptor/atlas/citation.py
- DisMech export code: https://github.com/srinivasdrona/raptor/blob/main/src/raptor/atlas/export.py
- TSC2 pack: https://github.com/srinivasdrona/raptor/blob/main/configs/atlas/packs/tsc2/pack.yaml
