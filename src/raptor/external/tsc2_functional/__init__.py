"""RAPTOR v2 TSC2 functional-row identity normalization slice.

Offline, deterministic normalization of the frozen MaveDB cliPE and IGVF
VAMP-seq/SGE functional-assay artifacts (already published by
``raptor.external.tsc2_sources``) into a single, exact
``raptor.external.normalized_functional_row.v1`` row shape per source row --
resolving genomic SPDI only where an SGE row's GRCh38 SNV reference allele
is independently verified against the pinned ``NC_000016.10`` FASTA via
``raptor.ingest.normalizer.SeqRepoGenomicNormalizer``. See
``docs/project/specs/raptor-v2-functional-identity-normalization-v1.yaml``
for the binding spec.

This package performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations
