# Task 1 Fix R3 Report — Public Setup Identity and Network Policy

## Scope

Resolved the four Important findings and the Minor finding from `task-1-rereview-r3.md`. Changes remain limited to the Task 1 source setup registry contract and pure-function tests. No proposal, MCP, UI, runner, Worker, scheduler, DNS lookup, or external request work was added.

## Fixes

1. Credential classification now NFKC-normalizes untrusted text and separates query-name, query-value, and free-text header/assignment rules. Query names remain fail-closed on sensitive fragments, while query values and free text only reject complete credential labels or known secret/header/assignment forms. Safe `q=monkey` and `Monkey: Daily` inputs remain valid; direct and percent-encoded full-width `token`/`api_key` forms fail with the constant credential error.
2. Agent `rss` and `website` normalization policies now carry `public_network_only=true`. Their local setup validation rejects `localhost` and its subdomains plus loopback, private, link-local, unspecified, reserved, multicast, and otherwise non-global IPv4/IPv6 literals without DNS. Task 3 must preserve this policy when selecting the existing public-network execution path regardless of source owner role.
3. GitHub repository aliases now percent-decode ordinary path characters while rejecting encoded separators, controls, malformed path segmentation, query/fragment/port ambiguity, invalid owner boundaries, overlength owner/repo values, and invalid repo grammar. Repository dots remain supported except for `.` and `..`. YouTube channel IDs require `UC` plus 22 URL-safe characters; playlist IDs use recorded `PL=34` and `UU/LL/FL=24` total-length rules with URL-safe characters.
4. Agent Apify lookup exposes only `platform/kind/target`. Any source customization such as `fetch_limit` or `analysis_mode` fails with the stable `source_requires_web_setup` error instead of being silently discarded.
5. Every no-type guide summary now includes safe `required_fields`; the legacy REST `list_source_types()` projection remains unchanged.

NFKC is used for security classification and hostname safety checks only. It does not rewrite persisted ordinary URL text or GitHub/YouTube identity values; source-specific ASCII grammar remains fail-closed.

## TDD Evidence

### RED

- The first focused run after adding the review regressions failed on all five review groups: missing summary fields, `monkey` false positives/full-width credential bypasses, missing public-network policy/local target rejection, weak GitHub/YouTube identities, and silently discarded Apify customization.
- Self-review added malformed double-slash GitHub identities; the isolated test failed for both `owner//repo` and `https://github.com//openai/codex` before the path parser was tightened.

### GREEN

```console
$ ./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q
197 passed
```

`./.venv/bin/python -m py_compile src/services/source_type_registry.py` and `git diff --check` also passed.

## Full Gate

```console
$ ./.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; duration=47.29s
```

## Self-review

- Confirmed ordinary safe query values and labels are not NFKC-rewritten or rejected by query-name substring policy.
- Confirmed local network checks perform no name resolution and the policy contract, rather than Task 1 runner changes, carries the execution requirement forward.
- Confirmed GitHub accepts single-character identities, 39/100-character boundaries, and dotted repositories while rejecting controls, encoded separators, repeated separators, and owner hyphen boundary violations.
- Confirmed YouTube tests use syntactically realistic fixed fake IDs and perform no availability lookup.
- Confirmed Apify guide and normalization accept exactly the same lookup identity fields, and the old REST source catalog shape remains covered unchanged.

## Remaining Boundary

Task 3 must treat `policy.public_network_only=true` as mandatory and use the existing DNS-pinned public-network path for every request and redirect; this Task intentionally does not modify execution code.
