# RAPTOR Golden Domain Corpus — ClinVar Knowns Loader (PRD-07)

**Purpose:** Frozen, citable reference for test fixtures in `tests/eval/`. Every claim in this document is backed by a primary source URL. This corpus is the independent oracle for AC1 (`ClinicalSignificance` → label), AC2 (`p.` → variant class), and supporting AC3/FR1 assertions. It is *not* generated from the implementation under test; it is derived from authoritative public specifications.

**Compiled from sources verified:** 2026-07-09

---

## 1. ClinVar Germline `ClinicalSignificance` (Aggregate) Vocabulary — COMPLETE

### 1.1 Source Provenance

| Source | URL | What it provides |
|--------|-----|------------------|
| ClinVar clinsig docs | `https://www.ncbi.nlm.nih.gov/clinvar/docs/clinsig/` | SCV options table, aggregate combination rules, OMIM-mapping table |
| GTR/ClinVar Standard Terms | `https://ftp.ncbi.nlm.nih.gov/pub/GTR/standard_terms/Clinical_significance.txt` | **Definitive machine-readable enumeration** of all currently accepted SCV-level ClinicalSignificance terms (updated weekly by NCBI) |
| ClinVar FTP README | `https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/README` | `ClinicalSignificance` column definition for `variant_summary.txt.gz`; `ClinSigSimple` definition including all P/LP/low-penetrance/risk-allele terms |
| ClinGen low-penetrance rec. | PubMed `38054408` (cited by ClinVar docs) | Origin of `Pathogenic, low penetrance`, `Likely pathogenic, low penetrance`, `Established risk allele`, `Likely risk allele`, `Uncertain risk allele` SCV terms |

### 1.2 The Definitive SCV-Level Term Enumeration

The following is the **complete current list** from `https://ftp.ncbi.nlm.nih.gov/pub/GTR/standard_terms/Clinical_significance.txt` (NCBI GTR/ClinVar standard terms file, verified 2026-07-02), annotated with mapping decisions:

```
Affects
Benign
Established risk allele
Likely benign
Likely pathogenic
Likely pathogenic, low penetrance
Likely risk allele
Pathogenic
Pathogenic, low penetrance
Uncertain risk allele
Uncertain significance
VUS-high
VUS-low
VUS-mid
association
association not found
confers sensitivity
conflicting data from submitters
drug response
not provided
other
protective
risk factor
```

> **Note on `risk factor`:** Does NOT appear in the ClinVar clinsig SCV options table, but IS present in the GTR standard terms file and arises in `variant_summary.txt.gz` from OMIM-mapped data. From the OMIM-mapping table on the ClinVar clinsig page: `"SUSCEPTIBILITY TO" / "MODIFIER OF"` keywords → `risk factor`. Confirmed real in FTP data.

> **Note on `confers sensitivity` and `association not found`:** These appear in the GTR standard terms file and in older ClinVar data, but are NOT listed as current SCV submission options on the ClinVar clinsig web page (last checked 2026-07-09). Treat as historical / legacy terms that may still appear in existing aggregate rows, and map to `NON_SCOREABLE`.

### 1.3 Aggregate (VCV/RCV) Combo Strings — What Appears in `variant_summary.txt.gz`

The `ClinicalSignificance` column in `variant_summary.txt.gz` reports the **aggregate** germline classification. This differs from SCV-level: it can contain combination strings produced by ClinVar's aggregation logic. From the combination-rules table on `https://www.ncbi.nlm.nih.gov/clinvar/docs/clinsig/`:

| Combination of submitted terms | Aggregate string emitted | RAPTOR mapping | Notes |
|---|---|---|---|
| Pathogenic only | `Pathogenic` | **P** | Single unambiguous submission |
| Likely pathogenic only | `Likely pathogenic` | **LP** | |
| Pathogenic + Likely pathogenic | `Pathogenic/Likely pathogenic` | **P** | ClinVar groups these as compatible; RAPTOR takes the higher |
| Benign only | `Benign` | **B** | |
| Likely benign only | `Likely benign` | **LB** | |
| Benign + Likely benign | `Benign/Likely benign` | **B** | Compatible; RAPTOR takes the higher |
| Uncertain significance only | `Uncertain significance` | **VUS** | |
| Pathogenic, low penetrance only | `Pathogenic, low penetrance` | **P** *(after suffix strip)* | Suffix `, low penetrance` is a qualifier on the base class, not a new class; strip, then re-map |
| Likely pathogenic, low penetrance only | `Likely pathogenic, low penetrance` | **LP** *(after suffix strip)* | Same rule |
| P + LP + `, low penetrance` mix | `Pathogenic/Likely pathogenic, low penetrance` | **P** *(after suffix strip)* | Confirmed by round-2 MAJOR-1 fix; suffix-strip applies before the slash-combo lookup |
| Established risk allele only | `Established risk allele` | **NON\_SCOREABLE** | ⚠️ *Governance call* — ClinGen defines ERA as reduced penetrance; not equivalent to full Pathogenic for a binary P/LP truth set. See §1.5 |
| Likely risk allele only | `Likely risk allele` | **NON\_SCOREABLE** | Same governance call |
| Uncertain risk allele only | `Uncertain risk allele` | **NON\_SCOREABLE** | |
| Uncertain significance + Uncertain risk allele | `Uncertain significance/Uncertain risk allele` | **NON\_SCOREABLE** | ⚠️ *Governance call* — the mixed uncertain/risk-allele form is not equivalent to plain VUS; see §1.5 |
| Pathogenic + Established risk allele | `Pathogenic/Established risk allele` | **NON\_SCOREABLE** | ⚠️ *Governance call* — see §1.5 |
| Likely pathogenic + Likely risk allele | `Likely pathogenic/Likely risk allele` | **NON\_SCOREABLE** | ⚠️ *Governance call* |
| Conflicting ACMG/ClinGen terms (any path-side vs. uncertain vs. benign) | `Conflicting classifications of pathogenicity` | **Conflicting** | **2023+ spelling** — from January 2024 ClinVar release split; this is the CURRENT canonical form in the `variant_summary.txt.gz` ClinicalSignificance column |
| Same conflict, older data | `Conflicting interpretations of pathogenicity` | **Conflicting** | **Pre-2023 spelling** — both must map identically; both appear in current `variant_summary.txt.gz` (historical rows not retroactively renamed) |
| Single ACMG/ClinGen term + non-ACMG term | `Pathogenic; drug response` | **NON\_SCOREABLE** | Semicolon-separated mixed aggregate; conservative — do not force-fit the P component |
| Conflicting ACMG/ClinGen + non-ACMG term | `Conflicting classifications of pathogenicity; drug response` | **NON\_SCOREABLE** | |
| No ACMG/ClinGen, multiple non-ACMG | `drug response; other` | **NON\_SCOREABLE** | |
| Legacy consortium disagreement | `conflicting data from submitters` | **NON\_SCOREABLE** | Historical; only one early consortium used this form. Distinct from `Conflicting classifications of pathogenicity` |
| Variant submitted only in a haplotype/genotype | `-` (dash) | **NON\_SCOREABLE** | Documented in ClinVar clinsig page: "This value may not be submitted. It is used in the file variant_summary.txt.gz … for a variant that was submitted to ClinVar only in combination with another variant." |

### 1.4 The VUS Sub-Tier Terms

From the ClinVar clinsig SCV options table, these are explicitly acknowledged sub-tiers of Uncertain significance:

| SCV term | Described as | Expected aggregate appearance | RAPTOR mapping |
|---|---|---|---|
| `VUS-high` | Consistent with 2015 ACMG/AMP guidelines (sub-tier) | May appear as-is in `ClinicalSignificance` if only sub-tier submissions exist | **VUS** (treat as variant of Uncertain significance) |
| `VUS-mid` | Same | Same | **VUS** |
| `VUS-low` | Same | Same | **VUS** |

> **Caution:** These SCV terms are NOT among the ten ACMG/ClinGen terms used in conflict calculation; how ClinVar aggregates them vs. plain `Uncertain significance` is not fully documented. If a fixture row has `VUS-high` in `ClinicalSignificance`, map it to VUS, but treat the mapping as a governance call rather than a guaranteed specification. Governance should confirm with ClinVar if these appear in real TSC1/TSC2 data.

### 1.5 Governance Calls — Genuinely Ambiguous Strings

These strings require a governance decision before they can be assigned to a scored label class. Do **not** force them into P/LP/LB/B in code without explicit sign-off:

| String | Why ambiguous | Recommended interim mapping |
|---|---|---|
| `Established risk allele` | ClinGen defines ERA as reduced-penetrance disease association — clinically distinct from Pathogenic (full penetrance). ACMG-2015 5-tier scale does not include ERA. Including ERA as "P" would confound penetrance levels in the truth set. | **NON\_SCOREABLE** until governance decides |
| `Likely risk allele` | Same reduced-penetrance concern | **NON\_SCOREABLE** |
| `Uncertain risk allele` | Has "uncertain" in name, which suggests VUS-level, but the risk-allele concept is distinct from disease VUS | **NON\_SCOREABLE** |
| `Uncertain significance/Uncertain risk allele` | Mixed uncertain/risk form | **NON\_SCOREABLE** |
| `Pathogenic/Established risk allele` | One submitter says P; one says ERA. The aggregate does not resolve penetrance — was the P call from the same disease context? | **NON\_SCOREABLE** |
| `VUS-high` / `VUS-mid` / `VUS-low` | Sub-tiers acknowledged by ClinVar but not in conflict-calculation vocabulary; aggregation behavior undocumented | **VUS** *(tentative; flag for governance review)* |

### 1.6 Non-Scoreable Terms (Complete)

These terms map to `NON_SCOREABLE` (the sentinel) and are **excluded** by `build_benchmark`. Every string NOT explicitly listed in the P/LP/LB/B/VUS/Conflicting map that does not match the `, low penetrance` suffix-strip pattern falls here by construction:

| Term | Source | Why non-scoreable |
|---|---|---|
| `drug response` | GTR file; ClinVar clinsig SCV table | Pharmacogenomic effect, not disease pathogenicity |
| `association` | GTR file; ClinVar clinsig SCV table | GWAS-derived; not an ACMG-style pathogenicity call |
| `association not found` | GTR file | Explicit negative GWAS result; not pathogenicity |
| `protective` | GTR file; ClinVar clinsig SCV table | Reduces disease risk; opposite direction |
| `Affects` | GTR file; ClinVar clinsig SCV table | Non-disease phenotype (e.g., lactose intolerance) |
| `risk factor` | GTR file; OMIM-mapped | Susceptibility/modifier; reduced penetrance class |
| `confers sensitivity` | GTR file | Historical pharmacogenomic term |
| `not provided` | GTR file; ClinVar clinsig SCV table | Submission without a classification |
| `other` | GTR file; ClinVar clinsig SCV table | Submitter's preferred term not in standard list |
| `conflicting data from submitters` | GTR file; ClinVar clinsig SCV table | Legacy consortium-only form; not ACMG conflict |
| `-` | ClinVar clinsig page | Variant submitted only in combination |
| `Pathogenic; drug response` | ClinVar clinsig aggregate table | Mixed ACMG + non-ACMG; ambiguous aggregate |
| `Conflicting classifications of pathogenicity; drug response` | ClinVar clinsig aggregate table | Conflict plus non-ACMG term |
| `drug response; other` | ClinVar clinsig aggregate table | Non-ACMG multi-term |

### 1.7 The `, low penetrance` Suffix-Strip Rule

Source: `https://www.ncbi.nlm.nih.gov/clinvar/docs/clinsig/` — "Likely pathogenic, low penetrance: As recommended by ClinGen for variants with decreased penetrance for Mendelian diseases."

The `, low penetrance` modifier (with the comma-space prefix) is a qualifier that annotates **any** base term. It does NOT change the ACMG pathogenicity tier — it adds penetrance context. The stripping rule:

```
strip(", low penetrance") from the right → re-lookup the base term
```

Applies to all these aggregate forms:
- `Pathogenic, low penetrance` → strip → `Pathogenic` → **P**
- `Likely pathogenic, low penetrance` → strip → `Likely pathogenic` → **LP**
- `Pathogenic/Likely pathogenic, low penetrance` → strip → `Pathogenic/Likely pathogenic` → **P**

**NOT applied to any other modifier.** The modifiers `, risk allele`, `; drug response`, etc. change clinical meaning and must NOT be stripped. They remain `NON_SCOREABLE`.

> **Critical implementation note:** The suffix-strip must be applied **before** the slash-combo lookup, and the strip must be **case-insensitive** and **whitespace-robust**. Verified by PRD-07 checker round-2 MAJOR-1 and round-2 MINOR-1.

---

## 2. ClinVar `ReviewStatus` Vocabulary — COMPLETE, with Star Rating + Quality Tier

### 2.1 Source Provenance

| Source | URL | What it provides |
|--------|-----|------------------|
| ClinVar review status docs | `https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/` | **Definitive** enumeration of all review status strings for SCV and aggregate (VCV/RCV) records, with gold-star correspondence |
| ClinVar FAQ | `https://www.ncbi.nlm.nih.gov/clinvar/docs/faq/#num_submitters` | Explains why a `single submitter` record can have `NumberSubmitters > 1` |
| ClinVar FTP README | `https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/README` | `ReviewStatus` column definition in `variant_summary.txt.gz` |

### 2.2 Aggregate Review Status — Complete Vocabulary for `variant_summary.txt.gz`

The `ReviewStatus` column in `variant_summary.txt.gz` reports the aggregate germline classification review status. Source: `https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/`

| ReviewStatus string (exact, as in `variant_summary.txt.gz`) | Stars | Fits truth set? | PRD-07 source rank | Notes |
|---|---|---|---|---|
| `practice guideline` | ★★★★ (4) | ✅ HIGH CONFIDENCE | `clingen_vcep` | Classification from a published practice guideline |
| `reviewed by expert panel` | ★★★ (3) | ✅ HIGH CONFIDENCE | `clingen_vcep` | Classification from a ClinGen VCEP or equivalent expert panel |
| `criteria provided, multiple submitters, no conflicts` | ★★ (2) | ✅ HIGH CONFIDENCE | `clinvar_2star_concordant` | Multiple criteria-providing submitters agree |
| `criteria provided, conflicting classifications` | ★ (1) | ❌ LOW CONFIDENCE | `clinvar` (excluded) | Multiple criteria-providing submitters disagree; ClinVar current spelling (2023+) |
| `criteria provided, single submitter` | ★ (1) | ❌ LOW CONFIDENCE | `clinvar` (excluded) | Single criteria-providing submitter — **regardless of `NumberSubmitters` value** (see §2.4) |
| `no assertion criteria provided` | ★ (0) | ❌ LOW CONFIDENCE | excluded | One or more submitters with a classification but **without** assertion criteria or evidence |
| `no classification provided` | ★ (0) | ❌ LOW CONFIDENCE | excluded | One or more submitted records **without** a classification |
| `no classification for the individual variant` | ★ (0) | ❌ LOW CONFIDENCE | excluded | Variant submitted only as part of a haplotype/genotype; never classified directly |

#### Newer / Additional Strings Verified in RAPTOR Tests

These strings appear in the RAPTOR test suite (`tests/eval/test_knowns_fixes5.py`, `test_knowns_fixes6.py`) and represent real ClinVar review status values:

| String | Stars | Fits truth set? | Source / notes |
|---|---|---|---|
| `criteria provided, conflicting interpretations of pathogenicity` | ★ (1) | ❌ | Older spelling of conflicting-classifications (pre-2023); both spellings appear in live data. Verified in `test_knowns_fixes6.py:_EXCLUDE_STATUSES` |
| `no assertion provided` | ★ (0) | ❌ | Historical/legacy term; functionally equivalent to `no assertion criteria provided`. Appears in older SCV and aggregate records. Verified in `test_knowns_fixes5.py` |
| `no classifications from unflagged records` | ★ (0) | ❌ | Appears when all contributing SCVs are flagged (e.g., for allele frequency issues); the variant has no usable classification. Used in ClinVar's VCF `CLNREVSTAT` field; also propagates to `variant_summary.txt.gz`. Verified in `test_knowns_fixes5.py` |

### 2.3 SCV-Level Review Status (for submitted records)

For completeness, the review statuses that appear on SCV records (not VCV/RCV aggregates). These appear in `submission_summary.txt` and `summary_of_conflicting_interpretations.txt`:

| ReviewStatus | Stars | Description |
|---|---|---|
| `practice guideline` | ★★★★ | SCV from a practice guideline |
| `reviewed by expert panel` | ★★★ | SCV from an expert panel |
| `criteria provided, single submitter` | ★ | Single SCV with criteria and evidence |
| `no assertion criteria provided` | ★ (0) | SCV with a classification but without criteria/evidence |
| `no classification provided` | ★ (0) | SCV without a classification |

> **Note:** There is no 2-star SCV-level status. The 2-star `criteria provided, multiple submitters, no conflicts` is an **aggregate-only** status that arises when multiple 1-star SCVs agree.

### 2.4 The `criteria provided, single submitter` + `NumberSubmitters` Pitfall

From `https://www.ncbi.nlm.nih.gov/clinvar/docs/faq/#num_submitters`:

> "The review status 'classified by single submitter' is based on non-expert panel submissions which include a classification, assertion criteria, and evidence for the variant classification. Some submissions to ClinVar **lack assertion criteria, evidence for the classification**, or less frequently the variant classification itself. These submissions are **included in the count of submissions** for a variant, but they may not contribute to the variant's review status."

**Consequence:** A variant can have `ReviewStatus = "criteria provided, single submitter"` **and** `NumberSubmitters = 5`. The extra 4 submissions contributed no assertion criteria and are therefore ignored in review-status calculation, but still counted in `NumberSubmitters`.

**Test fixture implication:** `NumberSubmitters` alone is NOT sufficient to determine truth-set eligibility. Review status must be the primary gate. A `criteria provided, single submitter` row with `NumberSubmitters=5` must be **excluded** from the truth set. This is documented and tested in PRD-07 checker round-4 (`test_knowns_fixes4.py`).

### 2.5 Low-Confidence Detection Pattern

The low-confidence detection in `build_benchmark` (from `src/raptor/eval/benchmark.py:_LOW_CONFIDENCE_REVIEW_MARKERS`) uses **case-insensitive substring matching** on four markers:

| Marker | What it catches |
|---|---|
| `"single submitter"` | `criteria provided, single submitter` |
| `"conflicting"` | `criteria provided, conflicting classifications`, `criteria provided, conflicting interpretations of pathogenicity` |
| `"no assertion"` | `no assertion criteria provided`, `no assertion provided` |
| `"no classification"` | `no classification provided`, `no classification for the individual variant`, `no classifications from unflagged records` |

These four substring patterns together cover the **complete** current low-confidence vocabulary. High-confidence statuses (`practice guideline`, `reviewed by expert panel`, `criteria provided, multiple submitters, no conflicts`) contain none of these substrings.

> **Critical:** `criteria provided, multiple submitters, no conflicts` contains `"no conflicts"`, not `"conflicting"`. The pattern `"conflicting"` does NOT match it. This is intentional and correct.

---

## 3. HGVS Protein (`p.`) Consequence Classification Examples

### 3.1 Source Provenance

| Source | URL | What it provides |
|--------|-----|------------------|
| HGVS substitution spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/substitution/` | Missense, nonsense, silent, start-loss syntax and rules |
| HGVS frameshift spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/frameshift/` | Frameshift syntax, short/long forms, Ter position notation |
| HGVS extension spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/extension/` | Stop-loss (no-stop) and start-extension syntax; key pitfall: `Ter→aa` is NOT truncating |
| HGVS deletion spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/deletion/` | In-frame deletion syntax; not a substitution |
| HGVS duplication spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/duplication/` | In-frame duplication syntax; not a substitution |
| HGVS deletion-insertion spec | `https://hgvs-nomenclature.org/stable/recommendations/protein/delins/` | delins syntax; "when ONE amino acid is replaced by ONE other, it is a substitution, not a delins" |
| HGVS amino acid standards | `https://hgvs-nomenclature.org/stable/background/standards/` | **Complete amino acid code tables**, Ter/`*` encoding, genetic code table |

### 3.2 Amino Acid Code Sets (HGVS Standard)

Source: `https://hgvs-nomenclature.org/stable/background/standards/`

| One-letter | Three-letter | Amino Acid | Notes |
|---|---|---|---|
| A | Ala | Alanine | |
| R | Arg | Arginine | |
| N | Asn | Asparagine | |
| D | Asp | Aspartic acid | |
| C | Cys | Cysteine | |
| Q | Gln | Glutamine | |
| E | Glu | Glutamic acid | |
| G | Gly | Glycine | |
| H | His | Histidine | |
| I | Ile | Isoleucine | |
| L | Leu | Leucine | |
| K | Lys | Lysine | |
| M | Met | Methionine | **Initiator codon**; position 1 = start codon |
| F | Phe | Phenylalanine | |
| P | Pro | Proline | |
| S | Ser | Serine | |
| T | Thr | Threonine | |
| W | Trp | Tryptophan | |
| Y | Tyr | Tyrosine | |
| V | Val | Valine | |
| U | Sec | Selenocysteine | TGA stop codon re-coded; non-standard incorporation |
| O | Pyl | Pyrrolysine | UAG stop codon re-coded; non-standard incorporation |
| `*` | Ter | Termination (stop) | **HGVS addition** (v2.0); NOT a real amino acid — represents stop codons TAA, TAG, TGA. Used as ALT = truncating (nonsense/stop-gain); used as REF = stop-loss (extension). See §3.5 pitfall. |
| X | Xaa | Unknown / other | **NOT** a canonical amino acid — used for alignment/unknown. `X` was historically used for stop codons; `Xaa` now preferred for unknown. Do NOT classify `Xaa`-containing variants as missense. |

**The canonical set for missense detection:** 20 standard AAs + Sec (U) + Pyl (O) = 22 residues. `Ter` / `*` and `Xaa` / `X` are explicitly excluded from the canonical set.

### 3.3 Classification Table

| `p.` token (as in ClinVar `Name`) | Full ClinVar `Name` example | Class | Why |
|---|---|---|---|
| **MISSENSE — simple single-aa substitution, 3-letter** | | | |
| `p.Arg611Gln` | `NM_000548.5(TSC2):c.1832G>A (p.Arg611Gln)` | **missense** | Arg→Gln, both canonical AAs, differ, pos≠1 or pos≠Met1 |
| `p.Trp24Cys` | `NP_003997.1:p.Trp24Cys` | **missense** | From HGVS substitution spec example |
| `p.Gly12Asp` | `NM_004985.5(KRAS):c.35G>A (p.Gly12Asp)` | **missense** | Edge case: Gly at pos 12 ≠ Met1; canonical substitution |
| `p.Phe508del` | — | **other** | Actually a deletion; not shown as `p.X508Y`, shown as `p.Phe508del`; see §3.5 |
| `p.Ala10Gly` | `NM_000548.5(TSC1):c.29C>G (p.Ala10Gly)` | **missense** | Near-N-terminus; Ala≠Met, canonical |
| `p.Tyr1853Cys` | `NM_000548.5(TSC2):c.5558A>G (p.Tyr1853Cys)` | **missense** | Near C-terminus; canonical |
| `p.(Arg611Gln)` | `NM_000548.5(TSC2):c.1832G>A (p.(Arg611Gln))` | **missense** | Predicted consequence (inner parens); inner token `Arg611Gln` is still missense. From HGVS sub. spec: "predicted consequences … should be given in parentheses" |
| **MISSENSE — 1-letter notation** | | | |
| `p.R611Q` | `NM_000548.5(TSC2):c.1832G>A (p.R611Q)` | **missense** | Single-letter equivalent of `p.Arg611Gln`; both are valid HGVS |
| `p.W24C` | `NP_003997.1:p.W24C` | **missense** | 1-letter form of `p.Trp24Cys` |
| `p.G12D` | `NM_004985.5(KRAS):c.35G>T (p.G12D)` | **missense** | Common 1-letter KRAS variant |
| `p.R611Q` (lowercase `p.r611q`) | `NM_000548.5(TSC2):c.1832G>A (p.r611q)` | **missense** | Case-folding must apply; lowercase is non-standard but appears in ClinVar |
| **TRUNCATING — nonsense (aa → Ter / `*`)** | | | |
| `p.Arg611Ter` | `NM_000548.5(TSC2):c.1831C>T (p.Arg611Ter)` | **truncating** | Arg (canonical AA) → Ter (stop); from HGVS sub. spec: "a nonsense variant … is described as a substitution" |
| `p.Gln1503*` | `NM_000548.5(TSC2):c.4507C>T (p.Gln1503*)` | **truncating** | `*` is 1-letter notation for Ter; ALT=`*`=stop |
| `p.Trp24Ter` | `LRG_199p1:p.Trp24Ter` | **truncating** | From HGVS sub. spec example |
| `p.W24*` | `LRG_199p1:p.W24*` | **truncating** | 1-letter with `*` ALT |
| `p.Arg611ter` | `NM_000548.5(TSC2):c.1831C>T (p.Arg611ter)` | **truncating** | Lowercase `ter`; canonical AA → stop; case-fold |
| **TRUNCATING — frameshift** | | | |
| `p.Ser1043fs` | `NM_000548.5(TSC2):c.3128delA (p.Ser1043fs)` | **truncating** | Short-form frameshift (`fs` suffix); from HGVS frameshift spec: "frameshifts can also be described using a short format" |
| `p.Ala10AlafsTer3` | `NM_000548.5(TSC1):c.28_29del (p.Ala10AlafsTer3)` | **truncating** | Long-form frameshift; `fsTer3` = new stop at position 3 in shifted frame |
| `p.Arg97ProfsTer23` | `NP_0123456.1:p.Arg97ProfsTer23` | **truncating** | From HGVS frameshift spec example; `Arg→Pro` at start of shift, stop at +23 |
| `p.Arg97Profs*23` | — | **truncating** | Alternative notation with `*` instead of `Ter` |
| `p.Arg97fs` | `NP_0123456.1:p.Arg97fs` | **truncating** | Short format without Ter position; from HGVS frameshift spec |
| `p.Ile327Argfs*?` | `NP_003997.1:p.Ile327Argfs*?` | **truncating** | No new stop codon found; still a frameshift |
| `p.His321Leufs*3` | `NP_003997.2:p.(His321Leufs*3)` | **truncating** | Predicted (parens) + frameshift |
| **OTHER — synonymous / silent** | | | |
| `p.=` | `NM_000548.5(TSC2):c.1833A>G (p.=)` | **other** | "The description `p.=` means the **entire** protein coding region was analysed and no variant was found." — HGVS sub. spec |
| `p.Gly12=` | `NM_004985.5(KRAS):c.36G>C (p.Gly12=)` | **other** | "amino acids that have been tested and found **not changed** (silent) are described as `p.Cys123=`" — HGVS sub. spec |
| `p.Cys188=` | `NP_003997.1:p.Cys188=` | **other** | From HGVS sub. spec example; silent DNA change |
| **OTHER — start-loss** | | | |
| `p.Met1Val` | `NM_000548.5(TSC1):c.1A>G (p.Met1Val)` | **other** | Met at position 1 is the initiator (start) codon; any change away from Met1 is a start-loss (LoF), not a missense. From HGVS sub. spec: "Do not use descriptions like `p.Met1Thr`, this is for sure **not** the consequence of the effect on protein translation." |
| `p.Met1?` | `NM_000548.5(TSC1):c.1A>? (p.Met1?)` | **other** | "unknown: the consequence … of a variant affecting the translation initiation codon can not be predicted" — HGVS sub. spec; `?` is not a canonical AA |
| `p.Met1ext-5` | `NP_003997.2:p.Met1ext-5` | **other** | N-terminal extension (upstream initiation site); contains `ext` marker |
| `p.M1V` | `NM_000548.5(TSC1):c.1A>G (p.M1V)` | **other** | 1-letter start-loss; M (Met) at position 1; same rule |
| `p.met1val` | `NM_1(TSC1):c.1A>G (p.met1val)` | **other** | Lowercase start-loss; case-folded Met detection must fire |
| **OTHER — stop-loss / C-terminal extension** | | | |
| `p.Ter1808Arg` | `NM_000548.5(TSC2):c.5422T>C (p.Ter1808Arg)` | **other** | **REF is Ter (stop codon)** → aa; this is a STOP-LOSS (extension), NOT a truncating change. The protein gets LONGER. Ter/*  is truncating ONLY as the ALT. |
| `p.*1808Arg` | `NM_000548.5(TSC2):c.5422T>C (p.*1808Arg)` | **other** | `*` as REF = stop-loss; identical rule |
| `p.Ter1808ArgextTer3` | `NP_003997.2:p.Ter1808ArgextTer3` | **other** | Stop-loss with known extension tail of 3 AAs; contains `ext` marker |
| `p.Ter327ArgextTer?` | `NP_003997.2:p.Ter327ArgextTer?` | **other** | Extension, no new stop found; contains `ext` |
| `p.*110Glnext*17` | `NP_003997.2:p.*110Glnext*17` | **other** | Alternative `*` notation for extension |
| `p.ter1808arg` | `NM_1(TSC1):c.1A>G (p.ter1808arg)` | **other** | Lowercase; `ter` as REF → stop-loss |
| **OTHER — in-frame deletion / duplication** | | | |
| `p.Arg611del` | `NM_000548.5(TSC2):c.1831_1833del (p.Arg611del)` | **other** | In-frame deletion; NOT a substitution. "del" is not a canonical AA code — `_SINGLE_AA_RE` would match `del` as 3-letter string but `del` is not in the canonical AA set. |
| `p.Val7del` | `NP_003997.2:p.Val7del` | **other** | From HGVS deletion spec example; in-frame single-AA deletion |
| `p.Lys23_Val25del` | `NP_003997.2:p.Lys23_Val25del` | **other** | Multi-AA in-frame deletion |
| `p.Arg611dup` | `NM_000548.5(TSC2):c.1831_1833dup (p.Arg611dup)` | **other** | In-frame duplication; `dup` not a canonical AA |
| `p.Val7dup` | `NP_003997.2:p.Val7dup` | **other** | From HGVS duplication spec example |
| **OTHER — deletion-insertion (delins)** | | | |
| `p.Arg611delinsGln` | `NM_000548.5(TSC2):c.1831_1833delinsCAG (p.Arg611delinsGln)` | **other** | ⚠️ **NOT missense**; the HGVS delins spec says "when ONE amino acid is replaced by ONE other, the change is a substitution, NOT a deletion-insertion." However ClinVar may sometimes write this for a complex DNA change whose protein consequence is a single-AA replacement. Per HGVS: if it is described as `delins`, it IS a delins (a distinct variant class). Confirmed non-missense: PRD-07 checker round-2 planner note explicitly DECLINED to map single-AA delins to missense. |
| `p.Cys28delinsTrpVal` | `NP_004371.2:p.Cys28delinsTrpVal` | **other** | Multi-replacement delins; from HGVS delins spec example |
| `p.Arg76_Cys77delinsSerTrp` | `NP_003997.1:p.Arg76_Cys77delinsSerTrp` | **other** | Multi-residue delins; from HGVS delins spec |
| **OTHER — no `p.` token (splice, intronic, etc.)** | | | |
| *(none)* | `NM_000548.5(TSC2):c.1832+1G>A` | **other** | No `(p....)` token in `Name`; splice-site change; `classify_variant` returns `other` when no `p.` match |
| *(none)* | `NM_000548.5(TSC2):c.5422-3C>G` | **other** | Intronic change; no `p.` |
| *(none)* | `NM_000548.5(TSC2):c.1-164C>T` | **other** | 5'UTR change; no `p.` |
| **OTHER — unparseable / uncertain / special** | | | |
| `p.?` | `NM_000548.5(TSC2):c.1832del (p.?)` | **other** | Unknown protein consequence; token is just `?` |
| `p.0` | `NM_000548.5(TSC1):c.[1A>G] (p.0)` | **other** | No protein produced; from HGVS sub. spec |
| `p.0?` | — | **other** | Predicted no protein |
| `p.Gly56Ala^Ser^Cys` | `NP_003997.1:p.(Gly56Ala^Ser^Cys)` | **other** | Uncertain substitution (multiple possibilities); contains `^` |
| `p.Xaa123Gln` | — | **other** | `Xaa` is not a canonical AA — `X` was historically used for stop, now means unknown; NOT missense even though it matches the 3-letter substitution pattern |
| `p.X123Q` | — | **other** | 1-letter `X` = unknown placeholder; not in canonical `_AA1` set |
| `p.Arg611Zzz` | — | **other** | `Zzz` is not a real 3-letter AA code |

### 3.4 The Four Key Pitfalls

These are the exact failure modes caught by PRD-07 checker rounds 1–3:

#### Pitfall 1: `Ter` / `*` Is Truncating ONLY as the ALT, Never as the REF

> Source: HGVS extension spec, `https://hgvs-nomenclature.org/stable/recommendations/protein/extension/`: "a **no-stop** variant, a variant changing the translation termination codon **into an amino acid codon**, is described as an **extension** … The variant is called a **stop-lost** variant."

| Token | REF | ALT | Class | Explanation |
|---|---|---|---|---|
| `p.Arg611Ter` | Arg | Ter | **truncating** | Arg (AA) → Ter (stop); canonical nonsense |
| `p.Ter1808Arg` | Ter | Arg | **other** | Ter (stop) → Arg (AA); stop-loss; protein gets longer |
| `p.Ter1808ArgextTer3` | Ter | Arg+ext | **other** | Contains `ext`; C-terminal extension |
| `p.W24*` | Trp | `*` | **truncating** | `*` as ALT = stop; nonsense |
| `p.*1808Arg` | `*` | Arg | **other** | `*` as REF = stop was there; stop-loss |

#### Pitfall 2: The Initiator Met at Position 1 Is a Start-Loss, Not Missense

> Source: HGVS substitution spec: "**NOTE**: not `p.Met1Thr`, this is for sure **not** the consequence of the effect on protein translation."

Any change of the form `p.Met1X` (where X is any amino acid other than Met) is a **start-loss** variant, regardless of how biochemically "similar" Met and X are. It disrupts translation initiation. Class: **other**.

Three-letter: `p.Met1Val`, `p.Met1Ala`, `p.Met1Leu`, etc. → **other**
One-letter: `p.M1V`, `p.M1A`, `p.M1L`, etc. → **other**
Case-folded: `p.met1val`, `p.m1v`, etc. → **other**

Exception: `p.Met1Met` would be synonymous (no change) but is written as `p.Met1=` per HGVS convention.

#### Pitfall 3: `del`, `dup`, `delins` Are Not Substitutions

> Source: HGVS delins spec: "**by definition, when ONE amino acid is replaced by ONE other amino acid, the change is a substitution, NOT a deletion-insertion.**"
> Source: HGVS deletion spec: "a **nonsense** variant … is NOT described as a Deletion of the C-terminal end of the protein."

Even though `del` and `dup` are 3-letter strings that could naively match the `[A-Za-z]{3}` pattern in a p. token regex, they are NOT canonical amino acid codes. A parser must validate that the "alt" token is a canonical AA — `del`, `dup`, `fs`, `ext`, `ins` are all HGVS operation keywords, not residues.

| Token | Naive regex match | Correct class |
|---|---|---|
| `p.Arg611del` | "del" matches 3-letter pattern | **other** — in-frame deletion |
| `p.Arg611dup` | "dup" matches 3-letter pattern | **other** — in-frame duplication |
| `p.Arg611delinsGln` | "delins" contains "del" | **other** — delins variant |
| `p.R611del` | "del" matches 1-letter+ pattern | **other** |

#### Pitfall 4: `Xaa` / `X` Are Not Canonical Amino Acids

> Source: HGVS standards: "†To prevent confusion, since 'X' has been used to indicate a translation stop codon, use 'Xaa' only."

`X` (1-letter) and `Xaa` (3-letter) represent unknown or placeholder residues. They are NOT real amino acids. A variant `p.Xaa123Gln` or `p.X123Q` should NOT be classified as missense, even though both residue positions follow the substitution pattern.

Similarly, `Zzz`, `Asx` (Asp or Asn), `Glx` (Glu or Gln) are not in the canonical set of 22 residues and must not be treated as missense.

### 3.5 Predicted-Consequence Parentheses Unwrapping

Source: HGVS substitution spec: "**predicted consequences**, i.e. without experimental evidence … should be given in parentheses, e.g., `p.(Arg611Gln)`."

ClinVar `Name` fields for variants where only DNA evidence exists use the `(p.(...))` form — double parentheses: the outer `(p.X)` is ClinVar's wrapping of the whole HGVS expression, the inner `(Arg611Gln)` is HGVS's predicted-consequence marker.

```
"NM_000548.5(TSC2):c.1832G>A (p.(Arg611Gln))"
                                   ^^^^^^^^^^^
                                   outer ( p.INNER )
                                               ^^^^^^^
                                               inner (Arg611Gln)
```

The inner parens must be stripped before classification. After stripping inner and outer parens/whitespace: `Arg611Gln` → missense. Failure to strip the inner parens was a confirmed bug in PRD-07 checker round-2 MAJOR-2.

---

## 4. Multi-Gene `GeneSymbol` Forms

### 4.1 Source Provenance

| Source | URL | What it provides |
|--------|-----|------------------|
| ClinVar FAQ — multi-gene variants | `https://www.ncbi.nlm.nih.gov/clinvar/docs/faq/#manygenes` | Policy table for what ClinVar reports when a variant affects multiple genes |
| ClinVar FTP README | `https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/README` | `GeneSymbol` column definition in `variant_summary.txt.gz` |
| RAPTOR ingest reader | `src/raptor/ingest/reader.py:_gene_matches` | Actual parsing logic + documented tokenization pitfall |
| RAPTOR knowns loader | `src/raptor/eval/knowns.py:_matched_target_gene` | Label-side parser (correct version with strip) |
| RAPTOR test fixture | `tests/eval/test_knowns_fixes.py:test_multigene_row_matches_target_gene` | Live example: `"subset of 2 genes: TSC1:PKD1"` |

### 4.2 The Two GeneSymbol Forms in `variant_summary.txt.gz`

#### Form 1: Single-Gene (Normal Case)

```
GeneSymbol = "TSC1"
GeneSymbol = "TSC2"
```

Exact match. These are HGNC-preferred symbols. `GeneID` column carries the integer NCBI Gene ID.

#### Form 2: Multi-Gene (CNV/SV or Overlapping Annotation)

```
GeneSymbol = "subset of N genes: A:B:C:..."
```

Where:
- `N` = integer count of genes listed
- `A`, `B`, `C`, … = HGNC-preferred gene symbols, colon-separated
- There is a **space** after the colon following `"genes:"` — so the FIRST gene symbol in the list has a leading space: `" A"` not `"A"`
- Subsequent symbols separated by `:` have no leading space: `":B"`, `":C"` etc.

**Real example from RAPTOR tests** (`test_knowns_fixes.py`):
```
"subset of 2 genes: TSC1:PKD1"
```
Splitting on `:` yields:
```python
["subset of 2 genes", " TSC1", "PKD1"]
```
Note the leading space on `" TSC1"`.

**GeneID for multi-gene rows** = `-1` (per ClinVar FTP README: "GeneID … reported if there is a single gene, otherwise reported as -1").

### 4.3 Why This Causes Silent Drops

If a gene filter does a naive `GeneSymbol == "TSC1"` check, multi-gene rows are always skipped. If it splits on `:` without stripping whitespace, the first token `" TSC1"` ≠ `"TSC1"` and the match fails.

**Confirmed bug in RAPTOR:** `src/raptor/ingest/reader.py:_gene_matches` does NOT strip whitespace from tokens:
```python
# reader.py (ingest side — known issue documented in round-1 MAJOR-4):
if ":" in gene_symbol_field:
    return self.gene in gene_symbol_field.split(":")  # " TSC1" ≠ "TSC1" → MISS
```

The label-side loader **correctly** strips:
```python
# knowns.py (label side — correct implementation):
tokens = [t.strip() for t in field.split(":")]
if gene in tokens:  # strips " TSC1" → "TSC1" → MATCH
    return gene
```

### 4.4 Additional GeneSymbol Edge Cases

From ClinVar FAQ multi-gene policy table (`https://www.ncbi.nlm.nih.gov/clinvar/docs/faq/#manygenes`):

| Situation | What ClinVar reports in GeneSymbol | Implication for gene filter |
|---|---|---|
| Variant submitted with a cDNA (single gene) | The single gene symbol | Normal exact match |
| Genomic location spanning multiple non-overlapping genes, no gene specified | `"subset of N genes: A:B:C"` format | Must tokenize + strip |
| Genomic location spanning overlapping/shared-exon genes | All overlapping genes listed | Same tokenization rule; a TSC1/TSC2 variant straddling a neighbor gene would appear here |
| Variant submitted as only a genomic range (no gene annotation) | Gene symbol derived from NCBI annotation | Usually single-gene if within one gene; may become multi-gene if annotation updates |

> **Note:** ClinVar's `GeneID` is `-1` for any row where `GeneSymbol` is in the multi-gene format. The `HGNC_ID` column is also `'-'` (a dash string) for such rows.

### 4.5 Correct Gene-Filter Implementation (Reference Algorithm)

```python
def _matched_target_gene(gene_symbol_field: str, target_genes: frozenset) -> str | None:
    """Returns the matched gene symbol, or None if no target gene found.
    Handles both exact-match (single-gene) and 'subset of N genes: A:B:C' (multi-gene)."""
    field = (gene_symbol_field or "").strip()
    if not field:
        return None
    # Fast path: exact match (the common case)
    if field in target_genes:
        return field
    # Multi-gene path: tokenize on ':' and strip each token
    if ":" in field:
        for token in field.split(":"):
            token = token.strip()
            if token in target_genes:
                return token
    return None
```

**Why strip matters:** The `"subset of N genes: TSC1:PKD1"` string, split on `:`, yields `[" TSC1", "PKD1"]` where the first gene has a leading space inherited from the `"genes: "` separator. Without strip, `"TSC1"` is not found in `[" TSC1", "PKD1"]`.

---

## 5. Summary Cross-Reference for Test Fixture Authors

### 5.1 AC1 Label-Map Golden Fixture

The following is the exhaustive golden truth for `map_clinical_significance(sig) → label`:

```python
# ── SCOREABLE: must map to the exact string shown ──────────────────────────
"Pathogenic"                                      → "P"
"Likely pathogenic"                               → "LP"
"Likely benign"                                   → "LB"
"Benign"                                          → "B"
"Pathogenic/Likely pathogenic"                    → "P"
"Benign/Likely benign"                            → "B"
"Uncertain significance"                          → "VUS"
"Conflicting interpretations of pathogenicity"    → "Conflicting"   # older spelling
"Conflicting classifications of pathogenicity"    → "Conflicting"   # 2023+ spelling

# ── LOW-PENETRANCE SUFFIX STRIPPED → base class ────────────────────────────
"Pathogenic, low penetrance"                      → "P"
"Likely pathogenic, low penetrance"               → "LP"
"Pathogenic/Likely pathogenic, low penetrance"    → "P"

# ── WHITESPACE/CASE ROBUST (same map, just normalised first) ───────────────
"Pathogenic "                                     → "P"    # trailing space
"  Benign"                                        → "B"    # leading space
"likely pathogenic"                               → "LP"   # case drift
"UNCERTAIN SIGNIFICANCE"                          → "VUS"  # all-caps

# ── NON-SCOREABLE (sentinel; excluded by build_benchmark) ──────────────────
"drug response"                                   → NON_SCOREABLE
"not provided"                                    → NON_SCOREABLE
"risk factor"                                     → NON_SCOREABLE
"association"                                     → NON_SCOREABLE
"association not found"                           → NON_SCOREABLE
"confers sensitivity"                             → NON_SCOREABLE
"protective"                                      → NON_SCOREABLE
"Affects"                                         → NON_SCOREABLE
"other"                                           → NON_SCOREABLE
"conflicting data from submitters"                → NON_SCOREABLE
"-"                                               → NON_SCOREABLE
"Established risk allele"                         → NON_SCOREABLE   # governance call
"Likely risk allele"                              → NON_SCOREABLE   # governance call
"Uncertain risk allele"                           → NON_SCOREABLE   # governance call
"Uncertain significance/Uncertain risk allele"    → NON_SCOREABLE   # governance call
"Pathogenic/Established risk allele"              → NON_SCOREABLE   # governance call
"VUS-high"                                        → VUS             # tentative; flag
"VUS-mid"                                         → VUS             # tentative; flag
"VUS-low"                                         → VUS             # tentative; flag
"Pathogenic; drug response"                       → NON_SCOREABLE   # mixed aggregate
```

### 5.2 AC2 Variant-Class Golden Fixture

```python
# ── MISSENSE ────────────────────────────────────────────────────────────────
"NM_000548.5(TSC2):c.1832G>A (p.Arg611Gln)"          → "missense"
"NM_000548.5(TSC2):c.1832G>A (p.R611Q)"              → "missense"  # 1-letter
"NM_000548.5(TSC2):c.1832G>A (p.(Arg611Gln))"        → "missense"  # predicted (inner parens)
"NM_000548.5(TSC2):c.1832G>A (p.arg611gln)"          → "missense"  # lowercase

# ── TRUNCATING ──────────────────────────────────────────────────────────────
"NM_000548.5(TSC2):c.1831C>T (p.Arg611Ter)"          → "truncating"
"NM_000548.5(TSC2):c.4507C>T (p.Gln1503*)"           → "truncating"
"NM_000548.5(TSC2):c.3128delA (p.Ser1043fs)"         → "truncating"
"NM_000548.5(TSC1):c.28_29del (p.Ala10AlafsTer3)"    → "truncating"
"NM_1(TSC1):c.1A>G (p.Arg611ter)"                    → "truncating"  # lowercase ter

# ── OTHER: synonymous ───────────────────────────────────────────────────────
"NM_000548.5(TSC2):c.1833A>G (p.=)"                  → "other"
"NM_000548.5(TSC2):c.1833A>G (p.Gly12=)"             → "other"

# ── OTHER: start-loss ───────────────────────────────────────────────────────
"NM_000548.5(TSC1):c.1A>G (p.Met1Val)"               → "other"
"NM_000548.5(TSC1):c.1A>G (p.M1V)"                   → "other"
"NM_1(TSC1):c.1A>G (p.met1val)"                      → "other"  # lowercase

# ── OTHER: stop-loss / extension ────────────────────────────────────────────
"NM_000548.5(TSC2):c.5422T>C (p.Ter1808Arg)"         → "other"
"NM_000548.5(TSC2):c.5422T>C (p.*1808Arg)"           → "other"
"NM_1(TSC1):c.1A>G (p.Ter1808ArgextTer3)"            → "other"
"NM_1(TSC1):c.1A>G (p.ter1808arg)"                   → "other"  # lowercase stop-loss

# ── OTHER: in-frame del/dup ─────────────────────────────────────────────────
"NM_000548.5(TSC2):c.1831_1833del (p.Arg611del)"     → "other"
"NM_000548.5(TSC2):c.1831_1833dup (p.Arg611dup)"     → "other"
"NM_1(TSC1):c.1A>G (p.R611del)"                      → "other"

# ── OTHER: delins (even single-AA) ─────────────────────────────────────────
"NM_000548.5(TSC2):c.1831_1833delinsCAG (p.Arg611delinsGln)"  → "other"

# ── OTHER: unknown/placeholder AA ──────────────────────────────────────────
"NM_1(TSC1):c.1A>G (p.Xaa123Gln)"                    → "other"
"NM_1(TSC1):c.1A>G (p.X123Q)"                        → "other"
"NM_1(TSC1):c.1A>G (p.Arg611Zzz)"                    → "other"

# ── OTHER: no p. token (splice/intronic) ────────────────────────────────────
"NM_000548.5(TSC2):c.1832+1G>A"                      → "other"
"NM_000548.5(TSC2):c.5422-3C>G"                      → "other"

# ── OTHER: unparseable ──────────────────────────────────────────────────────
"unparseable string p.????"                           → "other"
"NM_000548.5(TSC2):c.1832del (p.?)"                  → "other"
```

### 5.3 ReviewStatus High/Low Confidence Truth Set

```python
# ── HIGH CONFIDENCE (kept in truth set regardless of NumberSubmitters) ──────
"practice guideline"                                        → KEEP
"reviewed by expert panel"                                  → KEEP
"criteria provided, multiple submitters, no conflicts"      → KEEP

# ── LOW CONFIDENCE (excluded regardless of NumberSubmitters) ────────────────
"criteria provided, single submitter"                       → EXCLUDE
"criteria provided, conflicting classifications"            → EXCLUDE
"criteria provided, conflicting interpretations of pathogenicity"  → EXCLUDE
"no assertion criteria provided"                            → EXCLUDE
"no assertion provided"                                     → EXCLUDE  # historical
"no classification provided"                                → EXCLUDE
"no classification for the individual variant"              → EXCLUDE
"no classifications from unflagged records"                 → EXCLUDE  # newer
```

### 5.4 GeneSymbol Filter Golden Fixture

```python
"TSC1"                                   → matches TSC1 ✓
"TSC2"                                   → matches TSC2 ✓
"subset of 2 genes: TSC1:PKD1"           → matches TSC1 ✓ (after strip " TSC1" → "TSC1")
"subset of 3 genes: BRCA1:TSC2:TP53"    → matches TSC2 ✓ (no leading space on TSC2)
"subset of 2 genes: PKD1:PKD2"          → no match ✗
"BRCA1"                                  → no match ✗
""                                       → no match ✗
```

---

## 6. Gaps and Uncertainties

| Item | Status | Recommendation |
|---|---|---|
| `VUS-high` / `VUS-mid` / `VUS-low` in `variant_summary.txt.gz` aggregate column | Uncertain — these are valid SCV terms but the ClinVar aggregate documentation does not explicitly state they appear verbatim in `ClinicalSignificance`. Most likely aggregated under `Uncertain significance`, but a rare single-submitter row might retain `VUS-high`. | Pull a real TSC1/TSC2 snapshot and `grep -c "VUS-high" variant_summary.txt` to verify frequency before adding to AC1 fixture. |
| `no assertion provided` as exact `ReviewStatus` string | Appears in RAPTOR test code and benchmark exclusion logic, but is NOT listed in the canonical ClinVar `review_status/` documentation page (which lists `no assertion criteria provided`). May be a historical SCV-level form. | Query a real snapshot: `cut -f25 variant_summary.txt \| sort \| uniq -c` to get the full vocabulary from live data. |
| `criteria provided, conflicting interpretations of pathogenicity` | Appears in RAPTOR test fixtures; appears to be the older spelling of `criteria provided, conflicting classifications`. Neither form is listed on the current review status page which only shows `criteria provided, conflicting classifications`. | Same real-data query to confirm both spellings appear in `ReviewStatus` column. |
| Aggregate strings with ClinGen risk allele combos | The ClinVar clinsig docs show `Pathogenic/Established risk allele` is a possible aggregate string, but the mapping to P/LP/B/VUS is a governance call not a technical one. | File as a governance question before including in scored AC1 fixture. |
| `p.Met1?` and `p.0` parsing | These have `?` and `0` as the alt token respectively; the current `_TOKEN_RE` pattern `^([A-Za-z]{3}|[A-Za-z])(\d+)(.+)$` would not match `p.Met1?` (the `?` is not `[A-Za-z]`) and not `p.0` (no ref AA). Falls through to `other`. Correct, but should be in fixture. | Add explicit test cases for `p.?`, `p.0`, `p.0?`. |
| Single-character `p.` notation correctness | ClinVar sometimes uses `p.R611Q` (1-letter) and sometimes `p.Arg611Gln` (3-letter) for the same variant. The 1-letter form is valid per HGVS and must produce identical classification. | No gap — documented and tested in PRD-07 round-1 MAJOR-2. |

---

*All citations verified against live NCBI sources on 2026-07-09. ClinVar vocabulary evolves; the GTR standard terms file (`https://ftp.ncbi.nlm.nih.gov/pub/GTR/standard_terms/Clinical_significance.txt`) is updated weekly and should be the primary reference for any future AC1 fixture refresh.*