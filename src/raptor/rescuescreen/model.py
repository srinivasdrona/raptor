"""Immutable models and typed errors for RescueScreen entry-gate status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class RescueScreenError(Exception):
    """Base class for entry-gate status failures."""


class RescueScreenSchemaError(RescueScreenError):
    """The manifest violates the closed entry-gate schema."""


class RescueScreenHashError(RescueScreenError):
    """The manifest's declared self-hash does not match its content."""


class RescueScreenPathError(RescueScreenError):
    """The explicit manifest path is missing, unsafe, or unreadable."""


@dataclass(frozen=True, eq=True)
class GateEvidenceRef:
    artifact_id: str
    artifact_schema: str
    content_hash: str
    reviewed_by: str
    reviewed_at: str


@dataclass(frozen=True, eq=True)
class EntryGateAssessment:
    gate_id: str
    status: str
    fail_state: str
    evidence_refs: tuple[GateEvidenceRef, ...]
    note: str


@dataclass(frozen=True, eq=True)
class EntryGateManifest:
    schema: str
    lane_id: str
    lane_version: str
    manifest_version: str
    created_at: str
    manifest_content_hash: str
    hash_basis: str
    gates: tuple[EntryGateAssessment, ...]
    preservation_rules: tuple[str, ...]


@dataclass(frozen=True, eq=True)
class EntryGateReport:
    schema: str
    lane_id: str
    lane_version: str
    manifest_version: str
    manifest_content_hash: str
    overall_status: str
    first_blocking_gate: Optional[str]
    blocking_fail_state: Optional[str]
    blocking_gates: tuple[str, ...]
    eligible_next_stage: Optional[str]
    stage_execution_authorized: bool
    gates: tuple[EntryGateAssessment, ...]
    validation_ceiling: str
