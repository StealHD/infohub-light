# Task 3 Fifth Review Fix Report

## Outcome

Closed both Important findings and the Minor documentation finding in `.superpowers/sdd/task-3-rereview-r5.md` without implementing Task 5/6 proposal orchestration, MCP write behavior, delegation behavior, diagnostics, or UI. All earlier Task 3 protections remain in place.

## Changes

1. **Create/upsert final schedule binding**
   - Create planning now computes final source and subscription enabled states before calling the same `_final_schedule_preview()` used by update planning. Omitted or empty schedule input preserves the real live interval (or the default 60 minutes) while forcing the final preview disabled whenever the final source or subscription is disabled.
   - Existing-source normalized payloads seal the live source enabled state. Snapshot validation, restore, public preview construction, and live revalidation bind that state together with the complete final `schedule_preview`.
   - A disabled but actor-accessible existing source may be used by the controlled create/upsert planner, while REST subscribe visibility remains enabled-only. Explicit `schedule.enabled=true` against any final disabled subject now fails during prepare with `source_schedule_unavailable`; same-plan subscription re-enable on an enabled source remains valid.
   - Create apply compares the actual post-mutation schedule to the sealed preview before commit. Any divergence raises `invalid_plan_snapshot` and rolls back source/subscription/schedule changes atomically.

2. **Final active-source quota transitions**
   - Mutation apply computes the before/after active pair explicitly and performs admission only for a real `inactive -> active` transition. It no longer infers capacity use from `subscription.enabled=true` or from mutation write order.
   - `QuotaService.ensure_source_allowed()` now treats a disabled source as quota-neutral even when its subscription is being enabled. Already-enabled subscriptions remain idempotent.
   - Real source `false -> true` transitions still use the separate `ensure_source_reenable_allowed()` path and are admitted whenever the final subscription is enabled. Enabling a disabled subscription on a genuinely enabled source still checks and rejects at capacity.

3. **Snapshot documentation**
   - `.superpowers/sdd/task-3-brief.md` now shows snapshot version 2 and documents the complete update/create final `schedule_preview`, version-1 fail-closed/no-migration behavior, and mandatory re-prepare for development-only v1 proposals.
   - The already-correct main Task 3/5/6 implementation plan was not changed.

## TDD Evidence

- The initial 21-case create/quota selection produced 13 expected failures: prepare accepted an impossible schedule, enabled live schedules survived a final subscription disable in preview, disabled existing sources could not enter controlled upsert, create apply accepted a divergent final schedule, and quota rejected final-inactive changes.
- The same 21 cases passed after the minimal implementation. Two explicit follow-up regressions also passed for forged create snapshots and source-enabled live-state drift without an `updated_at` change.
- Coverage includes new and existing subscriptions, enabled and disabled existing sources, absent/disabled/enabled schedule rows, subscription disable, explicit schedule enable, omitted/empty schedule input, valid same-plan re-enable, final-inactive quota-neutral changes, true subscription activation, and true source re-enable.

## Verification

- The 12-file focused suite passed all 693 collected cases, including mutation, quota/API, store, schedule, health, source normalization, proposal sanitizer, media, config, and Worker seams.
- Full gate `.test-results/20260717T120103Z-40833/result.json` passed 22/22 commands with `first_failure=null`, `mapping_miss=false`, and `ui_impacted=false`.
- Python compilation, `project-defaults.yaml` JSON validation, and `git diff --check` passed.

## Remaining Work

Task 5/6 still need to implement proposal orchestration and the MCP facade against the existing version-2 snapshot/collector contract. Consumers must reject v1 or incomplete snapshots and require a fresh prepare operation.
