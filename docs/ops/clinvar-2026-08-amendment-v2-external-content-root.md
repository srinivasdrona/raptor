# External content-root layout — ADR-0020 `clinvar-2026-08-amendment-v2` stage 1/2

> Companion to `docs/ops/devbox-bias-nirvana-handoff.md` (ADR-0007/ADR-0008). This
> document only covers the **stage 1/2 transport + raw archive freeze** external
> root consumed by `raptor.eval.prospective_freeze.execute_transport_and_raw_freeze`
> (`allowed_external_root=`). It does not itself authorize archive access — see
> ADR-0020, the registration spec's `pre_data_approval` block, and
> `docs/project/approvals/clinvar-2026-08-amendment-v2.pre_data_approval.draft.json`
> for why no archive GET has occurred yet.

## Where this lives

Per ADR-0008, multi-GB / external content stays off the ARM Queen and off the
repo tree, isolated under the x64 worker's own scoped directory. For this
registration, that is:

```
D:\raptor-x64\prospective-freeze\clinvar-2026-08-amendment-v2\   <- allowed_external_root
```

(WSL/Linux x64 worker equivalent: `/srv/raptor-x64/prospective-freeze/clinvar-2026-08-amendment-v2/`.)
This directory is **sibling to**, not inside, the BIAS/Nirvana install root
(`D:\raptor-x64\` proper) described in the devbox handoff doc, and it is never
created under `D:\raptor\` / the repo working tree.

## What the code puts here (and only here)

`execute_transport_and_raw_freeze` stage 2 is the only writer into this root. For
each run it:

1. Mints a fresh `run_scope_id = uuid.uuid4().hex`.
2. Creates `allowed_external_root/<run_scope_id>/` (boundary-validated: no
   traversal, no symlink anywhere in the chain, no special files — see
   `_validate_destination_boundary`).
3. Streams the exact registered archive (`dataset_registration.filename`, i.e.
   `variant_summary_2026-08.txt.gz`) into that directory, atomically
   (temp-write + `os.replace`), hashing it as it streams.

Nothing else is ever written under this root by this module. In particular:

- The **transport-freeze record** and **raw-freeze record** (the two JSON
  manifests the overlay names — `data/census/tsc_prospective_validation_2026-08_
  amendment_v2_transport_freeze.json` / `..._raw_freeze.json`) live **inside the
  repo tree**, not under the external root.
- No labels, no benchmark, no BIAS/Nirvana output is ever staged here by stage
  1/2 — those belong to the separate, later, stage 3+ surface.

## Preconditions before the first real GET

- The directory `allowed_external_root` itself must already exist, be a plain
  directory (not a symlink), resolve to itself, sit outside the repository
  working tree, and be writable by the process user.
- This root may already contain content from unrelated prior runs — it is
  never required to be empty. What IS required, and enforced by
  `execute_transport_and_raw_freeze` itself before any archive GET, is that
  each run's own freshly minted `allowed_external_root/<run_scope_id>/`
  destination is unclaimed: if that specific run-scope subdirectory (or the
  archive leaf path inside it) already exists, the run is refused
  (`RUN_SCOPE_DESTINATION_NOT_FRESH`) rather than reusing or overwriting it.
- It must be created and owned on the **ADR-0008 designated x64 worker**. This
  execution-preparation session ran in WSL2 (`uname -m` = `aarch64`), which is
  not that worker (see `assert_runtime_boundary` /
  `docs/project/approvals/clinvar-2026-08-amendment-v2.pre_data_approval.draft.json`),
  so no such directory has been created, and none should be created from this
  host — doing so would not make the host eligible and would only create an
  unused, unverified artifact.

## Not covered here

Resource manifests, the pinned BIAS 3.0.0 commit, and the pinned Nirvana
3.18.1 runtime banner are a separate concern (`x64_freeze` in the approval
record) and are about the BIAS/Nirvana **install**, not this transport/raw
freeze external root. They must also be verified only on the real x64 worker.
