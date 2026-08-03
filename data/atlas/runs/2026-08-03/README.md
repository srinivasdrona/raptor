# Atlas deterministic-gate run manifests

These manifests publish the reproducibility boundary for the first real
$TSC2$ Mechanism Atlas runs without redistributing third-party article bodies
or presenting unreviewed candidate claims as accepted evidence.

Published here:

- official source identifiers, URLs, licences and content hashes;
- exact-span locators and extracted-text hashes;
- canonical variant identities;
- deterministic gate outcomes;
- explicit human-review blockers and zero-acceptance counts.

Not published here:

- raw JATS/XML article bodies or extracted full text;
- exact quote-bearing `AtlasCandidateImport` payloads;
- patient-level information;
- accepted mechanism profiles or classifications.

To reproduce a span, retrieve the cited official source, run the documented
deterministic whole-JATS extraction method, confirm the published extracted
text SHA-256, then verify the published `text-char:<start>:<end>` slice.
RAPTOR's offline resolver performs the final from-disk hash and exact-slice
checks.

The six-variant smoke cohort is an engineering-repeatability check, not the
formal contrast panel or scientific validation. Every run remains blocked at
named human Gate 8.
