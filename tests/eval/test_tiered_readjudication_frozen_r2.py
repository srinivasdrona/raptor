"""Test for the post-hoc re-adjudication of the frozen R2 masked-holdout gate.

Loads the byte-frozen R2 record via its canonical LF hash and asserts the derived axes.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import pytest
import sys
import yaml
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from raptor.eval.config import EvalConfig
from raptor.eval.model import Metrics

try:
    from raptor.eval.tiered_gate import (
        decide_tiered_gate,
        TieredReadjudicationInputError,
    )
except ImportError:
    class TieredReadjudicationError(Exception):
        pass
    class TieredReadjudicationInputError(TieredReadjudicationError):
        pass

    def decide_tiered_gate(*args, **kwargs):
        pytest.fail("Missing planned implementation of decide_tiered_gate", pytrace=False)

# Guarded imports for scripts.build_tiered_readjudication CLI contract
try:
    from scripts.build_tiered_readjudication import (
        main,
        REPO_ROOT,
        SOURCE_R2_CANONICAL_SHA256,
        InputError,
    )
except ImportError:
    REPO_ROOT = "D:\\AIProjects\\raptor-worktrees\\tiered-gate"
    SOURCE_R2_CANONICAL_SHA256 = "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    class InputError(Exception):
        pass
    def main(argv=None):
        pytest.fail("Missing planned implementation of build_tiered_readjudication.main", pytrace=False)


class MockRunMeta:
    def __init__(self, integrity_dict: dict, policy_dict: dict):
        self.effective_lineage_blockers = integrity_dict.get("effective_lineage_blockers", [])
        self.remask_survivors = integrity_dict.get("remask_survivors", 0)
        self.canonical_join_rows = integrity_dict.get("canonical_join_rows", 0)
        self.bias_rows = integrity_dict.get("bias_rows", 0)
        self.returned_artifacts_verified = integrity_dict.get("returned_artifacts_verified", 0)
        self.evaluation_skipped = policy_dict.get("evaluation_skipped", [])


def make_tiered_authorization_dict():
    """Build the exact versioned tiered_authorization configuration block."""
    return {
        "schema_version": 3,
        "axis_enums": {
            "A0_run_integrity": ["PASS", "INVALID"],
            "A1_data_sufficiency": ["ADEQUATE", "UNDERPOWERED", "NO_CALLS"],
            "A2_conditional_performance": ["MET", "UNMET", "NOT_ESTIMABLE", "NOT_APPLICABLE"],
            "A3_policy_parity": ["CLEAR", "BLOCKED"],
            "A5_scope_evidence_status": [
                "INVALID", "NOT_APPLICABLE", "NO_CALLS", "UNDERPOWERED",
                "BLOCKED_POLICY", "NOT_SUPPORTED", "SUPPORTED_POSTHOC", "VALIDATED_PROSPECTIVE"
            ],
            "A6_authorization_status": ["NOT_AUTHORIZED", "PENDING_PROSPECTIVE", "AUTHORIZED_RESEARCH_ONLY"]
        },
        "criterion_scope_applicability": {
            "PM1": ["missense:pathogenic"],
            "PP3": ["missense:pathogenic", "other:pathogenic"],
            "BP4": ["missense:benign", "other:benign"],
            "PP5": ["missense:pathogenic", "truncating:pathogenic", "other:pathogenic"],
            "BP6": ["missense:benign", "truncating:benign", "other:benign"],
            "PS4": ["missense:pathogenic", "truncating:pathogenic", "other:pathogenic"],
        },
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "RESEARCH_ONLY_NO_CLINICAL_USE": (
                "This is a post-hoc re-adjudication of the frozen ADR-0012 "
                "masked-holdout counts for research evidence only; no scope is authorized, "
                "and this authorizes no clinical classification, VUS worklist, or ClinVar "
                "submission pending a prospective validation on unseen data."
            ),
            "TRUNCATING_PATHOGENIC_PROSPECTIVE_AUTHORIZED": (
                "Prospective validation on unseen data has authorized the "
                "truncating-pathogenic research scope for research-evidence use only; "
                "full-spectrum VUS automation remains not authorized while missense is "
                "unvalidated, and this authorizes no clinical classification, VUS worklist, "
                "or ClinVar submission."
            )
        },
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "no_new_evidence_statement": (
            "No new evidence was generated: this record re-interprets the frozen R2 aggregate "
            "(source_canonical_lf_sha256 7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f) "
            "under the versioned tiered rule and performs no new run, scoring, annotation, "
            "benchmark read, network access, or data generation."
        ),
        "prospective_validation": {
            "status": "PENDING",
            "dataset_rule": {
                "registered_dataset": (
                    "The FIRST NCBI ClinVar GRCh38 variant_summary MONTHLY archive whose NCBI-published "
                    "official archive date is on or after 2026-08-01 — i.e. the 2026-08 monthly release, "
                    "file variant_summary_2026-08.txt.gz under "
                    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary/. "
                    "Selection is deterministic and yields EXACTLY ONE archive: order the monthly archives by "
                    "official published archive date ascending, take the first with date >= 2026-08-01; "
                    "ties broken by lexicographically smallest archive filename."
                ),
                "freeze_before_labels_scoring": {
                    "snapshot": "clinvar_2026-08-01",
                    "url": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary/variant_summary_2026-08.txt.gz",
                    "official_md5_to_be_frozen_when_exists": "PENDING_ARCHIVE_GENERATION",
                    "official_sha256_to_be_frozen_when_exists": "PENDING_ARCHIVE_GENERATION",
                },
                "unavailable_or_contract_invalid": {
                    "fallback_status": "BLOCKED_DATA",
                    "outcome_dependent_fallback": False,
                },
                "future_authorized_surfaces_pinned": {
                    "active": False,
                    "pinned_surfaces": ["full_spectrum", "research_scopes"],
                }
            }
        }
    }


def test_frozen_r2_re_adjudication():
    """Test loading and re-adjudicating the canonical-LF-verified R2 record."""
    ROOT = Path(__file__).resolve().parents[2]
    r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    assert r2_path.exists(), f"Could not find R2 record at {r2_path}"

    raw_bytes = r2_path.read_bytes()
    
    # 1. Verify the on-disk file line-endings-normalized (LF) SHA-256 hash
    lf_bytes = raw_bytes.replace(b"\r\n", b"\n")
    calculated_lf_hash = hashlib.sha256(lf_bytes).hexdigest()
    expected_lf_hash = "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    assert calculated_lf_hash == expected_lf_hash, f"LF Hash mismatch! Got {calculated_lf_hash}"

    # 2. Reconstruct state from R2 payload
    payload = json.loads(lf_bytes.decode("utf-8"))
    
    # Check R2 source hash
    source_content_hash = payload["content_hash"]
    assert source_content_hash == "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"

    # Reconstruct Metrics map
    metrics_map = {}
    for stratum_name, data in payload["metrics"].items():
        if stratum_name == "overall":
            continue
        m = Metrics(
            precision=data.get("precision", 0.0),
            recall=data.get("recall", 0.0),
            concordance=data.get("concordance", 0.0),
            counts=data.get("counts", {}),
            stratum=stratum_name,
            gating=data.get("gating", True),
            benign_precision=data.get("benign_precision", 0.0),
            benign_recall=data.get("benign_recall", 0.0),
            precision_lb=data.get("precision_lb", 0.0),
            recall_lb=data.get("recall_lb", 0.0),
            benign_precision_lb=data.get("benign_precision_lb", 0.0),
            benign_recall_lb=data.get("benign_recall_lb", 0.0),
        )
        metrics_map[stratum_name] = m

    # Construct EvalConfig
    config = EvalConfig(
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
        tavtigian_points={
            "supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8,
        },
        tavtigian_cutoffs={
            "pathogenic_min": 10, "likely_pathogenic_min": 6,
            "vus_min": 0, "vus_max": 5,
            "likely_benign_max": -1, "benign_max": -7,
        },
        min_count_per_class=36,
        split={"seed": 42, "holdout_fraction": 0.3},
        oracle_thresholds=payload["thresholds"],
        labels_snapshot=payload["benchmark"]["snapshot"],
    )

    # Construct RunMeta from integrity and policy
    run_meta = MockRunMeta(payload["integrity"], payload["policy"])

    # 3. Call decide_tiered_gate with explicit 4th argument
    decision = decide_tiered_gate(metrics_map, config, run_meta, make_tiered_authorization_dict())

    # 4. Verify outcomes for ALL SIX SCOPES across ALL AXES (Section 5 outcome pins)
    
    # (a) missense:pathogenic -> NO_CALLS/NOT_ESTIMABLE/BLOCKED/0-of-51/null/NO_CALLS/NOT_AUTHORIZED
    v_mp = decision.scopes["missense:pathogenic"]
    assert v_mp.data_sufficiency == "NO_CALLS"
    assert v_mp.conditional_performance == "NOT_ESTIMABLE"
    assert v_mp.policy_parity == "BLOCKED"
    assert v_mp.end_to_end_correct_call_coverage == "0/51"
    assert v_mp.precision_lb is None
    assert v_mp.recall_lb is None
    assert v_mp.scope_evidence_status == "NO_CALLS"
    assert v_mp.authorization_status == "NOT_AUTHORIZED"
    
    # Assert exact blocked reason is present
    assert "policy_parity=BLOCKED: PM1 evaluation_skipped applies_to missense:pathogenic" in v_mp.reasons
    
    # Other scopes must not contain it
    for scope_key, other_v in decision.scopes.items():
        if scope_key != "missense:pathogenic":
            assert "policy_parity=BLOCKED: PM1 evaluation_skipped applies_to missense:pathogenic" not in other_v.reasons

    # (b) missense:benign -> UNDERPOWERED/NOT_ESTIMABLE/CLEAR/9-of-103/null/UNDERPOWERED/NOT_AUTHORIZED
    v_mb = decision.scopes["missense:benign"]
    assert v_mb.data_sufficiency == "UNDERPOWERED"
    assert v_mb.conditional_performance == "NOT_ESTIMABLE"
    assert v_mb.policy_parity == "CLEAR"
    assert v_mb.end_to_end_correct_call_coverage == "9/103"
    assert v_mb.precision_lb is None
    assert v_mb.recall_lb is None
    assert v_mb.scope_evidence_status == "UNDERPOWERED"
    assert v_mb.authorization_status == "NOT_AUTHORIZED"

    # (c) truncating:pathogenic -> ADEQUATE/MET/CLEAR/189-of-210/SUPPORTED_POSTHOC/PENDING_PROSPECTIVE
    v_tp = decision.scopes["truncating:pathogenic"]
    assert v_tp.data_sufficiency == "ADEQUATE"
    assert v_tp.conditional_performance == "MET"
    assert v_tp.policy_parity == "CLEAR"
    assert v_tp.end_to_end_correct_call_coverage == "189/210"
    assert v_tp.precision_lb == 0.9806713599320976
    assert v_tp.recall_lb == 0.9806713599320976
    assert v_tp.scope_evidence_status == "SUPPORTED_POSTHOC"
    assert v_tp.authorization_status == "PENDING_PROSPECTIVE"

    # (d) truncating:benign -> NO_CALLS/NOT_APPLICABLE/CLEAR/0-of-1/NOT_APPLICABLE/NOT_AUTHORIZED
    v_tb = decision.scopes["truncating:benign"]
    assert v_tb.data_sufficiency == "NO_CALLS"
    assert v_tb.conditional_performance == "NOT_APPLICABLE"
    assert v_tb.policy_parity == "CLEAR"
    assert v_tb.end_to_end_correct_call_coverage == "0/1"
    assert v_tb.precision_lb is None
    assert v_tb.recall_lb is None
    assert v_tb.scope_evidence_status == "NOT_APPLICABLE"
    assert v_tb.authorization_status == "NOT_AUTHORIZED"

    # (e) other:pathogenic -> ADEQUATE/NOT_APPLICABLE/CLEAR/89-of-117/NOT_APPLICABLE/NOT_AUTHORIZED
    v_op = decision.scopes["other:pathogenic"]
    assert v_op.data_sufficiency == "ADEQUATE"
    assert v_op.conditional_performance == "NOT_APPLICABLE"
    assert v_op.policy_parity == "CLEAR"
    assert v_op.end_to_end_correct_call_coverage == "89/117"
    assert v_op.precision_lb is None
    assert v_op.recall_lb is None
    assert v_op.scope_evidence_status == "NOT_APPLICABLE"
    assert v_op.authorization_status == "NOT_AUTHORIZED"

    # (f) other:benign -> ADEQUATE/NOT_APPLICABLE/CLEAR/112-of-2095/NOT_APPLICABLE/NOT_AUTHORIZED
    # (called 113, fp=1, assert correct coverage is 112/2095, never called/actual 113/2095)
    v_ob = decision.scopes["other:benign"]
    assert v_ob.data_sufficiency == "ADEQUATE"
    assert v_ob.conditional_performance == "NOT_APPLICABLE"
    assert v_ob.policy_parity == "CLEAR"
    assert v_ob.end_to_end_correct_call_coverage == "112/2095"
    assert v_ob.called_count == 113
    assert v_ob.tn == 112
    assert v_ob.fp == 1
    assert v_ob.precision_lb is None
    assert v_ob.recall_lb is None
    assert v_ob.scope_evidence_status == "NOT_APPLICABLE"
    assert v_ob.authorization_status == "NOT_AUTHORIZED"

    # 5. Verify aggregates and statements
    assert decision.full_spectrum_status == "NOT_VALIDATED"
    assert decision.full_spectrum_authorization == "NOT_AUTHORIZED"
    assert decision.research_scope_evidence_status == "SUPPORTED_POSTHOC"
    assert decision.research_scope_authorization == "PENDING_PROSPECTIVE"
    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False
    assert decision.governance_state == "RESEARCH_ONLY_NO_CLINICAL_USE"
    
    expected_gov_statement = (
        "This is a post-hoc re-adjudication of the frozen ADR-0012 "
        "masked-holdout counts for research evidence only; no scope is authorized, "
        "and this authorizes no clinical classification, VUS worklist, or ClinVar "
        "submission pending a prospective validation on unseen data."
    )
    assert decision.governance_statement == expected_gov_statement

    expected_no_new_evidence = (
        "No new evidence was generated: this record re-interprets the frozen R2 aggregate "
        "(source_canonical_lf_sha256 7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f) "
        "under the versioned tiered rule and performs no new run, scoring, annotation, "
        "benchmark read, network access, or data generation."
    )
    assert decision.no_new_evidence_statement == expected_no_new_evidence

    expected_disclaimer = "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."
    assert decision.research_use_disclaimer == expected_disclaimer

    assert decision.prospective_validation_status == "PENDING"
    assert decision.source_content_hash == "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"
    assert decision.source_canonical_lf_sha256 == "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    assert decision.post_hoc is True

    # 6. Verify record has NO field pinning its OWN canonical-LF file SHA
    record_dict = decision.__dict__ if hasattr(decision, "__dict__") else decision
    assert "canonical_lf_file_sha256" not in record_dict
    assert "file_sha256" not in record_dict


def test_cli_wrong_hash_input_failure(tmp_path, monkeypatch):
    """Test the planned scripts.build_tiered_readjudication CLI contract for wrong hash input.

    Monkeypatches REPO_ROOT to a temporary path, copies R2 and configs to their canonical relative paths,
    and asserts that a modified/wrong-hash/one-byte input causes a typed InputError,
    writing neither the output nor the external manifest.
    """
    ROOT = Path(__file__).resolve().parents[2]
    
    canonical_source = tmp_path / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    canonical_config = tmp_path / "configs/eval/tsc2.yaml"
    canonical_tiered_config = tmp_path / "configs/eval/tiered_gate_v3.yaml"
    canonical_output = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.json"
    canonical_manifest = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.sha256"
    
    canonical_source.parent.mkdir(parents=True, exist_ok=True)
    canonical_config.parent.mkdir(parents=True, exist_ok=True)
    
    real_r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    real_config_path = ROOT / "configs/eval/tsc2.yaml"
    real_tiered_config_path = ROOT / "configs/eval/tiered_gate_v3.yaml"
    
    assert real_r2_path.exists(), f"Could not find R2 record at {real_r2_path}"
    canonical_source.write_bytes(real_r2_path.read_bytes())
    
    # Change one byte in that canonical file
    content = bytearray(canonical_source.read_bytes())
    if content:
        content[0] = (content[0] + 1) % 256
    else:
        content = bytearray(b"X")
    canonical_source.write_bytes(content)
    
    if real_config_path.exists():
        canonical_config.write_bytes(real_config_path.read_bytes())
    else:
        canonical_config.write_text("{}")
        
    if real_tiered_config_path.exists():
        canonical_tiered_config.write_bytes(real_tiered_config_path.read_bytes())
    else:
        canonical_tiered_config.write_text("{}")
        
    # Ensure neither output nor manifest pre-exists
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()
    
    try:
        import sys
        this_mod = sys.modules[__name__]
        import scripts.build_tiered_readjudication as cli_mod
        monkeypatch.setattr(cli_mod, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
    except ImportError:
        import sys
        this_mod = sys.modules[__name__]
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
        
    argv = [
        "--source-record", str(canonical_source),
        "--eval-config", str(canonical_config),
        "--tiered-config", str(canonical_tiered_config),
        "--output", str(canonical_output),
        "--external-manifest", str(canonical_manifest),
    ]
    
    try:
        with pytest.raises(InputError):
            main(argv)
    finally:
        assert not canonical_output.exists()
        assert not canonical_manifest.exists()


def test_cli_happy_path(tmp_path, monkeypatch):
    """Test the planned scripts.build_tiered_readjudication CLI contract for happy path."""
    ROOT = Path(__file__).resolve().parents[2]
    
    canonical_source = tmp_path / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    canonical_config = tmp_path / "configs/eval/tsc2.yaml"
    canonical_tiered_config = tmp_path / "configs/eval/tiered_gate_v3.yaml"
    canonical_output = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.json"
    canonical_manifest = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.sha256"
    
    canonical_source.parent.mkdir(parents=True, exist_ok=True)
    canonical_config.parent.mkdir(parents=True, exist_ok=True)
    
    real_r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    real_config_path = ROOT / "configs/eval/tsc2.yaml"
    real_tiered_config_path = ROOT / "configs/eval/tiered_gate_v3.yaml"
    
    assert real_r2_path.exists(), f"Could not find R2 record at {real_r2_path}"
    canonical_source.write_bytes(real_r2_path.read_bytes())
    
    if real_config_path.exists():
        canonical_config.write_bytes(real_config_path.read_bytes())
    else:
        canonical_config.write_text("{}")
        
    if real_tiered_config_path.exists():
        canonical_tiered_config.write_bytes(real_tiered_config_path.read_bytes())
    else:
        canonical_tiered_config.write_text("{}")
        
    # Ensure neither output nor manifest pre-exists
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()
    
    try:
        import sys
        this_mod = sys.modules[__name__]
        import scripts.build_tiered_readjudication as cli_mod
        monkeypatch.setattr(cli_mod, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
    except ImportError:
        import sys
        this_mod = sys.modules[__name__]
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
        
    argv = [
        "--source-record", str(canonical_source),
        "--eval-config", str(canonical_config),
        "--tiered-config", str(canonical_tiered_config),
        "--output", str(canonical_output),
        "--external-manifest", str(canonical_manifest),
    ]
    
    main(argv)
    
    # Assert both outputs now exist
    assert canonical_output.exists()
    assert canonical_manifest.exists()
    
    # Assert canonical LF JSON
    output_bytes = canonical_output.read_bytes()
    assert b"\r\n" not in output_bytes
    output_data = json.loads(output_bytes.decode("utf-8"))
    
    # Assert source hash/content hash, post_hoc=true, internal content_hash
    assert output_data["source_canonical_lf_sha256"] == "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    assert output_data["source_content_hash"] == "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"
    assert output_data["post_hoc"] is True
    assert "content_hash" in output_data
    
    # Assert manifest line/hash agreement
    manifest_text = canonical_manifest.read_text(encoding="utf-8").strip()
    calculated_sha256 = hashlib.sha256(output_bytes).hexdigest()
    assert calculated_sha256 in manifest_text
    assert canonical_output.name in manifest_text

    # Finding 2: Canonical provenance/hash schema assertions
    assert output_data.get("schema") == "raptor.tsc.tiered_readjudication.v3"
    assert output_data.get("date") == "2026-07-21"
    assert output_data.get("post_hoc") is True

    # 2. separate old_semantic_outcome and new_tiered_outcome
    assert "old_semantic_outcome" in output_data
    assert "new_tiered_outcome" in output_data
    assert isinstance(output_data["old_semantic_outcome"], dict)
    assert isinstance(output_data["new_tiered_outcome"], dict)
    assert output_data["old_semantic_outcome"].get("legacy_v1_missense_gate") == "FAIL"
    assert output_data["old_semantic_outcome"].get("full_spectrum_status") == "BLOCKED_POLICY"
    assert output_data["old_semantic_outcome"].get("vus_authorized") is False

    # 3. tiered_config_canonical_sha256 equals SHA-256 of loaded config's block (compact JSON, sort_keys=True)
    from raptor.eval.config import load_tiered_authorization
    loaded_auth = load_tiered_authorization(canonical_tiered_config)
    compact_loaded = json.dumps(loaded_auth, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_loaded_block_sha = hashlib.sha256(compact_loaded).hexdigest()

    raw_mapping = yaml.safe_load(canonical_tiered_config.read_text(encoding="utf-8"))
    compact_raw = json.dumps(raw_mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_raw_sha = hashlib.sha256(compact_raw).hexdigest()

    # Explicitly assert it differs from hashing the raw YAML wrapper containing top-level schema
    assert expected_loaded_block_sha != expected_raw_sha

    # and record must equal the loaded-block hash.
    assert output_data.get("tiered_config_canonical_sha256") == expected_loaded_block_sha

    # 4. implementation_module_sha256 equals Git-blob SHA-256 of tiered_gate.py
    tiered_gate_file = ROOT / "src" / "raptor" / "eval" / "tiered_gate.py"
    gate_lf_bytes = tiered_gate_file.read_bytes().replace(b"\r\n", b"\n")
    expected_module_sha = hashlib.sha256(gate_lf_bytes).hexdigest()
    assert output_data.get("implementation_module_sha256") == expected_module_sha

    # 5. implementation_commit is full 40 lowercase hex and non-null
    import re
    commit = output_data.get("implementation_commit")
    assert commit is not None
    assert isinstance(commit, str)
    assert re.match(r"^[0-9a-f]{40}$", commit)

    # 6. content_hash equals compact canonical JSON of the entire record excluding content_hash
    record_no_hash = {k: v for k, v in output_data.items() if k != "content_hash"}
    expected_content_hash = hashlib.sha256(
        json.dumps(record_no_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert output_data.get("content_hash") == expected_content_hash

    # 7. emitted bytes equal json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode()+b'\n' and LF-only
    expected_bytes = json.dumps(output_data, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    assert output_bytes == expected_bytes
    assert b"\r\n" not in output_bytes

    # 8. external manifest equals actual output file SHA
    manifest_lines = canonical_manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(manifest_lines) == 1
    manifest_sha, manifest_file = manifest_lines[0].split()
    assert manifest_sha == calculated_sha256
    assert manifest_file == canonical_output.name


def test_cli_partial_write_cleanup(tmp_path, monkeypatch):
    """Test that manifest publication failure cleans up output staging/publication."""
    ROOT = Path(__file__).resolve().parents[2]

    canonical_source = tmp_path / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    canonical_config = tmp_path / "configs/eval/tsc2.yaml"
    canonical_tiered_config = tmp_path / "configs/eval/tiered_gate_v3.yaml"
    canonical_output = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.json"
    canonical_manifest = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.sha256"

    canonical_source.parent.mkdir(parents=True, exist_ok=True)
    canonical_config.parent.mkdir(parents=True, exist_ok=True)

    real_r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    real_config_path = ROOT / "configs/eval/tsc2.yaml"
    real_tiered_config_path = ROOT / "configs/eval/tiered_gate_v3.yaml"

    assert real_r2_path.exists()
    canonical_source.write_bytes(real_r2_path.read_bytes())
    if real_config_path.exists():
        canonical_config.write_bytes(real_config_path.read_bytes())
    else:
        canonical_config.write_text("{}")

    if real_tiered_config_path.exists():
        canonical_tiered_config.write_bytes(real_tiered_config_path.read_bytes())
    else:
        canonical_tiered_config.write_text("{}")

    try:
        import sys
        this_mod = sys.modules[__name__]
        import scripts.build_tiered_readjudication as cli_mod
        monkeypatch.setattr(cli_mod, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
    except ImportError:
        import sys
        this_mod = sys.modules[__name__]
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))

    argv = [
        "--source-record", str(canonical_source),
        "--eval-config", str(canonical_config),
        "--tiered-config", str(canonical_tiered_config),
        "--output", str(canonical_output),
        "--external-manifest", str(canonical_manifest),
    ]

    # Intercept write_bytes: succeed on output json, fail on manifest sha256
    orig_write_bytes = Path.write_bytes
    def mocked_write_bytes(self, data, *args, **kwargs):
        if self.name.endswith(".sha256"):
            raise IOError("Simulated manifest publication failure")
        return orig_write_bytes(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", mocked_write_bytes)

    # Assert output and manifest do not exist beforehand
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()

    with pytest.raises((Exception, IOError)):
        main(argv)

    # On the current implementation, this assertion will FAIL because canonical_output was written
    # but not deleted after manifest write failed! This is a RED regression.
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()


def test_cli_post_write_reverify_failure(tmp_path, monkeypatch):
    """Test that post-write reverification failure cleans up both output and manifest."""
    ROOT = Path(__file__).resolve().parents[2]

    canonical_source = tmp_path / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    canonical_config = tmp_path / "configs/eval/tsc2.yaml"
    canonical_tiered_config = tmp_path / "configs/eval/tiered_gate_v3.yaml"
    canonical_output = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.json"
    canonical_manifest = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.sha256"

    canonical_source.parent.mkdir(parents=True, exist_ok=True)
    canonical_config.parent.mkdir(parents=True, exist_ok=True)

    real_r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    real_config_path = ROOT / "configs/eval/tsc2.yaml"
    real_tiered_config_path = ROOT / "configs/eval/tiered_gate_v3.yaml"

    assert real_r2_path.exists()
    canonical_source.write_bytes(real_r2_path.read_bytes())
    if real_config_path.exists():
        canonical_config.write_bytes(real_config_path.read_bytes())
    else:
        canonical_config.write_text("{}")

    if real_tiered_config_path.exists():
        canonical_tiered_config.write_bytes(real_tiered_config_path.read_bytes())
    else:
        canonical_tiered_config.write_text("{}")

    try:
        import sys
        this_mod = sys.modules[__name__]
        import scripts.build_tiered_readjudication as cli_mod
        monkeypatch.setattr(cli_mod, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
    except ImportError:
        import sys
        this_mod = sys.modules[__name__]
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))

    argv = [
        "--source-record", str(canonical_source),
        "--eval-config", str(canonical_config),
        "--tiered-config", str(canonical_tiered_config),
        "--output", str(canonical_output),
        "--external-manifest", str(canonical_manifest),
    ]

    # Intercept read_bytes: during reverification on canonical_output, return corrupted bytes
    orig_read_bytes = Path.read_bytes
    def mocked_read_bytes(self, *args, **kwargs):
        if self == canonical_output:
            return b"corrupted bytes"
        return orig_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", mocked_read_bytes)

    # Assert output and manifest do not exist beforehand
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()

    with pytest.raises(InputError):
        main(argv)

    # On the current implementation, this assertion will FAIL because canonical_output and canonical_manifest
    # were written but not deleted when the InputError was raised! This is a RED regression.
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()


def test_cli_drifted_tiered_config_failure(tmp_path, monkeypatch):
    """Assert that passing an alternate/drifted tiered config path, hash, or schema fails with no output/artifact."""
    ROOT = Path(__file__).resolve().parents[2]
    
    canonical_source = tmp_path / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    canonical_config = tmp_path / "configs/eval/tsc2.yaml"
    canonical_tiered_config = tmp_path / "configs/eval/tiered_gate_v3.yaml"
    canonical_output = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.json"
    canonical_manifest = tmp_path / "data/census/tsc_tiered_readjudication_2026-07-21.sha256"
    
    canonical_source.parent.mkdir(parents=True, exist_ok=True)
    canonical_config.parent.mkdir(parents=True, exist_ok=True)
    
    real_r2_path = ROOT / "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
    real_config_path = ROOT / "configs/eval/tsc2.yaml"
    real_tiered_config_path = ROOT / "configs/eval/tiered_gate_v3.yaml"
    
    assert real_r2_path.exists()
    canonical_source.write_bytes(real_r2_path.read_bytes())
    if real_config_path.exists():
        canonical_config.write_bytes(real_config_path.read_bytes())
    else:
        canonical_config.write_text("{}")
        
    # Write a DRIFTED/alternate tiered config to canonical_tiered_config
    if real_tiered_config_path.exists():
        data = yaml.safe_load(real_tiered_config_path.read_text(encoding="utf-8"))
        data["full_spectrum"]["requires"] = ["truncating:pathogenic"]  # Drifted requires
        canonical_tiered_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    else:
        canonical_tiered_config.write_text("schema_version: 3\nfull_spectrum:\n  requires: []")
        
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()
    
    try:
        import sys
        this_mod = sys.modules[__name__]
        import scripts.build_tiered_readjudication as cli_mod
        monkeypatch.setattr(cli_mod, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
    except ImportError:
        import sys
        this_mod = sys.modules[__name__]
        monkeypatch.setattr(this_mod, "REPO_ROOT", str(tmp_path))
        
    argv = [
        "--source-record", str(canonical_source),
        "--eval-config", str(canonical_config),
        "--tiered-config", str(canonical_tiered_config),
        "--output", str(canonical_output),
        "--external-manifest", str(canonical_manifest),
    ]
    
    with pytest.raises(Exception):
        main(argv)
        
    assert not canonical_output.exists()
    assert not canonical_manifest.exists()
