"""Generate a tiny LABEL-FREE GRCh38 sample VCF of real TSC variants from the frozen
held-out set, for the devbox BIAS/Nirvana smoke test. SNVs only (SPDI->VCF is
unambiguous: 0-based SPDI pos + 1 = 1-based VCF POS for a single-base ref/alt).
No label is emitted -- only chrom/pos/ref/alt (H1: the scorer stays label-blind)."""
import json
import sys
from pathlib import Path

HOLDOUT = Path(sys.argv[1])          # holdout.jsonl (frozen, out-of-repo)
OUT = Path(sys.argv[2])              # sample_tsc.vcf
N_PER_GENE = 4

# RefSeq GRCh38 accession -> VCF contig (chr name) for TSC genes
CONTIG = {"NC_000009.12": "chr9", "NC_000016.10": "chr16"}

picked = {c: [] for c in CONTIG}
# collect all candidate SNVs, then prefer a spread of classes (missense/truncating
# first so the smoke test exercises the PVS1/PP3 BIAS paths, not only 'other').
_cands = {c: [] for c in CONTIG}
for line in HOLDOUT.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    vid = row["variant_id"]
    try:
        acc, pos, ref, alt = vid.split(":")
    except ValueError:
        continue
    if acc not in CONTIG or len(ref) != 1 or len(alt) != 1 or ref == alt:
        continue  # SNV only, known contig
    _cands[acc].append((acc, int(pos), ref, alt, row.get("variant_class", "")))

_class_order = {"missense": 0, "truncating": 1, "other": 2}
for acc, cands in _cands.items():
    cands.sort(key=lambda c: (_class_order.get(c[4], 3), c[1]))
    picked[acc] = cands[:N_PER_GENE]

lines = [
    "##fileformat=VCFv4.2",
    "##source=RAPTOR-devbox-smoke-test (label-free TSC held-out SNVs, GRCh38)",
    '##contig=<ID=chr9,assembly=GRCh38>',
    '##contig=<ID=chr16,assembly=GRCh38>',
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
]
for acc, variants in picked.items():
    for (a, spdi_pos, ref, alt, vclass) in variants:
        vcf_pos = spdi_pos + 1  # SPDI 0-based -> VCF 1-based (single-base ref)
        lines.append(f"{CONTIG[a]}\t{vcf_pos}\t.\t{ref}\t{alt}\t.\t.\tCLASS={vclass}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {sum(len(v) for v in picked.values())} variants to {OUT}")
