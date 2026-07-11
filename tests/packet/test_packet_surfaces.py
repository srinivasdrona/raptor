"""PRD-04 Task B executable contract: render, queue, and calibration surfaces."""

from __future__ import annotations

import csv
from dataclasses import fields, replace
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

import test_packet_core as core


def _api():
    api = core._api()
    try:
        from raptor.packet.config import (
            NarrativeCatalog,
            NarrativeTemplate,
            RenderConfig,
            SelectionConfig,
            load_narrative_catalog,
            load_render_config,
            load_selection_config,
        )
        from raptor.packet.model import PacketView
        from raptor.packet.queue import (
            Batch,
            CoverageReport,
            QueueIndex,
            QueueRow,
            build_queue_index,
            coverage_report,
            select_calibration_batch,
        )
        from raptor.packet.render import render_markdown
    except ImportError as exc:
        pytest.fail(f"PRD-04 Task B surfaces are not implemented: {exc}")
    api.update(locals())
    return api


def _catalog(api):
    template = api["NarrativeTemplate"](
        template_id="criterion_summary",
        body="Gene {gene} has criterion {criterion}.",
        required_bindings=("gene", "criterion"),
    )
    return api["NarrativeCatalog"](
        config_version="1",
        templates={"criterion_summary": template},
    )


def _render_config(api):
    return api["RenderConfig"](
        config_version="1",
        non_authoritative_marker="NON-AUTHORITATIVE EVIDENCE REVIEW",
        first_pass_heading="FIRST-PASS BLINDED EVIDENCE REVIEW",
        operator_heading="OPERATOR PACKET",
        reconciliation_heading="RECONCILIATION PACKET",
        narrative_catalog=_catalog(api),
    )


def _selection_config(api, *, expected_atoms=None):
    return api["SelectionConfig"](
        config_version="1",
        census_snapshot_id="clinvar_2026-07-07",
        seed=42,
        required_dimensions=("pattern", "gene", "variant_class", "edge_flag"),
        expected_atoms=expected_atoms
        or {
            "pattern": (),
            "gene": (),
            "variant_class": (),
            "edge_flag": (),
        },
    )


def _plan(api, *, class_path: str = "identity.variant_class", template_id: str = "criterion_summary"):
    return api["NarrativePlan"](
        entries=(
            api["NarrativePlanEntry"](
                template_id=template_id,
                field_bindings=(
                    api["FieldBinding"](name="gene", field_path="identity.gene"),
                    api["FieldBinding"](name="criterion", field_path=class_path),
                ),
            ),
        ),
        model="test-model",
        prompt_hash="b" * 64,
    )


def _comparator(api):
    return api["ExternalComparator"](
        comparator_id="aavc-2024",
        source_name="AAVC",
        source_snapshot="ClinVar September 2024",
        source_doi="10.5281/zenodo.17201194",
        source_archive_sha256="c" * 64,
        source_commit="8da2b5a",
        match_method="exact_vcf_key",
        machine_class="LIKELY_BENIGN",
        criteria=("BS1_S",),
        flags=("EXTERNAL_MACHINE_OUTPUT",),
    )


def _packet(
    api,
    *,
    index: int = 0,
    gene: str = "TSC1",
    variant_class: str = "missense",
    flags: tuple[str, ...] = ("edge-a",),
    pattern_id: str = "pattern-00",
    plan=True,
):
    if gene == "TSC1":
        accession, transcript = "NC_000009.12", "NM_000368.5"
    else:
        accession, transcript = "NC_000016.10", "NM_000548.5"
    pattern = api["PatternRef"](
        census_snapshot_id="clinvar_2026-07-07",
        pattern_id=pattern_id,
        census_selection_stratum="candidate_LP_review",
        pattern_signature=("PM2:supporting", "PVS1:very_strong"),
        member_count=1,
    )
    packet_input = replace(
        core._packet_input(api),
        identity=api["CanonicalVariantIdentity"](
            canonical_spdi=f"{accession}:{1000 + index}:A:G",
            gene=gene,
            transcript=transcript,
            consequence="missense_variant",
            variant_class=variant_class,
        ),
        run_metadata=replace(
            core._packet_input(api).run_metadata,
            run_id=f"run-{index}",
            generated_at=f"2026-07-11T00:{index % 60:02d}:00Z",
        ),
        quality_flags=flags,
        pattern_ref=pattern,
        external_comparators=(_comparator(api),),
    )
    narrative = _plan(api, class_path="entries.0.criterion") if plan else None
    return api["build_packet"](
        packet_input,
        core._packet_config(api),
        narrative_plan=narrative,
    )


def test_ac9_strict_surface_config_loaders(tmp_path: Path) -> None:
    api = _api()
    assert {field.name for field in fields(api["NarrativeTemplate"])} == {
        "template_id", "body", "required_bindings",
    }
    assert {field.name for field in fields(api["RenderConfig"])} == {
        "config_version", "non_authoritative_marker", "first_pass_heading",
        "operator_heading", "reconciliation_heading", "narrative_catalog",
    }
    assert {field.name for field in fields(api["SelectionConfig"])} == {
        "config_version", "census_snapshot_id", "seed",
        "required_dimensions", "expected_atoms",
    }
    with pytest.raises(api["PacketConfigError"]):
        api["NarrativeTemplate"](
            template_id="bad",
            body="body",
            required_bindings=(None,),
        )
    with pytest.raises(api["PacketConfigError"]):
        api["SelectionConfig"](
            config_version="1",
            census_snapshot_id="snapshot",
            seed=1,
            required_dimensions=("pattern", "gene", "variant_class", "edge_flag"),
            expected_atoms={
                "pattern": None,
                "gene": (),
                "variant_class": (),
                "edge_flag": (),
            },
        )
    with pytest.raises(api["PacketValidationError"]):
        api["QueueRow"](
            packet_id="a" * 64,
            evidence_core_hash="b" * 64,
            canonical_spdi="NC_000009.12:1:A:G",
            gene="TSC1",
            review_state="POLICY_BLOCKED",
            gate_status="UNVERIFIED",
            quality_flags=(None,),
            contradiction=False,
        )

    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        "config_version: '1'\n"
        "templates:\n"
        "  criterion_summary:\n"
        "    template_id: criterion_summary\n"
        "    body: 'Gene {gene} has criterion {criterion}.'\n"
        "    required_bindings: [gene, criterion]\n",
        encoding="utf-8",
    )
    catalog = api["load_narrative_catalog"](catalog_path)
    assert catalog.templates["criterion_summary"].required_bindings == ("gene", "criterion")

    bad = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    bad["unknown"] = True
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(api["PacketConfigError"]):
        api["load_narrative_catalog"](bad_path)

    for content, loader in (
        (
            "config_version: null\ntemplates: {}\n",
            api["load_narrative_catalog"],
        ),
        (
            "config_version: '1'\n"
            "templates:\n"
            "  t:\n"
            "    template_id: t\n"
            "    body: null\n"
            "    required_bindings: []\n",
            api["load_narrative_catalog"],
        ),
        (
            "config_version: '1'\n"
            "templates:\n"
            "  t:\n"
            "    template_id: t\n"
            "    body: body\n"
            "    required_bindings: null\n",
            api["load_narrative_catalog"],
        ),
        (
            "config_version: '1'\n"
            "census_snapshot_id: null\n"
            "seed: 1\n"
            "required_dimensions: [pattern, gene, variant_class, edge_flag]\n"
            "expected_atoms: {pattern: [], gene: [], variant_class: [], edge_flag: []}\n",
            api["load_selection_config"],
        ),
        (
            "config_version: '1'\n"
            "census_snapshot_id: snapshot\n"
            "seed: 1\n"
            "required_dimensions: [pattern, gene, variant_class, edge_flag]\n"
            "expected_atoms: {pattern: null, gene: [], variant_class: [], edge_flag: []}\n",
            api["load_selection_config"],
        ),
    ):
        null_path = tmp_path / f"null-{hash(content)}.yaml"
        null_path.write_text(content, encoding="utf-8")
        with pytest.raises(api["PacketConfigError"]):
            loader(null_path)


@pytest.mark.parametrize(
    ("plan", "view"),
    [
        ("unknown-template", "FIRST_PASS"),
        ("missing-binding", "FIRST_PASS"),
        ("extra-binding", "FIRST_PASS"),
        ("unresolved-path", "FIRST_PASS"),
        ("primitive-method-path", "FIRST_PASS"),
        ("forbidden-first-pass-path", "FIRST_PASS"),
    ],
)
def test_ac9_template_plan_fails_loud(plan: str, view: str) -> None:
    api = _api()
    packet = _packet(api)
    valid = packet.narrative_plan
    if plan == "unknown-template":
        changed = replace(valid.entries[0], template_id="unknown")
    elif plan == "missing-binding":
        changed = replace(valid.entries[0], field_bindings=valid.entries[0].field_bindings[:1])
    elif plan == "extra-binding":
        changed = replace(
            valid.entries[0],
            field_bindings=valid.entries[0].field_bindings
            + (api["FieldBinding"]("extra", "identity.gene"),),
        )
    elif plan == "unresolved-path":
        changed = replace(
            valid.entries[0],
            field_bindings=(
                valid.entries[0].field_bindings[0],
                api["FieldBinding"]("criterion", "identity.not_a_field"),
            ),
        )
    elif plan == "primitive-method-path":
        changed = replace(
            valid.entries[0],
            field_bindings=(
                valid.entries[0].field_bindings[0],
                api["FieldBinding"]("criterion", "identity.gene.upper"),
            ),
        )
    else:
        changed = replace(
            valid.entries[0],
            field_bindings=(
                valid.entries[0].field_bindings[0],
                api["FieldBinding"]("criterion", "candidate_direction.direction"),
            ),
        )
    bad_packet = replace(packet, narrative_plan=replace(valid, entries=(changed,)))

    with pytest.raises(api["PacketValidationError"]):
        api["render_markdown"](
            bad_packet,
            _render_config(api),
            view=api["PacketView"][view],
        )


def test_ac9_valid_template_renders_expected_deterministic_text() -> None:
    api = _api()
    packet = _packet(api)
    first = api["render_markdown"](
        packet, _render_config(api), view=api["PacketView"].FIRST_PASS
    )
    second = api["render_markdown"](
        packet, _render_config(api), view=api["PacketView"].FIRST_PASS
    )

    assert first == second
    assert "Gene TSC1 has criterion PVS1." in first


def test_ac4_ac20_first_pass_double_blinding_and_operator_markers() -> None:
    api = _api()
    packet = _packet(api)
    config = _render_config(api)
    view = api["redact_for_first_pass"](packet)

    first_pass = api["render_markdown"](
        packet, config, view=api["PacketView"].FIRST_PASS
    )
    forbidden_values = (
        packet.candidate_direction.null_reason,
        packet.candidate_direction.policy_id,
        packet.pattern_ref.census_selection_stratum,
        packet.external_comparators[0].machine_class,
        packet.external_comparators[0].source_name,
    )
    assert config.first_pass_heading in first_pass
    assert all(value not in first_pass for value in forbidden_values if value)
    assert "PVS1" in first_pass
    assert "very_strong" in first_pass
    assert not hasattr(view, "candidate_direction")
    assert not hasattr(view, "external_comparators")
    assert not hasattr(view, "pattern_ref")

    operator = api["render_markdown"](
        packet, config, view=api["PacketView"].OPERATOR
    )
    assert config.non_authoritative_marker in operator
    assert packet.candidate_direction.null_reason in operator
    assert packet.review_state.value in operator
    assert packet.gate_status.value in operator
    assert "\nLP\n" not in operator
    assert "\nLB\n" not in operator

    queue = api["build_queue_index"]((packet,), config)
    assert {field.name for field in fields(api["QueueRow"])} == {
        "packet_id", "evidence_core_hash", "canonical_spdi", "gene",
        "review_state", "gate_status", "quality_flags", "contradiction",
    }
    assert not hasattr(queue.rows[0], "candidate_direction")


def test_ac13_queue_csv_jsonl_are_exact_sorted_first_pass_surfaces() -> None:
    api = _api()
    packets = (
        _packet(api, index=2, gene="TSC2", flags=("flag,quoted",), pattern_id="pattern-02"),
        _packet(api, index=1, gene="TSC1", flags=("flag-b",), pattern_id="pattern-01"),
    )
    index = api["build_queue_index"](packets, _render_config(api))

    assert [row.gene for row in index.rows] == ["TSC1", "TSC2"]
    reader = csv.DictReader(io.StringIO(index.to_csv()))
    rows = list(reader)
    assert reader.fieldnames == [
        "packet_id", "evidence_core_hash", "canonical_spdi", "gene",
        "review_state", "gate_status", "quality_flags", "contradiction",
    ]
    assert rows[0]["gene"] == "TSC1"
    assert rows[1]["quality_flags"] == "flag,quoted"

    json_rows = [json.loads(line) for line in index.to_jsonl().splitlines()]
    assert [row["packet_id"] for row in json_rows] == [
        packet.packet_id for packet in sorted(
            packets,
            key=lambda item: (
                item.identity.gene,
                item.identity.canonical_spdi,
                item.packet_id,
            ),
        )
    ]
    assert all("candidate_direction" not in row for row in json_rows)

    direct = api["QueueIndex"](rows=tuple(reversed(index.rows)))
    assert direct.rows == index.rows


def test_ac12_calibration_covers_all_30_populated_patterns_without_cartesian_cells() -> None:
    api = _api()
    packets = []
    classes = ("missense", "truncating", "other")
    for index in range(30):
        packets.append(
            _packet(
                api,
                index=index,
                gene="TSC1" if index % 2 == 0 else "TSC2",
                variant_class=classes[index % 3],
                flags=(f"edge-{index % 4}",),
                pattern_id=f"pattern-{index:02d}",
                plan=False,
            )
        )
    duplicate = replace(
        packets[0],
        packet_id="f" * 64,
        packet_envelope_hash="f" * 64,
    )
    universe = tuple(packets) + (duplicate,)
    expected = {
        "pattern": tuple(f"pattern-{index:02d}" for index in range(30))
        + ("pattern-unpopulated",),
        "gene": ("TSC1", "TSC2", "TSC3"),
        "variant_class": ("missense", "truncating", "other", "unpopulated-class"),
        "edge_flag": ("edge-0", "edge-1", "edge-2", "edge-3", "edge-unpopulated"),
    }
    config = _selection_config(api, expected_atoms=expected)
    batch = api["select_calibration_batch"](universe, config)
    repeated = api["select_calibration_batch"](tuple(reversed(universe)), config)

    assert len(batch.selected_packet_ids) == 30
    assert batch.selected_packet_ids == repeated.selected_packet_ids
    assert set(batch.coverage.populated["pattern"]) == {
        f"pattern-{index:02d}" for index in range(30)
    }
    assert batch.coverage.covered == batch.coverage.populated
    assert batch.coverage.missing == {
        "pattern": (),
        "gene": (),
        "variant_class": (),
        "edge_flag": (),
    }
    assert batch.coverage.impossible_unpopulated == {
        "pattern": ("pattern-unpopulated",),
        "gene": ("TSC3",),
        "variant_class": ("unpopulated-class",),
        "edge_flag": ("edge-unpopulated",),
    }

    first_hash = hashlib.sha256(f"42:{packets[0].packet_id}".encode()).hexdigest()
    duplicate_hash = hashlib.sha256(f"42:{duplicate.packet_id}".encode()).hexdigest()
    winner = packets[0].packet_id if first_hash < duplicate_hash else duplicate.packet_id
    loser = duplicate.packet_id if winner == packets[0].packet_id else packets[0].packet_id
    assert winner in batch.selected_packet_ids
    assert loser not in batch.selected_packet_ids
