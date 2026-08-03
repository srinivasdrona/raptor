import pytest
import yaml
import hashlib
import re
from pathlib import Path

# Repository relative root and matrix paths
REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_FILE = REPO_ROOT / "configs/eval/pp3bp4_predictor_matrix.yaml"


def _load_matrix():
    """Load and return the canonical machine matrix as data.
    
    If the file does not exist, raises FileNotFoundError. No imports of planned
    production code that does not exist.
    """
    if not MATRIX_FILE.exists():
        raise FileNotFoundError(f"Canonical machine matrix file not found: {MATRIX_FILE}")
    with open(MATRIX_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def test_t1_exact_candidate_ids():
    """T1: Canonical machine matrix contains exactly the 16 candidate IDs plus bias_composite."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    # Support dictionary mapping or list of dictionaries
    if isinstance(candidates, dict):
        candidate_ids = set(candidates.keys())
    else:
        candidate_ids = {r.get("candidate_id") for r in candidates if r.get("candidate_id")}

    if isinstance(audit_rows, dict):
        audit_ids = set(audit_rows.keys())
    else:
        audit_ids = {r.get("candidate_id") for r in audit_rows if r.get("candidate_id")}

    expected_candidates = {
        'revel', 'bayesdel_noaf', 'mutpred2', 'vest4', 'alphamissense', 'esm1b', 'varity_r',
        'cadd', 'evolutionary_action', 'fathmm', 'gerp_plus_plus', 'mpc', 'phylop',
        'polyphen2_humvar', 'primateai_original', 'sift'
    }
    expected_audit_rows = {'bias_composite'}

    assert candidate_ids == expected_candidates, f"Candidates mismatch. Got: {candidate_ids}"
    assert audit_ids == expected_audit_rows, f"Audit rows mismatch. Got: {audit_ids}"


def test_t2_rejected_aliases():
    """T2: Aliases PrimateAI-3D, generic VARITY/VARITY_ER, and BayesDel-addAF are rejected."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    records = []
    if isinstance(candidates, dict):
        records.extend(candidates.values())
    else:
        records.extend(candidates)

    forbidden_ids = {"primateai_3d", "primateai-3d", "varity", "varity_er", "bayesdel_addaf"}
    
    for r in records:
        cid = r.get("candidate_id")
        assert cid not in forbidden_ids, f"Forbidden candidate ID '{cid}' used."

        display_name = r.get("display_name", "")
        # Reject aliases in display names
        if cid == "primateai_original":
            assert "3d" not in display_name.lower(), f"primateai_original display name '{display_name}' has 3D alias."
        elif cid == "varity_r":
            assert display_name != "VARITY" and display_name != "VARITY_ER", f"varity_r display name '{display_name}' is generic."
        elif cid == "bayesdel_noaf":
            assert "addaf" not in display_name.lower(), f"bayesdel_noaf display name '{display_name}' contains addAF."


def test_t3_closed_schemas():
    """T3: Every record uses the closed identity/routing + fact_object field set; unknown/missing fields fail."""
    matrix = _load_matrix()

    # Closed top-level schema check (must have exactly these 7 keys)
    expected_top_level = {
        "schema", "version", "source_map", "confirm_pending_register",
        "candidates", "audit_rows", "smallest_pin_handoff"
    }
    assert set(matrix.keys()) == expected_top_level, f"Top-level keys mismatch. Got: {set(matrix.keys())}, expected: {expected_top_level}"

    # Closed record fields check (must have exactly these 24 keys, both candidates and audit rows)
    expected_record_fields = {
        "candidate_id", "display_name", "tool_kind", "evidence_role",
        "calibration_source_id", "calibration_locus", "score_direction",
        "transcript_and_consequence_scope", "component_or_feature_overlap",
        "structured_score_source", "license_source", "disposition", "rationale_source_ids",
        "calibrated_score_intervals", "explicit_indeterminate_interval",
        "maximum_supported_pp3_strength", "maximum_supported_bp4_strength",
        "calibrated_version", "current_release_pin_status",
        "structured_score_availability", "license_status",
        "training_manifest_status", "tsc_specific_evidence", "implementation_cost"
    }

    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})
    
    records = []
    if isinstance(candidates, dict):
        records.extend(candidates.values())
    else:
        records.extend(candidates)
        
    if isinstance(audit_rows, dict):
        records.extend(audit_rows.values())
    else:
        records.extend(audit_rows)

    for r in records:
        cid = r.get("candidate_id")
        # Ensure the record contains exactly the 24 schema fields (no extras, no omissions)
        assert set(r.keys()) == expected_record_fields, f"Record '{cid}' keys mismatch. Got: {set(r.keys())}, expected: {expected_record_fields}"


def test_t4_self_contained_source_map():
    """T4: Every source ID (records + fact objects) resolves within the matrix source_map, and each source_map entry carries a citation plus at least one of DOI/PMID/PMC/URL and a locus (the matrix is self-contained; no session-state file is referenced)."""
    matrix = _load_matrix()
    source_map = matrix.get("source_map", {})

    # Scan raw YAML text to ensure no session-state file path or UUID references exist
    raw_content = MATRIX_FILE.read_text(encoding="utf-8")
    assert "90703341" not in raw_content, "Found forbidden session state UUID in matrix file."
    assert "7c146921" not in raw_content, "Found forbidden session state UUID in matrix file."
    assert "session-state" not in raw_content.lower(), "Found forbidden 'session-state' reference in matrix file."

    # Validate each entry in source_map
    for src_id, entry in source_map.items():
        assert "session-state" not in str(entry).lower(), f"Source map entry '{src_id}' references session-state."
        assert "citation" in entry, f"Source map entry '{src_id}' is missing a citation."
        assert isinstance(entry["citation"], str) and entry["citation"].strip(), f"Source map entry '{src_id}' citation is not a non-empty string."

        # At least one of DOI, PMID, PMC, URL, preprint_doi
        has_id = any(
            k in entry and isinstance(entry[k], str) and entry[k].strip()
            for k in ["doi", "pmid", "pmc", "url", "preprint_doi"]
        )
        assert has_id, f"Source map entry '{src_id}' must contain at least one of doi, pmid, pmc, url, preprint_doi."

        # Must have a locus or loci
        has_locus = ("locus" in entry and entry["locus"]) or ("loci" in entry and entry["loci"])
        assert has_locus, f"Source map entry '{src_id}' must have a locus or loci."

    # Collect all source_ids used in candidates and audit_rows
    used_source_ids = set()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})
    
    records = []
    if isinstance(candidates, dict):
        records.extend(candidates.values())
    else:
        records.extend(candidates)
        
    if isinstance(audit_rows, dict):
        records.extend(audit_rows.values())
    else:
        records.extend(audit_rows)

    fact_object_fields = {
        "calibrated_score_intervals", "explicit_indeterminate_interval",
        "maximum_supported_pp3_strength", "maximum_supported_bp4_strength",
        "calibrated_version", "current_release_pin_status",
        "structured_score_availability", "license_status",
        "training_manifest_status", "tsc_specific_evidence", "implementation_cost"
    }

    for r in records:
        if r.get("calibration_source_id"):
            used_source_ids.add(r.get("calibration_source_id"))
        if r.get("rationale_source_ids"):
            for rsid in r.get("rationale_source_ids"):
                used_source_ids.add(rsid)

        for field in fact_object_fields:
            fact_obj = r.get(field)
            if isinstance(fact_obj, dict):
                src_ids = fact_obj.get("source_ids", [])
                if isinstance(src_ids, list):
                    for s in src_ids:
                        used_source_ids.add(s)

    # Ensure every used source ID resolves in the source_map
    for usid in used_source_ids:
        assert usid in source_map, f"Used source ID '{usid}' not found in top-level source_map."


def test_t5_only_revel_verified_intervals():
    """T5: Only REVEL has status: verified interval fact objects; all other candidates' interval fields are confirm_pending."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    records = {}
    if isinstance(candidates, dict):
        records = candidates
    else:
        records = {r.get("candidate_id"): r for r in candidates if r.get("candidate_id")}

    assert "revel" in records, "revel candidate not found in matrix."
    revel_intervals = records["revel"].get("calibrated_score_intervals")
    assert isinstance(revel_intervals, dict), "revel calibrated_score_intervals must be a fact-object dictionary."
    assert revel_intervals.get("status") == "verified", f"revel calibrated_score_intervals status must be 'verified', got: {revel_intervals.get('status')}"

    # Verify all other candidates have confirm_pending for calibrated_score_intervals
    for cid, record in records.items():
        if cid == "revel":
            continue
        interval = record.get("calibrated_score_intervals")
        assert isinstance(interval, dict), f"Candidate '{cid}' calibrated_score_intervals must be a fact-object dictionary."
        assert interval.get("status") == "confirm_pending", f"Candidate '{cid}' calibrated_score_intervals status must be 'confirm_pending', got: {interval.get('status')}"


def test_t6_markdown_parity():
    """T6: Markdown candidate IDs and material dispositions match the canonical machine matrix via explicit column contract."""
    matrix = _load_matrix()
    md_file = REPO_ROOT / "docs/reference/pp3bp4-candidate-matrix-2026-07.md"
    assert md_file.exists(), f"Markdown candidate matrix file not found: {md_file}"

    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    # Extract rows of the Candidate matrix table
    match = re.search(r'## 2\. Candidate matrix\s*\n\n?(.*?)(?:\n\n|\n[^|]|$)', md_content, re.DOTALL)
    if not match:
        table_lines = [line.strip() for line in md_content.splitlines() if line.strip().startswith('|')]
    else:
        table_lines = [line.strip() for line in match.group(1).splitlines() if line.strip().startswith('|')]

    if not table_lines:
        pytest.fail("No table lines found under Candidate matrix.")

    # Locate column headers in the table's first row
    header_parts = [p.strip().lower() for p in table_lines[0].split('|')[1:-1]]
    
    # Require an explicit "candidate_id" or "candidate id" column/marker in the Markdown table
    if "candidate_id" not in header_parts and "candidate id" not in header_parts:
        raise KeyError("Markdown table is missing an explicit 'candidate_id' or 'candidate id' column header.")
    
    cid_idx = header_parts.index("candidate_id") if "candidate_id" in header_parts else header_parts.index("candidate id")

    # Find "decision" or "disposition" column index
    decision_indices = [i for i, h in enumerate(header_parts) if h in ["decision", "disposition"]]
    if not decision_indices:
        raise KeyError("Markdown table is missing a 'decision' or 'disposition' column header.")
    disp_idx = decision_indices[0]

    parsed_md = {}
    for line in table_lines[1:]:
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if not parts or parts[0].startswith('---'):
            continue
        if len(parts) <= max(cid_idx, disp_idx):
            continue

        candidate_id = parts[cid_idx].replace('`', '').replace('*', '').strip()
        decision = parts[disp_idx].replace('`', '').replace('*', '').strip().lower()

        parsed_md[candidate_id] = decision

    # Collect YAML candidates and dispositions
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})
    yaml_records = {}
    if isinstance(candidates, dict):
        yaml_records.update(candidates)
    else:
        yaml_records.update({r.get("candidate_id"): r for r in candidates if r.get("candidate_id")})

    if isinstance(audit_rows, dict):
        yaml_records.update(audit_rows)
    else:
        yaml_records.update({r.get("candidate_id"): r for r in audit_rows if r.get("candidate_id")})

    # Assert exact Markdown ID set matches YAML 16 + bias
    assert set(parsed_md.keys()) == set(yaml_records.keys()), (
        f"Markdown IDs mismatch. Markdown set: {set(parsed_md.keys())}, YAML set: {set(yaml_records.keys())}"
    )

    # Assert exact dispositions match
    for cid, record in yaml_records.items():
        yaml_disp = record.get("disposition")
        md_disp = parsed_md[cid]
        assert yaml_disp == md_disp, f"Disposition mismatch for '{cid}': YAML={yaml_disp}, MD={md_disp}"


def test_t7_single_advance_shadow_revel():
    """T7: Exactly one candidate has disposition advance_shadow and it is REVEL."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    records = []
    if isinstance(candidates, dict):
        records = list(candidates.values())
    else:
        records = candidates

    advance_shadow_cids = []
    for r in records:
        if r.get("disposition") == "advance_shadow":
            advance_shadow_cids.append(r.get("candidate_id"))

    assert len(advance_shadow_cids) == 1, f"Expected exactly one advance_shadow candidate, got: {advance_shadow_cids}"
    assert advance_shadow_cids[0] == "revel", f"Expected 'revel' to be the only advance_shadow candidate, got: {advance_shadow_cids[0]}"


def test_t8_conservation_context_evidence_role():
    """T8: GERP++ and PhyloP carry evidence_role conservation_context and cannot be treated as independent votes."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    records = {}
    if isinstance(candidates, dict):
        records = candidates
    else:
        records = {r.get("candidate_id"): r for r in candidates if r.get("candidate_id")}

    for cid in ["gerp_plus_plus", "phylop"]:
        assert cid in records, f"Conservation candidate '{cid}' not found in matrix."
        record = records[cid]
        assert record.get("evidence_role") == "conservation_context", f"'{cid}' must have evidence_role 'conservation_context', got: {record.get('evidence_role')}"
        assert record.get("disposition") == "shadow_comparator", f"'{cid}' disposition should be shadow_comparator, got: {record.get('disposition')}"


def test_t9_training_manifest_status_isolated():
    """T9: Matrix training_manifest_status is a metadata fact object; it does not alter predictor_training_manifests.yaml or leakage-audit inputs."""
    # Byte-for-byte check of predictor_training_manifests.yaml
    manifest_path = REPO_ROOT / "configs/eval/predictor_training_manifests.yaml"
    expected_hash = "64208cd23081d5c99db332709b5de6b3603ac7e11d7bcc203ca7f74f952f229c"
    actual_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert actual_hash == expected_hash, "predictor_training_manifests.yaml has been modified."

    # Check training_manifest_status fact object in candidates
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    records = []
    if isinstance(candidates, dict):
        records = list(candidates.values())
    else:
        records = candidates

    for r in records:
        cid = r.get("candidate_id")
        assert "training_manifest_status" in r, f"Candidate '{cid}' is missing 'training_manifest_status'."
        status_obj = r.get("training_manifest_status")
        assert isinstance(status_obj, dict), f"training_manifest_status in '{cid}' must be a fact-object dictionary."
        assert "status" in status_obj, f"training_manifest_status in '{cid}' has no status."
        assert status_obj.get("status") in ["verified", "confirm_pending", "unavailable", "not_applicable"]


def test_t10_preserved_hashes_integrity():
    """T10: The three preserved artifacts match their base SHA-256 values byte-for-byte (2e9c1f21..., 64208cd2..., 6bba6b90...)."""
    files_to_check = {
        "configs/eval/pp3bp4_source_register.yaml": "2e9c1f215f24bf6ea6fffa697737f84092e6c5fce02db5e74c91e479f0b36932",
        "configs/eval/predictor_training_manifests.yaml": "64208cd23081d5c99db332709b5de6b3603ac7e11d7bcc203ca7f74f952f229c",
        "configs/eval/pp3bp4_candidate_policy.json": "6bba6b906c7bf1296450c8f1df4addda052f5d3ee90f45879a062d02980428b2"
    }
    for relative_path, expected_sha in files_to_check.items():
        abs_path = REPO_ROOT / relative_path
        assert abs_path.exists(), f"Preserved file {relative_path} not found."
        actual_sha = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"Preserved file {relative_path} hash changed. Got {actual_sha}, expected {expected_sha}"


def test_t11_no_production_wiring():
    """T11: No scorer, gate, packet, terminal, census, or production-policy wiring is added."""
    src_dir = REPO_ROOT / "src" / "raptor"
    assert src_dir.exists(), "src/raptor directory not found."

    forbidden_references = ["pp3bp4_predictor_matrix.yaml", "pp3bp4_predictor_matrix"]
    violating_files = []

    for py_file in src_dir.glob("**/*.py"):
        content = py_file.read_text(encoding="utf-8")
        for ref in forbidden_references:
            if ref in content:
                violating_files.append((str(py_file.relative_to(REPO_ROOT)), ref))

    assert not violating_files, f"Forbidden references/wiring found in production files: {violating_files}"


def test_t12_fact_object_schema_validation():
    """T12: Every fact object obeys fact_status.fact_object.validation (status/value/source_ids/cp_ids), and every cp_id resolves to the top-level confirm_pending_register; no CP id is comment-only."""
    matrix = _load_matrix()
    cp_register = matrix.get("confirm_pending_register", {})
    assert isinstance(cp_register, dict), "confirm_pending_register must be a dictionary."

    # Validate top-level confirm_pending_register
    for cp_id, resolution in cp_register.items():
        assert isinstance(cp_id, str) and cp_id.startswith("CP-"), f"Invalid CP ID format: {cp_id}"
        assert isinstance(resolution, str) and resolution.strip(), f"Resolution for '{cp_id}' must be a non-empty string."

    fact_object_fields = {
        "calibrated_score_intervals", "explicit_indeterminate_interval",
        "maximum_supported_pp3_strength", "maximum_supported_bp4_strength",
        "calibrated_version", "current_release_pin_status",
        "structured_score_availability", "license_status",
        "training_manifest_status", "tsc_specific_evidence", "implementation_cost"
    }

    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    records = []
    if isinstance(candidates, dict):
        records.extend(candidates.values())
    else:
        records.extend(candidates)

    if isinstance(audit_rows, dict):
        records.extend(audit_rows.values())
    else:
        records.extend(audit_rows)

    for r in records:
        cid = r.get("candidate_id")
        for field in fact_object_fields:
            fact_obj = r.get(field)
            assert isinstance(fact_obj, dict), f"Field '{field}' in '{cid}' must be a dictionary fact-object."

            # Closed schema for fact-object
            allowed_keys = {"status", "value", "source_ids", "cp_ids", "note"}
            fact_keys = set(fact_obj.keys())
            extra_keys = fact_keys - allowed_keys
            assert not extra_keys, f"Fact object '{field}' in '{cid}' has unexpected keys: {extra_keys}"

            status = fact_obj.get("status")
            assert status in ["verified", "confirm_pending", "unavailable", "not_applicable"], f"Invalid status '{status}' in '{field}' for '{cid}'"

            value = fact_obj.get("value")
            source_ids = fact_obj.get("source_ids", [])
            cp_ids = fact_obj.get("cp_ids", [])

            assert isinstance(source_ids, list), f"source_ids in '{field}' for '{cid}' must be a list."
            assert isinstance(cp_ids, list), f"cp_ids in '{field}' for '{cid}' must be a list."

            for s in source_ids:
                assert isinstance(s, str), f"source_id in '{field}' for '{cid}' must be a string."
            for c in cp_ids:
                assert isinstance(c, str), f"cp_id in '{field}' for '{cid}' must be a string."
                assert c in cp_register, f"cp_id '{c}' in '{field}' for '{cid}' does not exist in confirm_pending_register"

            # Validate specific status rules
            if status == "verified":
                assert value is not None, f"verified status in '{field}' for '{cid}' requires non-null value."
                assert len(source_ids) >= 1, f"verified status in '{field}' for '{cid}' requires >= 1 source_id."
                assert len(cp_ids) == 0, f"verified status in '{field}' for '{cid}' cannot have cp_ids."
            elif status == "confirm_pending":
                assert value is None or isinstance(value, dict), f"confirm_pending status in '{field}' for '{cid}' must have null or dict value."
                assert len(cp_ids) >= 1, f"confirm_pending status in '{field}' for '{cid}' requires >= 1 cp_id."
            elif status == "unavailable":
                assert value is None, f"unavailable status in '{field}' for '{cid}' requires null value."
                note = fact_obj.get("note")
                assert (isinstance(note, str) and note.strip()) or len(source_ids) > 0, f"unavailable status in '{field}' for '{cid}' requires note or source explaining why."
            elif status == "not_applicable":
                assert value is None, f"not_applicable status in '{field}' for '{cid}' requires null value."
                # T12 revision: must carry a rationale note or source IDs
                note = fact_obj.get("note")
                assert (isinstance(note, str) and note.strip()) or len(source_ids) > 0, (
                    f"not_applicable status in '{field}' for '{cid}' must carry a rationale note or source_ids explaining why."
                )


def test_t13_markdown_backing_relabeling():
    """T13: Markdown Backing config names pp3bp4_predictor_matrix.yaml (not the source register); the memo relation table labels the matrix and the REVEL provenance register distinctly."""
    matrix_md_file = REPO_ROOT / "docs/reference/pp3bp4-candidate-matrix-2026-07.md"
    assert matrix_md_file.exists(), "Candidate matrix markdown file not found."
    matrix_md = matrix_md_file.read_text(encoding="utf-8")

    # Backing config must name configs/eval/pp3bp4_predictor_matrix.yaml in the markdown configuration table
    backing_lines = [line for line in matrix_md.splitlines() if "backing config" in line.lower()]
    assert backing_lines, "Could not find 'Backing config' row in Candidate matrix markdown."
    assert "configs/eval/pp3bp4_predictor_matrix.yaml" in backing_lines[0], f"Backing config row does not reference pp3bp4_predictor_matrix.yaml: {backing_lines[0]}"

    recommendation_md_file = REPO_ROOT / "docs/reference/pp3-bp4-predictor-policy-recommendation-2026-07.md"
    assert recommendation_md_file.exists(), "Recommendation memo markdown file not found."
    rec_md = recommendation_md_file.read_text(encoding="utf-8")

    # Both configs must be named in the relation table
    assert "configs/eval/pp3bp4_predictor_matrix.yaml" in rec_md, "Recommendation memo does not reference pp3bp4_predictor_matrix.yaml"
    assert "configs/eval/pp3bp4_source_register.yaml" in rec_md, "Recommendation memo does not reference pp3bp4_source_register.yaml"

    # Parse and identify actual relation-table rows to verify distinct definitions
    rel_rows = []
    for line in rec_md.splitlines():
        if line.strip().startswith("|") and ("pp3bp4_predictor_matrix.yaml" in line or "pp3bp4_source_register.yaml" in line):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 2:
                rel_rows.append(parts)

    matrix_row = [r for r in rel_rows if "pp3bp4_predictor_matrix.yaml" in r[0]]
    source_row = [r for r in rel_rows if "pp3bp4_source_register.yaml" in r[0]]

    assert matrix_row, "Relation table row for pp3bp4_predictor_matrix.yaml not found."
    assert source_row, "Relation table row for pp3bp4_source_register.yaml not found."

    # Parse columns of the relation table to check description details
    matrix_desc = " ".join(matrix_row[0][1:]).lower()
    assert "comprehensive" in matrix_desc and "decision matrix" in matrix_desc, f"Matrix row does not describe comprehensive decision matrix: {matrix_row[0]}"

    source_desc = " ".join(source_row[0][1:]).lower()
    assert "revel" in source_desc and "provenance" in source_desc, f"Source register row does not describe REVEL policy provenance: {source_row[0]}"


def test_t14_exact_tool_kind_map():
    """T14: Every candidate's tool_kind equals candidate_identity.tool_kind_map exactly in the machine matrix; BayesDel-noAF is meta_predictor."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    expected_tool_kinds = {
        "revel": "meta_predictor",
        "bayesdel_noaf": "meta_predictor",
        "cadd": "meta_annotation_score",
        "evolutionary_action": "evolutionary_predictor",
        "fathmm": "hmm_predictor",
        "gerp_plus_plus": "conservation",
        "phylop": "conservation",
        "mpc": "regional_constraint",
        "mutpred2": "supervised_predictor",
        "vest4": "supervised_predictor",
        "polyphen2_humvar": "missense_predictor",
        "primateai_original": "deep_learning_predictor",
        "sift": "homology_predictor",
        "alphamissense": "protein_language_ml_predictor",
        "esm1b": "protein_language_model",
        "varity_r": "supervised_rare_variant_model",
        "bias_composite": "custom_composite"
    }

    for cid, r in candidates.items():
        assert cid in expected_tool_kinds, f"Unexpected candidate '{cid}'"
        assert r.get("tool_kind") == expected_tool_kinds[cid], (
            f"Candidate '{cid}' tool_kind mismatch. Got: {r.get('tool_kind')}, Expected: {expected_tool_kinds[cid]}"
        )

    for cid, r in audit_rows.items():
        assert cid in expected_tool_kinds, f"Unexpected audit row '{cid}'"
        assert r.get("tool_kind") == expected_tool_kinds[cid], (
            f"Audit row '{cid}' tool_kind mismatch. Got: {r.get('tool_kind')}, Expected: {expected_tool_kinds[cid]}"
        )


def test_t15_markdown_machine_parity():
    """T15: Markdown/machine parity for every row: candidate_id, display_name, tool_kind, evidence_role, calibration source, and disposition match the canonical machine matrix."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    yaml_records = {}
    yaml_records.update(candidates)
    yaml_records.update(audit_rows)

    md_file = REPO_ROOT / "docs/reference/pp3bp4-candidate-matrix-2026-07.md"
    assert md_file.exists(), f"Markdown file not found: {md_file}"

    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    # Extract rows of the Candidate matrix table under Section 2
    match = re.search(r'## 2\. Candidate matrix\s*\n\n?(.*?)(?:\n\n|\n[^|]|$)', md_content, re.DOTALL)
    if not match:
        table_lines = [line.strip() for line in md_content.splitlines() if line.strip().startswith('|')]
    else:
        table_lines = [line.strip() for line in match.group(1).splitlines() if line.strip().startswith('|')]

    if not table_lines:
        pytest.fail("No table lines found under Candidate matrix.")

    # Locate column headers in the table's first row
    headers = [h.strip().lower() for h in table_lines[0].split('|')[1:-1]]
    cid_idx = headers.index("candidate id")
    name_idx = headers.index("display name")
    kind_idx = headers.index("tool kind")
    role_idx = headers.index("evidence role")
    source_idx = headers.index("calibration source")
    dec_idx = headers.index("decision") if "decision" in headers else headers.index("disposition")

    parsed_md = {}
    for line in table_lines[1:]:
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if not parts or parts[0].startswith('---'):
            continue
        if len(parts) <= max(cid_idx, name_idx, kind_idx, role_idx, source_idx, dec_idx):
            continue

        cid = parts[cid_idx].replace('`', '').replace('*', '').strip()
        parsed_md[cid] = {
            "display_name": parts[name_idx].replace('`', '').replace('*', '').strip(),
            "tool_kind": parts[kind_idx].replace('`', '').replace('*', '').strip(),
            "evidence_role": parts[role_idx].replace('`', '').replace('*', '').strip(),
            "calibration_source": parts[source_idx].replace('`', '').replace('*', '').strip(),
            "disposition": parts[dec_idx].replace('`', '').replace('*', '').strip().lower()
        }

    # Verify exact set match
    assert set(parsed_md.keys()) == set(yaml_records.keys()), (
        f"Markdown IDs mismatch. Markdown set: {set(parsed_md.keys())}, YAML set: {set(yaml_records.keys())}"
    )

    # Parity comparisons
    for cid, yaml_r in yaml_records.items():
        md_r = parsed_md[cid]
        assert yaml_r.get("display_name") == md_r["display_name"], f"'{cid}' display_name mismatch"
        assert yaml_r.get("tool_kind") == md_r["tool_kind"], f"'{cid}' tool_kind mismatch"
        assert yaml_r.get("evidence_role") == md_r["evidence_role"], f"'{cid}' evidence_role mismatch"
        assert yaml_r.get("disposition") == md_r["disposition"], f"'{cid}' disposition mismatch"

        yaml_source_id = yaml_r.get("calibration_source_id")
        md_source = md_r["calibration_source"]
        if yaml_source_id is None or yaml_source_id == "null" or yaml_source_id == "none":
            assert "none" in md_source.lower() or md_source == "" or md_source == "null"
        else:
            # Check author and year substrings match
            author, year = yaml_source_id.split("_")
            assert author.lower() in md_source.lower(), f"'{cid}' calibration source author mismatch"
            assert year in md_source, f"'{cid}' calibration source year mismatch"


def test_t16_cp20_allowed_set():
    """T16: training_manifest_status carries CP-20 ONLY for cadd, evolutionary_action, mpc, phylop, gerp_plus_plus, primateai_original; no other candidate carries CP-20, and each such row uses an honest note with empty source_ids."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    allowed_cp20_set = {"cadd", "evolutionary_action", "mpc", "phylop", "gerp_plus_plus", "primateai_original"}

    for cid, r in candidates.items():
        tms = r.get("training_manifest_status", {})
        cp_ids = tms.get("cp_ids", [])
        source_ids = tms.get("source_ids", [])

        if "CP-20" in cp_ids:
            assert cid in allowed_cp20_set, f"Candidate '{cid}' must NOT carry CP-20"
            note = tms.get("note", "")
            assert isinstance(note, str) and "manifest not obtained" in note, f"Candidate '{cid}' training_manifest_status lacks honest note"
            assert len(source_ids) == 0, f"Candidate '{cid}' training_manifest_status has non-empty source_ids with CP-20"
        else:
            assert cid not in allowed_cp20_set, f"Candidate '{cid}' must carry CP-20 in training_manifest_status"

    bias_tms = audit_rows["bias_composite"].get("training_manifest_status", {})
    assert "CP-20" not in bias_tms.get("cp_ids", []), "bias_composite must not carry CP-20"


def test_t17_field_cp_allowlists():
    """T17: Field-CP allowlist (field_cp_semantics): each fact-object field's cp_ids are drawn only from the allowed set for that field/candidate; CP-21 appears only on REVEL current_release_pin_status; interval CPs (CP-1..CP-7) never appear on version/release/licence/availability/pin fields."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    all_records = {}
    all_records.update(candidates)
    all_records.update(audit_rows)

    interval_fields = {"calibrated_score_intervals", "explicit_indeterminate_interval", "maximum_supported_pp3_strength", "maximum_supported_bp4_strength"}
    interval_cps = {"CP-1", "CP-2", "CP-3", "CP-4", "CP-5", "CP-6", "CP-7"}

    for cid, r in all_records.items():
        for field, obj in r.items():
            if not isinstance(obj, dict) or "status" not in obj:
                continue

            cp_ids = obj.get("cp_ids", [])

            # General rules check
            if "CP-21" in cp_ids:
                assert cid == "revel" and field == "current_release_pin_status", (
                    f"CP-21 found on illegal candidate/field combo: {cid}.{field}"
                )

            if any(cp in interval_cps for cp in cp_ids):
                assert field in interval_fields, (
                    f"Interval CP found on version/release/licence/availability/pin field: {cid}.{field}"
                )

            # Field-specific check
            if field in interval_fields:
                if cid == "revel" or cid == "bias_composite":
                    assert not cp_ids, f"'{cid}' interval field must not have cp_ids"
                elif cid == "bayesdel_noaf":
                    assert set(cp_ids).issubset({"CP-1"})
                elif cid == "mutpred2":
                    assert set(cp_ids).issubset({"CP-2"})
                elif cid == "vest4":
                    assert set(cp_ids).issubset({"CP-3"})
                elif cid in ["cadd", "evolutionary_action", "fathmm", "gerp_plus_plus", "mpc", "phylop", "polyphen2_humvar", "primateai_original", "sift"]:
                    assert set(cp_ids).issubset({"CP-4"})
                elif cid == "alphamissense":
                    assert set(cp_ids).issubset({"CP-5"})
                elif cid == "esm1b":
                    assert set(cp_ids).issubset({"CP-6"})
                elif cid == "varity_r":
                    assert set(cp_ids).issubset({"CP-7"})

            elif field == "calibrated_version":
                if cid in ["bayesdel_noaf", "cadd", "evolutionary_action", "mutpred2", "polyphen2_humvar"]:
                    assert set(cp_ids).issubset({"CP-9"})
                elif cid in ["revel", "fathmm", "gerp_plus_plus", "mpc", "sift", "vest4"]:
                    assert set(cp_ids).issubset({"CP-23"})
                elif cid == "phylop":
                    assert set(cp_ids).issubset({"CP-14"})
                elif cid == "primateai_original":
                    assert set(cp_ids).issubset({"CP-15"})
                elif cid == "alphamissense":
                    assert set(cp_ids).issubset({"CP-10"})
                elif cid == "esm1b":
                    assert set(cp_ids).issubset({"CP-22"})
                elif cid == "varity_r":
                    assert set(cp_ids).issubset({"CP-11"})
                else:
                    assert not cp_ids

            elif field == "current_release_pin_status":
                if cid == "revel":
                    assert set(cp_ids).issubset({"CP-21"})
                elif cid == "bias_composite":
                    assert not cp_ids
                else:
                    assert set(cp_ids).issubset({"CP-28"})

            elif field == "structured_score_availability":
                if cid in ["revel", "bayesdel_noaf", "cadd", "fathmm", "gerp_plus_plus", "mpc", "phylop", "polyphen2_humvar", "primateai_original", "sift", "vest4", "alphamissense"]:
                    assert set(cp_ids).issubset({"CP-25"})
                elif cid == "esm1b":
                    assert set(cp_ids).issubset({"CP-12"})
                elif cid == "varity_r":
                    assert set(cp_ids).issubset({"CP-13"})
                elif cid == "mutpred2":
                    assert set(cp_ids).issubset({"CP-26"})
                elif cid == "evolutionary_action":
                    assert set(cp_ids).issubset({"CP-27"})
                else:
                    assert not cp_ids

            elif field == "license_status":
                if cid == "mpc":
                    assert set(cp_ids).issubset({"CP-16"})
                elif cid == "gerp_plus_plus":
                    assert set(cp_ids).issubset({"CP-17"})
                elif cid == "phylop":
                    assert set(cp_ids).issubset({"CP-18"})
                elif cid == "evolutionary_action":
                    assert set(cp_ids).issubset({"CP-19"})
                elif cid == "bias_composite":
                    assert not cp_ids
                else:
                    assert set(cp_ids).issubset({"CP-24"})

            elif field == "training_manifest_status":
                if cid in ["cadd", "evolutionary_action", "mpc", "phylop", "gerp_plus_plus", "primateai_original"]:
                    assert set(cp_ids).issubset({"CP-20"})
                else:
                    assert not cp_ids

            elif field == "tsc_specific_evidence":
                assert not cp_ids

            elif field == "implementation_cost":
                assert not cp_ids, f"implementation_cost has cp_ids on '{cid}'"


def test_t18_bergquist_release_facts():
    """T18: Bergquist release facts (alphamissense/esm1b/varity_r calibrated_version) use CP-10/CP-22/CP-11 with source_ids [bergquist_2025] (methods_data_availability locus); ESM1b evaluated release uses CP-22, never interval CP-6."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    assert "alphamissense" in candidates
    assert "esm1b" in candidates
    assert "varity_r" in candidates

    # AlphaMissense calibrated_version
    am_cv = candidates["alphamissense"].get("calibrated_version", {})
    assert "CP-10" in am_cv.get("cp_ids", [])
    assert am_cv.get("source_ids") == ["bergquist_2025"]

    # ESM1b calibrated_version (uses dedicated CP-22 release fact, never CP-6 interval fact)
    esm_cv = candidates["esm1b"].get("calibrated_version", {})
    assert "CP-22" in esm_cv.get("cp_ids", [])
    assert "CP-6" not in esm_cv.get("cp_ids", [])
    assert esm_cv.get("source_ids") == ["bergquist_2025"]

    # VARITY_R calibrated_version
    vr_cv = candidates["varity_r"].get("calibrated_version", {})
    assert "CP-11" in vr_cv.get("cp_ids", [])
    assert vr_cv.get("source_ids") == ["bergquist_2025"]


def test_t19_evidence_and_cost_disciplines():
    """T19: tsc_specific_evidence for every calibrated row is unavailable/none-identified (never not_applicable; not_applicable only for bias_composite); implementation_cost for every row is unavailable with no cp_ids and empty source_ids."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})
    audit_rows = matrix.get("audit_rows", {})

    all_records = {}
    all_records.update(candidates)
    all_records.update(audit_rows)

    for cid, r in candidates.items():
        tse = r.get("tsc_specific_evidence", {})
        assert tse.get("status") == "unavailable", f"'{cid}' tsc_specific_evidence must be unavailable"
        assert tse.get("status") != "not_applicable", f"'{cid}' tsc_specific_evidence must never be not_applicable"
        note = tse.get("note", "")
        assert isinstance(note, str) and "none identified" in note, f"'{cid}' tse lacks 'none identified' note"

    bias_tse = audit_rows["bias_composite"].get("tsc_specific_evidence", {})
    assert bias_tse.get("status") == "not_applicable", "bias_composite tsc_specific_evidence must be not_applicable"

    # implementation_cost must be unavailable for EVERY row, including bias_composite
    for cid, r in all_records.items():
        ic = r.get("implementation_cost", {})
        assert ic.get("status") == "unavailable", f"'{cid}' implementation_cost must be unavailable"
        assert ic.get("value") is None, f"'{cid}' implementation_cost value must be null"
        assert not ic.get("cp_ids"), f"'{cid}' implementation_cost must have no cp_ids"
        assert not ic.get("source_ids"), f"'{cid}' implementation_cost must have empty source_ids"
        note = ic.get("note", "")
        assert isinstance(note, str) and note.strip(), f"'{cid}' implementation_cost must have a note"


def test_t20_source_id_rule():
    """T20: source_id_rule holds: source_ids are non-empty only when a source_map locus resolves the fact; licence, non-REVEL pin, and standalone-acquisition confirm_pending facts have empty source_ids with a naming CP."""
    matrix = _load_matrix()
    candidates = matrix.get("candidates", {})

    for cid, r in candidates.items():
        # License status confirm_pending facts must have empty source_ids
        lic = r.get("license_status", {})
        if lic.get("status") == "confirm_pending":
            assert len(lic.get("source_ids", [])) == 0, f"'{cid}' license_status has non-empty source_ids"

        # Non-REVEL pin status must have empty source_ids
        if cid != "revel":
            pin = r.get("current_release_pin_status", {})
            if pin.get("status") == "confirm_pending":
                assert len(pin.get("source_ids", [])) == 0, f"'{cid}' current_release_pin_status has non-empty source_ids"

        # Standalone availability (mutpred2, evolutionary_action) must have empty source_ids
        if cid in ["mutpred2", "evolutionary_action"]:
            avail = r.get("structured_score_availability", {})
            if avail.get("status") == "confirm_pending":
                assert len(avail.get("source_ids", [])) == 0, f"'{cid}' structured_score_availability has non-empty source_ids"

