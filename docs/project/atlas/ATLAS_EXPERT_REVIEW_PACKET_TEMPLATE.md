# Atlas expert-review packet template

> **Status:** review-process template. Completing a packet can authorize one
> claim-scoped Atlas evidence statement only. It never authorizes a variant
> classification, phenotype conclusion, treatment recommendation, or broader
> mechanism profile.

## Packet identity

- Packet schema/version:
- Packet ID:
- Claim ID:
- Candidate run ID and canonical JSON SHA-256:
- Disease-pack ID/version/content hash:
- Citation-catalog ID/version/content hash:
- Source ID and normalized identifiers:
- Raw-source SHA-256:
- Extracted-text SHA-256:
- Exact locator:

All hashes must be recomputed from disk when the packet is opened.

## Immutable candidate material

- Canonical variant identity:
- Proposed claim text:
- Proposed claim kind:
- Proposed directionality:
- Exact source quote:
- Proposed assay/model context:
- Existing limitations:
- Related claims sharing a source, locator, assay lineage, or reagent:

Source-authored classification language inside a quote is quoted, not asserted
by RAPTOR.

## Reviewer assessment

Review the claim, source, exact span, wording, claim kind, directionality,
assay context, limitations, source independence, contradictions, and evidence
gaps as one atomic unit.

Choose exactly one:

- [ ] `ACCEPT_AS_WRITTEN`
- [ ] `ACCEPT_WITH_NARROWER_WORDING`
- [ ] `REJECT`
- [ ] `REQUEST_MORE_EVIDENCE`

Required fields:

- Approved wording:
- Approved claim kind:
- Approved directionality:
- Approved context:
- Added limitations:
- Contradiction assessment:
- Rationale:
- If narrowed, narrowing rationale:
- If rejected, rejection basis:
- If more evidence is required, blocking question:

Approved wording must exclude classification, phenotype, and treatment claims.
It may narrow the proposed claim but must never broaden it.

## Reviewer identity and signoff

- Reviewer name:
- Credentials:
- Reviewer role:
- Conflict-of-interest statement:
- Review date:
- Signature or authenticated reviewer ID:

The review date must be on or after packet generation. No reviewer field may be
prefilled by RAPTOR.

> This signoff authorizes only an Atlas evidence statement for this exact
> claim and span. It is not a variant classification, phenotype determination,
> or treatment recommendation.

## Closure rules

A packet closes only when every identity, hash, decision-specific field,
reviewer field, anti-overclaim check, and exact-span check passes. Rejection or
request-more-evidence is a valid terminal outcome. A later review creates a new
version linked with `supersedes_packet_id`; it never mutates the prior record.

