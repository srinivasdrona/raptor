# Anthropic rare-disease grant: eligibility and terms

> **Status:** application decision memo, not legal advice  
> **Official sources accessed:** 2026-07-30

## Decision summary

| Question | Current conclusion |
|---|---|
| Deadline | August 2, 2026 at 11:59 PM PST, using Anthropic's stated timezone |
| Recommended track | Track One: basic science and rare-disease mechanism discovery |
| RAPTOR fit | Strong substantive fit if framed as public-data-only research evidence and evaluation, not diagnosis or therapeutic development |
| Independent applicant eligibility | **UNCLEAR - owner decision required** |
| Award | Up to $50,000 in Claude credits over six months; credits are not cash |
| Public outputs | Track One outputs will be made publicly available through Monarch |
| Application submission | The form says information submitted through it is treated as non-confidential or proprietary; include no confidential, proprietary, patient, private, or paywalled material |
| Program-data terms | Public Program Rules appear to permit Anthropic training/research use of selected researchers' Program data, including Inputs and Outputs; confirm before accepting an award |
| Publicity terms | Public Program Rules include publicity/release language; confirm award-time terms before acceptance |

RAPTOR should submit only under the applicant's truthful identity and affiliation. It must not imply
an academic, nonprofit, clinical, patient-organization, or biotech affiliation that does not exist.

## Track selection

### Track One fits

Anthropic describes Track One as collaboration among clinical researchers, patient organizations,
and data scientists to accelerate basic science and rare-disease mechanism discovery. RAPTOR's
current work fits that scientific scope:

- reproducible TSC1/TSC2 evidence packets;
- honest evaluation of where automated evidence fails or abstains;
- a source-grounded Mechanism Atlas;
- exact citation/span verification;
- deterministic controls against unsupported claims and classification leakage;
- public, expert-reviewable research outputs.

The application should describe RAPTOR as rare-disease research-evidence infrastructure currently
implemented and evaluated for TSC1/TSC2. It is not a clinical diagnostic system and does not issue
authoritative classifications.

### Track Two does not fit

Track Two is aimed at early-stage biotechnology and clinical or therapeutic development, including
dose selection, biomarkers, trials, and regulatory documentation. RAPTOR has no therapeutic asset,
clinical-development program, dosing work, or biotech organization and should not be positioned
under this track.

## Eligibility

The official application form says:

> The AI for Science program offers credits to qualified nonprofit and academic researchers,
> unless specified otherwise.

It also asks applicants to enter academic emails and credentials where possible. The general AI for
Science announcement refers to researchers attached to a research institution. The rare-disease
announcement uses broader collaboration language but does not explicitly confirm that an
unaffiliated independent applicant is eligible for Track One.

Therefore:

> **Independent Track One eligibility is unclear, not confirmed.**

The application may still be submitted truthfully, but the applicant should not state or imply that
eligibility has been confirmed. A genuine academic, nonprofit, clinical, or patient-organization
collaborator would strengthen the application, but no collaborator should be invented or represented
without agreement.

The Program Rules also contain general eligibility restrictions, including age of majority,
sanctions/jurisdiction rules, and required employer or institution consent where applicable.

## Application fields retrieved

The live form exposes the following rare-disease Track One fields:

- email;
- primary contact;
- organization or research institution;
- position or title;
- organization, research-group, Google Scholar, or GitHub link;
- Track One or Track Two;
- project title;
- rare disease or disease class;
- Anthropic Console Organization ID;
- team and credentials, under 100 words;
- professional or academic profiles;
- project question, methods, outcomes, deliverables, and timeline, under 500 words;
- how Claude will be used, up to 200 words;
- scientific impact, up to 200 words;
- success measures, up to 100 words;
- requested API, Claude Science, or Claude Code credits;
- biosecurity categories and safeguards where applicable;
- additional information;
- acceptance of terms.

The form exposes word limits, not reliable per-field character limits.

## Credits, models, and usage policy

- Accepted applicants may receive up to $50,000 in Claude credits over six months.
- Credits have no cash value and are not transferable.
- Credits may be used with Claude Opus or other generally available models approved for biology.
- The form says grantees do not receive a blanket exemption from Anthropic's Usage Policy.
- The rare-disease announcement says some projects that encounter biological classifiers may be
  eligible for exemptions. This should not be represented as an approved exemption for RAPTOR.

## Public outputs and Monarch

Anthropic states that Track One outputs will be made publicly available through
Monarchinitiative.org.

The announcement invites grantees to use and contribute to resources such as Mondo and DisMech. It
does not state that every applicant must promise a specific Mondo term or DisMech YAML contribution.
RAPTOR can truthfully propose:

- a public evaluation dataset and rubric;
- a methods and failure report;
- source-grounded TSC mechanism profiles or hypotheses after expert review;
- a one-way DisMech-compatible export.

It should not promise Monarch or DisMech acceptance, maintainer approval, or a specific integration
format before discussing the contribution workflow with maintainers.

## Data, confidentiality, training, and publicity

### Application-submission handling

The application form states:

> Anthropic treats information submitted through this form as non-confidential or proprietary,
> so please do not submit confidential or proprietary information in your proposal.

This statement governs the application submission. The proposal must contain no:

- patient or private data;
- unpublished confidential research;
- proprietary data or source content;
- paywalled full text;
- credentials, secrets, or private identifiers.

Later use of Claude/API services is a separate context. Anthropic's baseline Commercial Terms state
that Customer Content is Confidential Information, the customer retains Inputs and owns Outputs,
and Anthropic may not train models on Customer Content from Services, subject to other applicable
terms. The AI for Science Program Rules may add program-specific terms for selected researchers, as
described below.

### RAPTOR input boundary

The proposed project should use only public and appropriately licensed sources. Exact quotations
should be limited to the evidence spans needed for verification and permitted by the source licence.
Raw public-source files remain outside Git; public outputs contain citations, bounded spans, derived
records, methods, and evaluation results.

### Training and program-data terms

Anthropic's baseline Commercial Terms state that Anthropic may not train models on Customer Content
from Services. However, the posted AI for Science Program Rules appear to require selected
researchers to have permissions allowing Anthropic to collect, analyze, train models on, and conduct
research on Program data, including Inputs and Outputs, and grant a perpetual, irrevocable licence
for those purposes.

The Program Rules also state that selected researchers accepting Credits will participate in
research surveys and interviews. Anthropic may retain, analyze, and conduct research on resulting
interview transcripts and may publish anonymized and aggregated research findings from program
participation.

This apparent program-specific override is material. Before accepting an award, the owner should
confirm:

1. whether the posted Program Rules govern this rare-disease call;
2. exact retention periods;
3. whether all credit-funded prompts and outputs may be used for model training;
4. whether additional award terms apply;
5. whether RAPTOR's public-source licences permit the contemplated processing and program-data use;
6. the scope, retention, recording, and publication terms for surveys and interviews.

### Publicity

The posted Program Rules include publicity/release provisions concerning selected researchers'
names, biographical information, photographs, voices, or likenesses. Confirm the final award terms
before acceptance.

## Action table

| Action | Decision |
|---|---|
| Submit | Track One, public-data-only, research-evidence and mechanism-evaluation framing |
| Disclose | Exact independent/affiliated status; non-diagnostic scope; public-output commitment; current team gap |
| Avoid | Invented affiliation; confidential or patient data; paywalled content; therapeutic or clinical claims; guaranteed Monarch acceptance |
| Confirm before award | Eligibility, Organization ID ownership, program-data training terms, retention, publicity release, public-output licence/format |

## Recommended applicant wording

Use only if accurate:

> Independent researcher and open-source maintainer developing RAPTOR, a public-data-only
> TSC1/TSC2 research-evidence program. RAPTOR produces auditable evidence and mechanism artifacts
> for expert review; it is not patient-facing and does not issue clinical classifications.

If applying through a qualifying institution, replace this with the actual institution, role, and
approved affiliation.

## Owner inputs required before submission

1. Applicant's exact legal name and truthful affiliation status.
2. Email domain and academic, professional, GitHub, or research credentials to provide.
3. Organization or research-institution field wording.
4. Anthropic Console Organization ID and the entity that controls it.
5. Any genuine collaborators and their approved roles.
6. Willingness to make Track One outputs public through Monarch.
7. Willingness to accept or seek clarification on program-data training and publicity terms.

## Official sources

- [Anthropic rare-disease research grants](https://www.anthropic.com/news/rare-disease-research-grants)
- [Official application form](https://docs.google.com/forms/d/e/1FAIpQLSfwDGfVg2lHJ0cc0oF_ilEnjvr_r4_paYi7VLlr5cLNXASdvA/viewform)
- [AI for Science program](https://www.anthropic.com/news/ai-for-science-program)
- [AI for Science Program Rules](https://www.anthropic.com/ai-for-science-program-rules)
- [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms)
- [Anthropic Credit Terms](https://www.anthropic.com/legal/credit-terms)
- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup)
- [Anthropic Privacy Policy](https://www.anthropic.com/legal/privacy)
- [Anthropic Service Specific Terms](https://www.anthropic.com/legal/service-specific-terms)
- [Mondo](https://mondo.monarchinitiative.org/)
- [DisMech](https://github.com/monarch-initiative/dismech)
