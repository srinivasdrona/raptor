# ClinVar / ClinGen VCEP submission — primary-source register (2026-07)

| Field | Value |
|---|---|
| Status | Reference / preparation support, **non-clinical, non-authoritative, planning-only** |
| Purpose | A dated, source-typed register of the official ClinVar/ClinGen primary documentation that grounds the RAPTOR ClinVar/VCEP **preparation** plan (`docs/prd/PRD-09-clinvar-vcep-submission-preparation.md`). |
| Compiled from sources verified | **2026-07-11** (single research session; ClinVar updates weekly — re-verify at run) |
| Revised | **2026-07-12** — schema re-verification closing rubber-duck MAJOR findings (§7): `recordStatus` enum (`novel`/`update`) + separate top-level `clinvarDeletion` withdrawal object; TSC VCEP open dependency reframed to roster/status/contact/engagement route. **Second revision 2026-07-12** — germline classification object-name HARD-BLOCK **CLOSED** by live production schema (HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time): new `germlineSubmission[]` → `germlineClassification` → `germlineClassificationDescription`; RAPTOR pins to the new shape only and rejects legacy/mixed `clinvarSubmission`/`clinicalSignificance`; schema-freshness re-pin guard added (§2.5). |
| Scope boundary | This document records **what the authorities say**. It does **not** authorize any submission, contact, or classification. No SCV is created by anything described here. |

> **Reading rule.** A ClinVar submission *schema* being satisfiable is **not** authority to submit.
> Authority requires a registered organization, a qualified/expert-panel submitter, an approved
> classification, and (for RAPTOR) PRD-06 gate `PASS` + per-variant qualified sign-off + a final approved
> policy (STRATEGY §9; GP-1). Every "field" claim below is *schema/mechanics*; every "authority" claim is
> flagged as such.

---

## 0. Source-type legend

| Tag | Meaning |
|---|---|
| **[PRIMARY-OFFICIAL]** | Retrieved directly from an NCBI/ClinVar or ClinGen official page/schema. |
| **[PRIMARY-DOC]** | Official downloadable protocol/PDF or standard-terms file (named, not fully re-fetched here). |
| **[SECONDARY-SYNTH]** | Assistant/search synthesis of official docs; **must be re-verified against the live schema before any build depends on it.** |
| **[INTERNAL]** | RAPTOR repository artifact (grounded in code/docs in this repo). |

All URLs were reachable **2026-07-11** unless noted. Dates are the verification date, not the page's own
"last updated".

---

## 1. ClinVar submission — mechanics and endpoints

| # | Claim | Source | Type | Verified |
|---|---|---|---|---|
| 1.1 | ClinVar is free, updated **weekly** (public release typically Sunday nights); API records are processed **entirely automatically with no curator review** and released in the next weekly release. | `https://www.ncbi.nlm.nih.gov/clinvar/docs/submit/`, `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.2 | ClinVar does **not** accept submissions from patients; submissions come from labs, clinics, researchers, expert panels, etc. Consent is **assumed** by ClinVar; once in ClinVar, data are unrestricted. | `.../docs/submit/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.3 | A submission is a **variant-level classification of a variant for a condition** (not case/patient-level); patient data may appear only as a **de-identified** observation. | `.../docs/submit/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.4 | Submission API uses **NCBI Submission Portal Public API** (REST/JSON). Submitting by API requires the org to be **registered** first (one-time manual step). | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.5 | API auth uses a **service account** + **API key** per organization (request a service account by emailing `clinvar@ncbi.nlm.nih.gov`). Each request carries header `SP-API-KEY` (**64 alphanumeric chars**); the key is shown once and is unrecoverable if lost. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.6 | Submit via `POST https://submit.ncbi.nlm.nih.gov/api/v1/submissions/` with body `{"actions":[{"type":"AddData","targetDb":"clinvar","data":{"content": <submission JSON>}}]}`. Up to **10,000 records** per API submission; batch rather than single-record. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.7 | **Dry run:** append `?dry-run=true` to the submissions URL. A dry run tests **JSON format + communication only** (not HGVS/data validation); **no submission ID is created and no data are processed to ClinVar** regardless of errors. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.8 | **Test endpoint:** `https://submit.ncbi.nlm.nih.gov/apitest/v1/submissions` runs data validation but **data submitted there are never made public**, even on success. Not intended for validating every dataset; testing SCV updates there is unreliable. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.9 | Submission status: `GET https://submit.ncbi.nlm.nih.gov/api/v1/submissions/SUBnnnnnn/actions/`. HTTP return codes include 200/201/204/400/401/429/5xx. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |
| 1.10 | New submitters are advised to start with the **Excel submission template** to get curator feedback before formatting by API. | `.../docs/api_http/` | PRIMARY-OFFICIAL | 2026-07-11 |

> **No-SCV facts that ground the RAPTOR dry-run validator (PRD-09 §6):** 1.7 and 1.8 are the two official
> "no public record" paths. RAPTOR's **primary** validator is offline (no network, no credentials) and
> emits only a conformance report; the live `dry-run=true` / `apitest` paths are optional, operator-gated,
> and — by NCBI's own definition — create **no SCV** and no public data.

---

## 2. ClinVar submission — record fields (schema mapping targets)

Fields below come from the ClinVar Submission API schema page (`.../docs/api_http/`, **[PRIMARY-OFFICIAL]**,
verified 2026-07-11) unless tagged otherwise. RAPTOR maps **into** these (PRD-09 §3).

### 2.1 Submission-level

| Field | Notes |
|---|---|
| `assertionCriteria` `{db, id}` or `{url}` | The criteria the org uses to classify. `db ∈ {PubMed, DOI, pmc}` + `id`, **or** a `url` to a previously uploaded criteria file. **One** criteria doc applies to the whole submission. Equivalent to spreadsheet "Assertion method citation". |
| `behalfOrgID` | Optional — submitting on behalf of another org. |
| `germlineSubmission[]` **[PRIMARY-OFFICIAL, verified 2026-07-12]** — **RAPTOR-PINNED TARGET** | The **new (2024-redesign) top-level array** of germline variant records being **added or updated** (each record carries `recordStatus`, `clinvarAccession?`, a `germlineClassification` object, `conditionSet`, `observedIn`, `variantSet`, `localID`/`localKey`). Novel/update germline records live here. **RAPTOR maps into `germlineSubmission[]` only** (§2.2). |
| `clinvarSubmission[]` **[PRIMARY-OFFICIAL, verified 2026-07-12]** — **LEGACY; RAPTOR REJECTS IN OUR OUTPUT** | The **legacy** top-level array holding records with a `clinicalSignificance` classification container. The live schema (verified 2026-07-12) presents `germlineSubmission` and `clinvarSubmission` as **mutually exclusive — the old `clinvarSubmission` and new `germlineSubmission` cannot appear together** in one submission. RAPTOR's generated output uses `germlineSubmission` **only** and must **reject** any record emitting `clinvarSubmission`/`clinicalSignificance` or mixing both (PRD-09 FR2/FR10). |
| `clinvarDeletion` `.accessionSet[] {accession, reason?}` **[PRIMARY-OFFICIAL, verified 2026-07-12]** | **Withdrawal/deletion** of previously submitted records. `clinvarDeletion` is a **separate top-level object** (sibling of `germlineSubmission`/`clinvarSubmission`, **not** a `recordStatus`). `accessionSet` is a required array (1–10,000 items); each entry has a **required** SCV `accession` (`SCVnnnnnnnnn`, *not* RCV/VCV) + an **optional** public `reason` comment explaining the deletion. |

### 2.2 Per-record (germline focus)

| Field | Allowed values / format | Notes |
|---|---|---|
| `recordStatus` | `novel` / `update` **[PRIMARY-OFFICIAL, verified 2026-07-12]** | Required enum; **only** `novel` (new record; accessions may be reserved pre-submission) or `update` (revise a prior SCV). There is **no `delete` value** — an earlier `recordStatus="delete"` reading was a schema misidentification and is **rejected**. **Withdrawal/deletion is the separate top-level `clinvarDeletion` object (§2.1), not a `recordStatus`.** |
| `clinvarAccession` | e.g. `SCV000123456` | Required for **updates** (and novel records if accessions were reserved). SCV, not RCV. |
| `localID` | string, public | Stable org-local variant id; **must not contain PHI**. |
| `localKey` | string, public | Local id for the **variant–condition pair** ("Linking ID" in spreadsheet). |
| `conditionSet.condition[]` | `{db, id}` or `{name}` | `db ∈ {OMIM, MedGen, Orphanet, MeSH, HP, MONDO}`. Identifier **preferred** over name. Multiple conditions on one record = "variant causes A **and** B in the same individual"; otherwise submit separate records. |
| `germlineClassification` (object) **[PRIMARY-OFFICIAL, verified 2026-07-12 — RESOLVED / RAPTOR-PINNED]** | contains `germlineClassificationDescription` (required), `dateLastEvaluated`, `comment`, `citation[]`, `modeOfInheritance`, `explanationOfInterpretation` | The 2024 ClinVar redesign split classification into `germlineClassification` / `somaticClassification*` / `oncogenicityClassification`. **The live production schema page (verified 2026-07-12, HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time) confirms the new `germlineSubmission[]` array requires a `germlineClassification` object whose required classification field is `germlineClassificationDescription`.** The legacy `clinvarSubmission[]`/`clinicalSignificance`/`clinicalSignificanceDescription` shape also appears but is **mutually exclusive** with `germlineSubmission` and is **rejected in RAPTOR output**. **RAPTOR pins to `germlineSubmission[].germlineClassification.germlineClassificationDescription`** (§2.1; PRD-09 FR2). *(Earlier drafts flagged the germline object name as an unconfirmed HARD-BLOCK; that block is **CLOSED** by this dated live-schema evidence.)* |
| `germlineClassificationDescription` | ClinVar germline term enum (e.g. `Pathogenic`, `Likely pathogenic`, `Uncertain significance`, `Likely benign`, `Benign`, …) | Required classification field inside `germlineClassification`. Definitive machine list: `https://ftp.ncbi.nlm.nih.gov/pub/GTR/standard_terms/Clinical_significance.txt` **[PRIMARY-DOC]** (already used by RAPTOR PRD-07 golden corpus). *(This replaces the legacy `clinicalSignificanceDescription`, which RAPTOR does not emit.)* |
| `dateLastEvaluated` | `yyyy-mm-dd` | Date the classification was last evaluated by the submitter (not patient phenotype date). |
| `comment` | free text, **no PII** | Rationale/evidence; ACMG codes alone are insufficient. |
| `citation[]` | `{db, id}` where `db ∈ {PubMed, BookShelf, DOI, pmc}` | Evidence citations used for the classification. |
| `observedIn[]` | required, ≥1 | See 2.3. |
| `variantSet.variant[]` | one of `hgvs` **or** `chromosomeCoordinates` (mutually exclusive) | See 2.4. Other set types exist (haplotypeSet, phaseUnknownSet, compoundHeterozygoteSet, diplotypeSet, distinctChromosomesSet) — **out of scope** for TSC1/TSC2 single small variants. |

### 2.3 `observedIn[]` (required)

| Field | Allowed values | Notes |
|---|---|---|
| `affectedStatus` | `yes` / `no` / `unknown` / `not provided` / `not applicable` | Required. |
| `alleleOrigin` | `germline` / `somatic` / `de novo` / `unknown` / `inherited` / `maternal` / `paternal` / `biparental` / `not applicable` | Required. |
| `collectionMethod` | `curation` / `literature only` / `reference population` / `provider interpretation` / `phenotyping only` / `case-control` / `clinical testing` / `in vitro` / `in vivo` / `research` / `not provided` | Required. **RAPTOR = `curation`** (no primary patient observation). |
| `numberOfIndividuals` | integer | Optional. |
| `clinicalFeatures[]` | HPO `{db:HP, id}`; `clinicalFeaturesAffectedStatus ∈ {present, absent, not tested}` | Optional; RAPTOR normally omits (no patient data). |

### 2.4 `variantSet.variant[]` (single small variant)

| Field | Allowed values | Notes |
|---|---|---|
| `hgvs` | one valid HGVS expression | **OR** chromosomeCoordinates, not both. |
| `chromosomeCoordinates.assembly` | `GRCh38` / `hg38` / `GRCh37` / … / `not applicable` | RAPTOR = **GRCh38**. |
| `chromosomeCoordinates.chromosome` | `1`–`22`, `X`, `Y`, `MT` | TSC1 = chr9; TSC2 = chr16. |
| `chromosomeCoordinates.start`/`stop` | 1-based integers | |
| `chromosomeCoordinates.referenceAllele`/`alternateAllele` | strings (≤50 nt) | Small variants. |
| `chromosomeCoordinates.accession` | e.g. `NC_000016.10` | Optional. |
| `gene[].symbol` | HGNC symbol (`TSC1`/`TSC2`) | Or NCBI Gene ID, not both. |

### 2.5 Schema-snapshot pin + freshness/re-pin guard **[PRIMARY-OFFICIAL, verified 2026-07-12]**

| Item | Value |
|---|---|
| Pinned live schema source | ClinVar Submission API HTTP docs / schema page (`.../docs/api_http/`) |
| Live page HTML sha256 (point-in-time) | `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad` |
| Pin scope | The **new** `germlineSubmission[]` → `germlineClassification` → `germlineClassificationDescription` shape, plus `recordStatus` (`novel`/`update`) and the separate top-level `clinvarDeletion.accessionSet[]` withdrawal object. |
| Re-pin guard (GP-5) | The recorded hash is a **point-in-time** snapshot, **not** permanent (ClinVar updates weekly). Any future validator/mapper build **must** re-hash the live schema page and compare against the pinned hash. **On hash drift, validator/mapper generation is blocked** until a human reviews the schema diff and re-pins (PRD-09 FR2.1/FR10.0). This prevents a silently-stale schema from producing false-conformant records. |

---

## 3. ClinVar review status (star level) — authority, not schema

| # | Claim | Source | Type | Verified |
|---|---|---|---|---|
| 3.1 | Review status ("stars") reflects the **level of review** behind the classification; a single submitter with criteria = **1 star** ("criteria provided, single submitter"); a **ClinGen expert panel** = **3 stars** ("reviewed by expert panel"). | `https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/` | PRIMARY-OFFICIAL (named; re-verify) | 2026-07-11 |
| 3.2 | Expert-panel (3★) status is **not** a form field a submitter self-asserts — it follows from being an **approved ClinGen VCEP** submitting under that affiliation. | `.../docs/review_status/` + ClinGen protocol (§4) | PRIMARY-OFFICIAL + PRIMARY-DOC | 2026-07-11 |

> **Authority distinction.** RAPTOR can produce a *schema-valid* record today; its **review status** would be
> **1★ at best** unless submitted by an approved VCEP. A **TSC VCEP exists** but had **0** ClinVar submissions
> / **0** expert-panel (3★) TSC records in ClinVar (STRATEGY.md; verified 2026-06-16) — the adoption gap
> PRD-09 prepares for, not a demand signal, and **not** an absence of the VCEP itself.

---

## 4. ClinGen VCEP — approval pathway (authority)

| # | Claim | Source | Type | Verified |
|---|---|---|---|---|
| 4.1 | Becoming a **Variant Curation Expert Panel (VCEP)** follows the official **ClinGen VCEP Protocol** (Version 12, 2025 cycle; Version 11 = Nov 2023). | `https://www.clinicalgenome.org/docs/clingen-variant-curation-expert-panel-vcep-protocol/`; v11 PDF `.../assets/files/3635/clingen_vcep_protocol_version_11_november2023-1.pdf` | PRIMARY-DOC | 2026-07-11 |
| 4.2 | Four-step process: **(1) Group definition** (membership/expertise, COI, scope — inheritance, transcripts, nomenclature); **(2) Develop classification criteria** (ACMG/AMP specification for the gene/disease); **(3) Pilot variant classifications** (apply criteria to a pilot set, reviewed by the VCEP Review Committee); **(4) Final approval** (address pilot feedback, ongoing-review/discrepancy plan, presentation). After approval the VCEP may submit at **3-star** to ClinVar. | ClinGen VCEP Protocol | PRIMARY-DOC (via [SECONDARY-SYNTH] summary; confirm in the PDF) | 2026-07-11 |
| 4.3 | Curators must complete ClinGen's **two levels of variant-curation training**; curation uses the **Variant Curation Interface (VCI)**; entry via a **Clinical Domain Working Group (CDWG)**; contact `cdwg_oversightcommittee@clinicalgenome.org`. | ClinGen VCEP Protocol / Procedures & Resources | PRIMARY-DOC / SECONDARY-SYNTH | 2026-07-11 |
| 4.4 | The VCEP's approved **ACMG/AMP gene-specific specification** is the document that becomes the ClinVar `assertionCriteria` for its submissions. | §4.2 + ClinVar `assertionCriteria` (§2.1) | PRIMARY-DOC + PRIMARY-OFFICIAL | 2026-07-11 |

> ClinGen page fetches were partially blocked (one 404, one search-synth). **Before any dependency on the
> exact VCEP steps, re-verify against ClinGen VCEP Protocol Version 12 directly.**

---

## 5. RAPTOR-side artifacts this maps from (internal)

| # | Claim | Source | Type |
|---|---|---|---|
| 5.1 | The packet source of record is `CandidateEvidencePacket` (`canonical_spdi`, `gene`, `transcript`, `consequence`, `variant_class`; `candidate_direction`; per-criterion evidence; `evidence_core_hash`; `review_state`; `predecessor_packet_id`). | `src/raptor/packet/model.py` | INTERNAL |
| 5.2 | Terminal packet state is `EXTERNAL_SUBMISSION_READY`, reachable only with an approved non-null policy + non-null direction + gate `PASS` + ADR-0009 mask ruling + two distinct QMG sign-offs + primary grounding. | `src/raptor/packet/state.py`, `docs/prd/PRD-04-candidate-evidence-packet.md` §4.5 | INTERNAL |
| 5.3 | Decisions live in a variant-scoped append-only hash-chained log; `DecisionEventType ∈ {reviewer_decision, independent_decision, pattern_policy_approval, supersession, comparator_reveal, reconciliation}` — **no withdrawal event exists** (open dependency for PRD-09 withdrawal). `ActorRole ∈ {operator, qualified_molecular_geneticist, vcep_curator, system}`. | `src/raptor/packet/decisions.py` | INTERNAL |
| 5.4 | AAVC is a **reveal-only external comparator**; `ScorerProvenance` resolves to a **BIAS raw row** and is never primary evidence. Neither may become a ClinVar `citation`/evidence. | `docs/reference/aavc-prior-art-audit-2026-07.md`, PRD-04 | INTERNAL |
| 5.5 | Two sign-off levels: operator (internal only) vs qualified molecular geneticist / VCEP (any externally meaningful classification or ClinVar submission). | STRATEGY §9 | INTERNAL |

---

## 6. Open verification items (must close before any build depends on them)

1. **Germline classification object name** — **RESOLVED (verified 2026-07-12):** the live production schema
   page (HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time)
   contains the **new `germlineSubmission[]` array requiring a `germlineClassification` object whose required
   classification field is `germlineClassificationDescription`**. The legacy `clinvarSubmission[]`/
   `clinicalSignificance` shape also appears but is **mutually exclusive** with `germlineSubmission` (the two
   cannot coexist). **RAPTOR pins to `germlineSubmission[].germlineClassification.germlineClassificationDescription`
   only and rejects the legacy/mixed shape** (§2.1–§2.2). The prior HARD-BLOCK is **closed**; re-pin guard in §2.5.
2. **`recordStatus` enum** — **RESOLVED (verified 2026-07-12):** the live schema allows only `novel`/`update`;
   there is **no `delete` value**. Withdrawal/deletion is the **separate top-level `clinvarDeletion.accessionSet[]`**
   object (§2.1–§2.2). A `recordStatus="delete"` reading was a prior error and is **rejected**.
3. ClinVar **review-status** wording and star mapping — re-fetch `.../docs/review_status/`.
4. **ClinGen VCEP Protocol v12** exact steps/committee names — re-fetch the official PDF.
5. Canonical **condition identifier** for tuberous sclerosis (MONDO/MedGen/OMIM id) — curator-confirmed.
6. The **TSC VCEP exists** (STRATEGY, verified 2026-06-16, with 0 ClinVar submissions at that date). Open
   item: confirm its **current roster/membership, status, contact, and the correct CDWG engagement route** —
   re-verify on ClinGen. *(Existence is **not** in question; framing corrected 2026-07-12.)*

---

## 7. Rubber-duck MAJOR findings — closure (2026-07-12)

| # | Finding | Resolution | Source / Type |
|---|---|---|---|
| MAJOR-1 | Withdrawal was mis-modeled as `recordStatus="delete"`. | The live ClinVar Submission API makes `recordStatus` a **required enum of only `novel`/`update`**. Withdrawal/deletion is the **separate top-level `clinvarDeletion` object** whose `accessionSet[]` entries each carry a **required** SCV `accession` + **optional** `reason`. Corrected in §2.1–§2.2, §6.2 and across PRD-09 (FR2/FR9/FR10.7/AC7). **No `recordStatus="delete"` remains except as a quoted, rejected prior error.** | `.../docs/api_http/` **[PRIMARY-OFFICIAL]**, verified 2026-07-12 |
| MAJOR-2 | TSC VCEP framed as possibly non-existent. | Reconciled with frozen STRATEGY: a **TSC VCEP exists** but had **0** ClinVar submissions at the dated verification (2026-06-16). Open dependency reframed to confirming **current roster/status/contact + CDWG engagement route**, not existence. Claim typing + verification dates preserved. | STRATEGY.md **[INTERNAL]**, verified 2026-06-16 |
| HARD-BLOCK **(now CLOSED)** | Germline classification **object name** was unconfirmed (earlier drafts saw only a `clinicalSignificance` container). | **CLOSED (verified 2026-07-12):** the live production schema page (HTML sha256 `3ed6b64bfff5b03c9cfe5ecf0e4f88096ff7116f0647c751027665e71a41dbad`, point-in-time) contains the **new `germlineSubmission[]` array requiring `germlineClassification` with required field `germlineClassificationDescription`**, alongside the legacy `clinvarSubmission`/`clinicalSignificance` shape which is **mutually exclusive** (cannot coexist). **RAPTOR pins to the new `germlineSubmission`/`germlineClassification` shape only and rejects legacy/mixed output** (§2.1–§2.2, §6.1; PRD-09 FR2/FR10). Re-pin guard added (§2.5). | `.../docs/api_http/` **[PRIMARY-OFFICIAL]**, verified 2026-07-12 |
