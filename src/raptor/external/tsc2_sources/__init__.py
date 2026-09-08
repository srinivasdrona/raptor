"""RAPTOR v2 TSC2 source-ingestion package (raptor-v2-missense-source-ingestion-v1).

Per `docs/project/specs/raptor-v2-missense-source-ingestion-v1.yaml`, every
module in this package is deterministic parsing, validation, hashing and
manifest construction over *injected* bytes -- no module here performs
network I/O; that is exclusively `scripts/fetch_tsc2_source_bundle.py`'s job
(the `architecture.network_boundary` rule). This package never imports
`raptor.sourceops`, `raptor.scorer`, `raptor.eval`, `raptor.packet`,
`raptor.census`, `raptor.kb` or `raptor.rescuescreen`.

Literature-source modules (this slice):
  endpoint.py -- HTTPS URL builders + host/path allowlist + injected transport.
  pubmed.py   -- NCBI Entrez ESearch/EFetch response parsing.
  litvar2.py  -- NCBI LitVar2 line-delimited mapping-record parsing.
  pmc.py      -- PMC/Europe PMC JATS full-text + licence parsing.

Functional-dataset and bundle/operator modules (`mavedb.py`, `igvf.py`,
`bundle.py`, `ingest.py`) are a separate, later build slice and are not
present yet.
"""
from __future__ import annotations