# Task 2 Fix R3 Report

## Scope

Resolved only the Task 2 R3 findings in `task-2-rereview-r3.md`:

- compact credential keys now reject controlled credential suffixes after the
  existing NFKC/camelCase/separator normalization;
- the free-text `sk-` token shape now requires a sufficiently long continuous
  token body and a right boundary.

No proposal lifecycle, schema, transaction, retention, deployment sanitizer,
or Task 3+ behavior changed.

## TDD Evidence

### RED

`./.venv/bin/pytest tests/test_agent_change_proposals.py -q` exited 1 with
12 expected failures: lowercase, uppercase, full-width, and percent-decoded
`githubtoken` / `webhooksecret` forms were accepted, while short `SK-...`
business names were rejected.

### GREEN

- `./.venv/bin/pytest tests/test_agent_change_proposals.py -q` passed.
- `./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q` passed.
- `./.venv/bin/python scripts/test_gate.py run --mode full` passed.
- `git diff --check` passed.

## Changes

- Keeps the pre-existing audited exact compact-key set, then rejects only the
  controlled compact suffixes `token`, `secret`, `password`, `cookie`,
  `authorization`, `credential`, and `signature` (including plural cookie and
  credential forms). Exact `accesskey`, `privatekey`, and `apikey` remain in
  the audited set.
- JSON field keys and percent-decoded URL query names share that classifier.
  The regression suite preserves safe `monkey`, `hockey`, `keynote`,
  `tokenizer`, and `tokenization` keys.
- `sk-` recognition remains case-insensitive, matching the repository's
  secret-prefix contract, but requires at least 20 continuous token
  characters and a right boundary. `SK-Engineering Weekly` remains valid;
  long `sk-proj-...` token shapes remain rejected.
