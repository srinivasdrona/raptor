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

## Prior acquisition reference

The exact August URL was acquired once on the ARM orchestration host. That
record proves that acquisition happened before label access, but its host-local
file is not an input dependency for the x64 run. The x64 worker performs a fresh
exact-URL acquisition and freezes the bytes it will actually consume before
decompression or label inspection.

| Item | Value |
|---|---|
| Registration | `clinvar-2026-08-amendment-v3` |
| Evidence commit | `34c3c0a2b6ed9b1756d5abd65b4e53450e2c3d34` |
| Archive | `variant_summary_2026-08.txt.gz` |
| Byte length | `441792560` |
| Prior ARM SHA-256 | `230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500` |
| Prior ARM MD5 | `2d6b8fcec81f20c9db443818d3fa4500` |
| Run scope | `f2d3291b67404153aae1c129a2b973db` |
| Snapshot ID | `clinvar_2026-08-monthly-amendment-v3` |

Authoritative repository inputs:

- `docs/project/specs/clinvar-2026-08-prospective-amendment-v3.yaml`
- `configs/eval/tsc2_clinvar_2026_08_amendment_v3.overlay.yaml`
- `data/census/tsc_prospective_validation_2026-08_amendment_v3_transport_freeze.json`
- `data/census/tsc_prospective_validation_2026-08_amendment_v3_raw_freeze.json`

The prior digests are comparison evidence, not an accessibility requirement and
not an acceptance gate for the x64-local acquisition. A cross-host mismatch is
recorded explicitly; it never causes one host's file to be silently relabelled
as the other. The x64 run requires two matching local downloads from the exact
registered URL, with the registered HTTP status, final URL, Last-Modified and
Content-Length, before its local digest becomes the run's content identity.

Never accept an alternate path, mirror, later release, substitute, or redirect
to a different path.

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
   worker independently retrieves and freezes the exact registered URL into its
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
& $python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Could not prepare pip in the run-local venv" }

& $python -m pip install -e "${repo}[dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install RAPTOR into the run-local venv" }

& $python -c "import platform,sys; print(sys.executable); print(platform.machine()); assert platform.machine().lower() in {'amd64','x86_64'}"
if ($LASTEXITCODE -ne 0) { throw "Python interpreter is not native x64" }

& $python -c "import bioutils,pysam,scipy,yaml; print('RAPTOR runtime dependencies: OK')"
if ($LASTEXITCODE -ne 0) { throw "Run-local RAPTOR dependencies are incomplete" }
```

Native Windows reports `platform.machine()` as `AMD64`; RAPTOR canonicalizes
that known x64 spelling to the approval record's `x86_64`. Do not create WSL or
look for `/home/sdrona/raptor/bin/python` on this worker.

### 3. Acquire and freeze the archive locally on x64

The x64 worker owns the bytes it will consume. Download the exact registered
URL twice without following redirects. Require both local copies to have the
registered transport metadata, exact byte length and identical SHA-256/MD5.
Freeze those locally observed digests before any decompression or label access.

The prior ARM hash is recorded only as a cross-host comparison. It is not a
reason to make the ARM filesystem accessible to x64 and it does not replace the
x64-local content identity.

```powershell
$url = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08.txt.gz"
$runRoot = "D:\raptor-x64\prospective-freeze\clinvar-2026-08-amendment-v3"
$archiveDir = Join-Path $runRoot "x64-local-acquisition"
$archive = Join-Path $archiveDir "variant_summary_2026-08.txt.gz"
$repeatArchive = Join-Path $archiveDir "variant_summary_2026-08.repeat.txt.gz"
$freezeRecord = Join-Path $archiveDir "x64_raw_freeze.json"

New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null

function Get-ArchiveIdentity([string]$Path) {
    [ordered]@{
        path = $Path
        byte_length = (Get-Item -LiteralPath $Path).Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        md5 = (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
}

function Invoke-ExactArchiveDownload([string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        throw "Refusing to overwrite existing acquisition file: $Destination"
    }

    $transport = & curl.exe --fail --silent --show-error `
      --proto "=https" `
      --output $Destination `
      --write-out "%{http_code}|%{url_effective}" `
      $url
    if ($LASTEXITCODE -ne 0 -or $transport -ne "200|$url") {
        throw "Exact archive transport failed or redirected: $transport"
    }
}

if (Test-Path -LiteralPath $freezeRecord) {
    throw "x64 acquisition is already frozen; reuse it only through its verified record"
}

$head = (& curl.exe --fail --silent --show-error --head --proto "=https" $url) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Exact archive HEAD failed" }
if ($head -notmatch "(?m)^HTTP/\S+\s+200\s+OK\s*$") {
    throw "Exact archive HEAD did not return HTTP 200"
}
if ($head -notmatch "(?mi)^Last-Modified:\s*Thu, 06 Aug 2026 04:05:02 GMT\s*$") {
    throw "Exact archive Last-Modified drifted"
}
if ($head -notmatch "(?mi)^Content-Length:\s*441792560\s*$") {
    throw "Exact archive Content-Length drifted"
}

foreach ($existing in @($archive, $repeatArchive)) {
    if (Test-Path -LiteralPath $existing) {
        $stamp = Get-Date -Format "yyyyMMddTHHmmss"
        Move-Item -LiteralPath $existing -Destination "$existing.prior-$stamp"
    }
}

Invoke-ExactArchiveDownload $archive
Invoke-ExactArchiveDownload $repeatArchive

$first = Get-ArchiveIdentity $archive
$second = Get-ArchiveIdentity $repeatArchive

if ($first.byte_length -ne 441792560 -or $second.byte_length -ne 441792560) {
    throw "One or both x64 downloads have the wrong byte length"
}
if ($first.sha256 -ne $second.sha256 -or $first.md5 -ne $second.md5) {
    throw "Independent x64 downloads do not have identical content hashes"
}

$localFreeze = [ordered]@{
    schema = "raptor.eval.x64_local_raw_freeze.v1"
    registration_id = "clinvar-2026-08-amendment-v3"
    exact_url = $url
    final_url = $url
    http_status = 200
    last_modified_utc = "2026-08-06T04:05:02Z"
    byte_length = $first.byte_length
    sha256 = $first.sha256
    md5 = $first.md5
    repeat_download_sha256 = $second.sha256
    repeat_download_md5 = $second.md5
    frozen_at = (Get-Date).ToUniversalTime().ToString("o")
    label_or_row_access_before_freeze = $false
    prior_arm_sha256 = "230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500"
    prior_arm_md5 = "2d6b8fcec81f20c9db443818d3fa4500"
    cross_host_sha256_match = ($first.sha256 -eq "230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500")
    cross_host_md5_match = ($first.md5 -eq "2d6b8fcec81f20c9db443818d3fa4500")
}

$freezeTemp = "$freezeRecord.tmp"
[System.IO.File]::WriteAllText(
    $freezeTemp,
    ($localFreeze | ConvertTo-Json),
    [System.Text.UTF8Encoding]::new($false)
)
Move-Item -LiteralPath $freezeTemp -Destination $freezeRecord

$localFreeze | ConvertTo-Json
```

The stage 3 operator must consume `$archive` and verify it against
`$freezeRecord` before decompression. It must record the comparison to the
earlier ARM freeze, but cross-host equality is not required: the x64-local
freeze is the content identity for the bytes actually scored. The two local
downloads must agree with each other exactly; otherwise stop with
`BLOCKED_DATA`.

### 4. Re-mask the frozen scorer resources for the new August holdout

The August `variant_summary` is the unseen evaluation label source. It must not
also update the scorer being evaluated.

The pinned BIAS/Nirvana scorer under test was built from the proven March 9
ClinVar source. Therefore, the March VCF, its Nirvana annotation and associated
source files already present under
`D:\raptor-x64\masked-heldout-2026-07-12` are the correct comparator
provenance. Using them does not substitute an old evaluation dataset: they are
part of the frozen model.

Do not download an August VCF or rebuild the model on August labels. That would
change the scorer during evaluation and introduce temporal leakage.

After stage 3 derives the new August benchmark:

1. Export the new holdout identities without labels.
2. Verify the existing March source bundle against the hashes and baseline
   reproduction evidence in
   `docs\ops\masked-heldout-bias-rerun-handoff.md`.
3. Apply the **new August holdout identity set** to the proven March 9 ClinVar
   VCF and its matching Nirvana source.
4. Regenerate PS1/PM5, PP2 and BP1 through BIAS's pinned generators in a new
   run-local namespace.
5. Repeat the PM1 reachability audit for the new holdout; skip PM1 only if both
   the published and reproduced resources have zero reachable holdout rows.
6. Require zero new-heldout survivors in every active ClinVar-derived
   comparator.
7. Keep PP5, BP6 and PS4 forbidden. Their direct-copy submission streams are
   not active scoring inputs and do not require an August replacement.
8. Never reuse the July run's already-masked resources: its 2,577-identity mask
   is a different holdout set.

The frozen evaluation separation is:

| Role | Source |
|---|---|
| Evaluation labels and split | x64-frozen `variant_summary_2026-08.txt.gz` |
| Scorer/tool versions | pinned BIAS 3.0.0 and Nirvana 3.18.1 |
| Scorer comparator provenance | proven March 9 ClinVar source bundle |
| Leakage control | regenerate comparator resources after removing the new August holdout identities |

The stage 3-6 implementation may add a narrow mask adapter for the existing
March Nirvana artifact if its monolithic compressed JSON shape differs from
`scripts\mask_clinvar_source.py`'s identity-only JSONL reader. That adapter may
extract identity fields only and must not expose August labels to the scoring
path.

### 5. Materialize marker files from the verified installation

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

- verify the archive bytes against the x64-local freeze record before
  decompression and record, but not gate on, comparison to the earlier
  host-local acquisition;
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
invariant failure: disagreement between the two x64-local downloads,
registered transport-metadata drift, immutable-input drift, wrong worker or
tool identity, corrupt/missing x64 resources, masking leakage, identity
mismatch, or an implementation defect that cannot be corrected without
changing registered semantics. A mismatch against the prior ARM hash is
reported, not blocking.

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
