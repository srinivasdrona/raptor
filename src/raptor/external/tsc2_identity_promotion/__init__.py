"""RAPTOR v2 TSC2 functional-identity promotion slice.

Consumes the frozen cliPE cDNA->SPDI projector bundle
(``raptor.external.tsc2_cdna_projector``) and VAMP-seq genomic crosswalk
bundle (``raptor.external.tsc2_vamp_crosswalk``) into a new immutable
functional-normalization run (``raptor.external.tsc2_functional``),
upgrading exact bundle-verified mappings to GRCh38 genomic SPDI while
preserving every unresolved row with an explicit state (see the binding
spec, ``docs/project/specs/raptor-v2-functional-identity-promotion-v1.yaml``).

This package performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
