# ADR-0008 x64 resource-manifest digest — `x64_freeze.resource_manifest_sha256`

> Companion to `docs/DECISIONS.md` ADR-0008, `docs/ops/devbox-bias-nirvana-handoff.md`,
> and `docs/ops/masked-heldout-bias-rerun-handoff.md`. This document defines EXACTLY
> what bytes `x64_freeze.resource_manifest_sha256` hashes, so the field
> `raptor.eval.prospective_freeze.assert_runtime_boundary` currently validates only
> for FORMAT (64-character lowercase hex) has one, single, reproducible meaning
> whenever a human approver pins a real value into a `pre_data_approval` record.
> It does not itself authorize any archive access, run BIAS/Nirvana, or approve
> anything — see the registration spec's `pre_data_approval` block and
> `docs/project/approvals/clinvar-2026-08-amendment-v2.pre_data_approval.draft.json`.

## Why this exists

`freeze_record_must_pin` (`docs/project/specs/clinvar-2026-08-prospective-amendment-v2.yaml`)
requires "x64 resource manifests and checksums" alongside the pinned BIAS commit and
Nirvana runtime banner. `assert_runtime_boundary` already enforces the closed
`_RUNTIME_IDENTITY_KEYS` shape and rejects a malformed `resource_manifest_sha256`
(not 64-hex-lowercase), but — unlike `bias_commit`/`nirvana_banner`, which are
pinned literal constants in this repository — no concrete expected value can be
pinned here, because the field's whole purpose is to attest to resource bundles
that live **only** on the ADR-0008 x64 worker and are never copied into this
repository (multi-GB Nirvana/BIAS annotation data). Without a precise definition
of what bytes the digest covers, "pin `resource_manifest_sha256`" is not
actually reproducible — two honest operators could compute two different,
unfalsifiable values from the same underlying resource state. This document (and
`raptor.eval.prospective_freeze.compute_resource_manifest_sha256`) closes that
gap.

## What is hashed: the three pinned checksum-manifest files

`resource_manifest_sha256` binds exactly three pre-existing, pinned checksum
manifest files, already named as `x64_handoff_requirements.items` in
`configs/eval/core_annotation_bundle.yaml` and required by
`docs/ops/masked-heldout-bias-rerun-handoff.md` §4/§9:

| Order | Logical id | Pinned filename | x64 worker location |
|---|---|---|---|
| 1 | `nirvana_full_manifest` | `nirvana-grch38-full.sha256.txt` | `D:\raptor-x64\CHECKSUMS\nirvana-grch38-full.sha256.txt` |
| 2 | `nirvana_updates_manifest` | `nirvana-grch38-updates.sha256.txt` | `D:\raptor-x64\CHECKSUMS\nirvana-grch38-updates.sha256.txt` |
| 3 | `bias_data_manifest` | `bias-hg38-data.sha256.txt` | `D:\raptor-x64\CHECKSUMS\bias-hg38-data.sha256.txt` |

These are the frozen per-file SHA-256 baselines for, respectively, the Nirvana
GRCh38 full data cache, the Nirvana GRCh38 supplementary/update data, and the
BIAS-2015 hg38 resource bundle (`current_x64_reannotation_readiness
.presence_proof_when_needed`: "recompute file-by-file SHA256 ... diff vs the
three frozen CHECKSUMS manifests"). This digest never reads the multi-GB data
those three files describe — only the three small manifest text files
themselves.

`RESOURCE_MANIFEST_ENTRIES` in `raptor.eval.prospective_freeze` is this exact
`(id, filename)` table, in this exact order, and is the single source of truth
both this document and the code must stay in sync with.

## The algorithm

1. For each of the three pinned `(id, filename)` entries, **in the pinned
   order above**, read `filename` from the supplied checksums directory as
   **raw bytes** (`Path.read_bytes()` — a binary read; no text-mode newline
   translation is ever applied, on either Windows or Linux, by this or any
   later step). Compute `sha256(raw_bytes).hexdigest()` for that file alone.
   Missing any one of the three pinned files is a hard, fail-closed
   `FileNotFoundError` — there is no partial/best-effort manifest, and a
   renamed file is indistinguishable from, and rejected exactly like, a
   missing one.
2. Build the canonical envelope:

   ```json
   {
     "schema": "raptor.eval.adr0008_resource_manifest_digest.v1",
     "manifests": [
       {"id": "nirvana_full_manifest", "filename": "nirvana-grch38-full.sha256.txt", "sha256": "<hex>"},
       {"id": "nirvana_updates_manifest", "filename": "nirvana-grch38-updates.sha256.txt", "sha256": "<hex>"},
       {"id": "bias_data_manifest", "filename": "bias-hg38-data.sha256.txt", "sha256": "<hex>"}
     ]
   }
   ```

   `schema` is a literal, versioned, domain-separation string: it is itself
   part of the hashed bytes, so a future deliberate change to this envelope's
   shape is made by defining a new `...v2` schema id (a different digest
   space entirely), never by silently reinterpreting an existing `v1` value.
   `manifests` is a JSON **array** in the pinned order — `json.dumps` never
   reorders array elements (only `sort_keys=True` sorts each *object's own*
   keys), so the pinned order survives into the hashed bytes unchanged.

3. Serialize the envelope with this repository's standard canonical-JSON
   convention (matching `raptor.eval.prospective_freeze._content_hash` /
   `raptor.packet.hashing._canonical_hash`): `json.dumps(envelope,
   sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, encoded UTF-8.
4. `resource_manifest_sha256` is `sha256(<that exact byte string>).hexdigest()`.

This is implemented, verbatim, by
`raptor.eval.prospective_freeze.compute_resource_manifest_sha256` (per-file
breakdown: `resource_manifest_entries`) — this document and that function must
never diverge; if they do, the function is authoritative and this document is
out of date.

### What this binds, and why it is Windows/Linux-reproducible

- **Identity** — each entry's fixed logical `id`.
- **Order** — the three entries' pinned position (see step 2's array-ordering
  note above): a hypothetical reorder is not independently possible without
  also changing which filename is looked up for which `id`, since the
  `(id, filename)` pairing is itself pinned in code.
- **Content** — each file's own raw-byte SHA-256.

A rename, a swap of which manifest's bytes sit behind which identity, or any
single changed byte in any one manifest all change the final digest.

Because every byte read is a **binary** read (`Path.read_bytes()`, no
`str`/text-mode decoding, no universal-newline translation), and every hash
step operates on those raw bytes directly, recomputing this digest from an
identical copy of the three files produces **the identical
`resource_manifest_sha256` on Windows and on Linux** — the contract never
depends on which OS performed the read. This is a byte-identity guarantee, not
a semantic-equivalence one: if the checksum-manifest generator itself emits
different literal bytes on two OSes for the "same" logical content (for
example CRLF vs LF line endings), those are two different `resource_manifest_sha256`
values by design — operators must treat the three manifest files, once
generated, as immutable inputs to be copied (not regenerated) across hosts
whenever a specific pinned digest value must be reproduced.

## Operator usage (read-only, x64 worker only)

`scripts/compute_adr0008_resource_manifest_sha256.py` wraps
`compute_resource_manifest_sha256`. It **only reads** the three pinned
manifest files under `--checksums-dir`; it never contacts ClinVar or any other
network endpoint, never runs BIAS-2015 or Nirvana, never touches the
multi-GB annotation-data bundles the manifests describe, and never writes,
mutates, or deletes anything.

Copy-paste on the real ADR-0008 x64 worker (PowerShell), once the three
manifest files exist under `D:\raptor-x64\CHECKSUMS` (the default):

```powershell
cd D:\raptor
python scripts\compute_adr0008_resource_manifest_sha256.py
```

To point at a non-default location:

```powershell
python scripts\compute_adr0008_resource_manifest_sha256.py --checksums-dir D:\raptor-x64\CHECKSUMS
```

The script refuses to run (exit code 2) on a non-`x86_64`/`AMD64` host unless
`--allow-non-x64-host` is passed — that flag exists only to let this
repository's own test suite exercise the script's logic on non-x64 dev/CI
hosts, and must never be used to produce a real pinned value.

The script prints a JSON report containing the per-manifest breakdown and the
final `resource_manifest_sha256`. That printed value is the only value a
human approver (`@dronasrinivas`) may paste into a specific `pre_data_approval`
record's `x64_freeze.resource_manifest_sha256` field — never a fabricated
value, never a value copied from a different registration or a different run,
and this document does not itself change any draft approval to `APPROVED_PRE_DATA`.

## Non-goals

- This digest does **not** verify the multi-GB Nirvana/BIAS data bundles
  themselves byte-for-byte (that is `current_x64_reannotation_readiness
  .presence_proof_when_needed`'s "recompute file-by-file SHA256 ... and diff"
  step in `configs/eval/core_annotation_bundle.yaml` — a separate, much more
  expensive, operation). It only pins the identity of the three *frozen
  baseline manifests* used as that recompute's comparison target.
- `assert_runtime_boundary` is **not** changed by this document: it still
  only checks that `resource_manifest_sha256` is syntactically a 64-character
  lowercase hex string. A concrete expected value cannot be pinned in code
  until it has actually been computed once on the real x64 worker; recording
  that real value into an approval record, and (separately) hard-pinning an
  expected value in code once one exists, are both future, human-gated steps
  — not implied or performed by this contract.
