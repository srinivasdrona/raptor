"""RAPTOR v2 R611Q literature-expansion package
(``raptor-v2-r611q-literature-expansion-v1``).

Per ``docs/project/specs/raptor-v2-r611q-literature-expansion-v1.yaml``,
every module in this package is deterministic parsing, validation, hashing
and manifest construction over *injected* bytes -- no module here performs
network I/O; that is exclusively ``scripts/fetch_r611q_literature_expansion.py``'s
job. This package never imports ``raptor.scorer``, ``raptor.eval``,
``raptor.packet``, ``raptor.census``, ``raptor.kb``, ``raptor.atlas`` or
``raptor.rescuescreen``, and never imports a network-capable module
(``socket``, ``requests``, ``httpx``, ``aiohttp``, ``urllib.request``,
``urllib3``).

This is an acquisition slice, not policy: it unions LitVar2/ClinVar
citation leads for the TSC2 R611Q anchor, subtracts an already-known
discovery-shelf baseline, acquires the new PubMed records/abstracts,
enriches article identity/licence via Europe PMC, and downloads JATS full
text only for articles explicitly reported as CC BY. It never assigns
ACMG evidence, extracts claims, or performs clinical classification.

Implemented modules:
  endpoint.py -- HTTPS URL builders + host/path/query allowlist + injected
                 transport-response validation (``request_with_transport``).
  parse.py    -- baseline/LitVar2/ClinVar/PubMed/Europe PMC/JATS response
                 parsing and article-index construction.
  bundle.py   -- bundle manifest construction, canonical content hashing,
                 external/create-only/symlink-safe atomic publication and
                 the aggregate-only committed summary.
"""
from __future__ import annotations
