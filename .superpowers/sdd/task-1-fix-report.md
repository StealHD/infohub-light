# Task 1 Fix Report — Agent Setup Contract and Input Safety

## Scope

Resolved the four Important findings and the Minor finding from `task-1-review.md`. No proposal, MCP, or UI work was added; no external service was accessed.

## RED / GREEN Evidence

### RED

1. `./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q`
   initially failed 19 tests: the guide exposed the legacy catalog types and the public `github`, `telegram`, `reddit`, `twitter`, `website`, `youtube`, and `apify` setup types were unsupported.
2. After adding the query-value regression, `./.venv/bin/pytest tests/test_source_setup_guidance.py -q`
   failed for `https://example.com/feed?cursor=access_token`, proving that a credential-shaped query value was still accepted.

### GREEN

`./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q`

Result: 37 passed.

## Fixes

- Created an Agent-only registry with exactly `rss`, `telegram`, `github`, `reddit`, `twitter`, `website`, `youtube`, and `apify`; its normalized output explicitly carries `catalog_source_type` plus the validated catalog config.
- Kept `list_source_types()` on the legacy catalog registry and added a REST-projection regression assertion.
- Rejected URL userinfo plus credential-shaped query names and values before alias normalization, across every Agent field.
- Recursively inspect mapping keys and values, reject credential-shaped nested data, and enforce scalar field types before alias parsing.
- Restricted Telegram input to valid public handles and rejected `+invite`, `joinchat`, and preview/non-channel paths.
- Wrapped malformed URL parsing as `SourceConfigError` without including user input in the error.

## Verification

- Focused: 37 passed.
- Static: `./.venv/bin/python -m py_compile src/services/source_type_registry.py` and `git diff --check` passed.
- Full gate: `./.venv/bin/python scripts/test_gate.py run --mode full` passed (exit 0).

## Commit

Implementation commit: `651f39e fix: harden agent source setup guidance`.

## Remaining Attention

Task 3 must consume the returned `catalog_source_type/config` pair, rather than store the public Agent type directly. This fix intentionally leaves Task 3 and later proposal/MCP/UI work out of scope.
