# ClinVar August 2026 v3 x64 execution handoff

> **Audience:** Copilot CLI running on the ADR-0008 designated x64 worker.
>
> **Mode:** Execute the remaining prospective validation. Do not create another
> plan, contract, ADR, registration, or owner-approval round.

## Owner authorization

`@dronasrinivas` explicitly authorized the prospective benchmark and scoring
run on 2026-09-01:

> I am approving the run

Record the scoring-stage approval time as `2026-09-01T15:25:29.806Z`. This
authorization is conditional on the existing registered dataset, immutable
inputs, masking policy, and x64 runtime identities passing their mechanical
checks exactly. It does not authorize changing any registered semantics.

Do not ask the owner to approve this run again.

## Frozen acquisition

The exact August archive has already been acquired and frozen.

| Item | Value |
|---|---|
| Registration | `clinvar-2026-08-amendment-v3` |
| Evidence commit | `34c3c0a2b6ed9b1756d5abd65b4e53450e2c3d34` |
| Archive | `variant_summary_2026-08.txt.gz` |
| Byte length | `441792560` |
| SHA-256 | `230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500` |
| MD5 | `2d6b8fcec81f20c9db443818d3fa4500` |
| Run scope | `f2d3291b67404153aae1c129a2b973db` |
| Snapshot ID | `clinvar_2026-08-monthly-amendment-v3` |

Authoritative repository inputs:

- `docs/project/specs/clinvar-2026-08-prospective-amendment-v3.yaml`
- `configs/eval/tsc2_clinvar_2026_08_amendment_v3.overlay.yaml`
- `data/census/tsc_prospective_validation_2026-08_amendment_v3_transport_freeze.json`
- `data/census/tsc_prospective_validation_2026-08_amendment_v3_raw_freeze.json`

The original archive is on the acquisition host at:

`D:\raptor-external\prospective-freeze\clinvar-2026-08-amendment-v3\f2d3291b67404153aae1c129a2b973db\variant_summary_2026-08.txt.gz`

Transfer those exact bytes to the x64 worker. If direct transfer is unavailable,
the x64 worker may download only the exact registered URL, but it must reject the
result unless byte length, SHA-256, and MD5 match the frozen values above. Never
accept an alternate path, mirror, later release, substitute, or redirect to a
different path.

## Recover the existing x64 worker

The July runs already proved that this worker can execute Nirvana, BIAS and the
RAPTOR parser. Reuse that installation. Do not reinstall the 58.7-GB annotation
bundle merely because the new v3 handoff paths or marker files are absent.

Three absences reported by the first v3 attempt are expected setup differences,
not reasons to abandon the run:

1. `/home/sdrona/raptor/bin/python` is the ARM development-host interpreter. It
   is not required on this Windows x64 worker.
2. The acquisition host's
   `D:\raptor-external\prospective-freeze\...` directory is host-local. The x64
   worker must copy or independently retrieve the exact frozen bytes into its
   own run root.
3. The three narrow marker files are a new machine-readable projection of the
   already-provisioned worker identity. Materialize them only after verifying
   the existing BIAS checkout, Nirvana installation and checksum manifests.

Do not run `scripts\run_clinvar_2026_08_prospective_freeze.py --execute` on this
worker. Stages 1-2 already completed on the acquisition host, and that operator
correctly enforces the acquisition host's WSL policy. This worker starts at
stage 3.

### 1. Locate and update the existing checkout

The prior x64 handoff used `D:\raptor\repo`; some later sessions used
`D:\raptor`. Resolve the real checkout rather than assuming either:

```powershell
$ErrorActionPreference = "Stop"

if (Test-Path -LiteralPath "D:\raptor\repo\.git") {
    $repo = "D:\raptor\repo"
} elseif (Test-Path -LiteralPath "D:\raptor\.git") {
    $repo = "D:\raptor"
} else {
    throw "Existing RAPTOR checkout not found at D:\raptor\repo or D:\raptor"
}

git -C $repo status --short
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect RAPTOR checkout" }

git -C $repo fetch origin
if ($LASTEXITCODE -ne 0) { throw "Could not fetch origin" }

git -C $repo switch fix/clinvar-archive-checksum-policy
if ($LASTEXITCODE -ne 0) {
    git -C $repo switch --track origin/fix/clinvar-archive-checksum-policy
}
if ($LASTEXITCODE -ne 0) { throw "Could not switch to the ClinVar v3 branch" }

git -C $repo pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "ClinVar v3 branch is not fast-forwardable" }

git -C $repo merge-base --is-ancestor `
  34c3c0a2b6ed9b1756d5abd65b4e53450e2c3d34 HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout does not contain the frozen acquisition evidence" }
```

Do not reset, clean or overwrite a dirty checkout. Use a new Git worktree if
unrelated local changes prevent the branch switch.

### 2. Use a native Windows x64 Python environment

The earlier formal x64 gate used a native Python 3.12 virtual environment under
`D:\raptor-x64\masked-heldout-2026-07-12`. Reuse its interpreter as a bootstrap
when present; otherwise use the installed x64 `py -3.12` launcher. Create a new
run-local venv so the historical environment remains untouched:

```powershell
$runRoot = "D:\raptor-x64\prospective-freeze\clinvar-2026-08-amendment-v3"
$venv = Join-Path $runRoot "validation-venv"
$priorPython = "D:\raptor-x64\masked-heldout-2026-07-12\gate-venv-2026-07-21\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    if (Test-Path -LiteralPath $priorPython) {
        & $priorPython -m venv $venv
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        py -3.12 -m venv $venv
    } else {
        throw "No existing native x64 Python 3.12 interpreter was found"
    }
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --quiet -e "$repo[dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install RAPTOR into the run-local venv" }

& $python -c "import platform,sys; print(sys.executable); print(platform.machine()); assert platform.machine().lower() in {'amd64','x86_64'}"
if ($LASTEXITCODE -ne 0) { throw "Python interpreter is not native x64" }
```

Native Windows reports `platform.machine()` as `AMD64`; RAPTOR canonicalizes
that known x64 spelling to the approval record's `x86_64`. Do not create WSL or
look for `/home/sdrona/raptor/bin/python` on this worker.

### 3. Materialize the frozen archive on x64

Prefer copying the already-frozen archive through the same RDP drive bridge used
by the earlier successful x64 handoffs:

`\\tsclient\D\raptor-external\prospective-freeze\clinvar-2026-08-amendment-v3\f2d3291b67404153aae1c129a2b973db\variant_summary_2026-08.txt.gz`

If an archive already exists at the x64 destination but its identity does not
match, preserve it under a timestamped `.mismatch-*` name with its observed
identity and then replace it from the known-good shared copy. If the drive
bridge is unavailable, retrieve the exact URL without following redirects.
Promote a temporary file only after all frozen identity checks pass:

```powershell
$url = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08.txt.gz"
$runRoot = "D:\raptor-x64\prospective-freeze\clinvar-2026-08-amendment-v3"
$runScope = "f2d3291b67404153aae1c129a2b973db"
$archiveDir = Join-Path $runRoot $runScope
$archive = Join-Path $archiveDir "variant_summary_2026-08.txt.gz"
$sharedArchive = "\\tsclient\D\raptor-external\prospective-freeze\clinvar-2026-08-amendment-v3\f2d3291b67404153aae1c129a2b973db\variant_summary_2026-08.txt.gz"

New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null

function Get-ArchiveIdentity([string]$Path) {
    [ordered]@{
        path = $Path
        byte_length = (Get-Item -LiteralPath $Path).Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        md5 = (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
}

function Test-FrozenArchiveIdentity([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $identity = Get-ArchiveIdentity $Path
    return (
        $identity.byte_length -eq 441792560 -and
        $identity.sha256 -eq "230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500" -and
        $identity.md5 -eq "2d6b8fcec81f20c9db443818d3fa4500"
    )
}

if ((Test-Path -LiteralPath $archive -PathType Leaf) -and
    -not (Test-FrozenArchiveIdentity $archive)) {
    $identity = Get-ArchiveIdentity $archive
    $stamp = Get-Date -Format "yyyyMMddTHHmmss"
    $mismatch = "$archive.mismatch-$stamp"
    Move-Item -LiteralPath $archive -Destination $mismatch
    $identity["path"] = $mismatch
    $identity | ConvertTo-Json |
      Set-Content -LiteralPath "$mismatch.identity.json" -Encoding utf8
}

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    $partial = "$archive.partial"
    if (Test-Path -LiteralPath $partial) {
        throw "Refusing to overwrite stale partial download: $partial"
    }

    if (Test-Path -LiteralPath $sharedArchive -PathType Leaf) {
        Copy-Item -LiteralPath $sharedArchive -Destination $partial
    } else {
        $transport = & curl.exe --fail --silent --show-error `
          --proto "=https" `
          --output $partial `
          --write-out "%{http_code}|%{url_effective}" `
          $url
        if ($LASTEXITCODE -ne 0 -or $transport -ne "200|$url") {
            throw "Exact archive transport failed or redirected: $transport"
        }
    }

    if (-not (Test-FrozenArchiveIdentity $partial)) {
        $observed = Get-ArchiveIdentity $partial | ConvertTo-Json -Compress
        throw "Transferred/downloaded archive does not match the frozen bytes: $observed"
    }
    Move-Item -LiteralPath $partial -Destination $archive
}

if (-not (Test-FrozenArchiveIdentity $archive)) {
    throw "Final x64 archive does not match the frozen bytes"
}

Get-ArchiveIdentity $archive | ConvertTo-Json
```

The stage 3 operator may consume this x64 path only after comparing its bytes to
the committed raw-freeze record. The host-local path recorded by stages 1-2 is
provenance, not a requirement that every worker mount the acquisition host's
filesystem. A mismatch in a copied or downloaded file must not be reinterpreted
as a new ClinVar release: preserve its observed identity, restore the frozen
bytes, and continue only after the exact registered hashes match.

### 4. Materialize marker files from the verified installation

The absence of marker files does not mean BIAS or Nirvana is absent. Verify the
installation that produced
`D:\raptor-x64\sample_tsc_nirvana.json.gz`,
`D:\raptor-x64\sample.bias_output.tsv`, and the July masked held-out result.
Then create the markers:

```powershell
$x64Root = "D:\raptor-x64"
$biasRoot = Join-Path $x64Root "BIAS-2015"
$versions = Join-Path $x64Root "VERSIONS.md"
$checksums = Join-Path $x64Root "CHECKSUMS"

$biasCommit = (git -C $biasRoot rev-parse HEAD).Trim()
if ($biasCommit -ne "ade13f206f3e2c2efe3ec92715d974645fc8da8f") {
    throw "Installed BIAS checkout is not the pinned commit: $biasCommit"
}

if (-not (Test-Path -LiteralPath $versions -PathType Leaf)) {
    throw "Existing x64 VERSIONS.md is missing"
}
$versionText = Get-Content -LiteralPath $versions -Raw
if ($versionText -notmatch ([regex]::Escape("3.18.1-0-g05f88047"))) {
    throw "VERSIONS.md does not attest the pinned Nirvana banner"
}

$requiredManifests = @(
    "nirvana-grch38-full.sha256.txt",
    "nirvana-grch38-updates.sha256.txt",
    "bias-hg38-data.sha256.txt"
)
foreach ($name in $requiredManifests) {
    if (-not (Test-Path -LiteralPath (Join-Path $checksums $name) -PathType Leaf)) {
        throw "Missing frozen resource manifest: $name"
    }
}

Set-Content -LiteralPath (Join-Path $x64Root "WORKER_DESIGNATION.txt") `
  -Encoding ascii -NoNewline -Value "adr-0008-designated-x64-worker"
Set-Content -LiteralPath (Join-Path $x64Root "BIAS_COMMIT.txt") `
  -Encoding ascii -NoNewline -Value $biasCommit
Set-Content -LiteralPath (Join-Path $x64Root "NIRVANA_BANNER.txt") `
  -Encoding ascii -NoNewline -Value "3.18.1-0-g05f88047"

& $python (Join-Path $repo "scripts\compute_adr0008_resource_manifest_sha256.py")
if ($LASTEXITCODE -ne 0) { throw "Resource-manifest digest computation failed" }
```

If the BIAS checkout, Nirvana version evidence, installed data, or any of the
three checksum manifests is genuinely absent, that is a real
`BLOCKED_TOOLCHAIN` condition. Missing marker files alone are not.

## Goal

Complete registered stages 3 through 6:

1. Derive and freeze the August GRCh38 TSC1/TSC2 benchmark.
2. Create the deterministic train/dev and holdout split.
3. Export label-free holdout identities.
4. Rebuild ClinVar-derived comparator resources with the holdout masked.
5. Run pinned Nirvana and BIAS-2015 at arm's length on the x64 worker.
6. Verify returned artifacts and join identities exactly.
7. Join labels only after scorer output is frozen.
8. Compute the registered prospective metrics and terminal outcomes.
9. Write immutable machine-readable evidence and a concise report.

This run is the required check of whether RAPTOR meets its preregistered
performance gates on the new ClinVar dataset.

## Existing implementation gap

Do not run `scripts/build_tsc_benchmark.py` unchanged. It is hard-coded to the
July snapshot and July archive digest.

The current v3 operator implements acquisition stages 1 and 2 only. Add the
smallest executable stage 3-6 surface needed for this registered run. Reuse
existing benchmark, split, masking, export, BIAS adapter, evaluation, and
prospective-adjudication modules. Do not reimplement their logic.

The additive implementation must:

- verify the archive bytes against both committed freeze records before
  decompression;
- build the effective eval configuration through the v3 overlay, replacing
  only `labels_snapshot`;
- derive only GRCh38 TSC1/TSC2 records;
- preserve seed `20260701` and holdout fraction `0.7`;
- preserve all registered labels, exclusions, criteria, thresholds, confidence
  bounds, policies, and authorization mappings;
- never use `--skip-verify`;
- freeze the benchmark, train/dev set, holdout, statistics, and their hashes;
- export a holdout VCF containing identities only, with no label,
  review-status, source, or variant-class fields;
- rebuild and independently audit all registered masked comparator resources;
- run BIAS as a separate program, never importing or copying BIAS source into
  RAPTOR;
- require zero held-out comparator survivors;
- require an exact canonical GRCh38 SPDI bijection on return;
- require zero PP3/BP4 scored calls under the existing approved
  disabled/manual policy;
- emit prospective outcomes through the existing registered truth table;
- preserve every July and historical artifact byte-for-byte.

Add focused tests for the new wiring. Do not run broad unrelated test suites.

## x64 runtime verification

Read before execution:

- `docs/DECISIONS.md` ADR-0007, ADR-0008, and ADR-0022
- `docs/ops/adr-0008-resource-manifest-digest.md`
- `docs/ops/devbox-bias-nirvana-handoff.md`
- `docs/ops/masked-heldout-bias-rerun-handoff.md`

Confirm the process is AMD64/x86_64 using the native run-local Python above.
Verify the marker files materialized from the existing installation:

| File | Exact content |
|---|---|
| `D:\raptor-x64\WORKER_DESIGNATION.txt` | `adr-0008-designated-x64-worker` |
| `D:\raptor-x64\BIAS_COMMIT.txt` | `ade13f206f3e2c2efe3ec92715d974645fc8da8f` |
| `D:\raptor-x64\NIRVANA_BANNER.txt` | `3.18.1-0-g05f88047` |

Recompute and compare the installed resource files against:

- `D:\raptor-x64\CHECKSUMS\nirvana-grch38-full.sha256.txt`
- `D:\raptor-x64\CHECKSUMS\nirvana-grch38-updates.sha256.txt`
- `D:\raptor-x64\CHECKSUMS\bias-hg38-data.sha256.txt`

Then run on the real x64 worker, without `--allow-non-x64-host`:

```powershell
Set-Location $repo
& $python scripts\compute_adr0008_resource_manifest_sha256.py
```

Use only the digest printed by that command.

## Scoring-stage approval record

After computing the real resource digest, write an external run-local approval
record with exactly this shape:

```json
{
  "schema": "raptor.eval.scoring_stage_approval.v1",
  "registration_id": "clinvar-2026-08-amendment-v3",
  "decision": "APPROVED_SCORING_STAGE",
  "approver": "@dronasrinivas",
  "approved_at": "2026-09-01T15:25:29.806Z",
  "x64_freeze": {
    "worker_designation": "adr-0008-designated-x64-worker",
    "worker_arch": "x86_64",
    "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
    "nirvana_banner": "3.18.1-0-g05f88047",
    "resource_manifest_sha256": "<digest computed on this worker>"
  },
  "immutable_inputs_verified": true
}
```

Validate it with
`raptor.eval.prospective_freeze.validate_scoring_stage_approval` using the real
default runtime probes. Never inject test probes or bypass the runtime boundary.

Capture and persist `first_scoring_execution_at` immediately before the first
BIAS/Nirvana execution. It must be strictly after the approval timestamp.

## Execute

Use a new external run root under `D:\raptor-x64`; do not put raw archives,
BIAS/Nirvana installations, resource bundles, or large intermediates in the
repository.

Execute in this order:

1. Verify the frozen archive and manifest chain.
2. Validate the scoring-stage approval and immutable inputs.
3. Derive and freeze the August benchmark and deterministic split.
4. Export the label-free holdout VCF.
5. Rebuild and audit the masked ClinVar-derived resources.
6. Run Nirvana and BIAS-2015 at arm's length.
7. Freeze the BIAS TSV and return manifest.
8. Verify resource, mask, identity, return-manifest, and policy invariants.
9. Join labels only after the scorer output is immutable.
10. Compute all registered strata, exact 95% Clopper-Pearson lower bounds,
    coverage, policy parity, and terminal outcomes.
11. Write a new immutable run artifact and human-readable report.
12. Commit only repository-owned implementation and evidence files.

Do not stop for another generic review or approval. Stop only for a hard
invariant failure: archive mismatch, immutable-input drift, wrong worker or tool
identity, corrupt/missing x64 resources, masking leakage, identity mismatch, or
an implementation defect that cannot be corrected without changing registered
semantics.

## Required report

Return:

- benchmark, holdout, and per-stratum counts;
- archive, benchmark, holdout, masked-resource, BIAS TSV, and report hashes;
- observed BIAS, Nirvana, worker, and resource identities;
- masked survivor count and identity-join result;
- PP3/BP4 scored-call count;
- all A0-A6 axis results;
- full-spectrum terminal outcome;
- truncating-pathogenic terminal outcome;
- whether the registered precision and recall lower-bound gates were met;
- commits created;
- any hard blocker, naming the exact failed invariant.
