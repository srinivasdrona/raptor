# Mechanism Atlas -- Core Module Charter

This package (`src/raptor/atlas/`) implements the **generic, condition-agnostic
core** of the RAPTOR Mechanism Atlas. It is the frozen data model, hashing
algorithm, identity admission, ontology, source-grounding, profile assembly,
candidate-promotion, and one-way export layer shared by every disease pack.

This document is **non-authoritative**. The authoritative contract is
`docs/project/specs/mechanism-atlas-starter.yaml` plus the associated
ADR/Architecture/Strategy documents and the frozen tests under
`tests/atlas/`. Where this README and the spec disagree, the spec and the
frozen tests govern.

## Boundaries

* **No disease specifics in code.** Nothing in this package -- no module,
  docstring, comment, string constant, or identifier -- may name a real
  gene, transcript accession, variant, pathway, or disease. All such
  specifics live exclusively in versioned disease packs under
  `configs/atlas/packs/<pack_id>/pack.yaml`.
* **One-directional module boundary.** This package never imports from
  `raptor.packet`, `raptor.scorer`, `raptor.eval`, or any Discovery SDK.
  Conversely, none of those packages may import from this package. Both
  directions are enforced by static AST scans
  (`raptor.atlas.guards.assert_atlas_import_boundary` /
  `assert_no_consumer_import`), run as part of `tests/atlas`.
* **Pack-driven, not hardcoded.** Every gene/transcript/assembly admission
  rule, ontology extension, and source-register pin is supplied by an
  injected `DiseasePack` object (built by `raptor.atlas.pack`). The core
  never hardcodes a pathway or classification branch for any condition.
* **Grounding vs. registration are separate concerns.** Building a profile
  (`build_mechanism_profile`) only resolves that a claim's source
  reference exists in the supplied source register; it does not assert
  leaf-grounding quality. Verified, direct-evidence-leaf grounding is a
  separate, explicitly-invoked check
  (`raptor.atlas.registry.validate_claim_grounding`).
* **No network access.** Nothing in this package performs external
  fetches. Candidate promotion (`raptor.atlas.promote`) validates
  out-of-process discovery output that has already been staged locally;
  it never calls out to retrieve anything itself.
* **One-way export.** `raptor.atlas.export.export_dismech` produces an
  external-facing record with no dependency on, or contribution back
  from, any external schema.

## Phase 1 scope

Phase 1 ships exactly one versioned disease pack (a pilot pack under
`configs/atlas/packs/`) wired end-to-end through this core, plus a set of
out-of-process Discovery configuration templates
(`configs/atlas/discovery/`) that describe -- but do not execute -- a
six-task retrieval/extraction pipeline. All promotion flows exercised in
Phase 1 are synthetic; no real literature claims or spans are admitted by
this repository's tests or fixtures. See
`docs/project/atlas/ATLAS_RUNBOOK.md` for operational detail and the exact
Phase 2 gating criteria required before any real-world claim may be
promoted.
