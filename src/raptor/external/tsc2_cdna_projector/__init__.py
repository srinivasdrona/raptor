"""RAPTOR v2 -- bounded cliPE cDNA -> GRCh38 SPDI projector acquisition.

See ``docs/project/specs/raptor-v2-clipe-cdna-spdi-projector-acquisition-v1.yaml``
for the binding contract. This package is pure, offline, deterministic
parsing/validation/hashing/manifest construction over injected transport
results and an injected reference-FASTA seam; it performs no network I/O of
its own (``scripts/fetch_tsc2_clipe_cdna_spdi_projector.py`` is the only
real network entry point for this slice).
"""
from __future__ import annotations

__all__: list[str] = []
