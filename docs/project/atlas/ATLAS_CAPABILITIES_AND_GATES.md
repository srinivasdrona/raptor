# RAPTOR Mechanism Atlas: capabilities, gates, and boundaries

> **Status:** Consolidated explanatory reference. This guide is not a specification,
> ADR, run record, or scientific evidence source.
>
> **Authority:** Scope and policy are governed by
> [`docs/STRATEGY.md`](../../STRATEGY.md),
> [`docs/DECISIONS.md`](../../DECISIONS.md), and the binding specifications under
> [`docs/project/specs/`](../specs/). Current implementation semantics are governed by
> [`src/raptor/atlas/`](../../../src/raptor/atlas/) and its frozen tests under
> [`tests/atlas/`](../../../tests/atlas/). Frozen run records under
> [`data/atlas/`](../../../data/atlas/) are authoritative for what a particular run
> did. This document explains those sources together; it does not supersede them.

## 1. Purpose and research-only scope

The Mechanism Atlas is a research-evidence system for assembling a traceable
representation of what sources report about a molecular mechanism:

- canonical variant identity;
- exact, source-grounded observations;
- assay and model context;
- supporting, contradicting, missing, and unknown evidence;
- candidate mechanism classes and graph relationships; and
- immutable provenance sufficient to replay deterministic checks.

It is **not** a variant classifier, clinical interpretation system, patient-facing
tool, phenotype predictor, treatment recommender, or RescueScreen execution engine.
Mechanism evidence cannot be imported as ACMG/ClinVar truth, and a mechanism profile
cannot flow back into classification without a separately approved evidence policy.
Reported rescue or perturbation observations remain research evidence in their exact
experimental context, never treatment advice. These boundaries come from
[ADR-0009](../../DECISIONS.md#adr-0009--clinvar-derived-acmg-criteria-direct-copy-banned-pp5bp6ps4-transitive-deferred-to-audit),
[ADR-0010](../../DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy),
[ADR-0015](../../DECISIONS.md#adr-0015--atlas-internal-summaries-are-context-only-and-r611q-is-the-first-phase-2-anchor),
and the binding scope in
[`docs/STRATEGY.md`](../../STRATEGY.md#strategy-scope).

## 2. Architecture and current capabilities

### 2.1 Condition-agnostic core and disease packs

The reusable core is
[`src/raptor/atlas/`](../../../src/raptor/atlas/). It contains frozen value models,
identity admission, ontology validation, source and citation controls, hashing,
profile assembly, promotion gates, panel/generalization machinery, and one-way
export. It must not contain a concrete disease, gene, transcript, pathway, or variant
literal.

Condition-specific policy is injected through versioned disease packs. The only
shipped pack is
[`configs/atlas/packs/tsc2/pack.yaml`](../../../configs/atlas/packs/tsc2/pack.yaml),
which supplies the allowed $\mathrm{TSC2}$ gene, `GRCh38` assembly pin,
`NM_000548.5` transcript pin, namespaced ontology extensions, context vocabularies,
source-register metadata, prohibitions, and pilot metadata. Its `pack_id`,
`pack_version`, and canonical `pack_content_hash` are bound into profiles.

This split is an **internal portability seam**, not evidence that another gene or
disease works. The governing decision is
[ADR-0014](../../DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary).

### 2.2 Untrusted extraction seam

Out-of-process discovery or manual extraction produces an
[`AtlasCandidateImport`](../../../src/raptor/atlas/model.py), not an accepted claim.
The extraction lane can be replaced without changing the core because the candidate
shape is the seam:

1. `candidate_variant`;
2. `proposed_claims`;
3. `proposed_sources`; and
4. `retrieval_provenance`.

The candidate retains raw `dict`/`list` shapes specifically because it is untrusted.
The current discovery template orders identity confirmation, retrieval, claim/span
extraction, contradiction search, context normalization, and gap mapping in
[`configs/atlas/discovery/task_graph.json`](../../../configs/atlas/discovery/task_graph.json).
Discovery cannot write accepted profiles and the core imports no Discovery SDK.

### 2.3 Identity, ontology, contexts, and mechanism graph

- [`identity.py`](../../../src/raptor/atlas/identity.py) admits only a
  chromosome-level, `NC_...` canonical SPDI shape and checks gene, assembly, and
  transcript constraints against the bound pack. HGVS forms remain descriptive
  aliases; they are not the admission key.
- [`ontology.py`](../../../src/raptor/atlas/ontology.py) defines condition-agnostic
  claim kinds, node layers, and mechanism-class seeds. A pack may add only
  namespaced extensions.
- [`ContextRecord`](../../../src/raptor/atlas/model.py) carries assay, model system,
  cell type, tissue, zygosity context, and assay limitations.
- [`MechanismEdge`](../../../src/raptor/atlas/model.py) links mechanism layers and
  records supporting and contradicting claim IDs plus an edge state. If an edge has
  both supporting and contradicting claims, its state must be `conflicting`.
- [`EvidenceAssessment`](../../../src/raptor/atlas/model.py) represents supporting,
  contradicting, missing-evidence, and unknown claim sets. `unknown`, `conflicting`,
  and empty outcomes are legitimate; the system must not manufacture a narrative.

### 2.4 Typed source roles and two source registries

Atlas separates **registration** from **grounding**:

1. A disease pack source register uses
   [`SourceRegisterEntry`](../../../src/raptor/atlas/model.py) to record source type,
   role, identifiers, verification state, licence, and optional hash metadata.
2. A versioned local citation catalog uses
   [`CatalogSource`](../../../src/raptor/atlas/model.py) and
   [`LocalCitationResolver`](../../../src/raptor/atlas/citation.py) to bind canonical
   identifiers to locally staged raw and extracted artifacts.

Allowed source types are `PRIMARY-OFFICIAL`, `PRIMARY-DOC`, `PRIMARY-LIT`,
`SECONDARY-SYNTH`, `DATASET`, `CROSSWALK`, and `UNVERIFIED`. Roles are
`direct_evidence_leaf`, `provenance_only`, `context`, and `crosswalk`.

Only a source that satisfies **all** of the following can ground an accepted claim:

- role `direct_evidence_leaf`;
- source type `PRIMARY-LIT` or `DATASET`;
- `permitted_use: grounding_and_quote`;
- `verification: verified`;
- at least one supported canonical identifier; and
- verified local raw content, plus verified extracted text when a text span is used.

The committed catalog at
[`configs/atlas/catalogs/tsc2/catalog.yaml`](../../../configs/atlas/catalogs/tsc2/catalog.yaml)
is intentionally metadata-only with `sources: []`. Real raw and extracted content
lives under an explicitly supplied external content root. The public, aggregate
source reconstruction record for the first real run is
[`data/atlas/runs/2026-08-03/source_catalog_manifest.yaml`](../../../data/atlas/runs/2026-08-03/source_catalog_manifest.yaml).
The governing resolver decision is
[ADR-0016](../../DECISIONS.md#adr-0016--deterministic-offline-citation-resolver-and-phase-2-promotion-span-verification).

### 2.5 Exact content and span fidelity

The resolver:

- canonicalizes `PMID`, `PMCID`, `DOI`, and `ACCESSION` identifiers;
- requires every alias proposed for one source to resolve to the same full frozen
  `CatalogSource`;
- recomputes raw and extracted artifact SHA-256 digests and byte lengths from disk;
- rejects absolute paths, traversal, and resolved symlink/junction escape from the
  supplied content root;
- normalizes extracted UTF-8 text using `atlas.text_norm.v1` (line endings to LF,
  Unicode NFC, no case-folding or whitespace collapse); and
- verifies `text-char:<start>:<end>` by exact string slicing.

It performs no PDF/HTML/XML parsing, fuzzy matching, source acquisition, or network
retrieval. `page_or_figure` is descriptive metadata and never substitutes for the
exact text slice.

### 2.6 Frozen profiles, immutable hashes, and one-way export

Core admitted values are frozen dataclasses with tuple-based collections. A
[`MechanismProfile`](../../../src/raptor/atlas/model.py) binds identity, claims,
candidate classes, edges, evidence assessment, provenance, and exactly one disease
pack.

[`hashing.py`](../../../src/raptor/atlas/hashing.py) produces:

- `evidence_core_hash`: pack binding, minimal identity, canonically ordered and
  deduplicated claims, candidate classes, edges, and evidence; and
- `profile_envelope_hash`: the evidence content plus full identity and canonicalized
  source/version pins.

Both hashes include the pack binding and exclude run bookkeeping. Exact duplicate
claims and pins are collapsed deterministically; distinct spans from the same source
remain distinct.

[`export_dismech`](../../../src/raptor/atlas/export.py) is a one-way projection.
Atlas has no dependency on an external DisMech schema and accepts no contribution
back through that export.

### 2.7 Firewalls

[`guards.py`](../../../src/raptor/atlas/guards.py) implements independent controls:

- **classification firewall:** recursively rejects known classifier/ClinVar-derived
  keys and ACMG criterion tokens in a candidate;
- **import firewall:** static AST checks prevent Atlas from importing packet,
  scorer, eval, or Discovery code;
- **consumer firewall:** static AST checks prevent the forbidden consumer packages
  from importing Atlas; and
- **network firewall:** static AST checks reject network-capable imports anywhere
  under the Atlas package.

The checks are static source scans, not ambient `sys.modules` observations.

### 2.8 Panel and generalization components

[`identity_map.py`](../../../src/raptor/atlas/identity_map.py) and
[`panel.py`](../../../src/raptor/atlas/panel.py) support offline identity replay,
locked candidate universes, deterministic selection, complete disposition records,
and explicit infeasible/undetermined outcomes. These components test engineering
and panel-selection contracts; they do not themselves establish biological
generalization. See
[`ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md`](ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md)
and the current panel status in
[Section 9](#9-generalization-and-package-readiness-boundary).

## 3. Multi-source use without role laundering

Different source classes answer different questions and must remain in their proper
roles:

| Source class | Appropriate Atlas use | Grounding status |
|---|---|---|
| Primary experimental literature | Direct observation with exact quote, assay/model context, and eligible licence | May ground only as verified `PRIMARY-LIT` + `direct_evidence_leaf` |
| Direct datasets such as MaveDB or IGVF records | Exact experimental row/record or dataset observation, with dataset identity and context | May ground only as verified `DATASET` + `direct_evidence_leaf`; v1 text spans do not define a general dataset-row locator grammar |
| Official identity and crosswalk records | Canonical identity, transcript/protein/accession reconciliation, and provenance | `PRIMARY-OFFICIAL`/`CROSSWALK` with `crosswalk` or `provenance_only`; cannot ground a mechanism claim merely by identifying the allele |
| Experimental structures and structure databases | Structure identity, construct/chain/residue coverage, and structural context | Context/provenance unless an eligible direct leaf and exact supported proposition are separately admitted; residue presence alone is not a mechanism |
| Secondary reviews, internal summaries, and handoffs | Search terms, source leads, historical context, contradiction prompts, and synthesis framing | `SECONDARY-SYNTH`/`context`/`query_seed`; never a direct grounding leaf |

The role rule is invariant across variants. An internal summary can help find a
paper, but repeating the summary does not make it evidence. A primary paper and an
associated dataset also must not be double-counted as independent experiments merely
because they have different identifiers.

## 4. Correctness model: fidelity is not scientific sufficiency

Atlas separates deterministic correctness from scientific judgment:

| Correctness dimension | What Atlas checks | What remains outside that check |
|---|---|---|
| Schema | Required shapes, frozen types, enums, and references | Whether the schema captured every scientifically relevant nuance |
| Identity | SPDI shape, pack binding, allowed gene/assembly/transcript, alias agreement where replayed | Whether the source-reported allele or construct was experimentally correct |
| Source | Typed role/type, identifier resolution, licence/permitted use, verification state | Whether the source design is strong, unbiased, or independent |
| Content | Raw/extracted digest and byte-length recomputation | Whether the source is scientifically persuasive |
| Span | Exact normalized `text-char` slice equals the proposed quote | Whether the quote semantically supports the proposed claim |
| Context | Pack/ontology validator accepts the claim kind and supplied context | Whether the supplied context is complete or accurately interpreted |
| Graph | Claim references exist; support/contradiction state invariants hold | Whether the proposed causal graph is biologically correct or complete |
| Dedup/conflict | Deterministic duplicate handling and supplied unresolved-conflict markers | Whether retrieval found every relevant contradiction or independent replication |
| Leakage | Known classification keys/tokens and forbidden imports are rejected | Whether subtle conceptual bias entered without a forbidden token |
| Reproducibility | Canonical hashes, byte pins, path containment, immutable run records | Whether a reproducible result is biologically true |

**Gates 1–7 establish deterministic fidelity, not biological truth.** Gate 8 adds
a named human judgment that a verified span supports the proposed claim in its stated
context. Even a Gate 8 pass does not prove completeness, independent replication,
causality, generalization, clinical significance, or treatment relevance.

## 5. Exact promotion gates

The implementation source of truth is
[`src/raptor/atlas/promote.py`](../../../src/raptor/atlas/promote.py).
`validate_candidate_import` runs the gates in the exact order below and
short-circuits at the first exception. Gate 3 returns a candidate-local resolution
map that is explicitly passed to Gate 4; there is no module-global cache or
cross-candidate state. `promote_candidate` does not mutate the candidate and returns
a frozen tuple of admitted `ObservedClaim` values only after all eight gates pass.

| Gate | Implementation name | Exact acceptance semantics | A pass proves | A pass does **not** prove |
|---:|---|---|---|---|
| 1 | `_gate1_canonical_spdi_readmission` | Candidate pack binding must exactly equal the injected pack ID/version/hash; `spdi_proposed` must pass the sole canonical genomic-SPDI shape validator; `gene_proposed` must be allowed by the pack | Candidate is bound to the intended pack and presents an admissible SPDI/gene shape | Independent biological identity, transcript consequence, or source correctness |
| 2 | `_gate2_source_type_role_validation` | Source entry IDs are unique; any direct leaf is `PRIMARY-LIT`/`DATASET`; every proposed claim links to such a leaf and that source declares at least one supported bibliographic identifier | Claim-to-source structure and role/type pairing are admissible | Identifier resolution, content integrity, span fidelity, or evidence quality |
| 3 | `_gate3_citation_resolution` | Resolver implements `resolve` + `verify_span`; candidate bib values are raw scheme-less payloads; every direct-leaf alias resolves; all aliases for one source return the same full `CatalogSource`; catalog role/type match the candidate; resolver applies grounding eligibility and raw-content verification | Eligible local source identity, alias consistency, and pinned content resolution | That any quote supports a claim or that the study is sufficient |
| 4 | `_gate4_exact_span_resolution` | Each claim has a typed nonblank locator and quote; its source was resolved by Gate 3; extracted-text pins are complete; resolver returns a matching `VerifiedSpan` for the exact normalized slice | The cited bytes and exact quote/offset match deterministically | Semantic entailment, context adequacy, replication, or biological truth |
| 5 | `_gate5_context_ontology_pack_validation` | The injected `context_validator` accepts each proposed claim kind and context mapping | The supplied validator accepted the claim/context under the bound policy | That the context is complete, correctly extracted, or scientifically appropriate |
| 6 | `_gate6_duplicate_conflict_rules` | The supplied duplicate index contains no value whose string form marks an unresolved `conflict` | No unresolved conflict marker exists in the supplied index | Exhaustive contradiction discovery, source independence, or absence of conflicting science |
| 7 | `_gate7_no_classification_leakage` | Candidate claims, sources, variant, and provenance pass the recursive classification-leakage scanner | Known forbidden classifier/ClinVar/ACMG tokens are absent from the candidate payload | Freedom from every subtle bias, label influence, or scientific overinterpretation |
| 8 | `_gate8_named_human_oracle_span_review` | For every claim, the reviewer callback returns either a nonblank named string or a mapping with nonblank `reviewer_id`/`name` and `accepted: true`; bare booleans and generic truthy values are rejected | A named human accepted the claim/span review unit | Universal truth, complete literature coverage, classification, clinical validity, or treatment actionability |

Because validation short-circuits, a record that reports a Gate 8 block after Gates
1–7 passed has not been promoted. It must retain zero accepted claims unless and
until a separate named-human review succeeds and `promote_candidate` is actually
invoked.

## 6. Data flow and trust boundaries

```text
out-of-process discovery or manual extraction
    -> untrusted AtlasCandidateImport
    -> disease-pack and local-catalog resolution
    -> Gates 1-8, in order
    -> frozen ObservedClaim values
    -> MechanismProfile + mechanism edges + EvidenceAssessment
    -> optional one-way DisMech export
```

The discovery/extraction side may retrieve or prepare appropriately licensed source
material, but Atlas itself performs **no network or source acquisition**. The core
only reads locally staged artifacts through an explicitly supplied content root. A
Discovery outage, rejected candidate, or failed gate cannot mutate an accepted
profile.

## 7. Validation and reproducibility controls

The reproducibility boundary is layered:

1. **Manifest identity:** disease packs and citation catalogs use canonical,
   self-excluding content hashes. Pack identity is included in both profile hashes.
2. **Artifact identity:** raw and extracted file SHA-256 digests and byte lengths are
   recomputed from disk; catalog declarations are never trusted as proof.
3. **Path safety:** catalog manifests and artifacts must remain within their allowed
   roots; absolute paths, traversal, non-regular files, and symlink/junction escapes
   fail closed.
4. **Identifier agreement:** every proposed identifier alias for one source must
   resolve to one identical frozen catalog declaration.
5. **Span replay:** the resolver re-reads the extracted text and verifies the exact
   normalized character slice.
6. **Static isolation:** AST guards enforce import, consumer, network, and
   classification boundaries.
7. **Immutable admitted values:** frozen dataclasses and tuple collections prevent
   in-place mutation of accepted profiles.
8. **Deterministic hashing:** canonical ordering and exact-duplicate collapse make
   semantically identical profiles hash identically while preserving distinct spans.
9. **Executable tests:** [`tests/atlas/`](../../../tests/atlas/) covers identity,
   model invariants, discovery candidate promotion, citation resolution, identity
   replay, and panel selection.
10. **Real manifests:** [`data/atlas/runs/2026-08-03/`](../../../data/atlas/runs/2026-08-03/)
    publishes identifiers, licences, hashes, locators, and gate states without
    redistributing article bodies or unreviewed quote-bearing candidates.

These controls make a run replayable and falsifiable. They do not elevate a
deterministically reproduced statement into a scientifically sufficient conclusion.

<a id="r611q-current"></a>
## 8. Current real example: $\mathrm{TSC2}$ $p.\mathrm{Arg611Gln}$ ($\mathrm{R611Q}$)

The frozen record
[`data/atlas/runs/2026-08-03/r611q_gate_result.json`](../../../data/atlas/runs/2026-08-03/r611q_gate_result.json)
is the authority for the first real anchor run:

- canonical SPDI `NC_000016.10:2070570:G:A`;
- two verified `text-char` spans from two eligible primary-literature sources;
- `scope: deterministic_fidelity_only`;
- Gates 1–7 `passed`;
- Gate 8 `BLOCKED_HUMAN_REVIEW`;
- `accepted_claim_count: 0`;
- `promote_candidate_invoked: false`; and
- `scientific_sufficiency_reviewed: false`.

The accompanying aggregate manifest documentation is
[`data/atlas/runs/2026-08-03/README.md`](../../../data/atlas/runs/2026-08-03/README.md).
It deliberately omits raw article bodies, extracted full text, exact quote-bearing
candidate payloads, and accepted profiles.

The later package-v2 addendum adds the proposed, decision-null
`r611q-claim-2` boundary observation while preserving
`PROPOSED_UNACCEPTED`, zero accepted claims, Gate 8
`BLOCKED_HUMAN_REVIEW`, and `stage_execution_authorized: false`. The binding
package contract is
[`docs/project/specs/r611q-package-v2-addendum-v1.yaml`](../specs/r611q-package-v2-addendum-v1.yaml);
the tracked aggregate-only projections are
[`data/rescuescreen/r611q/package-v2-addendum/README.md`](../../../data/rescuescreen/r611q/package-v2-addendum/README.md)
and
[`package_summary.json`](../../../data/rescuescreen/r611q/package-v2-addendum/package_summary.json).
The detailed expert packet/form are external generated artifacts and are **not in
Git**.

This current state supersedes stale explanatory statements that the resolver is only
planned or that no real spans have been checked. The historical
[`ATLAS_RUNBOOK.md`](ATLAS_RUNBOOK.md) remains useful for boundaries and usage, but
the frozen run records above govern current run status.

## 9. Generalization and package-readiness boundary

### 9.1 What is already reusable

Intake and extraction are already largely implementation-agnostic:

- any producer can emit the `AtlasCandidateImport` shape;
- the core is condition-agnostic;
- disease specifics are pack-injected;
- citation resolution is catalog-injected and offline;
- ontology extensions are namespaced; and
- profile/export APIs do not require Discovery.

That is architectural preparation, not scientific generalization.

### 9.2 What is not yet proven

Multi-gene or second-disease pack reuse is scientifically unproven. The design-only
portability experiment in
[`docs/project/specs/mechanism-atlas-starter.yaml`](../specs/mechanism-atlas-starter.yaml)
expects mostly unchanged core tests, zero Atlas core behavioral change, and bounded
pack-onboarding effort. Failure would mean the machinery is bespoke to
$\mathrm{TSC2}$, not that the thresholds should be weakened.

RAPTOR's strategy reset and binding GP-13 explicitly reject a generic
variant-interpretation platform, generic literature-agent stack, generic NGS
pipeline, or open-ended non-variant knowledge platform. A new condition must name a
specific $\mathrm{TSC}/\mathrm{mTOR}$ user, artifact, expert validator, falsifier,
and reason a generic product is insufficient. See
[`docs/STRATEGY.md`](../../STRATEGY.md#strategy-guiding-policy) and
[ADR-0014](../../DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary).

### 9.3 Panel result and source-diversity block

The frozen selection protocol is
[`ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md`](ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md),
with registration in
[`atlas-phase2-panel-selection-registration-v1.yaml`](atlas-phase2-panel-selection-registration-v1.yaml).
The audited run
[`data/atlas/tsc2_phase2_panel_selection_run_2026-08-06.json`](../../../data/atlas/tsc2_phase2_panel_selection_run_2026-08-06.json)
ended `INFEASIBLE_PANEL`: all 24 attempts completed exhaustively within budget, no
member was selected, 10 of 35 identities were unresolved, and source lineage was
unknown for 32 of 35 records and all 37 attributable observations.

Per
[ADR-0017](../../DECISIONS.md#adr-0017--dual-atlas-panel-products-a-post-result-technical-coverage-panel-separated-from-a-still-blocked-independent-validation-panel)
and
[`atlas-panel-products-v1.yaml`](../specs/atlas-panel-products-v1.yaml):

- the technical coverage panel is design-only, engineering-only, and makes no
  generalization claim; and
- the independent-validation panel remains `BLOCKED_SOURCE_DIVERSITY` until a new
  frozen source registry, verified lineage map, lawfully accessible exact-span
  corpus, new universe/protocol/registration, preregistration, and candidate-free
  feasibility check exist.

A green technical panel would not unblock or provide evidence for the independent
scientific panel.

### 9.4 Triggers before expansion or standalone extraction

Before another disease can be claimed, the portability experiment must pass under
owner approval, a GP-13 gate, and—where real scientific content is involved—a named
oracle. A clean core or second YAML pack alone is insufficient.

Standalone package/repository extraction is also not authorized now. The binding
starter specification requires an explicit extraction decision grounded in evidence
such as a stable ontology across contrasting $\mathrm{TSC2}$ variants, a successful
portability experiment, a concrete second consumer, or independent release/team/
licensing need. The preliminary
[`MECHANISM_ATLAS_HANDOFF.md`](MECHANISM_ATLAS_HANDOFF.md) recommends the stricter
operational posture: wait for a stable, useful $\mathrm{TSC2}$ pilot and another
concrete consumer. API independence is an enabling seam, not by itself a reason to
publish a standalone package.

## 10. Atlas-to-RescueScreen boundary

RescueScreen is a separate, downstream research lane governed by
[ADR-0018](../../DECISIONS.md#adr-0018--raptor-rescuescreen-a-gated-research-only-structural-rescue-track-downstream-of-reviewed-mechanism-evidence)
and
[`docs/project/specs/structural-rescue-screen-v1.yaml`](../specs/structural-rescue-screen-v1.yaml).
It may consume only reviewed/accepted mechanism representations. It may not promote,
corroborate, or feed computational output back into an Atlas claim or classification.

For $\mathrm{R611Q}$, the current authority is
[`data/rescuescreen/r611q/RESCUESCREEN_EVIDENCE_READINESS_SUMMARY.md`](../../../data/rescuescreen/r611q/RESCUESCREEN_EVIDENCE_READINESS_SUMMARY.md):

- `EG-1` through `EG-5` are all `NOT_SATISFIED`;
- the first blocker is `EG-1 / MECHANISM_UNVERIFIED`;
- Atlas Gate 8 is `BLOCKED_HUMAN_REVIEW`;
- accepted Atlas claims remain zero;
- `stage_execution_authorized` is `false`; and
- the current decision is `DO_NOT_START_RESCUESCREEN_STAGE_WORK`.

For assay falsifier `AF-4`,
[`assay_falsifier_matrix.json`](../../../data/rescuescreen/r611q/synthesis-v1/assay_falsifier_matrix.json)
requires a native $\mathrm{TSC1}$–$\mathrm{TSC2}$ complex readout together with
matched $\mathrm{TSC1}$ and $\mathrm{TSC2}$ abundance. The package-v2
$\mathrm{TSC2}$–$\mathrm{TSC2}$ self-association observation is explicitly
non-discriminating for `AF-4`: it does not establish preserved
$\mathrm{TSC1}$ binding and does not change any entry gate or stage state. See the
package-v2 contract and aggregate references in [Section 8](#r611q-current).

## 11. Documentation authority and reference map

| Source | Authority class | Use |
|---|---|---|
| [`docs/STRATEGY.md`](../../STRATEGY.md) | Binding strategy/scope | Product boundary, GP-13, research-only ceiling |
| [`docs/DECISIONS.md`](../../DECISIONS.md) | Accepted decisions | ADR-0014/15/16/17/18 policy and architecture decisions |
| [`mechanism-atlas-starter.yaml`](../specs/mechanism-atlas-starter.yaml) | Binding Atlas contract | Core/pack model, portability and extraction gates |
| [`atlas-citation-resolver-v1.yaml`](../specs/atlas-citation-resolver-v1.yaml) | Binding resolver contract | Catalog, content, path, identifier, and span verification |
| [`atlas-panel-products-v1.yaml`](../specs/atlas-panel-products-v1.yaml) | Binding panel-product contract | Engineering/scientific claim ceilings and source-diversity block |
| [`src/raptor/atlas/`](../../../src/raptor/atlas/) | Current implementation | Exact code behavior, including Gates 1–8 |
| [`tests/atlas/`](../../../tests/atlas/) | Frozen executable contract | Regression and invariant coverage |
| [`data/atlas/`](../../../data/atlas/) | Frozen run authority | What a recorded run passed, blocked, selected, or accepted |
| [`ATLAS_RUNBOOK.md`](ATLAS_RUNBOOK.md) | Explanatory/operational | Historical Phase 1 usage and boundaries; not current run authority |
| [`src/raptor/atlas/README.md`](../../../src/raptor/atlas/README.md) | Explanatory package charter | Concise module boundary; not a spec |
| [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md) | Architecture overview | System-level orientation; dated status text may lag frozen runs |
| [`MECHANISM_ATLAS_HANDOFF.md`](MECHANISM_ATLAS_HANDOFF.md) | Preliminary design input | Questions and extraction criteria; never evidence |
| This guide | Consolidated explanation | Reader orientation across the authorities above |

## 12. Glossary

- **Accepted claim:** an `ObservedClaim` returned only after all eight promotion
  gates pass and promotion is invoked.
- **Candidate:** an untrusted `AtlasCandidateImport` awaiting validation.
- **Catalog:** a hash-bound local identifier-to-artifact manifest used by the
  offline resolver.
- **Canonical SPDI:** the genome-anchored variant identity key used for Atlas
  admission.
- **Context:** assay/model/cell/tissue/zygosity/limitation metadata that constrains
  the meaning of an observation.
- **Direct evidence leaf:** the only source role allowed to ground a claim, and only
  when paired with eligible `PRIMARY-LIT` or `DATASET` type and verification.
- **Disease pack:** versioned condition-specific configuration injected into the
  condition-agnostic core.
- **Deterministic fidelity:** reproducible identity, source, bytes, span, context,
  leakage, and provenance checks; not a synonym for scientific truth.
- **Evidence assessment:** explicit supporting, contradicting, missing, and unknown
  claim sets.
- **Gate 8:** named-human review of a deterministically verified claim/span unit.
- **Mechanism profile:** frozen, pack-bound representation of admitted claims,
  graph edges, evidence state, and provenance for one identity.
- **Scientific sufficiency:** human/domain judgment about whether evidence actually
  supports a claim and is adequate for its intended scope.
- **Source register:** typed bibliographic/dataset metadata used to resolve claim
  references; distinct from the byte-pinned local citation catalog.
