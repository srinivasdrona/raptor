import sys
import json
import urllib.request

vcf_data = [
    ("NC_000009.12", 132912446, "A", "T", "SNV"),          # 5098
    ("NC_000016.10", 2087897, "C", "T", "SNV"),            # 12393
    ("NC_000009.12", 132905686, "GCTTT", "G", "SMALL_INDEL"),  # 5097
    ("NC_000016.10", 2071892, "C", "CTACT", "SMALL_INDEL"),    # 12395
    ("NC_000016.10", 2088292, "CCGGCTCCGCCACATCAAG", "C", "SMALL_INDEL"), # 12402
]

results = []
for chrom, pos, ref, alt, cls in vcf_data:
    url = f"https://api.ncbi.nlm.nih.gov/variation/v0/vcf/{chrom}/{pos}/{ref}/{alt}/contextuals"
    try:
        req = urllib.request.urlopen(url)
        data = json.loads(req.read())
        spdi = data['data']['spdis'][0]
        results.append({
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "spdi": f"{spdi['seq_id']}:{spdi['position']}:{spdi['deleted_sequence']}:{spdi['inserted_sequence']}",
            "hgvs_g": spdi.get('hgvs', '') # if present
        })
    except Exception as e:
        print(f"Error for {chrom}:{pos}:{ref}:{alt} -> {e}")

print(json.dumps(results, indent=2))
