# R611Q expert-review handoff

> **Status:** prepared, unreviewed, Gate 8 blocked. This handoff contains no
> reviewer identity or signoff and authorizes no accepted Atlas claim.

## Review package

External package root:

`D:\AIProjects\raptor-data\atlas\r611q-expert-review-v1`

| Artifact | SHA-256 |
|---|---|
| `R611Q_EXPERT_REVIEW_PACKET.md` | `ac456eeac4bd6e0c6a41320d3687575e058d1016e92ddd2e8b140dabfdcbe4e2` |
| `R611Q_EXPERT_REVIEW_FORM.yaml` | `0e9d096559f36fcfde2f3340cf9af54a4328ddb74791d9ddef4df1edc54151ba` |

The adjacent `MANIFEST.sha256` binds both artifacts.

## Candidate and source bindings

- Candidate: `NC_000016.10:2070570:G:A`,
  `NM_000548.5:c.1832G>A`, `NP_000539.2:p.Arg611Gln`.
- Candidate canonical-JSON SHA-256:
  `61a431ae5c97a490aa90c8bcb2191352e3c79d812cc9bb2aa1b9a9ca20d2ac45`.
- Disease-pack hash:
  `1294478c6d112f91e5719ee345d2b5be1925567ec4f4abdff50b0e092ff08927`.
- Citation-catalog hash:
  `5d83d8b5e7c3c4923dc6dae038530360db47760abe8c3f86fbc26f3d5821b22e`.
- Claim A: `pmc4843954`, `text-char:20956:21353`, extracted-text hash
  `54a09c6fba81b218210f2051496d4226265eed958f5b6ee2a86f3737a463be77`.
- Claim B: `pmc11593644`, `text-char:31054:31266`, extracted-text hash
  `0a6f1a0410cf1eda7f86dd375dcf4954cfb1cc72950670ef22357eb267873544`.

## Required reviewer outcome

The qualified reviewer assesses each claim independently and records exactly
one of:

- `ACCEPT_AS_WRITTEN`
- `ACCEPT_WITH_NARROWER_WORDING`
- `REJECT`
- `REQUEST_MORE_EVIDENCE`

The packet explicitly tests claim wording, claim kind, directionality,
experimental context, source independence, contradictions, limitations, and
evidence gaps. A signoff applies only to the reviewed claim and exact span; it
is not a variant classification, phenotype determination, treatment
recommendation, or reusable signoff for another claim sharing the same source.

## Current qualifications

- No opposing primary result was found in the permitted corpus, but the search
  is coverage-limited.
- Functional papers share substantial Nellist/Erasmus assay and reagent
  lineage; they are not fully independent replications.
- MaveDB/HAP1 is methodologically independent but lacks per-variant
  calibration in the frozen metadata.
- Transcript `.3`/`.5` and exon 16/17 conventions remain unresolved.
- Foundational paywalled or licence-restricted sources remain unverified.

