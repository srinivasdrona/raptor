"""RAPTOR external-evidence ports.

Everything under `raptor.external` talks to a third-party data source across
an arm's-length boundary (ADR-0007 style): RAPTOR parses/validates what an
external source publishes, never imports the external source's own code, and
never lets external evidence reach `raptor.scorer` or the ACMG/ClinVar gate
(see `raptor.external.mave` for the concrete TSC2 MAVE example).
"""
