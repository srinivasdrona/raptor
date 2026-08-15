# S1 stack re-adjudication

**Status:** post-hoc authority-order correction
**Machine record:** [`model_role_s1_readjudication_2026-08-15.json`](../../data/eval/model_role_s1_readjudication_2026-08-15.json)

S1 used:

- planner: Claude Opus 5;
- test author: Gemini 3.7 Flash;
- doer: Claude Sonnet 5;
- checker: GPT-5.6 Sol.

The original checker results incorrectly treated some PLAN additions as if they
were authoritative requirements. This re-adjudication applies:

`SPEC → candidate-visible fixtures → PLAN → tests → implementation`.

A PLAN may clarify mechanics but cannot add or contradict a binding SPEC
requirement.

## Corrected result

S1 remains unsuitable as a winning stack:

- **2/15 clean cells**;
- **13/15 failed cells**.

The reason is now correctly distributed:

| Owner | Cells with attributable failure |
|---|---:|
| Planner | 6 |
| Checker | 6 |
| Doer | 6 |
| Test author | 5 |

Counts overlap because a cell may contain multiple stage failures.

## Major correction

All five registry-bridge cells remain stack failures, but the adjudicated
findings do **not** establish doer or test-author failure:

- the planner added malformed-input and detailed-check-object requirements not
  present in the SPEC;
- several plans contradicted the SPEC's required output of exactly six ordered
  check IDs;
- the checker enforced those PLAN additions over the SPEC.

Primary ownership therefore moves to:

- **planner:** unauthorized contract expansion;
- **checker:** wrong authority resolution / false-positive findings.

## Findings that remain valid

- **Snapshot publisher:** source/output aliasing, destination corruption on a
  failing call, unsafe temporary-file cleanup, malformed record publication and
  untyped output-path failures.
- **Workspace boundary:** whitespace-altering path resolution and acceptance of
  repeated dot-only path forms.
- **Test author:** two missing snapshot test artifacts plus missed snapshot and
  boundary edge cases.

## Consequence

S1 is still ineligible, but it cannot be summarized as "Sonnet failed despite
green Gemini tests." It exposed failures in all four roles, especially the
planner/checker authority boundary.
