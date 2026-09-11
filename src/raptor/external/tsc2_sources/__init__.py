"""RAPTOR v2 TSC2 source-ingestion package (raptor-v2-missense-source-ingestion-v1).

Per `docs/project/specs/raptor-v2-missense-source-ingestion-v1.yaml`, every
module in this package is deterministic parsing, validation, hashing and
manifest construction over *injected* bytes -- no module here performs
network I/O; that is exclusively `scripts/fetch_tsc2_source_bundle.py`'s job
(the `architecture.network_boundary` rule). This package never imports
`raptor.sourceops`, `raptor.scorer`, `raptor.eval`, `raptor.packet`,
`raptor.census`, `raptor.kb` or `raptor.rescuescreen`.

Implemented modules:
  endpoint.py -- HTTPS URL builders + host/path/query allowlist + injected
                 transport-response validation (`request_with_transport`/
                 `fetch_with_transport`).
  pubmed.py   -- NCBI Entrez ESearch/EFetch response parsing, including
                 partial-date (`YYYY`/`YYYY-MM`) and `MedlineDate` handling.
  litvar2.py  -- NCBI LitVar2 line-delimited mapping-record parsing.
  pmc.py      -- PMC/Europe PMC JATS full-text + licence parsing.
  mavedb.py   -- MaveDB score-set metadata/scores.csv verification and
                 final-URL identity binding.
  igvf.py     -- IGVF analysis-set/tabular-file metadata + downloaded-bytes
                 verification and final-URL/S3-object identity binding.
  bundle.py   -- bundle manifest construction, canonical content hashing,
                 and external/create-only/symlink-safe atomic publication.
  ingest.py   -- plan-driven, source-specific ingestion over an injected
                 transport, wrapping every failure as `SourceIngestionError`.
"""
from __future__ import annotations