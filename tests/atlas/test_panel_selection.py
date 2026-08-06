"""Executable contract/property suite for the Atlas Phase-2 contrast-panel selector.

Authority
---------
* ``docs/project/specs/atlas-panel-selector-v1.yaml`` (test_contract, module_api)
* ``docs/project/atlas/ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md`` v1.0.4
* ``docs/project/atlas/atlas-phase2-panel-selection-registration-v1.yaml`` (SHAPE only)

RED boundary
------------
Exactly ONE test asserts the implementation exists
(:func:`test_red_panel_selector_implementation_exists`). Every traceability
target is gated behind ``requires_impl`` and therefore SKIPS until
``raptor.atlas.panel`` lands. The ``test_meta_*`` tests are deliberately
UNGATED: they are what stops this file from silently rotting back into a
pass-only shell, so they must run in the RED state too.

Fixture rules honoured here
---------------------------
* Every artifact is synthesized under ``tmp_path`` by a helper that computes
  every self-hash from the bytes it just wrote. No digest literal is pasted.
* No real gene symbol, transcript/protein accession, HGVS string, PMID or DOI
  appears anywhere. ``_SYN_SEQ_ACC`` is a deliberately reserved, non-existent
  ``NC_`` accession used ONLY because ``raptor.atlas.identity.admit_identity``
  requires a genome-anchored accession shape; :func:`test_ps_x_006_...`
  enforces that it is the only SPDI-shaped literal in this module.
* No expected panel is cribbed from real data. Expected panels are derived by
  hand from the synthetic constraint set, and the adversarial search tests
  additionally SELF-VALIDATE their fixture against an independent brute-force
  oracle before asserting anything about the implementation.

Known spec gaps (reported, not invented)
----------------------------------------
G1 ``complete_search(n, *, pool, constraints, node_budget)`` and
   ``run_attempt_schedule(*, pool, registration, node_budget)`` are declared
   without a ``pool``/``constraints`` shape. Their behaviour is therefore
   driven END-TO-END through ``select_panel`` plus the directly callable
   ``enumerate_allocations``; the tests never guess the missing shapes.
G2–G4 were resolved before implementation: ``raw_inventory_hash`` consumes the
   normalized file text through an explicit path; ``SelectionInputs.repo_root``
   is mandatory and contains every tracked artifact; the CLI is exactly
   ``scripts/run_panel_selection.py``.
G5 PS-I-001..005 are specified for the SEPARATE file
   ``tests/atlas/test_panel_selection_external.py``. This remediation is
   restricted to ONE file, so they are realised here against TRACKED
   artifacts only (registration + lock records), asserting no panel, no
   candidate identity and no universe count -- exactly the prohibition the
   external suite carries. PS-I-003/PS-I-004 additionally assert the
   real-mapper guard structurally, because the external content root is not
   available to this file.
G6 Protocol 8.1 rule E5 ("all supporting material is public and lawfully
   usable") has no dedicated 4.3 primitive. It is driven from the disease
   pack's ``prohibitions.non_public_license_families`` instead of inventing a
   helper; see the GAP NOTE above :func:`_eligibility_case`.
"""

from __future__ import annotations

import ast
import collections
import hashlib
import inspect
import itertools
import json
import random
import re
import unicodedata
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pytest
import yaml

import raptor.atlas as _atlas_pkg
from raptor.atlas import guards as _atlas_guards
from raptor.atlas import identity as _atlas_identity
from raptor.atlas import identity_map as _atlas_identity_map
from raptor.atlas import model as _atlas_model
from raptor.atlas import pack as _atlas_pack

RED_SENTINEL = "RED: raptor.atlas panel selector not implemented"

try:  # pragma: no cover - exercised by the RED boundary test itself
    from raptor.atlas import panel as _panel

    IMPORT_ERROR = ""
except Exception as _exc:  # pragma: no cover - the pre-implementation path
    _panel = None
    IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

IMPLEMENTATION_MISSING = _panel is None


def test_red_panel_selector_implementation_exists() -> None:
    """The single implementation-absent RED boundary for this suite."""

    assert not IMPLEMENTATION_MISSING, f"{RED_SENTINEL} ({IMPORT_ERROR})"


requires_impl = pytest.mark.skipif(IMPLEMENTATION_MISSING, reason=RED_SENTINEL)


# ---------------------------------------------------------------------------
# Repository anchors
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "atlas-panel-selector-v1.yaml"
PROTOCOL_PATH = (
    REPO_ROOT / "docs" / "project" / "atlas" / "ATLAS_PHASE2_PANEL_SELECTION_PROTOCOL.md"
)
REGISTRATION_PATH = (
    REPO_ROOT
    / "docs"
    / "project"
    / "atlas"
    / "atlas-phase2-panel-selection-registration-v1.yaml"
)
PANEL_MODULE_PATH = REPO_ROOT / "src" / "raptor" / "atlas" / "panel.py"
CLI_PATH = REPO_ROOT / "scripts" / "run_panel_selection.py"
THIS_FILE = Path(__file__).resolve()

OMEGA = ("S6", "S4", "S5", "S2", "S3", "S1")
SPEC_STRATA = (
    "known_pathogenic",
    "known_benign",
    "conflicting",
    "vus_with_functional_evidence",
    "vus_without_functional_evidence",
)
LADDER_STEPS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
EXECUTION_ORDER = ("V1", "V2", "V3", "V4", "V5", "V7", "V6")


def _sut(name: str) -> Any:
    """Resolve a name from the system under test.

    The spec pins ``panel.py`` for logic and ``model.py`` for value types, so
    both are searched (plus the package re-exports). A missing name is a hard
    failure -- this suite never invents an API to keep itself green.
    """

    for holder in (_panel, _atlas_model, _atlas_pkg):
        if holder is None:
            continue
        obj = getattr(holder, name, None)
        if obj is not None:
            return obj
    raise AssertionError(
        f"SPEC GAP or missing surface: {name!r} is not exported by raptor.atlas.panel, "
        "raptor.atlas.model or the raptor.atlas package"
    )


# ---------------------------------------------------------------------------
# Synthetic vocabulary -- nothing below denotes a real biological entity
# ---------------------------------------------------------------------------

SYN_GENE = "SYNGENE7"
SYN_ASSEMBLY = "SYNASM1"
SYN_TRANSCRIPT = "SYN_TX0007.1"
SYN_PROTEIN = "SYN_PR0007.1"
SYN_ASM_ACC = "SYN_ASM_ACC.1"
#: Reserved, deliberately non-existent genomic accession. It exists solely to
#: satisfy the ``NC_<digits>.<digits>`` shape that admit_identity enforces.
_SYN_SEQ_ACC = "NC_" + "999999.9"
SYN_PACK_ID = "synthpanelpack"
SYN_PACK_VERSION = "0.0.1"
SYN_SEED = "synthetic-panel-seed-v0"
SYN_PROTOCOL_VERSION = "0.1.1"
SYN_PRIOR_PROTOCOL_VERSION = "0.1.0"
SYN_ASSAYS = ("synassay_alpha", "synassay_beta", "synassay_gamma", "synassay_delta")
SYN_MODELS = ("synmodel_one", "synmodel_two", "synmodel_three")
RUN_STARTED_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
LOCK_CREATED_AT = "2026-05-01T00:00:00Z"
EXECUTOR_IDENTITY = "synthetic-executor"


def _syn_spdi(position: int, alt: str = "G") -> str:
    return f"{_SYN_SEQ_ACC}:{position}:A:{alt}"


# ---------------------------------------------------------------------------
# Independent digest helpers (protocol 20.2/20.3, recomputed from hashlib)
# ---------------------------------------------------------------------------


def _text_norm(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(manifest: Mapping[str, Any], self_key: str) -> str:
    payload = {key: value for key, value in manifest.items() if key != self_key}
    return _sha256_text(_canonical_json(payload))


def _doc_hash(path: Path) -> str:
    return _sha256_text(_text_norm(path.read_text(encoding="utf-8")))


def _raw_inventory_file_digest(path: Path) -> tuple[str, int]:
    encoded = _text_norm(path.read_text(encoding="utf-8")).encode("utf-8")
    return _sha256_bytes(encoded), len(encoded)


def _ledger_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_text(_canonical_json([dict(row) for row in rows]))


def _discovery_commitment(keys: Iterable[str]) -> tuple[int, str]:
    distinct = sorted(set(keys))
    return len(distinct), _sha256_text("\n".join(distinct))


def _raw_identity_normalized(raw: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw).strip())


def _universe_key(*, identity_state: str, spdi_canonical: str | None, raw_identity_string: str) -> str:
    if identity_state == "resolved" and spdi_canonical:
        return spdi_canonical
    return "UNRESOLVED:" + _sha256_text(_raw_identity_normalized(raw_identity_string))


def _draw_key(spdi_canonical: str, *, selection_seed: str = SYN_SEED) -> str:
    return _sha256_text(f"{selection_seed}|{spdi_canonical}")


def _lineage_group_key(identifiers: Iterable[str]) -> str:
    joined = "|".join(sorted({_raw_identity_normalized(i) for i in identifiers}))
    return "LG:" + _sha256_text(joined)[:16]


def _bundle_digest(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    total = 0
    for path in files:
        raw = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
        total += len(raw)
    return digest.hexdigest(), len(files), total


def _dump_yaml(payload: Mapping[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Protocol recomputation reference (independent of the implementation)
# ---------------------------------------------------------------------------


def _context_key(observation: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        observation["assay_kind"],
        observation["model_system"],
        observation["cell_or_tissue"],
        observation["zygosity_context"],
    )


def _matched_strata(functional_evidence_present: bool, observations: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Protocol 6.2 predicates over primitives ONLY (firewall-respecting)."""

    matched: set[str] = set()
    m = len(observations)
    if not functional_evidence_present:
        matched.add("S6")
    buckets = {o["reported_outcome_bucket"] for o in observations}
    if m >= 2:
        for left, right in itertools.combinations(observations, 2):
            if left["reported_outcome_bucket"] == right["reported_outcome_bucket"]:
                continue
            if _context_key(left) == _context_key(right):
                matched.add("S4")
            else:
                matched.add("S5")
    if m >= 1:
        if "intermediate_deviation" in buckets:
            matched.add("S2")
        if "near_reference" in buckets:
            matched.add("S3")
        if "substantial_deviation" in buckets:
            matched.add("S1")
    return tuple(s for s in OMEGA if s in matched)


def _primary_stratum(matched: Sequence[str]) -> str:
    for stratum in OMEGA:
        if stratum in matched:
            return stratum
    raise AssertionError("no stratum matched; the synthetic fixture is malformed")


def _lineage_edges(observations: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    for i, j in itertools.combinations(range(len(observations)), 2):
        left, right = observations[i], observations[j]
        linked = False
        if left.get("dataset_accession") and left.get("dataset_accession") == right.get("dataset_accession"):
            linked = True
        left_sources = set(left.get("source_identifiers") or ())
        right_sources = set(right.get("source_identifiers") or ())
        if left.get("version_of") in right_sources or right.get("version_of") in left_sources:
            linked = True
        if left.get("experimental_program_id") not in (None, "unknown") and left.get(
            "experimental_program_id"
        ) == right.get("experimental_program_id"):
            linked = True
        if (
            left.get("lab_lineage_key") not in (None, "unknown")
            and left.get("lab_lineage_key") == right.get("lab_lineage_key")
            and left.get("assay_protocol_lineage_key") not in (None, "unknown")
            and left.get("assay_protocol_lineage_key") == right.get("assay_protocol_lineage_key")
        ):
            linked = True
        if right["observation_id"] in (left.get("derived_from_observation_ids") or ()) or left[
            "observation_id"
        ] in (right.get("derived_from_observation_ids") or ()):
            linked = True
        if left_sources & right_sources:
            linked = True
        if linked:
            edges.append((i, j))
    return edges


def _lineage_components(observations: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    parent = list(range(len(observations)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in _lineage_edges(observations):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[int]] = {}
    for index in range(len(observations)):
        groups.setdefault(find(index), []).append(index)
    return [sorted(members) for _, members in sorted(groups.items())]


def _observation_unknown(observation: Mapping[str, Any]) -> bool:
    return "unknown" in (
        observation.get("lab_lineage_key"),
        observation.get("assay_protocol_lineage_key"),
    )


def _lineage_index(all_observations: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """observation_id -> lineage_group_key, with protocol 7.2 unknown pooling."""

    mapping: dict[str, str] = {}
    for component in _lineage_components(all_observations):
        members = [all_observations[i] for i in component]
        established = not any(_observation_unknown(o) for o in members)
        if established:
            identifiers: set[str] = set()
            for member in members:
                identifiers.update(member.get("source_identifiers") or ())
            key = _lineage_group_key(identifiers)
        else:
            key = "LG:UNKNOWN-POOL"
        for member in members:
            mapping[member["observation_id"]] = key
    return mapping


def _record_groups(record: Mapping[str, Any], index: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(sorted({index[o["observation_id"]] for o in record["observations"]}))


def _support_class(record: Mapping[str, Any], index: Mapping[str, str]) -> str:
    observations = record["observations"]
    if not record["functional_evidence_present"]:
        return "evidence_absent"
    if not any(o["access_status"] == "open_lawful" and o["span_verifiable"] for o in observations):
        return "access_blocked"
    groups = _record_groups(record, index)
    established = tuple(g for g in groups if g != "LG:UNKNOWN-POOL")
    if len(established) >= 2:
        return "multi_independent"
    if all(o["throughput_class"] == "high_throughput" for o in observations):
        return "single_high_throughput_only"
    return "single_low_throughput"


_CROSSWALK_CONTRADICTORY = {
    ("vus_with_functional_evidence", "S6"),
    ("vus_without_functional_evidence", "S1"),
    ("vus_without_functional_evidence", "S2"),
    ("vus_without_functional_evidence", "S3"),
    ("vus_without_functional_evidence", "S4"),
    ("vus_without_functional_evidence", "S5"),
}
_CROSSWALK_DISCORDANT = {
    ("known_pathogenic", "S3"),
    ("known_benign", "S1"),
}


def _crosswalk_cell(spec_stratum: str, primary: str) -> str:
    if (spec_stratum, primary) in _CROSSWALK_CONTRADICTORY:
        return "contradictory"
    if (spec_stratum, primary) in _CROSSWALK_DISCORDANT:
        return "discordant"
    return "permitted"


# ---------------------------------------------------------------------------
# Synthetic universe record / observation builders
# ---------------------------------------------------------------------------


def _obs(
    observation_id: str,
    *,
    bucket: str = "substantial_deviation",
    assay: str = SYN_ASSAYS[0],
    model: str = SYN_MODELS[0],
    tissue: str = "syntissue_x",
    zygosity: str = "synzyg_het",
    throughput: str = "low_throughput",
    sources: Sequence[str] = ("ACCESSION:SYNSRC-1",),
    dataset_accession: str | None = None,
    version_of: str | None = None,
    program: str = "unknown",
    lab: str = "synlab-1",
    protocol_lineage: str = "synproto-1",
    derived_from: Sequence[str] = (),
    access: str = "open_lawful",
    license_family: str = "synlicense_open",
    span_verifiable: bool = True,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "reported_outcome_bucket": bucket,
        "assay_kind": assay,
        "model_system": model,
        "cell_or_tissue": tissue,
        "zygosity_context": zygosity,
        "throughput_class": throughput,
        "source_identifiers": list(sources),
        "dataset_accession": dataset_accession,
        "version_of": version_of,
        "experimental_program_id": program,
        "lab_lineage_key": lab,
        "assay_protocol_lineage_key": protocol_lineage,
        "derived_from_observation_ids": list(derived_from),
        "access_status": access,
        "license_family": license_family,
        "span_verifiable": span_verifiable,
        "bucket_basis": "synthetic declared basis",
    }


def _rec(
    record_id: str,
    *,
    residue: int | None,
    observations: Sequence[Mapping[str, Any]] = (),
    spec_stratum: str = "conflicting",
    spec_stratum_derivation: str = "external_label",
    resolved: bool = True,
    raw_identity_string: str | None = None,
    consequence_class: str = "missense_substitution",
    spdi_position: int | None = None,
) -> dict[str, Any]:
    """A universe record whose DERIVED fields are filled in later by the builder.

    ``spdi_position`` decouples the genomic coordinate from the protein
    residue so two records can legitimately collide on residue/codon while
    keeping distinct ``universe_key`` values (protocol section 16.2/16.3).
    """

    raw = raw_identity_string or (f"synraw.{record_id}" if residue is None else f"p.Lys{residue}Glu")
    position = spdi_position if spdi_position is not None else residue
    return {
        "record_id": record_id,
        "_raw_identity_string": raw,
        "_residue": residue,
        "_spdi_position": position,
        "identity_state": "resolved" if resolved else "unresolved",
        "spdi_canonical": _syn_spdi(position) if (resolved and position is not None) else None,
        "hgvs_c": f"{SYN_TRANSCRIPT}:c.{3 * residue - 2}A>G" if resolved and residue else None,
        "hgvs_p": f"{SYN_PROTEIN}:p.Lys{residue}Glu" if resolved and residue else None,
        "_transcript_pin": SYN_TRANSCRIPT if resolved else None,
        "residue_index": residue if resolved else None,
        "codon_index": residue if resolved else None,
        "consequence_class": consequence_class if resolved else None,
        "functional_evidence_present": bool(observations),
        "observations": [dict(o) for o in observations],
        "spec_stratum": spec_stratum,
        "spec_stratum_basis": "synthetic label basis",
        "spec_stratum_derivation": spec_stratum_derivation,
    }


def _standard_records() -> list[dict[str, Any]]:
    """Six eligible records over four strata plus one unresolved record.

    Hand-derived expectation: K = 4 non-empty strata (S1, S2, S3, S6), so
    ``N_target = clamp(4 + 2, 5, 10) = 6`` and the six eligible records are the
    ONLY six-member set. Every constraint is satisfiable at n = 6:
    C1/C2/C3 (max 2 per stratum <= 3), C5 (all eligible selected),
    D1 (alpha/beta/gamma), D2 (two model systems), D3 (2 <= 3),
    D4 (rec-e carries two assay kinds), P1 (max 2 sole-supported),
    P2 (four established groups), P3 (zero high-throughput-only).
    """

    return [
        _rec(
            "rec-a",
            residue=11,
            spec_stratum="known_pathogenic",
            observations=[
                _obs("obs-a1", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYNSRC-A",), lab="synlab-a", protocol_lineage="synproto-a"),
            ],
        ),
        _rec(
            "rec-b",
            residue=12,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-b1", bucket="intermediate_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYNSRC-B",), lab="synlab-b", protocol_lineage="synproto-b"),
            ],
        ),
        _rec(
            "rec-c",
            residue=13,
            spec_stratum="known_benign",
            observations=[
                _obs("obs-c1", bucket="near_reference", assay=SYN_ASSAYS[2], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYNSRC-C",), lab="synlab-c", protocol_lineage="synproto-c"),
            ],
        ),
        _rec("rec-d", residue=14, spec_stratum="vus_without_functional_evidence", observations=[]),
        _rec(
            "rec-e",
            residue=15,
            spec_stratum="known_pathogenic",
            observations=[
                _obs("obs-e1", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYNSRC-A",), lab="synlab-a", protocol_lineage="synproto-a"),
                _obs("obs-e2", bucket="substantial_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYNSRC-A",), lab="synlab-a", protocol_lineage="synproto-a"),
            ],
        ),
        _rec(
            "rec-f",
            residue=16,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-f1", bucket="intermediate_deviation", assay=SYN_ASSAYS[2], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYNSRC-D",), lab="synlab-d", protocol_lineage="synproto-d"),
            ],
        ),
        _rec("rec-z", residue=None, resolved=False, spec_stratum="vus_without_functional_evidence"),
    ]


# ---------------------------------------------------------------------------
# Synthetic world (pack, protocol, registration, universe, raw, map, responses)
# ---------------------------------------------------------------------------


def _pack_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema": "atlas.disease_pack.v1",
        "pack_id": SYN_PACK_ID,
        "pack_version": SYN_PACK_VERSION,
        "pack_content_hash": "0" * 64,
        "allowed_genes": [SYN_GENE],
        "assembly_pins": [SYN_ASSEMBLY],
        "transcript_pins": [{"transcript": SYN_TRANSCRIPT, "requires": "synthetic-verification"}],
        "reconciliation_policy": {"alias_to_canonical_spdi_only": True, "no_fabrication": True},
        "ontology_extensions": {
            "claim_kinds": [],
            "node_layers": [],
            "mechanism_classes": [],
            "context_vocabularies": {},
        },
        "source_register_pins": [],
        "prohibitions": {
            "non_public_license_families": ["synlicense_nonpublic"],
            "identifiable_content": False,
        },
        "pilot_eval_metadata": {},
    }
    manifest["pack_content_hash"] = _canonical_hash(manifest, "pack_content_hash")
    return manifest


_PROTOCOL_TEXT = (
    "# Synthetic panel selection protocol (fixture)\n\n"
    "This file exists only so the fixture has a hashable protocol document.\n"
    "It carries no rules; the rules under test are the real protocol's.\n"
)


class _World:
    """A complete, self-consistent synthetic selection world under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo_root = root / "repo"
        self.external_root = root / "external"
        self.protocol_path = self.repo_root / "docs" / "project" / "atlas" / "synthetic-protocol.md"
        self.registration_path = (
            self.repo_root / "docs" / "project" / "atlas" / "synthetic-registration.yaml"
        )
        self.pack_path = self.repo_root / "configs" / "atlas" / "packs" / SYN_PACK_ID / "pack.yaml"
        self.universe_lock_path = (
            self.repo_root / "configs" / "atlas" / "panels" / "synth" / "universe-lock.yaml"
        )
        self.map_lock_path = (
            self.repo_root / "configs" / "atlas" / "panels" / "synth" / "identity-map-lock.yaml"
        )
        self.universe_path = self.external_root / "candidate-universe.yaml"
        self.raw_inventory_path = self.external_root / "discovery-inventory.raw.yaml"
        self.map_path = self.external_root / "raw-identity-map.yaml"
        self.response_root = self.external_root / "responses"
        self.anchor_residue = 99
        self.anchor_spdi = _syn_spdi(self.anchor_residue)
        self._baseline: dict[Path, bytes] = {}

    # -- introspection helpers ------------------------------------------
    @property
    def input_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(p for p in self.root.rglob("*") if p.is_file()))

    def snapshot(self) -> dict[str, bytes]:
        return {str(p): p.read_bytes() for p in self.input_paths}

    def seal(self) -> "_World":
        self._baseline = {p: p.read_bytes() for p in self.input_paths}
        return self

    def assert_inputs_unchanged(self) -> None:
        current = {p: p.read_bytes() for p in self.input_paths}
        assert set(current) == set(self._baseline), "the selector added or removed an input file"
        changed = [str(p) for p in current if current[p] != self._baseline[p]]
        assert not changed, f"input files were rewritten by the selector: {changed}"

    def read_yaml(self, path: Path) -> dict[str, Any]:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def tamper_yaml(self, path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
        """Rewrite a sealed artifact WITHOUT repairing its self-hash."""

        payload = self.read_yaml(path)
        mutate(payload)
        _write_yaml(path, payload)
        self._baseline[path] = path.read_bytes()

    def inputs(self, **overrides: Any) -> Any:
        selection_inputs = _sut("SelectionInputs")
        anchor = _sut("AnchorSpec")(
            spdi_canonical=self.anchor_spdi, residue_index=self.anchor_residue
        )
        kwargs: dict[str, Any] = {
            "repo_root": self.repo_root,
            "protocol_path": self.protocol_path,
            "registration_path": self.registration_path,
            "pack_path": self.pack_path,
            "universe_path": self.universe_path,
            "raw_inventory_path": self.raw_inventory_path,
            "anchor": anchor,
            "run_started_at": RUN_STARTED_AT,
            "executor_identity": EXECUTOR_IDENTITY,
            "identity_map_path": self.map_path,
            "identity_map_response_root": self.response_root,
            "node_budget_override": None,
        }
        kwargs.update(overrides)
        return selection_inputs(**kwargs)


def _write_responses(world: _World, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Write the pinned official response bundle and return per-record pins."""

    root = world.response_root
    pins: dict[str, Any] = {}
    reference_rows: list[list[str]] = []
    reference_ids: list[str] = []
    for index, record in enumerate(records):
        raw_record_id = f"raw-{record['record_id']}"
        resolved = record["identity_state"] == "resolved"
        uid = str(9000 + index)
        ids = [uid] if resolved else []
        search_path = root / "search" / f"{raw_record_id}.json"
        search_path.parent.mkdir(parents=True, exist_ok=True)
        search_path.write_text(
            json.dumps({"esearchresult": {"count": str(len(ids)), "idlist": ids}}), encoding="utf-8"
        )
        summary_pins: list[dict[str, Any]] = []
        for summary_uid in ids:
            residue = record["_residue"]
            title = (
                f"{SYN_TRANSCRIPT}({SYN_GENE}):c.{3 * residue - 2}A>G (p.Lys{residue}Glu)"
            )
            summary_path = root / "summary" / raw_record_id / f"{summary_uid}.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "result": {
                            "uids": [summary_uid],
                            summary_uid: {
                                "uid": summary_uid,
                                "gene_sort": SYN_GENE,
                                "genes": [{"symbol": SYN_GENE}],
                                "title": title,
                                "protein_change": f"K{residue}E",
                                "molecular_consequence_list": ["missense variant"],
                                "variation_set": [
                                    {
                                        "variant_type": "single nucleotide variant",
                                        "canonical_spdi": record.get("_mock_spdi") or _syn_spdi(record["_spdi_position"]),
                                        "variation_loc": [
                                            {
                                                "status": "current",
                                                "assembly_name": SYN_ASSEMBLY,
                                                "assembly_acc_ver": SYN_ASM_ACC,
                                            }
                                        ],
                                    }
                                ],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = summary_path.read_bytes()
            summary_pins.append(
                {
                    "uid": summary_uid,
                    "relative_path": summary_path.relative_to(root).as_posix(),
                    "sha256": _sha256_bytes(payload),
                    "byte_length": len(payload),
                }
            )
            reference_ids.append(summary_uid)
            reference_rows.append(
                [
                    summary_uid,
                    title,
                    SYN_GENE,
                    f"{SYN_TRANSCRIPT}:c.{3 * residue - 2}A>G",
                    f"{SYN_PROTEIN}:p.Lys{residue}Glu",
                ]
            )
        pins[record["record_id"]] = {
            "raw_record_id": raw_record_id,
            "search_path": search_path,
            "search_count": len(ids),
            "summary_pins": summary_pins,
        }

    reference_path = root / "reference" / "protein.json"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_text(
        json.dumps([len(reference_rows), reference_ids, None, reference_rows]), encoding="utf-8"
    )
    tool_path = root / "acquisition-tool.py"
    tool_path.write_text("# synthetic acquisition tool\n", encoding="utf-8")
    pins["__reference__"] = reference_path
    pins["__tool__"] = tool_path
    pins["__reference_rows__"] = len(reference_rows)
    return pins


def build_world(
    tmp_path: Path,
    *,
    records: Sequence[Mapping[str, Any]] | None = None,
    node_budget: int = 200000,
    panel_min: int = 5,
    panel_max: int = 10,
    search_scope: str = "full_eligible_universe",
    stratum_shortlist_size: Any = None,
    lock_at_current_bindings: bool = False,
    on_pack: Callable[[dict], None] | None = None,
    on_registration: Callable[[dict], None] | None = None,
    on_universe: Callable[[dict], None] | None = None,
    on_universe_lock: Callable[[dict], None] | None = None,
    on_map: Callable[[dict], None] | None = None,
    on_map_lock: Callable[[dict], None] | None = None,
    on_raw: Callable[[dict], None] | None = None,
    on_ledger: Callable[[list], None] | None = None,
    on_records: Callable[[list], None] | None = None,
    seal: bool = True,
) -> _World:
    """Build a complete, hash-consistent synthetic world.

    Every mutation hook runs BEFORE the corresponding self-hash is computed, so
    a hook produces a world that is internally consistent but semantically
    different; :meth:`_World.tamper_yaml` produces the opposite (bytes changed,
    self-hash stale).
    """

    world = _World(tmp_path)
    raw_records = [dict(r) for r in (records if records is not None else _standard_records())]
    if on_records is not None:
        on_records(raw_records)

    # -- pack -----------------------------------------------------------
    pack = _pack_manifest()
    if on_pack is not None:
        on_pack(pack)
        pack["pack_content_hash"] = _canonical_hash(pack, "pack_content_hash")
    _write_yaml(world.pack_path, pack)

    # -- protocol document ----------------------------------------------
    world.protocol_path.parent.mkdir(parents=True, exist_ok=True)
    world.protocol_path.write_text(_PROTOCOL_TEXT, encoding="utf-8")

    # -- derived record fields ------------------------------------------
    all_observations = [o for r in raw_records for o in r["observations"]]
    index = _lineage_index(all_observations)
    universe_records: list[dict[str, Any]] = []
    for record in raw_records:
        matched = _matched_strata(record["functional_evidence_present"], record["observations"])
        primary = _primary_stratum(matched) if matched else "S6"
        groups = _record_groups(record, index)
        unknown = any(_observation_unknown(o) for o in record["observations"])
        resolved = record["identity_state"] == "resolved"
        entry = {
            "record_id": record["record_id"],
            "universe_key": _universe_key(
                identity_state=record["identity_state"],
                spdi_canonical=record["spdi_canonical"],
                raw_identity_string=record["_raw_identity_string"],
            ),
            "identity_state": record["identity_state"],
            "spdi_canonical": record["spdi_canonical"],
            "hgvs_c": record["hgvs_c"],
            "hgvs_p": record["hgvs_p"],
            "_transcript_pin": record["_transcript_pin"],
            "residue_index": record["residue_index"],
            "codon_index": record["codon_index"],
            "consequence_class": record["consequence_class"],
            "functional_evidence_present": record["functional_evidence_present"],
            "observations": record["observations"],
            "spec_stratum": record["spec_stratum"],
            "spec_stratum_basis": record["spec_stratum_basis"],
            "spec_stratum_derivation": record["spec_stratum_derivation"],
            "all_matched_strata": list(matched),
            "primary_stratum": primary,
            "support_source_groups": list(groups),
            "lineage_confidence": "unknown" if unknown else "established",
            "support_class": _support_class(record, index),
            "exclusion_flags": [] if resolved else ["X1"],
            "_mock_spdi": record.get("_mock_spdi"),
            "_raw_identity_string": record["_raw_identity_string"],
            "_residue": record["_residue"],
            "_spdi_position": record["_spdi_position"],
        }
        universe_records.append(entry)

    # -- response bundle + identity map ---------------------------------
    pins = _write_responses(world, universe_records)
    raw_rows = [
        {
            "raw_record_id": pins[r["record_id"]]["raw_record_id"],
            "raw_identity_string": r["_raw_identity_string"],
            "source_reported_consequence_hint": "missense_substitution",
        }
        for r in universe_records
    ]
    raw_manifest = {
        "schema": "atlas.discovery_inventory.raw.v1",
        "record_count": len(raw_rows),
        "captured_at": "2026-04-01T00:00:00Z",
        "format": "yaml",
        "rows": raw_rows,
    }
    if on_raw is not None:
        on_raw(raw_manifest)
    _write_yaml(world.raw_inventory_path, raw_manifest)
    raw_hash, raw_bytes = _raw_inventory_file_digest(world.raw_inventory_path)
    raw_file_sha = _sha256_bytes(world.raw_inventory_path.read_bytes())

    map_records = []
    for record in universe_records:
        pin = pins[record["record_id"]]
        resolved = record["identity_state"] == "resolved"
        map_records.append(
            {
                "raw_record_id": pin["raw_record_id"],
                "raw_identity_string": record["_raw_identity_string"],
                "source_reported_consequence_hint": "missense_substitution",
                "search_term": f"{record['_raw_identity_string']}[varname] AND {SYN_GENE}[gene]",
                "search_response_relative_path": pin["search_path"]
                .relative_to(world.response_root)
                .as_posix(),
                "search_response_sha256": _sha256_bytes(pin["search_path"].read_bytes()),
                "search_count": pin["search_count"],
                "summary_response_pins": pin["summary_pins"],
                "match_state": "resolved_unique_official_match"
                if resolved
                else "unresolved_official_zero_match",
                "normalization_outcome": "resolved_identity" if resolved else "unresolved_identity",
                "universe_key": record["universe_key"],
                "identity_state": record["identity_state"],
                "spdi_canonical": record["spdi_canonical"],
                "hgvs_c": record["hgvs_c"],
                "hgvs_p": record["hgvs_p"],
                "transcript_pin": record["_transcript_pin"],
                "residue_index": record["residue_index"],
                "codon_index": record["codon_index"],
                "consequence_class": record["consequence_class"],
                "scope_decision": "in_scope" if resolved else "unresolved",
                "exclusion_code": None if resolved else "X1",
            }
        )

    bundle_hash, file_count, byte_count = _bundle_digest(world.response_root)
    reference_path = pins["__reference__"]
    tool_path = pins["__tool__"]
    map_manifest: dict[str, Any] = {
        "schema": "atlas.raw_identity_map.v2",
        "map_id": "synthetic-panel-map",
        "map_version": "1",
        "map_content_hash": "0" * 64,
        "created_at": "2026-04-02T00:00:00Z",
        "pack_binding": {
            "pack_id": pack["pack_id"],
            "pack_version": pack["pack_version"],
            "pack_content_hash": pack["pack_content_hash"],
        },
        "reference_binding": {
            "provider": "SYNTHETIC",
            "database": "synthetic-variants",
            "transcript": SYN_TRANSCRIPT,
            "protein": SYN_PROTEIN,
            "assembly": SYN_ASSEMBLY,
            "protein_reference_total_count": pins["__reference_rows__"],
            "protein_reference_page_size": 500,
            "protein_reference_response_pins": [
                {
                    "offset": 0,
                    "count": 500,
                    "relative_path": reference_path.relative_to(world.response_root).as_posix(),
                    "sha256": _sha256_bytes(reference_path.read_bytes()),
                    "byte_length": len(reference_path.read_bytes()),
                }
            ],
        },
        "raw_inventory_binding": {
            "path": world.raw_inventory_path.name,
            "sha256": raw_file_sha,
            "record_count": len(raw_rows),
        },
        "response_bundle": {
            "sha256": bundle_hash,
            "file_count": file_count,
            "byte_count": byte_count,
        },
        "acquisition_tool": {
            "relative_path": tool_path.relative_to(world.response_root).as_posix(),
            "sha256": _sha256_bytes(tool_path.read_bytes()),
        },
        "records": map_records,
    }
    if on_map is not None:
        on_map(map_manifest)
    map_manifest["map_content_hash"] = _canonical_hash(map_manifest, "map_content_hash")
    _write_yaml(world.map_path, map_manifest)

    map_lock: dict[str, Any] = {
        "schema": "atlas.raw_identity_map_lock.v2",
        "lock_id": "synthetic-panel-map-lock",
        "lock_version": "1",
        "created_at": "2026-04-03T00:00:00Z",
        "map_id": map_manifest["map_id"],
        "map_version": map_manifest["map_version"],
        "map_content_hash": map_manifest["map_content_hash"],
        "map_record_count": len(map_records),
        "raw_inventory_content_hash": raw_file_sha,
        "raw_inventory_record_count": len(raw_rows),
        "response_bundle_hash": bundle_hash,
        "response_file_count": file_count,
        "response_byte_count": byte_count,
        "pack_binding": dict(map_manifest["pack_binding"]),
        "reference_binding": dict(map_manifest["reference_binding"]),
        "acquisition_tool_sha256": map_manifest["acquisition_tool"]["sha256"],
        "lock_content_hash": "0" * 64,
    }
    if on_map_lock is not None:
        on_map_lock(map_lock)
    map_lock["lock_content_hash"] = _canonical_hash(map_lock, "lock_content_hash")
    _write_yaml(world.map_lock_path, map_lock)

    # -- ledger + universe ----------------------------------------------
    ledger_rows = [
        {
            "raw_record_id": pins[r["record_id"]]["raw_record_id"],
            "raw_identity_string": r["_raw_identity_string"],
            "normalization_rule_id": "SYN-N1",
            "normalization_outcome": "resolved_identity"
            if r["identity_state"] == "resolved"
            else "unresolved_identity",
            "universe_key": r["universe_key"],
        }
        for r in universe_records
    ]
    if on_ledger is not None:
        on_ledger(ledger_rows)
    ledger_hash = _ledger_hash(ledger_rows)
    discovery_count, discovery_hash = _discovery_commitment(r["universe_key"] for r in ledger_rows)

    public_records = [
        {k: v for k, v in record.items() if not k.startswith("_")} for record in universe_records
    ]
    universe: dict[str, Any] = {
        "schema": "atlas.candidate_universe.v1",
        "universe_id": "synthetic-universe",
        "universe_version": 3,
        "universe_content_hash": "0" * 64,
        "gene": SYN_GENE,
        "assembly": SYN_ASSEMBLY,
        "transcript_pin": SYN_TRANSCRIPT,
        "pack_binding": dict(map_manifest["pack_binding"]),
        "discovery_run_ref": {"run_id": "synthetic-run", "captured_at": "2026-04-01T00:00:00Z"},
        "raw_inventory": {
            "path": world.raw_inventory_path.name,
            "captured_at": raw_manifest["captured_at"],
            "record_count": len(raw_rows),
            "content_hash_algorithm": "atlas.raw_inventory_hash.v1",
            "content_hash": raw_hash,
            "normalized_byte_length": raw_bytes,
            "format": "yaml",
        },
        "discovery_set_commitment": {
            "discovery_set_count": discovery_count,
            "discovery_set_hash": discovery_hash,
            "algorithm": "atlas.discovery_set_commitment.v1",
            "committed_at": "2026-04-04T00:00:00Z",
        },
        "normalization_ledger": ledger_rows,
        "completeness_attestation": {
            "attesting_role": "synthetic-custodian",
            "statement": (
                "No discovered candidate was withheld and no record was added after any "
                "selection was attempted."
            ),
            "attested_at": "2026-04-04T00:00:00Z",
        },
        "records": public_records,
    }
    if on_universe is not None:
        on_universe(universe)
    universe["universe_content_hash"] = _canonical_hash(universe, "universe_content_hash")
    _write_yaml(world.universe_path, universe)

    # -- universe lock ---------------------------------------------------
    prior_doc_hash = _sha256_text("synthetic prior protocol document")
    prior_registration_hash = _sha256_text("synthetic prior registration")
    protocol_doc_hash = _doc_hash(world.protocol_path)
    universe_lock: dict[str, Any] = {
        "schema": "atlas.candidate_universe_lock.v1",
        "lock_id": "synthetic-universe-lock",
        "lock_version": 4,
        "universe_id": universe["universe_id"],
        "universe_version": universe["universe_version"],
        "created_at": LOCK_CREATED_AT,
        "created_by_role": "synthetic-custodian",
        "protocol_version": SYN_PROTOCOL_VERSION if lock_at_current_bindings else SYN_PRIOR_PROTOCOL_VERSION,
        "protocol_doc_hash": protocol_doc_hash if lock_at_current_bindings else prior_doc_hash,
        "registration_content_hash": "PENDING" if lock_at_current_bindings else prior_registration_hash,
        "universe_content_hash": universe["universe_content_hash"],
        "universe_content_hash_algorithm": "atlas.candidate_universe_content_hash.v1",
        "raw_inventory": {
            "path": world.raw_inventory_path.name,
            "content_hash": raw_hash,
            "content_hash_algorithm": "atlas.raw_inventory_hash.v1",
            "record_count": len(raw_rows),
            "normalized_byte_length": raw_bytes,
            "captured_at": raw_manifest["captured_at"],
        },
        "normalization_ledger": {
            "hash": ledger_hash,
            "hash_algorithm": "atlas.normalization_ledger_hash.v1",
            "row_count": len(ledger_rows),
        },
        "discovery_set_commitment": {
            "hash": discovery_hash,
            "hash_algorithm": "atlas.discovery_set_commitment.v1",
            "count": discovery_count,
            "committed_at": universe["discovery_set_commitment"]["committed_at"],
        },
        "pack_binding": dict(map_manifest["pack_binding"]),
        "identity_map_binding": {
            "schema": map_lock["schema"],
            "map_id": map_manifest["map_id"],
            "map_version": map_manifest["map_version"],
            "lock_id": map_lock["lock_id"],
            "lock_version": map_lock["lock_version"],
            "map_content_hash": map_manifest["map_content_hash"],
            "lock_content_hash": map_lock["lock_content_hash"],
            "response_bundle_hash": bundle_hash,
            "map_record_count": len(map_records),
            "pack_binding": dict(map_manifest["pack_binding"]),
        },
        "storage_location": "external_content_root",
        "completeness_attestation_ref": "synthetic-attestation",
        "lock_content_hash": "0" * 64,
    }
    if on_universe_lock is not None:
        on_universe_lock(universe_lock)

    # -- registration (two-pass: the lock mirrors the registration hash) --
    def _registration(lock_hash: str) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "schema": "atlas.panel_selection_registration.v1",
            "registration_id": "synthetic-registration",
            "protocol_version": SYN_PROTOCOL_VERSION,
            "protocol_doc_path": str(
                world.protocol_path.relative_to(world.repo_root).as_posix()
            ),
            "protocol_doc_hash": protocol_doc_hash,
            "protocol_doc_hash_algorithm": "atlas.protocol_doc_hash.v1",
            "registration_content_hash": "0" * 64,
            "registration_content_hash_algorithm": "atlas.registration_content_hash.v1",
            "selection_seed": SYN_SEED,
            "pack_binding_observed_at_freeze": dict(map_manifest["pack_binding"]),
            "candidate_universe_contract": {
                "universe_lock": {
                    "active": {
                        "path": world.universe_lock_path.relative_to(world.repo_root).as_posix(),
                        "lock_version": universe_lock["lock_version"],
                        "universe_version": universe_lock["universe_version"],
                        "lock_content_hash": lock_hash,
                        "universe_content_hash": universe["universe_content_hash"],
                    },
                    "superseded": [
                        {
                            "path": "configs/atlas/panels/synth/universe-lock-v3.yaml",
                            "lock_version": 3,
                            "universe_version": 2,
                            "status": "invalid_binding",
                            "note": "synthetic invalid-binding predecessor; never admissible",
                        }
                    ],
                }
            },
            "identity_map_contract": {
                "active": {
                    "path": world.map_lock_path.relative_to(world.repo_root).as_posix(),
                    "lock_id": map_lock["lock_id"],
                    "lock_version": map_lock["lock_version"],
                    "map_id": map_lock["map_id"],
                    "map_version": map_lock["map_version"],
                    "lock_content_hash": map_lock["lock_content_hash"],
                    "map_content_hash": map_lock["map_content_hash"],
                }
            },
            "executor_preconditions": {"execution_order": list(EXECUTION_ORDER)},
            "sampling_strata": {"omega": list(OMEGA), "ids": list(OMEGA)},
            "panel_size_rule": {
                "formula": "clamp(K + 2, min, max)",
                "min": panel_min,
                "max": panel_max,
            },
            "search_parameters": {
                "search_scope": search_scope,
                "stratum_shortlist_size": stratum_shortlist_size,
                "search_node_budget": node_budget,
            },
            "constraints": {
                "coverage": {"C1": True, "C2": True, "C3": "ceil(n/2)", "C4": True, "C5": True},
                "diversity": {"D1": 3, "D2": 2, "D3": "ceil(n/2)", "D4": True},
                "source_concentration": {"P1": "ceil(n/2)", "P2": 3, "P3": 2},
            },
            "relaxation_ladder": [
                {"step": "R1", "constraint": "C5", "before": True, "after": "report_only"},
                {"step": "R2", "constraint": "P2", "before": 3, "after": 2},
                {"step": "R3", "constraint": "P1", "before": "ceil(n/2)", "after": "ceil(2n/3)"},
                {"step": "R4", "constraint": "D1", "before": 3, "after": 2},
                {"step": "R5", "constraint": "P3", "before": 2, "after": 3},
                {"step": "R6", "constraint": "D2", "before": 2, "after": 1},
                {"step": "R7", "constraint": "P2", "before": 2, "after": 1},
            ],
            "never_relaxed": [
                "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8",
                "firewall", "C1", "C2", "C4", "anti_proxy", "dedupe",
                "unknown_lineage_pooling", "undetermined_relaxation",
            ],
            "amendment_log": [
                {
                    "version": SYN_PRIOR_PROTOCOL_VERSION,
                    "timestamp": "2026-03-01T00:00:00Z",
                    "known_candidate_level_results_at_amendment": False,
                    "pre_first_run_correction": False,
                },
                {
                    "version": SYN_PROTOCOL_VERSION,
                    "timestamp": "2026-03-02T00:00:00Z",
                    "known_candidate_level_results_at_amendment": False,
                    "pre_first_run_correction": True,
                    "supersedes_digests": {
                        "protocol_doc_hash": prior_doc_hash,
                        "registration_content_hash": prior_registration_hash,
                        "note": "synthetic predecessor digests, retained for audit",
                    },
                    "rejected_draft_digests": {
                        "protocol_doc_hash": _sha256_text("synthetic rejected draft protocol"),
                        "registration_content_hash": _sha256_text("synthetic rejected draft registration"),
                        "status": "rejected_before_issue",
                        "note": "AUDIT HISTORY ONLY; never in force, never admissible for K5",
                    },
                },
            ],
        }
        if on_registration is not None:
            on_registration(manifest)
        manifest["registration_content_hash"] = _canonical_hash(
            manifest, "registration_content_hash"
        )
        return manifest

    universe_lock["lock_content_hash"] = _canonical_hash(universe_lock, "lock_content_hash")
    registration = _registration(universe_lock["lock_content_hash"])
    if lock_at_current_bindings:
        universe_lock["registration_content_hash"] = registration["registration_content_hash"]
        universe_lock["lock_content_hash"] = _canonical_hash(universe_lock, "lock_content_hash")
        registration = _registration(universe_lock["lock_content_hash"])
    _write_yaml(world.universe_lock_path, universe_lock)
    _write_yaml(world.registration_path, registration)

    world.pack = pack
    world.universe = universe
    world.universe_lock = universe_lock
    world.registration = registration
    world.map_manifest = map_manifest
    world.map_lock = map_lock
    world.raw_manifest = raw_manifest
    world.ledger_rows = ledger_rows
    world.universe_records = universe_records
    world.protocol_doc_hash = protocol_doc_hash
    world.prior_doc_hash = prior_doc_hash
    world.prior_registration_hash = prior_registration_hash
    if seal:
        world.seal()
    return world


# ---------------------------------------------------------------------------
# Invocation + assertion helpers
# ---------------------------------------------------------------------------


def _select(world: _World, **overrides: Any) -> Any:
    return _sut("select_panel")(world.inputs(**overrides))


def _preconditions(world: _World, **overrides: Any) -> Any:
    return _sut("verify_preconditions")(world.inputs(**overrides))


def _expect(
    world: _World,
    call: Callable[[], Any],
    *,
    error: str,
    code: str | None = None,
    check_id: str | None = None,
) -> BaseException:
    """Assert a typed, fail-closed error and that NOTHING on disk was repaired."""

    error_type = _sut(error)
    with pytest.raises(error_type) as excinfo:
        call()
    raised = excinfo.value
    text = f"{getattr(raised, 'code', '')} {getattr(raised, 'check_id', '')} {raised}"
    if code is not None:
        assert code in text, f"expected code {code!r} in {text!r}"
    if check_id is not None:
        assert check_id in text, f"expected check id {check_id!r} in {text!r}"
    world.assert_inputs_unchanged()
    return raised


def _eligible_pool(world: _World) -> list[dict[str, Any]]:
    """The synthetic eligible pool, derived independently of the implementation."""

    pool = []
    for record in world.universe_records:
        if record["identity_state"] != "resolved":
            continue
        if record["residue_index"] == world.anchor_residue:
            continue
        pool.append(record)
    return sorted(pool, key=lambda r: (_draw_key(r["spdi_canonical"]), r["spdi_canonical"]))


# ---------------------------------------------------------------------------
# Independent constraint checker + brute-force oracle (structurally unlike the
# implementation's allocation-enumeration + DFS, so it cannot be self-confirming)
# ---------------------------------------------------------------------------


def _ceil_half(n: int) -> int:
    return -(-n // 2)


def _check_constraints(
    panel: Sequence[Mapping[str, Any]],
    *,
    n: int,
    nonempty_strata: Sequence[str],
    spec_values: Sequence[str],
    index: Mapping[str, str],
    level: str = "L0",
    pool: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Protocol sections 17.3/17.4 re-expressed as a flat predicate.

    Written as an independent oracle: it takes a *complete* candidate set and
    answers yes/no, with none of the implementation's allocation enumeration,
    ordering or pruning machinery.  ``level`` selects the relaxed thresholds
    from the section 17.6 ladder.
    """

    rung = (["L0", *LADDER_STEPS]).index(level)
    if len(panel) != n:
        return False
    primaries = [r["primary_stratum"] for r in panel]
    if set(nonempty_strata) - set(primaries):
        return False  # C1
    if "S6" in nonempty_strata and "S6" not in primaries:
        return False  # C2
    if any(primaries.count(s) > _ceil_half(n) for s in set(primaries)):
        return False  # C3
    if rung < 1 and set(spec_values) - {r["spec_stratum"] for r in panel}:
        return False  # C5 (report-only from R1)
    assay_kinds = [{o["assay_kind"] for o in r["observations"]} for r in panel]
    distinct_assays = set().union(*assay_kinds) if assay_kinds else set()
    if len(distinct_assays) < (3 if rung < 4 else 2):
        return False  # D1 (relaxed at R4)
    models = set().union(*[{o["model_system"] for o in r["observations"]} for r in panel]) if panel else set()
    if len(models) < (2 if rung < 6 else 1):
        return False  # D2 (relaxed at R6)
    for assay in distinct_assays:
        if sum(1 for kinds in assay_kinds if assay in kinds) > _ceil_half(n):
            return False  # D3
    if pool is not None:
        multi = [r for r in pool if len({o["assay_kind"] for o in r["observations"]}) >= 2]
        if multi and not any(len({o["assay_kind"] for o in r["observations"]}) >= 2 for r in panel):
            return False  # D4 (conditional)
    residues = [r["residue_index"] for r in panel]
    if len(set(residues)) != len(residues):
        return False  # section 16 residue collision
    codons = [(r["_transcript_pin"], r["codon_index"]) for r in panel]
    if len(set(codons)) != len(codons):
        return False  # section 16 codon collision
    groups_per_record = [_record_groups(r, index) for r in panel]
    sole_support: dict[str, int] = {}
    for groups in groups_per_record:
        if len(groups) == 1:
            sole_support[groups[0]] = sole_support.get(groups[0], 0) + 1
    sole_cap = _ceil_half(n) if rung < 3 else -(-2 * n // 3)
    if any(count > sole_cap for count in sole_support.values()):
        return False  # P1 (relaxed at R3)
    established = {g for groups in groups_per_record for g in groups if g != "LG:UNKNOWN-POOL"}
    min_groups = 3 if rung < 2 else (2 if rung < 7 else 1)
    if len(established) < min_groups:
        return False  # P2 (relaxed at R2, then R7)
    if sum(1 for r in panel if _support_class(r, index) == "single_high_throughput_only") > (2 if rung < 5 else 3):
        return False  # P3 (relaxed at R5)
    return True


def _brute_force_solutions(
    pool: Sequence[Mapping[str, Any]],
    *,
    n: int,
    index: Mapping[str, str],
    level: str = "L0",
) -> list[tuple[str, ...]]:
    """Every valid panel of size n, enumerated by raw combination (no pruning)."""

    nonempty = sorted({r["primary_stratum"] for r in pool})
    spec_values = sorted({r["spec_stratum"] for r in pool})
    ordered = sorted(pool, key=lambda r: (_draw_key(r["spdi_canonical"]), r["spdi_canonical"]))
    solutions = []
    for combo in itertools.combinations(ordered, n):
        if _check_constraints(
            combo,
            n=n,
            nonempty_strata=nonempty,
            spec_values=spec_values,
            index=index,
            level=level,
            pool=ordered,
        ):
            solutions.append(tuple(r["record_id"] for r in combo))
    return solutions


def _selected_ids(run: Any) -> tuple[str, ...]:
    return tuple(getattr(run, "selected_record_ids"))


def _spec_ids() -> list[str]:
    text = SPEC_PATH.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"PS-[A-Z]-\d{3}", text)))


def _module_ast() -> ast.Module:
    return ast.parse(THIS_FILE.read_text(encoding="utf-8"))


def _function_nodes(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _write_text(path: Path, text: str, world: _World | None = None) -> None:
    path.write_text(text, encoding="utf-8")
    if world is not None:
        world._baseline[path] = path.read_bytes()


def _checks(report: Any) -> tuple[str, ...]:
    return tuple(getattr(report, "checks_passed"))


# ---------------------------------------------------------------------------
# PS-V-* preconditions
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_v_001_protocol_digest_mismatch(tmp_path: Path) -> None:
    """PS-V-001: one changed byte in the protocol document fails V1."""

    world = build_world(tmp_path)
    _write_text(world.protocol_path, _PROTOCOL_TEXT + "x", world)
    _expect(
        world,
        lambda: _select(world),
        error="AtlasPanelRegistrationError",
        code="PROTOCOL_DIGEST_MISMATCH",
        check_id="V1",
    )


@requires_impl
def test_ps_v_002_registration_self_hash_mismatch(tmp_path: Path) -> None:
    """PS-V-002: a registration whose bytes no longer match its self-hash fails V2."""

    world = build_world(tmp_path)
    world.tamper_yaml(
        world.registration_path,
        lambda payload: payload.__setitem__("registration_id", "tampered-registration"),
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasPanelRegistrationError",
        code="REGISTRATION_SELF_HASH_MISMATCH",
        check_id="V2",
    )


@requires_impl
def test_ps_v_003_seed_mismatch(tmp_path: Path) -> None:
    """PS-V-003: a seed differing from the registration's fails V3."""

    world = build_world(tmp_path, on_registration=lambda m: m.__setitem__("selection_seed", "other-seed"))
    error = _expect(
        world,
        lambda: _select(world),
        error="AtlasPanelRegistrationError",
        code="SEED_MISMATCH",
        check_id="V3",
    )
    assert SYN_SEED not in str(error) or "other-seed" in str(error)


@requires_impl
def test_ps_v_004_pack_drift_against_each_comparand(tmp_path: Path) -> None:
    """PS-V-004: drift against ANY of the three pack comparands is PACK_DRIFT."""

    drifted = "b" * 64
    cases = (
        ("on_registration", lambda m: m["pack_binding_observed_at_freeze"].__setitem__("pack_content_hash", drifted)),
        ("on_universe", lambda m: m["pack_binding"].__setitem__("pack_content_hash", drifted)),
        ("on_universe_lock", lambda m: m["pack_binding"].__setitem__("pack_content_hash", drifted)),
    )
    for hook, mutate in cases:
        world = build_world(tmp_path / f"case-{hook}", **{hook: mutate})
        _expect(
            world,
            lambda w=world: _select(w),
            error="AtlasPanelPackDriftError",
            code="PACK_DRIFT",
            check_id="V4",
        )


@requires_impl
def test_ps_v_005_checks_short_circuit_in_registration_order(tmp_path: Path) -> None:
    """PS-V-005: V2 wins over V4, and V7 wins over V6 (mapper verified first)."""

    early = build_world(tmp_path / "early")
    early.tamper_yaml(early.registration_path, lambda p: p.__setitem__("registration_id", "x"))
    early.tamper_yaml(early.pack_path, lambda p: p.__setitem__("pack_version", "9.9.9"))
    _expect(
        early,
        lambda: _select(early),
        error="AtlasPanelRegistrationError",
        code="REGISTRATION_SELF_HASH_MISMATCH",
        check_id="V2",
    )

    late = build_world(tmp_path / "late")
    late.map_lock_path.unlink()
    late._baseline.pop(late.map_lock_path, None)
    late.tamper_yaml(late.universe_path, lambda p: p["normalization_ledger"].pop())
    error = _expect(
        late,
        lambda: _select(late),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_MISSING",
        check_id="IM1",
    )
    assert "U2" not in str(error), "V6 must not run before V7"


@requires_impl
def test_ps_v_006_precondition_report_is_all_or_nothing(tmp_path: Path) -> None:
    """PS-V-006: a report exists only when every check passed; no partial object."""

    world = build_world(tmp_path / "ok")
    report = _preconditions(world)
    passed = _checks(report)
    for check in ("V1", "V2", "V3", "V4", "V5", "V7", "V6"):
        assert check in passed, f"{check} missing from checks_passed {passed}"
    assert getattr(report, "verified_protocol_doc_hash") == world.protocol_doc_hash
    assert getattr(report, "verified_universe_content_hash") == world.universe["universe_content_hash"]

    broken = build_world(tmp_path / "broken")
    broken.tamper_yaml(broken.registration_path, lambda p: p.__setitem__("registration_id", "x"))
    with pytest.raises(_sut("AtlasPanelError")):
        _preconditions(broken)
    with pytest.raises(TypeError):
        _sut("PreconditionReport")(verified_protocol_doc_hash=world.protocol_doc_hash)


@requires_impl
def test_ps_v_007_no_mapper_injection_seam(tmp_path: Path) -> None:
    """PS-V-007: no mapper field, no mapper keyword, no module-level mapper hook."""

    world = build_world(tmp_path)
    field_names = {f.name for f in dataclass_fields(_sut("SelectionInputs"))}
    assert "raw_identity_mapper" not in field_names
    assert not any("mapper" in name for name in field_names), field_names
    assert "universe_lock_path" not in field_names
    with pytest.raises(TypeError):
        world.inputs(raw_identity_mapper=object())

    select_params = inspect.signature(_sut("select_panel")).parameters
    assert not any("mapper" in name for name in select_params)

    tree = ast.parse(PANEL_MODULE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assert "mapper" not in target.id.lower(), (
                        f"panel.py exposes a module-level mapper hook {target.id!r}"
                    )


# ---------------------------------------------------------------------------
# PS-K-* universe lock and protocol-version delta
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_k_001_lock_resolved_from_registration_pointer(tmp_path: Path) -> None:
    """PS-K-001: the lock comes from the registration; a decoy elsewhere is ignored."""

    world = build_world(tmp_path)
    decoy = world.external_root / "universe-lock.yaml"
    decoy_payload = dict(world.universe_lock)
    decoy_payload["lock_id"] = "decoy-lock"
    decoy_payload["universe_content_hash"] = "c" * 64
    _write_yaml(decoy, decoy_payload)
    world.seal()

    report = _preconditions(world)
    active = getattr(report, "active_universe_lock")
    assert Path(active["path"]).name == world.universe_lock_path.name
    assert "decoy" not in str(active["path"])
    assert getattr(report, "verified_lock_content_hash") == world.universe_lock["lock_content_hash"]


@requires_impl
def test_ps_k_002_missing_and_corrupt_lock(tmp_path: Path) -> None:
    """PS-K-002: absence is UNIVERSE_LOCK_MISSING(K1); tampered self-hash is K2."""

    missing = build_world(tmp_path / "missing")
    missing.universe_lock_path.unlink()
    missing._baseline.pop(missing.universe_lock_path, None)
    _expect(
        missing,
        lambda: _select(missing),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_MISSING",
        check_id="K1",
    )

    corrupt = build_world(tmp_path / "corrupt")
    corrupt.tamper_yaml(corrupt.universe_lock_path, lambda p: p.__setitem__("created_by_role", "other"))
    _expect(
        corrupt,
        lambda: _select(corrupt),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_CORRUPT",
        check_id="K2",
    )


@requires_impl
def test_ps_k_003_lock_hash_must_match_registration_mirror(tmp_path: Path) -> None:
    """PS-K-003: a self-consistent lock that the registration does not mirror fails K2."""

    world = build_world(
        tmp_path,
        on_universe_lock=lambda lock: lock.__setitem__("created_by_role", "another-role"),
    )
    stored = world.read_yaml(world.universe_lock_path)
    assert stored["lock_content_hash"] == _canonical_hash(stored, "lock_content_hash"), (
        "fixture must self-verify so the test isolates the registration mirror"
    )
    world.tamper_yaml(
        world.registration_path,
        lambda p: p["candidate_universe_contract"]["universe_lock"]["active"].__setitem__(
            "lock_content_hash", "d" * 64
        ),
    )
    # repair the registration self-hash so ONLY the mirror disagrees
    payload = world.read_yaml(world.registration_path)
    payload["registration_content_hash"] = _canonical_hash(payload, "registration_content_hash")
    _write_yaml(world.registration_path, payload)
    world.seal()
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_CORRUPT",
        check_id="K2",
    )


@requires_impl
def test_ps_k_004_lock_binding_field_mismatches(tmp_path: Path) -> None:
    """PS-K-004: one case per bound universe/raw/ledger/discovery field."""

    mutations = {
        "universe_content_hash": lambda lock: lock.__setitem__("universe_content_hash", "e" * 64),
        "raw_content_hash": lambda lock: lock["raw_inventory"].__setitem__("content_hash", "e" * 64),
        "raw_record_count": lambda lock: lock["raw_inventory"].__setitem__("record_count", 999),
        "ledger_hash": lambda lock: lock["normalization_ledger"].__setitem__("hash", "e" * 64),
        "ledger_row_count": lambda lock: lock["normalization_ledger"].__setitem__("row_count", 999),
        "discovery_hash": lambda lock: lock["discovery_set_commitment"].__setitem__("hash", "e" * 64),
        "discovery_count": lambda lock: lock["discovery_set_commitment"].__setitem__("count", 999),
    }
    for name, mutate in mutations.items():
        world = build_world(tmp_path / f"k4-{name}", on_universe_lock=mutate)
        _expect(
            world,
            lambda w=world: _select(w),
            error="AtlasUniverseLockError",
            code="UNIVERSE_LOCK_MISMATCH",
            check_id="K3",
        )


@requires_impl
def test_ps_k_005_lock_pack_binding_drift(tmp_path: Path) -> None:
    """PS-K-005: a lock pack binding that is not the live pack is PACK_DRIFT at K4."""

    world = build_world(
        tmp_path,
        on_universe_lock=lambda lock: lock["pack_binding"].__setitem__("pack_content_hash", "f" * 64),
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasPanelPackDriftError",
        code="PACK_DRIFT",
        check_id="K4",
    )


@requires_impl
def test_ps_k_006_duplicate_lock_for_one_universe_version(tmp_path: Path) -> None:
    """PS-K-006: two locks for one universe_version is K6; another version is not."""

    other_version = build_world(tmp_path / "other")
    sibling = other_version.universe_lock_path.with_name("universe-lock-v2.yaml")
    payload = dict(other_version.universe_lock)
    payload["lock_id"] = "synthetic-universe-lock-v2"
    payload["universe_version"] = other_version.universe["universe_version"] - 1
    payload["lock_version"] = 3
    payload["lock_content_hash"] = _canonical_hash(payload, "lock_content_hash")
    _write_yaml(sibling, payload)
    other_version.seal()
    assert _checks(_preconditions(other_version)), "a lock for a different version is not a duplicate"

    duplicate = build_world(tmp_path / "dupe")
    twin = duplicate.universe_lock_path.with_name("universe-lock-twin.yaml")
    twin_payload = dict(duplicate.universe_lock)
    twin_payload["lock_id"] = "synthetic-universe-lock-twin"
    twin_payload["lock_version"] = 5
    twin_payload["lock_content_hash"] = _canonical_hash(twin_payload, "lock_content_hash")
    _write_yaml(twin, twin_payload)
    duplicate.seal()
    _expect(
        duplicate,
        lambda: _select(duplicate),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_INVALID",
        check_id="K6",
    )


@requires_impl
def test_ps_k_007_lock_created_after_run_start(tmp_path: Path) -> None:
    """PS-K-007: a lock created after the injected run clock is K6."""

    world = build_world(tmp_path)
    earlier = RUN_STARTED_AT - timedelta(days=365)
    _expect(
        world,
        lambda: _select(world, run_started_at=earlier),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_INVALID",
        check_id="K6",
    )


@requires_impl
def test_ps_k_008_delta_shape_is_complete_even_when_equal(tmp_path: Path) -> None:
    """PS-K-008: exactly eight non-null fields, present when differs is False."""

    expected = {
        "lock_protocol_version",
        "lock_protocol_doc_hash",
        "lock_registration_content_hash",
        "current_protocol_version",
        "current_protocol_doc_hash",
        "current_registration_content_hash",
        "differs",
        "reconciled_via_amendment_log_versions",
    }
    assert {f.name for f in dataclass_fields(_sut("LockProtocolVersionDelta"))} == expected

    differing = build_world(tmp_path / "differs")
    delta = getattr(_preconditions(differing), "lock_protocol_version_delta")
    assert getattr(delta, "differs") is True
    assert getattr(delta, "lock_protocol_version") == SYN_PRIOR_PROTOCOL_VERSION
    assert getattr(delta, "current_protocol_version") == SYN_PROTOCOL_VERSION
    assert tuple(getattr(delta, "reconciled_via_amendment_log_versions")) == (SYN_PROTOCOL_VERSION,)

    equal = build_world(tmp_path / "equal", lock_at_current_bindings=True)
    same = getattr(_preconditions(equal), "lock_protocol_version_delta")
    assert getattr(same, "differs") is False
    assert tuple(getattr(same, "reconciled_via_amendment_log_versions")) == ()
    for name in expected:
        assert getattr(same, name) is not None, f"delta field {name} is null when differs is False"


@requires_impl
def test_ps_k_009_incomplete_delta_is_rejected(tmp_path: Path) -> None:
    """PS-K-009: omitting any delta field is UNIVERSE_LOCK_DELTA_INCOMPLETE(K5)."""

    delta_type = _sut("LockProtocolVersionDelta")
    names = [f.name for f in dataclass_fields(delta_type)]
    complete = {
        "lock_protocol_version": SYN_PRIOR_PROTOCOL_VERSION,
        "lock_protocol_doc_hash": "a" * 64,
        "lock_registration_content_hash": "b" * 64,
        "current_protocol_version": SYN_PROTOCOL_VERSION,
        "current_protocol_doc_hash": "c" * 64,
        "current_registration_content_hash": "d" * 64,
        "differs": True,
        "reconciled_via_amendment_log_versions": (SYN_PROTOCOL_VERSION,),
    }
    for omitted in names:
        with pytest.raises(TypeError):
            delta_type(**{k: v for k, v in complete.items() if k != omitted})

    world = build_world(
        tmp_path,
        on_universe_lock=lambda lock: lock.pop("registration_content_hash"),
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasLockDeltaError",
        code="UNIVERSE_LOCK_DELTA_INCOMPLETE",
        check_id="K5",
    )


@requires_impl
def test_ps_k_010_unknown_lock_triple_is_rejected(tmp_path: Path) -> None:
    """PS-K-010: a lock triple absent from the amendment log is PROTOCOL_UNKNOWN."""

    unknown_version = build_world(
        tmp_path / "version",
        on_universe_lock=lambda lock: lock.__setitem__("protocol_version", "0.0.9"),
    )
    _expect(
        unknown_version,
        lambda: _select(unknown_version),
        error="AtlasLockDeltaError",
        code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN",
        check_id="K5",
    )

    unknown_digest = build_world(
        tmp_path / "digest",
        on_universe_lock=lambda lock: lock.__setitem__("protocol_doc_hash", "9" * 64),
    )
    _expect(
        unknown_digest,
        lambda: _select(unknown_digest),
        error="AtlasLockDeltaError",
        code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN",
        check_id="K5",
    )


@requires_impl
def test_ps_k_011_valid_delta_does_not_waive_other_lock_checks(tmp_path: Path) -> None:
    """PS-K-011 ADVERSARIAL: a reconcilable delta never rescues a broken K3."""

    baseline = build_world(tmp_path / "baseline")
    delta = getattr(_preconditions(baseline), "lock_protocol_version_delta")
    assert getattr(delta, "differs") is True, "fixture must carry a reconcilable delta"

    broken = build_world(
        tmp_path / "broken",
        on_universe_lock=lambda lock: lock["normalization_ledger"].__setitem__("row_count", 42),
    )
    _expect(
        broken,
        lambda: _select(broken),
        error="AtlasUniverseLockError",
        code="UNIVERSE_LOCK_MISMATCH",
        check_id="K3",
    )


@requires_impl
def test_ps_k_012_chain_must_be_gap_free(tmp_path: Path) -> None:
    """PS-K-012 ADVERSARIAL: a skipped intervening amendment is DELTA_INCOMPLETE."""

    def add_gap(manifest: dict) -> None:
        log = manifest["amendment_log"]
        log.append(
            {
                "version": "0.1.2",
                "timestamp": "2026-03-03T00:00:00Z",
                "known_candidate_level_results_at_amendment": False,
                "pre_first_run_correction": True,
            }
        )
        manifest["protocol_version"] = "0.1.2"

    world = build_world(tmp_path, on_registration=add_gap)
    versions = [entry["version"] for entry in world.registration["amendment_log"]]
    assert versions == [SYN_PRIOR_PROTOCOL_VERSION, SYN_PROTOCOL_VERSION, "0.1.2"], versions
    _expect(
        world,
        lambda: _select(world),
        error="AtlasLockDeltaError",
        code="UNIVERSE_LOCK_DELTA_INCOMPLETE",
        check_id="K5",
    )


@requires_impl
def test_ps_k_013_k5_is_universe_lock_only(tmp_path: Path) -> None:
    """PS-K-013: an identity-map lock never acquires a delta requirement."""

    baseline = build_world(tmp_path / "baseline")
    report = _preconditions(baseline)
    delta = getattr(report, "lock_protocol_version_delta")
    assert getattr(delta, "lock_protocol_version") == baseline.universe_lock["protocol_version"]
    assert "protocol_version" not in baseline.map_lock

    injected = build_world(
        tmp_path / "injected",
        on_map_lock=lambda lock: lock.__setitem__("protocol_version", "0.0.7"),
    )
    _expect(
        injected,
        lambda: _select(injected),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_CORRUPT",
        check_id="IM1",
    )


# ---------------------------------------------------------------------------
# PS-M-* identity map binding (V7 / IM1-IM6)
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_m_001_map_lock_resolved_from_registration(tmp_path: Path) -> None:
    """PS-M-001: IM1 resolves the map lock from the registration, not the caller."""

    world = build_world(tmp_path)
    decoy = world.map_path.with_name("identity-map-lock.yaml")
    decoy_payload = dict(world.map_lock)
    decoy_payload["lock_id"] = "decoy-map-lock"
    decoy_payload["map_record_count"] = 1
    decoy_payload["lock_content_hash"] = _canonical_hash(decoy_payload, "lock_content_hash")
    _write_yaml(decoy, decoy_payload)
    world.seal()

    field_names = {f.name for f in dataclass_fields(_sut("SelectionInputs"))}
    assert "identity_map_lock_path" not in field_names
    report = _preconditions(world)
    assert getattr(report, "verified_map_content_hash", world.map_lock["map_content_hash"]) == (
        world.map_lock["map_content_hash"]
    )
    assert "IM1" in _checks(report)


@requires_impl
def test_ps_m_002_map_lock_absent_corrupt_or_unmirrored(tmp_path: Path) -> None:
    """PS-M-002: absent / wrong-schema / tampered / unmirrored map locks all fail IM1."""

    missing = build_world(tmp_path / "missing")
    missing.map_lock_path.unlink()
    missing._baseline.pop(missing.map_lock_path, None)
    _expect(
        missing,
        lambda: _select(missing),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_MISSING",
        check_id="IM1",
    )

    wrong_schema = build_world(
        tmp_path / "schema", on_map_lock=lambda lock: lock.__setitem__("schema", "atlas.wrong.v1")
    )
    _expect(
        wrong_schema,
        lambda: _select(wrong_schema),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_CORRUPT",
        check_id="IM1",
    )

    unparsable = build_world(tmp_path / "unparsable")
    _write_text(unparsable.map_lock_path, "schema: [unclosed\n", unparsable)
    _expect(
        unparsable,
        lambda: _select(unparsable),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_CORRUPT",
        check_id="IM1",
    )

    tampered = build_world(tmp_path / "tampered")
    tampered.tamper_yaml(tampered.map_lock_path, lambda p: p.__setitem__("lock_id", "other"))
    _expect(
        tampered,
        lambda: _select(tampered),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_CORRUPT",
        check_id="IM1",
    )

    unmirrored = build_world(tmp_path / "mirror")
    payload = unmirrored.read_yaml(unmirrored.registration_path)
    payload["identity_map_contract"]["active"]["lock_content_hash"] = "7" * 64
    payload["registration_content_hash"] = _canonical_hash(payload, "registration_content_hash")
    _write_yaml(unmirrored.registration_path, payload)
    unmirrored.seal()
    _expect(
        unmirrored,
        lambda: _select(unmirrored),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_CORRUPT",
        check_id="IM1",
    )


@requires_impl
def test_ps_m_003_stale_map_version_is_never_a_fallback(tmp_path: Path) -> None:
    """PS-M-003: a perfectly self-verifying but stale map version is IM1 MISMATCH."""

    def bump(payload: dict) -> None:
        payload["identity_map_contract"]["active"]["map_version"] = "2"
        payload["identity_map_contract"]["active"]["lock_version"] = "2"

    world = build_world(tmp_path)
    stored = world.read_yaml(world.map_lock_path)
    assert stored["lock_content_hash"] == _canonical_hash(stored, "lock_content_hash")
    payload = world.read_yaml(world.registration_path)
    bump(payload)
    payload["registration_content_hash"] = _canonical_hash(payload, "registration_content_hash")
    _write_yaml(world.registration_path, payload)
    world.seal()
    _expect(
        world,
        lambda: _select(world),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
        check_id="IM1",
    )


@requires_impl
def test_ps_m_004_lock_to_map_field_disagreements(tmp_path: Path) -> None:
    """PS-M-004: one failing case per bound lock<->map field, plus map self-hash."""

    mutations = {
        "map_id": lambda lock: lock.__setitem__("map_id", "other-map"),
        "map_content_hash": lambda lock: lock.__setitem__("map_content_hash", "1" * 64),
        "map_record_count": lambda lock: lock.__setitem__("map_record_count", 1),
        "raw_inventory_content_hash": lambda lock: lock.__setitem__("raw_inventory_content_hash", "2" * 64),
        "raw_inventory_record_count": lambda lock: lock.__setitem__("raw_inventory_record_count", 1),
        "response_bundle_hash": lambda lock: lock.__setitem__("response_bundle_hash", "3" * 64),
        "response_file_count": lambda lock: lock.__setitem__("response_file_count", 1),
        "response_byte_count": lambda lock: lock.__setitem__("response_byte_count", 1),
        "acquisition_tool_sha256": lambda lock: lock.__setitem__("acquisition_tool_sha256", "4" * 64),
    }
    for name, mutate in mutations.items():
        world = build_world(tmp_path / f"m4-{name}", on_map_lock=mutate)
        _expect(
            world,
            lambda w=world: _select(w),
            error="AtlasIdentityMapBindingError",
            code="IDENTITY_MAP_MISMATCH",
        )

    self_hash = build_world(tmp_path / "m4-self")
    self_hash.tamper_yaml(self_hash.map_path, lambda p: p.__setitem__("created_at", "2026-04-09T00:00:00Z"))
    _expect(
        self_hash,
        lambda: _select(self_hash),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )


@requires_impl
def test_ps_m_005_response_bundle_drift_is_detected_from_disk(tmp_path: Path) -> None:
    """PS-M-005: flipped byte, missing file, extra file and tool edit all fail IM3."""

    flipped = build_world(tmp_path / "flip")
    target = sorted(flipped.response_root.rglob("*.json"))[0]
    payload = target.read_bytes().replace(b"9000", b"9900", 1)
    assert payload != target.read_bytes(), "fixture failed to alter a response byte"
    target.write_bytes(payload)
    flipped._baseline[target] = payload
    _expect(
        flipped,
        lambda: _select(flipped),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )

    removed = build_world(tmp_path / "missing")
    victim = sorted(removed.response_root.rglob("summary/*/*.json"))[0]
    victim.unlink()
    removed._baseline.pop(victim, None)
    _expect(
        removed,
        lambda: _select(removed),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )

    extra = build_world(tmp_path / "extra")
    intruder = extra.response_root / "search" / "unexpected.json"
    intruder.write_text("{}", encoding="utf-8")
    extra._baseline[intruder] = intruder.read_bytes()
    _expect(
        extra,
        lambda: _select(extra),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )

    tool = build_world(tmp_path / "tool")
    tool_path = tool.response_root / "acquisition-tool.py"
    tool_path.write_text("# synthetic acquisition tool (edited)\n", encoding="utf-8")
    tool._baseline[tool_path] = tool_path.read_bytes()
    _expect(
        tool,
        lambda: _select(tool),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )


@requires_impl
def test_ps_m_006_map_pack_and_reference_binding(tmp_path: Path) -> None:
    """PS-M-006: pack drift and reference-pin drift both fail IM4."""

    pack_drift = build_world(
        tmp_path / "pack",
        on_map=lambda m: m["pack_binding"].__setitem__("pack_content_hash", "5" * 64),
    )
    _expect(pack_drift, lambda: _select(pack_drift), error="AtlasPanelError")

    assembly = build_world(
        tmp_path / "assembly",
        on_map=lambda m: m["reference_binding"].__setitem__("assembly", "SYNASM9"),
    )
    _expect(
        assembly,
        lambda: _select(assembly),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )

    transcript = build_world(
        tmp_path / "transcript",
        on_map=lambda m: m["reference_binding"].__setitem__("transcript", "SYN_TX9999.9"),
    )
    _expect(
        transcript,
        lambda: _select(transcript),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
    )

    asserted_protein = build_world(
        tmp_path / "protein",
        on_map=lambda m: m["reference_binding"].__setitem__("protein", "SYN_PR9999.9"),
    )
    _expect(asserted_protein, lambda: _select(asserted_protein), error="AtlasPanelError")


@requires_impl
def test_ps_m_007_map_to_raw_bijection(tmp_path: Path) -> None:
    """PS-M-007: count drift, one-character raw drift and non-bijection fail IM5."""

    def drop_raw_row(raw: dict) -> None:
        raw["rows"] = raw["rows"][:-1]
        raw["record_count"] = len(raw["rows"])

    count = build_world(tmp_path / "count", on_raw=drop_raw_row)
    _expect(count, lambda: _select(count), error="AtlasPanelError")

    def bend_one_character(raw: dict) -> None:
        raw["rows"][0]["raw_identity_string"] = raw["rows"][0]["raw_identity_string"] + "z"

    drift = build_world(tmp_path / "drift", on_raw=bend_one_character)
    _expect(drift, lambda: _select(drift), error="AtlasPanelError")

    def duplicate_id(raw: dict) -> None:
        raw["rows"][1]["raw_record_id"] = raw["rows"][0]["raw_record_id"]

    dupe = build_world(tmp_path / "dupe", on_raw=duplicate_id)
    _expect(dupe, lambda: _select(dupe), error="AtlasPanelError")


@requires_impl
def test_ps_m_008_universe_lock_identity_map_binding(tmp_path: Path) -> None:
    """PS-M-008: IM6 field drift and a v>=3 lock with no binding both fail."""

    mutations = [
        lambda lock: lock["identity_map_binding"].__setitem__("map_content_hash", "6" * 64),
        lambda lock: lock["identity_map_binding"].__setitem__("schema", "invalid.schema"),
        lambda lock: lock["identity_map_binding"].__setitem__("map_id", "invalid-map-id"),
        lambda lock: lock["identity_map_binding"].__setitem__("lock_id", "invalid-lock-id"),
        lambda lock: lock["identity_map_binding"]["pack_binding"].__setitem__("pack_version", "invalid-version"),
    ]

    for i, mutation in enumerate(mutations):
        drift = build_world(tmp_path / f"drift_{i}", on_universe_lock=mutation)
        _expect(
            drift,
            lambda: _select(drift),
            error="AtlasIdentityMapBindingError",
            code="IDENTITY_MAP_MISMATCH",
            check_id="IM6",
        )

    absent = build_world(
        tmp_path / "absent",
        on_universe_lock=lambda lock: lock.pop("identity_map_binding"),
    )
    assert absent.universe_lock["universe_version"] >= 3
    _expect(
        absent,
        lambda: _select(absent),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_MISMATCH",
        check_id="IM6",
    )


@requires_impl
def test_ps_m_009_mapper_fault_never_becomes_a_candidate_property(tmp_path: Path) -> None:
    """PS-M-009 CRITICAL FALSE-GREEN: a missing map lock is a tool failure, not data."""

    world = build_world(tmp_path)
    world.map_lock_path.unlink()
    world._baseline.pop(world.map_lock_path, None)
    before = world.snapshot()
    error = _expect(
        world,
        lambda: _select(world),
        error="AtlasIdentityMapBindingError",
        code="IDENTITY_MAP_LOCK_MISSING",
    )
    assert world.snapshot() == before, "a mapper fault must not write anything"
    text = str(error)
    assert "unresolved" not in text.lower()
    assert "out_of_scope" not in text.lower()
    assert "INFEASIBLE" not in text
    run_records = [p for p in world.root.rglob("*.json") if "responses" not in p.parts]
    assert run_records == [], f"a run record was written despite a tool failure: {run_records}"


@requires_impl
def test_ps_m_010_identity_map_verified_before_replay(tmp_path: Path) -> None:
    """PS-M-010 ORDER: with IM2 and RP4 both broken, replay is never reached."""

    calls: list[str] = []
    world = build_world(
        tmp_path,
        on_map_lock=lambda lock: lock.__setitem__("map_content_hash", "8" * 64),
        on_universe=lambda u: u["records"][0].__setitem__("residue_index", 4242),
    )
    original = _sut("replay_normalization")

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append("replay")
        return original(*args, **kwargs)

    assert _panel is not None
    setattr(_panel, "replay_normalization", spy)
    try:
        _expect(
            world,
            lambda: _select(world),
            error="AtlasIdentityMapBindingError",
            code="IDENTITY_MAP_MISMATCH",
        )
    finally:
        setattr(_panel, "replay_normalization", original)
    assert calls == [], "replay_normalization ran before the identity map was verified"


# ---------------------------------------------------------------------------
# PS-U-* conservation (U1-U6)
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_u_001_raw_inventory_hash_and_count(tmp_path: Path) -> None:
    """PS-U-001: raw inventory digest or record_count drift is a contract breach."""

    digest = build_world(
        tmp_path / "digest",
        on_universe=lambda u: u["raw_inventory"].__setitem__("content_hash", "a" * 64),
    )
    _expect(
        digest,
        lambda: _select(digest),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U1",
    )

    count = build_world(tmp_path / "count")
    count.tamper_yaml(count.raw_inventory_path, lambda p: p.__setitem__("record_count", 999))
    _expect(count, lambda: _select(count), error="AtlasPanelError")


@requires_impl
def test_ps_u_002_ledger_is_a_bijection_onto_raw_rows(tmp_path: Path) -> None:
    """PS-U-002: short ledger, duplicate raw_record_id and non-bijection all fail U2."""

    short = build_world(tmp_path / "short", on_ledger=lambda rows: rows.pop())
    _expect(
        short,
        lambda: _select(short),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U2",
    )

    def duplicate(rows: list) -> None:
        rows[1]["raw_record_id"] = rows[0]["raw_record_id"]

    dupe = build_world(tmp_path / "dupe", on_ledger=duplicate)
    _expect(
        dupe,
        lambda: _select(dupe),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )

    def unknown_row(rows: list) -> None:
        rows[0]["raw_record_id"] = "raw-not-in-inventory"

    orphan = build_world(tmp_path / "orphan", on_ledger=unknown_row)
    _expect(
        orphan,
        lambda: _select(orphan),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


@requires_impl
def test_ps_u_003_ledger_key_set_equals_record_key_set(tmp_path: Path) -> None:
    """PS-U-003: key-set divergence and two records per key both fail U3."""

    def rekey(rows: list) -> None:
        rows[0]["universe_key"] = "UNRESOLVED:" + "a" * 64

    diverged = build_world(tmp_path / "diverged", on_ledger=rekey)
    _expect(
        diverged,
        lambda: _select(diverged),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U3",
    )

    def collide(universe: dict) -> None:
        universe["records"][1]["universe_key"] = universe["records"][0]["universe_key"]

    collided = build_world(tmp_path / "collided", on_universe=collide)
    _expect(
        collided,
        lambda: _select(collided),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


@requires_impl
def test_ps_u_004_discovery_commitment_over_sorted_distinct_keys(tmp_path: Path) -> None:
    """PS-U-004: the commitment is over sorted DISTINCT keys joined by newline."""

    world = build_world(tmp_path / "ok")
    keys = [r["universe_key"] for r in world.universe["records"]]
    expected_count, expected_hash = _discovery_commitment(keys)
    assert world.universe["discovery_set_commitment"]["discovery_set_hash"] == expected_hash
    assert expected_hash == _sha256_text("\n".join(sorted(set(keys))))
    report = _preconditions(world)
    assert getattr(report, "verified_discovery_set_hash") == expected_hash
    assert getattr(report, "verified_discovery_set_count") == expected_count

    drifted = build_world(
        tmp_path / "drift",
        on_universe=lambda u: u["discovery_set_commitment"].__setitem__("discovery_set_count", 1),
    )
    _expect(
        drifted,
        lambda: _select(drifted),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U4",
    )


@requires_impl
def test_ps_u_005_universe_self_hash_and_attestation(tmp_path: Path) -> None:
    """PS-U-005: stale universe self-hash fails U5; a roleless attestation fails U6."""

    stale = build_world(tmp_path / "stale")
    stale.tamper_yaml(stale.universe_path, lambda p: p.__setitem__("universe_id", "other"))
    _expect(
        stale,
        lambda: _select(stale),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U5",
    )

    roleless = build_world(
        tmp_path / "roleless",
        on_universe=lambda u: u["completeness_attestation"].pop("attesting_role"),
    )
    _expect(
        roleless,
        lambda: _select(roleless),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="U6",
    )

    absent = build_world(
        tmp_path / "absent", on_universe=lambda u: u.pop("completeness_attestation")
    )
    _expect(absent, lambda: _select(absent), error="AtlasUniverseContractError")


@requires_impl
def test_ps_u_006_prohibited_universe_content(tmp_path: Path) -> None:
    """PS-U-006: section 4.4 prohibited fields are rejected even when hashes verify."""

    prohibited = {
        "effect_size": 0.5,
        "score": 12,
        "p_value": 0.01,
        "ranking": 1,
        "promising": True,
    }
    for field, value in prohibited.items():
        world = build_world(
            tmp_path / f"u6-{field}",
            on_universe=lambda u, f=field, v=value: u["records"][0].__setitem__(f, v),
        )
        stored = world.read_yaml(world.universe_path)
        assert stored["universe_content_hash"] == _canonical_hash(stored, "universe_content_hash")
        error = _expect(
            world,
            lambda w=world: _select(w),
            error="AtlasUniverseContractError",
            code="UNIVERSE_CONTRACT_BREACH",
        )
        assert "4.4" in str(error) or field in str(error)


# ---------------------------------------------------------------------------
# PS-R-* normalization/admission replay (U7 -> RP1-RP7)
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_r_001_replayed_outcome_must_equal_ledger(tmp_path: Path) -> None:
    """PS-R-001: an outcome the mapper does not reproduce fails RP1 by raw_record_id."""

    def flip(rows: list) -> None:
        rows[0]["normalization_outcome"] = "collapsed_duplicate"

    world = build_world(tmp_path, on_ledger=flip)
    offender = world.ledger_rows[0]["raw_record_id"]
    error = _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP1",
    )
    assert offender in str(error), f"RP1 must name the offending raw_record_id {offender!r}"


@requires_impl
def test_ps_r_002_surrogate_key_normalization_has_no_case_fold(tmp_path: Path) -> None:
    """PS-R-002: the UNRESOLVED surrogate uses NFC+strip+collapse and NEVER case-folds."""

    spaced = "  synraw.MiXeD\tCase \n"
    assert _raw_identity_normalized(spaced) == "synraw.MiXeD Case"
    assert _raw_identity_normalized(spaced) != _raw_identity_normalized(spaced.lower())
    key = _universe_key(identity_state="unresolved", spdi_canonical=None, raw_identity_string=spaced)
    assert key == "UNRESOLVED:" + _sha256_text("synraw.MiXeD Case")
    assert _sut("raw_identity_normalized")(spaced) == "synraw.MiXeD Case"
    assert (
        _sut("universe_key")(
            identity_state="unresolved", spdi_canonical=None, raw_identity_string=spaced
        )
        == key
    )

    def rekey(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["identity_state"] == "unresolved")
        record["universe_key"] = "UNRESOLVED:" + _sha256_text("synraw.mixed case")

    world = build_world(tmp_path, on_universe=rekey)
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


@requires_impl
def test_ps_r_003_identity_state_is_confirmed_in_both_directions(tmp_path: Path) -> None:
    """PS-R-003: declared-resolved that cannot admit AND declared-unresolved that can."""

    def declare_resolved(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["identity_state"] == "unresolved")
        record["identity_state"] = "resolved"
        record["spdi_canonical"] = _syn_spdi(77)

    forced = build_world(tmp_path / "forced", on_universe=declare_resolved)
    _expect(
        forced,
        lambda: _select(forced),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP3",
    )

    def declare_unresolved(universe: dict) -> None:
        record = universe["records"][0]
        record["identity_state"] = "unresolved"

    denied = build_world(tmp_path / "denied", on_universe=declare_unresolved)
    _expect(
        denied,
        lambda: _select(denied),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP3",
    )


@requires_impl
def test_ps_r_004_identity_fields_are_character_identical(tmp_path: Path) -> None:
    """PS-R-004: any identity field differing after text_norm fails RP4."""

    mutations = {
        "spdi_canonical": lambda u: u["records"][0].__setitem__("spdi_canonical", _syn_spdi(88)),
        "hgvs_c": lambda u: u["records"][0].__setitem__("hgvs_c", f"{SYN_TRANSCRIPT}:c.{999}A>G"),
        "hgvs_p": lambda u: u["records"][0].__setitem__("hgvs_p", f"{SYN_PROTEIN}:p.Lys{888}Glu"),
        "transcript_pin": lambda u: u.__setitem__("transcript_pin", "SYN_TX0009.9"),
        "residue_index": lambda u: u["records"][0].__setitem__("residue_index", 88),
        "codon_index": lambda u: u["records"][0].__setitem__("codon_index", 88),
    }
    for name, mutate in mutations.items():
        world = build_world(
            tmp_path / f"rp4-{name}",
            on_universe=mutate,
        )
        _expect(
            world,
            lambda w=world: _select(w),
            error="AtlasUniverseContractError",
            code="UNIVERSE_CONTRACT_BREACH",
        )


@requires_impl
def test_ps_r_005_consequence_and_scope_come_from_the_map(tmp_path: Path) -> None:
    """PS-R-005: declared consequence/scope that the replay does not derive fails RP5."""

    consequence = build_world(
        tmp_path / "consequence",
        on_universe=lambda u: u["records"][0].__setitem__("consequence_class", "synthetic_other"),
    )
    _expect(
        consequence,
        lambda: _select(consequence),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP5",
    )

    map_side = build_world(
        tmp_path / "mapside",
        on_map=lambda m: m["records"][0].__setitem__("consequence_class", "synthetic_other"),
    )
    _expect(map_side, lambda: _select(map_side), error="AtlasPanelError")


@requires_impl
def test_ps_r_006_undecidable_mapper_is_a_tool_failure(tmp_path: Path) -> None:
    """PS-R-006 ADVERSARIAL: a raw row the map cannot answer stops the run."""

    def drop_map_record(manifest: dict) -> None:
        manifest["records"] = manifest["records"][:-1]

    world = build_world(tmp_path, on_map=drop_map_record)
    error = _expect(world, lambda: _select(world), error="AtlasPanelError")
    text = str(error)
    assert "X1" not in text, "an unanswerable row must not be recorded as X1"
    assert "out_of_scope" not in text


@requires_impl
def test_ps_r_007_exclusion_flags_and_duplicate_collapse(tmp_path: Path) -> None:
    """PS-R-007: declared exclusion_flags drift fails RP6; collapse is stable (RP7)."""

    def wrong_flags(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["identity_state"] == "unresolved")
        record["exclusion_flags"] = ["X8"]

    flags = build_world(tmp_path / "flags", on_universe=wrong_flags)
    _expect(
        flags,
        lambda: _select(flags),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP6",
    )

    def spurious_flags(universe: dict) -> None:
        universe["records"][0]["exclusion_flags"] = ["X2"]

    spurious = build_world(tmp_path / "spurious", on_universe=spurious_flags)
    _expect(
        spurious,
        lambda: _select(spurious),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP6",
    )

    def setup_anchors(raw_records: list) -> None:
        r1 = raw_records[0]
        r1["_residue"] = 61
        r1["_spdi_position"] = 61
        r1["spdi_canonical"] = _syn_spdi(61)
        r1["hgvs_c"] = f"{SYN_TRANSCRIPT}:c.{3 * 61 - 2}A>G"
        r1["hgvs_p"] = f"{SYN_PROTEIN}:p.Lys{61}Glu"
        r1["_raw_identity_string"] = f"p.Lys{61}Glu"
        r1["residue_index"] = 61
        r1["codon_index"] = 61
        
        r2 = raw_records[1]
        r2["_residue"] = 61
        r2["_spdi_position"] = 61
        r2["_mock_spdi"] = _syn_spdi(61, alt="C")
        r2["spdi_canonical"] = _syn_spdi(61, alt="C")
        r2["hgvs_c"] = f"{SYN_TRANSCRIPT}:c.{3 * 61 - 2}A>G"
        r2["hgvs_p"] = f"{SYN_PROTEIN}:p.Lys{61}Glu"
        r2["_raw_identity_string"] = f"p.Lys{61}Glu"
        r2["residue_index"] = 61
        r2["codon_index"] = 61

    def flags_anchors(universe: dict) -> None:
        r1 = universe["records"][0]
        r1["exclusion_flags"] = ["X3"]

        r2 = universe["records"][1]
        r2["exclusion_flags"] = ["X3"]

    anchors = build_world(
        tmp_path / "anchors",
        on_records=setup_anchors,
        on_universe=flags_anchors,
    )
    AnchorSpec = _sut("AnchorSpec")
    matching_anchor = AnchorSpec(spdi_canonical=_syn_spdi(61), residue_index=61)
    map_bytes_before = anchors.map_path.read_bytes()
    _select(anchors, anchor=matching_anchor)
    assert anchors.map_path.read_bytes() == map_bytes_before

    different_anchor = AnchorSpec(spdi_canonical=_syn_spdi(99), residue_index=99)
    _expect(
        anchors,
        lambda: _select(anchors, anchor=different_anchor),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
        check_id="RP6",
    )
    assert anchors.map_path.read_bytes() == map_bytes_before

    def conflict_universe(universe: dict) -> None:
        r1 = universe["records"][0]
        # X1 would match the effective_exclusion_code if the conflict guard were missing
        r1["exclusion_flags"] = ["X1"]

    conflict_world = build_world(
        tmp_path / "conflict",
        on_records=setup_anchors,
        on_universe=conflict_universe,
    )

    class ConflictMapper:
        def __init__(self, real_mapper):
            self.real_mapper = real_mapper

        def replay(self, raw_record_id: str, *args, **kwargs):
            base_replay = self.real_mapper.replay(raw_record_id, *args, **kwargs)
            if raw_record_id == "raw-rec-a":
                # Inject a mapper-owned exclusion_code into a resolved replay
                object.__setattr__(base_replay, "exclusion_code", "X1")
            return base_replay

    inputs = conflict_world.inputs(anchor=matching_anchor)
    _, _, universe, raw_manifest, pack, real_mapper = _sut("_run_preconditions")(inputs)

    replay_normalization = _sut("replay_normalization")
    AtlasUniverseContractError = _sut("AtlasUniverseContractError")
    
    with pytest.raises(AtlasUniverseContractError) as excinfo:
        replay_normalization(
            raw_manifest, universe, pack=pack,
            mapper=ConflictMapper(real_mapper), anchor=matching_anchor
        )
    
    raised = excinfo.value
    assert getattr(raised, "code", "") == "UNIVERSE_CONTRACT_BREACH"
    assert getattr(raised, "check_id", "") == "RP6"
    assert "conflicts with the anchor-derived exclusion 'X3'" in str(raised)

    stable = build_world(tmp_path / "stable")
    first = _preconditions(stable)
    second = _preconditions(stable)
    assert getattr(first, "verified_discovery_set_count") == getattr(
        second, "verified_discovery_set_count"
    )


@requires_impl
def test_ps_r_008_replay_mismatch_is_reported_never_repaired(tmp_path: Path) -> None:
    """PS-R-008: universe bytes are identical after a failing replay."""

    world = build_world(
        tmp_path, on_universe=lambda u: u["records"][0].__setitem__("residue_index", 4321)
    )
    before = world.universe_path.read_bytes()
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )
    assert world.universe_path.read_bytes() == before, "the universe file was repaired in place"


@requires_impl
def test_ps_r_009_replay_uses_the_map_not_the_universe(tmp_path: Path) -> None:
    """PS-R-009 CRITICAL FALSE-GREEN: map and universe disagree; the map wins.

    The universe is left entirely self-consistent (its own hash, ledger and
    commitment all recompute), and ONLY the pinned map's replay tuple is moved.
    An implementation that echoed the universe's declared fields back at itself
    would see no disagreement at all and would pass vacuously.
    """

    def bend_map(manifest: dict) -> None:
        manifest["records"][0]["residue_index"] = 4242
        manifest["records"][0]["codon_index"] = 4242

    world = build_world(tmp_path, on_map=bend_map)
    stored = world.read_yaml(world.universe_path)
    assert stored["universe_content_hash"] == _canonical_hash(stored, "universe_content_hash")
    assert stored["records"][0]["residue_index"] != 4242
    offender = world.map_manifest["records"][0]["raw_record_id"]
    error = _expect(world, lambda: _select(world), error="AtlasPanelError")
    assert offender in str(error), f"the replay failure must name {offender!r}"


# ---------------------------------------------------------------------------
# PS-S-* strata determination and the metadata firewall
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_s_001_each_stratum_fires_from_primitives(tmp_path: Path) -> None:
    """PS-S-001: S1..S6 fire from primitives; S4 needs same context, S5 differing."""

    recompute = _sut("recompute_all_matched_strata")
    cases = {
        "S6": (False, []),
        "S1": (True, [_obs("o1", bucket="substantial_deviation")]),
        "S2": (True, [_obs("o1", bucket="intermediate_deviation")]),
        "S3": (True, [_obs("o1", bucket="near_reference")]),
        "S4": (
            True,
            [
                _obs("o1", bucket="substantial_deviation"),
                _obs("o2", bucket="near_reference"),
            ],
        ),
        "S5": (
            True,
            [
                _obs("o1", bucket="substantial_deviation", model=SYN_MODELS[0]),
                _obs("o2", bucket="near_reference", model=SYN_MODELS[1]),
            ],
        ),
    }
    for stratum, (present, observations) in cases.items():
        record = {"functional_evidence_present": present, "observations": observations}
        matched = tuple(recompute(record, omega=OMEGA))
        assert stratum in matched, f"{stratum} did not fire for {matched}"
        assert matched == _matched_strata(present, observations)
    s4 = tuple(recompute({"functional_evidence_present": True, "observations": cases["S4"][1]}, omega=OMEGA))
    s5 = tuple(recompute({"functional_evidence_present": True, "observations": cases["S5"][1]}, omega=OMEGA))
    assert "S5" not in s4 and "S4" not in s5


@requires_impl
def test_ps_s_002_substantial_versus_intermediate_is_a_differing_pair(tmp_path: Path) -> None:
    """PS-S-002: graded differences route conservatively into the contested strata."""

    observations = [
        _obs("o1", bucket="substantial_deviation"),
        _obs("o2", bucket="intermediate_deviation"),
    ]
    matched = tuple(
        _sut("recompute_all_matched_strata")(
            {"functional_evidence_present": True, "observations": observations}, omega=OMEGA
        )
    )
    assert "S4" in matched, matched
    assert _matched_strata(True, observations) == matched


@requires_impl
def test_ps_s_003_all_matched_is_emitted_in_omega_order(tmp_path: Path) -> None:
    """PS-S-003: multi-stratum matching is normal and ordered by registration Omega."""

    observations = [
        _obs("o1", bucket="substantial_deviation"),
        _obs("o2", bucket="intermediate_deviation"),
        _obs("o3", bucket="near_reference", model=SYN_MODELS[1]),
    ]
    matched = tuple(
        _sut("recompute_all_matched_strata")(
            {"functional_evidence_present": True, "observations": observations}, omega=OMEGA
        )
    )
    assert len(matched) > 1
    assert list(matched) == [s for s in OMEGA if s in matched]
    assert matched == _matched_strata(True, observations)


@requires_impl
def test_ps_s_004_primary_is_the_first_element_under_omega(tmp_path: Path) -> None:
    """PS-S-004: primary_stratum is Omega-first; there is no discretionary rule."""

    recompute = _sut("recompute_primary_stratum")
    assert recompute(["S1", "S2", "S4"]) == "S4"
    assert recompute(["S3", "S1"]) == "S3"
    assert recompute(["S6"]) == "S6"
    assert recompute(list(reversed(OMEGA))) == OMEGA[0]
    for subset_size in (1, 2, 3):
        for subset in itertools.combinations(OMEGA, subset_size):
            assert recompute(list(reversed(subset))) == _primary_stratum(subset)


@requires_impl
def test_ps_s_005_declared_primary_is_only_a_comparand(tmp_path: Path) -> None:
    """PS-S-005: a flipped declared primary_stratum is a breach, never an input."""

    world = build_world(
        tmp_path, on_universe=lambda u: u["records"][0].__setitem__("primary_stratum", "S6")
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


@requires_impl
def test_ps_s_006_firewall_fields_are_structurally_unreachable(tmp_path: Path) -> None:
    """PS-S-006 ADVERSARIAL: firewall fields change no stratum and are not parameters."""

    recompute = _sut("recompute_all_matched_strata")
    parameters = set(inspect.signature(recompute).parameters)
    for forbidden in ("spec_stratum", "spec_stratum_basis", "access_status", "license_family", "span_verifiable"):
        assert forbidden not in parameters, f"{forbidden} must not be a stratum-function parameter"

    observations = [_obs("o1", bucket="substantial_deviation")]
    base = tuple(recompute({"functional_evidence_present": True, "observations": observations}, omega=OMEGA))
    poisoned_obs = [dict(observations[0], access_status="restricted", license_family="synlicense_closed", span_verifiable=False)]
    poisoned = tuple(
        recompute(
            {
                "functional_evidence_present": True,
                "observations": poisoned_obs,
                "spec_stratum": "known_benign",
                "spec_stratum_basis": "synthetic",
            },
            omega=OMEGA,
        )
    )
    assert poisoned == base, "a firewall field altered the recomputed strata"


@requires_impl
def test_ps_s_007_evidence_presence_must_match_observations(tmp_path: Path) -> None:
    """PS-S-007: true-with-zero and false-with-many are both contract breaches."""

    def true_without(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["record_id"] == "rec-d")
        record["functional_evidence_present"] = True

    empty = build_world(tmp_path / "empty", on_universe=true_without)
    _expect(
        empty,
        lambda: _select(empty),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )

    def false_with(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["record_id"] == "rec-a")
        record["functional_evidence_present"] = False

    populated = build_world(tmp_path / "populated", on_universe=false_with)
    _expect(
        populated,
        lambda: _select(populated),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


# ---------------------------------------------------------------------------
# PS-L-* lineage recomputation
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_l_001_each_edge_rule_forms_a_component(tmp_path: Path) -> None:
    """PS-L-001: L1..L6 each join observations; the key is the declared digest."""

    edge_cases = {
        "L1": (
            _obs("o1", sources=("ACCESSION:SYN-1",), dataset_accession="SYNDS-1", lab="lab-1", protocol_lineage="p-1"),
            _obs("o2", sources=("ACCESSION:SYN-2",), dataset_accession="SYNDS-1", lab="lab-2", protocol_lineage="p-2"),
        ),
        "L2": (
            _obs("o1", sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="p-1"),
            _obs("o2", sources=("ACCESSION:SYN-2",), version_of="ACCESSION:SYN-1", lab="lab-2", protocol_lineage="p-2"),
        ),
        "L3": (
            _obs("o1", sources=("ACCESSION:SYN-1",), program="SYNPROG-1", lab="lab-1", protocol_lineage="p-1"),
            _obs("o2", sources=("ACCESSION:SYN-2",), program="SYNPROG-1", lab="lab-2", protocol_lineage="p-2"),
        ),
        "L4": (
            _obs("o1", sources=("ACCESSION:SYN-1",), lab="lab-x", protocol_lineage="proto-x"),
            _obs("o2", sources=("ACCESSION:SYN-2",), lab="lab-x", protocol_lineage="proto-x"),
        ),
        "L5": (
            _obs("o1", sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="p-1"),
            _obs("o2", sources=("ACCESSION:SYN-2",), derived_from=("o1",), lab="lab-2", protocol_lineage="p-2"),
        ),
        "L6": (
            _obs("o1", sources=("ACCESSION:SYN-9",), lab="lab-1", protocol_lineage="p-1"),
            _obs("o2", sources=("ACCESSION:SYN-9",), lab="lab-2", protocol_lineage="p-2"),
        ),
    }
    build_index = _sut("recompute_lineage_index")
    for rule, pair in edge_cases.items():
        universe = {"records": [{"record_id": "r1", "observations": list(pair)}]}
        index = build_index(universe)
        mapping = dict(getattr(index, "group_of_observation"))
        assert mapping["o1"] == mapping["o2"], f"{rule} failed to join the pair"
        identifiers = set(pair[0]["source_identifiers"]) | set(pair[1]["source_identifiers"])
        assert mapping["o1"] == _lineage_group_key(identifiers)

    separate = {
        "records": [
            {
                "record_id": "r1",
                "observations": [
                    _obs("a1", sources=("ACCESSION:SYN-A",), lab="lab-a", protocol_lineage="proto-a"),
                    _obs("a2", sources=("ACCESSION:SYN-B",), lab="lab-b", protocol_lineage="proto-b"),
                ],
            }
        ]
    }
    mapping = dict(getattr(build_index(separate), "group_of_observation"))
    assert mapping["a1"] != mapping["a2"], "unrelated observations must not be merged"


@requires_impl
def test_ps_l_002_group_key_is_stable_under_renaming_and_reordering(tmp_path: Path) -> None:
    """PS-L-002: keys survive custodian-id renaming and observation reordering."""

    build_index = _sut("recompute_lineage_index")
    observations = [
        _obs("o1", sources=("ACCESSION:SYN-A",), lab="lab-a", protocol_lineage="proto-a", program="prog-a"),
        _obs("o2", sources=("ACCESSION:SYN-A", "ACCESSION:SYN-B"), lab="lab-a", protocol_lineage="proto-a"),
    ]
    baseline = dict(getattr(build_index({"records": [{"record_id": "r", "observations": observations}]}), "group_of_observation"))

    renamed = [dict(o, lab_lineage_key="renamed-lab", assay_protocol_lineage_key="renamed-proto") for o in observations]
    renamed_index = dict(getattr(build_index({"records": [{"record_id": "r", "observations": renamed}]}), "group_of_observation"))
    assert set(renamed_index.values()) == set(baseline.values())

    reordered = list(reversed(observations))
    reordered_index = dict(getattr(build_index({"records": [{"record_id": "r", "observations": reordered}]}), "group_of_observation"))
    assert reordered_index == baseline


@requires_impl
def test_ps_l_003_unknown_lineage_pools_into_one_group(tmp_path: Path) -> None:
    """PS-L-003 ADVERSARIAL: unknowns never count as two independent groups."""

    build_index = _sut("recompute_lineage_index")
    observations = [
        _obs("u1", sources=("ACCESSION:SYN-U1",), lab="unknown", protocol_lineage="proto-1"),
        _obs("u2", sources=("ACCESSION:SYN-U2",), lab="lab-2", protocol_lineage="unknown"),
    ]
    index = build_index({"records": [{"record_id": "r", "observations": observations}]})
    mapping = dict(getattr(index, "group_of_observation"))
    assert mapping["u1"] == "LG:UNKNOWN-POOL"
    assert mapping["u2"] == "LG:UNKNOWN-POOL"
    assert len(set(mapping.values())) == 1
    assert getattr(index, "unknown_observation_count") == 2
    assert dict(getattr(index, "group_confidence"))["LG:UNKNOWN-POOL"] == "unknown"


@requires_impl
def test_ps_l_004_declared_groups_are_only_comparands(tmp_path: Path) -> None:
    """PS-L-004: declared support_source_groups that differ are a contract breach."""

    world = build_world(
        tmp_path,
        on_universe=lambda u: u["records"][0].__setitem__("support_source_groups", ["LG:0000000000000000"]),
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


@requires_impl
def test_ps_l_005_support_class_recomputes_across_all_five_values(tmp_path: Path) -> None:
    """PS-L-005: every section 14.1 value is reachable from primitives alone."""

    recompute = _sut("recompute_support_class")
    build_index = _sut("recompute_lineage_index")
    cases = {
        "evidence_absent": [],
        "single_low_throughput": [
            _obs("s1", sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="proto-1"),
        ],
        "single_high_throughput_only": [
            _obs("h1", sources=("ACCESSION:SYN-1",), throughput="high_throughput", lab="lab-1", protocol_lineage="proto-1"),
        ],
        "multi_independent": [
            _obs("m1", sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="proto-1"),
            _obs("m2", sources=("ACCESSION:SYN-2",), lab="lab-2", protocol_lineage="proto-2"),
        ],
        "access_blocked": [
            _obs("b1", sources=("ACCESSION:SYN-1",), access="restricted", span_verifiable=False, lab="lab-1", protocol_lineage="proto-1"),
        ],
    }
    for expected, observations in cases.items():
        record = {
            "record_id": f"rec-{expected}",
            "functional_evidence_present": bool(observations),
            "observations": observations,
        }
        index = build_index({"records": [record]})
        assert recompute(record, lineage=index) == expected
        local_index = _lineage_index(observations)
        assert _support_class(record, local_index) == expected

    world = build_world(
        tmp_path, on_universe=lambda u: u["records"][0].__setitem__("support_class", "multi_independent")
    )
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


# ---------------------------------------------------------------------------
# Extra synthetic pools used by the search/outcome suites
# ---------------------------------------------------------------------------


def _last_branch_records() -> list[dict[str, Any]]:
    """A pool whose ONLY valid panel lives in the FINAL allocation branch.

    Three ``S6`` members carry three distinct ``spec_stratum`` values, so C5
    can only be satisfied by taking all three -- which forces the most
    imbalanced allocation ``(S6=3, S2=1, S1=1)``, the LAST vector under the
    declared ``(max ascending, then lexicographic)`` order. Within that branch
    only ``b1``/``a1`` reach three established lineage groups and three assay
    kinds. The test proves both facts with the independent oracle before it
    asserts anything about the implementation.
    """

    return [
        _rec("rec-d1", residue=21, spec_stratum="known_pathogenic", observations=[]),
        _rec("rec-d2", residue=22, spec_stratum="known_benign", observations=[]),
        _rec("rec-d3", residue=23, spec_stratum="vus_without_functional_evidence", observations=[]),
        _rec(
            "rec-b1",
            residue=24,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-b1a", bucket="intermediate_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="proto-1"),
                _obs("obs-b1b", bucket="intermediate_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-2",), lab="lab-2", protocol_lineage="proto-2"),
            ],
        ),
        _rec(
            "rec-b2",
            residue=25,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-b2a", bucket="intermediate_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="proto-1"),
            ],
        ),
        _rec(
            "rec-a1",
            residue=26,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-a1a", bucket="substantial_deviation", assay=SYN_ASSAYS[2], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-3",), lab="lab-3", protocol_lineage="proto-3"),
                _obs("obs-a1b", bucket="substantial_deviation", assay=SYN_ASSAYS[3], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-3",), lab="lab-3", protocol_lineage="proto-3"),
            ],
        ),
        _rec(
            "rec-a2",
            residue=27,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-a2a", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-1",), lab="lab-1", protocol_lineage="proto-1"),
            ],
        ),
    ]


def _single_assay_records() -> list[dict[str, Any]]:
    """A pool that can NEVER satisfy D1 (one assay kind), at any ladder level."""

    records = []
    for offset, bucket in enumerate(
        ("substantial_deviation", "intermediate_deviation", "near_reference",
         "substantial_deviation", "intermediate_deviation")
    ):
        records.append(
            _rec(
                f"rec-s{offset}",
                residue=41 + offset,
                spec_stratum="conflicting",
                observations=[
                    _obs(
                        f"obs-s{offset}",
                        bucket=bucket,
                        assay=SYN_ASSAYS[0],
                        model=SYN_MODELS[0],
                        sources=(f"ACCESSION:SYN-S{offset}",),
                        lab=f"lab-s{offset}",
                        protocol_lineage=f"proto-s{offset}",
                    )
                ],
            )
        )
    records.append(_rec("rec-s6", residue=51, spec_stratum="conflicting", observations=[]))
    return records


def _collision_records() -> list[dict[str, Any]]:
    """Two eligible records share residue/codon 31 at DIFFERENT genomic positions.

    Hand-derived: K = 4 (S1, S2, S3, S6) so ``N_target = 6``; six records are
    eligible but ``rec-x1``/``rec-x2`` are mutually exclusive under section 17.7,
    so no six-member panel exists and the run must settle for a FIVE-member
    panel at level L0 rather than relax.  Exactly one of the two colliding
    records may appear, and it must be the one with the lower draw key.
    """

    return [
        _rec(
            "rec-x1",
            residue=31,
            spdi_position=131,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-x1", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-X1",), lab="lab-x1", protocol_lineage="proto-x1"),
            ],
        ),
        _rec(
            "rec-x2",
            residue=31,
            spdi_position=132,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-x2", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-X2",), lab="lab-x2", protocol_lineage="proto-x2"),
            ],
        ),
        _rec(
            "rec-x3",
            residue=32,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-x3", bucket="intermediate_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-X3",), lab="lab-x3", protocol_lineage="proto-x3"),
            ],
        ),
        _rec(
            "rec-x4",
            residue=33,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-x4", bucket="near_reference", assay=SYN_ASSAYS[2], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-X4",), lab="lab-x4", protocol_lineage="proto-x4"),
            ],
        ),
        _rec("rec-x5", residue=34, spec_stratum="conflicting", observations=[]),
        _rec(
            "rec-x6",
            residue=35,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-x6", bucket="substantial_deviation", assay=SYN_ASSAYS[3], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-X6",), lab="lab-x6", protocol_lineage="proto-x6"),
            ],
        ),
    ]


def _c5_blocked_records() -> list[dict[str, Any]]:
    """C5 (spec-stratum coverage) is unsatisfiable at L0, and ONLY C5.

    Five distinct declared spec strata are present among the eligible pool, but
    two of them are held solely by ``rec-y4``/``rec-y5``, which collide on
    residue 54.  No panel can therefore carry all five, so every L0 attempt is
    INFEASIBLE; at R1 (C5 report-only) a six-member panel exists.
    """

    return [
        _rec("rec-y1", residue=51, spec_stratum="known_pathogenic", observations=[]),
        _rec(
            "rec-y2",
            residue=52,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-y2", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-Y2",), lab="lab-y2", protocol_lineage="proto-y2"),
            ],
        ),
        _rec(
            "rec-y3",
            residue=53,
            spec_stratum="vus_with_functional_evidence",
            observations=[
                _obs("obs-y3", bucket="intermediate_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-Y3",), lab="lab-y3", protocol_lineage="proto-y3"),
            ],
        ),
        _rec(
            "rec-y4",
            residue=54,
            spdi_position=154,
            spec_stratum="known_benign",
            observations=[
                _obs("obs-y4", bucket="near_reference", assay=SYN_ASSAYS[2], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-Y4",), lab="lab-y4", protocol_lineage="proto-y4"),
            ],
        ),
        _rec(
            "rec-y5",
            residue=54,
            spdi_position=155,
            spec_stratum="vus_without_functional_evidence",
            observations=[],
        ),
        _rec(
            "rec-y6",
            residue=56,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-y6", bucket="substantial_deviation", assay=SYN_ASSAYS[3], model=SYN_MODELS[1],
                     sources=("ACCESSION:SYN-Y6",), lab="lab-y6", protocol_lineage="proto-y6"),
            ],
        ),
        _rec(
            "rec-y7",
            residue=57,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-y7", bucket="intermediate_deviation", assay=SYN_ASSAYS[1], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-Y7",), lab="lab-y7", protocol_lineage="proto-y7"),
            ],
        ),
    ]


def _no_s6_records() -> list[dict[str, Any]]:
    """Every record carries functional evidence, so stratum S6 is empty.

    K = 3 (S1, S2, S3) so ``N_target = 5`` and the five records are the panel;
    the run must still succeed while raising the abstention-control flag.
    """

    plan = (
        ("rec-n1", 61, "substantial_deviation", SYN_ASSAYS[0], SYN_MODELS[0]),
        ("rec-n2", 62, "intermediate_deviation", SYN_ASSAYS[1], SYN_MODELS[1]),
        ("rec-n3", 63, "near_reference", SYN_ASSAYS[2], SYN_MODELS[0]),
        ("rec-n4", 64, "substantial_deviation", SYN_ASSAYS[3], SYN_MODELS[1]),
        ("rec-n5", 65, "intermediate_deviation", SYN_ASSAYS[1], SYN_MODELS[0]),
    )
    return [
        _rec(
            record_id,
            residue=residue,
            spec_stratum="conflicting",
            observations=[
                _obs(f"obs-{record_id}", bucket=bucket, assay=assay, model=model,
                     sources=(f"ACCESSION:SYN-{record_id.upper()}",),
                     lab=f"lab-{record_id}", protocol_lineage=f"proto-{record_id}"),
            ],
        )
        for record_id, residue, bucket, assay, model in plan
    ]


def _blocked_control_records() -> list[dict[str, Any]]:
    """No genuine S6 record; the only evidence-free-looking record is ACCESS BLOCKED.

    ``rec-blocked`` carries a restricted, unverifiable observation, so it is
    excluded under E4/X5 with support class ``access_blocked`` -- it must NOT be
    laundered into the abstention control (protocol section 12.4).
    """

    records = _no_s6_records()
    records.append(
        _rec(
            "rec-blocked",
            residue=66,
            spec_stratum="conflicting",
            observations=[
                _obs("obs-blocked", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0],
                     sources=("ACCESSION:SYN-BLOCKED",), lab="lab-blocked", protocol_lineage="proto-blocked",
                     access="restricted", span_verifiable=False),
            ],
        )
    )
    return records


def _expected_allocations(
    n: int, *, nonempty_strata: Sequence[str], pool_sizes: Mapping[str, int]
) -> tuple[tuple[int, ...], ...]:
    """Independent allocation enumeration straight from protocol section 17.5."""

    ordered = [s for s in OMEGA if s in nonempty_strata]
    caps = [min(_ceil_half(n), pool_sizes[s]) for s in ordered]
    vectors = []
    for combo in itertools.product(*[range(1, cap + 1) for cap in caps]):
        if sum(combo) == n:
            vectors.append(combo)
    return tuple(sorted(vectors, key=lambda v: (max(v), v)))


def _allocation_of(panel: Sequence[Mapping[str, Any]], nonempty: Sequence[str]) -> tuple[int, ...]:
    primaries = [r["primary_stratum"] for r in panel]
    return tuple(primaries.count(s) for s in OMEGA if s in nonempty)


def _pool_context(world: _World) -> tuple[list[dict[str, Any]], dict[str, str]]:
    pool = _eligible_pool(world)
    index = _lineage_index([o for r in world.universe_records for o in r["observations"]])
    return pool, index


# ---------------------------------------------------------------------------
# PS-E-* eligibility
# ---------------------------------------------------------------------------


def _eligibility_case(record: Mapping[str, Any], observations: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    base = {
        "record_id": "case",
        "identity_state": "resolved",
        "spdi_canonical": _syn_spdi(61),
        "hgvs_c": f"{SYN_TRANSCRIPT}:c.{181}A>G",
        "hgvs_p": f"{SYN_PROTEIN}:p.Lys{61}Glu",
        "transcript_pin": SYN_TRANSCRIPT,
        "residue_index": 61,
        "codon_index": 61,
        "consequence_class": "missense_substitution",
        "functional_evidence_present": bool(observations),
        "observations": list(observations),
        "spec_stratum": "conflicting",
        "spec_stratum_basis": "synthetic label basis",
        "spec_stratum_derivation": "external_label",
        "exclusion_flags": [],
    }
    base.update(record)
    return base


def _evaluate(world: _World, record: Mapping[str, Any], *, anchor_residue: int | None = None) -> tuple[bool, str, str]:
    pack = _atlas_pack.load_disease_pack(str(world.pack_path))
    universe = {"records": [record], "gene": SYN_GENE, "assembly": SYN_ASSEMBLY}
    lineage = _sut("recompute_lineage_index")(universe)
    anchor = _sut("AnchorSpec")(
        spdi_canonical=_syn_spdi(anchor_residue if anchor_residue is not None else world.anchor_residue),
        residue_index=anchor_residue if anchor_residue is not None else world.anchor_residue,
    )
    return _sut("evaluate_eligibility")(
        record, universe=universe, lineage=lineage, anchor=anchor, pack=pack
    )


@requires_impl
def test_ps_e_001_each_rule_yields_its_exclusion_code(tmp_path: Path) -> None:
    """PS-E-001: E1..E8 each map to their declared X-code and rule_id.

    GAP NOTE (G6): protocol 8.1 E5 ("all supporting material is public and
    lawfully usable") has no dedicated section 4.3 primitive. The case below
    drives it from the pack's declared prohibited licence family, which is the
    only declared, attributable basis available; a different declared basis is
    a spec gap, not a licence to skip the case.
    """

    world = build_world(tmp_path)
    open_obs = _obs("ok", sources=("ACCESSION:SYN-OK",), lab="lab-ok", protocol_lineage="proto-ok")
    cases = {
        "E1": (_eligibility_case({"identity_state": "unresolved", "spdi_canonical": None}), "X1"),
        "E2": (_eligibility_case({"consequence_class": "nonsense_substitution"}, [open_obs]), "X2"),
        "E3": (
            _eligibility_case(
                {"residue_index": world.anchor_residue, "codon_index": world.anchor_residue,
                 "spdi_canonical": world.anchor_spdi},
                [open_obs],
            ),
            "X3",
        ),
        "E4": (
            _eligibility_case(
                {},
                [_obs("blocked", access="restricted", span_verifiable=False,
                      sources=("ACCESSION:SYN-BL",), lab="lab-bl", protocol_lineage="proto-bl")],
            ),
            "X5",
        ),
        "E5": (
            _eligibility_case(
                {},
                [_obs("nonpublic", license_family="synlicense_nonpublic",
                      sources=("ACCESSION:SYN-NP",), lab="lab-np", protocol_lineage="proto-np")],
            ),
            "X9",
        ),
        "E6": (_eligibility_case({"functional_evidence_present": True}, []), "X7"),
        "E7": (_eligibility_case({"hgvs_p": None}, [open_obs]), "X6"),
        "E8": (_eligibility_case({"exclusion_flags": ["retracted_source"]}, [open_obs]), "X8"),
    }
    for rule_id, (record, expected_code) in cases.items():
        eligible, code, rule = _evaluate(world, record)
        assert eligible is False, f"{rule_id} case was accepted as eligible"
        assert code == expected_code, f"{rule_id} produced {code!r}, expected {expected_code!r}"
        assert rule == rule_id, f"{rule_id} case reported rule_id {rule!r}"

    eligible, code, rule = _evaluate(world, _eligibility_case({}, [open_obs]))
    assert eligible is True, f"the clean case was excluded as {code}/{rule}"


@requires_impl
def test_ps_e_002_anchor_residue_is_driven_by_the_injected_spec(tmp_path: Path) -> None:
    """PS-E-002: the anchor identity AND any other substitution at its residue."""

    world = build_world(tmp_path)
    open_obs = _obs("ok", sources=("ACCESSION:SYN-OK",), lab="lab-ok", protocol_lineage="proto-ok")
    identical = _eligibility_case(
        {"spdi_canonical": world.anchor_spdi, "residue_index": world.anchor_residue,
         "codon_index": world.anchor_residue},
        [open_obs],
    )
    neighbour = _eligibility_case(
        {"spdi_canonical": _syn_spdi(500), "residue_index": world.anchor_residue,
         "codon_index": world.anchor_residue},
        [open_obs],
    )
    for record in (identical, neighbour):
        eligible, code, rule = _evaluate(world, record)
        assert (eligible, code, rule) == (False, "X3", "E3")

    moved = _evaluate(world, neighbour, anchor_residue=world.anchor_residue + 1)
    assert moved[0] is True, "the anchor must come from the injected AnchorSpec, not a literal"


@requires_impl
def test_ps_e_003_access_blocked_versus_genuine_abstention(tmp_path: Path) -> None:
    """PS-E-003: E4 excludes access-blocked evidence but keeps bona fide S6."""

    world = build_world(tmp_path)
    blocked = _eligibility_case(
        {},
        [_obs("blocked", access="restricted", span_verifiable=False,
              sources=("ACCESSION:SYN-BL",), lab="lab-bl", protocol_lineage="proto-bl")],
    )
    assert _evaluate(world, blocked) == (False, "X5", "E4")

    abstention = _eligibility_case({"functional_evidence_present": False}, [])
    eligible, code, rule = _evaluate(world, abstention)
    assert eligible is True, f"a genuine S6 record was excluded as {code}/{rule}"


@requires_impl
def test_ps_e_004_eligible_but_not_selected_is_never_an_exclusion(tmp_path: Path) -> None:
    """PS-E-004: NS_NOT_IN_SOLUTION, never an X-code, for considered-not-chosen."""

    world = build_world(tmp_path, records=_last_branch_records())
    run = _select(world)
    dispositions = {d.record_id: d for d in getattr(run, "dispositions")}
    selected = set(_selected_ids(run))
    pool_ids = {r["record_id"] for r in _eligible_pool(world)}
    unselected = pool_ids - selected
    assert unselected, "fixture must leave at least one eligible record unselected"
    for record_id in unselected:
        disposition = dispositions[record_id].disposition
        assert not re.fullmatch(r"X\d+", disposition), (
            f"{record_id} was eligible but recorded as exclusion {disposition}"
        )
        assert disposition.startswith("NS_"), disposition
    assert any(dispositions[r].disposition == "NS_NOT_IN_SOLUTION" for r in unselected)


@requires_impl
def test_ps_e_005_external_label_contradiction_is_report_only(tmp_path: Path) -> None:
    """PS-E-005: a contradictory EXTERNAL label flags but never aborts."""

    def contradict(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["record_id"] == "rec-a")
        record["spec_stratum"] = "vus_without_functional_evidence"
        record["spec_stratum_derivation"] = "external_label"

    world = build_world(tmp_path, on_universe=contradict)
    assert _crosswalk_cell("vus_without_functional_evidence", "S1") == "contradictory"
    run = _select(world)
    dispositions = {d.record_id: d for d in getattr(run, "dispositions")}
    assert dispositions["rec-a"].stale_label_discordant is True
    assert dispositions["rec-a"].primary_stratum == "S1", "the functional axis must not be relabelled"
    assert dispositions["rec-a"].spec_stratum == "vus_without_functional_evidence"
    assert "rec-a" in _selected_ids(run), "a stale label must not remove eligibility"
    assert _sut("crosswalk_cell")(
        "vus_without_functional_evidence", "S1", "external_label"
    ) in ("contradictory", "permitted")


@requires_impl
def test_ps_e_006_recomputed_label_contradiction_is_fatal(tmp_path: Path) -> None:
    """PS-E-006: the same contradiction is a breach when recomputed in-universe."""

    def contradict(universe: dict) -> None:
        record = next(r for r in universe["records"] if r["record_id"] == "rec-a")
        record["spec_stratum"] = "vus_without_functional_evidence"
        record["spec_stratum_derivation"] = "recomputed_from_locked_observations"

    world = build_world(tmp_path, on_universe=contradict)
    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )
    assert _sut("crosswalk_cell")(
        "vus_without_functional_evidence", "S1", "recomputed_from_locked_observations"
    ) == "contradictory"


# ---------------------------------------------------------------------------
# PS-A-* allocation, draw order and complete search
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_a_001_allocation_enumeration_and_order(tmp_path: Path) -> None:
    """PS-A-001: C1/C3/sum honoured and emitted in the declared balance-first order."""

    enumerate_allocations = _sut("enumerate_allocations")
    nonempty = ["S6", "S2", "S1"]
    pool_sizes = {"S6": 3, "S2": 2, "S1": 2}
    actual = tuple(tuple(v) for v in enumerate_allocations(5, nonempty_strata=nonempty, pool_sizes=pool_sizes))
    expected = _expected_allocations(5, nonempty_strata=nonempty, pool_sizes=pool_sizes)
    assert actual == expected, f"{actual} != {expected}"
    assert all(min(vector) >= 1 for vector in actual), "C1 violated"
    assert all(max(vector) <= _ceil_half(5) for vector in actual), "C3 violated"
    assert all(sum(vector) == 5 for vector in actual)
    assert [max(v) for v in actual] == sorted(max(v) for v in actual), "not balance-first"
    assert actual[-1] == (3, 1, 1), actual

    empty = tuple(enumerate_allocations(2, nonempty_strata=nonempty, pool_sizes=pool_sizes))
    assert empty == (), "an unsatisfiable size must enumerate nothing"


@requires_impl
def test_ps_a_002_draw_key_and_global_order(tmp_path: Path) -> None:
    """PS-A-002: draw_key is sha256(seed|spdi) and order is (draw_key, spdi)."""

    draw_key = _sut("draw_key")
    spdi = _syn_spdi(31)
    expected = hashlib.sha256(f"{SYN_SEED}|{spdi}".encode("utf-8")).hexdigest()
    assert draw_key(spdi, selection_seed=SYN_SEED) == expected
    assert expected == expected.lower()
    assert draw_key(spdi, selection_seed="other-seed") != expected

    spdis = [_syn_spdi(i) for i in range(11, 20)]
    ordered = sorted(spdis, key=lambda s: (draw_key(s, selection_seed=SYN_SEED), s))
    assert ordered == sorted(spdis, key=lambda s: (_draw_key(s), s))
    assert ordered != spdis or len(spdis) == 1, "draw order must not be insertion order"


@requires_impl
def test_ps_a_003_only_solution_in_the_last_branch_is_found(tmp_path: Path) -> None:
    """PS-A-003 ADVERSARIAL: completeness against a last-branch-only solution."""

    world = build_world(tmp_path, records=_last_branch_records())
    pool, index = _pool_context(world)
    nonempty = sorted({r["primary_stratum"] for r in pool})
    solutions = _brute_force_solutions(pool, n=5, index=index)
    assert len(solutions) == 1, f"fixture must have exactly one solution, got {solutions}"

    pool_sizes = {s: sum(1 for r in pool if r["primary_stratum"] == s) for s in nonempty}
    vectors = _expected_allocations(5, nonempty_strata=nonempty, pool_sizes=pool_sizes)
    assert len(vectors) > 1, "fixture must offer several allocation branches"
    winner = [r for r in pool if r["record_id"] in set(solutions[0])]
    assert _allocation_of(winner, nonempty) == vectors[-1], (
        "fixture failed to place the solution in the LAST allocation branch"
    )

    run = _select(world)
    assert getattr(run, "terminal_outcome") == "PANEL_SELECTED"
    assert set(_selected_ids(run)) == set(solutions[0])


@requires_impl
def test_ps_a_004_non_hereditary_minimums_never_prune(tmp_path: Path) -> None:
    """PS-A-004 ADVERSARIAL: a prefix violating D1/D2/P2 must stay reachable."""

    world = build_world(tmp_path, records=_last_branch_records())
    pool, index = _pool_context(world)
    solutions = _brute_force_solutions(pool, n=5, index=index)
    assert len(solutions) == 1
    winner = {r["record_id"]: r for r in pool if r["record_id"] in set(solutions[0])}

    prefix = [r for r in winner.values() if r["primary_stratum"] == "S6"]
    assert len(prefix) == 3, "fixture must start with an evidence-free prefix"
    assay_kinds = {o["assay_kind"] for r in prefix for o in r["observations"]}
    models = {o["model_system"] for r in prefix for o in r["observations"]}
    groups = {g for r in prefix for g in _record_groups(r, index)}
    assert len(assay_kinds) < 3 and len(models) < 2 and len(groups) < 3, (
        "fixture prefix does not violate the non-hereditary minimums"
    )

    run = _select(world)
    assert set(_selected_ids(run)) == set(solutions[0]), (
        "the solution was pruned by a non-hereditary minimum"
    )


@requires_impl
def test_ps_a_005_hereditary_pruning_matches_a_brute_force_oracle(tmp_path: Path) -> None:
    """PS-A-005: pruning is sound -- no complete solution is ever removed."""

    world = build_world(tmp_path / "base")
    pool, index = _pool_context(world)
    solutions = _brute_force_solutions(pool, n=6, index=index)
    assert len(solutions) == 1, solutions
    run = _select(world)
    assert set(_selected_ids(run)) == set(solutions[0])

    collide = build_world(tmp_path / "collide", records=_collision_records())
    collide_pool, collide_index = _pool_context(collide)
    colliding = [r for r in collide_pool if r["residue_index"] == 31]
    assert len(colliding) == 2, "fixture must contain a residue collision"
    assert _brute_force_solutions(collide_pool, n=6, index=collide_index) == [], (
        "fixture must make the target size unreachable through the collision alone"
    )
    for combo in _brute_force_solutions(collide_pool, n=5, index=collide_index):
        assert len({r["record_id"] for r in colliding} & set(combo)) <= 1


@requires_impl
def test_ps_a_006_collisions_resolve_by_draw_order_only(tmp_path: Path) -> None:
    """PS-A-006: residue/codon collisions are decided by draw order, not evidence."""

    world = build_world(tmp_path / "base", records=_collision_records())
    pool, _ = _pool_context(world)
    colliding = sorted(
        (r for r in pool if r["residue_index"] == 31),
        key=lambda r: (_draw_key(r["spdi_canonical"]), r["spdi_canonical"]),
    )
    assert len(colliding) == 2
    winner = colliding[0]["record_id"]

    run = _select(world)
    selected = set(_selected_ids(run))
    assert winner in selected
    assert colliding[1]["record_id"] not in selected
    loser = {d.record_id: d for d in getattr(run, "dispositions")}[colliding[1]["record_id"]]
    assert loser.disposition in ("NS_COLLISION_RESIDUE", "NS_COLLISION_CODON")

    def restate_basis(records: list) -> None:
        for record in records:
            for observation in record["observations"]:
                observation["bucket_basis"] = "a different declared synthetic basis"

    restated = build_world(
        tmp_path / "restated", records=_collision_records(), on_records=restate_basis
    )
    assert winner in set(_selected_ids(_select(restated))), (
        "an observation field changed the collision outcome"
    )


@requires_impl
def test_ps_a_007_infeasible_complete_requires_exhaustion(tmp_path: Path) -> None:
    """PS-A-007: INFEASIBLE_COMPLETE only with nodes_expanded strictly below budget."""

    budget = 50000
    world = build_world(tmp_path, records=_single_assay_records(), node_budget=budget)
    pool, index = _pool_context(world)
    assert _brute_force_solutions(pool, n=6, index=index) == [], "fixture must be infeasible"
    assert _brute_force_solutions(pool, n=5, index=index) == [], "fixture must be infeasible"

    run = _select(world)
    assert getattr(run, "terminal_outcome") == "INFEASIBLE_PANEL"
    attempts = getattr(run, "attempts")
    assert attempts, "an infeasible run must still record its attempts"
    for attempt in attempts:
        assert attempt.status == "INFEASIBLE_COMPLETE", attempt
        assert attempt.nodes_expanded < budget, attempt


@requires_impl
def test_ps_a_008_search_scope_guard_runs_before_any_attempt(tmp_path: Path) -> None:
    """PS-A-008 ADVERSARIAL: a narrowed scope or shortlist is refused up front."""

    narrowed = build_world(tmp_path / "scope", search_scope="stratum_shortlist")
    _expect(
        narrowed,
        lambda: _select(narrowed),
        error="AtlasPanelRegistrationError",
        code="UNSUPPORTED_SEARCH_SCOPE",
    )

    shortlist = build_world(tmp_path / "shortlist", stratum_shortlist_size=12)
    _expect(
        shortlist,
        lambda: _select(shortlist),
        error="AtlasPanelRegistrationError",
        code="UNSUPPORTED_SEARCH_SCOPE",
    )


# ---------------------------------------------------------------------------
# PS-O-* schedule, relaxation and terminal outcomes
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_o_001_schedule_is_level_major_and_size_descending(tmp_path: Path) -> None:
    """PS-O-001: every size at a level is tried before the next level."""

    world = build_world(tmp_path, records=_collision_records())
    run = _select(world)
    attempts = list(getattr(run, "attempts"))
    assert attempts, "the attempt log must never be empty"
    levels = [a.level for a in attempts]
    order = ["L0", *LADDER_STEPS]
    assert levels == sorted(levels, key=order.index), f"levels are not level-major: {levels}"
    for level in dict.fromkeys(levels):
        sizes = [a.n for a in attempts if a.level == level]
        assert sizes == sorted(sizes, reverse=True), f"{level} sizes not descending: {sizes}"
    accepted = next(a for a in attempts if a.status == "SOLUTION")
    assert accepted.level == "L0", "a relaxed panel was preferred over an L0 one"
    assert getattr(run, "n_selected") == accepted.n
    bigger = [a for a in attempts if a.n > accepted.n]
    assert bigger and all(a.status == "INFEASIBLE_COMPLETE" for a in bigger), (
        "a larger size must have been tried and rejected first, not skipped"
    )


@requires_impl
def test_ps_o_002_undetermined_at_l0_stops_with_no_relaxation(tmp_path: Path) -> None:
    """PS-O-002 ADVERSARIAL: budget exhaustion never advances the ladder."""

    world = build_world(tmp_path, records=_last_branch_records(), node_budget=1)
    run = _select(world)
    assert getattr(run, "terminal_outcome") == "UNDETERMINED_SEARCH_INCOMPLETE"
    assert tuple(getattr(run, "applied_relaxation_steps")) == ()
    assert getattr(run, "independence_status") == "DECLARED"
    assert getattr(run, "n_selected") is None
    assert _selected_ids(run) == ()
    attempts = list(getattr(run, "attempts"))
    assert any(a.status == "UNDETERMINED" for a in attempts)
    assert all(a.level == "L0" for a in attempts), [a.level for a in attempts]
    assert all(a.status != "INFEASIBLE_COMPLETE" for a in attempts)
    undetermined = next(a for a in attempts if a.status == "UNDETERMINED")
    assert undetermined.nodes_expanded == 1, undetermined


@requires_impl
def test_ps_o_003_infeasible_panel_still_emits_a_complete_record(tmp_path: Path) -> None:
    """PS-O-003: no panel, zero members, but every record still disposed."""

    world = build_world(tmp_path, records=_single_assay_records())
    run = _select(world)
    assert getattr(run, "terminal_outcome") == "INFEASIBLE_PANEL"
    assert _selected_ids(run) == ()
    assert getattr(run, "n_selected") is None
    dispositions = getattr(run, "dispositions")
    assert len(dispositions) == len(world.universe["records"])
    assert all(d.disposition != "SEL" for d in dispositions)
    assert all(a.status == "INFEASIBLE_COMPLETE" for a in getattr(run, "attempts"))


@requires_impl
def test_ps_o_004_relaxed_levels_are_stamped_and_recorded(tmp_path: Path) -> None:
    """PS-O-004: level > L0 stamps RELAXED and records before/after values."""

    world = build_world(tmp_path, records=_c5_blocked_records())
    pool, index = _pool_context(world)
    assert _brute_force_solutions(pool, n=6, index=index, level="L0") == [], (
        "fixture must be infeasible at L0"
    )
    assert _brute_force_solutions(pool, n=6, index=index, level="R1"), (
        "fixture must become feasible once C5 is relaxed"
    )

    run = _select(world)
    assert getattr(run, "terminal_outcome") == "PANEL_SELECTED"
    steps = list(getattr(run, "applied_relaxation_steps"))
    assert steps and steps[0].startswith("R1"), steps
    assert getattr(run, "independence_status") == "RELAXED"
    flags = dict(getattr(run, "flags"))
    assert flags.get("spec_taxonomy_coverage") == "PARTIAL"
    ladder = {s["step"]: s for s in world.registration["relaxation_ladder"]}
    assert "before" in ladder["R1"] and "after" in ladder["R1"]


@requires_impl
def test_ps_o_005_never_relaxed_items_are_unreachable(tmp_path: Path) -> None:
    """PS-O-005: the ladder never touches a never_relaxed item, at any level."""

    world = build_world(tmp_path, records=_single_assay_records())
    never = set(world.registration["never_relaxed"])
    ladder_targets = {step["constraint"] for step in world.registration["relaxation_ladder"]}
    assert ladder_targets & never == set(), ladder_targets & never
    for mandatory in ("C1", "C2", "C4", "E1", "E8", "firewall", "undetermined_relaxation"):
        assert mandatory in never

    run = _select(world)
    assert getattr(run, "terminal_outcome") == "INFEASIBLE_PANEL"
    assert _selected_ids(run) == (), "a never-relaxed constraint was weakened to reach a number"
    for step in getattr(run, "applied_relaxation_steps"):
        assert any(step.startswith(name) for name in LADDER_STEPS), step


@requires_impl
def test_ps_o_006_n_selected_follows_a_solution_and_stays_in_bounds(tmp_path: Path) -> None:
    """PS-O-006: N_selected exists only with a solution and respects the bounds."""

    bounds = build_world(tmp_path / "ok")
    run = _select(bounds)
    rule = bounds.registration["panel_size_rule"]
    assert getattr(run, "n_target") == max(rule["min"], min(rule["max"], 4 + 2))
    n_selected = getattr(run, "n_selected")
    assert rule["min"] <= n_selected <= rule["max"]
    assert n_selected == len(_selected_ids(run))

    starved = build_world(tmp_path / "starved", records=_single_assay_records())
    assert getattr(_select(starved), "n_selected") is None


@requires_impl
def test_ps_o_007_abstention_control_is_required_or_flagged(tmp_path: Path) -> None:
    """PS-O-007: S6 non-empty forces an S6 member; S6 empty is flagged, not faked."""

    present = build_world(tmp_path / "present")
    run = _select(present)
    dispositions = {d.record_id: d for d in getattr(run, "dispositions")}
    selected_strata = {dispositions[r].primary_stratum for r in _selected_ids(run)}
    assert "S6" in selected_strata, "C2 was not enforced"
    assert dict(getattr(run, "flags")).get("ABSTENTION_CONTROL_MISSING") in (False, None)

    absent = build_world(tmp_path / "absent", records=_no_s6_records())
    absent_run = _select(absent)
    absent_dispositions = {d.record_id: d for d in getattr(absent_run, "dispositions")}
    assert all(d.primary_stratum != "S6" for d in absent_dispositions.values())
    assert dict(getattr(absent_run, "flags")).get("ABSTENTION_CONTROL_MISSING") is True


@requires_impl
def test_ps_o_008_access_blocked_never_serves_as_the_control(tmp_path: Path) -> None:
    """PS-O-008: an access-blocked record is X5, never the abstention control."""

    world = build_world(tmp_path, records=_blocked_control_records())
    run = _select(world)
    dispositions = {d.record_id: d for d in getattr(run, "dispositions")}
    assert dispositions["rec-blocked"].disposition == "X5"
    assert "rec-blocked" not in _selected_ids(run)
    assert dispositions["rec-blocked"].support_class == "access_blocked"
    assert dict(getattr(run, "flags")).get("ABSTENTION_CONTROL_MISSING") is True


# ---------------------------------------------------------------------------
# Declared-order oracle + randomized pools (used by the PS-P property tests)
# ---------------------------------------------------------------------------


def _oracle_first_solution(
    pool: Sequence[Mapping[str, Any]],
    *,
    n: int,
    index: Mapping[str, str],
    level: str = "L0",
) -> tuple[str, ...] | None:
    """The declared-first solution, built by enumerate-then-test.

    Protocol section 17.5 declares the acceptance order: allocation vectors in
    ``(max ascending, lexicographic in Omega order)``, then per-stratum
    combinations in lexicographic order over draw-ordered indices. This helper
    reproduces that ORDER without reproducing the implementation's pruned
    depth-first search, so agreement is evidence rather than tautology.
    """

    nonempty = sorted({r["primary_stratum"] for r in pool})
    ordered = sorted(pool, key=lambda r: (_draw_key(r["spdi_canonical"]), r["spdi_canonical"]))
    pool_sizes = {s: sum(1 for r in ordered if r["primary_stratum"] == s) for s in nonempty}
    omega_order = [s for s in OMEGA if s in nonempty]
    strata_pools = {s: [r for r in ordered if r["primary_stratum"] == s] for s in omega_order}
    spec_values = sorted({r["spec_stratum"] for r in ordered})
    for vector in _expected_allocations(n, nonempty_strata=nonempty, pool_sizes=pool_sizes):
        per_stratum = [
            list(itertools.combinations(strata_pools[s], vector[i]))
            for i, s in enumerate(omega_order)
        ]
        for parts in itertools.product(*per_stratum):
            members = [record for part in parts for record in part]
            if _check_constraints(
                members,
                n=n,
                nonempty_strata=nonempty,
                spec_values=spec_values,
                index=index,
                level=level,
                pool=ordered,
            ):
                return tuple(r["record_id"] for r in members)
    return None


def _oracle_schedule(
    pool: Sequence[Mapping[str, Any]],
    *,
    index: Mapping[str, str],
    panel_min: int = 5,
    panel_max: int = 10,
) -> tuple[str, int, tuple[str, ...]] | None:
    """Walk the declared level-major / size-descending schedule independently."""

    k = len({r["primary_stratum"] for r in pool})
    n_target = max(panel_min, min(panel_max, k + 2))
    for level in ("L0", *LADDER_STEPS):
        for n in range(n_target, panel_min - 1, -1):
            solution = _oracle_first_solution(pool, n=n, index=index, level=level)
            if solution is not None:
                return level, n, solution
    return None


def _random_records(seed: int, *, size: int) -> list[dict[str, Any]]:
    """A randomized but fully synthetic pool; nothing here denotes real data."""

    rng = random.Random(seed)
    buckets = (
        "substantial_deviation",
        "intermediate_deviation",
        "near_reference",
        "context_dependent",
    )
    records: list[dict[str, Any]] = []
    for offset in range(size):
        residue = 71 + offset
        if rng.random() < 0.25:
            records.append(
                _rec(f"rnd-{offset}", residue=residue, spec_stratum=rng.choice(SPEC_STRATA[:3]))
            )
            continue
        observations = []
        for slot in range(rng.choice((1, 1, 2))):
            observations.append(
                _obs(
                    f"obs-rnd-{offset}-{slot}",
                    bucket=rng.choice(buckets),
                    assay=rng.choice(SYN_ASSAYS),
                    model=rng.choice(SYN_MODELS),
                    sources=(f"ACCESSION:SYN-R{rng.randrange(size + 2)}",),
                    lab=f"lab-r{rng.randrange(size + 2)}",
                    protocol_lineage=f"proto-r{rng.randrange(size + 2)}",
                    throughput=rng.choice(("low_throughput", "low_throughput", "high_throughput")),
                )
            )
        records.append(
            _rec(
                f"rnd-{offset}",
                residue=residue,
                spec_stratum=rng.choice(SPEC_STRATA[:3]),
                observations=observations,
            )
        )
    return records


def _run_record(world: _World, run: Any, **overrides: Any) -> dict[str, Any]:
    return _sut("render_run_record")(run, inputs=world.inputs(**overrides))


def _cli_module() -> Any:
    """Import the thin CLI adapter from its spec-pinned path (never guessed)."""

    import importlib.util

    assert CLI_PATH.exists(), f"SPEC GAP or missing surface: {CLI_PATH} was not created"
    spec = importlib.util.spec_from_file_location("_atlas_panel_cli_under_test", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_pack_paths() -> list[Path]:
    """Tracked pack manifests, discovered by shape so no real id is embedded."""

    return sorted((REPO_ROOT / "configs" / "atlas" / "packs").glob("*/pack.yaml"))


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# PS-D-* audit trail
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_d_001_one_disposition_row_per_universe_record(tmp_path: Path) -> None:
    """PS-D-001 ADVERSARIAL: unresolved and excluded records are rows too."""

    world = build_world(tmp_path, records=_blocked_control_records() + [
        _rec("rec-zz", residue=None, resolved=False, spec_stratum="conflicting"),
        _rec("rec-extra1", residue=98, spec_stratum="conflicting", observations=[
            _obs("obs-e1", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0])
        ]),
        _rec("rec-extra2", residue=101, spec_stratum="conflicting", observations=[
            _obs("obs-e2", bucket="substantial_deviation", assay=SYN_ASSAYS[0], model=SYN_MODELS[0])
        ]),
    ])
    run = _select(world)
    universe_ids = [record["record_id"] for record in world.universe["records"]]
    rows = list(getattr(run, "dispositions"))
    row_ids = [d.record_id for d in rows]

    assert len(row_ids) == len(set(row_ids)), f"duplicate disposition rows: {row_ids}"
    assert sorted(row_ids) == sorted(universe_ids), (
        f"disposition table is not one row per universe record: {sorted(row_ids)}"
    )
    selected = set(_selected_ids(run))
    assert selected, "fixture must select a panel for this comparison to bite"

    eligible_count = sum(1 for d in rows if not d.disposition.startswith("X"))
    assert eligible_count > len(selected), "fixture must have more eligible records than selected records"

    unresolved = next(d for d in rows if d.record_id == "rec-zz")
    assert unresolved.identity_state == "unresolved"
    assert unresolved.disposition == "X1"
    assert unresolved.draw_key is None
    excluded = next(d for d in rows if d.record_id == "rec-blocked")
    assert excluded.disposition == "X5"
    not_selected = [d for d in rows if d.disposition.startswith("NS_")]
    assert not_selected, "eligible-but-unselected records must carry an NS_* disposition"

    rendered = _run_record(world, run)
    assert len(rendered["dispositions"]) == len(universe_ids)


@requires_impl
def test_ps_d_002_rows_carry_rule_ids_and_selected_rows_carry_slots(tmp_path: Path) -> None:
    """PS-D-002: every row names the rule; only selected rows carry a slot."""

    world = build_world(tmp_path)
    run = _select(world)
    rows = list(getattr(run, "dispositions"))
    selected = set(_selected_ids(run))
    assert selected

    for row in rows:
        assert isinstance(row.rule_id, str) and row.rule_id.strip(), row
        if row.record_id in selected:
            assert row.disposition == "SEL", row
            assert row.allocation_slot in OMEGA, row
            assert row.allocation_slot == row.primary_stratum, row
        else:
            assert row.disposition != "SEL", row
            assert row.allocation_slot is None, row

    assert len({row.rule_id for row in rows}) >= 2, "one rule_id for every outcome is not an audit"
    slots = [row.allocation_slot for row in rows if row.allocation_slot is not None]
    assert len(slots) == len(selected)
    nonempty = sorted({r["primary_stratum"] for r in _eligible_pool(world)})
    assert tuple(slots.count(s) for s in OMEGA if s in nonempty) == _allocation_of(
        [{"primary_stratum": s} for s in slots], nonempty
    )


@requires_impl
def test_ps_d_003_run_record_carries_every_digest_and_the_full_delta(tmp_path: Path) -> None:
    """PS-D-003: no PreconditionReport field and no delta field may be dropped."""

    world = build_world(tmp_path)
    run = _select(world)
    rendered = _run_record(world, run)
    required_blocks = {
        "verified_digests",
        "normalization_replay",
        "identity_map",
        "procedure",
        "result",
        "dispositions",
        "provenance",
    }
    assert required_blocks <= set(rendered), sorted(required_blocks - set(rendered))

    report = getattr(run, "preconditions")
    digests = rendered["verified_digests"]
    for field in dataclass_fields(type(report)):
        assert field.name in digests, f"{field.name} missing from the run record"
    for name in ("verified_protocol_doc_hash", "verified_registration_content_hash",
                 "verified_live_pack_content_hash", "verified_universe_content_hash"):
        assert digests[name] == getattr(report, name)

    delta = digests["lock_protocol_version_delta"]
    expected = {f.name for f in dataclass_fields(_sut("LockProtocolVersionDelta"))}
    assert set(delta) == expected, set(delta).symmetric_difference(expected)
    assert all(delta[name] is not None for name in expected), delta
    assert delta["lock_protocol_version"] == SYN_PRIOR_PROTOCOL_VERSION
    assert delta["current_protocol_version"] == SYN_PROTOCOL_VERSION

    procedure = rendered["procedure"]
    result = rendered["result"]

    for proc_field in ("selection_seed", "search_scope", "search_node_budget", "attempt_log", "terminal_outcome"):
        assert proc_field in procedure, f"{proc_field} missing from procedure block"
    for res_field in ("terminal_outcome", "n_target", "n_selected", "selected_record_ids"):
        assert res_field in result, f"{res_field} missing from result block"

    assert procedure["search_scope"] == "full_eligible_universe"
    assert procedure["search_node_budget"] == 200000
    assert procedure["search_node_budget"] != procedure["attempts"][0]["nodes_expanded"]

    equal = build_world(tmp_path / "equal", lock_at_current_bindings=True)
    equal_delta = _run_record(equal, _select(equal))["verified_digests"][
        "lock_protocol_version_delta"
    ]
    assert equal_delta["differs"] is False
    assert set(equal_delta) == expected, "the delta was pruned because differs is False"

    # RR1: Registration post-selection drift
    drift_reg = build_world(tmp_path / "drift_reg")
    drift_reg_run = _select(drift_reg)
    drift_reg.tamper_yaml(
        drift_reg.registration_path,
        lambda r: r.__setitem__("search_scope", "tampered_scope")
    )
    _expect(
        drift_reg,
        lambda: _run_record(drift_reg, drift_reg_run),
        error="AtlasPanelRegistrationError",
        code="REGISTRATION_RENDER_SNAPSHOT_DRIFT",
        check_id="RR1",
    )

    # RR2: Universe post-selection drift
    drift_univ = build_world(tmp_path / "drift_univ")
    drift_univ_run = _select(drift_univ)
    drift_univ.tamper_yaml(
        drift_univ.universe_path,
        lambda u: u["records"].pop()
    )
    _expect(
        drift_univ,
        lambda: _run_record(drift_univ, drift_univ_run),
        error="AtlasUniverseContractError",
        code="UNIVERSE_RENDER_SNAPSHOT_DRIFT",
        check_id="RR2",
    )

    # Unchanged world control
    control = build_world(tmp_path / "control")
    control_run = _select(control)
    control_record1 = _run_record(control, control_run)
    control_record2 = _run_record(control, control_run)
    assert control_record1 == control_record2, "unchanged inputs must render deterministically"


@requires_impl
def test_ps_d_004_cli_refuses_to_overwrite_a_run_record(tmp_path: Path) -> None:
    """PS-D-004: an existing run-record path is never rewritten (spec gap G4)."""

    assert CLI_PATH.exists(), f"SPEC GAP or missing surface: {CLI_PATH} was not created"
    source = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    flags = sorted(
        {
            arg.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--")
        }
    )
    assert flags, "SPEC GAP: the CLI declares no argparse flags to drive"

    def flag_for(*needles: str) -> str:
        for needle in needles:
            for flag in flags:
                if needle in flag:
                    return flag
        raise AssertionError(f"SPEC GAP: no CLI flag matches any of {needles} in {flags}")

    world = build_world(tmp_path)
    out_path = tmp_path / "existing-run-record.json"
    sentinel = '{"already": "written"}'
    out_path.write_text(sentinel, encoding="utf-8")

    argv = [
        flag_for("protocol"), str(world.protocol_path),
        flag_for("registration"), str(world.registration_path),
        flag_for("pack"), str(world.pack_path),
        flag_for("universe"), str(world.universe_path),
        flag_for("raw-inventory", "raw"), str(world.raw_inventory_path),
        flag_for("identity-map-response-root", "response-root", "response"), str(world.response_root),
        flag_for("identity-map"), str(world.map_path),
        flag_for("anchor-spdi", "anchor"), world.anchor_spdi,
        flag_for("anchor-residue", "residue"), str(world.anchor_residue),
        flag_for("out", "run-record", "output"), str(out_path),
    ]
    entry_name = next((n for n in ("main", "run", "cli") if hasattr(_cli_module(), n)), None)
    assert entry_name is not None, (
        "SPEC GAP: cli_boundary pins no entry-point name; none of main/run/cli exists"
    )
    entry = getattr(_cli_module(), entry_name)

    with pytest.raises(BaseException) as excinfo:
        entry(argv)
    raised = excinfo.value
    if isinstance(raised, SystemExit):
        assert raised.code not in (0, None), "the CLI exited successfully over an existing record"
    assert out_path.read_text(encoding="utf-8") == sentinel, "the run record was overwritten"


@requires_impl
def test_ps_d_005_flags_are_computed_not_declared(tmp_path: Path) -> None:
    """PS-D-005: every section 18.1 flag is present AND reacts to the world."""

    world = build_world(tmp_path)
    flags = dict(getattr(_select(world), "flags"))
    exact = (
        "independence_status",
        "spec_taxonomy_coverage",
        "ABSTENTION_CONTROL_MISSING",
        "UNDETERMINED_SEARCH_INCOMPLETE",
        "INFEASIBLE_PANEL",
        "label_function_discordant",
        "stale_label_discordant",
        "unresolved_identity_count",
    )
    for name in exact:
        assert name in flags, f"flag {name} missing from {sorted(flags)}"
    assert [k for k in flags if "x5" in k.lower()], f"no X5 attrition flag in {sorted(flags)}"
    assert len([k for k in flags if k.startswith("lineage_unknown_")]) >= 2, sorted(flags)

    assert flags["independence_status"] == "DECLARED"
    assert flags["spec_taxonomy_coverage"] == "COMPLETE"
    assert flags["ABSTENTION_CONTROL_MISSING"] is False
    assert flags["UNDETERMINED_SEARCH_INCOMPLETE"] is False
    assert flags["INFEASIBLE_PANEL"] is False
    assert flags["unresolved_identity_count"] == 1
    x5_key = next(k for k in flags if "x5" in k.lower() and isinstance(flags[k], int))
    assert flags[x5_key] == 0

    blocked = build_world(tmp_path / "blocked", records=_blocked_control_records())
    blocked_flags = dict(getattr(_select(blocked), "flags"))
    assert blocked_flags[x5_key] == 1, "the X5 attrition flag is a constant, not a count"
    assert blocked_flags["ABSTENTION_CONTROL_MISSING"] is True
    assert blocked_flags["unresolved_identity_count"] == 0

    starved = build_world(tmp_path / "starved", records=_single_assay_records())
    starved_flags = dict(getattr(_select(starved), "flags"))
    assert starved_flags["INFEASIBLE_PANEL"] is True
    assert starved_flags["UNDETERMINED_SEARCH_INCOMPLETE"] is False


# ---------------------------------------------------------------------------
# PS-P-* property and metamorphic
# ---------------------------------------------------------------------------


@requires_impl
def test_ps_p_001_two_runs_are_byte_identical_apart_from_provenance(tmp_path: Path) -> None:
    """PS-P-001: determinism, with the injected clock/identity excluded."""

    world = build_world(tmp_path)
    first = _select(world)
    second = _select(
        world,
        run_started_at=RUN_STARTED_AT + timedelta(hours=7),
        executor_identity="a-different-synthetic-executor",
    )
    assert _selected_ids(first) == _selected_ids(second)
    assert [(a.level, a.n, a.status, a.nodes_expanded) for a in getattr(first, "attempts")] == [
        (a.level, a.n, a.status, a.nodes_expanded) for a in getattr(second, "attempts")
    ]

    left = _run_record(world, first)
    right = _run_record(
        world,
        second,
        run_started_at=RUN_STARTED_AT + timedelta(hours=7),
        executor_identity="a-different-synthetic-executor",
    )
    assert _stable_json(left) != _stable_json(right), "provenance did not vary; the test is vacuous"
    left.pop("provenance")
    right.pop("provenance")
    assert _stable_json(left) == _stable_json(right)


@requires_impl
def test_ps_p_002_record_and_observation_order_is_irrelevant(tmp_path: Path) -> None:
    """PS-P-002 METAMORPHIC: reordering the universe repins hashes, not results."""

    def reverse_everything(records: list) -> None:
        records.reverse()
        for record in records:
            record["observations"] = list(reversed(record["observations"]))

    base = build_world(tmp_path / "base")
    shuffled = build_world(tmp_path / "shuffled", on_records=reverse_everything)
    base_order = [r["record_id"] for r in base.universe["records"]]
    shuffled_order = [r["record_id"] for r in shuffled.universe["records"]]
    assert base_order != shuffled_order, "the metamorphic transform did nothing"
    assert sorted(base_order) == sorted(shuffled_order)
    assert base.universe["universe_content_hash"] != shuffled.universe["universe_content_hash"]

    base_run = _select(base)
    shuffled_run = _select(shuffled)
    assert _selected_ids(base_run) == _selected_ids(shuffled_run)
    assert [(a.level, a.n, a.status) for a in getattr(base_run, "attempts")] == [
        (a.level, a.n, a.status) for a in getattr(shuffled_run, "attempts")
    ]
    assert {d.record_id: d.disposition for d in getattr(base_run, "dispositions")} == {
        d.record_id: d.disposition for d in getattr(shuffled_run, "dispositions")
    }


@requires_impl
def test_ps_p_003_identity_preserving_renaming_changes_nothing(tmp_path: Path) -> None:
    """PS-P-003 METAMORPHIC: record ids and custodian keys are labels, not facts."""

    def rename(records: list) -> None:
        for record in records:
            record["record_id"] = record["record_id"].replace("rec-", "node-")
            for observation in record["observations"]:
                observation["lab_lineage_key"] = observation["lab_lineage_key"].replace(
                    "synlab-", "custodian-"
                )
                observation["assay_protocol_lineage_key"] = observation[
                    "assay_protocol_lineage_key"
                ].replace("synproto-", "method-")

    base = build_world(tmp_path / "base")
    renamed = build_world(tmp_path / "renamed", on_records=rename)

    base_groups = _lineage_index([o for r in base.universe_records for o in r["observations"]])
    renamed_groups = _lineage_index(
        [o for r in renamed.universe_records for o in r["observations"]]
    )
    assert base_groups == renamed_groups, "renaming a custodian key moved a lineage group key"

    base_run = _select(base)
    renamed_run = _select(renamed)
    assert _selected_ids(base_run) != _selected_ids(renamed_run), "the rename did not apply"
    assert tuple(rid.replace("rec-", "node-") for rid in _selected_ids(base_run)) == _selected_ids(
        renamed_run
    )
    base_keys = {r["record_id"]: r["universe_key"] for r in base.universe_records}
    renamed_keys = {r["record_id"]: r["universe_key"] for r in renamed.universe_records}
    assert sorted(base_keys.values()) == sorted(renamed_keys.values())
    assert {d.support_class for d in getattr(base_run, "dispositions")} == {
        d.support_class for d in getattr(renamed_run, "dispositions")
    }


@requires_impl
def test_ps_p_004_canonical_hash_agrees_with_the_shipped_pack_hash(tmp_path: Path) -> None:
    """PS-P-004 METAMORPHIC: one canonicalization rule, two implementations."""

    canonical_content_hash = _sut("canonical_content_hash")
    manifest = _pack_manifest()
    assert canonical_content_hash(manifest, self_key="pack_content_hash") == _atlas_pack.pack_content_hash(
        manifest
    )
    assert canonical_content_hash(manifest, self_key="pack_content_hash") == manifest[
        "pack_content_hash"
    ]

    live = yaml.safe_load(_live_pack_paths()[0].read_text(encoding="utf-8"))
    assert canonical_content_hash(live, self_key="pack_content_hash") == _atlas_pack.pack_content_hash(
        live
    )

    mutated = dict(manifest)
    mutated["pack_version"] = manifest["pack_version"] + "-x"
    assert canonical_content_hash(mutated, self_key="pack_content_hash") != canonical_content_hash(
        manifest, self_key="pack_content_hash"
    )


@requires_impl
@pytest.mark.parametrize("seed", [11, 23, 37, 59])
def test_ps_p_005_returned_solutions_satisfy_every_active_constraint(
    tmp_path: Path, seed: int
) -> None:
    """PS-P-005 PROPERTY: an independent checker validates whatever comes back."""

    world = build_world(tmp_path / f"seed{seed}", records=_random_records(seed, size=7))
    run = _select(world)
    outcome = getattr(run, "terminal_outcome")
    assert outcome in ("PANEL_SELECTED", "INFEASIBLE_PANEL", "UNDETERMINED_SEARCH_INCOMPLETE")
    if outcome != "PANEL_SELECTED":
        assert _selected_ids(run) == ()
        return

    pool, index = _pool_context(world)
    selected = set(_selected_ids(run))
    panel = [r for r in pool if r["record_id"] in selected]
    assert len(panel) == len(selected), "a selected record was not in the eligible pool"
    accepted = next(a for a in getattr(run, "attempts") if a.status == "SOLUTION")
    assert _check_constraints(
        panel,
        n=accepted.n,
        nonempty_strata=sorted({r["primary_stratum"] for r in pool}),
        spec_values=sorted({r["spec_stratum"] for r in pool}),
        index=index,
        level=accepted.level,
        pool=pool,
    ), f"seed {seed}: the returned panel violates a constraint active at {accepted.level}"


@requires_impl
@pytest.mark.parametrize("seed", [101, 202, 303, 404])
def test_ps_p_006_completeness_matches_a_brute_force_oracle(tmp_path: Path, seed: int) -> None:
    """PS-P-006 PROPERTY: SOLUTION iff the oracle finds one, and the same one."""

    world = build_world(tmp_path / f"seed{seed}", records=_random_records(seed, size=6))
    pool, index = _pool_context(world)
    expected = _oracle_schedule(pool, index=index)
    run = _select(world)
    outcome = getattr(run, "terminal_outcome")

    if expected is None:
        assert outcome == "INFEASIBLE_PANEL", f"seed {seed}: solved a provably unsolvable pool"
        assert _selected_ids(run) == ()
        return

    level, n, solution = expected
    assert outcome == "PANEL_SELECTED", f"seed {seed}: oracle found {solution} at {level}/{n}"
    assert getattr(run, "n_selected") == n
    assert set(_selected_ids(run)) == set(solution), (
        f"seed {seed}: expected the declared-first solution {solution}"
    )
    accepted = next(a for a in getattr(run, "attempts") if a.status == "SOLUTION")
    assert (accepted.level, accepted.n) == (level, n)


@requires_impl
def test_ps_p_007_lowering_the_budget_only_ever_yields_undetermined(tmp_path: Path) -> None:
    """PS-P-007 METAMORPHIC: a budget cut never manufactures INFEASIBLE."""

    records = _standard_records() + [
        _rec(f"rec-dummy-{i}", residue=100 + i, spec_stratum="conflicting", observations=[
            _obs(f"obs-dummy-{i}", bucket="near_reference", assay=SYN_ASSAYS[0], model=SYN_MODELS[0])
        ])
        for i in range(10)
    ]
    reference = build_world(tmp_path / "full", records=records)
    reference_run = _select(reference)
    assert getattr(reference_run, "terminal_outcome") == "PANEL_SELECTED"
    expected_panel = _selected_ids(reference_run)

    seen_undetermined = False
    for budget in (1, 2, 3, 5, 13, 89, 1597):
        world = build_world(tmp_path / f"budget{budget}", records=records, node_budget=budget)
        run = _select(world)
        outcome = getattr(run, "terminal_outcome")
        assert outcome != "INFEASIBLE_PANEL", (
            f"budget {budget} turned a solvable world into INFEASIBLE_PANEL"
        )
        if outcome == "UNDETERMINED_SEARCH_INCOMPLETE":
            seen_undetermined = True
            assert _selected_ids(run) == ()
            assert tuple(getattr(run, "applied_relaxation_steps")) == ()
        else:
            assert _selected_ids(run) == expected_panel
        for attempt in getattr(run, "attempts"):
            assert attempt.nodes_expanded <= budget, attempt
    assert seen_undetermined, "no budget was tight enough; the property was never exercised"


@requires_impl
def test_ps_p_008_panel_is_invariant_under_within_record_permutation(tmp_path: Path) -> None:
    """PS-P-008 PROPERTY: observation order and source order carry no meaning."""

    def widen(records: list) -> None:
        for record in records:
            for observation in record["observations"]:
                observation["source_identifiers"] = list(observation["source_identifiers"]) + [
                    f"ACCESSION:SYN-EXTRA-{observation['observation_id']}"
                ]

    def widen_and_permute(records: list) -> None:
        widen(records)
        for record in records:
            record["observations"] = list(reversed(record["observations"]))
            for observation in record["observations"]:
                observation["source_identifiers"] = list(
                    reversed(observation["source_identifiers"])
                )

    base = build_world(tmp_path / "base", on_records=widen)
    permuted = build_world(tmp_path / "permuted", on_records=widen_and_permute)

    base_sources = [
        tuple(o["source_identifiers"]) for r in base.universe_records for o in r["observations"]
    ]
    permuted_sources = [
        tuple(o["source_identifiers"]) for r in permuted.universe_records for o in r["observations"]
    ]
    assert base_sources != permuted_sources, "the permutation did nothing"
    assert sorted(map(sorted, base_sources)) == sorted(map(sorted, permuted_sources))

    base_run = _select(base)
    permuted_run = _select(permuted)
    assert _selected_ids(base_run) == _selected_ids(permuted_run)
    assert {d.record_id: d.source_group_keys for d in getattr(base_run, "dispositions")} == {
        d.record_id: d.source_group_keys for d in getattr(permuted_run, "dispositions")
    }


# ---------------------------------------------------------------------------
# PS-X-* purity and adversarial
# ---------------------------------------------------------------------------

FORBIDDEN_CORE_IMPORTS = (
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp",
    "ftplib", "telnetlib", "asyncio", "xmlrpc", "smtplib", "websocket", "websockets",
    "grpc", "pycurl", "argparse", "subprocess",
)
FORBIDDEN_CORE_ATTRS = (
    "os.environ", "os.getenv", "os.putenv", "datetime.now", "datetime.utcnow",
    "time.time", "time.monotonic", "random.random", "random.shuffle",
)
FORBIDDEN_CORE_CALLS = ("print", "input", "eval", "exec", "compile", "getenv")


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _core_purity_violations(source: str) -> list[str]:
    """Static AST purity scan; returns a violation list so it can be inverted."""

    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_CORE_IMPORTS:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_CORE_IMPORTS:
                found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            for banned in FORBIDDEN_CORE_ATTRS:
                if dotted == banned or dotted.endswith("." + banned):
                    found.append(dotted)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CORE_CALLS:
                found.append(f"{node.func.id}()")
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not targets or not isinstance(node.value, (ast.List, ast.Dict, ast.Set)):
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        empty = not getattr(node.value, "elts", None) and not getattr(node.value, "keys", None)
        if any(not n.isupper() for n in names) or empty:
            found.append(f"module-level mutable state: {names}")
    return sorted(set(found))


@requires_impl
def test_ps_x_001_core_module_is_statically_pure(tmp_path: Path) -> None:
    """PS-X-001: panel.py reads no clock, no environment and no argv."""

    assert PANEL_MODULE_PATH.exists(), f"SPEC GAP or missing surface: {PANEL_MODULE_PATH}"
    source = PANEL_MODULE_PATH.read_text(encoding="utf-8")
    assert len(source) > 2000, "the scanned module is too small to be the selector"
    assert "def select_panel" in source, "the scan is pointed at the wrong module"
    assert _core_purity_violations(source) == []

    # The scanner must be able to FAIL, otherwise the assertion above is empty.
    inversions = (
        "import os\nvalue = os.getenv('RAPTOR_ATLAS_CONTENT_ROOT')\n",
        "import socket\n",
        "import argparse\n",
        "from datetime import datetime\nnow = datetime.now()\n",
        "import time\nstamp = time.time()\n",
        "def f():\n    print('x')\n",
        "CACHE = {}\n",
    )
    for snippet in inversions:
        assert _core_purity_violations(snippet), f"the purity scanner missed: {snippet!r}"


@requires_impl
def test_ps_x_002_repository_import_guards_stay_clean(tmp_path: Path) -> None:
    """PS-X-002: the shipped guards still pass once panel.py exists."""

    package_path = str(REPO_ROOT / "src" / "raptor" / "atlas")
    assert PANEL_MODULE_PATH.exists()
    assert PANEL_MODULE_PATH.parent == Path(package_path), "panel.py is outside the scanned root"
    assert _atlas_guards.assert_no_network_imports(package_path) is None
    assert _atlas_guards.assert_atlas_import_boundary(package_path) is None
    assert _atlas_guards.assert_no_consumer_import(package_path) is None

    scanned = sorted(p.name for p in Path(package_path).glob("*.py"))
    assert "panel.py" in scanned, scanned
    assert set(_atlas_guards.FORBIDDEN_NETWORK_IMPORT_PREFIXES) & set(FORBIDDEN_CORE_IMPORTS)


@requires_impl
def test_ps_x_003_path_safety_is_enforced_on_every_supplied_path(tmp_path: Path) -> None:
    """PS-X-003: traversal, drive paths, directories and escaping links all fail."""

    traversal = build_world(
        tmp_path / "traversal",
        on_registration=lambda r: r["candidate_universe_contract"]["universe_lock"]["active"]
        .__setitem__("path", "configs/atlas/panels/synth/../synth/universe-lock.yaml"),
    )
    _expect(traversal, lambda: _select(traversal), error="AtlasPanelInputError")

    drive_root = tmp_path / "drive"
    absolute_lock = (
        drive_root / "repo" / "configs" / "atlas" / "panels" / "synth" / "universe-lock.yaml"
    )
    drive = build_world(
        drive_root,
        on_registration=lambda r: r["candidate_universe_contract"]["universe_lock"]["active"]
        .__setitem__("path", str(absolute_lock)),
    )
    assert absolute_lock.is_file(), "the fixture must make absoluteness the ONLY fault"
    _expect(drive, lambda: _select(drive), error="AtlasPanelInputError")

    directory = build_world(tmp_path / "directory")
    _expect(
        directory,
        lambda: _select(directory, universe_path=directory.external_root),
        error="AtlasPanelInputError",
    )

    escape = build_world(tmp_path / "escape")
    outside = tmp_path / "outside-universe.yaml"
    outside.write_text(escape.universe_path.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "link-to-outside.yaml"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("the OS refuses symlink creation for this user")
    _expect(escape, lambda: _select(escape, universe_path=link), error="AtlasPanelInputError")

    # PS-X-003: Durable regression coverage - parent junction/reparse escape
    junction_escape = build_world(
        tmp_path / "junction_escape",
        on_registration=lambda r: r["candidate_universe_contract"]["universe_lock"]["active"]
        .__setitem__("path", "jail/escaped-dir/universe-lock.yaml"),
    )
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    outside_universe = outside_dir / "universe-lock.yaml"
    outside_universe.write_text(junction_escape.universe_path.read_text(encoding="utf-8"), encoding="utf-8")

    jail_dir = junction_escape.repo_root / "jail"
    jail_dir.mkdir(parents=True)
    junction_link = jail_dir / "escaped-dir"

    import os
    if os.name == "nt":
        import subprocess
        subprocess.check_call(["cmd.exe", "/c", "mklink", "/J", str(junction_link), str(outside_dir)])
    else:
        junction_link.symlink_to(outside_dir, target_is_directory=True)

    junction_escape.seal()

    assert junction_link.is_dir()
    assert (junction_link / "universe-lock.yaml").is_file()
    assert junction_link.resolve().parent == tmp_path, "junction must point outside repo_root"

    _expect(
        junction_escape,
        lambda: _select(junction_escape),
        error="AtlasPanelInputError"
    )


@requires_impl
def test_ps_x_004_inputs_are_never_mutated_and_stay_frozen(tmp_path: Path) -> None:
    """PS-X-004: loaded structures are deep-frozen and the caller's world is not touched."""

    world = build_world(tmp_path)
    inputs = world.inputs()
    before = world.snapshot()
    run = _select(world)
    assert world.snapshot() == before, "select_panel rewrote one of its own inputs"

    with pytest.raises(Exception):
        inputs.node_budget_override = 5  # type: ignore[misc]

    registration = _sut("load_selection_registration")(world.registration_path)
    with pytest.raises(TypeError):
        registration["schema"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        registration["panel_size_rule"]["min"] = 0  # type: ignore[index]
    assert isinstance(registration["never_relaxed"], tuple)

    universe = _sut("load_candidate_universe")(world.universe_path)
    with pytest.raises(TypeError):
        universe["records"][0]["primary_stratum"] = "S1"  # type: ignore[index]
    assert isinstance(universe["records"], tuple)

    with pytest.raises(Exception):
        run.selected_record_ids = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        getattr(run, "preconditions").active_universe_lock["path"] = "x"  # type: ignore[index]


@requires_impl
def test_ps_x_005_no_failure_path_ever_repairs_an_input(tmp_path: Path) -> None:
    """PS-X-005 ADVERSARIAL: every stale artifact stays stale, byte for byte."""

    cases: list[tuple[str, Callable[[_World], None]]] = [
        ("registration", lambda w: w.tamper_yaml(
            w.registration_path, lambda p: p.__setitem__("registrar_role", "tampered"))),
        ("universe_lock", lambda w: w.tamper_yaml(
            w.universe_lock_path, lambda p: p.__setitem__("created_by_role", "tampered"))),
        ("universe", lambda w: w.tamper_yaml(
            w.universe_path, lambda p: p.__setitem__("universe_id", "tampered"))),
        ("map", lambda w: w.tamper_yaml(
            w.map_path, lambda p: p.__setitem__("map_id", "tampered"))),
        ("map_lock", lambda w: w.tamper_yaml(
            w.map_lock_path, lambda p: p.__setitem__("created_at", "2026-05-02T00:00:00Z"))),
    ]
    for name, tamper in cases:
        world = build_world(tmp_path / name)
        tamper(world)
        stale = world.snapshot()
        _expect(world, lambda: _select(world), error="AtlasPanelError")
        assert world.snapshot() == stale, f"{name}: the selector rewrote a stale artifact"


@requires_impl
def test_ps_x_006_this_module_embeds_no_real_biological_entity(tmp_path: Path) -> None:
    """PS-X-006: the fixture purity scan, with every needle built from parts."""

    text = THIS_FILE.read_text(encoding="utf-8")

    accession = re.compile(r"\bN" + r"[MPCGR]_\d{4,}(?:\.\d+)?")
    for match in accession.findall(text):
        assert match == _SYN_SEQ_ACC, f"real-looking accession literal: {match}"

    for stem, suffix in (("TS", "C2"), ("TS", "C1"), ("BRC", "A1"), ("MT", "OR"),
                         ("PT", "EN"), ("TP", "53"), ("KRA", "S"), ("EGF", "R")):
        needle = stem + suffix
        assert needle.lower() not in text.lower(), f"real gene/locus token present: {needle}"

    for pattern in (r"c\." + r"\d+[ACGT]>[ACGT]", r"p\.[A-Z][a-z]{2}\d+",
                    "PM" + r"ID:?\s*\d+", r"\b10\.\d{4,}/\S+"):
        assert not re.search(pattern, text), f"real-looking literal matching {pattern}"

    # Textual absence is not enough: every identity this module CONSTRUCTS must
    # also be bound to the synthetic transcript/protein, never to a real one.
    sample = _rec("rec-purity", residue=7)
    assert sample["hgvs_c"].startswith(SYN_TRANSCRIPT + ":"), sample["hgvs_c"]
    assert sample["hgvs_p"].startswith(SYN_PROTEIN + ":"), sample["hgvs_p"]
    assert sample["_transcript_pin"] == SYN_TRANSCRIPT
    assert sample["spdi_canonical"].startswith(_SYN_SEQ_ACC + ":"), sample["spdi_canonical"]
    assert _rec("rec-purity-unresolved", residue=None)["hgvs_c"] is None

    assert "clin" + "var" not in text.lower()
    assert ("gr" + "ch") not in text.lower()
    for name in ("SYN_GENE", "SYN_TRANSCRIPT", "SYN_PROTEIN", "SYN_ASSEMBLY"):
        assert globals()[name].startswith("SYN"), name

    tree = _module_ast()
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    record_ids = {value for value in literals if re.fullmatch(r"rec-[a-z0-9]+", value)}
    assert record_ids, "the scan found no synthetic record ids at all"
    assert all(value.startswith("rec-") for value in record_ids)


@requires_impl
def test_ps_x_007_tracked_hash_artifacts_are_unchanged(tmp_path: Path) -> None:
    """PS-X-007 REGRESSION: pack, catalog and profile hashing still self-verify."""

    packs = _live_pack_paths()
    assert packs, "no tracked pack manifest was found"
    live_hashes = set()
    for path in packs:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert _atlas_pack.pack_content_hash(manifest) == manifest["pack_content_hash"], path
        assert _sut("canonical_content_hash")(manifest, self_key="pack_content_hash") == manifest[
            "pack_content_hash"
        ], path
        live_hashes.add(manifest["pack_content_hash"])

    catalogs = sorted((REPO_ROOT / "configs" / "atlas" / "catalogs").glob("*/catalog.yaml"))
    assert catalogs, "no tracked catalog manifest was found"
    for path in catalogs:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert _atlas_pkg.catalog_content_hash(manifest) == manifest["catalog_content_hash"], path

    registration = yaml.safe_load(REGISTRATION_PATH.read_text(encoding="utf-8"))
    assert registration["pack_binding_observed_at_freeze"]["pack_content_hash"] in live_hashes
    assert callable(_atlas_pkg.profile_envelope_hash)
    assert _atlas_pkg.pack_content_hash is _atlas_pack.pack_content_hash


@requires_impl
def test_ps_x_008_a_raised_node_budget_is_an_input_fault(tmp_path: Path) -> None:
    """PS-X-008 ADVERSARIAL: the override may only ever lower the budget."""

    world = build_world(tmp_path / "raise", node_budget=1000)
    raised = _expect(
        world,
        lambda: _select(world, node_budget_override=1001),
        error="AtlasPanelInputError",
    )
    text = f"{getattr(raised, 'code', '')} {raised}".lower()
    assert "budget" in text, f"the fault does not name the budget: {text!r}"

    lowered = build_world(tmp_path / "lower", node_budget=1000)
    run = _select(lowered, node_budget_override=999)
    assert getattr(run, "terminal_outcome") in (
        "PANEL_SELECTED",
        "UNDETERMINED_SEARCH_INCOMPLETE",
    )
    for attempt in getattr(run, "attempts"):
        assert attempt.nodes_expanded <= 999, attempt
    rendered = _run_record(lowered, run, node_budget_override=999)
    assert "999" in _stable_json(rendered["procedure"]), "the lowered budget was not recorded"

    equal = build_world(tmp_path / "equal", node_budget=1000)
    assert getattr(_select(equal, node_budget_override=1000), "terminal_outcome") is not None


@requires_impl
def test_ps_x_009_a_ranked_universe_is_rejected_although_it_hashes(tmp_path: Path) -> None:
    """PS-X-009 ADVERSARIAL: a clean hash never launders a prohibited field."""

    def rank(universe: dict) -> None:
        universe["records"][0]["recommended_rank"] = 1
        universe["records"][0]["priority_score"] = 0.97

    world = build_world(tmp_path, on_universe=rank)
    manifest = world.read_yaml(world.universe_path)
    assert manifest["records"][0]["recommended_rank"] == 1
    assert _canonical_hash(manifest, "universe_content_hash") == manifest["universe_content_hash"], (
        "the fixture must present a universe whose own hash verifies"
    )
    assert _sut("candidate_universe_content_hash")(manifest) == manifest["universe_content_hash"]

    _expect(
        world,
        lambda: _select(world),
        error="AtlasUniverseContractError",
        code="UNIVERSE_CONTRACT_BREACH",
    )


# ---------------------------------------------------------------------------
# PS-I-* tracked-artifact integration (spec gap G5: realised in-file, one-file rule)
# ---------------------------------------------------------------------------


def _real_registration() -> dict[str, Any]:
    return yaml.safe_load(REGISTRATION_PATH.read_text(encoding="utf-8"))


def _real_yaml(relative: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))


@requires_impl
def test_ps_i_001_tracked_registration_resolves_and_mirrors_both_locks(tmp_path: Path) -> None:
    """PS-I-001: registration -> universe lock v4 + identity-map lock v4, mirrored."""

    registration = _real_registration()
    loaded_registration = _sut("load_selection_registration")(REGISTRATION_PATH)
    assert loaded_registration["schema"] == "atlas.panel_selection_registration.v1"

    assert _sut("protocol_doc_hash")(PROTOCOL_PATH) == registration["protocol_doc_hash"]
    assert _sut("registration_content_hash")(registration) == registration[
        "registration_content_hash"
    ]

    lock_path, lock = _sut("resolve_active_lock")(registration, repo_root=REPO_ROOT)
    active = registration["candidate_universe_contract"]["universe_lock"]["active"]
    assert Path(lock_path) == (REPO_ROOT / active["path"])
    assert _sut("universe_lock_content_hash")(lock) == lock["lock_content_hash"]
    assert lock["lock_content_hash"] == active["lock_content_hash"]
    for field in ("lock_id", "lock_version", "universe_id", "universe_version",
                  "universe_content_hash", "created_at", "created_by_role", "storage_location"):
        assert str(lock[field]) == str(active[field]), field
    assert dict(lock["pack_binding"]) == dict(active["pack_binding"])
    im_binding = lock["identity_map_binding"]
    active_im_binding = active["identity_map_binding"]
    for im6_field in ("schema", "map_id", "map_version", "lock_id", "lock_version",
                      "map_content_hash", "lock_content_hash", "response_bundle_hash",
                      "map_record_count"):
        assert im_binding[im6_field] == active_im_binding[im6_field], im6_field
    assert dict(im_binding["pack_binding"]) == dict(lock["pack_binding"])

    map_active = registration["identity_map_contract"]["active"]
    map_lock = _real_yaml(map_active["path"])

    assert lock["identity_map_binding"]["schema"] == map_lock["schema"], "IM6 schema must bind to map_lock, not map_manifest"

    assert _atlas_pkg.identity_map_lock_content_hash(map_lock) == map_lock["lock_content_hash"]
    assert map_lock["lock_content_hash"] == map_active["lock_content_hash"]
    for field in ("lock_id", "lock_version", "map_id", "map_version", "map_content_hash",
                  "response_bundle_hash", "created_at"):
        assert str(map_lock[field]) == str(map_active[field]), field
    assert map_lock["lock_content_hash"] == lock["identity_map_binding"]["lock_content_hash"]
    assert registration["identity_map_contract"]["map_storage"]["tracked_in_repository"] is False

    # Real universe-shape integration coverage (synthetic proxy)
    world = build_world(tmp_path / "universe_shape")
    universe = yaml.safe_load(world.universe_path.read_text(encoding="utf-8"))
    assert "transcript_pin" in universe, "Universe v4 top-level transcript pin must be present"
    for rec in universe["records"]:
        assert "transcript_pin" not in rec, "Universe v4 records must omit per-record transcript_pin"


@requires_impl
def test_ps_i_002_real_k5_delta_chain_is_gap_free(tmp_path: Path) -> None:
    """PS-I-002: the lock-time -> current chain is complete and contiguous."""

    registration = _real_registration()
    _, lock = _sut("resolve_active_lock")(registration, repo_root=REPO_ROOT)
    delta = _sut("build_lock_delta")(
        lock=lock,
        registration=registration,
        verified_protocol_doc_hash=registration["protocol_doc_hash"],
        verified_registration_content_hash=registration["registration_content_hash"],
    )
    assert getattr(delta, "lock_protocol_version") == lock["protocol_version"]
    assert getattr(delta, "lock_protocol_doc_hash") == lock["protocol_doc_hash"]
    assert getattr(delta, "lock_registration_content_hash") == lock["registration_content_hash"]
    assert getattr(delta, "current_protocol_version") == registration["protocol_version"]
    assert getattr(delta, "differs") is True

    chain = tuple(getattr(delta, "reconciled_via_amendment_log_versions"))
    declared = tuple(
        registration["lock_protocol_version_delta_contract"]["expected_delta_for_active_lock"][
            "reconciled_via_amendment_log_versions"
        ]
    )
    assert chain == declared, f"{chain} != registration-declared {declared}"

    log_versions = [str(entry["version"]) for entry in registration["amendment_log"]]
    assert chain, "an empty chain cannot reconcile a differing lock"
    assert set(chain) <= set(log_versions)
    start = log_versions.index(str(lock["protocol_version"]))
    assert tuple(log_versions[start + 1:]) == chain, "the chain skips an amendment"
    assert chain[-1] == registration["protocol_version"]


@requires_impl
def test_ps_i_003_the_real_mapper_seam_cannot_be_bypassed(tmp_path: Path) -> None:
    """PS-I-003 (gap G5): no synthetic run can certify the real mapper."""

    field_names = {f.name for f in dataclass_fields(_sut("SelectionInputs"))}
    assert not [n for n in field_names if "mapper" in n], field_names
    signature = inspect.signature(_sut("select_panel"))
    assert list(signature.parameters) == ["inputs"], signature
    assert not [n for n in signature.parameters if "mapper" in n]

    source = PANEL_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    verify = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "verify_identity_map"),
        None,
    )
    assert verify is not None, "SPEC GAP or missing surface: verify_identity_map"
    called = {_dotted(n.func).split(".")[-1] for n in ast.walk(verify) if isinstance(n, ast.Call)}
    assert "load_identity_map" in called, sorted(called)
    assert not [name for name in called if name.endswith("Mapper") and name != "RawIdentityMapper"]

    module_names = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any((name or "").startswith("tests") for name in module_names)

    decorators = {
        _dotted(dec.func) if isinstance(dec, ast.Call) else _dotted(dec)
        for node in _module_ast().body
        if isinstance(node, ast.FunctionDef)
        for dec in node.decorator_list
    }
    assert not any("external" in d for d in decorators), sorted(decorators)


@requires_impl
def test_ps_i_004_preconditions_alone_write_nothing(tmp_path: Path) -> None:
    """PS-I-004 (gap G5): verify_preconditions stops before any search or write."""

    data_root = REPO_ROOT / "data"
    before = sorted(str(p) for p in data_root.rglob("*")) if data_root.exists() else []

    world = build_world(tmp_path)
    snapshot = world.snapshot()
    report = _preconditions(world)
    assert world.snapshot() == snapshot, "verify_preconditions wrote to its own inputs"

    assert type(report).__name__ == "PreconditionReport"
    for absent in ("selected_record_ids", "attempts", "terminal_outcome", "dispositions"):
        assert not hasattr(report, absent), f"a precondition report exposed {absent}"

    order = tuple(world.registration["executor_preconditions"]["execution_order"])
    assert order == EXECUTION_ORDER
    checks = _checks(report)
    positions = [checks.index(check) for check in order if check in checks]
    assert positions == sorted(positions), checks
    assert {"V1", "V2", "V3", "V4"} <= set(checks)

    after = sorted(str(p) for p in data_root.rglob("*")) if data_root.exists() else []
    assert after == before, "a run record was written by a precondition-only call"


@requires_impl
def test_ps_i_005_the_invalid_binding_lock_is_never_admissible(tmp_path: Path) -> None:
    """PS-I-005 ADVERSARIAL: lock v3 self-verifies yet is protocol-unknown."""

    registration = _real_registration()
    superseded = registration["candidate_universe_contract"]["universe_lock"]["superseded"]
    invalid = next(entry for entry in superseded if entry.get("status") == "invalid_binding")
    invalid_lock = _real_yaml(invalid["path"])

    assert _sut("universe_lock_content_hash")(invalid_lock) == invalid_lock["lock_content_hash"]
    log_versions = [str(entry["version"]) for entry in registration["amendment_log"]]
    assert str(invalid_lock["protocol_version"]) in log_versions, (
        "the fixture must present a lock whose version DOES appear in the log"
    )

    error = _sut("AtlasUniverseLockError")
    with pytest.raises(error) as excinfo:
        _sut("build_lock_delta")(
            lock=invalid_lock,
            registration=registration,
            verified_protocol_doc_hash=registration["protocol_doc_hash"],
            verified_registration_content_hash=registration["registration_content_hash"],
        )
    raised = excinfo.value
    assert "UNIVERSE_LOCK_PROTOCOL_UNKNOWN" in f"{getattr(raised, 'code', '')} {raised}"

    _, active_lock = _sut("resolve_active_lock")(registration, repo_root=REPO_ROOT)
    active_delta = _sut("build_lock_delta")(
        lock=active_lock,
        registration=registration,
        verified_protocol_doc_hash=registration["protocol_doc_hash"],
        verified_registration_content_hash=registration["registration_content_hash"],
    )
    chain = tuple(getattr(active_delta, "reconciled_via_amendment_log_versions"))
    assert str(invalid_lock["protocol_version"]) not in chain, chain
    assert str(invalid_lock["lock_version"]) != str(active_lock["lock_version"])


# ---------------------------------------------------------------------------
# Traceability: every declared spec ID -> exactly one substantive test.
#
# The map is 1:1 by construction (asserted below): 106 IDs, 106 targets, no
# duplicate keys and no duplicate values.  Grouping several IDs under one test
# is permitted by the remediation brief, but is deliberately NOT used here --
# each declared case has its own executable body.
# ---------------------------------------------------------------------------

TRACEABILITY: dict[str, str] = {
    "PS-A-001": "test_ps_a_001_allocation_enumeration_and_order",
    "PS-A-002": "test_ps_a_002_draw_key_and_global_order",
    "PS-A-003": "test_ps_a_003_only_solution_in_the_last_branch_is_found",
    "PS-A-004": "test_ps_a_004_non_hereditary_minimums_never_prune",
    "PS-A-005": "test_ps_a_005_hereditary_pruning_matches_a_brute_force_oracle",
    "PS-A-006": "test_ps_a_006_collisions_resolve_by_draw_order_only",
    "PS-A-007": "test_ps_a_007_infeasible_complete_requires_exhaustion",
    "PS-A-008": "test_ps_a_008_search_scope_guard_runs_before_any_attempt",
    # --- D: dispositions, run record, CLI boundary
    "PS-D-001": "test_ps_d_001_one_disposition_row_per_universe_record",
    "PS-D-002": "test_ps_d_002_rows_carry_rule_ids_and_selected_rows_carry_slots",
    "PS-D-003": "test_ps_d_003_run_record_carries_every_digest_and_the_full_delta",
    "PS-D-004": "test_ps_d_004_cli_refuses_to_overwrite_a_run_record",
    "PS-D-005": "test_ps_d_005_flags_are_computed_not_declared",
    # --- E: eligibility
    "PS-E-001": "test_ps_e_001_each_rule_yields_its_exclusion_code",
    "PS-E-002": "test_ps_e_002_anchor_residue_is_driven_by_the_injected_spec",
    "PS-E-003": "test_ps_e_003_access_blocked_versus_genuine_abstention",
    "PS-E-004": "test_ps_e_004_eligible_but_not_selected_is_never_an_exclusion",
    "PS-E-005": "test_ps_e_005_external_label_contradiction_is_report_only",
    "PS-E-006": "test_ps_e_006_recomputed_label_contradiction_is_fatal",
    # --- I: integration against tracked artifacts
    "PS-I-001": "test_ps_i_001_tracked_registration_resolves_and_mirrors_both_locks",
    "PS-I-002": "test_ps_i_002_real_k5_delta_chain_is_gap_free",
    "PS-I-003": "test_ps_i_003_the_real_mapper_seam_cannot_be_bypassed",
    "PS-I-004": "test_ps_i_004_preconditions_alone_write_nothing",
    "PS-I-005": "test_ps_i_005_the_invalid_binding_lock_is_never_admissible",
    # --- K: universe-lock binding and the K5 delta
    "PS-K-001": "test_ps_k_001_lock_resolved_from_registration_pointer",
    "PS-K-002": "test_ps_k_002_missing_and_corrupt_lock",
    "PS-K-003": "test_ps_k_003_lock_hash_must_match_registration_mirror",
    "PS-K-004": "test_ps_k_004_lock_binding_field_mismatches",
    "PS-K-005": "test_ps_k_005_lock_pack_binding_drift",
    "PS-K-006": "test_ps_k_006_duplicate_lock_for_one_universe_version",
    "PS-K-007": "test_ps_k_007_lock_created_after_run_start",
    "PS-K-008": "test_ps_k_008_delta_shape_is_complete_even_when_equal",
    "PS-K-009": "test_ps_k_009_incomplete_delta_is_rejected",
    "PS-K-010": "test_ps_k_010_unknown_lock_triple_is_rejected",
    "PS-K-011": "test_ps_k_011_valid_delta_does_not_waive_other_lock_checks",
    "PS-K-012": "test_ps_k_012_chain_must_be_gap_free",
    "PS-K-013": "test_ps_k_013_k5_is_universe_lock_only",
    # --- L: lineage and support class
    "PS-L-001": "test_ps_l_001_each_edge_rule_forms_a_component",
    "PS-L-002": "test_ps_l_002_group_key_is_stable_under_renaming_and_reordering",
    "PS-L-003": "test_ps_l_003_unknown_lineage_pools_into_one_group",
    "PS-L-004": "test_ps_l_004_declared_groups_are_only_comparands",
    "PS-L-005": "test_ps_l_005_support_class_recomputes_across_all_five_values",
    # --- M: identity-map lock binding (IM1-IM6)
    "PS-M-001": "test_ps_m_001_map_lock_resolved_from_registration",
    "PS-M-002": "test_ps_m_002_map_lock_absent_corrupt_or_unmirrored",
    "PS-M-003": "test_ps_m_003_stale_map_version_is_never_a_fallback",
    "PS-M-004": "test_ps_m_004_lock_to_map_field_disagreements",
    "PS-M-005": "test_ps_m_005_response_bundle_drift_is_detected_from_disk",
    "PS-M-006": "test_ps_m_006_map_pack_and_reference_binding",
    "PS-M-007": "test_ps_m_007_map_to_raw_bijection",
    "PS-M-008": "test_ps_m_008_universe_lock_identity_map_binding",
    "PS-M-009": "test_ps_m_009_mapper_fault_never_becomes_a_candidate_property",
    "PS-M-010": "test_ps_m_010_identity_map_verified_before_replay",
    # --- O: outcome, schedule and relaxation
    "PS-O-001": "test_ps_o_001_schedule_is_level_major_and_size_descending",
    "PS-O-002": "test_ps_o_002_undetermined_at_l0_stops_with_no_relaxation",
    "PS-O-003": "test_ps_o_003_infeasible_panel_still_emits_a_complete_record",
    "PS-O-004": "test_ps_o_004_relaxed_levels_are_stamped_and_recorded",
    "PS-O-005": "test_ps_o_005_never_relaxed_items_are_unreachable",
    "PS-O-006": "test_ps_o_006_n_selected_follows_a_solution_and_stays_in_bounds",
    "PS-O-007": "test_ps_o_007_abstention_control_is_required_or_flagged",
    "PS-O-008": "test_ps_o_008_access_blocked_never_serves_as_the_control",
    # --- P: properties and metamorphic relations
    "PS-P-001": "test_ps_p_001_two_runs_are_byte_identical_apart_from_provenance",
    "PS-P-002": "test_ps_p_002_record_and_observation_order_is_irrelevant",
    "PS-P-003": "test_ps_p_003_identity_preserving_renaming_changes_nothing",
    "PS-P-004": "test_ps_p_004_canonical_hash_agrees_with_the_shipped_pack_hash",
    "PS-P-005": "test_ps_p_005_returned_solutions_satisfy_every_active_constraint",
    "PS-P-006": "test_ps_p_006_completeness_matches_a_brute_force_oracle",
    "PS-P-007": "test_ps_p_007_lowering_the_budget_only_ever_yields_undetermined",
    "PS-P-008": "test_ps_p_008_panel_is_invariant_under_within_record_permutation",
    # --- R: replay through the verified mapper (RP1-RP7)
    "PS-R-001": "test_ps_r_001_replayed_outcome_must_equal_ledger",
    "PS-R-002": "test_ps_r_002_surrogate_key_normalization_has_no_case_fold",
    "PS-R-003": "test_ps_r_003_identity_state_is_confirmed_in_both_directions",
    "PS-R-004": "test_ps_r_004_identity_fields_are_character_identical",
    "PS-R-005": "test_ps_r_005_consequence_and_scope_come_from_the_map",
    "PS-R-006": "test_ps_r_006_undecidable_mapper_is_a_tool_failure",
    "PS-R-007": "test_ps_r_007_exclusion_flags_and_duplicate_collapse",
    "PS-R-008": "test_ps_r_008_replay_mismatch_is_reported_never_repaired",
    "PS-R-009": "test_ps_r_009_replay_uses_the_map_not_the_universe",
    # --- S: strata, Omega precedence and the metadata firewall
    "PS-S-001": "test_ps_s_001_each_stratum_fires_from_primitives",
    "PS-S-002": "test_ps_s_002_substantial_versus_intermediate_is_a_differing_pair",
    "PS-S-003": "test_ps_s_003_all_matched_is_emitted_in_omega_order",
    "PS-S-004": "test_ps_s_004_primary_is_the_first_element_under_omega",
    "PS-S-005": "test_ps_s_005_declared_primary_is_only_a_comparand",
    "PS-S-006": "test_ps_s_006_firewall_fields_are_structurally_unreachable",
    "PS-S-007": "test_ps_s_007_evidence_presence_must_match_observations",
    # --- U: universe contract (U1-U7)
    "PS-U-001": "test_ps_u_001_raw_inventory_hash_and_count",
    "PS-U-002": "test_ps_u_002_ledger_is_a_bijection_onto_raw_rows",
    "PS-U-003": "test_ps_u_003_ledger_key_set_equals_record_key_set",
    "PS-U-004": "test_ps_u_004_discovery_commitment_over_sorted_distinct_keys",
    "PS-U-005": "test_ps_u_005_universe_self_hash_and_attestation",
    "PS-U-006": "test_ps_u_006_prohibited_universe_content",
    # --- V: preconditions in registration-pinned order
    "PS-V-001": "test_ps_v_001_protocol_digest_mismatch",
    "PS-V-002": "test_ps_v_002_registration_self_hash_mismatch",
    "PS-V-003": "test_ps_v_003_seed_mismatch",
    "PS-V-004": "test_ps_v_004_pack_drift_against_each_comparand",
    "PS-V-005": "test_ps_v_005_checks_short_circuit_in_registration_order",
    "PS-V-006": "test_ps_v_006_precondition_report_is_all_or_nothing",
    "PS-V-007": "test_ps_v_007_no_mapper_injection_seam",
    # --- X: purity and adversarial
    "PS-X-001": "test_ps_x_001_core_module_is_statically_pure",
    "PS-X-002": "test_ps_x_002_repository_import_guards_stay_clean",
    "PS-X-003": "test_ps_x_003_path_safety_is_enforced_on_every_supplied_path",
    "PS-X-004": "test_ps_x_004_inputs_are_never_mutated_and_stay_frozen",
    "PS-X-005": "test_ps_x_005_no_failure_path_ever_repairs_an_input",
    "PS-X-006": "test_ps_x_006_this_module_embeds_no_real_biological_entity",
    "PS-X-007": "test_ps_x_007_tracked_hash_artifacts_are_unchanged",
    "PS-X-008": "test_ps_x_008_a_raised_node_budget_is_an_input_fault",
    "PS-X-009": "test_ps_x_009_a_ranked_universe_is_rejected_although_it_hashes",
}


# ---------------------------------------------------------------------------
# Meta tests.
#
# These are deliberately NOT gated on the implementation: they police this test
# module itself, so they must run in the RED phase -- that is precisely when a
# hollow or mis-mapped suite would otherwise slip through.
# ---------------------------------------------------------------------------

_SUT_CALL_NAMES = frozenset(
    {
        "_sut",
        "_select",
        "_preconditions",
        "_run_record",
        "_cli_module",
        "build_world",
        "_real_registration",
        "_oracle_first_solution",
        "_oracle_schedule",
        "_brute_force_solutions",
        "_core_purity_violations",
        "_module_ast",
        "assert_no_network_imports",
        "assert_atlas_import_boundary",
        "assert_no_consumer_import",
    }
)

# `_expect` drives the SUT *and* asserts the raised error, code and check id.
_ASSERTION_HELPERS = frozenset({"_expect"})

_BEHAVIOUR_FREE_NAMES = frozenset({"hasattr", "getattr", "isinstance", "callable"})

# Needles are assembled from parts so that this constant never matches itself.
_REAL_ENTITY_TOKENS = tuple(
    (stem + suffix).lower()
    for stem, suffix in (
        ("ts", "c2"), ("ts", "c1"), ("brc", "a1"), ("mt", "or"), ("pt", "en"),
        ("tp", "53"), ("kra", "s"), ("egf", "r"), ("clin", "var"), ("gr", "ch"),
        ("hg", "38"), ("ense", "mbl"), ("omi", "m:"), ("hgn", "c:"),
    )
)


def _traceability_literal() -> ast.Dict:
    """Return the AST node of the TRACEABILITY dict literal (not the evaluated value)."""

    for node in _module_ast().body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            first = node.targets[0]
            target = first.id if isinstance(first, ast.Name) else None
        if target == "TRACEABILITY":
            assert isinstance(node.value, ast.Dict), "TRACEABILITY must be a literal dict"
            return node.value
    raise AssertionError("TRACEABILITY literal not found in this module")


def _body_statements(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(func.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    return body


def _is_hollow(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _body_statements(func)
    if not body:
        return True
    for statement in body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            if statement.value.value is Ellipsis:
                continue
        return False
    return True


def _behaviour_counts(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    counts = {"assert": 0, "raises": 0, "expect": 0, "sut": 0, "call": 0}
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            counts["assert"] += 1
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            leaf = dotted.split(".")[-1]
            if dotted in {"pytest.raises", "pytest.warns"}:
                counts["raises"] += 1
            elif leaf in _ASSERTION_HELPERS:
                counts["expect"] += 1
            elif leaf in _SUT_CALL_NAMES:
                counts["sut"] += 1
            elif leaf and leaf not in _BEHAVIOUR_FREE_NAMES:
                counts["call"] += 1
    return counts


def _meta_test_names(functions: Mapping[str, ast.FunctionDef]) -> list[str]:
    return sorted(name for name in functions if name.startswith("test_meta_"))


def _assert_meta_tests_are_ungated(functions: Mapping[str, ast.FunctionDef]) -> None:
    """Every meta test polices the others' gating, so silencing one is not enough."""

    metas = _meta_test_names(functions)
    assert metas == [
        "test_meta_module_is_synthetic",
        "test_meta_no_hollow_tests",
        "test_meta_targets_assert_behaviour",
        "test_meta_traceability_covers_every_spec_id",
    ], metas
    for name in metas:
        decorators = {
            _dotted(d.func) if isinstance(d, ast.Call) else _dotted(d)
            for d in functions[name].decorator_list
        }
        assert not any("skip" in d or "requires_impl" == d for d in decorators), (name, decorators)


def test_meta_traceability_covers_every_spec_id() -> None:
    """Every declared PS-* ID maps to exactly one existing substantive test."""

    declared = _spec_ids()
    assert len(declared) == 106, f"expected 106 declared spec ids, found {len(declared)}"
    assert set(TRACEABILITY) == set(declared), {
        "missing": sorted(set(declared) - set(TRACEABILITY)),
        "extra": sorted(set(TRACEABILITY) - set(declared)),
    }
    assert len(TRACEABILITY) == len(declared)

    literal = _traceability_literal()
    keys = [k.value for k in literal.keys if isinstance(k, ast.Constant)]
    assert len(keys) == len(literal.keys), "every TRACEABILITY key must be a plain string literal"
    assert len(keys) == len(set(keys)), "duplicate key in the TRACEABILITY literal"
    assert len(keys) == len(declared)

    functions = _function_nodes(_module_ast())
    _assert_meta_tests_are_ungated(functions)
    for ident, target in sorted(TRACEABILITY.items()):
        assert target in functions, f"{ident} -> missing function {target}"
        assert target in globals(), f"{ident} -> {target} is not importable at module level"
        assert callable(globals()[target]), f"{ident} -> {target} is not callable"

    substantive = {name for name in functions if name.startswith("test_ps_")}
    targets = set(TRACEABILITY.values())
    assert targets == substantive, {
        "unmapped_tests": sorted(substantive - targets),
        "targets_that_are_not_tests": sorted(targets - substantive),
    }
    assert len(targets) == len(TRACEABILITY), "a target is reused by two spec ids"

    prefixes = collections.Counter(ident.split("-")[1] for ident in TRACEABILITY)
    assert prefixes == {
        "A": 8, "D": 5, "E": 6, "I": 5, "K": 13, "L": 5, "M": 10,
        "O": 8, "P": 8, "R": 9, "S": 7, "U": 6, "V": 7, "X": 9,
    }, dict(prefixes)


def test_meta_targets_assert_behaviour() -> None:
    """No target may pass by existing: each asserts behaviour and exercises the SUT."""

    functions = _function_nodes(_module_ast())
    _assert_meta_tests_are_ungated(functions)
    thin: list[str] = []
    detached: list[str] = []
    for ident, target in sorted(TRACEABILITY.items()):
        func = functions[target]
        assert not _is_hollow(func), f"{ident} -> {target} is hollow"
        counts = _behaviour_counts(func)
        behaviour = counts["assert"] + counts["raises"] + counts["expect"]
        contact = counts["sut"] + counts["expect"]
        if behaviour < 1:
            thin.append(f"{ident}:{target}(no assertion)")
        if contact < 1:
            detached.append(f"{ident}:{target}")
        if behaviour + contact < 2:
            thin.append(f"{ident}:{target}(too few checks)")
    assert not thin, thin
    assert not detached, detached

    # The scanner itself must be falsifiable, otherwise the loop above is empty.
    probe = ast.parse(
        "def test_placeholder():\n"
        '    """doc."""\n'
        "    pass\n"
        "def test_existence_only():\n"
        "    assert hasattr(object, 'mro')\n"
        "def test_real(tmp_path):\n"
        "    world = build_world(tmp_path)\n"
        "    assert _select(world) is not None\n"
    )
    probed = _function_nodes(probe)
    assert _is_hollow(probed["test_placeholder"])
    assert _behaviour_counts(probed["test_existence_only"])["sut"] == 0
    assert _behaviour_counts(probed["test_existence_only"])["expect"] == 0
    assert _behaviour_counts(probed["test_real"])["sut"] >= 1
    assert _behaviour_counts(probed["test_real"])["assert"] >= 1


def test_meta_no_hollow_tests() -> None:
    """Hollow scan: not one test function in this module is pass/ellipsis-only."""

    functions = _function_nodes(_module_ast())
    tests = {name: node for name, node in functions.items() if name.startswith("test_")}
    assert len(tests) >= 107, f"unexpectedly few tests: {len(tests)}"
    hollow = sorted(name for name, node in tests.items() if _is_hollow(node))
    assert hollow == [], hollow

    docstring_only = sorted(name for name, node in tests.items() if not _body_statements(node))
    assert docstring_only == []

    red = [name for name in tests if name.startswith("test_red_")]
    assert len(red) == 1, red
    metas = _meta_test_names(functions)
    assert len(tests) == len(TRACEABILITY) + len(red) + len(metas), sorted(tests)

    # Meta tests must never be gated, or the hollow scan would vanish in RED.
    _assert_meta_tests_are_ungated(functions)
    for name in red:
        decorators = {_dotted(d.func) if isinstance(d, ast.Call) else _dotted(d)
                      for d in functions[name].decorator_list}
        assert "requires_impl" not in decorators, f"{name} must not be skipped in the RED phase"

    # Every substantive test must be gated, so the RED boundary stays singular.
    for name in TRACEABILITY.values():
        decorators = {_dotted(d.func) if isinstance(d, ast.Call) else _dotted(d)
                      for d in functions[name].decorator_list}
        assert "requires_impl" in decorators, f"{name} is not gated on the implementation"


def test_meta_module_is_synthetic() -> None:
    """No real biological identifier or expected panel may be embedded here."""

    text = THIS_FILE.read_text(encoding="utf-8")
    _assert_meta_tests_are_ungated(_function_nodes(_module_ast()))
    lowered = text.lower()
    for token in _REAL_ENTITY_TOKENS:
        assert token not in lowered, f"real-world token {token!r} leaked into the test module"

    assert _SYN_SEQ_ACC.startswith("NC_" + "9999"), _SYN_SEQ_ACC
    accessions = set(re.findall(r"\bN[CMPGR]_\d+\.\d+\b", text))
    assert accessions <= {_SYN_SEQ_ACC}, accessions

    hgvs = re.findall(r"\bc\.\d+[ACGT]>[ACGT]\b", text) + re.findall(r"\bp\.[A-Z][a-z]{2}\d+", text)
    assert hgvs == [], hgvs
    assert re.findall(r"\b(?:PM" + r"ID|DOI)[:\s]\s*\d", text) == []

    # Every constructed identity is bound to the synthetic reference sequences.
    sample = _rec("rec-meta", residue=5)
    assert sample["hgvs_c"].startswith(SYN_TRANSCRIPT + ":"), sample["hgvs_c"]
    assert sample["hgvs_p"].startswith(SYN_PROTEIN + ":"), sample["hgvs_p"]
    assert sample["spdi_canonical"].startswith(_SYN_SEQ_ACC + ":"), sample["spdi_canonical"]
    assert SYN_GENE.startswith("SYN") and SYN_ASSEMBLY.startswith("SYN")

    identifiers = set(re.findall(r'"(rec-[a-z0-9]+)"', text))
    assert identifiers, "the synthetic fixtures must use rec-* identifiers"
    assert all(i.startswith("rec-") for i in identifiers)
