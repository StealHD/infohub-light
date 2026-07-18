# Task 2 Report: Schema v7 Proposal Persistence and Sanitization

## Scope

Implemented only Task 2 persistence and retention boundaries:

- additive schema v7 `agent_change_proposals` table, exact indexes, cascade foreign keys, and migration marker;
- proposal create/get/expire/apply/cleanup store API with JSON projection;
- 10-minute TTL, atomic per-delegation pending cap of 10, 24-hour prepare cleanup, and 30-day maintenance retention;
- fail-closed proposal JSON validation for secret/header/job-content shapes, credential strings, sensitive URL queries, non-JSON objects, and non-finite numbers;
- transaction-aware `create_source(commit=False)` with source-key conflict translation;
- maintenance integration and proposal-first deployment database sanitization, including pre-v7 compatibility.

No Task 3+ mutation service, MCP tool, REST contract, or UI behavior was implemented.

## TDD Evidence

### RED

Initial command:

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q
```

Result: exit 1 with 17 expected failures because the v7 table/API, maintenance count, deployment count, and `create_source(commit=False)` did not exist.

Self-review added a second focused RED for unsupported JSON objects:

```text
./.venv/bin/pytest 'tests/test_agent_change_proposals.py::test_proposal_payload_rejects_sensitive_shapes_without_echoing_values' -q
```

Result: exit 1 with one expected failure proving that `bytes` could otherwise pass the pre-serialization scan. The implementation was then tightened to accept only strict JSON-compatible values.

### GREEN

Required focused command:

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q
```

Result: exit 0, 27 tests passed.

Python compile check:

```text
./.venv/bin/python -m py_compile src/storage/service_store.py src/services/maintenance.py scripts/prepare_service_deployment.py
```

Result: exit 0.

Full gate:

```text
./.venv/bin/python scripts/test_gate.py run --mode full
```

Result: passed, 22/22 commands, no failures, `mapping_miss=false`, duration 55.927 seconds.

Final whitespace check:

```text
git diff --check
```

Result: exit 0.

## Self-review

- Proposal creation uses `BEGIN IMMEDIATE` when opening its own transaction, expires elapsed pending rows, prunes only same-delegation expired rows older than 24 hours, counts unexpired pending rows, and inserts atomically.
- Store projections remove every raw `*_json` field and expose only parsed `payload`, `preview`, `fingerprints`, and `result_summary`.
- Sensitive validation rejects recursively by structure and value and always raises the fixed non-echoing message `proposal data contains prohibited sensitive content`.
- Apply transitions only unexpired `pending` rows; expire never rewrites applied rows; `commit=False` leaves caller-owned transactions open.
- Maintenance deletes only `applied`/`expired` records whose `updated_at` is older than 30 days and preserves future pending rows.
- Deployment sanitization deletes proposal rows before delegation rows and reports zero when the v7 table does not exist.
- Existing schema and REST-facing store behavior remained green under the full gate.

## Commits

- Implementation: `ef0b41aee99287c7dc45bfe7927464df0dc5592c` (`feat: persist agent change proposals`)
- Report: follow-up documentation commit containing this file.

## Remaining Attention

- Task 3+ must open the outer `BEGIN IMMEDIATE` transaction before using `commit=False` operations for atomic business apply.
- Task 3+ must continue passing only normalized safe proposal payloads/result summaries; the store deliberately fails closed on unknown objects and sensitive shapes.
- This task did not implement proposal business orchestration, MCP/REST adapters, or UI.
