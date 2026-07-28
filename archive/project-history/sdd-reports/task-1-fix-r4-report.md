# Task 1 Fix R4 Report — Encoded Credentials and Source Identity Boundaries

## Scope

Resolved only the four Important findings in `task-1-rereview-r4.md`. Changes remain limited to Task 1 source setup normalization and pure-function tests. No proposal, MCP, UI, runner, Worker, scheduler, DNS lookup, or external request work was added.

## Fixes

1. Credential detection now builds a classification-only copy with NFKC normalization, at most two percent-decode rounds, a 16,384-character fail-closed bound, and Unicode `Cf`/default-ignorable removal. Prefix, Bearer/Basic, header, assignment, and userinfo checks run on that copy while accepted text retains its original persisted value. Encoded and ignorable-obfuscated `Authorization` forms fail with the constant credential error; `q=monkey`, `Monkey: Daily`, and safe percent text remain accepted.
2. RSS/website public-network setup validation now locally parses `inet_aton`-style one-to-four-part IPv4 forms with decimal, octal, hexadecimal, and mixed components. Loopback/non-global results such as `127.1`, `2130706433`, `0x7f000001`, and `0177.0.0.1` are rejected without DNS, while ordinary domains remain valid and `policy.public_network_only=true` is unchanged.
3. GitHub repository setup removes one terminal `.git` transport suffix from both confirmed `github.com` repository URLs and the explicitly supported bare `owner/repo.git` form. Existing encoded-separator, control-character, segmentation, owner, and repository grammar boundaries still apply.
4. Telegram setup accepts only a public username root URL with no query, fragment, parameters, or repeated path separators. Official route names including `share`, `proxy`, `socks`, `confirmphone`, `joinchat`, `s`, and other known deep-link namespaces are rejected for both URL and bare-handle input.

## TDD Evidence

### RED

- The first focused run after adding the four review regression groups failed 33 cases for the expected Telegram route/suffix, credential-obfuscation, GitHub clone suffix, and historical IPv4 gaps.
- Self-review added empty Telegram query/fragment, repeated-slash, and `addlist` route cases; the isolated run failed the four newly exposed cases before the URL-root and reserved-route checks were tightened.

### GREEN

```console
$ ./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q
246 passed
```

`./.venv/bin/python -m py_compile src/services/source_type_registry.py` and `git diff --check` also passed.

## Full Gate

```console
$ ./.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; duration=46.537s
```

## Self-review

- Confirmed the security copy never replaces accepted persisted text and fails closed when its length bound is exceeded.
- Compared representative historical IPv4 conversions with the local system `inet_aton` result; loopback mappings matched, public numeric forms remained subject to the normal public-IP classification, and dotted ordinary domains were not parsed as literals.
- Rechecked `.git` removal after path decoding and before repository grammar validation, including the empty-repository boundary.
- Rechecked Telegram public username roots, query/fragment delimiters, repeated separators, private invites, previews, and reserved route names.
- Confirmed the legacy REST source type projection and Task 1 execution-policy shapes were not changed.

## Remaining Boundary

Task 3 must still preserve `policy.public_network_only=true` through the existing per-request and per-redirect public-network execution path. This Task intentionally does not modify execution code.
