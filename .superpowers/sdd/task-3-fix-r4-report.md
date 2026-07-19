# Task 3 Fourth Review Fix Report

## Outcome

Closed both Important findings in `.superpowers/sdd/task-3-rereview-r4.md` without implementing Task 5/6 proposal orchestration, MCP write behavior, delegation behavior, or UI. The sealed plan constructor remains closed.

## Changes

1. **Canonical Agent-type reverse validation**
   - `validate_normalized_source_setup()` now reconstructs the canonical public Agent input for all eight public types and calls the same forward normalizer used during planning.
   - The rebuilt self-service `{catalog_source_type, config, policy}` or managed `{lookup_identity, policy}` result must match the supplied normalized identity exactly. This rejects catalog-valid but Agent-invalid identities such as generic RSS under YouTube, invalid GitHub owners, Reddit post paths, reserved/private Telegram routes, and noncanonical managed targets.
   - Private-create snapshot restore/apply and supported catalog-config update planning/restore share the same validator; raw Agent input is not persisted or executed.

2. **Complete update schedule final-state binding**
   - Update planning now merges the live schedule, requested schedule delta, and final source/subscription enabled states into a complete `schedule_preview` stored in the sealed normalized payload and shown in the preview.
   - Final source or subscription disablement deterministically forces the schedule preview to disabled. An explicit request to enable a schedule while either final subject is disabled fails during prepare with `source_schedule_unavailable`; re-enabling the subject in the same plan remains allowed.
   - Snapshot restore requires the exact v2 update payload shape and validates the final schedule snapshot's types, explicit-delta relationships, disable-cascade invariants, and preview equality. Apply recomputes it from live state, then verifies the actual post-mutation schedule before commit so late divergence rolls back atomically.

3. **Snapshot compatibility**
   - The plan snapshot version is now 2 because update plans require `schedule_preview`.
   - Version 1 fails closed and callers must prepare a new proposal. Task 5/6 have not shipped production proposal orchestration, so no persisted proposal migration or legacy fallback was added.
   - The Task 3/5/6 implementation-plan contract now documents the v2 envelope and consumer behavior.

## TDD Evidence

- The all-public-type reverse-normalization suite first produced 9 expected failures: two managed round trips returned the wrong envelope and seven forged identities were accepted, while the pre-existing Twitter rejection already passed.
- Shared update planner/restore reverse-validation cases then produced 3 expected failures for GitHub, Reddit, and Telegram before the shared validation path was added.
- Schedule final-state cases first produced 28 expected failures for disable cascades, omitted/empty/interval-only updates, prepare-time rejection, snapshot binding, and live apply binding; the two valid same-plan re-enable cases already passed.
- The 12-file focused suite passed all 657 collected cases. The REST schedule PATCH omission/explicit-null compatibility regression also passed.

## Verification

- Full gate result `.test-results/20260717T100743Z-97424/result.json` passed 22/22 commands, including the complete Python suite, Node/Vitest tests, lint, typecheck, builds, compose validation, and syntax/config checks; `first_failure=null` and `mapping_miss=false`.
- Focused tests, Python compilation, `project-defaults.yaml` JSON validation, and `git diff --check` passed.
- Self-review found no Task 5/6 production business implementation and no external API contract change.

## Remaining Work

Task 5/6 still need to implement proposal orchestration and the MCP facade against the documented v2 snapshot contract. Consumers must reject v1 or missing `schedule_preview` snapshots and require a fresh prepare operation.
