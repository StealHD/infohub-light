# Task 3 Second Review Fix Report

## Outcome

Closed all five Important findings in `.superpowers/sdd/task-3-rereview.md` without implementing Task 4+ proposal orchestration, MCP write tools, delegation, UI, or new REST endpoints.

## Changes

1. **Trusted, versioned plan construction and restoration**
   - `SubscriptionChangePlan` no longer has a public trusted constructor. Planner creation and `restore_plan_snapshot()` are the only supported entry points, and snapshots use a strict versioned JSON envelope.
   - Planner creation, JSON restoration, and apply-time defensive revalidation share `_validate_plan_parts()` as the single invariant builder. It enforces exact per-kind keys and types, target/fingerprint shape, subscription/schedule/disposition contracts, source type-to-catalog mapping, normalized config/source key, public-network marker, managed-only restrictions, and deterministic preview binding.
   - Forged private localhost payloads, false markers, managed types, preview mismatches, extra/malformed fields, and internally forged instances fail closed. Create/update/delete snapshots round-trip through JSON and restore to the same executable plan.

2. **Separated subscription idempotence from source re-enable admission**
   - `ensure_source_allowed()` retains the idempotent shortcut for an already-enabled subscription even when its source remains disabled.
   - A separate `ensure_source_reenable_allowed()` performs capacity admission for a real source `false -> true` transition. Agent and REST source updates use that explicit transition path.

3. **Fail-closed cleanup ownership for outer transactions**
   - Media invalidation, `apply_plan()`, and REST source mutation now require an explicit `PostCommitMediaCleanup` whenever the database transaction is caller-owned, including the default `commit=True` call made inside an existing transaction.
   - Outer commit runs collected unlink work after commit; rollback preserves the database row and bytes and discards cleanup. The collector is not exposed through results or errors, and missing ownership is rejected before mutation.

4. **Context-sensitive public metadata credential classification**
   - Public source projection now detects Task 2-strength known credential value shapes embedded in display text, query values, and fragments after bounded NFKC and percent decoding.
   - GitHub, Slack, MCP, long `sk-`, assignment/header, and JWT shapes remain opaque, while safe titles such as `Bearer Market Report` are allowed unless an explicit authorization context makes them credentials.

5. **Schedule preview reflects the final state**
   - Existing subscriptions merge omitted or empty schedule input with their current state, so preview and apply agree.
   - New subscriptions show the real default final state (`enabled=false`, `interval_minutes=60`) before confirmation.

## TDD Evidence

The new regressions were observed failing before their corresponding production changes:

- public construction/restoration accepted or could not reject forged payloads, and existing/new schedule previews disagreed with apply;
- repeated subscription enable requests at quota failed when the source was disabled, while true source re-enable needed separate admission;
- caller-owned transactions silently lost media cleanup without a collector;
- embedded common token shapes reached public previews and a safe Bearer business title became opaque.

The focused suite then passed with positive and negative coverage for every finding, including all three plan-kind JSON round trips, strict restore schema, apply-time forged-instance defense, Agent/REST quota behavior, outer commit/rollback/no-collector media flows, classifier contexts, and schedule preview/apply consistency.

## Verification

- Python compile plus 484 focused cases passed:
  - `./.venv/bin/python -m py_compile src/services/subscription_mutation.py src/services/source_type_registry.py src/services/quota.py src/services/media_cache.py src/api/server.py`
  - `./.venv/bin/pytest tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_source_schedule.py tests/test_source_health.py tests/test_media_cache_unit.py tests/test_worker.py tests/test_catalog_source_runner.py tests/test_source_setup_guidance.py -q`
- Full gate passed: `./.venv/bin/python scripts/test_gate.py run --mode full`
  - 22/22 commands passed
  - `mapping_miss=false`
  - `ui_impacted=false`
- `python3 -m json.tool project-defaults.yaml` and `git diff --check` passed.

Quota coverage is in the mutation/API tests and media coverage is in `tests/test_media_cache_unit.py`; this repository has no separate `tests/test_quota.py` or `tests/test_media_cache.py` files.

## Remaining Work

None for the five Task 3 rereview findings. Task 4+ callers that own the transaction must pass a `PostCommitMediaCleanup`, commit the database transaction, then run it; rollback paths must discard it.
