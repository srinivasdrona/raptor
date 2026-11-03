# R611Q structure-readiness v1

This deterministic, hash-bound evidence pack records only wild-type experimental
structure context for $	ext{TSC2}$ residue 611. It is an evidence product for
human review, not a mechanism finding, pocket analysis, docking result, compound
screen, treatment recommendation, or RescueScreen-stage authorization.

## Rebuild

From the repository root, run:

```bash
python scripts/build_r611q_structure_readiness.py --pack-dir data/rescuescreen/r611q/structure-readiness-v1
python scripts/build_r611q_structure_readiness.py --pack-dir data/rescuescreen/r611q/structure-readiness-v1 --check
```

The builder uses Python standard library modules only. `--check` rebuilds into a
temporary sibling directory and compares every generated artifact byte-for-byte
without mutating this pack. `manifest.sha256` covers every pack file other than
itself. `source_catalog.json` includes raw input hashes and a self-excluding
canonical content hash.

## Scope boundary

The package preserves `EG-1` through `EG-5` as `NOT_SATISFIED`. In particular,
the supplied mapping evidence does not establish exact RefSeq-to-construct
equivalence, and residue inclusion does not measure a direct $	ext{Arg611}$-
$	ext{TSC1}$ contact, a pocket, or ligandability.
