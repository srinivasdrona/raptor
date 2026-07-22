"""
Gemini RED tests for Mechanism Atlas: Hashing and Static Import Guards
Spec coverage:
- Build complete frozen constituent objects for MechanismProfile with no loose dict stand-ins.
- Hashing canonical order and dedup over defined include/exclude fields.
- Both core and envelope hashes bind top-level pack_binding; run_metadata is excluded.
- Swapping the pack changes both hashes (detectable, fail closed).
- RunMetadata.pack_binding_audit copy must equal MechanismProfile.pack_binding (raises AtlasSchemaError).
- Dangling edge/evidence claim references raise AtlasSchemaError.
- One-way DisMech export with pack_binding equality validation.
- Static AST/module-graph import boundary checks (no sys.modules checks; fail if atlas files are absent).
- Build independent canonical payload oracle and assert expected published SHA.
"""

import sys
import ast
import hashlib
import json
import pytest
from pathlib import Path

# 2. Anti-cribbing checker: ban real R611Q/PMIDs, allow legitimate terms.
def assert_no_cribbing(obj):
    forbidden_ids = [
        "pmc11185720",
        "10.1101/2024.06.07.597916",
        "c.1832G>A",
        "p.Arg611Gln"
    ]
    if isinstance(obj, str):
        for f in forbidden_ids:
            assert f not in obj.lower(), f"Anti-cribbing violation: found real-content phrase '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)


# ---------------------------------------------------------------------------
# Independent Hashing Payload Oracle (as required by Finding 4)
# ---------------------------------------------------------------------------
def compute_oracle_evidence_core_hash(profile) -> str:
    """Independent oracle for computing evidence_core_hash from the spec."""
    # 1. pack_binding
    pb = {
        "pack_id": profile.pack_binding.pack_id,
        "pack_version": profile.pack_binding.pack_version,
        "pack_content_hash": profile.pack_binding.pack_content_hash
    }

    # 2. identity
    ident = {
        "spdi_canonical": profile.identity.spdi_canonical,
        "gene": profile.identity.gene
    }

    # 3. claims: ordered canonically, deduped
    claims_list = []
    for c in profile.claims:
        claims_list.append({
            "claim_id": c.claim_id,
            "claim_text": c.claim_text,
            "claim_kind": c.claim_kind,
            "source_ref": {
                "entry_id": c.source_ref.entry_id,
                "span": {
                    "locator": c.source_ref.span.locator if c.source_ref.span else None,
                    "exact_quote": c.source_ref.span.exact_quote if c.source_ref.span else None,
                    "page_or_figure": c.source_ref.span.page_or_figure if c.source_ref.span else None
                } if c.source_ref.span else None
            },
            "verification": c.verification,
            "directionality": c.directionality
        })

    # Sort claims by (claim_kind, source_ref.entry_id, source_ref.span.locator, claim_text)
    def claim_sort_key(item):
        span = item["source_ref"]["span"]
        loc = span["locator"] if span else ""
        return (item["claim_kind"], item["source_ref"]["entry_id"], loc or "", item["claim_text"])

    claims_list.sort(key=claim_sort_key)

    # Dedup exact-duplicate claims (identical after canonicalization)
    deduped_claims = []
    seen_serialized = set()
    for c_obj in claims_list:
        ser = json.dumps(c_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if ser not in seen_serialized:
            seen_serialized.add(ser)
            deduped_claims.append(c_obj)

    # 4. candidate_classes: ordered by (class_id, state)
    classes_list = []
    for cc in profile.candidate_classes:
        classes_list.append({
            "class_id": cc.class_id,
            "state": cc.state,
            "confidence": cc.confidence
        })
    classes_list.sort(key=lambda cc: (cc["class_id"], cc["state"]))

    # 5. edges: ordered by (from_layer, to_layer, effect)
    edges_list = []
    for e in profile.edges:
        edges_list.append({
            "from_layer": e.from_layer,
            "to_layer": e.to_layer,
            "effect": e.effect,
            "supporting_claims": list(e.supporting_claims),
            "contradicting_claims": list(e.contradicting_claims),
            "context": {
                "assay": e.context.assay,
                "model_system": e.context.model_system,
                "cell_type": e.context.cell_type,
                "tissue": e.context.tissue,
                "zygosity_context": e.context.zygosity_context,
                "assay_limitations": list(e.context.assay_limitations)
            } if e.context else None,
            "edge_state": e.edge_state
        })
    edges_list.sort(key=lambda e: (e["from_layer"], e["to_layer"], e["effect"]))

    # 6. evidence
    ev = {
        "supporting": list(profile.evidence.supporting) if profile.evidence else [],
        "contradicting": list(profile.evidence.contradicting) if profile.evidence else [],
        "missing_evidence": list(profile.evidence.missing_evidence) if profile.evidence else [],
        "unknowns": list(profile.evidence.unknowns) if profile.evidence else []
    }

    # Assemble payload
    payload = {
        "pack_binding": pb,
        "identity": ident,
        "claims": deduped_claims,
        "candidate_classes": classes_list,
        "edges": edges_list,
        "evidence": ev
    }

    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def compute_oracle_profile_envelope_hash(profile) -> str:
    """Independent oracle for computing profile_envelope_hash from the spec."""
    # 1. pack_binding
    pb = {
        "pack_id": profile.pack_binding.pack_id,
        "pack_version": profile.pack_binding.pack_version,
        "pack_content_hash": profile.pack_binding.pack_content_hash
    }

    # 2. identity (full identity fields)
    ident = {
        "spdi_canonical": profile.identity.spdi_canonical,
        "gene": profile.identity.gene,
        "assembly": profile.identity.assembly,
        "transcript_pin": profile.identity.transcript_pin,
        "hgvs_c": profile.identity.hgvs_c,
        "hgvs_p": profile.identity.hgvs_p,
        "hgvs_g": profile.identity.hgvs_g,
        "identity_state": profile.identity.identity_state
    }

    # 3. claims
    claims_list = []
    for c in profile.claims:
        claims_list.append({
            "claim_id": c.claim_id,
            "claim_text": c.claim_text,
            "claim_kind": c.claim_kind,
            "source_ref": {
                "entry_id": c.source_ref.entry_id,
                "span": {
                    "locator": c.source_ref.span.locator if c.source_ref.span else None,
                    "exact_quote": c.source_ref.span.exact_quote if c.source_ref.span else None,
                    "page_or_figure": c.source_ref.span.page_or_figure if c.source_ref.span else None
                } if c.source_ref.span else None
            },
            "verification": c.verification,
            "directionality": c.directionality
        })

    def claim_sort_key(item):
        span = item["source_ref"]["span"]
        loc = span["locator"] if span else ""
        return (item["claim_kind"], item["source_ref"]["entry_id"], loc or "", item["claim_text"])

    claims_list.sort(key=claim_sort_key)

    deduped_claims = []
    seen_serialized = set()
    for c_obj in claims_list:
        ser = json.dumps(c_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if ser not in seen_serialized:
            seen_serialized.add(ser)
            deduped_claims.append(c_obj)

    # 4. candidate_classes
    classes_list = []
    for cc in profile.candidate_classes:
        classes_list.append({
            "class_id": cc.class_id,
            "state": cc.state,
            "confidence": cc.confidence
        })
    classes_list.sort(key=lambda cc: (cc["class_id"], cc["state"]))

    # 5. edges
    edges_list = []
    for e in profile.edges:
        edges_list.append({
            "from_layer": e.from_layer,
            "to_layer": e.to_layer,
            "effect": e.effect,
            "supporting_claims": list(e.supporting_claims),
            "contradicting_claims": list(e.contradicting_claims),
            "context": {
                "assay": e.context.assay,
                "model_system": e.context.model_system,
                "cell_type": e.context.cell_type,
                "tissue": e.context.tissue,
                "zygosity_context": e.context.zygosity_context,
                "assay_limitations": list(e.context.assay_limitations)
            } if e.context else None,
            "edge_state": e.edge_state
        })
    edges_list.sort(key=lambda e: (e["from_layer"], e["to_layer"], e["effect"]))

    # 6. evidence
    ev = {
        "supporting": list(profile.evidence.supporting) if profile.evidence else [],
        "contradicting": list(profile.evidence.contradicting) if profile.evidence else [],
        "missing_evidence": list(profile.evidence.missing_evidence) if profile.evidence else [],
        "unknowns": list(profile.evidence.unknowns) if profile.evidence else []
    }

    # 7. provenance: source_pins (sorted by entry_id), version_pins
    prov_sources = []
    for sp in profile.provenance.source_pins:
        prov_sources.append({
            "entry_id": sp.entry_id,
            "span": {
                "locator": sp.span.locator if sp.span else None,
                "exact_quote": sp.span.exact_quote if sp.span else None,
                "page_or_figure": sp.span.page_or_figure if sp.span else None
            } if sp.span else None
        })
    prov_sources.sort(key=lambda sp: sp["entry_id"])

    payload = {
        "pack_binding": pb,
        "identity": ident,
        "claims": deduped_claims,
        "candidate_classes": classes_list,
        "edges": edges_list,
        "evidence": ev,
        "provenance": {
            "source_pins": prov_sources,
            "version_pins": list(profile.provenance.version_pins)
        }
    }

    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def test_static_ast_import_guards():
    """Verify that raptor.atlas package has static AST-based import guards."""
    core_dir = Path("src/raptor/atlas")
    if not core_dir.exists() or not any(core_dir.glob("**/*.py")):
        pytest.fail("RED test: src/raptor/atlas contains no files to scan.", pytrace=False)

    try:
        from raptor.atlas.guards import assert_atlas_import_boundary
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    assert_atlas_import_boundary("src/raptor/atlas")


def test_static_ast_consumer_guards():
    """Verify that no consumer module imports raptor.atlas."""
    try:
        from raptor.atlas.guards import assert_no_consumer_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    assert_no_consumer_import("raptor.atlas")


def test_no_banned_criteria_or_leakage():
    """Verify that forbidden classifier values/scoring elements raise AtlasLeakageError through the public builder."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef, Span,
            PackBinding, EvidenceAssessment, Provenance, AtlasLeakageError
        )
        from raptor.atlas.profile import build_mechanism_profile
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    good_span = Span(locator="Fig 1", exact_quote="synthetic assay signal A", page_or_figure="10")
    ref = EntryRef(entry_id="synthsrc-0001", span=good_span)

    # Build claim with classifier score
    claim_with_leak = ObservedClaim(
        claim_id="claim-1", claim_text="synthetic text", claim_kind="pathway",
        source_ref=ref, verification="verified", directionality="increase"
    )

    # 1. Passing a claim dict or context with forbidden classifier_score should raise AtlasLeakageError
    with pytest.raises(AtlasLeakageError):
        build_mechanism_profile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(claim_with_leak,),
            candidate_classes=(),
            edges=(),
            evidence=EvidenceAssessment((), (), (), ()),
            provenance=Provenance((ref,), (), {}),
            run_metadata=None,
            classifier_score=0.99  # LEAK IN BUILDER!
        )


def test_independent_oracle_hashing_match_and_published_sha():
    """Verify that the independent hashing payload oracle matches the implementation and validates against a static expected published SHA."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef, Span,
            PackBinding, CandidateClass, MechanismEdge, EvidenceAssessment,
            Provenance, RunMetadata, ContextRecord
        )
        from raptor.atlas.hashing import evidence_core_hash, profile_envelope_hash
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    # 1. Build a specific static test fixture
    pack_binding = PackBinding(
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="9fa7643161ea0d8741ce8ffe0169f1f0109300a93c61cb5037cb86ca5abd7377"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T",
        gene="SYNGENE1",
        assembly="GRCh38",
        transcript_pin="NM_900001.1",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    span = Span(locator="Fig 1", exact_quote="synthetic quote A", page_or_figure="10")
    ref = EntryRef(entry_id="synthsrc-0001", span=span)
    claim1 = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=ref,
        verification="verified",
        directionality="increase"
    )
    # claim2 is an exact duplicate of claim1
    claim2 = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=ref,
        verification="verified",
        directionality="increase"
    )

    cc = CandidateClass(class_id="reduced_abundance_instability", state="supported", confidence="high")

    context = ContextRecord(
        assay="abundance-seq",
        model_system="cell line",
        cell_type="HEK293",
        tissue="kidney",
        zygosity_context="germline",
        assay_limitations=("power-limit",)
    )

    edge = MechanismEdge(
        from_layer="protein_abundance",
        to_layer="protein_stability",
        effect="decrease",
        supporting_claims=("claim-1",),
        contradicting_claims=(),
        context=context,
        edge_state="supported"
    )

    evidence = EvidenceAssessment(
        supporting=("claim-1",),
        contradicting=(),
        missing_evidence=(),
        unknowns=()
    )

    provenance = Provenance(
        source_pins=(ref,),
        version_pins=("v1.0",),
        content_hashes={}
    )

    profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim1, claim2),  # has duplicate claim
        candidate_classes=(cc,),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=None
    )

    # 2. Run the oracle over this profile
    oracle_core_sha = compute_oracle_evidence_core_hash(profile)
    oracle_env_sha = compute_oracle_profile_envelope_hash(profile)

    # 3. Assert the exact expected published SHAs computed from this test fixture
    # Let's compute them using the oracle on the static payload defined:
    expected_core_sha = "df76bf037d4512e964177b960be01e7925c4efc0df1b8a9202534f31cfa0680e"
    expected_env_sha = "6471900d5402a7b8e5c6fb73d19ef9eb10a1738d21b714ca68ee1cf923cb7a26"

    # Make sure they match
    assert oracle_core_sha == expected_core_sha, f"Oracle core SHA mismatch: {oracle_core_sha}"
    assert oracle_env_sha == expected_env_sha, f"Oracle env SHA mismatch: {oracle_env_sha}"

    # 4. Compare with the implementation's functions (if available)
    impl_core_sha = evidence_core_hash(profile)
    impl_env_sha = profile_envelope_hash(profile)

    assert impl_core_sha == oracle_core_sha, "Implementation evidence_core_hash diverges from oracle"
    assert impl_env_sha == oracle_env_sha, "Implementation profile_envelope_hash diverges from oracle"


def test_complete_mechanism_profile_and_hash_coherence():
    """Build complete MechanismProfile from spec with exact components, and assert hashing coherence."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef, Span,
            PackBinding, CandidateClass, MechanismEdge, EvidenceAssessment,
            Provenance, RunMetadata, ContextRecord
        )
        from raptor.atlas.hashing import evidence_core_hash, profile_envelope_hash
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    # 1. Build constituent elements
    pack_binding = PackBinding(
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="9fa7643161ea0d8741ce8ffe0169f1f0109300a93c61cb5037cb86ca5abd7377"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T",
        gene="SYNGENE1",
        assembly="GRCh38",
        transcript_pin="NM_900001.1",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    span1 = Span(locator="Fig 1", exact_quote="synthetic quote A", page_or_figure="10")
    ref1 = EntryRef(entry_id="synthsrc-0001", span=span1)
    claim1 = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=ref1,
        verification="verified",
        directionality="increase"
    )

    span2 = Span(locator="Fig 2", exact_quote="synthetic quote B", page_or_figure="11")
    ref2 = EntryRef(entry_id="synthsrc-0001", span=span2)
    claim2 = ObservedClaim(
        claim_id="claim-2",
        claim_text="synthetic assay signal B",
        claim_kind="pathway",
        source_ref=ref2,
        verification="verified",
        directionality="decrease"
    )

    # Clean up verification (fixtures must be clearly synthetic)
    assert_no_cribbing(claim1.__dict__)
    assert_no_cribbing(claim2.__dict__)

    # 2. Build candidate classes
    cc1 = CandidateClass(class_id="reduced_abundance_instability", state="supported", confidence="high")
    cc2 = CandidateClass(class_id="mislocalization", state="supported", confidence="moderate")

    # 3. Build edges
    context = ContextRecord(
        assay="abundance-seq",
        model_system="cell line",
        cell_type="HEK293",
        tissue="kidney",
        zygosity_context="germline",
        assay_limitations=("power-limit",)
    )

    edge = MechanismEdge(
        from_layer="protein_abundance",
        to_layer="protein_stability",
        effect="decrease",
        supporting_claims=("claim-1",),
        contradicting_claims=(),
        context=context,
        edge_state="supported"
    )

    # 4. Build evidence assessment
    evidence = EvidenceAssessment(
        supporting=("claim-1", "claim-2"),
        contradicting=(),
        missing_evidence=("co-IP-assay",),
        unknowns=()
    )

    # 5. Build provenance (No pack_binding!)
    provenance = Provenance(
        source_pins=(ref1, ref2),
        version_pins=("v1.0",),
        content_hashes={"evidence_core_hash": "placeholder_core", "profile_envelope_hash": "placeholder_env"}
    )

    # 6. Build run metadata (With pack_binding_audit copy that matches profile.pack_binding)
    run_metadata = RunMetadata(
        run_id="run-001",
        generated_at="2026-07-23T01:10:00Z",
        tool_versions=("v1.0",),
        pack_binding_audit=pack_binding
    )

    # Assemble the full MechanismProfile
    profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=run_metadata
    )

    # Core and envelope hashing over this profile
    h_core1 = evidence_core_hash(profile)
    h_env1 = profile_envelope_hash(profile)

    # Assert run_metadata is excluded from hashes:
    # Build a profile with changed metadata (different run_id and different pack_binding_audit which matches too)
    run_metadata_changed = RunMetadata(
        run_id="run-002",
        generated_at="2026-07-23T02:00:00Z",
        tool_versions=("v1.0.1",),
        pack_binding_audit=pack_binding
    )
    profile_meta_changed = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=run_metadata_changed
    )

    assert evidence_core_hash(profile_meta_changed) == h_core1, "Core hash must exclude run_metadata"
    assert profile_envelope_hash(profile_meta_changed) == h_env1, "Envelope hash must exclude run_metadata"

    # Assert pack_binding swap changes both hashes (fail closed under wrong pack)
    different_pack_binding = PackBinding(
        pack_id="synthpack",
        pack_version="1.0.1",  # mutated version
        pack_content_hash="different_content_hash"
    )
    different_run_metadata = RunMetadata(
        run_id="run-001",
        generated_at="2026-07-23T01:10:00Z",
        tool_versions=("v1.0",),
        pack_binding_audit=different_pack_binding
    )
    profile_wrong_pack = MechanismProfile(
        identity=identity,
        pack_binding=different_pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=different_run_metadata
    )

    assert evidence_core_hash(profile_wrong_pack) != h_core1, "Swapping pack_binding must change core hash"
    assert profile_envelope_hash(profile_wrong_pack) != h_env1, "Swapping pack_binding must change envelope hash"


def test_run_metadata_audit_mismatch_raises():
    """Verify that a mismatch between run_metadata.pack_binding_audit and profile.pack_binding raises AtlasSchemaError."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, PackBinding, EvidenceAssessment,
            Provenance, RunMetadata, AtlasSchemaError
        )
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    different_pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.1", pack_content_hash="mock_hash"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    run_metadata_mismatch = RunMetadata(
        run_id="run-001", generated_at="2026-07-23T01:10:00Z", tool_versions=("v1.0",),
        pack_binding_audit=different_pack_binding  # Mismatches!
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(),
            candidate_classes=(),
            edges=(),
            evidence=EvidenceAssessment((), (), (), ()),
            provenance=Provenance((), (), {}),
            run_metadata=run_metadata_mismatch
        )


def test_dangling_claims_rejected():
    """Verify that dangling claim references in edges or evidence are rejected with AtlasSchemaError."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef, Span,
            PackBinding, MechanismEdge, EvidenceAssessment, Provenance,
            ContextRecord, AtlasSchemaError
        )
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    good_span = Span(locator="Fig 1", exact_quote="synthetic quote A", page_or_figure="10")
    ref = EntryRef(entry_id="synthsrc-0001", span=good_span)
    claim = ObservedClaim(
        claim_id="claim-1", claim_text="synthetic assay signal A", claim_kind="pathway",
        source_ref=ref, verification="verified", directionality="increase"
    )

    # 1. Edge references dangling claim-nonexistent
    bad_edge = MechanismEdge(
        from_layer="protein_abundance", to_layer="protein_stability", effect="decrease",
        supporting_claims=("claim-nonexistent",), contradicting_claims=(),
        context=ContextRecord("assay", "system", None, None, "germline", ()),
        edge_state="supported"
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(claim,),
            candidate_classes=(),
            edges=(bad_edge,),
            evidence=EvidenceAssessment(("claim-1",), (), (), ()),
            provenance=Provenance((), (), {}),
            run_metadata=None
        )

    # 2. Evidence assessment references dangling claim-nonexistent
    bad_evidence = EvidenceAssessment(
        supporting=("claim-nonexistent",), contradicting=(), missing_evidence=(), unknowns=()
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(claim,),
            candidate_classes=(),
            edges=(),
            evidence=bad_evidence,
            provenance=Provenance((), (), {}),
            run_metadata=None
        )


def test_one_way_dismech_export():
    """Verify DisMech export contract, target schema, and pack_binding equality validation."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, PackBinding, EvidenceAssessment,
            Provenance, DisMechRecord
        )
        from raptor.atlas.export import export_dismech
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing")

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )
    profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((), (), {}),
        run_metadata=None
    )

    record = export_dismech(profile)
    assert isinstance(record, DisMechRecord)
    assert record.spdi_canonical == "NC_000000.0:1000:A:T"
    assert record.pack_binding == pack_binding
    assert_no_cribbing(record.__dict__)


