# Task 4 Report: Explicit Delegation Write Access and Feature Flag

## Scope

Implemented only the Task 4 authorization boundary:

- canonical read and subscription-write delegation scopes, with the existing read constant retained as a compatibility alias;
- explicit `access=read|subscriptions_write` creation, defaulting to read and deriving every returned `access` value from stored scopes;
- fail-closed parsing for malformed, duplicate, unknown, or additional stored scopes, without migrating existing rows;
- an independent, disabled-by-default `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED` setting with exact `true|false` parsing and startup dependency validation;
- delegation REST input/output changes, deterministic viewer denial for write connections, disabled-write rejection, and a separate name-only rename model.

No proposal orchestration, Remote MCP write tool, UI, deployment rollout, or production flag enablement was implemented.

## TDD Evidence

### RED

The required focused command was run after adding the access, compatibility, flag, viewer, and rename tests:

```text
./.venv/bin/pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py -q
```

It exited 1 with 17 failures showing the missing `access` projection/argument, write flag field/parser/dependency, API top-level flag, write creation status, viewer denial, and rename isolation. One new two-client test also exposed a test-directory setup mistake; after changing the helper to create parent directories, the isolated test failed for the intended missing behavior (`400` instead of `409`). Production code was added only after that corrected RED.

### GREEN

Required focused suite:

```text
./.venv/bin/pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py -q
32 passed
```

Related TokenVerifier/store/deployment regressions:

```text
./.venv/bin/pytest tests/test_remote_mcp_http.py tests/test_agent_change_proposals.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q
113 passed
```

Full repository gate:

```text
./.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; 0 failed; mapping_miss=false; duration=67.793s
```

## Authorization and Compatibility Review

- `subscriptions_write` is persisted only as the exact canonical pair `inteliscope:read` plus `inteliscope:subscriptions:write`; direct store callers reject every other access value before creating a token or row.
- Authentication continues hashing the opaque token and loading scopes from the matching database row. `access` is never accepted from the bearer token and is not an authentication input.
- Existing read rows are not updated. Re-running initialization leaves their single read scope and read access unchanged.
- Unknown, extra, duplicate, non-list, or malformed scope storage projects no usable scopes. It cannot authenticate through the existing Remote MCP read-scope requirement or be projected as write access.
- The compatibility alias `AGENT_DELEGATION_SCOPE` still points to the read scope, so the existing six Remote MCP tools remain readable by both read and write delegations.
- The write flag gates only creation of new write delegations in this task. Store authentication still recognizes a previously issued write token after the flag is disabled; later write-tool rejection remains the responsibility of the planned write service/tool guard.
- Read delegation creation remains available to viewers when Remote MCP is enabled. A viewer write request returns stable `403 forbidden` whether the independent write flag is on or off; a non-viewer receives `409 subscription_writes_disabled` while it is off.
- PATCH uses a separate `extra="forbid"` rename model, so `access` cannot be added or escalated during rename.
- Token hash-only storage, 90-day TTL, five-active atomic limit, revoke, expiry, usage-touch coalescing, and disabled-user permanent revocation remained green.

## Configuration Review

- Both Remote MCP flags accept only literal lowercase `true` or `false`; whitespace, case variants, and numeric aliases fail startup validation.
- Subscription writes default to false.
- Enabling subscription writes while Remote MCP itself is disabled raises a startup configuration error.
- Reading the new setting does not alter public URL validation or the existing read-only MCP server/tool registration.

## Commit

The implementation, tests, report, and WORKLOG entry are included in the Task 4 commit reported by the final handoff.

## Remaining Attention

- Task 8 write tools must recheck the live write flag for every prepare/apply request so already-issued write tokens fail closed after rollback.
- The planned final contract/documentation task must record the new delegation access and feature flag API; this focused implementation did not edit control-plane contracts.
