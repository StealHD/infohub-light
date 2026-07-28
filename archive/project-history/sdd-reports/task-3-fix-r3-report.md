# Task 3 Third Review Fix Report

## Outcome

Closed the two Important findings in `.superpowers/sdd/task-3-rereview-r3.md` without implementing Task 5/6 proposal orchestration, MCP endpoints, delegation behavior, or UI. The sealed plan constructor remains closed.

## Changes

1. **Shared bounded credential classification**
   - Added `src/security.py` as the single classifier used by Task 1 public source metadata/projectors and the Task 2 proposal sanitizer.
   - Classification uses non-persistent copies capped at 16 KiB, NFKC normalization, ignorable-character folding, and at most two percent-decode rounds. Parser/classifier errors fail closed.
   - Mapping keys, query names, query values, fragments, and free-text header/assignment contexts remain distinct. `Bearer Market Report`, `SK-Internationalization`, and short hyphenated `sk-` business text are allowed; legacy `sk-` requires a long continuous alphanumeric body.
   - Embedded AIza keys use the real fixed body length; `gsk_`, `hf_`, GitHub, `xox*`, `sk-proj`, legacy `sk-`, JWT, MCP, and the existing known families are rejected with token boundaries after raw, encoded, or full-width normalization.
   - `_reject_agent_sensitive_metadata()` now converts every `SourceConfigError` from public metadata classification to the fixed non-echoing `invalid_source_config` error instead of ignoring non-credential parser errors.

2. **Versioned proposal consumer contract**
   - Updated the implementation plan's Task 3/5/6 interface map and examples: Task 5 stores the complete `plan.to_snapshot()` envelope in proposal payload while retaining safe preview/fingerprint/target duplicates; Task 6 verifies those duplicates, restores only with `restore_plan_snapshot()`, and never reopens the public constructor.
   - Task 6 now explicitly owns `BEGIN IMMEDIATE` and a `PostCommitMediaCleanup`: pass it to `apply_plan(commit=False)`, call `run()` only after commit, and call `discard()` on rollback or any rejection, including committed expiry rejection.
   - Added a local real-row contract test covering planner → snapshot → Task 2 create/get → duplicate-column verification → restore → outer apply/proposal-consume commit + collector run, plus rollback + discard with proposal/business rows restored.

## TDD Evidence

- Task 3 public metadata/projector regressions first produced 9 expected failures for embedded AIza/gsk_/hf_ values, raw/encoded/full-width fragments, `SK-Internationalization`, and malformed userinfo parser failure.
- Task 2 proposal payload/result/query regressions first produced 10 expected failures; the real proposal-row seam already passed against the existing versioned/store primitives.
- The broader `xox*` family regression then failed specifically for `xoxe-...` before the shared pattern was generalized; it passed after the minimal classifier change.
- The 10-file focused suite passed all 591 collected cases.
- Full gate passed 22/22 commands with `mapping_miss=false` and `ui_impacted=false`.
- Python compile, `project-defaults.yaml` JSON validation, and `git diff --check` passed.

## Remaining Work

Task 5/6 still need to implement the documented proposal service and MCP facade later. They must consume the fixed snapshot/collector contract above; no Task 5/6 business behavior was added here.
