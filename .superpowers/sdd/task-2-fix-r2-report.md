# Task 2 Fix R2 Report

## Scope

Resolved only the 1 Important and 1 Minor findings from
`.superpowers/sdd/task-2-rereview.md`:

- proposal key and URL query-name classification now rejects a controlled set
  of compact credential names after NFKC/camelCase/separator normalization;
- proposal free-text classification no longer treats ordinary `Basic ...` or
  `Bearer ...` business names as credentials.

No Task 3+ mutation service, MCP/REST write contract, UI behavior, lifecycle
clock, transaction, schema, cleanup, or deployment sanitizer behavior changed.

## Changes

- Added an exact compact credential-key set covering common unseparated forms,
  including `apikey`, `accesskey`, `accesstoken`, `authtoken`, `refreshtoken`,
  `clientsecret`, and `clienttoken`. The check uses the same key classifier for
  nested JSON keys and percent-decoded URL query names.
- Kept compact matching controlled and exact. Safe business keys containing
  the letters `key`, including `monkey`, `hockey`, `keyboard_layout`, and
  `keynote`, remain accepted.
- Replaced the context-free `Basic`/`Bearer` match with explicit credential
  header/assignment contexts such as `Authorization`, `Proxy-Authorization`,
  `Cookie`, `X-API-Key`, and `token=`, while retaining known token-prefix
  detection and adding a high-confidence JWT shape.
- Kept the fixed, non-echoing validation error unchanged.

## TDD Evidence

### RED

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py -q
```

Result: exit 1 with 25 expected failures. Compact lowercase/uppercase/full-width
keys and percent-decoded query names were accepted; safe `Basic Engineering
News` and `Bearer Market Report` names were rejected; explicit Cookie,
X-API-Key, token assignment, and JWT shapes were accepted.

### GREEN

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py -q
```

Result: exit 0, 56 passed.

```text
./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q
```

Result: exit 0, 69 passed.

```text
./.venv/bin/python scripts/test_gate.py run --mode full
```

Result: passed, 22/22 commands, no failures, `mapping_miss=false`, duration
50.719 seconds.

## Boundary Review

- Structured sensitive keys still fail closed before JSON persistence or safe
  projection.
- JSON and URL query-name checks share `_is_sensitive_proposal_key()`;
  `parse_qsl()` percent-decodes query names before classification.
- `Authorization: Basic ...` and `Authorization: Bearer ...` remain rejected,
  while the two required business-name regressions are accepted.
- Proposal authoritative-clock, transaction ownership, schema v7, retention,
  maintenance cleanup, and deployment sanitization code paths are unchanged.
