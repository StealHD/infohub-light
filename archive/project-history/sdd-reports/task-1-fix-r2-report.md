# Task 1 Fix R2 Report — Source Setup Security and Policy Boundaries

## Scope

Resolved all six Important findings in `task-1-rereview.md`. Changes are limited to the source setup registry and its focused tests; no proposal, MCP, UI, external network, paid source, AI, Worker, or scheduler work was performed.

## Fixes

1. Query names now fail closed on `token/key/secret/auth/password/signature/credential`, including compound and percent-decoded forms such as `access_key`, `private_key`, and `x_api_key`; decoded and repeated query values are checked independently.
2. All Agent free-text input rejects credential header and assignment forms, including `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, and `token=`. Credential errors are constant and never include input.
3. Unsupported source type errors are constant across guide, Agent normalization, catalog validation, and source key generation.
4. YouTube accepts only HTTPS `youtube.com`/`www.youtube.com` `/feeds/videos.xml` identities with exactly one non-empty `channel_id` or `playlist_id`; normalization returns a canonical `https://www.youtube.com/...` RSS URL.
5. Reddit accepts only a validated bare subreddit name, `r/name`, or an exact subreddit root URL with an optional single trailing slash. Post, user, query, fragment, and multi-segment forms are rejected.
6. Every normalization result carries an explicit execution policy. Self-service types return catalog config plus `create_or_existing`; Twitter and Apify return only a non-create-ready `lookup_identity` plus `existing_visible_only`, `self_service=false`, and `requires_web_setup=true`.

The legacy `list_source_types()` REST projection remains unchanged, and the Agent guide remains exactly the eight required public types.

## TDD Evidence

### RED

- Existing focused baseline: 37 passed.
- After adding the six review regression groups, the focused run failed 66 cases for the expected missing query, free-text, safe-error, YouTube, Reddit, and policy behaviors.
- Self-review added a top-level `x_api_key` mapping regression; it failed because the old path returned `unsupported fields: x_api_key` instead of the constant credential error.

### GREEN

```console
$ ./.venv/bin/pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q
119 passed
```

`./.venv/bin/python -m py_compile src/services/source_type_registry.py` also passed.

## Full Gate

```console
$ ./.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; duration=46.453s
```

`git diff --check` passed with no output.

## Commit

Implementation commit: `e7aa83d fix: close source setup security gaps`.

## Self-review and Remaining Risk

- Rechecked percent-decoded/repeated query handling, YouTube extra query/duplicate identity/fragment/port rejection, Reddit case and trailing-slash behavior, constant errors, and the absence of `enabled` from managed-source lookup identities.
- No production consumer of the new normalization result is introduced in Task 1. Later service work must consume the policy-bearing shape; managed types deliberately omit top-level `catalog_source_type/config` so an old create path fails closed.
- YouTube identity syntax is validated locally without an external availability check, as required by the no-network constraint.
