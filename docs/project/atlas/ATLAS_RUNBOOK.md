# RAPTOR Mechanism Atlas -- Phase 1 Runbook

> **Status:** Non-authoritative operational guide. The authoritative contract
> is `docs/project/specs/mechanism-atlas-starter.yaml`, the associated
> ADR/Architecture/Strategy documents, and the frozen tests under
> `tests/atlas/`. This runbook explains boundaries and usage; it asserts no
> real mechanistic claim, span, or classification of its own.

## What Phase 1 delivers

* A condition-agnostic generic core (`src/raptor/atlas/`): frozen data
  model, pack loader/hasher, identity admission, ontology, source
  registry/grounding, profile builder, an eight-gate candidate-promotion
  pipeline, static import/leakage guards, and a one-way DisMech export.
* Exactly one versioned pilot disease pack:
  `configs/atlas/packs/tsc2/pack.yaml`. It declares `TSC2` as its sole
  allowed gene, a pinned `GRCh38` assembly and MANE-Select transcript, a
  namespaced ontology extension, and three `provenance_only` bibliographic
  source pins (a public preprint, a public ClinVar dataset record, and a
  public MaveDB dataset listing).
* A set of out-of-process Discovery configuration templates
  (`configs/atlas/discovery/`) describing a six-task retrieval/extraction
  pipeline (`identity_confirmation -> literature_retrieval ->
  claim_span_extraction -> contradiction_search ->
  assay_context_normalization -> evidence_gap_mapping`). These templates
  are private, out-of-process, and contribute nothing to any shared
  Bookshelf catalog.

## What Phase 1 does NOT deliver

* **No real mechanistic claims or spans.** Every `ObservedClaim`,
  `EntryRef`/`Span`, and `MechanismEdge` exercised by `tests/atlas/` is
  synthetic. The tsc2 pack's three source register pins are real
  bibliographic *metadata* (citation identifiers, license family) with
  `verification: confirm_pending` -- none is asserted as a `verified`,
  span-grounded, direct-evidence-leaf claim.
* **No real anchor content yet.** Phase 1 admits no real `TSC2
  p.Arg611Gln (R611Q)` claims or spans. Phase 2 uses R611Q as its first
  anchor under the same general rule as every other variant: internal
  summaries may seed questions, but only primary publications or direct
  datasets with exact supporting spans can ground accepted claims.
* **No network access.** Nothing under `src/raptor/atlas/` or
  `configs/atlas/discovery/` performs an external fetch. Discovery output
  is assumed to already be staged locally as an `AtlasCandidateImport`
  before it ever reaches `raptor.atlas.promote`.
* **No classification leakage.** Classifier scores and ClinVar-derived
  classification criteria (e.g. `PP3`/`BP4`/`PS3`/`BS3`) are rejected as
  mechanism truth by both the promotion pipeline (Gate 7) and the static
  leakage scanner.

## Operating the core (synthetic usage)

1. Load a disease pack: `raptor.atlas.pack.load_disease_pack(path_or_pack_id)`.
   This validates structure and recomputes/verifies
   `atlas.pack_content_hash.v1` fail-closed.
2. Admit an identity: `raptor.atlas.identity.admit_identity(record, pack=pack)`.
3. Build a profile: `raptor.atlas.profile.build_mechanism_profile(identity,
   claims, contexts, edges, sources, pack=pack)`. This produces both
   `evidence_core_hash` and `profile_envelope_hash` in
   `profile.provenance.content_hashes`.
4. Stronger, explicit leaf-grounding verification (role/type/verification/
   span, beyond mere source-existence resolution) is a separate step:
   `raptor.atlas.registry.validate_claim_grounding(claim, registry, pack=pack)`
   and `raptor.atlas.registry.verify_source(entry)`.
5. Stage and promote a Discovery candidate:
   `raptor.atlas.promote.validate_candidate_import(candidate, context)` runs
   all eight gates in order; `raptor.atlas.promote.promote_candidate(...)`
   returns a frozen tuple of newly-admitted claims only if every gate
   passes, and never mutates the input candidate.
6. Export (one-way, no external dependency):
   `raptor.atlas.export.export_dismech(profile)`.

## Phase 2 gate (stop/go)

Before any real-world claim or span may be admitted:

1. Independent grounding of the pinned variant identity and each proposed
   claim's exact span against a primary publication or direct dataset.
   Internal handoffs and derived summaries may seed queries but cannot be
   proposed sources or claim-grounding evidence.
2. A completed, reviewed contrast panel (pathogenic/benign/conflicting/VUS)
   demonstrating the ontology is not overfit to a single case.
3. All eight promotion gates exercised against real (not synthetic)
   `AtlasCandidateImport` payloads, with a named human-oracle reviewer
   signing off on every claim's span.
4. Replacement of both Discovery `context_manifest.json` placeholder
   fields (`prompt_hash`, `packet_manifest_hash`) with real, hash-verified
   values once a real Discovery run has produced them.
5. A documented decision on whether to extract the module, expand beyond
   `TSC2`, or admit another gene -- only after the pilot demonstrates a
   stable, reusable ontology and a concrete second consumer, per the
   module's stop/go criteria.

Until all of the above are satisfied, this repository's Mechanism Atlas
remains Phase 1: synthetic-only, disease-pack-scoped, and non-authoritative
for any clinical, classification, or treatment purpose.
