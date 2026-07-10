"""PRD-08 sec 3.A/10.3 `export.py` — deterministic label-free GRCh38 SPDI->VCF
4.2 export + bijective identity manifest for the live-eval held-out boundary.

This module is the label-free boundary itself (FR-A1/FR-A4): it accesses
only ``row["variant_id"]`` (a canonical SPDI string, sec 2.1) -- never
``label``/``source``/``review_status``/``variant_class`` -- and every
output (VCF data row + manifest row) carries only per-row identity fields.
File-level provenance (reference checksums, benchmark snapshot id, code
version, counts, content hashes) is legitimate and lives in the
``.provenance.json`` sidecar (FR-A4/FR-A7), never in a per-row field.

Per-shape conversion (FR-A2, sec 10.6): SPDI position is 0-based
(``pos0``); both-non-empty (SNV/MNV/delins) -> ``POS=pos0+1``; a pure
insertion/deletion left-anchors at ``pos0-1`` with ``POS=pos0`` and fails
loud (`ContigStartAnchorError`) at ``pos0==0`` (no anchor exists); a
deleted-vs-reference disagreement fails loud (`ExportReferenceMismatchError`,
R-A10) rather than silently correcting.

`export_holdout` sorts VCF rows (and their 1:1 manifest rows) by the pinned
total sort key ``(contig, POS, REF, ALT)`` using the config's *configured*
contig order (never lexical string order, FR-A5) so output is
permutation-independent -- reordering the input ids never changes the
emitted bytes/hashes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


class ExportConfigError(ValueError):
    """Raised on a malformed/drifted `configs/eval/export.yaml` (FR8-style pin)."""


class ExportReferenceMismatchError(ValueError):
    """Raised when a SPDI `deleted` sequence disagrees with the pinned
    reference (R-A10) -- never silently corrected, no row emitted."""


class ContigStartAnchorError(ValueError):
    """Raised when a pure insertion/deletion sits at `pos0==0` -- no
    left-anchor base exists; never guessed, never right-anchor fallback."""


class ReferencePort(Protocol):
    """FR2-style injected reference port: offline tests use a tiny synthetic
    FASTA; the real CLI wires the checksummed ingest reference discipline."""

    def fetch(self, accession: str, start: int, end: int) -> str: ...


@dataclass(frozen=True)
class ExportConfig:
    """Frozen, schema-validated view of `configs/eval/export.yaml` (sec 10.2).

    `contigs` is an ORDERED list of `{"accession": ..., "vcf_contig": ...}`
    pins -- list order IS the deterministic VCF sort order (FR-A5), never
    accidental lexical string order.
    """

    assembly: str
    contigs: list[dict[str, str]]

    @property
    def accession_to_contig(self) -> dict[str, str]:
        return {c["accession"]: c["vcf_contig"] for c in self.contigs}

    @property
    def contig_order(self) -> dict[str, int]:
        return {c["vcf_contig"]: i for i, c in enumerate(self.contigs)}


def load_export_config(path: str | Path, ingest_config: Any) -> ExportConfig:
    """Load + schema-validate `configs/eval/export.yaml` (sec 10.2/10.3).

    Rejects: an assembly other than `ingest_config.assembly`; a blank/
    duplicate accession or VCF-contig pin; an accession set that does not
    exactly equal the ingest config's configured genomic accessions
    (`ingest_config.gene_configs[*].genome_accession`) -- missing or extra.
    """
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ExportConfigError(f"export config root must be a mapping, got {type(raw).__name__}")

    assembly = raw.get("assembly")
    if not assembly or not str(assembly).strip():
        raise ExportConfigError("export config `assembly` must not be blank")
    assembly = str(assembly)

    ingest_assembly = getattr(ingest_config, "assembly", None)
    if assembly != ingest_assembly:
        raise ExportConfigError(
            f"export config assembly {assembly!r} != ingest config assembly {ingest_assembly!r}"
        )

    contigs_raw = raw.get("contigs")
    if not isinstance(contigs_raw, list) or not contigs_raw:
        raise ExportConfigError("export config `contigs` must be a non-empty list")

    contigs: list[dict[str, str]] = []
    seen_accessions: set[str] = set()
    seen_vcf_contigs: set[str] = set()
    for entry in contigs_raw:
        if not isinstance(entry, dict):
            raise ExportConfigError(f"each `contigs` entry must be a mapping, got {entry!r}")
        accession = entry.get("accession")
        vcf_contig = entry.get("vcf_contig")
        if not accession or not str(accession).strip():
            raise ExportConfigError("`contigs` entry `accession` must not be blank")
        if not vcf_contig or not str(vcf_contig).strip():
            raise ExportConfigError("`contigs` entry `vcf_contig` must not be blank")
        accession = str(accession)
        vcf_contig = str(vcf_contig)
        if accession in seen_accessions:
            raise ExportConfigError(f"duplicate `contigs` accession pin: {accession!r}")
        if vcf_contig in seen_vcf_contigs:
            raise ExportConfigError(f"duplicate `contigs` vcf_contig pin: {vcf_contig!r}")
        seen_accessions.add(accession)
        seen_vcf_contigs.add(vcf_contig)
        contigs.append({"accession": accession, "vcf_contig": vcf_contig})

    gene_configs = getattr(ingest_config, "gene_configs", None) or {}
    expected_accessions = {gc.genome_accession for gc in gene_configs.values()}
    if seen_accessions != expected_accessions:
        missing = expected_accessions - seen_accessions
        extra = seen_accessions - expected_accessions
        raise ExportConfigError(
            f"export config contig accessions {sorted(seen_accessions)} do not match ingest "
            f"config genomic accessions {sorted(expected_accessions)} "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )

    return ExportConfig(assembly=assembly, contigs=contigs)


def spdi_to_vcf(variant_id: str, reference: ReferencePort) -> tuple[str, int, str, str]:
    """Convert one canonical SPDI `variant_id` to VCF 4.2 `(accession, POS,
    REF, ALT)` (FR-A2/sec 10.6). `reference` is an injected FASTA-access
    port; `spdi_to_vcf` returns the SPDI accession itself (not the VCF
    contig name) -- `export_holdout` maps accession -> configured VCF
    contig, keeping this conversion free of a hidden global contig map.
    """
    parts = variant_id.split(":")
    if len(parts) != 4:
        raise ValueError(f"malformed SPDI variant_id (expected accession:pos0:deleted:inserted): {variant_id!r}")
    accession, pos0_str, deleted, inserted = parts
    try:
        pos0 = int(pos0_str)
    except ValueError as exc:
        raise ValueError(f"malformed SPDI position in variant_id {variant_id!r}: {pos0_str!r}") from exc
    if pos0 < 0:
        raise ValueError(f"SPDI position must be >= 0 in variant_id {variant_id!r}: {pos0}")

    if deleted and inserted:
        # Both non-empty: SNV/MNV/delins -- POS=pos0+1, no anchor needed.
        _verify_deleted(reference, accession, pos0, deleted, variant_id)
        return (accession, pos0 + 1, deleted, inserted)

    if not deleted and not inserted:
        raise ValueError(
            f"SPDI variant_id {variant_id!r} has both deleted and inserted empty -- not a valid variant"
        )

    if not deleted:
        # Pure insertion: left-anchor at pos0-1.
        if pos0 == 0:
            raise ContigStartAnchorError(
                f"pure insertion at contig start (pos0==0) has no left anchor: {variant_id!r}"
            )
        anchor = _fetch_anchor(reference, accession, pos0, variant_id)
        return (accession, pos0, anchor, anchor + inserted)

    # Pure deletion: left-anchor at pos0-1, verify deleted vs reference.
    if pos0 == 0:
        raise ContigStartAnchorError(
            f"pure deletion at contig start (pos0==0) has no left anchor: {variant_id!r}"
        )
    _verify_deleted(reference, accession, pos0, deleted, variant_id)
    anchor = _fetch_anchor(reference, accession, pos0, variant_id)
    return (accession, pos0, anchor + deleted, anchor)


_VALID_ANCHOR_BASES = frozenset("ACGT")


def _fetch_anchor(reference: ReferencePort, accession: str, pos0: int, variant_id: str) -> str:
    """Shared insertion/deletion left-anchor fetch (`pos0-1`): reject unless
    the reference returns exactly one uppercase A/C/G/T base (R-A10) --
    empty, multi-base, lowercase, or ambiguous (e.g. `N`) anchors fail loud
    before REF/ALT construction; never normalized, never guessed."""
    anchor = reference.fetch(accession, pos0 - 1, pos0)
    if len(anchor) != 1 or anchor not in _VALID_ANCHOR_BASES:
        raise ExportReferenceMismatchError(
            f"REF_MISMATCH: invalid left-anchor base {anchor!r} at {accession}:{pos0 - 1} "
            f"(variant_id {variant_id!r})"
        )
    return anchor


def _verify_deleted(reference: ReferencePort, accession: str, pos0: int, deleted: str, variant_id: str) -> None:
    """R-A10: fail loud on any deleted-vs-reference disagreement -- never a
    silent correction, no row emitted."""
    observed = reference.fetch(accession, pos0, pos0 + len(deleted))
    if observed != deleted:
        raise ExportReferenceMismatchError(
            f"REF_MISMATCH: deleted sequence {deleted!r} does not match reference "
            f"{observed!r} at {accession}:{pos0} (variant_id {variant_id!r})"
        )


@dataclass
class ExportResult:
    """`{vcf_text, manifest_rows, conservation_count, vcf_hash, manifest_hash,
    provenance}` (sec 10.3). `write(out_dir, prefix)` emits exactly
    `{prefix}.vcf`, `{prefix}.manifest.jsonl`, `{prefix}.provenance.json`."""

    vcf_text: str
    manifest_rows: list[dict[str, str]] = field(default_factory=list)
    conservation_count: int = 0
    vcf_hash: str = ""
    manifest_hash: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def write(self, out_dir: str | Path, prefix: str = "holdout_input") -> None:
        out_dir = Path(out_dir)

        vcf_path = out_dir / f"{prefix}.vcf"
        vcf_path.write_bytes(self.vcf_text.encode("utf-8"))

        manifest_path = out_dir / f"{prefix}.manifest.jsonl"
        manifest_path.write_bytes(_render_manifest(self.manifest_rows).encode("utf-8"))

        sidecar = dict(self.provenance)
        sidecar["conservation_count"] = self.conservation_count
        sidecar["vcf_hash"] = self.vcf_hash
        sidecar["manifest_hash"] = self.manifest_hash
        provenance_path = out_dir / f"{prefix}.provenance.json"
        provenance_path.write_bytes(
            (json.dumps(sidecar, sort_keys=True, indent=2) + "\n").encode("utf-8")
        )


def _render_vcf(rows: list[tuple[str, int, str, str]]) -> str:
    lines = [
        "##fileformat=VCFv4.2",
        "##source=raptor.eval.export",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
    ]
    for contig, pos, ref, alt in rows:
        lines.append(f"{contig}\t{pos}\t.\t{ref}\t{alt}\t.\t.\t.")
    return "\n".join(lines) + "\n"


def _render_manifest(rows: list[dict[str, str]]) -> str:
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    return "\n".join(lines) + ("\n" if lines else "")


def export_holdout(
    variant_ids: Iterable[str],
    reference: ReferencePort,
    config: ExportConfig,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> ExportResult:
    """Deterministic label-free SPDI->VCF 4.2 export + bijective identity
    manifest (FR-A5/A6). Accepts an `Iterable[str]` of canonical SPDI
    `variant_id`s (never a label-bearing row); maps each SPDI accession to
    its configured VCF contig; enforces conservation (every input yields
    exactly one VCF row + one manifest row) and bijection (`variant_id` <->
    `vcf_key`) -- any duplicate input id or `vcf_key` collision is fatal
    (`ValueError`). `provenance`, if given, is deep-copied -- the caller's
    mapping is never mutated and never copied into a per-row field.
    """
    import copy

    accession_to_contig = config.accession_to_contig
    contig_order = config.contig_order

    seen_variant_ids: set[str] = set()
    seen_vcf_keys: set[str] = set()
    entries: list[tuple[int, int, str, str, str, str, str, str]] = []

    for variant_id in variant_ids:
        if variant_id in seen_variant_ids:
            raise ValueError(
                f"duplicate input variant_id {variant_id!r} -- bijection breach (FR-A6)"
            )
        seen_variant_ids.add(variant_id)

        accession, pos, ref, alt = spdi_to_vcf(variant_id, reference)

        contig = accession_to_contig.get(accession)
        if contig is None:
            raise ValueError(
                f"accession {accession!r} (from variant_id {variant_id!r}) is not configured "
                "in the export config's `contigs` pins"
            )

        vcf_key = f"{contig}:{pos}:{ref}:{alt}"
        if vcf_key in seen_vcf_keys:
            raise ValueError(
                f"vcf_key collision: {vcf_key!r} -- distinct SPDI ids map to the same VCF "
                "row, bijection breach (FR-A6)"
            )
        seen_vcf_keys.add(vcf_key)

        order_index = contig_order[contig]
        entries.append((order_index, pos, ref, alt, contig, accession, variant_id, vcf_key))

    # Pinned total sort key (contig, POS, REF, ALT) via the *configured*
    # contig order -- never accidental lexical string order (FR-A5).
    entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    vcf_rows = [(contig, pos, ref, alt) for (_, pos, ref, alt, contig, _accession, _vid, _key) in entries]
    manifest_rows = [
        {"variant_id": variant_id, "vcf_key": vcf_key, "accession": accession, "contig": contig}
        for (_order, _pos, _ref, _alt, contig, accession, variant_id, vcf_key) in entries
    ]

    vcf_text = _render_vcf(vcf_rows)
    manifest_text = _render_manifest(manifest_rows)

    provenance_copy: dict[str, Any] = copy.deepcopy(dict(provenance)) if provenance is not None else {}

    return ExportResult(
        vcf_text=vcf_text,
        manifest_rows=manifest_rows,
        conservation_count=len(entries),
        vcf_hash=hashlib.sha256(vcf_text.encode("utf-8")).hexdigest(),
        manifest_hash=hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
        provenance=provenance_copy,
    )
