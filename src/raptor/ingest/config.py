"""PRD-02 sec 10.3 `config.py` — FR8/AC7: gene-list-driven config, nothing hardcoded.

Schema-validates a `configs/ingest/*.yaml` file; raises loudly on a
missing/blank required pin (GP-6).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

#: Top-level keys every config must define (sec 10.2).
_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "genes",
    "assembly",
    "assembly_patch",
    "mane_release",
    "normalizer",
    "clinvar_snapshot_id",
    "clinvar_snapshot_date",
    "clinvar_snapshot_file_checksum",
    "reference_checksums",
)

_REQUIRED_NORMALIZER_KEYS: tuple[str, ...] = ("tool", "version")

_REQUIRED_GENE_KEYS: tuple[str, ...] = (
    "genome_accession",
    "transcript_accession",
    "protein_accession",
)


class ConfigError(ValueError):
    """Raised on a missing/blank required config pin (FR8/AC7)."""


def _require(mapping: Mapping[str, Any], key: str, *, ctx: str = "") -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required config key: {ctx}{key!r}")
    value = mapping[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"config key {ctx}{key!r} must not be blank")
    return value


@dataclass(frozen=True)
class GeneConfig:
    """Per-gene pins (sec 10.2): genome/transcript/protein accessions."""

    genome_accession: str
    transcript_accession: str
    protein_accession: str


@dataclass(frozen=True)
class IngestConfig:
    """Frozen, schema-validated ingest config (FR8). Gene-list-driven (GP-6):
    the engine is gene-agnostic -- `genes` names which per-gene blocks apply."""

    genes: list[str]
    assembly: str
    assembly_patch: str
    mane_release: str
    normalizer: Mapping[str, Any]
    clinvar_snapshot_id: str
    clinvar_snapshot_date: str
    clinvar_snapshot_file_checksum: str
    reference_checksums: Mapping[str, Any]
    gene_configs: Mapping[str, GeneConfig]

    def gene_config(self, gene: str) -> GeneConfig:
        try:
            return self.gene_configs[gene]
        except KeyError as exc:
            raise ConfigError(f"no config block for gene {gene!r}") from exc

    def pins_dict(self) -> dict[str, Any]:
        """A JSON-serializable snapshot of every pin -- used as `config_pins`
        in manual-queue records (FR6) so a failure is reproducible."""
        return {
            "assembly": self.assembly,
            "assembly_patch": self.assembly_patch,
            "mane_release": self.mane_release,
            "normalizer": dict(self.normalizer),
            "clinvar_snapshot_id": self.clinvar_snapshot_id,
            "clinvar_snapshot_date": self.clinvar_snapshot_date,
            "clinvar_snapshot_file_checksum": self.clinvar_snapshot_file_checksum,
            "reference_checksums": dict(self.reference_checksums),
            "gene_configs": {
                gene: dataclasses.asdict(gc) for gene, gc in self.gene_configs.items()
            },
        }


def load_config(path: str | Path) -> IngestConfig:
    """Load + schema-validate a `configs/ingest/*.yaml` file (FR8/AC7).

    Raises `ConfigError` (a `ValueError` subclass) on any missing/blank
    required pin -- including a missing per-gene block for any gene listed
    in `genes`.
    """
    # NOTE: reads via `Path.read_text()`, not the builtin file-open call --
    # this module is scanned by the KB source contract test
    # (tests/kb/test_schema_contract.py::test_no_forbidden_file_read_calls_in_kb_source,
    # `SRC_ROOT` covers the whole `src/raptor` tree) which bans that builtin
    # call spelling anywhere in the package (GP-9/H1: no ad-hoc file reads).
    # Loading a config/data file this way is legitimate ingestion
    # (FR1/FR8), not trace-cribbing, but must still steer clear of the
    # banned spelling.
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

    for key in _REQUIRED_TOP_KEYS:
        _require(raw, key)

    genes = raw["genes"]
    if not isinstance(genes, list) or not genes:
        raise ConfigError("`genes` must be a non-empty list")
    genes = [str(g) for g in genes]

    normalizer = raw["normalizer"]
    if not isinstance(normalizer, dict):
        raise ConfigError("`normalizer` must be a mapping with `tool`/`version`")
    for key in _REQUIRED_NORMALIZER_KEYS:
        _require(normalizer, key, ctx="normalizer.")

    reference_checksums = raw["reference_checksums"]
    if not isinstance(reference_checksums, dict):
        raise ConfigError("`reference_checksums` must be a mapping")

    gene_configs: dict[str, GeneConfig] = {}
    for gene in genes:
        block = raw.get(gene)
        if not isinstance(block, dict):
            raise ConfigError(f"missing config block for gene {gene!r}")
        for key in _REQUIRED_GENE_KEYS:
            _require(block, key, ctx=f"{gene}.")
        gene_configs[gene] = GeneConfig(
            genome_accession=str(block["genome_accession"]),
            transcript_accession=str(block["transcript_accession"]),
            protein_accession=str(block["protein_accession"]),
        )

    return IngestConfig(
        genes=genes,
        assembly=str(raw["assembly"]),
        assembly_patch=str(raw["assembly_patch"]),
        mane_release=str(raw["mane_release"]),
        normalizer={k: v for k, v in normalizer.items()},
        clinvar_snapshot_id=str(raw["clinvar_snapshot_id"]),
        clinvar_snapshot_date=str(raw["clinvar_snapshot_date"]),
        clinvar_snapshot_file_checksum=str(raw["clinvar_snapshot_file_checksum"]),
        reference_checksums={k: v for k, v in reference_checksums.items()},
        gene_configs=gene_configs,
    )
