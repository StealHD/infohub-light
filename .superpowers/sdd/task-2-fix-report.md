# Task 2 Fix Report

## Scope

Resolved only the two Important findings from `.superpowers/sdd/task-2-review.md`:

- proposal create/apply lifecycle decisions now use an authoritative UTC clock inside the transaction;
- proposal sensitive-key classification now applies NFKC normalization and camelCase boundary splitting.

No Task 3+ mutation service, MCP/REST write contract, or UI behavior was added.

## Changes

- Kept the public `created_at`, `expires_at`, and `applied_at` method signatures. Caller timestamps remain timezone/format checked, and create still requires an exact ten-minute relative interval, but their absolute values no longer affect lifecycle state.
- `create_agent_change_proposal()` obtains authoritative UTC now after transaction acquisition, expires/prunes/counts against that value, and persists `created_at=updated_at=now` plus `expires_at=now+10 minutes`.
- `apply_agent_change_proposal()` validates the compatibility argument but checks expiry and persists `applied_at=updated_at` using authoritative UTC now.
- Added the scoped `_proposal_utc_now()` clock seam for deterministic monkeypatching without changing existing constructors or freezing global system time.
- Sensitive keys are NFKC-normalized and split at camelCase/acronym boundaries before existing fail-closed classification. Nested `apiKey`, `accessToken`, `clientSecret`, full-width variants, and sensitive URL query names are rejected with the existing fixed non-echoing error.
- Cleanup/maintenance fixture rows are now aged directly in the test database instead of backdating public lifecycle arguments.

## TDD Evidence

### RED

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py -q
```

Result: exit 1 with 8 expected failures: five camelCase/NFKC sensitive shapes were accepted, caller-created time was persisted, a future create bypassed the pending cap, and a backdated apply consumed a really expired proposal.

### GREEN

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q
```

Result: exit 0, 36 passed.

```text
./.venv/bin/python scripts/test_gate.py run --mode full
```

Result: passed, 22/22 commands, no failures, `mapping_miss=false`, duration 118.922 seconds.

## Boundary Review

- A future caller `created_at` cannot expire another proposal or create an eleventh unexpired pending row.
- A backdated caller `applied_at` cannot consume a proposal after the authoritative expiry boundary.
- Persisted lifecycle timestamps are fixed from authoritative now, including apply `applied_at/updated_at`.
- `cleanup_agent_change_proposals(now=...)` remains the explicit maintenance/test interface requested by the Task 2 brief.
- `commit=False` outer-transaction behavior and cross-connection `BEGIN IMMEDIATE` behavior are unchanged.
- Safe business identifiers including `source_id`, `subscription_id`, and `confirmation_hash` remain accepted.
