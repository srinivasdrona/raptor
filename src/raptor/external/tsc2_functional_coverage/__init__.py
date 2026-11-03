"""RAPTOR v2 TSC2 functional coverage map (``raptor-v2-functional-coverage-map-v1``).

This package builds an immutable, label-blind $TSC2$ functional identity
coverage map: it joins the frozen, verified functional-promotion SPDI
identities to the frozen VUS universe, its internal priority subset, the
protected prospective holdout, the Atlas contrast-candidate identity map
and the $R611Q$ Atlas anchor, and publishes row-level membership only to
an external create-only bundle while committing only aggregate counts,
hashes and leakage markers.

Submodules:

- ``model``: the exact ten-field output row contract
  (``FunctionalCoverageRow``).
- ``ingest``: frozen-input validation, raw-byte pinning and path safety
  for every one of this slice's seven external input roots.
- ``coverage``: the exact-SPDI join, output-row construction and full-
  cohort coverage statistics.
- ``bundle``: output bundle manifest, canonical hashing/JSONL, create-
  only/symlink-safe publication and the aggregate-only committed summary.

This package performs no network I/O and never imports ``raptor.packet``,
``raptor.kb`` or ``raptor.rescuescreen``.
"""
