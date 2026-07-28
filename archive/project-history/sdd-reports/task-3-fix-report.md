# Task 3 Review Fix Report

## Outcome

Closed all five Important findings in `.superpowers/sdd/task-3-review.md` without implementing Task 4+ proposal orchestration, MCP write tools, delegation, UI, or new REST endpoints.

## Changes

1. **Sealed confirmed plans**
   - `SubscriptionChangePlan` stores canonical JSON snapshots of normalized payload, preview, target IDs, and fingerprints.
   - Every public plan property returns a defensive copy, so nested caller mutation cannot alter the executable plan.
   - Raw prepare requests are no longer retained. Apply revalidates the live actor, visibility, ownership, target identity/fingerprints, and conflicts, then executes the originally normalized snapshot without re-normalizing it.

2. **Public-network enforcement for Agent RSS updates**
   - Agent RSS config updates now use the Task 1 public setup normalizer, reject local/private literal targets, and force the internal `enforce_public_network=true` marker without accepting that marker from caller input.
   - Catalog runner fallback projections preserve the persisted marker when a subscription disappears between eligibility and config construction.

3. **Quota admission on source re-enable**
   - A false-to-true source transition is admitted before the source write whenever the resulting subscription remains enabled.
   - Quota idempotence now requires both the target subscription and source to already be enabled in the workspace.

4. **Transaction-safe avatar invalidation**
   - Database avatar-row invalidation stays inside the owning transaction; filesystem unlink is collected and runs only after a successful commit.
   - Rollback discards deferred cleanup and preserves both the media row and original bytes.
   - `apply_plan(commit=False)` fails closed unless the outer caller supplies an explicit `PostCommitMediaCleanup`; the collector is not exposed in response data. REST-owned mutation cleanup is verified to run after the connection leaves its transaction.

5. **Credential-safe catalog preview projection**
   - Existing-source create/update/delete previews use a shared catalog-to-public projector.
   - Legacy unsafe display/config values (userinfo, sensitive queries, credential assignments, malformed/unsupported targets) produce a stable opaque summary instead of echoing stored content.

## TDD Evidence

The new regressions were observed failing before their corresponding fixes:

- nested plan mutation and apply-time normalizer changes altered or rebuilt confirmed work;
- owner Agent RSS update accepted localhost and the runner fallback dropped the public-network marker;
- disabled-source re-enable at quota capacity did not raise;
- a late mutation failure restored the avatar row but the file had already been removed;
- unsafe existing/update/delete previews echoed legacy content;
- `commit=False` without an explicit cleanup collector did not fail closed.

Each regression then passed after the smallest scoped production change. Additional positive cases cover legal public RSS updates, safe previews, explicit outer-transaction cleanup, rollback preservation, and REST post-commit unlink ordering.

## Verification

- Focused compile plus 452 focused cases:
  - `./.venv/bin/python -m py_compile src/services/subscription_mutation.py src/services/source_type_registry.py src/services/catalog_source_runner.py src/services/quota.py src/services/media_cache.py`
  - `./.venv/bin/pytest tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_source_schedule.py tests/test_source_health.py tests/test_media_cache_unit.py tests/test_worker.py tests/test_catalog_source_runner.py tests/test_source_setup_guidance.py -q`
- Full gate: `./.venv/bin/python scripts/test_gate.py run --mode full`
  - 22/22 commands passed
  - `mapping_miss=false`
  - Python full suite, syntax/JSON, compose checks, legacy Node checks, frontend lint/typecheck/vitest/build all passed
- `git diff --check` passed.

The requested `tests/test_quota.py` and `tests/test_media_cache.py` paths do not exist in this repository; quota coverage is in the mutation/API tests and media coverage is in `tests/test_media_cache_unit.py`.

## Remaining Work

None for the five Task 3 review findings. A Task 4+ outer transaction that calls `apply_plan(commit=False)` must provide a `PostCommitMediaCleanup`, commit the database transaction, then run the collector; on rollback it must discard the collector.
