# Task 1 Fix R5 Report — Percent-Escaped Hostname Rejection

## Scope

Resolved only the single Important finding in `task-1-rereview-r5.md`. The change remains limited to Task 1 setup normalization and pure-function regression coverage; it does not modify proposal, MCP, UI, runner, Worker, scheduler, DNS lookup, or external request behavior.

## Fix

RSS and website setup validation now rejects any hostname containing `%` before NFKC, IDNA, localhost, standard-IP, or historical-IPv4 classification. This fails closed for percent-escaped local literals and IPv6 zone identifiers without decoding or rewriting the URL that would otherwise be persisted. The rejection uses the existing constant `url must target the public network` and never echoes the supplied URL.

## TDD Evidence

### RED

The new focused regression test first failed all ten source-type/URL cases because percent-escaped hostnames were accepted:

- `127%2e0%2e0%2e1`
- `%31%32%37.0.0.1`
- `localhost%2e`
- `%6cocalhost`
- a public IPv6 literal with a percent-encoded zone identifier

### GREEN

```console
$ ./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q
256 passed
```

`./.venv/bin/python -m py_compile src/services/source_type_registry.py` also passed. Existing regressions retain acceptance for ordinary domains including numeric-label names and retain `policy.public_network_only=true` for RSS and website sources.

## Full Gate

```console
$ ./.venv/bin/python scripts/test_gate.py run --mode full
exit 0
```

`git diff --check` passed after the implementation changes.

## Self-review

- The `%` check applies only after parsing the URL authority and only to RSS/website setup inputs already subject to public-network literal validation.
- The value is never percent-decoded or changed; only its classification is rejected.
- The constant public-network error remains free of user-controlled input.
- IPv6 zone identifiers are rejected whether their `%` is encoded or literal in the parsed hostname.

## Remaining Boundary

Task 3 must continue to honor `policy.public_network_only=true` through the existing per-request and per-redirect public-network execution path. This Task intentionally does not modify execution code.
