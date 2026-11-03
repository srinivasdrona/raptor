"""RAPTOR v2 -- VAMP-seq protein -> genomic SPDI crosswalk acquisition.

See ``docs/project/specs/raptor-v2-vamp-genomic-crosswalk-acquisition-v1.yaml``
for the binding contract. This package is pure, offline, deterministic
parsing/validation/hashing/manifest construction over injected archive/
score bytes, an injected reference-FASTA seam, and an injected genomic
normalizer; it performs no network I/O of its own
(``scripts/fetch_tsc2_vamp_genomic_crosswalk.py`` is the only real
network entry point for this slice).
"""
from __future__ import annotations

__all__: list[str] = []
