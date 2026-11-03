from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

JsonObject = dict[str, Any]

ALLOWED_SOURCE_LIFECYCLES = {
    "CONFIRM_PENDING",
    "VERIFIED_ACTIVE",
    "PINNED_HISTORICAL",
    "METADATA_ONLY",
    "ACCESS_BLOCKED",
    "RETIRED",
}

ALLOWED_RECORD_KINDS = {
    "SINGLE_SOURCE",
    "COMPOSITE_MANIFEST",
    "POLICY_SOURCE_REGISTER",
    "METADATA_CATALOG_TEMPLATE",
}


class SourceOpsError(Exception):
    code = "REGISTRY_SCHEMA_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: JsonObject | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = details or {}


class RegistrySchemaError(SourceOpsError):
    code = "REGISTRY_SCHEMA_ERROR"


class RegistryHashMismatch(SourceOpsError):
    code = "REGISTRY_HASH_MISMATCH"


class DeclarationReferenceError(SourceOpsError):
    code = "DECLARATION_REFERENCE_INVALID"


class DeclarationDriftError(SourceOpsError):
    code = "DECLARATION_DRIFT"


class SourceMetadataIncomplete(SourceOpsError):
    code = "SOURCE_METADATA_INCOMPLETE"


class ImmutableHistoryViolation(SourceOpsError):
    code = "IMMUTABLE_HISTORY_VIOLATION"


class ForbiddenRoleFlow(SourceOpsError):
    code = "FORBIDDEN_ROLE_FLOW"


class DanglingConsumerOrSourceError(SourceOpsError):
    code = "DANGLING_CONSUMER_OR_SOURCE"


class ForbiddenCrossLaneClaimError(SourceOpsError):
    code = "FORBIDDEN_CROSS_LANE_CLAIM"


class ConsumerNotFoundError(SourceOpsError):
    code = "CONSUMER_NOT_FOUND"


class SourceBlockedError(SourceOpsError):
    code = "SOURCE_BLOCKED"


class StagedSnapshotError(SourceOpsError):
    code = "STAGED_SNAPSHOT_ERROR"


class VerificationArtifactError(SourceOpsError):
    code = "VERIFICATION_ARTIFACT_ERROR"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RegistrySchemaError(f"{label} must be a mapping")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RegistrySchemaError(f"{label} must be a list")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RegistrySchemaError(f"{label} must be a boolean")
    return value


def _require_str(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise RegistrySchemaError(f"{label} must be a string")
    return value


def _require_allowed_lifecycle(value: Any, label: str) -> str:
    item = _require_str(value, label)
    if item not in ALLOWED_SOURCE_LIFECYCLES:
        raise RegistrySchemaError(f"{label} must be one of {sorted(ALLOWED_SOURCE_LIFECYCLES)}")
    return item


@dataclass(frozen=True, slots=True)
class DeclarationReference:
    path: str
    role: str
    canonical_lf_sha256: str
    authority_scope: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DeclarationReference":
        mapping = _require_mapping(data, "declaration_ref")
        required = {"path", "role", "canonical_lf_sha256", "authority_scope"}
        if required - set(mapping):
            raise RegistrySchemaError(f"declaration_ref missing keys: {sorted(required - set(mapping))}")
        if set(mapping) - required:
            raise RegistrySchemaError(f"declaration_ref has unknown keys")
        return cls(
            path=_require_str(mapping["path"], "declaration_ref.path"),
            role=_require_str(mapping["role"], "declaration_ref.role"),
            canonical_lf_sha256=_require_str(mapping["canonical_lf_sha256"], "declaration_ref.canonical_lf_sha256"),
            authority_scope=_require_str(mapping["authority_scope"], "declaration_ref.authority_scope"),
        )

    def as_dict(self) -> JsonObject:
        return {"path": self.path, "role": self.role, "canonical_lf_sha256": self.canonical_lf_sha256, "authority_scope": self.authority_scope}


@dataclass(frozen=True, slots=True)
class Component:
    component_id: str
    display_name: str
    lifecycle_state: str
    source_role: str
    version_or_snapshot: str
    licence_status: str
    declaration_locator: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Component":
        mapping = _require_mapping(data, "component")
        required = {"component_id", "display_name", "lifecycle_state", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"}
        if required - set(mapping):
            raise RegistrySchemaError(f"component missing keys: {sorted(required - set(mapping))}")
        if set(mapping) - required:
            raise RegistrySchemaError("component has unknown keys")
        return cls(
            component_id=_require_str(mapping["component_id"], "component.component_id"),
            display_name=_require_str(mapping["display_name"], "component.display_name"),
            lifecycle_state=_require_allowed_lifecycle(mapping["lifecycle_state"], "component.lifecycle_state"),
            source_role=_require_str(mapping["source_role"], "component.source_role"),
            version_or_snapshot=_require_str(mapping["version_or_snapshot"], "component.version_or_snapshot"),
            licence_status=_require_str(mapping["licence_status"], "component.licence_status"),
            declaration_locator=_require_str(mapping["declaration_locator"], "component.declaration_locator"),
        )

    def as_dict(self) -> JsonObject:
        return {"component_id": self.component_id, "display_name": self.display_name, "lifecycle_state": self.lifecycle_state, "source_role": self.source_role, "version_or_snapshot": self.version_or_snapshot, "licence_status": self.licence_status, "declaration_locator": self.declaration_locator}


@dataclass(frozen=True, slots=True)
class LicenceInfo:
    status: str
    identifier_or_family: str
    terms_locator: str
    permitted_use: str
    redistribution: str
    cloud_egress: str
    verification_basis: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LicenceInfo":
        mapping = _require_mapping(data, "licence")
        required = {"status", "identifier_or_family", "terms_locator", "permitted_use", "redistribution", "cloud_egress", "verification_basis"}
        if required - set(mapping):
            raise RegistrySchemaError(f"licence missing keys: {sorted(required - set(mapping))}")
        if set(mapping) - required:
            raise RegistrySchemaError("licence has unknown keys")
        return cls(
            status=_require_str(mapping["status"], "licence.status"),
            identifier_or_family=_require_str(mapping["identifier_or_family"], "licence.identifier_or_family"),
            terms_locator=_require_str(mapping["terms_locator"], "licence.terms_locator"),
            permitted_use=_require_str(mapping["permitted_use"], "licence.permitted_use"),
            redistribution=_require_str(mapping["redistribution"], "licence.redistribution"),
            cloud_egress=_require_str(mapping["cloud_egress"], "licence.cloud_egress"),
            verification_basis=_require_str(mapping["verification_basis"], "licence.verification_basis"),
        )

    def as_dict(self) -> JsonObject:
        return {"status": self.status, "identifier_or_family": self.identifier_or_family, "terms_locator": self.terms_locator, "permitted_use": self.permitted_use, "redistribution": self.redistribution, "cloud_egress": self.cloud_egress, "verification_basis": self.verification_basis}


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version_or_snapshot: str
    release_date: str
    retrieved_at: str
    content_pin_status: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ReleaseInfo":
        mapping = _require_mapping(data, "release")
        required = {"version_or_snapshot", "release_date", "retrieved_at", "content_pin_status"}
        if required - set(mapping):
            raise RegistrySchemaError("release missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("release has unknown keys")
        return cls(
            version_or_snapshot=_require_str(mapping["version_or_snapshot"], "release.version_or_snapshot"),
            release_date=_require_str(mapping["release_date"], "release.release_date"),
            retrieved_at=_require_str(mapping["retrieved_at"], "release.retrieved_at"),
            content_pin_status=_require_str(mapping["content_pin_status"], "release.content_pin_status"),
        )

    def as_dict(self) -> JsonObject:
        return {"version_or_snapshot": self.version_or_snapshot, "release_date": self.release_date, "retrieved_at": self.retrieved_at, "content_pin_status": self.content_pin_status}


@dataclass(frozen=True, slots=True)
class AcquisitionInfo:
    method: str
    operator_contract: str
    writes_outside_repository: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AcquisitionInfo":
        mapping = _require_mapping(data, "acquisition")
        required = {"method", "operator_contract", "writes_outside_repository"}
        if required - set(mapping):
            raise RegistrySchemaError("acquisition missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("acquisition has unknown keys")
        return cls(
            method=_require_str(mapping["method"], "acquisition.method"),
            operator_contract=_require_str(mapping["operator_contract"], "acquisition.operator_contract"),
            writes_outside_repository=_require_bool(mapping["writes_outside_repository"], "acquisition.writes_outside_repository"),
        )

    def as_dict(self) -> JsonObject:
        return {"method": self.method, "operator_contract": self.operator_contract, "writes_outside_repository": self.writes_outside_repository}


@dataclass(frozen=True, slots=True)
class RefreshInfo:
    cadence: str
    freshness_sla: str
    last_checked_at: str
    next_check_rule: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RefreshInfo":
        mapping = _require_mapping(data, "refresh")
        required = {"cadence", "freshness_sla", "last_checked_at", "next_check_rule"}
        if required - set(mapping):
            raise RegistrySchemaError("refresh missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("refresh has unknown keys")
        return cls(
            cadence=_require_str(mapping["cadence"], "refresh.cadence"),
            freshness_sla=_require_str(mapping["freshness_sla"], "refresh.freshness_sla"),
            last_checked_at=_require_str(mapping["last_checked_at"], "refresh.last_checked_at"),
            next_check_rule=_require_str(mapping["next_check_rule"], "refresh.next_check_rule"),
        )

    def as_dict(self) -> JsonObject:
        return {"cadence": self.cadence, "freshness_sla": self.freshness_sla, "last_checked_at": self.last_checked_at, "next_check_rule": self.next_check_rule}


@dataclass(frozen=True, slots=True)
class DriftPolicy:
    materiality_basis: str
    actions: tuple[str, ...]
    approval_required: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DriftPolicy":
        mapping = _require_mapping(data, "drift_policy")
        required = {"materiality_basis", "actions", "approval_required"}
        if required - set(mapping):
            raise RegistrySchemaError("drift_policy missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("drift_policy has unknown keys")
        actions = tuple(_require_str(item, "drift_policy.actions[]") for item in _require_list(mapping["actions"], "drift_policy.actions"))
        return cls(materiality_basis=_require_str(mapping["materiality_basis"], "drift_policy.materiality_basis"), actions=actions, approval_required=_require_bool(mapping["approval_required"], "drift_policy.approval_required"))

    def as_dict(self) -> JsonObject:
        return {"materiality_basis": self.materiality_basis, "actions": list(self.actions), "approval_required": self.approval_required}


@dataclass(frozen=True, slots=True)
class RollbackInfo:
    predecessor_source_id: str | None
    immutable_predecessor_required: bool
    rollback_artifact: str
    origin_reason: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RollbackInfo":
        mapping = _require_mapping(data, "rollback")
        required = {"predecessor_source_id", "immutable_predecessor_required", "rollback_artifact", "origin_reason"}
        if required - set(mapping):
            raise RegistrySchemaError("rollback missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("rollback has unknown keys")
        predecessor = mapping["predecessor_source_id"]
        predecessor_value = None if predecessor is None else _require_str(predecessor, "rollback.predecessor_source_id")
        return cls(predecessor_source_id=predecessor_value, immutable_predecessor_required=_require_bool(mapping["immutable_predecessor_required"], "rollback.immutable_predecessor_required"), rollback_artifact=_require_str(mapping["rollback_artifact"], "rollback.rollback_artifact"), origin_reason=_require_str(mapping["origin_reason"], "rollback.origin_reason"))

    def as_dict(self) -> JsonObject:
        return {"predecessor_source_id": self.predecessor_source_id, "immutable_predecessor_required": self.immutable_predecessor_required, "rollback_artifact": self.rollback_artifact, "origin_reason": self.origin_reason}


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    display_name: str
    record_kind: str
    lifecycle_state: str
    owner: str
    authoritative_locator: str
    declaration_refs: tuple[DeclarationReference, ...]
    licence: LicenceInfo
    release: ReleaseInfo
    acquisition: AcquisitionInfo
    refresh: RefreshInfo
    consumers: tuple[str, ...]
    drift_policy: DriftPolicy
    rollback: RollbackInfo
    components: tuple[Component, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    unblock_condition: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    _components_present: bool = field(default=False, repr=False, compare=False, hash=False)
    _blocked_reasons_present: bool = field(default=False, repr=False, compare=False, hash=False)
    _missing_inputs_present: bool = field(default=False, repr=False, compare=False, hash=False)
    _unblock_condition_present: bool = field(default=False, repr=False, compare=False, hash=False)
    _reviewed_by_present: bool = field(default=False, repr=False, compare=False, hash=False)
    _reviewed_at_present: bool = field(default=False, repr=False, compare=False, hash=False)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SourceRecord":
        mapping = _require_mapping(data, "source_record")
        required = {"source_id", "display_name", "record_kind", "lifecycle_state", "owner", "authoritative_locator", "declaration_refs", "licence", "release", "acquisition", "refresh", "consumers", "drift_policy", "rollback"}
        optional = {"components", "blocked_reasons", "missing_inputs", "unblock_condition", "reviewed_by", "reviewed_at"}
        if required - set(mapping):
            raise RegistrySchemaError("source_record missing required keys")
        if set(mapping) - (required | optional):
            raise RegistrySchemaError("source_record has unknown keys")

        record_kind = _require_str(mapping["record_kind"], "source_record.record_kind")
        if record_kind not in ALLOWED_RECORD_KINDS:
            raise RegistrySchemaError(f"source_record.record_kind must be one of {sorted(ALLOWED_RECORD_KINDS)}")

        components_value = mapping.get("components")
        if record_kind == "SINGLE_SOURCE":
            if components_value not in (None, []):
                raise RegistrySchemaError("single-source records must not carry components")
        elif record_kind in {"COMPOSITE_MANIFEST", "POLICY_SOURCE_REGISTER"}:
            if not isinstance(components_value, list):
                raise RegistrySchemaError(f"{record_kind} records must carry a components list")
        refs = tuple(DeclarationReference.from_mapping(item) for item in _require_list(mapping["declaration_refs"], "source_record.declaration_refs"))
        comps = components_value
        components = () if comps is None else tuple(Component.from_mapping(item) for item in _require_list(comps, "source_record.components"))
        blocked = tuple(_require_str(item, "blocked_reasons[]") for item in _require_list(mapping.get("blocked_reasons", []), "source_record.blocked_reasons"))
        missing_inputs = tuple(_require_str(item, "missing_inputs[]") for item in _require_list(mapping.get("missing_inputs", []), "source_record.missing_inputs"))
        return cls(
            source_id=_require_str(mapping["source_id"], "source_record.source_id"),
            display_name=_require_str(mapping["display_name"], "source_record.display_name"),
            record_kind=record_kind,
            lifecycle_state=_require_allowed_lifecycle(mapping["lifecycle_state"], "source_record.lifecycle_state"),
            owner=_require_str(mapping["owner"], "source_record.owner"),
            authoritative_locator=_require_str(mapping["authoritative_locator"], "source_record.authoritative_locator"),
            declaration_refs=refs,
            licence=LicenceInfo.from_mapping(mapping["licence"]),
            release=ReleaseInfo.from_mapping(mapping["release"]),
            acquisition=AcquisitionInfo.from_mapping(mapping["acquisition"]),
            refresh=RefreshInfo.from_mapping(mapping["refresh"]),
            consumers=tuple(_require_str(item, "source_record.consumers[]") for item in _require_list(mapping["consumers"], "source_record.consumers")),
            drift_policy=DriftPolicy.from_mapping(mapping["drift_policy"]),
            rollback=RollbackInfo.from_mapping(mapping["rollback"]),
            components=components,
            blocked_reasons=blocked,
            missing_inputs=missing_inputs,
            unblock_condition=None if mapping.get("unblock_condition") is None else _require_str(mapping["unblock_condition"], "source_record.unblock_condition"),
            reviewed_by=None if mapping.get("reviewed_by") is None else _require_str(mapping["reviewed_by"], "source_record.reviewed_by"),
            reviewed_at=None if mapping.get("reviewed_at") is None else _require_str(mapping["reviewed_at"], "source_record.reviewed_at"),
            _components_present="components" in mapping,
            _blocked_reasons_present="blocked_reasons" in mapping,
            _missing_inputs_present="missing_inputs" in mapping,
            _unblock_condition_present="unblock_condition" in mapping,
            _reviewed_by_present="reviewed_by" in mapping,
            _reviewed_at_present="reviewed_at" in mapping,
        )

    def as_dict(self) -> JsonObject:
        out: JsonObject = {"source_id": self.source_id, "display_name": self.display_name, "record_kind": self.record_kind, "lifecycle_state": self.lifecycle_state, "owner": self.owner, "authoritative_locator": self.authoritative_locator, "declaration_refs": [item.as_dict() for item in self.declaration_refs], "licence": self.licence.as_dict(), "release": self.release.as_dict(), "acquisition": self.acquisition.as_dict(), "refresh": self.refresh.as_dict(), "consumers": list(self.consumers), "drift_policy": self.drift_policy.as_dict(), "rollback": self.rollback.as_dict()}
        if self._components_present:
            out["components"] = [item.as_dict() for item in self.components]
        if self._blocked_reasons_present:
            out["blocked_reasons"] = list(self.blocked_reasons)
        if self._missing_inputs_present:
            out["missing_inputs"] = list(self.missing_inputs)
        if self._unblock_condition_present: out["unblock_condition"] = self.unblock_condition
        if self._reviewed_by_present: out["reviewed_by"] = self.reviewed_by
        if self._reviewed_at_present: out["reviewed_at"] = self.reviewed_at
        return out


@dataclass(frozen=True, slots=True)
class Consumer:
    consumer_id: str
    owner: str
    required_sources: tuple[str, ...]
    freshness_required: bool
    on_blocked_source: str
    forbidden_source_roles: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Consumer":
        mapping = _require_mapping(data, "consumer")
        required = {"consumer_id", "owner", "required_sources", "freshness_required", "on_blocked_source", "forbidden_source_roles"}
        if required - set(mapping):
            raise RegistrySchemaError("consumer missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("consumer has unknown keys")
        return cls(
            consumer_id=_require_str(mapping["consumer_id"], "consumer.consumer_id"),
            owner=_require_str(mapping["owner"], "consumer.owner"),
            required_sources=tuple(_require_str(item, "consumer.required_sources[]") for item in _require_list(mapping["required_sources"], "consumer.required_sources")),
            freshness_required=_require_bool(mapping["freshness_required"], "consumer.freshness_required"),
            on_blocked_source=_require_str(mapping["on_blocked_source"], "consumer.on_blocked_source"),
            forbidden_source_roles=tuple(_require_str(item, "consumer.forbidden_source_roles[]") for item in _require_list(mapping["forbidden_source_roles"], "consumer.forbidden_source_roles")),
        )

    def as_dict(self) -> JsonObject:
        return {"consumer_id": self.consumer_id, "owner": self.owner, "required_sources": list(self.required_sources), "freshness_required": self.freshness_required, "on_blocked_source": self.on_blocked_source, "forbidden_source_roles": list(self.forbidden_source_roles)}


@dataclass(frozen=True, slots=True)
class CoverageExclusion:
    exclusion_id: str
    declaration_path: str
    declaration_locator: str
    owner: str
    reason: str
    review_condition: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CoverageExclusion":
        mapping = _require_mapping(data, "coverage_exclusion")
        required = {"exclusion_id", "declaration_path", "declaration_locator", "owner", "reason", "review_condition"}
        if required - set(mapping):
            raise RegistrySchemaError("coverage_exclusion missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("coverage_exclusion has unknown keys")
        return cls(
            exclusion_id=_require_str(mapping["exclusion_id"], "coverage_exclusion.exclusion_id"),
            declaration_path=_require_str(mapping["declaration_path"], "coverage_exclusion.declaration_path"),
            declaration_locator=_require_str(mapping["declaration_locator"], "coverage_exclusion.declaration_locator"),
            owner=_require_str(mapping["owner"], "coverage_exclusion.owner"),
            reason=_require_str(mapping["reason"], "coverage_exclusion.reason"),
            review_condition=_require_str(mapping["review_condition"], "coverage_exclusion.review_condition"),
        )

    def as_dict(self) -> JsonObject:
        return {"exclusion_id": self.exclusion_id, "declaration_path": self.declaration_path, "declaration_locator": self.declaration_locator, "owner": self.owner, "reason": self.reason, "review_condition": self.review_condition}


@dataclass(frozen=True, slots=True)
class PreservationRule:
    rule_id: str
    path: str
    owner: str
    reason: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PreservationRule":
        mapping = _require_mapping(data, "preservation_rule")
        required = {"rule_id", "path", "owner", "reason"}
        if required - set(mapping):
            raise RegistrySchemaError("preservation_rule missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("preservation_rule has unknown keys")
        return cls(rule_id=_require_str(mapping["rule_id"], "preservation_rule.rule_id"), path=_require_str(mapping["path"], "preservation_rule.path"), owner=_require_str(mapping["owner"], "preservation_rule.owner"), reason=_require_str(mapping["reason"], "preservation_rule.reason"))

    def as_dict(self) -> JsonObject:
        return {"rule_id": self.rule_id, "path": self.path, "owner": self.owner, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Registry:
    schema: str
    registry_id: str
    registry_version: str
    created_at: str
    registry_content_hash: str
    hash_basis: str
    source_records: tuple[SourceRecord, ...]
    consumers: tuple[Consumer, ...]
    coverage_exclusions: tuple[CoverageExclusion, ...]
    preservation_rules: tuple[PreservationRule, ...]
    _raw_mapping: Mapping[str, Any] | None = field(default=None, repr=False, compare=False, hash=False)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Registry":
        mapping = _require_mapping(data, "registry")
        required = {"schema", "registry_id", "registry_version", "created_at", "registry_content_hash", "hash_basis", "source_records", "consumers", "coverage_exclusions", "preservation_rules"}
        if required - set(mapping):
            raise RegistrySchemaError("registry missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("registry has unknown keys")
        raw_mapping = copy.deepcopy(dict(mapping))
        instance = cls(
            schema=_require_str(mapping["schema"], "registry.schema"),
            registry_id=_require_str(mapping["registry_id"], "registry.registry_id"),
            registry_version=_require_str(mapping["registry_version"], "registry.registry_version"),
            created_at=_require_str(mapping["created_at"], "registry.created_at"),
            registry_content_hash=_require_str(mapping["registry_content_hash"], "registry.registry_content_hash"),
            hash_basis=_require_str(mapping["hash_basis"], "registry.hash_basis"),
            source_records=tuple(SourceRecord.from_mapping(item) for item in _require_list(mapping["source_records"], "registry.source_records")),
            consumers=tuple(Consumer.from_mapping(item) for item in _require_list(mapping["consumers"], "registry.consumers")),
            coverage_exclusions=tuple(CoverageExclusion.from_mapping(item) for item in _require_list(mapping["coverage_exclusions"], "registry.coverage_exclusions")),
            preservation_rules=tuple(PreservationRule.from_mapping(item) for item in _require_list(mapping["preservation_rules"], "registry.preservation_rules")),
            _raw_mapping=raw_mapping,
        )
        return instance

    def as_dict(self) -> JsonObject:
        return {"schema": self.schema, "registry_id": self.registry_id, "registry_version": self.registry_version, "created_at": self.created_at, "registry_content_hash": self.registry_content_hash, "hash_basis": self.hash_basis, "source_records": [item.as_dict() for item in self.source_records], "consumers": [item.as_dict() for item in self.consumers], "coverage_exclusions": [item.as_dict() for item in self.coverage_exclusions], "preservation_rules": [item.as_dict() for item in self.preservation_rules]}


@dataclass(frozen=True, slots=True)
class ManifestChecksum:
    mode: str
    raw_byte_size: int | None = None
    raw_sha256: str | None = None
    canonical_lf_utf8_bytes: int | None = None
    canonical_lf_sha256: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ManifestChecksum":
        mapping = _require_mapping(data, "checksum")
        fields = {"mode", "raw_byte_size", "raw_sha256", "canonical_lf_utf8_bytes", "canonical_lf_sha256"}
        if set(mapping) != fields:
            raise RegistrySchemaError("checksum has unknown keys")
        return cls(
            mode=_require_str(mapping["mode"], "checksum.mode"),
            raw_byte_size=None if mapping.get("raw_byte_size") is None else int(mapping["raw_byte_size"]),
            raw_sha256=None if mapping.get("raw_sha256") is None else _require_str(mapping["raw_sha256"], "checksum.raw_sha256"),
            canonical_lf_utf8_bytes=None if mapping.get("canonical_lf_utf8_bytes") is None else int(mapping["canonical_lf_utf8_bytes"]),
            canonical_lf_sha256=None if mapping.get("canonical_lf_sha256") is None else _require_str(mapping["canonical_lf_sha256"], "checksum.canonical_lf_sha256"),
        )

    def as_dict(self) -> JsonObject:
        return {
            "mode": self.mode,
            "raw_byte_size": self.raw_byte_size,
            "raw_sha256": self.raw_sha256,
            "canonical_lf_utf8_bytes": self.canonical_lf_utf8_bytes,
            "canonical_lf_sha256": self.canonical_lf_sha256,
        }


@dataclass(frozen=True, slots=True)
class ManifestFile:
    file_id: str
    path: str
    role: str
    media_type: str
    checksum: ManifestChecksum
    component_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ManifestFile":
        mapping = _require_mapping(data, "file")
        required = {"file_id", "path", "role", "media_type", "checksum", "component_ids"}
        if required - set(mapping):
            raise RegistrySchemaError("file missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("file has unknown keys")
        return cls(
            file_id=_require_str(mapping["file_id"], "file.file_id"),
            path=_require_str(mapping["path"], "file.path"),
            role=_require_str(mapping["role"], "file.role"),
            media_type=_require_str(mapping["media_type"], "file.media_type"),
            checksum=ManifestChecksum.from_mapping(mapping["checksum"]),
            component_ids=tuple(_require_str(item, "file.component_ids[]") for item in _require_list(mapping["component_ids"], "file.component_ids")),
        )

    def as_dict(self) -> JsonObject:
        return {"file_id": self.file_id, "path": self.path, "role": self.role, "media_type": self.media_type, "checksum": self.checksum.as_dict(), "component_ids": list(self.component_ids)}


@dataclass(frozen=True, slots=True)
class ManifestContentBinding:
    binding_id: str
    baseline_kind: str
    baseline_id: str | None
    candidate_file_id: str | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ManifestContentBinding":
        mapping = _require_mapping(data, "content_binding")
        required = {"binding_id", "baseline_kind", "baseline_id", "candidate_file_id"}
        if required - set(mapping):
            raise RegistrySchemaError("content_binding missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("content_binding has unknown keys")
        baseline_id = mapping.get("baseline_id")
        candidate_file_id = mapping.get("candidate_file_id")
        if baseline_id is not None:
            baseline_id = _require_str(baseline_id, "content_binding.baseline_id")
        if candidate_file_id is not None:
            candidate_file_id = _require_str(candidate_file_id, "content_binding.candidate_file_id")
        return cls(
            binding_id=_require_str(mapping["binding_id"], "content_binding.binding_id"),
            baseline_kind=_require_str(mapping["baseline_kind"], "content_binding.baseline_kind"),
            baseline_id=baseline_id,
            candidate_file_id=candidate_file_id,
        )

    def as_dict(self) -> JsonObject:
        return {"binding_id": self.binding_id, "baseline_kind": self.baseline_kind, "baseline_id": self.baseline_id, "candidate_file_id": self.candidate_file_id}


@dataclass(frozen=True, slots=True)
class ComponentProjectionEntry:
    component_id: str
    display_name: str
    source_role: str
    version_or_snapshot: str
    licence_status: str
    declaration_locator: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ComponentProjectionEntry":
        mapping = _require_mapping(data, "component_projection_entry")
        required = {"component_id", "display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"}
        if required - set(mapping):
            raise RegistrySchemaError("component_projection_entry missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("component_projection_entry has unknown keys")
        return cls(
            component_id=_require_str(mapping["component_id"], "component_projection_entry.component_id"),
            display_name=_require_str(mapping["display_name"], "component_projection_entry.display_name"),
            source_role=_require_str(mapping["source_role"], "component_projection_entry.source_role"),
            version_or_snapshot=_require_str(mapping["version_or_snapshot"], "component_projection_entry.version_or_snapshot"),
            licence_status=_require_str(mapping["licence_status"], "component_projection_entry.licence_status"),
            declaration_locator=_require_str(mapping["declaration_locator"], "component_projection_entry.declaration_locator"),
        )

    def as_dict(self) -> JsonObject:
        return {"component_id": self.component_id, "display_name": self.display_name, "source_role": self.source_role, "version_or_snapshot": self.version_or_snapshot, "licence_status": self.licence_status, "declaration_locator": self.declaration_locator}


@dataclass(frozen=True, slots=True)
class ManifestComponentProjection:
    mode: str
    components: tuple[ComponentProjectionEntry, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ManifestComponentProjection":
        mapping = _require_mapping(data, "component_projection")
        required = {"mode", "components"}
        if required - set(mapping):
            raise RegistrySchemaError("component_projection missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("component_projection has unknown keys")
        return cls(
            mode=_require_str(mapping["mode"], "component_projection.mode"),
            components=tuple(ComponentProjectionEntry.from_mapping(item) for item in _require_list(mapping["components"], "component_projection.components")),
        )

    def as_dict(self) -> JsonObject:
        return {"mode": self.mode, "components": [item.as_dict() for item in self.components]}


@dataclass(frozen=True, slots=True)
class SourceBinding:
    source_id: str
    registry_content_hash: str
    declaration_refs: tuple[DeclarationReference, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SourceBinding":
        mapping = _require_mapping(data, "source_binding")
        required = {"source_id", "registry_content_hash", "declaration_refs"}
        if required - set(mapping):
            raise RegistrySchemaError("source_binding missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("source_binding has unknown keys")
        return cls(
            source_id=_require_str(mapping["source_id"], "source_binding.source_id"),
            registry_content_hash=_require_str(mapping["registry_content_hash"], "source_binding.registry_content_hash"),
            declaration_refs=tuple(DeclarationReference.from_mapping(item) for item in _require_list(mapping["declaration_refs"], "source_binding.declaration_refs")),
        )

    def as_dict(self) -> JsonObject:
        return {
            "source_id": self.source_id,
            "registry_content_hash": self.registry_content_hash,
            "declaration_refs": [item.as_dict() for item in self.declaration_refs],
        }


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    display_name: str
    record_kind: str
    owner: str
    authoritative_locator: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateIdentity":
        mapping = _require_mapping(data, "candidate.identity")
        required = {"display_name", "record_kind", "owner", "authoritative_locator"}
        if required - set(mapping):
            raise RegistrySchemaError("candidate.identity missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("candidate.identity has unknown keys")
        return cls(
            display_name=_require_str(mapping["display_name"], "candidate.identity.display_name"),
            record_kind=_require_str(mapping["record_kind"], "candidate.identity.record_kind"),
            owner=_require_str(mapping["owner"], "candidate.identity.owner"),
            authoritative_locator=_require_str(mapping["authoritative_locator"], "candidate.identity.authoritative_locator"),
        )

    def as_dict(self) -> JsonObject:
        return {"display_name": self.display_name, "record_kind": self.record_kind, "owner": self.owner, "authoritative_locator": self.authoritative_locator}


@dataclass(frozen=True, slots=True)
class CandidateRelease:
    version_or_snapshot: str
    release_date: str | None
    retrieved_at: str
    content_pin_status: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateRelease":
        mapping = _require_mapping(data, "candidate.release")
        required = {"version_or_snapshot", "release_date", "retrieved_at", "content_pin_status"}
        if required - set(mapping):
            raise RegistrySchemaError("candidate.release missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("candidate.release has unknown keys")
        return cls(
            version_or_snapshot=_require_str(mapping["version_or_snapshot"], "candidate.release.version_or_snapshot"),
            release_date=None if mapping.get("release_date") is None else _require_str(mapping["release_date"], "candidate.release.release_date"),
            retrieved_at=_require_str(mapping["retrieved_at"], "candidate.release.retrieved_at"),
            content_pin_status=_require_str(mapping["content_pin_status"], "candidate.release.content_pin_status"),
        )

    def as_dict(self) -> JsonObject:
        return {"version_or_snapshot": self.version_or_snapshot, "release_date": self.release_date, "retrieved_at": self.retrieved_at, "content_pin_status": self.content_pin_status}


@dataclass(frozen=True, slots=True)
class CandidateLicence:
    status: str
    identifier_or_family: str
    terms_locator: str
    permitted_use: str
    redistribution: str
    cloud_egress: str
    verification_basis: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateLicence":
        mapping = _require_mapping(data, "candidate.licence")
        required = {"status", "identifier_or_family", "terms_locator", "permitted_use", "redistribution", "cloud_egress", "verification_basis"}
        if required - set(mapping):
            raise RegistrySchemaError("candidate.licence missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("candidate.licence has unknown keys")
        return cls(
            status=_require_str(mapping["status"], "candidate.licence.status"),
            identifier_or_family=_require_str(mapping["identifier_or_family"], "candidate.licence.identifier_or_family"),
            terms_locator=_require_str(mapping["terms_locator"], "candidate.licence.terms_locator"),
            permitted_use=_require_str(mapping["permitted_use"], "candidate.licence.permitted_use"),
            redistribution=_require_str(mapping["redistribution"], "candidate.licence.redistribution"),
            cloud_egress=_require_str(mapping["cloud_egress"], "candidate.licence.cloud_egress"),
            verification_basis=_require_str(mapping["verification_basis"], "candidate.licence.verification_basis"),
        )

    def as_dict(self) -> JsonObject:
        return {"status": self.status, "identifier_or_family": self.identifier_or_family, "terms_locator": self.terms_locator, "permitted_use": self.permitted_use, "redistribution": self.redistribution, "cloud_egress": self.cloud_egress, "verification_basis": self.verification_basis}


@dataclass(frozen=True, slots=True)
class CandidateAcquisition:
    method: str
    operator_contract: str
    writes_outside_repository: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateAcquisition":
        mapping = _require_mapping(data, "candidate.acquisition")
        required = {"method", "operator_contract", "writes_outside_repository"}
        if required - set(mapping):
            raise RegistrySchemaError("candidate.acquisition missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("candidate.acquisition has unknown keys")
        return cls(
            method=_require_str(mapping["method"], "candidate.acquisition.method"),
            operator_contract=_require_str(mapping["operator_contract"], "candidate.acquisition.operator_contract"),
            writes_outside_repository=_require_bool(mapping["writes_outside_repository"], "candidate.acquisition.writes_outside_repository"),
        )

    def as_dict(self) -> JsonObject:
        return {"method": self.method, "operator_contract": self.operator_contract, "writes_outside_repository": self.writes_outside_repository}


@dataclass(frozen=True, slots=True)
class Candidate:
    snapshot_id: str
    identity: CandidateIdentity
    release: CandidateRelease
    licence: CandidateLicence
    acquisition: CandidateAcquisition

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Candidate":
        mapping = _require_mapping(data, "candidate")
        required = {"snapshot_id", "identity", "release", "licence", "acquisition"}
        if required - set(mapping):
            raise RegistrySchemaError("candidate missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("candidate has unknown keys")
        return cls(
            snapshot_id=_require_str(mapping["snapshot_id"], "candidate.snapshot_id"),
            identity=CandidateIdentity.from_mapping(mapping["identity"]),
            release=CandidateRelease.from_mapping(mapping["release"]),
            licence=CandidateLicence.from_mapping(mapping["licence"]),
            acquisition=CandidateAcquisition.from_mapping(mapping["acquisition"]),
        )

    def as_dict(self) -> JsonObject:
        return {
            "snapshot_id": self.snapshot_id,
            "identity": self.identity.as_dict(),
            "release": self.release.as_dict(),
            "licence": self.licence.as_dict(),
            "acquisition": self.acquisition.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ManifestDocument:
    schema: str
    manifest_content_hash: str
    hash_basis: str
    observed_at: str
    source_binding: SourceBinding
    candidate: Candidate
    files: tuple[ManifestFile, ...]
    content_bindings: tuple[ManifestContentBinding, ...]
    component_projection: ManifestComponentProjection | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ManifestDocument":
        mapping = _require_mapping(data, "manifest")
        required = {"schema", "manifest_content_hash", "hash_basis", "observed_at", "source_binding", "candidate", "files", "content_bindings", "component_projection"}
        if required - set(mapping):
            raise RegistrySchemaError("manifest missing required keys")
        if set(mapping) - required:
            raise RegistrySchemaError("manifest has unknown keys")
        files = tuple(ManifestFile.from_mapping(item) for item in _require_list(mapping["files"], "manifest.files"))
        bindings = tuple(ManifestContentBinding.from_mapping(item) for item in _require_list(mapping["content_bindings"], "manifest.content_bindings"))
        projection = None if mapping.get("component_projection") is None else ManifestComponentProjection.from_mapping(mapping["component_projection"])
        return cls(
            schema=_require_str(mapping["schema"], "manifest.schema"),
            manifest_content_hash=_require_str(mapping["manifest_content_hash"], "manifest.manifest_content_hash"),
            hash_basis=_require_str(mapping["hash_basis"], "manifest.hash_basis"),
            observed_at=_require_str(mapping["observed_at"], "manifest.observed_at"),
            source_binding=SourceBinding.from_mapping(mapping["source_binding"]),
            candidate=Candidate.from_mapping(mapping["candidate"]),
            files=files,
            content_bindings=bindings,
            component_projection=projection,
        )

    def as_dict(self) -> JsonObject:
        payload: JsonObject = {
            "schema": self.schema,
            "manifest_content_hash": self.manifest_content_hash,
            "hash_basis": self.hash_basis,
            "observed_at": self.observed_at,
            "source_binding": self.source_binding.as_dict(),
            "candidate": self.candidate.as_dict(),
            "files": [item.as_dict() for item in self.files],
            "content_bindings": [item.as_dict() for item in self.content_bindings],
        }
        payload["component_projection"] = None if self.component_projection is None else self.component_projection.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class CliResult:
    schema: str
    command: str
    run_status: str
    input_validity: str
    stage_outcome: str | None
    source_id: str | None
    registry_content_hash: str | None
    manifest_content_hash: str | None
    verification_artifact: dict[str, Any] | None
    diff_artifact: dict[str, Any] | None
    error: dict[str, Any] | None
    validation_ceiling: str

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())

    def __contains__(self, key: object) -> bool:
        return key in self.as_dict()

    def keys(self):
        return self.as_dict().keys()

    def items(self):
        return self.as_dict().items()

    def values(self):
        return self.as_dict().values()

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "command": self.command,
            "run_status": self.run_status,
            "input_validity": self.input_validity,
            "stage_outcome": self.stage_outcome,
            "source_id": self.source_id,
            "registry_content_hash": self.registry_content_hash,
            "manifest_content_hash": self.manifest_content_hash,
            "verification_artifact": self.verification_artifact,
            "diff_artifact": self.diff_artifact,
            "error": self.error,
            "validation_ceiling": self.validation_ceiling,
        }


@dataclass(frozen=True, slots=True)
class VerifyStageResult:
    exit_code: int
    report: CliResult

    def __iter__(self):
        # Attribute access (``result.report``) exposes the typed, immutable
        # ``CliResult`` unchanged. Tuple unpacking (``code, report =
        # verify_stage(...)``) instead yields the plain JSON-serializable
        # dict payload, matching the shape callers see over the CLI/JSON
        # boundary so it can be passed straight to ``json.dumps`` (e.g. for
        # asserting no raw exception text leaked into the report).
        yield self.exit_code
        yield self.report.as_dict()


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    type: str
    details: JsonObject = field(default_factory=dict)

    def as_dict(self) -> JsonObject:
        payload: JsonObject = {"code": self.code, "message": self.message, "type": self.type}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class ValidationResult:
    schema: str
    registry_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    consumer_state: str | None = None
    consumer: JsonObject | None = None
    validation_ceiling: str | None = None

    def as_report(self) -> JsonObject:
        payload: JsonObject = {"schema": self.schema, "registry_valid": self.registry_valid, "errors": [item.as_dict() for item in self.errors]}
        if self.validation_ceiling is not None:
            payload["validation_ceiling"] = self.validation_ceiling
        if self.consumer_state is not None:
            payload["consumer_state"] = self.consumer_state
        if self.consumer is not None:
            payload["consumer"] = self.consumer
        return payload


# ---------------------------------------------------------------------------
# V2-S3 drift planning models (additive).
#
# These types are produced by ``raptor.sourceops.drift_planning`` and never
# parsed from untrusted external bytes directly (the drift-planning module
# performs that validation itself and only then constructs these frozen
# records), so most constructors here accept already-validated values rather
# than repeating ``from_mapping``-style schema checks.
# ---------------------------------------------------------------------------


def freeze_json(value: Any) -> Any:
    """Recursively convert a plain JSON-shaped value into an immutable form.

    Mappings become read-only ``MappingProxyType`` views and lists become
    tuples; scalars are returned unchanged. Used so public V2-S3 model
    fields that carry open-ended JSON content (for example a V2-S2 fact's
    ``before``/``after`` envelope) are never a bare mutable ``dict``/``list``.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    """Inverse of :func:`freeze_json`: rebuild plain ``dict``/``list`` values
    suitable for ``json.dumps`` from a frozen model field.
    """
    if isinstance(value, MappingProxyType):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class FactPathSelector:
    mode: str
    values: tuple[str, ...]

    def as_dict(self) -> JsonObject:
        return {"mode": self.mode, "values": list(self.values)}


@dataclass(frozen=True, slots=True)
class MaterialitySelectors:
    classifications: tuple[str, ...]
    difference_kinds: tuple[str, ...]
    fact_kinds: tuple[str, ...]
    subject_types: tuple[str, ...]
    fact_path: FactPathSelector
    source_roles: tuple[str, ...]
    source_lifecycles: tuple[str, ...]
    consumer_freshness_profiles: tuple[str, ...]
    record_kinds: tuple[str, ...]

    def as_dict(self) -> JsonObject:
        return {
            "classifications": list(self.classifications),
            "difference_kinds": list(self.difference_kinds),
            "fact_kinds": list(self.fact_kinds),
            "subject_types": list(self.subject_types),
            "fact_path": self.fact_path.as_dict(),
            "source_roles": list(self.source_roles),
            "source_lifecycles": list(self.source_lifecycles),
            "consumer_freshness_profiles": list(self.consumer_freshness_profiles),
            "record_kinds": list(self.record_kinds),
        }


@dataclass(frozen=True, slots=True)
class MaterialityRule:
    priority: int
    rule_id: str
    rationale_id: str
    selectors: MaterialitySelectors
    outcome: str

    def as_dict(self) -> JsonObject:
        return {"priority": self.priority, "rule_id": self.rule_id, "rationale_id": self.rationale_id, "selectors": self.selectors.as_dict(), "outcome": self.outcome}


@dataclass(frozen=True, slots=True)
class MaterialityPolicy:
    schema: str
    policy_id: str
    policy_version: str
    policy_content_hash: str
    hash_basis: str
    approval_binding: Mapping[str, Any]
    registry_binding: Mapping[str, Any]
    artifact_binding: Mapping[str, Any]
    evaluator: Mapping[str, Any]
    rules: tuple[MaterialityRule, ...]
    raw_mapping: Mapping[str, Any]

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_content_hash": self.policy_content_hash,
            "hash_basis": self.hash_basis,
            "approval_binding": thaw_json(self.approval_binding),
            "registry_binding": thaw_json(self.registry_binding),
            "artifact_binding": thaw_json(self.artifact_binding),
            "evaluator": thaw_json(self.evaluator),
            "rules": [item.as_dict() for item in self.rules],
        }


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    path: str
    content_hash: str
    schema: str

    def as_dict(self) -> JsonObject:
        return {"path": self.path, "content_hash": self.content_hash, "schema": self.schema}


@dataclass(frozen=True, slots=True)
class V2S2ArtifactRef:
    path: str
    content_hash: str
    schema: str

    def as_dict(self) -> JsonObject:
        return {"path": self.path, "content_hash": self.content_hash, "schema": self.schema}


@dataclass(frozen=True, slots=True)
class DiffFact:
    difference_kind: str
    fact_kind: str
    subject_type: str
    subject_id: str
    fact_path: str
    classification: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    provenance: Mapping[str, Any]
    fact_id: str
    fact_index: int

    def locator(self) -> JsonObject:
        return {
            "difference_kind": self.difference_kind,
            "fact_kind": self.fact_kind,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "fact_path": self.fact_path,
            "classification": self.classification,
        }

    def as_dict(self) -> JsonObject:
        payload = self.locator()
        payload["before"] = thaw_json(self.before)
        payload["after"] = thaw_json(self.after)
        payload["provenance"] = thaw_json(self.provenance)
        return payload


@dataclass(frozen=True, slots=True)
class V2S2ArtifactPair:
    manifest_content_hash: str
    source_id: str
    observed_at: str
    registry_content_hash: str
    verification: Mapping[str, Any]
    diff: Mapping[str, Any]
    verification_ref: V2S2ArtifactRef
    diff_ref: V2S2ArtifactRef
    facts: tuple[DiffFact, ...]
    stage_outcome: str

    def as_dict(self) -> JsonObject:
        return {
            "manifest_content_hash": self.manifest_content_hash,
            "source_id": self.source_id,
            "observed_at": self.observed_at,
            "registry_content_hash": self.registry_content_hash,
            "verification": thaw_json(self.verification),
            "diff": thaw_json(self.diff),
            "verification_ref": self.verification_ref.as_dict(),
            "diff_ref": self.diff_ref.as_dict(),
            "facts": [item.as_dict() for item in self.facts],
            "stage_outcome": self.stage_outcome,
        }


@dataclass(frozen=True, slots=True)
class FactEvaluation:
    fact_id: str
    fact_index: int
    fact_locator: Mapping[str, Any]
    context: Mapping[str, Any]
    evaluation: str
    rule_id: str
    rationale_id: str
    conservative_default: bool

    def as_dict(self) -> JsonObject:
        return {
            "fact_id": self.fact_id,
            "fact_index": self.fact_index,
            "fact_locator": thaw_json(self.fact_locator),
            "context": thaw_json(self.context),
            "evaluation": self.evaluation,
            "rule_id": self.rule_id,
            "rationale_id": self.rationale_id,
            "conservative_default": self.conservative_default,
        }


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    outcome: str
    counts: Mapping[str, int]
    evaluations: tuple[FactEvaluation, ...]
    source_id: str
    rule_id_priority_order: tuple[str, ...] = ()

    def as_dict(self) -> JsonObject:
        return {"outcome": self.outcome, "counts": thaw_json(self.counts), "evaluations": [item.as_dict() for item in self.evaluations]}


@dataclass(frozen=True, slots=True)
class ActionDisposition:
    action: str
    disposition: str
    reason_id: str
    route_ids: tuple[str, ...]

    def as_dict(self) -> JsonObject:
        return {"action": self.action, "disposition": self.disposition, "reason_id": self.reason_id, "route_ids": list(self.route_ids)}


@dataclass(frozen=True, slots=True)
class RoutePrerequisite:
    prerequisite: str
    status: str

    def as_dict(self) -> JsonObject:
        return {"prerequisite": self.prerequisite, "status": self.status}


@dataclass(frozen=True, slots=True)
class ProposedRoute:
    route_id: str
    action: str
    state: str
    source_id: str
    target: Mapping[str, Any]
    consumer_id: str | None
    prerequisites: tuple[RoutePrerequisite, ...]
    reason_fact_ids: tuple[str, ...]
    reason_rule_ids: tuple[str, ...]
    proposal_only: bool
    approval_required: bool
    approval_state: str
    executed: bool

    def as_dict(self) -> JsonObject:
        return {
            "route_id": self.route_id,
            "action": self.action,
            "state": self.state,
            "source_id": self.source_id,
            "target": thaw_json(self.target),
            "consumer_id": self.consumer_id,
            "prerequisites": [item.as_dict() for item in self.prerequisites],
            "reason_fact_ids": list(self.reason_fact_ids),
            "reason_rule_ids": list(self.reason_rule_ids),
            "proposal_only": self.proposal_only,
            "approval_required": self.approval_required,
            "approval_state": self.approval_state,
            "executed": self.executed,
        }


@dataclass(frozen=True, slots=True)
class ImpactRoutingResult:
    source_declared_actions: tuple[str, ...]
    action_dispositions: tuple[ActionDisposition, ...]
    routes: tuple[ProposedRoute, ...]

    def as_dict(self) -> JsonObject:
        return {
            "source_declared_actions": list(self.source_declared_actions),
            "action_dispositions": [item.as_dict() for item in self.action_dispositions],
            "routes": [item.as_dict() for item in self.routes],
        }


@dataclass(frozen=True, slots=True)
class RollbackFileBinding:
    binding_id: str
    predecessor_path: str
    predecessor_content_byte_size: int
    predecessor_canonical_lf_sha256: str
    current_path: str
    current_content_byte_size: int
    current_canonical_lf_sha256: str

    def as_dict(self) -> JsonObject:
        return {
            "binding_id": self.binding_id,
            "predecessor_path": self.predecessor_path,
            "predecessor_content_byte_size": self.predecessor_content_byte_size,
            "predecessor_canonical_lf_sha256": self.predecessor_canonical_lf_sha256,
            "current_path": self.current_path,
            "current_content_byte_size": self.current_content_byte_size,
            "current_canonical_lf_sha256": self.current_canonical_lf_sha256,
        }


@dataclass(frozen=True, slots=True)
class PreservationBinding:
    rule_id: str
    path: str
    content_byte_size: int
    canonical_lf_sha256: str

    def as_dict(self) -> JsonObject:
        return {"rule_id": self.rule_id, "path": self.path, "content_byte_size": self.content_byte_size, "canonical_lf_sha256": self.canonical_lf_sha256}


@dataclass(frozen=True, slots=True)
class RollbackMetadataArtifact:
    schema: str
    artifact_content_hash: str
    hash_basis: str
    rollback_source_record_binding_hash_basis: str
    current_source_id: str
    current_rollback_source_record_binding_hash: str
    predecessor_source_id: str | None
    predecessor_rollback_source_record_binding_hash: str | None
    current_declaration_refs: tuple[Mapping[str, Any], ...]
    predecessor_declaration_refs: tuple[Mapping[str, Any], ...]
    file_bindings: tuple[RollbackFileBinding, ...]
    preservation_bindings: tuple[PreservationBinding, ...]

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "artifact_content_hash": self.artifact_content_hash,
            "hash_basis": self.hash_basis,
            "rollback_source_record_binding_hash_basis": self.rollback_source_record_binding_hash_basis,
            "current_source_id": self.current_source_id,
            "current_rollback_source_record_binding_hash": self.current_rollback_source_record_binding_hash,
            "predecessor_source_id": self.predecessor_source_id,
            "predecessor_rollback_source_record_binding_hash": self.predecessor_rollback_source_record_binding_hash,
            "current_declaration_refs": [thaw_json(item) for item in self.current_declaration_refs],
            "predecessor_declaration_refs": [thaw_json(item) for item in self.predecessor_declaration_refs],
            "file_bindings": [item.as_dict() for item in self.file_bindings],
            "preservation_bindings": [item.as_dict() for item in self.preservation_bindings],
        }


@dataclass(frozen=True, slots=True)
class RollbackBlocker:
    code: str
    phase: str
    subject: Any
    expected: Any
    actual: Any

    def as_dict(self) -> JsonObject:
        return {"code": self.code, "phase": self.phase, "subject": thaw_json(self.subject), "expected": thaw_json(self.expected), "actual": thaw_json(self.actual)}


@dataclass(frozen=True, slots=True)
class RollbackIntegrityCheck:
    check: str
    status: str

    def as_dict(self) -> JsonObject:
        return {"check": self.check, "status": self.status}


@dataclass(frozen=True, slots=True)
class ProposedRollbackOperation:
    operation_id: str
    sequence: int
    operation_type: str
    source_path: str | None
    target_path: str | None
    expected_source_hash: str | None
    expected_target_hash: str | None
    preservation_rule_id: str | None
    proposal_only: bool
    approval_required: bool
    approval_state: str
    executed: bool

    def as_dict(self) -> JsonObject:
        return {
            "operation_id": self.operation_id,
            "sequence": self.sequence,
            "operation_type": self.operation_type,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "expected_source_hash": self.expected_source_hash,
            "expected_target_hash": self.expected_target_hash,
            "preservation_rule_id": self.preservation_rule_id,
            "proposal_only": self.proposal_only,
            "approval_required": self.approval_required,
            "approval_state": self.approval_state,
            "executed": self.executed,
        }


@dataclass(frozen=True, slots=True)
class RollbackRehearsal:
    outcome: str
    reason_code: str
    blocker: RollbackBlocker | None
    rollback_route_eligible: bool
    proposed_operations: tuple[ProposedRollbackOperation, ...]
    lineage: Mapping[str, Any]
    rollback_artifact_registry_path: str | None
    rollback_artifact_status: str
    rollback_artifact_content_hash: str | None
    rollback_file_bindings: tuple[RollbackFileBinding, ...]
    rollback_preservation_bindings: tuple[PreservationBinding, ...]
    integrity_checks: tuple[RollbackIntegrityCheck, ...]

    def rehearsal_dict(self) -> JsonObject:
        return {
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "blocker": None if self.blocker is None else self.blocker.as_dict(),
            "rollback_route_eligible": self.rollback_route_eligible,
            "proposed_operations": [item.as_dict() for item in self.proposed_operations],
        }

    def rollback_artifact_dict(self) -> JsonObject:
        return {
            "registry_path": self.rollback_artifact_registry_path,
            "status": self.rollback_artifact_status,
            "content_hash": self.rollback_artifact_content_hash,
            "file_bindings": [item.as_dict() for item in self.rollback_file_bindings],
            "preservation_bindings": [item.as_dict() for item in self.rollback_preservation_bindings],
        }


@dataclass(frozen=True, slots=True)
class ImpactPlanArtifact:
    schema: str
    artifact_content_hash: str
    hash_basis: str
    observed_at: str
    input_binding: Mapping[str, Any]
    observation: Mapping[str, Any]
    policy_evaluation: Mapping[str, Any]
    proposal: Mapping[str, Any]
    proposal_only: bool
    approval_required: bool
    approval_state: str
    executed: bool
    validation_ceiling: str

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "artifact_content_hash": self.artifact_content_hash,
            "hash_basis": self.hash_basis,
            "observed_at": self.observed_at,
            "input_binding": thaw_json(self.input_binding),
            "observation": thaw_json(self.observation),
            "policy_evaluation": thaw_json(self.policy_evaluation),
            "proposal": thaw_json(self.proposal),
            "proposal_only": self.proposal_only,
            "approval_required": self.approval_required,
            "approval_state": self.approval_state,
            "executed": self.executed,
            "validation_ceiling": self.validation_ceiling,
        }


@dataclass(frozen=True, slots=True)
class RollbackPlanArtifact:
    schema: str
    artifact_content_hash: str
    hash_basis: str
    observed_at: str
    input_binding: Mapping[str, Any]
    impact_plan_content_hash: str
    lineage: Mapping[str, Any]
    rollback_artifact: Mapping[str, Any]
    integrity_checks: tuple[RollbackIntegrityCheck, ...]
    rehearsal: Mapping[str, Any]
    proposal_only: bool
    approval_required: bool
    approval_state: str
    executed: bool
    validation_ceiling: str

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "artifact_content_hash": self.artifact_content_hash,
            "hash_basis": self.hash_basis,
            "observed_at": self.observed_at,
            "input_binding": thaw_json(self.input_binding),
            "impact_plan_content_hash": self.impact_plan_content_hash,
            "lineage": thaw_json(self.lineage),
            "rollback_artifact": thaw_json(self.rollback_artifact),
            "integrity_checks": [item.as_dict() for item in self.integrity_checks],
            "rehearsal": thaw_json(self.rehearsal),
            "proposal_only": self.proposal_only,
            "approval_required": self.approval_required,
            "approval_state": self.approval_state,
            "executed": self.executed,
            "validation_ceiling": self.validation_ceiling,
        }


@dataclass(frozen=True, slots=True)
class PlanDriftCliResult:
    schema: str
    command: str
    run_status: str
    input_validity: str
    baseline_validity: str
    policy_validity: str
    assessment_outcome: str
    rollback_rehearsal_outcome: str
    source_id: str | None
    manifest_content_hash: str | None
    diff_artifact_content_hash: str | None
    verification_artifact_content_hash: str | None
    registry_content_hash: str | None
    policy_content_hash: str | None
    impact_plan: ArtifactReference | None
    rollback_plan: ArtifactReference | None
    error: Mapping[str, Any] | None
    proposal_only: bool
    approval_required: bool
    approval_state: str
    executed: bool
    validation_ceiling: str

    def as_dict(self) -> JsonObject:
        return {
            "schema": self.schema,
            "command": self.command,
            "run_status": self.run_status,
            "input_validity": self.input_validity,
            "baseline_validity": self.baseline_validity,
            "policy_validity": self.policy_validity,
            "assessment_outcome": self.assessment_outcome,
            "rollback_rehearsal_outcome": self.rollback_rehearsal_outcome,
            "source_id": self.source_id,
            "manifest_content_hash": self.manifest_content_hash,
            "diff_artifact_content_hash": self.diff_artifact_content_hash,
            "verification_artifact_content_hash": self.verification_artifact_content_hash,
            "registry_content_hash": self.registry_content_hash,
            "policy_content_hash": self.policy_content_hash,
            "impact_plan": None if self.impact_plan is None else self.impact_plan.as_dict(),
            "rollback_plan": None if self.rollback_plan is None else self.rollback_plan.as_dict(),
            "error": None if self.error is None else thaw_json(self.error),
            "proposal_only": self.proposal_only,
            "approval_required": self.approval_required,
            "approval_state": self.approval_state,
            "executed": self.executed,
            "validation_ceiling": self.validation_ceiling,
        }


@dataclass(frozen=True, slots=True)
class PlanDriftResult:
    exit_code: int
    cli_result: PlanDriftCliResult

    def __iter__(self):
        yield self.exit_code
        yield self.cli_result.as_dict()
