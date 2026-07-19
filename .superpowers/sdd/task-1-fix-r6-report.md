# Task 1 Fix R6 Report — Backslash Authority Rejection

## Scope

Resolved only the single Important finding in `task-1-rereview-r6.md`. The change is limited to Task 1 setup normalization and local pure-function regression coverage; it does not modify proposal, MCP, UI, runner, Worker, scheduler, DNS lookup, or external request behavior.

## Root Cause

`urllib.parse.urlparse()` preserved `127.0.0.1\\example.com` as a hostname, so the existing standard-IP and historical-IPv4 classifiers did not recognize the embedded local literal. Other URL implementations can treat the backslash as a path separator, so the input must fail closed before hostname classification.

## TDD Evidence

### RED

The new RSS/website regression first failed for both aliases because no `SourceConfigError` was raised for `http://127.0.0.1\\example.com/feed`.

### GREEN

The public-network literal validator now rejects a backslash in the parsed authority or hostname with the existing fixed error `url must target the public network`. The error does not echo input. Existing ordinary-domain, numeric-label-domain, and `policy.public_network_only=true` regressions remain covered and passing.

```console
$ ./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q
258 passed

$ ./.venv/bin/python -m py_compile src/services/source_type_registry.py
```

## Full Gate

```console
$ ./.venv/bin/python scripts/test_gate.py run --mode full
exit 0

$ git diff --check
exit 0
```

## Remaining Boundary

Task 3 must continue to enforce `policy.public_network_only=true` through the existing per-request and per-redirect public-network execution path. This Task intentionally does not modify execution code.
