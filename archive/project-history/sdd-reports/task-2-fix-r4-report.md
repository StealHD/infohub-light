# Task 2 Fix R4 Report

## Scope

Resolved only the Task 2 R4 findings in `task-2-rereview-r4.md`:

- proposal string values now use bounded classification-only copies with NFKC
  and at most two percent-decode rounds before credential matching;
- URL query names and every query value use the same bounded classification;
- `sk-` matching distinguishes modern `sk-proj-...` and legacy continuous
  alphanumeric token bodies from long hyphenated business names.

No persisted safe value is rewritten. Proposal lifecycle, schema, authoritative
clock, transaction ownership, retention, deployment sanitizer, key suffix
classification, and Task 3+ behavior are unchanged.

## TDD Evidence

### RED

- The first proposal regression run failed in 9 expected cases: full-width,
  once/twice percent-encoded direct and query token values were accepted,
  encoded result summaries were accepted, and the two requested long `SK-`
  business names were rejected.
- The bounded-copy regression then failed in 2 expected cases for oversized
  input and NFKC output amplification.
- The direct query-component regression failed for a twice-encoded token in a
  query name, proving query names were not yet receiving credential-pattern
  classification.

### GREEN

- `./.venv/bin/pytest tests/test_agent_change_proposals.py -q`: 86 passed.
- `./.venv/bin/pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q`: 99 passed.
- `./.venv/bin/python scripts/test_gate.py run --mode full`: 22/22 commands
  passed, `mapping_miss=false`.
- `./.venv/bin/python -m py_compile src/storage/service_store.py`: passed.
- `git diff --check`: passed before the report/worklog update and rerun before
  commit.

## Changes

- Classification copies are capped at 16 KiB. Input overflow, NFKC expansion,
  and decode output overflow fail closed with the existing fixed non-echoing
  error. Each copy is NFKC-normalized and percent-decoded no more than twice.
- The classifier never mutates `payload`, `preview`, `fingerprints`, or
  `result_summary`; safe `%20` text and safe encoded URLs round-trip unchanged.
- Raw query components are split without an implicit extra decode round. Each
  name receives both sensitive-key and credential-pattern checks, and every
  value receives credential-pattern checks through the shared bounded copies.
- Modern `sk-proj-...` remains rejected. Legacy `sk-` tokens require a long,
  continuous alphanumeric body; realistic fixed fake tokens remain rejected,
  while `SK-Engineering-Newsletter` and `SK-Software-Knowledge-Hub` are allowed.
