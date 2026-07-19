# Task 3 Report: Shared Subscription Mutation Domain Service

## Scope

Implemented only the Task 3 mutation boundary:

- typed `SubscriptionActor`, immutable `SubscriptionChangePlan`, and stable `SubscriptionMutationError`;
- Agent-safe create/update/delete planning with safe previews, target fingerprints, live revalidation, explicit delete disposition, and Task 1 policy consumption;
- one `BEGIN IMMEDIATE` apply transaction spanning source, subscription, schedule, health, avatar-cache DB state, queued-job invalidation, and Feed reconciliation;
- explicit REST mutation methods used by all existing catalog/subscription/schedule mutation paths without changing administrator shared-source rights;
- additive `source_catalog.enforce_public_network` persistence and both existing RSS execution projections, while keeping the internal marker out of REST source responses.

No proposal orchestration, MCP tool, delegation flag/scope, new REST endpoint, or UI behavior was implemented.

## TDD Evidence

### RED

Initial required command:

```text
./.venv/bin/pytest tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py -q
```

Result: collection failed as expected because `src.services.subscription_mutation` did not exist.

Subsequent focused RED cycles verified:

- two REST-context tests failed because `rest_create_subscription` did not exist;
- the API integration test failed because `app.state.subscription_mutations` did not exist;
- four source-metadata credential cases were initially accepted;
- the update credential regression was initially accepted after the fixture was corrected to fail for the intended reason;
- the REST source projection exposed `enforce_public_network` when its internal-field filter was temporarily removed.

Each RED failed for the missing behavior before the corresponding implementation was restored or added.

### GREEN

Domain suite:

```text
./.venv/bin/pytest tests/test_subscription_mutation_service.py -q
36 passed
```

Required focused suite:

```text
./.venv/bin/pytest \
  tests/test_subscription_mutation_service.py \
  tests/test_api_service.py \
  tests/test_api_permissions_matrix.py \
  tests/test_source_schedule.py \
  tests/test_source_health.py -q
165 passed
```

Additional schema/execution regressions:

```text
./.venv/bin/pytest tests/test_service_store.py tests/test_user_config_builder.py tests/test_worker.py -q
43 passed
```

## Atomic Rollback

- Private create inserts source first, rechecks quota, creates/upserts the subscription, and updates the schedule inside the caller-owned transaction.
- A late injected failure after the real schedule write leaves zero source, subscription, and schedule rows.
- An update failure after source/subscription/schedule writes, health reset, and avatar-cache deletion restores the original source, subscription, schedule, health row, and cache DB row.
- `ServiceStore.create_source/update_source/create_subscription/update_subscription/delete_subscription`, `SourceScheduleService`, `SourceHealthService`, and `MediaCacheService` all join the outer transaction without committing it.
- Existing store lifecycle behavior still cancels queued jobs and reconciles Feed state inside that same transaction.

## Agent Safety and Public Network Execution

- Private create consumes Task 1 `catalog_source_type/config/policy`; public Agent types are never written directly as catalog types.
- Only `resolution_mode=create_or_existing` plus `self_service=true` can create; Twitter/Apify `existing_visible_only` returns `source_requires_web_setup`.
- Existing visible shared sources remain subscribable but cannot receive Agent source updates.
- Agent create/update rejects credential-shaped config and source metadata without echoing values.
- RSS/website `policy.public_network_only=true` is persisted as an internal catalog choice and ORed into both user-config and direct Worker catalog execution, including owner/admin-owned Agent-created sources.
- REST never accepts or exposes the internal execution marker, so later owner/admin updates cannot silently clear it.

## REST Compatibility

- Existing API-local mutation implementations are now thin calls to the shared service.
- Pydantic `model_fields_set` still carries omission separately from explicit `null` and empty lists; domain/store tests preserve `override_channel: null`, list clears, and omitted personal tags/priority.
- Existing viewer denial, member private ownership, admin shared-source update/delete, source-key conflict copy/action, HTTP status, `{ok,data}` envelope, and `not_found` isolation pass unchanged.
- REST uses explicit `rest_*` methods rather than the Agent-safe planner, preventing accidental privilege reduction or expansion.

## Verification

```text
./.venv/bin/python scripts/test_gate.py run --mode full
exit 0

git diff --check
exit 0
```

The full gate emitted its normal private command logs under `.test-results/20260717T070907Z-86546`; no failing log was present or opened.

## Self-review

- Re-read every changed public signature and all API call sites; no direct catalog/subscription/schedule store mutation remains in `src/api/server.py`.
- Verified live actor/workspace/role/ownership/visibility and quota checks occur during plan rebuild under `BEGIN IMMEDIATE`.
- Verified missing and cross-user subscription IDs share the same `not_found` contract.
- Verified `disable_private` is explicit, private-owner-only, and checks for remaining subscriptions after deletion before disabling; failure rolls the deletion back.
- Verified health resets only for config/secret identity changes, while avatar invalidation only follows source-key change.
- Verified no Task 4 delegation scope/flag, proposal orchestration, MCP, new REST endpoint, or UI file was touched.

## Commit

- Implementation and tests: `9e0f135` (`refactor: share subscription mutation service`)
- This report is recorded in the follow-up documentation commit reported by the final handoff.

## Remaining Attention

- Task 4+ proposal orchestration must persist only the normalized safe `payload/preview/fingerprints` and invoke `apply_plan()` inside its proposal transition transaction.
- Task 4+ must not expose `enforce_public_network` through MCP projections or introduce a caller-controlled way to clear it.
