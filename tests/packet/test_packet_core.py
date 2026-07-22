from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, asdict, fields, replace
from enum import Enum
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from raptor.eval.lineage_policy import load_lineage_policy


HEX64 = "a" * 64
BIAS_COMMIT = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"


def _api():
    try:
        from raptor.packet.build import build_packet
        from raptor.packet.config import (
            CandidateDirectionPolicy,
            PacketConfig,
            PacketConfigError,
            load_candidate_direction_policy,
            load_packet_config,
        )
        from raptor.packet.direction import compute_candidate_direction
        from raptor.packet.hashing import (
            decision_record_hash,
            evidence_core_hash,
            narrative_plan_hash,
            packet_envelope_hash,
        )
        from raptor.packet.model import (
            CandidateEvidencePacket,
            CanonicalVariantIdentity,
            CensusSelectionMetadata,
            CriterionEntry,
            DirectionPolicyError,
            DispositionMappingError,
            ExternalComparator,
            FieldBinding,
            FirstPassPacketView,
            GateStatus,
            MissingEvidence,
            NarrativePlan,
            NarrativePlanEntry,
            PacketCriterionInput,
            PacketHashError,
            PacketInput,
            PacketPolicyDisposition,
            PacketSchemaError,
            PacketValidationError,
            PatternRef,
            PointContribution,
            PrimaryEvidenceRef,
            PrimaryGrounding,
            ProvenanceValidationError,
            ResolutionStatus,
            ReviewState,
            RunMetadata,
            ScorerProvenance,
            SourceSnapshotPins,
            redact_for_first_pass,
            resolve_packet_policy_disposition,
        )
    except ImportError as exc:
        pytest.fail(f"PRD-04 packet core is not implemented: {exc}")
    api = locals()
    api["_packet_config"] = _packet_config
    return api


def _provenance(api, *, key: str = "row-1"):
    return api["ScorerProvenance"](
        bias_row_key=key,
        chromosome="chr9",
        position=132900000,
        ref="A",
        alt="G",
        scorer_run_id="run-1",
        input_sha256="1" * 64,
        output_sha256="2" * 64,
        raw_row_sha256="3" * 64,
        bias_version="3.0.0",
        bias_commit=BIAS_COMMIT,
        nirvana_version="3.18.1",
        transcript="NM_000368.4",
    )


def _criterion_input(
    api,
    criterion: str = "PVS1",
    strength: str = "very_strong",
    direction: str = "pathogenic",
    *,
    key: str = "row-1",
):
    return api["PacketCriterionInput"](
        criterion=criterion,
        strength=strength,
        direction=direction,
        rationale=f"{criterion} source rationale",
        scorer_provenance=_provenance(api, key=key),
        primary_evidence_refs=(),
        primary_grounding=api["PrimaryGrounding"].NOT_REQUIRED,
        primary_grounding_reason="not required by packet policy",
    )


def _candidate_policy(api, *, approved: bool = False):
    cls = api["CandidateDirectionPolicy"]
    if not approved:
        return cls(
            policy_id="tsc-candidate-v1",
            version="1",
            approval_status="unapproved",
            approved_by=None,
            approval_ref=None,
            criterion_strength_points={},
            candidate_lp_min=None,
            candidate_lb_max=None,
        )
    return cls(
        policy_id="test-approved",
        version="1",
        approval_status="approved",
        approved_by="test-oracle",
        approval_ref="TEST-DECISION-1",
        criterion_strength_points={
            "PVS1": {"very_strong": 8},
            "PM2": {"supporting": 1},
            "BP4": {"strong": -4},
        },
        candidate_lp_min=6,
        candidate_lb_max=-1,
    )


def _packet_config(api, *, approved: bool = False):
    return api["PacketConfig"](
        packet_schema_version="1.0",
        config_version="1",
        lineage_policy=load_lineage_policy("configs/eval/bias_lineage.yaml"),
        lineage_policy_sha256=hashlib.sha256(
            Path("configs/eval/bias_lineage.yaml").read_bytes()
        ).hexdigest(),
        candidate_direction_policy=_candidate_policy(api, approved=approved),
        candidate_policy_sha256="4" * 64,
        primary_required_criteria=frozenset({"PS3"}),
    )


def _packet_input(api, criteria=None):
    criterion_inputs = tuple(criteria or [_criterion_input(api)])
    return api["PacketInput"](
        identity=api["CanonicalVariantIdentity"](
            canonical_spdi="NC_000009.12:132900000:A:G",
            gene="TSC1",
            transcript="NM_000368.5",
            consequence="missense_variant",
            variant_class="missense",
        ),
        criterion_inputs=criterion_inputs,
        run_metadata=api["RunMetadata"](
            run_id="run-1",
            generated_at="2026-07-11T00:00:00Z",
            code_commit="9adbd7b",
            packet_config_sha256="5" * 64,
            lineage_policy_sha256="6" * 64,
            candidate_policy_sha256="7" * 64,
        ),
        source_snapshot=api["SourceSnapshotPins"](
            snapshot_id="clinvar_2026-07-07",
            snapshot_date="2026-07-07",
            clinvar_sha256="8" * 64,
            bias_output_sha256="9" * 64,
            manifest_sha256="a" * 64,
        ),
        quality_flags=("provisional",),
        missing_evidence=(
            api["MissingEvidence"](
                category="functional_assay",
                next_action="review TSC assay literature",
                supporting_field_paths=("entries.0.criterion",),
            ),
        ),
        pattern_ref=None,
        external_comparators=(),
        predecessor_packet_id=None,
        predecessor_envelope_hash=None,
    )


def _normalize(value):
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset)):
        return [_normalize(item) for item in value]
    return value


def _canonical_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_ac1_exact_frozen_core_schema_and_config_loader(tmp_path: Path) -> None:
    api = _api()
    expected_packet_fields = {
        "packet_schema_version", "packet_id", "evidence_core_hash",
        "narrative_plan_hash", "packet_envelope_hash", "identity", "entries",
        "candidate_direction", "exclusions", "contradiction", "quality_flags",
        "missing_evidence", "narrative_plan", "external_comparators",
        "review_state", "gate_status", "pattern_ref", "run_metadata",
        "source_snapshot", "predecessor_packet_id", "predecessor_envelope_hash",
        "census_selection_stratum",
    }
    assert {field.name for field in fields(api["CandidateEvidencePacket"])} == expected_packet_fields
    assert api["load_packet_config"]("configs/packet/schema.yaml").packet_schema_version == "1.0"
    assert (
        api["load_candidate_direction_policy"](
            "configs/packet/candidate_direction.yaml"
        ).approval_status
        == "unapproved"
    )

    raw = yaml.safe_load(Path("configs/packet/schema.yaml").read_text(encoding="utf-8"))
    raw["unknown"] = True
    bad = tmp_path / "schema.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(api["PacketConfigError"]):
        api["load_packet_config"](bad)

    bad_policy = tmp_path / "candidate.yaml"
    bad_policy.write_text(
        "policy_id: 123\n"
        "version: null\n"
        "approval_status: unapproved\n"
        "approved_by: null\n"
        "approval_ref: null\n"
        "criterion_strength_points: null\n"
        "candidate_lp_min: null\n"
        "candidate_lb_max: null\n",
        encoding="utf-8",
    )
    with pytest.raises(api["PacketConfigError"]):
        api["load_candidate_direction_policy"](bad_policy)

    bad_schema = tmp_path / "bad-schema.yaml"
    schema_raw = yaml.safe_load(
        Path("configs/packet/schema.yaml").read_text(encoding="utf-8")
    )
    schema_raw["packet_schema_version"] = 123
    schema_raw["primary_required_criteria"] = None
    bad_schema.write_text(yaml.safe_dump(schema_raw), encoding="utf-8")
    with pytest.raises(api["PacketConfigError"]):
        api["load_packet_config"](bad_schema)

    packet = api["build_packet"](_packet_input(api), _packet_config(api))
    with pytest.raises(FrozenInstanceError):
        packet.packet_id = "mutated"
    with pytest.raises(api["PacketValidationError"]):
        replace(_packet_input(api), quality_flags="edge-a")
    with pytest.raises(api["PacketValidationError"]):
        replace(_packet_input(api), quality_flags=(None,))


def test_ac21_exact_provenance_schemas_and_resolution_rules() -> None:
    api = _api()
    assert {field.name for field in fields(api["ScorerProvenance"])} == {
        "bias_row_key", "chromosome", "position", "ref", "alt", "scorer_run_id",
        "input_sha256", "output_sha256", "raw_row_sha256", "bias_version",
        "bias_commit", "nirvana_version", "transcript",
    }
    assert {field.name for field in fields(api["PrimaryEvidenceRef"])} == {
        "ref_id", "source_type", "source_id", "locator", "source_snapshot",
        "source_version", "source_sha256", "source_sha256_null_reason",
        "supports_criterion", "resolution_status", "unresolved_reason",
    }

    with pytest.raises(TypeError):
        api["ScorerProvenance"](
            bias_row_key="missing-most-required-fields",
            chromosome="chr9",
        )
    with pytest.raises(api["ProvenanceValidationError"]):
        replace(_provenance(api), input_sha256="not-a-sha")
    for changes in (
        {"position": 0},
        {"ref": "not-dna"},
        {"alt": "?"},
        {"bias_version": "wrong"},
        {"bias_commit": "not-40-char-lowercase-hex"},
    ):
        with pytest.raises(api["ProvenanceValidationError"]):
            replace(_provenance(api), **changes)

    resolved = api["PrimaryEvidenceRef"](
        ref_id="pubmed-1",
        source_type="literature",
        source_id="PMID:1",
        locator="figure:2",
        source_snapshot="pubmed-2026-07",
        source_version="1",
        source_sha256=None,
        source_sha256_null_reason="publisher exposes no downloadable artifact",
        supports_criterion="PS3",
        resolution_status=api["ResolutionStatus"].RESOLVED,
        unresolved_reason=None,
    )
    assert resolved.resolution_status is api["ResolutionStatus"].RESOLVED

    with pytest.raises(api["ProvenanceValidationError"]):
        replace(resolved, source_sha256_null_reason=None)
    with pytest.raises(api["ProvenanceValidationError"]):
        replace(
            resolved,
            source_sha256="not-a-sha",
            source_sha256_null_reason=None,
        )
    with pytest.raises(api["ProvenanceValidationError"]):
        replace(resolved, source_type="bias_row")
    assert replace(resolved, source_type="clingen_guidance").source_type == "clingen_guidance"
    assert replace(resolved, source_type="database_record").source_type == "database_record"
    with pytest.raises(api["ProvenanceValidationError"]):
        replace(resolved, source_type="clinical_guidance")
    with pytest.raises(api["ProvenanceValidationError"]):
        replace(
            resolved,
            resolution_status=api["ResolutionStatus"].UNRESOLVED,
            unresolved_reason=None,
        )


def test_ac1_ac5_identity_and_primary_grounding_are_consistent() -> None:
    api = _api()
    valid = _packet_input(api)
    for changes in (
        {"gene": "BRCA1"},
        {"variant_class": "weird"},
        {"canonical_spdi": ""},
        {"canonical_spdi": "not-a-spdi"},
        {"canonical_spdi": "NC_000016.10:100:A:G"},
        {"transcript": "not-a-mane-version"},
        {"transcript": "NM_000548.5"},
        {"consequence": "???"},
    ):
        invalid = replace(valid, identity=replace(valid.identity, **changes))
        with pytest.raises(api["PacketValidationError"]):
            api["build_packet"](invalid, _packet_config(api))

    utr = replace(valid, identity=replace(valid.identity, consequence="3_prime_UTR_variant"))
    utr_packet = api["build_packet"](utr, _packet_config(api))
    assert utr_packet.identity.consequence == "3_prime_UTR_variant"
    multi = replace(
        valid,
        identity=replace(
            valid.identity,
            consequence="splice_region_variant,5_prime_UTR_variant",
        ),
    )
    multi_packet = api["build_packet"](multi, _packet_config(api))
    assert multi_packet.identity.consequence == "splice_region_variant,5_prime_UTR_variant"

    ps3_not_required = _packet_input(
        api,
        [
            replace(
                _criterion_input(api, "PS3", "strong", "pathogenic", key="ps3"),
                primary_grounding=api["PrimaryGrounding"].NOT_REQUIRED,
                primary_grounding_reason="caller claims not required",
            ),
        ],
    )
    with pytest.raises(api["PacketValidationError"]):
        api["build_packet"](ps3_not_required, _packet_config(api))

    ps3_absent = replace(
        ps3_not_required,
        criterion_inputs=(
            replace(
                ps3_not_required.criterion_inputs[0],
                primary_grounding=api["PrimaryGrounding"].ABSENT,
                primary_grounding_reason="primary assay record not yet assembled",
            ),
        ),
    )
    packet = api["build_packet"](ps3_absent, _packet_config(api))
    assert packet.entries[0].primary_required is True
    assert packet.entries[0].primary_grounding is api["PrimaryGrounding"].ABSENT

    present_without_ref = replace(
        valid,
        criterion_inputs=(
            replace(
                valid.criterion_inputs[0],
                primary_grounding=api["PrimaryGrounding"].PRESENT,
                primary_grounding_reason="",
            ),
        ),
    )
    with pytest.raises(api["PacketValidationError"]):
        api["build_packet"](present_without_ref, _packet_config(api))

    wrong_ref = api["PrimaryEvidenceRef"](
        ref_id="wrong-criterion",
        source_type="literature",
        source_id="PMID:1",
        locator="figure:1",
        source_snapshot="pubmed-2026-07",
        source_version="1",
        source_sha256="d" * 64,
        source_sha256_null_reason=None,
        supports_criterion="BA1",
        resolution_status=api["ResolutionStatus"].RESOLVED,
        unresolved_reason=None,
    )
    ps3_wrong_ref = replace(
        ps3_absent,
        criterion_inputs=(
            replace(
                ps3_absent.criterion_inputs[0],
                primary_evidence_refs=(wrong_ref,),
                primary_grounding=api["PrimaryGrounding"].PRESENT,
                primary_grounding_reason="",
            ),
        ),
    )
    with pytest.raises(api["PacketValidationError"]):
        api["build_packet"](ps3_wrong_ref, _packet_config(api))


def test_ac7_ac22_lineage_precedence_is_exhaustive_and_policy_derived() -> None:
    api = _api()
    policy = load_lineage_policy("configs/eval/bias_lineage.yaml")
    buckets = {
        api["PacketPolicyDisposition"].INCLUDED: set(),
        api["PacketPolicyDisposition"].MASKED: set(),
        api["PacketPolicyDisposition"].EXCLUDED: set(),
        api["PacketPolicyDisposition"].DEFERRED: set(),
    }
    for criterion, record in policy.records.items():
        disposition = api["resolve_packet_policy_disposition"](
            record.validation_disposition,
            record.production_disposition,
        )
        buckets[disposition].add(criterion)

    assert buckets[api["PacketPolicyDisposition"].INCLUDED] == {
        "PVS1", "PM2", "PM4", "BA1", "BS1", "BP3", "BP7",
    }
    assert buckets[api["PacketPolicyDisposition"].MASKED] == {
        "PS1", "PM5", "PM1", "PP2", "BP1",
    }
    assert buckets[api["PacketPolicyDisposition"].EXCLUDED] == {"PS4", "PP5", "BP6"}
    assert buckets[api["PacketPolicyDisposition"].DEFERRED] == {"PS3", "BS2", "PP3", "BP4"}

    dispositions = ("allowed", "requires_heldout_mask", "forbidden", "deferred")
    expected = {}
    for production in dispositions:
        expected[("forbidden", production)] = api["PacketPolicyDisposition"].EXCLUDED
        expected[("requires_heldout_mask", production)] = api["PacketPolicyDisposition"].MASKED
    for validation in ("allowed", "deferred"):
        expected[(validation, "deferred")] = api["PacketPolicyDisposition"].DEFERRED
    expected[("deferred", "allowed")] = api["PacketPolicyDisposition"].DEFERRED
    expected[("allowed", "allowed")] = api["PacketPolicyDisposition"].INCLUDED

    for validation in dispositions:
        for production in dispositions:
            pair = (validation, production)
            if pair in expected:
                assert api["resolve_packet_policy_disposition"](*pair) is expected[pair]
            else:
                with pytest.raises(api["DispositionMappingError"]):
                    api["resolve_packet_policy_disposition"](*pair)
    with pytest.raises(api["DispositionMappingError"]):
        api["resolve_packet_policy_disposition"]("unknown", "allowed")


def test_ac4_ac6_unapproved_null_and_approved_point_arithmetic() -> None:
    api = _api()
    unapproved = api["compute_candidate_direction"]([], _candidate_policy(api))
    assert unapproved.direction is None
    assert unapproved.null_reason == "production_policy_unapproved"
    assert unapproved.signed_points is None
    assert unapproved.per_criterion_points == ()
    for bad_points in (
        {"PVS1": {"very_strong": True}},
        {"PVS1": {"very_strong": "8"}},
    ):
        with pytest.raises(api["PacketConfigError"]):
            api["CandidateDirectionPolicy"](
                policy_id="bad",
                version="1",
                approval_status="approved",
                approved_by="oracle",
                approval_ref="decision",
                criterion_strength_points=bad_points,
                candidate_lp_min=6,
                candidate_lb_max=-1,
            )

    policy = load_lineage_policy("configs/eval/bias_lineage.yaml")
    entries = []
    for criterion, strength in (("PVS1", "very_strong"), ("PM2", "supporting")):
        record = policy.records[criterion]
        entries.append(
            api["CriterionEntry"](
                criterion=criterion,
                strength=strength,
                direction="pathogenic",
                rationale="test",
                lineage_class=record.lineage_class,
                validation_disposition=record.validation_disposition,
                production_disposition=record.production_disposition,
                decision_dependency=record.decision_dependency,
                packet_policy_disposition=api["PacketPolicyDisposition"].INCLUDED,
                exclusion_reason=None,
                scorer_provenance=_provenance(api, key=criterion),
                primary_evidence_refs=(),
                primary_grounding=api["PrimaryGrounding"].NOT_REQUIRED,
                primary_grounding_reason="not required",
                primary_required=False,
            )
        )
    direction = api["compute_candidate_direction"](entries, _candidate_policy(api, approved=True))
    assert direction.direction == "candidate_LP_review"
    assert direction.signed_points == 9
    assert [(item.criterion, item.strength, item.points) for item in direction.per_criterion_points] == [
        ("PM2", "supporting", 1),
        ("PVS1", "very_strong", 8),
    ]
    with pytest.raises(api["DirectionPolicyError"]):
        api["compute_candidate_direction"](
            [replace(entries[0], criterion="UNKNOWN")],
            _candidate_policy(api, approved=True),
        )


def test_ac5_ac7_ac8_build_preserves_provenance_lineage_and_contradiction() -> None:
    api = _api()
    packet_input = _packet_input(
        api,
        [
            _criterion_input(api, "PVS1", "very_strong", "pathogenic", key="pvs1"),
            _criterion_input(api, "BA1", "stand_alone", "benign", key="ba1"),
            _criterion_input(api, "PS1", "strong", "pathogenic", key="ps1"),
            _criterion_input(api, "PP5", "supporting", "pathogenic", key="pp5"),
            replace(
                _criterion_input(api, "PS3", "strong", "pathogenic", key="ps3"),
                primary_grounding=api["PrimaryGrounding"].ABSENT,
                primary_grounding_reason="primary assay record not yet assembled",
            ),
        ],
    )
    packet = api["build_packet"](packet_input, _packet_config(api))
    by_criterion = {entry.criterion: entry for entry in packet.entries}

    assert packet.candidate_direction.direction is None
    assert packet.review_state is api["ReviewState"].POLICY_BLOCKED
    assert packet.gate_status is api["GateStatus"].UNVERIFIED
    assert packet.contradiction is True
    assert by_criterion["PS1"].packet_policy_disposition is api["PacketPolicyDisposition"].MASKED
    assert by_criterion["PP5"].packet_policy_disposition is api["PacketPolicyDisposition"].EXCLUDED
    assert by_criterion["PP5"].exclusion_reason == "direct_copy_forbidden"
    assert by_criterion["PS3"].packet_policy_disposition is api["PacketPolicyDisposition"].DEFERRED
    assert by_criterion["PS3"].decision_dependency
    assert by_criterion["PVS1"].scorer_provenance.bias_row_key == "pvs1"
    assert by_criterion["PVS1"].primary_evidence_refs == ()
    assert by_criterion["PVS1"].primary_grounding is api["PrimaryGrounding"].NOT_REQUIRED


def test_ac2_ac19_hash_payloads_are_exact_and_domains_are_separate() -> None:
    api = _api()
    binding = api["FieldBinding"](name="criterion", field_path="entries.0.criterion")
    plan = api["NarrativePlan"](
        entries=(
            api["NarrativePlanEntry"](
                template_id="criterion_summary",
                field_bindings=(binding,),
            ),
        ),
        model="test-model",
        prompt_hash="b" * 64,
    )
    packet = api["build_packet"](
        _packet_input(api),
        _packet_config(api),
        narrative_plan=plan,
    )

    core_payload = {
        "identity": _normalize(packet.identity),
        "entries": _normalize(packet.entries),
        "candidate_direction": _normalize(packet.candidate_direction),
        "exclusions": _normalize(packet.exclusions),
        "contradiction": packet.contradiction,
        "quality_flags": sorted(packet.quality_flags),
        "missing_evidence": _normalize(packet.missing_evidence),
    }
    assert api["evidence_core_hash"](packet) == _canonical_hash(core_payload)
    assert packet.evidence_core_hash == _canonical_hash(core_payload)

    plan_payload = _normalize(plan)
    assert api["narrative_plan_hash"](plan) == _canonical_hash(plan_payload)
    assert packet.narrative_plan_hash == _canonical_hash(plan_payload)

    envelope_payload = {
        "evidence_core_hash": packet.evidence_core_hash,
        "narrative_plan_hash": packet.narrative_plan_hash,
        "packet_schema_version": packet.packet_schema_version,
        "run_pins": {
            "code_commit": packet.run_metadata.code_commit,
            "packet_config_sha256": packet.run_metadata.packet_config_sha256,
            "lineage_policy_sha256": packet.run_metadata.lineage_policy_sha256,
            "candidate_policy_sha256": packet.run_metadata.candidate_policy_sha256,
        },
        "source_snapshot": _normalize(packet.source_snapshot),
        "pattern_ref": None,
        "external_comparators": [],
        "review_state": packet.review_state.value,
        "gate_status": packet.gate_status.value,
        "predecessor_packet_id": None,
        "predecessor_envelope_hash": None,
    }
    expected_envelope = _canonical_hash(envelope_payload)
    assert api["packet_envelope_hash"](packet) == expected_envelope
    assert packet.packet_envelope_hash == expected_envelope
    assert packet.packet_id == expected_envelope

    run_only = replace(
        packet,
        run_metadata=replace(
            packet.run_metadata,
            run_id="different",
            generated_at="2026-07-12T00:00:00Z",
        ),
    )
    assert api["evidence_core_hash"](run_only) == packet.evidence_core_hash
    assert api["packet_envelope_hash"](run_only) == packet.packet_envelope_hash

    pin_change = replace(
        packet,
        run_metadata=replace(packet.run_metadata, code_commit="different-commit"),
    )
    assert api["evidence_core_hash"](pin_change) == packet.evidence_core_hash
    assert api["packet_envelope_hash"](pin_change) != packet.packet_envelope_hash

    comparator = api["ExternalComparator"](
        comparator_id="aavc-2024",
        source_name="AAVC",
        source_snapshot="ClinVar September 2024",
        source_doi="10.5281/zenodo.17201194",
        source_archive_sha256="c" * 64,
        source_commit="8da2b5a",
        match_method="exact_vcf_key",
        machine_class="VUS-LOW",
        criteria=(),
        flags=(),
    )
    comparator_change = replace(packet, external_comparators=(comparator,))
    assert api["evidence_core_hash"](comparator_change) == packet.evidence_core_hash
    assert api["packet_envelope_hash"](comparator_change) != packet.packet_envelope_hash

    payload = {"record_id": "00000000-0000-0000-0000-000000000001", "decision": "accept"}
    expected_decision = hashlib.sha256(
        (("0" * 64) + json.dumps(payload, sort_keys=True, separators=(",", ":"))).encode("utf-8")
    ).hexdigest()
    assert api["decision_record_hash"]("0" * 64, payload) == expected_decision
    with pytest.raises(api["PacketHashError"]):
        api["decision_record_hash"]("not-a-hash", payload)


def test_ac3_packet_core_has_no_label_eval_combiner_or_kb_coupling() -> None:
    module_dir = Path("src/raptor/packet")
    expected = {"model.py", "build.py", "direction.py", "hashing.py", "config.py"}
    if not module_dir.is_dir():
        pytest.fail("packet core implementation is missing")
    paths = [module_dir / name for name in expected]
    assert all(path.is_file() for path in paths)

    forbidden_modules = {
        "raptor.eval.combine",
        "raptor.eval.harness",
        "raptor.eval.knowns",
        "raptor.eval.benchmark",
        "raptor.kb.store",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module}
            else:
                imported = set()
            assert imported.isdisjoint(forbidden_modules)
        assert "KBStore" not in {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def test_ac20_first_pass_projection_schema_omits_both_machine_directions() -> None:
    api = _api()
    packet = api["build_packet"](_packet_input(api), _packet_config(api))
    view = api["redact_for_first_pass"](packet)

    assert isinstance(view, api["FirstPassPacketView"])
    assert {field.name for field in fields(api["FirstPassPacketView"])} == {
        "packet_id",
        "evidence_core_hash",
        "identity",
        "entries",
        "exclusions",
        "contradiction",
        "quality_flags",
        "missing_evidence",
        "narrative_plan",
        "review_state",
        "gate_status",
    }
    assert not hasattr(view, "candidate_direction")
    assert not hasattr(view, "external_comparators")
    assert not hasattr(view, "pattern_ref")
