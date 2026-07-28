# Task 4 Fix Report: Bounded Delegation Scope Parsing

## Scope

Closed the sole Task 4 review finding without changing the shared `_json_loads()` helper or implementing later tasks.

`agent_delegations.scopes_json` now uses a delegation-only parser that accepts only bounded `str` values, rejects values longer than 512 characters or deeper than four JSON containers, and degrades JSON/type/recursion failures to no scopes. Only the exact canonical read list or read-plus-write list remains usable.

## TDD Evidence

### RED

```text
./.venv/bin/pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py tests/test_remote_mcp_http.py -q
```

Exit 1 with 9 expected failures: invalid UTF-8 BLOB raised from list/authentication/TokenVerifier, while valid JSON BLOB and oversized text retained the read scope.

### GREEN

The same focused command passed:

```text
64 passed
```

The new regressions cover invalid JSON text, invalid UTF-8 and valid-JSON BLOBs, oversized and deeply nested text, non-list, unknown, and duplicate stored scopes. Store projection/authentication, delegation GET, direct TokenVerifier verification, and real Remote MCP initialization all fail closed with `access="read"`, `scopes=[]`, and MCP `403`.

## Compatibility

- Normal canonical read/write scope rows retain the existing behavior.
- Corrupt rows still appear in the list with the safe read-shaped projection rather than causing a 500.
- The bearer token remains syntactically authenticated for an active row, but it receives no scopes; the existing global read-scope check consistently denies MCP access.

## Final Verification

```text
./.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; first_failure=null

git diff --check
passed
```
