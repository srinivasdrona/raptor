# RescueScreen $TSC2$ $p.\mathrm{Arg611Gln}$ search protocol

**Cutoff:** 2026-08-17  
**Purpose:** durable RescueScreen exploratory evidence synthesis. This protocol does not perform Atlas acceptance, ACMG interpretation, clinical interpretation, or treatment recommendation.

## Identity anchor

- SPDI: `NC_000016.10:2070570:G:A`
- Transcript: `NM_000548.5:c.1832G>A`
- Protein: `NP_000539.2:p.Arg611Gln`
- Aliases: `R611Q`, `G1832A`, `rs28934872`
- UniProt: `P49815`, `VAR_005650`

Literature using `NM_000548.3` or exon 16/17 conventions was normalized only when the coding and protein aliases agreed. No residue-offset arithmetic was used for structures.

## Authoritative local inputs

- `C:\Users\sdrona\AppData\Local\Temp\1786947585279-copilot-tool-output-6044ef.txt` — SHA-256 `db68b55cb7671a10eece69173009c46bfec96d8c69aaa33c97b75b2e4b35bbdb`
- `D:\AIProjects\raptor-data\atlas\r611q-expert-review-v1\R611Q_EXPERT_REVIEW_FORM.yaml` — SHA-256 `0e9d096559f36fcfde2f3340cf9af54a4328ddb74791d9ddef4df1edc54151ba`
- `D:\AIProjects\raptor-data\atlas\r611q-expert-review-v1\R611Q_EXPERT_REVIEW_PACKET.md` — SHA-256 `ac456eeac4bd6e0c6a41320d3687575e058d1016e92ddd2e8b140dabfdcbe4e2`
- `D:\AIProjects\raptor-worktrees\panel-products-rescue-screen\docs\project\specs\structural-rescue-screen-v1.yaml` — SHA-256 `c08131bf51ace985613a485cacce22c040ab38f32c9ac1ec56b1228642f337eb`
- `D:\AIProjects\raptor-worktrees\r611q-expert-review\data\atlas\runs\2026-08-03\source_catalog_manifest.yaml` — SHA-256 `38f0f61d971c9b62851b29e404580deca7f2f8feebc5cadc176cd4208decccff`
- `D:\AIProjects\raptor\pre-build\RescueScreen Exploration.md` — SHA-256 `2333287aff5bf1b26c70e166f40626ba33bb44e96ac4299b4c75497a12d65e40`

The frozen Atlas catalog comprises 11 publications plus MaveDB. The expert packet and form remain unreviewed, with Gate 8 `BLOCKED_HUMAN_REVIEW` and `accepted_claim_count=0`.

## Search and verification routes

1. Enumerate the frozen Atlas PMID/PMCID/DOI inventory and the user-named additions.
2. Search exact identity tokens: `R611Q`, `Arg611Gln`, `p.(Arg611Gln)`, `c.1832G>A`, `G1832A`, `rs28934872`.
3. Verify metadata through PubMed EFetch; never classify from title or search snippet alone.
4. Inspect primary text through PMC, Europe PMC full-text XML, publisher pages, lawful author manuscripts, and PubMed abstracts.
5. Extract exact table rows, result sentences, figure legends, dataset rows, assay model, construct, readout, replicate count, access status, and license when exposed.
6. Verify licenses through the NCBI PMC OA API, Crossref license records, MaveDB metadata, UniProt terms, and resource records. “Readable” was not equated with openly licensed.
7. Verify the MaveDB row directly: `urn:mavedb:00001201-a-1#62`, score `0.345544328`.
8. Download and decompress IGVF `IGVFFI9747KART`; verify MD5/SHA-256 and extract line 8168 for `ENSP00000219476.3:p.Arg611Gln`.
9. Verify dbSNP, UniProt, RCSB and PDBe records. Inspect mmCIF atom records and UniProt chain mappings for PDB `7DL2` and `9CE3`.
10. Backward/forward trace only when the resulting primary record or authoritative dataset could be inspected. Search hits without primary evidence remained `UNVERIFIED_LEAD`.

## Classification rules

Every publication receives exactly one category:

- `DIRECT_FUNCTIONAL`
- `DIRECT_BIOCHEMICAL`
- `DIRECT_CLINICAL_OR_TUMOR`
- `DIRECT_DATASET`
- `STRUCTURAL_CONTEXT`
- `INDIRECT_GENERAL_MECHANISM`
- `REVIEW_ONLY`
- `UNVERIFIED_LEAD`

Counts in this bundle:

- `DIRECT_BIOCHEMICAL`: **2**
- `DIRECT_CLINICAL_OR_TUMOR`: **11**
- `DIRECT_DATASET`: **2**
- `DIRECT_FUNCTIONAL`: **11**
- `INDIRECT_GENERAL_MECHANISM`: **2**
- `REVIEW_ONLY`: **0**
- `STRUCTURAL_CONTEXT`: **3**
- `UNVERIFIED_LEAD`: **2**

“Direct” means the allele, an allele-bearing line, or an exact allele dataset row was actually examined. Direct does not mean independent, clinically interpretable, or Atlas-accepted. Grouped attribution, comparator reuse, tumor/LOH context, and derivative cell lines are recorded explicitly.

## Proposition coding

- `SUPPORTS`: direct result favors the proposition in its stated system.
- `CONTRADICTS`: direct result favors the opposite proposition.
- `MEASURED_INDETERMINATE`: endpoint was measured but falls in a declared ambiguous interval.
- `NOT_MEASURED`: verified experimental design omitted the endpoint.
- `INDIRECT_CONTEXT`: relevant general, grouped, structural, clinical, or computational context.
- `CONTROL_REUSE`: $R611Q$ was a known comparator rather than a new allele-generation experiment.

No null result was inferred from silence.

## Deduplication rules

- PMID, PMCID and DOI aliases form one publication.
- PMID `38895336` and MaveDB are one cliPE experimental program.
- The 2026 integrated MAVE paper reuses the cliPE score but adds VAMP-seq; recalibration is not replication.
- PMIDs `31799751`, `32555378`, and `39596632` share the 3H9-1B1 line and assay lineage.
- The Nellist/Erasmus parental-cell papers share construct and laboratory ancestry.
- `621-101` and `621-327` descend from the patient-621 $R611Q$-plus-LOH tumor lineage.

## Access and search limits

Publisher access failed or exact original spans remained unavailable for PMIDs `11741832`, `15483652`, and `22903760`. Several PMC-readable articles have no confirmed open-content license. The IGVF file is public and uncontrolled, but its file record does not expose an explicit reuse license. The search is bounded to sources verified through 2026-08-17; absence of a contradiction is not proof that none exists.
