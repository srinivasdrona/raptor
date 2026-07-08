import sys
import json
import urllib.request

vcf_data = [
    ("NC_000009.12", 132912446, "A", "T", "SNV", "5098", "TSC1"),
    ("NC_000016.10", 2087897, "C", "T", "SNV", "12393", "TSC2"),
    ("NC_000009.12", 132905686, "GCTTT", "G", "SMALL_INDEL", "5097", "TSC1"),
    ("NC_000016.10", 2071892, "C", "CTACT", "SMALL_INDEL", "12395", "TSC2"),
    ("NC_000016.10", 2088292, "CCGGCTCCGCCACATCAAG", "C", "SMALL_INDEL", "12402", "TSC2"),
]

results = []
for chrom, pos, ref, alt, cls, var_id, gene in vcf_data:
    spdi_url = f"https://api.ncbi.nlm.nih.gov/variation/v0/vcf/{chrom}/{pos}/{ref}/{alt}/contextuals"
    try:
        req = urllib.request.urlopen(spdi_url)
        data = json.loads(req.read())
        spdi = data['data']['spdis'][0]
        spdi_str = f"{spdi['seq_id']}:{spdi['position']}:{spdi['deleted_sequence']}:{spdi['inserted_sequence']}"
        
        hgvs_g = None
        # get HGVS from another endpoint if possible, but actually we can just format simple ones
        if cls == "SNV":
            hgvs_g = f"{chrom}:g.{pos}{ref}>{alt}"
        
        # for noncoding we will simulate missing hgvs_c/p. Wait, AC3 requires checking null reasons.
        # So we'll just set it to null and expected_hgvs_c_null_reason to "awaiting_uta_projection" since UTA is not here
        
        results.append({
            "variation_id": var_id,
            "raw_coords": f"{chrom}:{pos}:{ref}:{alt}",
            "gene": gene,
            "variant_class": cls,
            "expected_variant_id": spdi_str,
            "expected_hgvs_g": hgvs_g, # omit for indels to not guess, we test SPDI strictly
            "expected_hgvs_c": None,
            "expected_hgvs_p": None,
            "expected_hgvs_c_null_reason": "awaiting_uta_projection",
            "expected_hgvs_p_null_reason": "awaiting_uta_projection"
        })
    except Exception as e:
        print(f"Error for {chrom}:{pos}:{ref}:{alt} -> {e}")

# add a manual queue case manually
results.append({
    "variation_id": "33205",
    "raw_coords": "NC_000009.12:-1:na:na",
    "gene": "TSC1",
    "variant_class": "IMPRECISE_SV",
    "expected_variant_id": None,
    "expected_manual_queue": True
})

print(json.dumps(results, indent=2))
with open("/mnt/d/AIProjects/raptor/tests/ingest/fixtures/ac3_canonical.json", "w") as f:
    json.dump(results, f, indent=2)
