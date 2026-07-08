"""PRD-02 — Variant ingestion & normalization.

Ingests a pinned ClinVar `variant_summary.txt.gz` snapshot, filtered to a
config-driven gene list, and normalizes each row to a canonical GRCh38
genomic SPDI (`variant_id`, PRD-02 sec 2.1) via an injected `Normalizer`
port (`normalizer.py`). Writes go through the committed PRD-03 `KBStore`
API (`pipeline.run_ingest`).
"""
