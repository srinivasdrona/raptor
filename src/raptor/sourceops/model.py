from __future__ import annotations

import copy
from dataclasses import dataclass, field
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
