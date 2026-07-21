"""Executable contract for the real TSC provisional calibration-batch script."""

from __future__ import annotations

from dataclasses import replace
import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from raptor.eval.config import load_config as load_eval_config
from raptor.packet.config import (
    load_packet_config,
    load_render_config,
    load_selection_config,
)
from raptor.packet.model import (
    CanonicalVariantIdentity,
    PacketView,
    PrimaryGrounding,
    ReviewState,
    redact_for_first_pass,
)
from raptor.packet.render import render_markdown
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.model import BiasRecord


def _api():
    try:
        from scripts.build_tsc_calibration_batch import (
            BASIS,
            LIMITATIONS,
            ConservationError,
            ManifestEntry,
            OutputBoundaryError,
            RunPins,
            StratumEntry,
            assert_batch_coverage,
            assert_census_record_boundary,
            assert_source_of_record_conservation,
            build_batch_manifest,
            build_candidate_universe,
            build_census_source_of_record,
            build_packet_input,
            build_scorer_provenance,
            canonical_json,
            derive_quality_flags,
            load_manifest,
            main,
            reproduce_census_strata,
            select_batch,
            write_outputs,
        )
    except ImportError as exc:
        pytest.fail(f"calibration implementation is missing: {exc}")
    return locals()


def _row(index: int, criteria, *, gene: str = "TSC2") -> BiasRecord:
    chromosome = "chr9" if gene == "TSC1" else "chr16"
    raw = f"{chromosome}\t{1000 + index}\tA\tG\t{gene}\t{criteria!r}"
    return BiasRecord(
        chromosome=chromosome,
        position=1000 + index,
        ref_allele="A",
        alt_allele="G",
        variant_id=f"{chromosome}:{1000 + index}:A:G",
        variant_type="SNV",
        consequence="missense_variant",
        acmg_classification="uncertain",
        gene_name=gene,
        transcript="NM_000548.4" if gene != "TSC1" else "NM_000368.4",
        criteria=criteria,
        provenance={"raw_row": raw},
    )


@pytest.fixture
def synthetic_rows():
    return (
        _row(1, {"pvs1": (4, "very strong")}),
        _row(2, {"pm2": (3, "strong"), "pp3": (2, "moderate")}),
        _row(3, {"bp4": (3, "strong"), "pp3": (2, "moderate"), "pm2": (1, "supporting")}),
        _row(4, {"ba1": (5, "stand alone")}, gene="TSC1"),
        _row(5, {}),
        _row(6, {"pm2": (1, "supporting")}, gene="NTHL1"),
    )


@pytest.fixture
def manifest_entries(synthetic_rows):
    api = _api()
    entries = []
    for row in synthetic_rows:
        accession = "NC_000009.12" if row.gene_name == "TSC1" else "NC_000016.10"
        entries.append(
            api["ManifestEntry"](
                variant_id=f"{accession}:{row.position - 1}:A:G",
                vcf_key=(
                    f"{row.chromosome}:{row.position}:{row.ref_allele}:{row.alt_allele}"
                ),
            )
        )
    return tuple(entries)


@pytest.fixture
def run_pins():
    api = _api()
    return api["RunPins"](
        input_sha256="1" * 64,
        output_sha256="2" * 64,
        manifest_sha256="3" * 64,
        source_snapshot="clinvar_2026-07-07",
        bias_version="3.0.0",
        bias_commit="ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_version="3.18.1",
        code_commit="7e03ca4",
    )


@pytest.fixture
def configs():
    return {
        "scorer": load_scorer_config("configs/acmg/tsc.yaml"),
        "eval": load_eval_config("configs/eval/tsc2.yaml"),
        "packet": load_packet_config("configs/packet/schema.yaml"),
        "selection": load_selection_config("configs/packet/selection.yaml"),
        "render": load_render_config("configs/packet/render.yaml"),
    }


def _synthetic_stats(run_pins):
    return {
        "corpus": {"total_vus": 6},
        "run_integrity": {
            "bias_tsv_sha256": run_pins.output_sha256,
            "input_vcf_sha256": run_pins.input_sha256,
            "bias_rows": 6,
            "unique_raw_keys": 6,
        },
        "worker": {
            "bias": run_pins.bias_version,
            "bias_commit": run_pins.bias_commit,
            "nirvana": run_pins.nirvana_version,
        },
        "raptor_current_policy_internal_direction": {
            "candidate_LP_review": 1,
            "candidate_LB_review": 1,
            "no_deterministic_resolution": 3,
            "annotation_manual_review": 1,
        },
        "candidate_pattern_compression": {
            "candidate_LP_review": {"exact_strength_patterns": 1},
            "candidate_LB_review": {"exact_strength_patterns": 1},
        },
    }


def _strata(api, rows, manifest_entries, configs):
    manifest_by_key = {entry.vcf_key: entry for entry in manifest_entries}
    return api["reproduce_census_strata"](
        rows,
        manifest_by_key,
        configs["scorer"],
        configs["eval"],
    )


def test_cal_ac1_reproduces_strata_and_fails_loud_on_conservation_drift(
    synthetic_rows,
    manifest_entries,
    run_pins,
    configs,
) -> None:
    api = _api()
    strata = _strata(api, synthetic_rows, manifest_entries, configs)

    assert [entry.stratum for entry in strata] == [
        "candidate_LP_review",
        "no_deterministic_resolution",
        "no_deterministic_resolution",
        "candidate_LB_review",
        "no_deterministic_resolution",
        "manual_review",
    ]
    assert [entry.signed_points for entry in strata] == [8, 4, 1, -8, 0, 0]
    assert all(entry.basis == api["BASIS"] for entry in strata)
    assert len({entry.pattern_id for entry in strata if entry.pattern_id}) == 2

    stats = _synthetic_stats(run_pins)
    api["assert_source_of_record_conservation"](
        manifest_entries,
        synthetic_rows,
        strata,
        stats,
        run_pins,
    )
    with pytest.raises(api["ConservationError"]):
        api["assert_source_of_record_conservation"](
            manifest_entries[:-1],
            synthetic_rows,
            strata,
            stats,
            run_pins,
        )
    bad_stats = json.loads(json.dumps(stats))
    bad_stats["raptor_current_policy_internal_direction"]["candidate_LP_review"] = 3
    with pytest.raises(api["ConservationError"]):
        api["assert_source_of_record_conservation"](
            manifest_entries,
            synthetic_rows,
            strata,
            bad_stats,
            run_pins,
        )


def test_cal_ac2_real_provenance_and_packet_conformance(
    synthetic_rows,
    manifest_entries,
    run_pins,
    configs,
) -> None:
    api = _api()
    strata = _strata(api, synthetic_rows, manifest_entries, configs)
    provenance = api["build_scorer_provenance"](synthetic_rows[0], run_pins)
    assert provenance.input_sha256 == run_pins.input_sha256
    assert provenance.output_sha256 == run_pins.output_sha256
    assert provenance.raw_row_sha256 == hashlib.sha256(
        synthetic_rows[0].provenance["raw_row"].encode("utf-8")
    ).hexdigest()
    assert provenance.transcript == "NM_000548.4"

    identity = CanonicalVariantIdentity(
        canonical_spdi=manifest_entries[0].variant_id,
        gene="TSC2",
        transcript="NM_000548.5",
        consequence="missense_variant",
        variant_class="missense",
    )
    packet_input = api["build_packet_input"](
        identity,
        synthetic_rows[0],
        strata[0],
        configs["packet"],
        run_pins,
    )
    assert len(packet_input.criterion_inputs) == 1
    assert packet_input.criterion_inputs[0].primary_grounding is PrimaryGrounding.NOT_REQUIRED
    assert packet_input.criterion_inputs[0].primary_evidence_refs == ()

    ps3_row = _row(7, {"pvs1": (4, "very strong"), "ps3": (3, "AVADA")})
    ps3_identity = CanonicalVariantIdentity(
        canonical_spdi="NC_000016.10:1006:A:G",
        gene="TSC2",
        transcript="NM_000548.5",
        consequence="missense_variant",
        variant_class="missense",
    )
    ps3_input = api["build_packet_input"](
        ps3_identity,
        ps3_row,
        replace(strata[0], variant_id=ps3_identity.canonical_spdi),
        configs["packet"],
        run_pins,
    )
    ps3 = next(item for item in ps3_input.criterion_inputs if item.criterion == "PS3")
    assert ps3.primary_grounding is PrimaryGrounding.ABSENT
    assert ps3.primary_grounding_reason == "no_primary_literature_or_ps3_assay"

    universe = api["build_candidate_universe"](
        strata,
        synthetic_rows,
        manifest_entries,
        configs["packet"],
        run_pins,
    )
    assert len(universe) == 2
    for packet in universe:
        assert packet.candidate_direction.direction is None
        assert packet.candidate_direction.null_reason == "production_policy_unapproved"
        assert packet.review_state is ReviewState.POLICY_BLOCKED
        assert len(packet.entries) == len(
            next(
                row.criteria
                for row, entry in zip(synthetic_rows, strata)
                if entry.variant_id == packet.identity.canonical_spdi
            )
        )


def test_cal_ac3_coverage_and_ac4_first_pass_redaction(
    synthetic_rows,
    manifest_entries,
    run_pins,
    configs,
) -> None:
    api = _api()
    strata = _strata(api, synthetic_rows, manifest_entries, configs)
    universe = api["build_candidate_universe"](
        strata,
        synthetic_rows,
        manifest_entries,
        configs["packet"],
        run_pins,
    )
    batch = api["select_batch"](universe, configs["selection"])
    api["assert_batch_coverage"](batch, strata)
    assert len(batch.selected_packet_ids) == 2
    assert batch.coverage.missing == {
        "pattern": (),
        "gene": (),
        "variant_class": (),
        "edge_flag": (),
    }

    for packet in batch.packets:
        view = redact_for_first_pass(packet)
        assert not hasattr(view, "candidate_direction")
        assert not hasattr(view, "pattern_ref")
        markdown = render_markdown(packet, configs["render"], view=PacketView.FIRST_PASS)
        forbidden = (
            "production_policy_unapproved",
            packet.pattern_ref.census_selection_stratum,
            "AAVC",
        )
        assert all(value not in markdown for value in forbidden)


def test_cal_ac5_manifest_limitations_and_ac6_determinism(
    synthetic_rows,
    manifest_entries,
    run_pins,
    configs,
) -> None:
    api = _api()
    strata = _strata(api, synthetic_rows, manifest_entries, configs)
    first = api["build_candidate_universe"](
        strata,
        synthetic_rows,
        manifest_entries,
        configs["packet"],
        run_pins,
    )
    second = api["build_candidate_universe"](
        tuple(reversed(strata)),
        tuple(reversed(synthetic_rows)),
        tuple(reversed(manifest_entries)),
        configs["packet"],
        run_pins,
    )
    assert api["canonical_json"](first) == api["canonical_json"](second)

    batch = api["select_batch"](first, configs["selection"])
    manifest = api["build_batch_manifest"](
        first,
        batch,
        configs["packet"],
        configs["selection"],
        configs["render"],
        run_pins,
        _synthetic_stats(run_pins),
        {"blocked": True, "blocking_criteria": ["PS1", "PM5"]},
    )
    assert tuple(manifest["limitations"]) == tuple(api["LIMITATIONS"])
    census = api["build_census_source_of_record"](manifest)
    blob = api["canonical_json"](census)
    assert "NC_000" not in blob
    assert "selected_packet_ids" not in census


def test_cal_ac7_script_only_eval_import_and_no_network_or_labels() -> None:
    path = Path("scripts/build_tsc_calibration_batch.py")
    if not path.is_file():
        pytest.fail("calibration script is missing")
    text = path.read_text(encoding="utf-8")
    assert "raptor.eval.combine" in text
    for packet_path in Path("src/raptor/packet").glob("*.py"):
        tree = ast.parse(packet_path.read_text(encoding="utf-8"), filename=str(packet_path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "raptor.eval.combine" not in imported
    for forbidden in ("requests", "urllib", "httpx", "raptor.eval.knowns", "raptor.eval.benchmark"):
        assert forbidden not in text
    assert (api_basis := _api()["BASIS"])
    assert api_basis == "eval_only_census_selection_metadata"


def test_cal_ac8_output_boundary_and_deterministic_artifacts(
    tmp_path: Path,
    synthetic_rows,
    manifest_entries,
    run_pins,
    configs,
) -> None:
    api = _api()
    strata = _strata(api, synthetic_rows, manifest_entries, configs)
    universe = api["build_candidate_universe"](
        strata,
        synthetic_rows,
        manifest_entries,
        configs["packet"],
        run_pins,
    )
    batch = api["select_batch"](universe, configs["selection"])
    manifest = api["build_batch_manifest"](
        universe,
        batch,
        configs["packet"],
        configs["selection"],
        configs["render"],
        run_pins,
        _synthetic_stats(run_pins),
        {"blocked": True},
    )
    with pytest.raises(api["OutputBoundaryError"]):
        api["write_outputs"](
            Path.cwd() / "data" / "forbidden",
            batch,
            configs["render"],
            manifest,
        )
    repo_root = Path(__file__).resolve().parents[2]
    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(api["OutputBoundaryError"]):
            api["write_outputs"](
                repo_root / "data" / "forbidden",
                batch,
                configs["render"],
                manifest,
            )
    finally:
        os.chdir(original_cwd)

    allowed_census = repo_root / "data" / "census" / "calibration-test.json"
    assert api["assert_census_record_boundary"](allowed_census) == allowed_census.resolve()
    for forbidden_census in (
        tmp_path / "elsewhere.json",
        repo_root / "data" / "not-census.json",
        repo_root / "data" / "census" / "nested" / "record.json",
        repo_root / "data" / "census" / "record.txt",
    ):
        with pytest.raises(api["OutputBoundaryError"]):
            api["assert_census_record_boundary"](forbidden_census)

    first, second = tmp_path / "first", tmp_path / "second"
    api["write_outputs"](first, batch, configs["render"], manifest)
    api["write_outputs"](second, batch, configs["render"], manifest)
    first_files = {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert json.loads((first / "batch_manifest.json").read_text(encoding="utf-8"))[
        "limitations"
    ] == list(api["LIMITATIONS"])


@pytest.mark.skipif(
    os.environ.get("RAPTOR_TSC_CALIBRATION_REAL") != "1",
    reason="requires explicit real calibration paths",
)
def test_real_integration_conservation(tmp_path: Path) -> None:
    api = _api()
    required = {
        "RAPTOR_TSC_MANIFEST": os.environ.get("RAPTOR_TSC_MANIFEST"),
        "RAPTOR_TSC_BIAS_TSV": os.environ.get("RAPTOR_TSC_BIAS_TSV"),
        "RAPTOR_TSC_PROVENANCE": os.environ.get("RAPTOR_TSC_PROVENANCE"),
    }
    assert all(required.values())
    result = api["main"](
        [
            "--manifest", required["RAPTOR_TSC_MANIFEST"],
            "--bias-tsv", required["RAPTOR_TSC_BIAS_TSV"],
            "--provenance", required["RAPTOR_TSC_PROVENANCE"],
            "--census-stats", "data/census/tsc_vus_clinvar_2026-07-07_stats.json",
            "--lineage-audit", "data/census/tsc_bias_lineage_audit_2026-07-10.json",
            "--packet-config", "configs/packet/schema.yaml",
            "--selection-config", "configs/packet/selection.yaml",
            "--render-config", "configs/packet/render.yaml",
            "--narrative-catalog", "configs/packet/narrative_templates.yaml",
            "--scorer-config", "configs/acmg/tsc.yaml",
            "--eval-config", "configs/eval/tsc2.yaml",
            "--output-dir", str(tmp_path / "real"),
        ]
    )
    assert result == 0
    manifest = json.loads(
        (tmp_path / "real" / "batch_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["conservation"] == {
        "manifest_identities": 6618,
        "bias_rows": 6618,
        "candidate_LP_review": 238,
        "candidate_LB_review": 1333,
        "lp_patterns": 20,
        "lb_patterns": 10,
    }
