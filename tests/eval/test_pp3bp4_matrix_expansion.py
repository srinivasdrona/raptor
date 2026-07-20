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
    """T3: Every record uses the closed identity/routing + fact_object field set; unknown fields fail."""
    matrix = _load_matrix()

    # Closed top-level schema check
    allowed_top_level = {
        "schema", "version", "source_map", "confirm_pending_register",
        "candidates", "audit_rows", "smallest_pin_handoff"
    }
    top_keys = set(matrix.keys())
    extra_top = top_keys - allowed_top_level
    assert not extra_top, f"Unexpected top-level fields found in matrix: {extra_top}"

    # Closed record fields check
    allowed_record_fields = {
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
        record_keys = set(r.keys())
        extra_keys = record_keys - allowed_record_fields
        assert not extra_keys, f"Record '{cid}' has unexpected fields: {extra_keys}"


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
    """T6: Markdown candidate IDs and material dispositions match the canonical machine matrix."""
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

    parsed_md = {}
    for line in table_lines:
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if not parts:
            continue
        if parts[0].lower() in ['candidate', '---']:
            continue

        candidate_name = parts[0]
        decision = parts[-1].replace('**', '').strip().lower()

        # Normalize name to candidate ID
        cid = candidate_name.lower().replace(' ', '_').replace('-', '_').replace('++', '_plus_plus').replace('+', '_plus')
        if cid == 'bias_composite':
            pass
        elif cid == 'gerp':
            cid = 'gerp_plus_plus'

        parsed_md[cid] = decision

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

    # Assert exact match
    for cid, record in yaml_records.items():
        assert cid in parsed_md, f"Candidate '{cid}' from YAML not found in Markdown table."
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


def test_t13_markdown_backing_relabeling():
    """T13: Markdown Backing config names pp3bp4_predictor_matrix.yaml (not the source register); the memo relation table labels the matrix and the REVEL provenance register distinctly."""
    matrix_md_file = REPO_ROOT / "docs/reference/pp3bp4-candidate-matrix-2026-07.md"
    assert matrix_md_file.exists(), "Candidate matrix markdown file not found."
    matrix_md = matrix_md_file.read_text(encoding="utf-8")

    # Backing config must name configs/eval/pp3bp4_predictor_matrix.yaml
    assert "configs/eval/pp3bp4_predictor_matrix.yaml" in matrix_md, "Candidate matrix markdown does not reference pp3bp4_predictor_matrix.yaml"

    recommendation_md_file = REPO_ROOT / "docs/reference/pp3-bp4-predictor-policy-recommendation-2026-07.md"
    assert recommendation_md_file.exists(), "Recommendation memo markdown file not found."
    rec_md = recommendation_md_file.read_text(encoding="utf-8")

    # Both configs must be named in the relation table
    assert "configs/eval/pp3bp4_predictor_matrix.yaml" in rec_md, "Recommendation memo does not reference pp3bp4_predictor_matrix.yaml"
    assert "configs/eval/pp3bp4_source_register.yaml" in rec_md, "Recommendation memo does not reference pp3bp4_source_register.yaml"

    lines_with_matrix = [line for line in rec_md.splitlines() if "pp3bp4_predictor_matrix.yaml" in line]
    lines_with_source = [line for line in rec_md.splitlines() if "pp3bp4_source_register.yaml" in line]

    assert lines_with_matrix, "Could not find relation lines for pp3bp4_predictor_matrix.yaml"
    assert lines_with_source, "Could not find relation lines for pp3bp4_source_register.yaml"

    # Distinct labeling rows check
    for lm in lines_with_matrix:
        for ls in lines_with_source:
            assert lm != ls, f"The matrix and source register are defined on the same line in relation table: {lm}"
