# OpenClaw Subscription Management and Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Inteliscope's Remote MCP so explicitly authorized local OpenClaw connections can guide source setup, manage the caller's subscriptions through server-enforced two-stage proposals, and explain source/job failures from sanitized persisted evidence.

**Architecture:** Keep the existing stateless `/mcp` endpoint and user-scoped delegation model. Move subscription mutations into a shared domain service used by REST and MCP, persist short-lived proposals in additive schema v7, and keep source guidance plus diagnostics in focused services behind a thin MCP adapter. Read-only tokens and the original six tools remain compatible; write access is opt-in per newly created delegation and separately guarded by a disabled-by-default feature flag.

**Tech Stack:** Python 3.11+, FastAPI, MCP Python SDK `mcp>=1.26,<2`, Pydantic v2, SQLite, React 19, TypeScript strict, Material UI, TanStack Query, Vitest, Playwright, pytest.

## Global Constraints

- `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false` is the default; turning it off must leave all six read tools available.
- Preserve `inteliscope:read`; add `inteliscope:subscriptions:write`, always accompanied by read scope.
- Existing delegation rows and tokens remain read-only. Only a new Web-created connection can receive write scope.
- `owner`, `admin`, and `member` may manage their own private sources/subscriptions; `viewer` remains read-only.
- Every business write requires `prepare_*` followed by `apply_subscription_change`; proposal TTL is exactly 10 minutes and successful apply is single-use.
- Apply must use `BEGIN IMMEDIATE` and recheck flag, scope, role, ownership, visibility, quota, source key, and target fingerprints before changing business rows.
- Delete requires `source_disposition="keep"` or `"disable_private"`; there is no default.
- Agent-created sources are always private, never accept `secret_env`, credentials, headers, cookies, arbitrary SQL, paths, or caller identity fields, and cannot create Apify sources.
- Source types are exactly `rss`, `github_release`, `github_user`, `reddit_subreddit`, `reddit_user`, `telegram_channel`, `apify_social`, and `hackernews`.
- Diagnostics use deterministic classification only and return one of `auth_missing`, `rate_limited`, `network_timeout`, `upstream_rejected`, `invalid_source_config`, `source_disabled`, `subscription_disabled`, `schedule_blocked`, `worker_unavailable`, `no_items`, or `unknown`.
- Stable new errors are `subscription_writes_disabled`, `write_scope_required`, `proposal_limit`, `proposal_expired`, `proposal_consumed`, `proposal_stale`, `confirmation_mismatch`, and `source_requires_web_setup`; inaccessible object IDs remain `not_found`.
- No server-side Agent/LLM, OAuth, new process, new port, refresh/retry/cancel tool, shared-source mutation, secret collection, local Gateway probe, WebSocket, or in-site chat.
- Logs may contain only delegation ID, tool name, proposal ID, action, result, elapsed time, and request ID; never tool arguments, confirmation text, source config, article/job contents, or diagnostic message.
- Keep delegation limiting at 60 calls/minute with burst 10; keep Nginx `/mcp` at 256 KiB body, 120 requests/minute/IP, and 8 concurrent connections/IP.
- Do not write `usage_events` per MCP call. Continue coalescing `last_used_at` updates to at most once per 15 minutes.
- Automated tests must not call real sources, Apify, AI, Worker loops, scheduler loops, or external OpenClaw services.
- Preserve the current one-time token rules: 90-day lifetime, five active connections, token hash only in SQLite, and token only in Dialog local state.

---

## File and Interface Map

| File | Responsibility |
|---|---|
| `src/security.py` | Shared bounded, context-sensitive credential classification used by public source projection and proposal persistence; classification never rewrites persisted values. |
| `src/services/source_type_registry.py` | Canonical bilingual guide metadata, accepted formats, examples, safe self-service boundary, and Agent input normalization for all eight source types. |
| `src/storage/service_store.py` | Schema v7 proposal table, delegation scope persistence, proposal CRUD/cleanup, transaction-safe source creation, and row projections. |
| `src/services/subscription_mutation.py` | Shared role/ownership/quota/source/schedule validation, normalized change plans, atomic create/update/delete execution, and REST-compatible domain errors. |
| `src/services/agent_change_proposal.py` | Ten-minute proposal lifecycle, exact confirmation hash comparison, stale fingerprint checks, delegation isolation, and single-use apply. |
| `src/mcp/remote_subscription_service.py` | Safe source discovery plus MCP-facing guide/prepare/apply facade. |
| `src/mcp/remote_diagnostics.py` | User-scoped evidence gathering and deterministic source/job cause classification. |
| `src/mcp/remote_models.py` | Pydantic input models and discriminated source union for the eight new MCP tools. |
| `src/mcp/remote_server.py` | Tool registration, annotations, claim-to-actor conversion, rate limiting, safe error/log mapping. |
| `src/mcp/remote_config.py` | Remote MCP read flag/public URL plus the independent subscription-write flag. |
| `src/api/server.py` | Thin REST adapters using `SubscriptionMutationService`; delegation `access` API and service injection into MCP. |
| `frontend/src/features/agents/AgentsPage.tsx` | Read/write access choice, capability labels, permission-aware OpenClaw tool filters, and unchanged one-time-secret lifecycle. |
| `integrations/openclaw/inteliscope/**` | OpenClaw routing, one-field-at-a-time guidance, diagnosis limits, secret refusal, preview/confirmation/apply flow. |

The core interfaces introduced by Tasks 3–6 are fixed before implementation:

- `SubscriptionActor(workspace_id: str, user_id: str, role: str)`.
- `SubscriptionChangePlan` is sealed: only the mutation planners and `SubscriptionMutationService.restore_plan_snapshot()` may create an executable plan; its public constructor stays closed.
- `SubscriptionChangePlan.to_snapshot()` returns the complete version-2 JSON envelope `{version,kind,normalized,preview,targets,fingerprints}`; proposal persistence stores that envelope intact. Version 2 requires update plans to carry the complete final `schedule_preview` after merging live source/subscription/schedule state with every requested delta.
- `SubscriptionMutationService.restore_plan_snapshot(snapshot) -> SubscriptionChangePlan` validates the exact envelope, Agent-type canonical reverse-normalization invariants, final schedule preview binding, targets, and fingerprints. Version-1 snapshots fail closed: Task 5/6 are not implemented in production yet, so there is no persisted proposal migration or legacy fallback; any development-only v1 proposal must be prepared again.
- `SubscriptionMutationService.plan_create(actor, *, source, subscription, schedule) -> SubscriptionChangePlan`.
- `SubscriptionMutationService.plan_update(actor, *, subscription_id, source_updates, subscription_updates, schedule_updates) -> SubscriptionChangePlan`.
- `SubscriptionMutationService.plan_delete(actor, *, subscription_id, source_disposition) -> SubscriptionChangePlan`.
- `SubscriptionMutationService.apply_plan(actor, plan, *, commit=True, post_commit_cleanup=None) -> dict[str, Any]`; a caller-owned transaction must pass an explicit `PostCommitMediaCleanup`, commit before `run()`, and call `discard()` on every rollback or rejection path.
- `DelegatedActor` extends `SubscriptionActor` with `delegation_id: str` and `scopes: tuple[str, ...]`.
- `AgentChangeProposalService.prepare(actor, plan) -> dict[str, Any]`.
- `AgentChangeProposalService.apply(actor, *, proposal_id, confirmation_text) -> dict[str, Any]`.

### Task 1: Canonical Bilingual Source Setup Guidance

**Files:**
- Modify: `src/services/source_type_registry.py`
- Modify: `tests/test_source_type_registry.py`
- Create: `tests/test_source_setup_guidance.py`

**Interfaces:**
- Consumes: Existing `SourceTypeDefinition`, `SourceFieldDefinition`, `validate_source_config()`, and `source_key()`.
- Produces: `get_source_setup_guide(source_type: str | None, locale: str) -> dict[str, Any]` and `normalize_source_setup_input(source_type: str, config: dict[str, Any]) -> dict[str, Any]`.

- [ ] **Step 1: Write failing guide coverage and normalization tests**

```python
from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
    normalize_source_setup_input,
)

SOURCE_TYPES = {
    "rss", "github_release", "github_user", "reddit_subreddit",
    "reddit_user", "telegram_channel", "apify_social", "hackernews",
}

def test_setup_guide_is_complete_bilingual_and_secret_safe():
    zh = get_source_setup_guide(None, "zh-CN")
    en = get_source_setup_guide(None, "en")
    assert {item["type"] for item in zh["source_types"]} == SOURCE_TYPES
    assert {item["type"] for item in en["source_types"]} == SOURCE_TYPES
    for locale, payload in (("zh-CN", zh), ("en", en)):
        assert payload["locale"] == locale
        for summary in payload["source_types"]:
            detail = get_source_setup_guide(summary["type"], locale)["source_type"]
            assert set(detail) >= {
                "type", "label", "description", "self_service",
                "requires_web_setup", "required_fields", "fields",
            }
            for field in detail["fields"]:
                assert set(field) >= {
                    "name", "label", "required", "input_type", "default",
                    "options", "min", "max", "help", "accepted_formats",
                    "examples", "how_to_find",
                }
    serialized = repr((zh, en)).lower()
    assert "secret_env" not in serialized
    assert "token_env" not in serialized
    assert "sk-" not in serialized

def test_agent_normalization_accepts_public_aliases_and_rejects_credentials():
    assert normalize_source_setup_input(
        "github_release", {"repository": "https://github.com/openai/codex"}
    )["owner"] == "openai"
    assert normalize_source_setup_input(
        "reddit_subreddit", {"subreddit": "https://reddit.com/r/LocalLLaMA/"}
    )["subreddit"] == "LocalLLaMA"
    assert normalize_source_setup_input(
        "telegram_channel", {"channel": "https://t.me/durov"}
    )["channel"] == "durov"
    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input("github_user", {
            "username": "openai", "token": "never-store-this",
        })
    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input("rss", {
            "url": "https://example.com/feed?access_token=never-store-this",
        })
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q`

Expected: FAIL because `get_source_setup_guide` and `normalize_source_setup_input` do not exist.

- [ ] **Step 3: Extend registry metadata without changing the existing REST projection**

Add localized guide fields while keeping `list_source_types()` defaulting to its current English `label`, `description`, and field shape:

```python
SUPPORTED_GUIDE_LOCALES = ("zh-CN", "en")
_FORBIDDEN_AGENT_CONFIG_KEYS = {
    "secret", "secret_env", "token", "token_env", "api_key", "password",
    "cookie", "cookies", "authorization", "headers",
}

def get_source_setup_guide(
    source_type: str | None = None,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    selected_locale = locale if locale in SUPPORTED_GUIDE_LOCALES else "en"
    if source_type is None:
        return {
            "locale": selected_locale,
            "source_types": [item.guide_summary(selected_locale) for item in _SOURCE_TYPES],
        }
    definition = _BY_TYPE.get(str(source_type))
    if definition is None:
        raise SourceConfigError(f"unsupported source type: {source_type}")
    return {"locale": selected_locale, "source_type": definition.guide_detail(selected_locale)}

def normalize_source_setup_input(
    source_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(config or {})
    forbidden = {str(key).lower() for key in raw} & _FORBIDDEN_AGENT_CONFIG_KEYS
    if forbidden or _contains_secret_shape(raw):
        raise SourceConfigError("credentials are not accepted; configure secrets in Web")
    aliased = _normalize_public_aliases(source_type, raw)
    allowed = {field.name for field in _BY_TYPE[source_type].fields}
    unknown = set(aliased) - allowed
    if unknown:
        raise SourceConfigError("unsupported fields: " + ", ".join(sorted(unknown)))
    return validate_source_config(source_type, aliased)
```

`_contains_secret_shape()` recursively checks strings for the existing secret prefixes plus Bearer/Basic credentials and rejects RSS query parameter names containing `token`, `key`, `secret`, `auth`, `password`, `signature`, or `credential`. Encode these exact fields and self-service boundaries in `_SOURCE_TYPES`:

| Type | Required / optional fields and defaults | Accepted examples | Self-service / Web boundary |
|---|---|---|---|
| `rss` | required `url`; optional `name`; `keep_latest_item=false` | `https://example.com/feed.xml` | yes; authenticated feed goes to Web |
| `github_release` | required `owner` + `repo`, or alias `repository` | `openai/codex`, `https://github.com/openai/codex` | public repo yes; private/token-only repo goes to Web |
| `github_user` | required `username` | `openai`, `https://github.com/openai` | public user yes; token-only access goes to Web |
| `reddit_subreddit` | required `subreddit`; `sort=hot`; `time_filter=day`; `fetch_limit=25`; `min_score=10` | `LocalLLaMA`, `r/LocalLLaMA`, public subreddit URL | yes |
| `reddit_user` | required `username`; `sort=new`; `fetch_limit=10` | `spez`, `u/spez`, public user URL | yes |
| `telegram_channel` | required `channel`; `fetch_limit=20` | `durov`, `@durov`, `https://t.me/durov` | public channel yes; private channel goes to Web |
| `apify_social` | required `platform`, `kind`, `target`; `fetch_limit=20`; `analysis_mode=full` | `x/profile/openai` | no creation; subscribe a visible preconfigured source or use Web |
| `hackernews` | no identity field; `fetch_top_stories=30`; `min_score=100` | default top stories | yes |

- [ ] **Step 4: Run registry tests and verify GREEN**

Run: `pytest tests/test_source_setup_guidance.py tests/test_source_type_registry.py -q`

Expected: PASS; existing `/api/catalog/source-types` shape tests remain unchanged.

- [ ] **Step 5: Commit the registry contract**

```bash
git add src/services/source_type_registry.py tests/test_source_type_registry.py tests/test_source_setup_guidance.py
git commit -m "feat: add source setup guidance contract"
```

### Task 2: Schema v7 Proposal Persistence and Sanitization

**Files:**
- Modify: `src/storage/service_store.py`
- Modify: `src/services/maintenance.py`
- Modify: `scripts/prepare_service_deployment.py`
- Create: `tests/test_agent_change_proposals.py`
- Modify: `tests/test_maintenance.py`
- Modify: `tests/test_prepare_service_deployment.py`

**Interfaces:**
- Consumes: ServiceStore connection lifecycle, schema migration markers, `_json_dumps()`, `_json_loads()`, and delegation foreign keys.
- Produces: `AgentProposalLimitError`, proposal row projection, proposal create/get/expire/apply/cleanup methods, and schema marker `agent_change_proposals_v7`.

- [ ] **Step 1: Write failing schema, pending-limit, retention, and sanitizer tests**

```python
def test_agent_change_proposal_schema_v7_is_idempotent(store):
    store.initialize(); store.initialize()
    columns = {row["name"] for row in store.connect().execute(
        "PRAGMA table_info(agent_change_proposals)"
    )}
    assert columns == {
        "id", "workspace_id", "user_id", "delegation_id", "kind",
        "source_id", "subscription_id", "payload_json", "preview_json",
        "fingerprints_json", "confirmation_hash", "status", "created_at",
        "expires_at", "applied_at", "result_summary_json", "updated_at",
    }
    marker = store.connect().execute(
        "SELECT name FROM schema_migrations WHERE version = 7"
    ).fetchone()
    assert marker["name"] == "agent_change_proposals_v7"

def test_proposal_pending_limit_is_atomic_and_payload_is_safe(store, delegation):
    for index in range(10):
        store.create_agent_change_proposal(**proposal_values(delegation, index))
    with pytest.raises(AgentProposalLimitError):
        store.create_agent_change_proposal(**proposal_values(delegation, 11))
    raw = store.connect().execute(
        "SELECT payload_json FROM agent_change_proposals LIMIT 1"
    ).fetchone()["payload_json"]
    assert "secret_env" not in raw
    assert "Authorization" not in raw
```

Extend the deployment sanitizer and maintenance assertions:

```python
assert result["agent_change_proposals_removed"] == 1
assert deployed.execute("SELECT COUNT(*) FROM agent_change_proposals").fetchone()[0] == 0
assert maintenance_result["deleted"]["agent_change_proposals"] == 1
```

- [ ] **Step 2: Run persistence tests and verify RED**

Run: `pytest tests/test_agent_change_proposals.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q`

Expected: FAIL because schema v7 and proposal store methods are absent.

- [ ] **Step 3: Add the additive table, indexes, marker, and store API**

Add these constants and errors:

```python
AGENT_PROPOSAL_TTL_MINUTES = 10
AGENT_PROPOSAL_MAX_PENDING = 10
AGENT_PROPOSAL_PREPARE_EXPIRED_RETENTION_HOURS = 24
AGENT_PROPOSAL_MAINTENANCE_RETENTION_DAYS = 30

class AgentProposalLimitError(ValueError):
    pass
```

Add schema with foreign keys to `workspaces`, `users`, and `agent_delegations`, all `ON DELETE CASCADE`, plus indexes `(delegation_id,status,expires_at)` and `(status,updated_at)`. Add these exact methods:

- `create_agent_change_proposal(*, proposal_id, workspace_id, user_id, delegation_id, kind, source_id, subscription_id, payload, preview, fingerprints, confirmation_hash, created_at, expires_at, commit=True) -> dict[str, Any]`.
- `get_agent_change_proposal(proposal_id) -> dict[str, Any] | None`.
- `expire_agent_change_proposal(proposal_id, *, now, commit=True) -> dict[str, Any] | None`.
- `apply_agent_change_proposal(proposal_id, *, applied_at, result_summary, commit=True) -> dict[str, Any]`.
- `cleanup_agent_change_proposals(*, now, delegation_id=None, maintenance=False, commit=True) -> dict[str, int]`.

`create_agent_change_proposal()` must start `BEGIN IMMEDIATE`, mark elapsed pending rows expired, delete only rows older than 24 hours for the same delegation, count unexpired pending rows, reject the eleventh, then insert. Maintenance mode deletes applied/expired rows older than 30 days. JSON projections return parsed `payload`, `preview`, `fingerprints`, and `result_summary`; raw `*_json` keys never leave the store method.

- [ ] **Step 4: Make source creation transaction-aware and sanitize deployment copies**

Change `ServiceStore.create_source()` to accept `commit: bool = True`; begin/commit only when it owns the transaction and translate unique source-key failures to `SourceKeyConflictError`. In `prepare_deployment_database()`, delete proposals before delegations and report both counters:

```python
agent_change_proposals_removed = (
    connection.execute("DELETE FROM agent_change_proposals").rowcount
    if has_agent_change_proposals else 0
)
agent_delegations_removed = connection.execute("DELETE FROM agent_delegations").rowcount
```

In `MaintenanceService._prune_locked()`, run the 30-day proposal retention in the existing maintenance transaction and add its deleted count to the returned mapping:

```python
proposal_cleanup = self.store.cleanup_agent_change_proposals(
    now=now.isoformat(), maintenance=True, commit=False,
)
# Include this expression in the final return mapping:
"agent_change_proposals": proposal_cleanup["deleted"],
```

Update the existing exact deleted-count assertion in `tests/test_maintenance.py` to include `"agent_change_proposals": 0`, then seed one 31-day-old applied proposal and assert the count becomes 1.

- [ ] **Step 5: Run persistence tests and verify GREEN**

Run: `pytest tests/test_agent_change_proposals.py tests/test_agent_delegations.py tests/test_maintenance.py tests/test_prepare_service_deployment.py -q`

Expected: PASS, including idempotent initialization, foreign keys, concurrent pending cap, cleanup windows, and sanitized deployment copies.

- [ ] **Step 6: Commit schema v7**

```bash
git add src/storage/service_store.py src/services/maintenance.py scripts/prepare_service_deployment.py tests/test_agent_change_proposals.py tests/test_maintenance.py tests/test_prepare_service_deployment.py
git commit -m "feat: persist agent change proposals"
```

### Task 3: Shared Subscription Mutation Domain Service

**Files:**
- Create: `src/security.py`
- Modify: `src/services/source_type_registry.py`
- Create: `src/services/subscription_mutation.py`
- Modify: `src/api/server.py`
- Modify: `src/storage/service_store.py`
- Create: `tests/test_subscription_mutation_service.py`
- Modify: `tests/test_api_service.py`
- Modify: `tests/test_api_permissions_matrix.py`

**Interfaces:**
- Consumes: Task 1 normalization, `QuotaService`, `SourceScheduleService`, `SourceHealthService`, `MediaCacheService`, and transaction-aware store operations from Task 2.
- Produces: `SubscriptionActor`, sealed `SubscriptionChangePlan`, `SubscriptionMutationError`, `plan_create()`, `plan_update()`, `plan_delete()`, `to_snapshot()`, `restore_plan_snapshot()`, `apply_plan(..., post_commit_cleanup=...)`, and thin REST wrappers.

- [ ] **Step 1: Write failing domain tests for every atomic mutation**

```python
def test_private_source_and_subscription_are_created_atomically(service, member):
    actor = SubscriptionActor.from_user(member)
    plan = service.plan_create(
        actor,
        source={"mode": "private", "type": "rss", "display_name": "Example", "config": {"url": "https://example.com/feed.xml"}},
        subscription={"enabled": True, "priority": 25},
        schedule={"enabled": True, "interval_minutes": 60},
    )
    result = service.apply_plan(actor, plan)
    assert result["action"] == "created"
    assert result["source"]["scope"] == "private"
    assert result["subscription"]["source_id"] == result["source"]["id"]
    assert result["schedule"]["enabled"] is True

def test_create_rolls_back_source_when_subscription_admission_fails(service, member, monkeypatch):
    monkeypatch.setattr(service.quota, "ensure_source_allowed", Mock(side_effect=QuotaExceeded("enabled source quota exceeded")))
    plan = private_rss_plan(service, member)
    with pytest.raises(SubscriptionMutationError, match="enabled source quota exceeded"):
        service.apply_plan(SubscriptionActor.from_user(member), plan)
    assert service.store.connect().execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 0

@pytest.mark.parametrize("disposition,source_enabled", [("keep", True), ("disable_private", False)])
def test_delete_requires_explicit_source_disposition(service, member, private_subscription, disposition, source_enabled):
    actor = SubscriptionActor.from_user(member)
    result = service.apply_plan(actor, service.plan_delete(
        actor, subscription_id=private_subscription["id"], source_disposition=disposition,
    ))
    assert result["source_disabled"] is (not source_enabled)
```

Cover in the same file: viewer denial, shared-source update denial through the Agent-safe planner, own-private update, omission versus explicit null/list clearing, schedule interval set `{30,60,180,360,720,1440}`, quota recheck, source-key conflict, Apify `source_requires_web_setup`, and health reset only when config/source identity changes.

- [ ] **Step 2: Run domain and REST tests and verify RED**

Run: `pytest tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py -q`

Expected: FAIL because the shared service does not exist.

- [ ] **Step 3: Create typed plans and exact domain errors**

```python
class SubscriptionMutationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, action: str = ""):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.action = action

@dataclass(frozen=True, slots=True)
class SubscriptionActor:
    workspace_id: str
    user_id: str
    role: str

    @classmethod
    def from_user(cls, user: dict[str, Any]) -> "SubscriptionActor":
        return cls(str(user["workspace_id"]), str(user["id"]), str(user["role"]))

@dataclass(frozen=True, slots=True, init=False)
class SubscriptionChangePlan:
    # No public trusted constructor. Planner and restore entrypoints seal
    # canonical JSON and expose defensive-copy properties only.
    kind: Literal["create", "update", "delete"]

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "version": 2,
            "kind": self.kind,
            "normalized": self.payload,
            "preview": self.preview,
            "targets": self.target_ids,
            "fingerprints": self.fingerprints,
        }
```

`restore_plan_snapshot()` is the only persistence-consumer entrypoint and must validate the exact versioned envelope plus all normalized/preview/target/fingerprint invariants before returning a plan. It reverse-normalizes every public Agent type from canonical catalog config or managed lookup identity and requires the rebuilt `{catalog_source_type,config|lookup_identity,policy}` result to match exactly. Fingerprint existing source/subscription/schedule rows with their `updated_at`; a missing schedule fingerprints as `None`. Update normalized payloads carry a full final `schedule_preview`: source or subscription final disablement forces `enabled=false`, while an explicit request to enable the schedule against a final disabled subject fails during prepare with `source_schedule_unavailable`. Preview contains safe source name/type/normalized public target, subscription fields, the full final schedule fields, action, impact, warnings, and delete disposition. Apply recomputes that final schedule against live state and requires its result to match. The public target is the non-secret RSS URL, repository/user/subreddit/channel identifier, social target summary, or Hacker News settings selected by the user; the preview never exposes a raw config object, credentials, or internal identity fields.

Snapshot compatibility is deliberately fail-closed: version 2 is the only accepted version. Task 5/6 have not shipped proposal orchestration, so no production proposal rows require migration; development-only version-1 proposals must be discarded and prepared again, and consumers must not synthesize missing `schedule_preview` values or reopen the sealed constructor.

- [ ] **Step 4: Implement plan normalization and atomic apply**

`plan_create()` accepts only these source shapes:

```python
{"mode": "existing", "source_id": "src_example"}
{"mode": "private", "type": "rss", "display_name": "Example", "description": "Public feed", "default_channel": None, "default_topics": [], "config": {"url": "https://example.com/feed.xml"}}
```

For private mode, call `normalize_source_setup_input()`, compute `source_key()`, reject `apify_social`, reject any existing workspace source key, and force `scope="private"`, `owner_user_id=actor.user_id`, `secret_env=None`, `enabled=True`. `plan_update()` permits source keys `display_name`, `description`, `default_channel`, `default_topics`, `config`, and `enabled`; it rejects type/scope/owner/secret changes. `plan_delete()` rejects a missing disposition and permits `disable_private` only for the actor's private source.

`apply_plan()` must:

```python
conn = self.store.connect()
owns_transaction = not conn.in_transaction
if (not owns_transaction or not commit) and post_commit_cleanup is None:
    raise SubscriptionMutationError("post_commit_cleanup_required", ...)
cleanup = post_commit_cleanup or PostCommitMediaCleanup()
try:
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    self._revalidate_live_plan(actor, plan)
    result = self._apply_normalized(actor, plan, cleanup=cleanup)
    if owns_transaction and commit:
        conn.commit()
        cleanup.run()
    return result
except Exception:
    if owns_transaction and conn.in_transaction:
        conn.rollback()
        cleanup.discard()
    raise
```

The service owns cleanup only when it owns the commit. Task 6 owns the outer proposal transaction, so it must create and pass the collector, commit the database transaction, then run the collector; every rollback or rejected apply discards it.

Create source/subscription/schedule, update source/subscription/schedule, and delete subscription/optionally disable source within that one transaction. Call quota again before enabling, reset health on config identity changes, invalidate avatar on source-key change, and preserve existing schedule/job/feed invalidation behavior by reusing `ServiceStore` and `SourceScheduleService` methods with the outer transaction active.

- [ ] **Step 5: Replace API-local mutation closures with thin service calls**

Instantiate once in `create_app()`:

```python
subscription_mutations = SubscriptionMutationService(
    store,
    quota=quota,
    source_schedules=source_schedules,
    source_health=source_health,
    media_cache=media_cache,
)
```

Map domain errors without exposing internals:

```python
def mutation_api_error(exc: SubscriptionMutationError) -> ApiError:
    return ApiError(exc.code, str(exc), status_code=exc.status_code, action=exc.action)
```

Make catalog/subscription/schedule REST endpoints call direct service methods or build-and-apply a plan. Preserve current HTTP status, envelope, omission/null semantics, viewer policy, admin shared-source rights, and source-key conflict copy.

- [ ] **Step 6: Run domain and REST regression tests**

Run: `pytest tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_source_schedule.py tests/test_source_health.py -q`

Expected: PASS with no REST contract changes beyond internal reuse.

- [ ] **Step 7: Commit the shared mutation boundary**

```bash
git add src/services/subscription_mutation.py src/api/server.py src/storage/service_store.py tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py
git commit -m "refactor: share subscription mutation service"
```

### Task 4: Explicit Delegation Write Access and Feature Flag

**Files:**
- Modify: `src/storage/service_store.py`
- Modify: `src/mcp/remote_config.py`
- Modify: `src/api/server.py`
- Modify: `tests/test_agent_delegations.py`
- Modify: `tests/test_agent_delegation_api.py`
- Modify: `tests/test_remote_mcp_config.py`

**Interfaces:**
- Consumes: Existing delegation creation/list/authentication and RemoteMCPSettings.
- Produces: `AGENT_DELEGATION_READ_SCOPE`, `AGENT_DELEGATION_WRITE_SCOPE`, `access` projection, `RemoteMCPSettings.subscription_writes_enabled`, and POST `{name,access}`.

- [ ] **Step 1: Write failing scope, viewer, compatibility, and flag tests**

```python
def test_new_write_delegation_has_both_scopes_but_existing_rows_remain_read_only(store, user):
    read_connection, _ = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Read",
    )
    write_connection, write_token = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Write",
        access="subscriptions_write",
    )
    assert read_connection["access"] == "read"
    assert read_connection["scopes"] == ["inteliscope:read"]
    assert write_connection["access"] == "subscriptions_write"
    assert store.authenticate_agent_delegation(write_token)["scopes"] == [
        "inteliscope:read", "inteliscope:subscriptions:write",
    ]

def test_viewer_and_disabled_write_flag_reject_write_connections(client, monkeypatch):
    response = client.post("/api/me/agent-delegations", json={
        "name": "Write Mac", "access": "subscriptions_write",
    })
    assert response.status_code in {403, 409}
    assert response.json()["error"]["code"] in {"forbidden", "subscription_writes_disabled"}
```

- [ ] **Step 2: Run delegation/config tests and verify RED**

Run: `pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py -q`

Expected: FAIL because access and the write flag are not defined.

- [ ] **Step 3: Add explicit access mapping without migrating old rows**

```python
AGENT_DELEGATION_READ_SCOPE = "inteliscope:read"
AGENT_DELEGATION_WRITE_SCOPE = "inteliscope:subscriptions:write"

def _scopes_for_access(access: str) -> list[str]:
    if access == "read":
        return [AGENT_DELEGATION_READ_SCOPE]
    if access == "subscriptions_write":
        return [AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE]
    raise ValueError("access must be read or subscriptions_write")
```

Keep `AGENT_DELEGATION_SCOPE = AGENT_DELEGATION_READ_SCOPE` as a compatibility alias. Add `access="read"` to `create_agent_delegation()` and derive list projection access from `scopes_json`; do not update existing rows.

- [ ] **Step 4: Parse and expose the independent write flag**

```python
@dataclass(frozen=True, slots=True)
class RemoteMCPSettings:
    enabled: bool
    public_url: str
    subscription_writes_enabled: bool = False
```

Parse `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED` with the same exact `true|false` validation as the read flag. It may be true only when Remote MCP itself is enabled; otherwise raise a startup configuration error.

- [ ] **Step 5: Extend delegation REST input and output**

```python
class AgentDelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    access: Literal["read", "subscriptions_write"] = "read"
```

GET returns top-level `subscription_writes_enabled` and each connection's `access/scopes`. POST rejects write access with `409 subscription_writes_disabled` when the flag is off and `403 forbidden` for viewers; read creation remains allowed for viewers. PATCH remains name-only by using a separate `AgentDelegationRenameRequest`, preventing access escalation during rename.

- [ ] **Step 6: Run delegation/config tests and verify GREEN**

Run: `pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py -q`

Expected: PASS; token lifetime, hash-only storage, five-connection concurrency, revoke, expiry, and disabled-user tests remain green.

- [ ] **Step 7: Commit explicit access control**

```bash
git add src/storage/service_store.py src/mcp/remote_config.py src/api/server.py tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_config.py
git commit -m "feat: add subscription write delegations"
```

### Task 5: Prepare Proposals and Safe Source Discovery

**Files:**
- Create: `src/services/agent_change_proposal.py`
- Create: `src/mcp/remote_subscription_service.py`
- Create: `tests/test_remote_mcp_subscription_service.py`

**Interfaces:**
- Consumes: Task 1 guides, Task 2 proposal store, Task 3 mutation plans, Task 4 delegated scopes/flag.
- Produces: `DelegatedActor`, `AgentProposalError`, safe `get_source_setup_guide`, `list_available_sources`, and three prepare methods.

- [ ] **Step 1: Write failing discovery and prepare tests**

```python
def test_available_sources_are_user_scoped_and_secret_safe(service, member, other_private, public_source):
    result = service.list_available_sources(
        actor=delegated_actor(member, write=True), source_type=None, unsubscribed_only=False,
    )
    assert [item["id"] for item in result["items"]] == [public_source["id"]]
    assert "secret_env" not in repr(result)
    assert "owner_user_id" not in repr(result)

def test_prepare_create_writes_only_a_safe_ten_minute_proposal(service, member, business_dump):
    before = business_dump()
    result = service.prepare_create_subscription(
        actor=delegated_actor(member, write=True),
        source={"mode": "private", "type": "rss", "display_name": "Example", "config": {"url": "https://example.com/feed.xml"}},
        subscription={"priority": 10}, schedule=None,
    )
    assert result["kind"] == "create"
    assert result["confirmation_text"].startswith("确认执行 ")
    assert parse_iso(result["expires_at"]) - parse_iso(result["created_at"]) == timedelta(minutes=10)
    assert business_dump() == before
```

Also assert: read-only scope returns `write_scope_required`; flag off returns `subscription_writes_disabled`; viewer returns forbidden; unknown/other-user objects return `not_found`; delete requires disposition; preview includes impact/warnings but no raw config.

- [ ] **Step 2: Run service tests and verify RED**

Run: `pytest tests/test_remote_mcp_subscription_service.py -q`

Expected: FAIL because proposal and subscription facade classes do not exist.

- [ ] **Step 3: Add the delegated actor and stable proposal errors**

```python
@dataclass(frozen=True, slots=True)
class DelegatedActor(SubscriptionActor):
    delegation_id: str
    scopes: tuple[str, ...]

class AgentProposalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
```

The guard order is fixed: write feature flag, write scope, role, then object/plan validation. This prevents a disabled flag from creating proposal rows and keeps viewer behavior deterministic.

- [ ] **Step 4: Persist a prepared plan with a one-time confirmation phrase**

```python
def prepare(self, actor: DelegatedActor, plan: SubscriptionChangePlan) -> dict[str, Any]:
    self._require_write(actor)
    proposal_id = f"agp_{uuid.uuid4().hex}"
    created_at = self.now().astimezone(timezone.utc)
    expires_at = created_at + timedelta(minutes=10)
    confirmation_text = f"确认执行 {proposal_id[-8:]}"
    snapshot = plan.to_snapshot()
    row = self.store.create_agent_change_proposal(
        proposal_id=proposal_id,
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        delegation_id=actor.delegation_id,
        kind=snapshot["kind"],
        source_id=snapshot["targets"].get("source_id"),
        subscription_id=snapshot["targets"].get("subscription_id"),
        payload={"plan_snapshot": snapshot},
        # Safe duplicate columns keep existing proposal projection/index usage.
        preview=snapshot["preview"],
        fingerprints=snapshot["fingerprints"],
        confirmation_hash=hashlib.sha256(confirmation_text.encode()).hexdigest(),
        created_at=created_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    return {
        "proposal_id": row["id"], "kind": row["kind"],
        "preview": row["preview"], "created_at": row["created_at"],
        "expires_at": row["expires_at"], "confirmation_text": confirmation_text,
}
```

Map `AgentProposalLimitError` to `proposal_limit`. The confirmation phrase is returned from prepare but only its SHA-256 is stored. The complete version-2 envelope is authoritative; `kind`, target columns, `preview`, and `fingerprints` are safe duplicates that Task 6 must compare with the envelope before calling `restore_plan_snapshot()`. A mismatch or any version-1 snapshot fails closed and never falls back to the old public-constructor shape; the caller must prepare a new proposal.

- [ ] **Step 5: Add the MCP-facing facade and safe source discovery**

`RemoteMCPSubscriptionService` receives `store`, `mutations`, `proposals`, and `secret_is_set: Callable[[str], bool]`. `list_available_sources()` calls `list_visible_sources()` and returns exactly:

```python
{
    "id": source["id"],
    "name": source["display_name"],
    "type": source["type"],
    "scope": source["scope"],
    "enabled": source["enabled"],
    "default_channel": source.get("default_channel"),
    "default_topics": source.get("default_topics", []),
    "secret_configured": bool(source.get("secret_env") and secret_is_set(source["secret_env"])),
    "subscribed": source["id"] in subscribed_source_ids,
}
```

The three prepare facade methods call the matching mutation planner, then `AgentChangeProposalService.prepare()`.

- [ ] **Step 6: Run prepare/discovery tests and verify GREEN**

Run: `pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py -q`

Expected: PASS; prepare changes only proposal rows and never a source/subscription/schedule row.

- [ ] **Step 7: Commit proposal preparation**

```bash
git add src/services/agent_change_proposal.py src/mcp/remote_subscription_service.py tests/test_remote_mcp_subscription_service.py
git commit -m "feat: prepare subscription change proposals"
```

### Task 6: Atomic Apply, Stale Detection, and Single-Use Concurrency

**Files:**
- Modify: `src/services/agent_change_proposal.py`
- Modify: `src/mcp/remote_subscription_service.py`
- Modify: `tests/test_remote_mcp_subscription_service.py`
- Modify: `tests/test_agent_change_proposals.py`

**Interfaces:**
- Consumes: Pending proposal rows and `SubscriptionMutationService.apply_plan()`.
- Produces: `apply_subscription_change()` with exact confirmation, delegation isolation, expiry, stale detection, atomic proposal consumption, and safe result summary.

- [x] **Step 1: Add failing apply lifecycle and concurrency tests**

```python
def test_apply_requires_exact_phrase_and_does_not_consume_on_failure(service, prepared):
    with pytest.raises(AgentProposalError) as mismatch:
        service.apply_subscription_change(
            actor=prepared.actor, proposal_id=prepared.id, confirmation_text="确认",
        )
    assert mismatch.value.code == "confirmation_mismatch"
    assert prepared.reload()["status"] == "pending"
    result = service.apply_subscription_change(
        actor=prepared.actor, proposal_id=prepared.id,
        confirmation_text=prepared.confirmation_text,
    )
    assert result["status"] == "applied"
    with pytest.raises(AgentProposalError) as consumed:
        service.apply_subscription_change(
            actor=prepared.actor, proposal_id=prepared.id,
            confirmation_text=prepared.confirmation_text,
        )
    assert consumed.value.code == "proposal_consumed"

def test_concurrent_apply_has_exactly_one_business_write(service, prepared):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply_or_code(service, prepared), range(2)))
    assert results.count("applied") == 1
    assert results.count("proposal_consumed") == 1
```

Add cases for exact 10-minute boundary, cross-user, cross-delegation, revoked/expired delegation, role downgrade, feature flag change, target `updated_at` change, source-key collision, quota change, and mutation exception rollback.

- [x] **Step 2: Run apply tests and verify RED**

Run: `pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py -q`

Expected: FAIL because apply is absent.

- [x] **Step 3: Implement apply with all checks inside one immediate transaction**

```python
def apply(self, actor: DelegatedActor, *, proposal_id: str, confirmation_text: str) -> dict[str, Any]:
    self._require_write(actor)
    conn = self.store.connect()
    owns_transaction = not conn.in_transaction
    cleanup = PostCommitMediaCleanup()
    try:
        if owns_transaction:
            conn.execute("BEGIN IMMEDIATE")
        row = self.store.get_agent_change_proposal(proposal_id)
        self._require_same_actor_pending(row, actor)
        now = self.now().astimezone(timezone.utc)
        if now >= datetime.fromisoformat(row["expires_at"]):
            self.store.expire_agent_change_proposal(proposal_id, now=now.isoformat(), commit=False)
            if owns_transaction:
                conn.commit()
            cleanup.discard()
            raise AgentProposalError("proposal_expired", "proposal expired")
        actual = hashlib.sha256(str(confirmation_text).encode()).hexdigest()
        if not hmac.compare_digest(actual, row["confirmation_hash"]):
            raise AgentProposalError("confirmation_mismatch", "confirmation text does not match")
        snapshot = row["payload"].get("plan_snapshot")
        duplicate_targets = {key: value for key, value in {
            "source_id": row.get("source_id"),
            "subscription_id": row.get("subscription_id"),
        }.items() if value}
        if (
            not isinstance(snapshot, dict)
            or row["kind"] != snapshot.get("kind")
            or row["preview"] != snapshot.get("preview")
            or row["fingerprints"] != snapshot.get("fingerprints")
            or duplicate_targets != snapshot.get("targets")
        ):
            raise AgentProposalError("proposal_stale", "proposal snapshot does not match stored projection")
        plan = self.mutations.restore_plan_snapshot(snapshot)
        result = self.mutations.apply_plan(
            actor, plan, commit=False, post_commit_cleanup=cleanup,
        )
        self.store.apply_agent_change_proposal(
            proposal_id, applied_at=now.isoformat(),
            result_summary=self._safe_result(result), commit=False,
        )
        if owns_transaction:
            conn.commit()
            try:
                cleanup.run()
            except Exception:
                pass
        return {"proposal_id": proposal_id, "status": "applied", "result": self._safe_result(result)}
    except Exception:
        if owns_transaction and conn.in_transaction:
            conn.rollback()
        cleanup.discard()
        raise
```

On expiry, commit only the proposal status change, discard the collector, then return `proposal_expired`; on every other rejection/exception, roll back and discard. A successful outer commit is the only path that calls `cleanup.run()`; once commit succeeds, cleanup is best-effort and its exception is silently discarded so it cannot expose private paths or turn a committed mutation into an apply failure. `_require_same_actor_pending()` maps absent or cross-scope IDs to `not_found`, applied to `proposal_consumed`, and expired to `proposal_expired`.

- [x] **Step 4: Re-authenticate current delegation state before applying**

Add `ServiceStore.get_active_agent_delegation_principal(delegation_id)` and use it inside apply to confirm active token lifetime, enabled user, current role, and current scopes without needing the opaque token. Build a fresh `DelegatedActor`; do not trust role/scopes captured in the MCP request if they changed after initialize.

- [x] **Step 5: Run lifecycle, transaction, and concurrency tests**

Run: `pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py -q`

Expected: PASS; exactly one concurrent apply succeeds, stale/denied applies change no business rows, and failed mutations leave the proposal pending.

- [x] **Step 6: Commit atomic apply**

```bash
git add src/services/agent_change_proposal.py src/mcp/remote_subscription_service.py src/storage/service_store.py tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py
git commit -m "feat: apply subscription proposals atomically"
```

### Task 7: Deterministic Source and Job Diagnostics

**Files:**
- Create: `src/mcp/remote_diagnostics.py`
- Create: `tests/test_remote_mcp_diagnostics.py`
- Modify: `src/mcp/remote_service.py`
- Modify: `src/services/job_queue.py`
- Modify: `tests/test_remote_mcp_read_service.py`
- Modify: `tests/test_job_queue.py`
- Modify: `tests/test_job_queue_reliability.py`

**Interfaces:**
- Consumes: `SourceHealthService`, `JobQueue`, `RuntimeStatusService`, `sanitize_issue_message()`, subscription/source/schedule rows, a `secret_is_set` callback, and the existing safe job result allowlist.
- Produces: `RemoteMCPDiagnostics.diagnose_source()` and `.diagnose_job()` with one shared response shape.

- [x] **Step 1: Write failing classification, unknown, sanitization, and isolation tests**

```python
@pytest.mark.parametrize("code,category", [
    ("TimeoutError", "network_timeout"),
    ("HTTP_429", "rate_limited"),
    ("Unauthorized", "auth_missing"),
    ("SourceConfigError", "invalid_source_config"),
    ("HTTPError", "upstream_rejected"),
])
def test_job_diagnostic_classifies_safe_codes(diagnostics, failed_job, code, category):
    failed_job(error_code=code, error_message="https://example.com/a?token=secret Authorization: Bearer hidden")
    result = diagnostics.diagnose_job(actor=ACTOR, job_id=failed_job.id)
    assert result["cause"]["category"] == category
    assert result["cause"]["confidence"] == "confirmed"
    assert "token=secret" not in repr(result)
    assert "Bearer hidden" not in repr(result)

def test_diagnostic_degrades_to_unknown_without_evidence(diagnostics, unknown_subscription):
    result = diagnostics.diagnose_source(actor=ACTOR, subscription_id=unknown_subscription["id"])
    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["confidence"] == "unknown"
    assert result["cause"]["message"] == "现有记录不足以确定原因"
```

Also assert that another user's IDs return `RemoteMCPNotFound`, no payload/raw result/worker ID/claim/lock/config/secret environment/secret value/user/workspace field appears, and only anonymous `worker_status` plus `secret_configured: bool` may be used as evidence.

- [x] **Step 2: Run diagnostic tests and verify RED**

Run: `pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py -q`

Expected: FAIL because diagnostics service is absent and safe jobs do not expose sanitized diagnostic messages internally.

- [x] **Step 3: Implement fixed evidence precedence and cause mapping**

Use this precedence:

1. disabled source → `source_disabled` / confirmed;
2. disabled subscription → `subscription_disabled` / confirmed;
3. schedule `last_skip_reason` or disabled/overdue state → `schedule_blocked` / confirmed;
4. queued/running job plus runtime `missing|stale` → `worker_unavailable` / confirmed;
5. normalized error code mapping → confirmed;
6. sanitized message keyword mapping → likely;
7. target-specific successful attempt with an explicit `fetched_count == 0` → `no_items` / confirmed;
8. otherwise `unknown` / unknown.

Code matching is case-insensitive and deterministic:

```python
_CODE_RULES = (
    ("auth_missing", ("unauthorized", "forbidden", "auth", "credential", "tokenmissing")),
    ("rate_limited", ("429", "ratelimit", "rate_limit", "quotaexceeded")),
    ("network_timeout", ("timeout", "timedout", "connection", "dns", "network")),
    ("invalid_source_config", ("sourceconfig", "invalidconfig", "validationerror")),
    ("upstream_rejected", ("httperror", "fetchfailed", "upstream", "rejected")),
)
```

Return the fixed shape:

```python
{
    "target": {"kind": kind, "id": target_id, "name": name},
    "status": status,
    "cause": {"category": category, "code": safe_code, "title": title,
              "message": safe_message, "confidence": confidence,
              "retryable": retryable},
    "evidence": evidence,
    "suggested_actions": actions,
    "related_job_id": related_job_id,
}
```

`diagnose_source()` must combine subscription/source enabled state, schedule state and `last_skip_reason`, persisted Source Health, its related job, and a boolean `secret_configured` computed through the injected callback. Collect and validate both Health and Schedule `last_job_id` references against the actor before choosing one; an owned `user_feed_refresh` is valid when reached through either real foreign-key link even though its own source/subscription columns are empty. Prefer an active Schedule-linked Job, otherwise choose the latest explicit candidate by `(created_at, id)`; run the direct source/subscription fallback query only when no valid explicit candidate exists. Preserve whether the selected Job came from Health, Schedule, both, or fallback. A selected active Job is always the current attempt: source status follows its exact `queued/running` state and prior Health is marked historical. A newer Schedule-linked terminal Job also wins over a different Health Job.

Manual retry reuses the same Job ID, so `JobQueue.retry_job()` must reopen Source Health application provenance in the same transaction that changes the terminal Job to `queued`: delete every `user_source_health_applications` row for that Job and set `user_source_health.last_job_id=NULL` only where it equals that Job ID, while retaining all other Health fields as historical state. The same successful conditional UPDATE must set `result_json=NULL` and `started_at=NULL`; ordinary Job reads and diagnostics therefore expose no prior-attempt result while the retry is queued/running or if the new Worker attempt fails before producing a `FeedRunResult`, and the next claim writes the new attempt's start time. A later Worker `SourceOutcome` can then insert a fresh idempotency row and replace Health for every affected subscription, including a multi-subscription `user_feed_refresh`. A rejected retry or a retry that returns another active Job must not clear provenance or attempt-local fields, and `commit=False` must leave the Job, attempt reset, ledger, and Health-link changes inside the caller-owned transaction. Diagnostics use this explicit link state: detached prior Health is historical while the retried attempt is active; once a new outcome restores `last_job_id` and the application row, that Health is current. Do not infer retry generation from Job/Health status combinations or timestamp ordering. Evidence may contain only the secret boolean; it never contains the environment-variable name.

`diagnose_job()` uses the target Job itself as the attribution boundary: source data supplies only a safe display name, Source Health and Schedule never replace the target's status/code/message, and anonymous Worker readiness applies only while that exact Job is `queued` or `running`. It may classify `no_items` only from that exact Job when it is `succeeded` and its allowlisted result explicitly contains `fetched_count == 0`; Source Health and `item_count` cannot substitute. `diagnose_source()` may use the current healthy last-success attempt or its validated related succeeded Job under the same explicit fetched-count rule. Diagnostic count fields accept only raw JSON integers (excluding booleans) greater than or equal to zero; negative, floating-point, and string values are omitted rather than coerced, while integer zero is preserved.

Each public diagnostic captures one `checked_at` and passes it unchanged to runtime freshness, schedule precedence, and evidence construction. Every externally controlled scalar projection, including Job/Health/Schedule codes, both result identifiers, and complete (pre-truncation) target display names, must use one fail-closed classifier that rejects credential values/URLs, compact `Bearer`/`Basic` schemes (including punctuation separators), and standalone sensitive labels such as `AWS_ACCESS_KEY_ID`, `SSH_PRIVATE_KEY`, terminal `*_KEY`, `*_CONNECTION_STRING`, `CREDENTIAL(S)`, `credentials_json`, `*_KEY_ENV`, `*_API_KEY_ENV`, `*_SECRET_ENV`, `*_TOKEN_ENV`, and `*_API_KEY`. The classifier runs before name truncation and remains diagnostics-local so the general mapping-key classifier keeps its lower false-positive policy and ordinary business names are not broadly suppressed.

Actions use only modes `prepare_change`, `web`, `wait`, or `contact_admin`. Titles/labels are fixed localized strings; they never claim a repair ran.

- [x] **Step 4: Keep ordinary job list/get projection narrow**

Do not add error messages to `list_jobs` or `get_job`. Let diagnostics query the owned raw job internally, sanitize its message with `sanitize_issue_message()`, and apply the existing result allowlist. This preserves the current six-tool data-minimization contract.

- [x] **Step 5: Run diagnostic and leak-regression tests**

Run: `pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py tests/test_source_health.py tests/test_job_queue.py tests/test_job_queue_reliability.py tests/test_worker.py -q`

Expected: PASS with deterministic confidence wording and zero sensitive-field leakage.

- [x] **Step 6: Commit diagnostics**

```bash
git add src/mcp/remote_diagnostics.py src/mcp/remote_service.py tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py
git commit -m "feat: explain source and job failures"
```

### Task 8: Register the Eight New MCP Tools with Exact Annotations

**Files:**
- Create: `src/mcp/remote_models.py`
- Modify: `src/mcp/remote_server.py`
- Modify: `src/api/server.py`
- Modify: `tests/test_remote_mcp_http.py`
- Create: `tests/test_remote_mcp_subscription_http.py`

**Interfaces:**
- Consumes: Task 4 settings/scopes, Task 5–6 subscription facade, Task 7 diagnostics.
- Produces: 14-tool Streamable HTTP surface, typed inputs, claim-derived actor, safe MCP errors, and correct annotations.

- [x] **Step 1: Write failing real-client tool list and prepare/apply tests**

```python
EXPECTED_TOOLS = [
    "get_my_feed", "get_item", "list_subscriptions", "source_health",
    "list_jobs", "get_job", "get_source_setup_guide",
    "list_available_sources", "prepare_create_subscription",
    "prepare_update_subscription", "prepare_delete_subscription",
    "apply_subscription_change", "diagnose_source", "diagnose_job",
]

@pytest.mark.anyio
async def test_real_mcp_client_lists_fourteen_tools_with_exact_annotations(mcp_session):
    listed = await mcp_session.list_tools()
    assert [tool.name for tool in listed.tools] == EXPECTED_TOOLS
    annotations = {tool.name: tool.annotations for tool in listed.tools}
    for name in {"get_source_setup_guide", "list_available_sources", "diagnose_source", "diagnose_job"}:
        assert annotations[name].readOnlyHint is True
        assert annotations[name].destructiveHint is False
        assert annotations[name].idempotentHint is True
        assert annotations[name].openWorldHint is False
    for name in {"prepare_create_subscription", "prepare_update_subscription", "prepare_delete_subscription"}:
        assert annotations[name].readOnlyHint is False
        assert annotations[name].destructiveHint is False
        assert annotations[name].idempotentHint is False
    assert annotations["apply_subscription_change"].destructiveHint is True
```

Add a real-client write flow that creates a write delegation, prepares a free RSS source, verifies no business row before apply, applies the exact phrase, verifies source/subscription rows after apply, then verifies the second apply returns `proposal_consumed`. Add a read-token call that returns `write_scope_required` and a flag-off call that returns `subscription_writes_disabled`.

- [x] **Step 2: Run Remote MCP HTTP tests and verify RED**

Run: `pytest tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py -q`

Expected: FAIL because the eight tools and typed inputs are absent.

- [x] **Step 3: Define discriminated tool inputs**

```python
class ExistingSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["existing"]
    source_id: str

class PrivateSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["private"]
    type: Literal["rss", "github_release", "github_user", "reddit_subreddit", "reddit_user", "telegram_channel", "apify_social", "hackernews"]
    display_name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=500)
    default_channel: str | None = None
    default_topics: list[str] = Field(default_factory=list, max_length=50)

SourceInput = Annotated[ExistingSourceInput | PrivateSourceInput, Field(discriminator="mode")]
```

Define extra-forbid subscription/schedule/update/delete/apply models. No model contains user/workspace, URL outside a source config field, SQL, path, secret, or header fields.

- [x] **Step 4: Pass full authenticated context through the tool runner**

Build a `DelegatedActor` from `AccessToken` claims plus `access.scopes`. Update `run_tool()` so write operations receive delegation ID, scopes, and role; reads continue receiving workspace/user. Catch `AgentProposalError` and `SubscriptionMutationError` by stable code, catch `RemoteMCPNotFound` as `not_found`, and keep internal errors as `internal_error request_id=mcp_...`.

Log format is fixed:

```python
"remote_mcp_call delegation_id=%s tool=%s proposal_id=%s action=%s outcome=%s elapsed_ms=%s request_id=%s"
```

Use `"-"` for absent proposal/action and never log kwargs or exception messages.

- [x] **Step 5: Register all eight tools and inject services from `create_app()`**

Create separate annotation objects:

```python
READ_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PREPARE_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
APPLY_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
```

Keep global MCP auth requiring only `inteliscope:read`; per-tool write checks belong to the proposal service. Change `create_remote_mcp()` to accept the already-created mutation service, runtime status service, and a secret-status callback, keeping one FastMCP/session manager per FastAPI app.

- [x] **Step 6: Run MCP transport, isolation, and annotation tests**

Run: `pytest tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py tests/test_remote_mcp_diagnostics.py tests/test_nginx_remote_mcp.py -q`

Expected: PASS; `/mcp` remains exact/no-redirect, Host/Origin/body/rate limits remain intact, two apps have independent session managers, and cross-user/admin IDs remain `not_found`.

- [x] **Step 7: Commit the 14-tool MCP surface**

```bash
git add src/mcp/remote_models.py src/mcp/remote_server.py src/api/server.py tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py
git commit -m "feat: expose controlled subscription MCP tools"
```

- [x] **Step 8: Add real-client regressions for pre-business validation failures**

Call `prepare_create_subscription` through `ClientSession.call_tool()` with four invalid payloads: an outer identity extra, a nested model extra, an invalid `source.mode` discriminator, and an out-of-range subscription priority. For each call assert the only stable tool error is `invalid_request`, exactly one audit record uses the fixed seven-field layout with `proposal_id=-`, `action=-`, `outcome=invalid_request`, and `request_id=mcp_...`, and neither the response nor captured logs contain submitted values or Pydantic validation details.

Run: `.venv/bin/pytest tests/test_remote_mcp_subscription_http.py -k validation -q`

Expected before the fix: FAIL because FastMCP `Tool.run()` validates before the registered business function, returns SDK/Pydantic error text, and emits no `remote_mcp_call` record.

- [x] **Step 9: Add an app-local outer tool validation adapter**

Create a `FastMCP` subclass in `src/mcp/remote_server.py` that overrides the SDK's outer `call_tool` adapter, with one fresh server instance per FastAPI app. The adapter must use each tool's existing `FuncMetadata.pre_parse_json()` and generated Pydantic argument model to validate before `ToolManager.call_tool`/`Tool.run`; on `ValidationError`, it returns only `ToolError("invalid_request")` and emits one fixed audit record without inspecting, serializing, or logging arguments or exception text in the rejection handler. Successful validation delegates to the SDK call path unchanged, so current `run_tool()` remains the sole normal/business audit path and cannot double-log.

- [x] **Step 10: Verify the Task 8 validation fix and adjacent contracts**

Run the Task 8 focused/transport/diagnostics/Nginx set, Task 4–7 adjacency set, full test gate, `py_compile`, JSON validation, and `git diff --check`. Reconfirm 14-tool order, typed schemas, exact annotations, per-app manager/session isolation, normal `run_tool()` single logging, and zero UI changes; record fresh evidence in `.superpowers/sdd/task-8-fix-r1-report.md` and `WORKLOG.md` before the independent fix commit.

- [x] **Step 11: Add RED regressions for the shared pre-validation delegation bucket**

Use real `ClientSession.call_tool()` calls to prove that ten invalid registered write calls consume burst 10 and the eleventh returns exactly `rate_limited`; every call must emit exactly one fixed seven-field audit record without arguments, validation details, exceptions, URLs, or sensitive values. Mix invalid calls, valid calls, and stable `not_found` business errors to prove all three share one bucket and successful/business calls are not charged twice. Reuse the same stored delegation through two independently created FastAPI apps to prove their buckets are app-local. Send an unauthenticated registered call and an authenticated unknown-tool call before the burst to prove neither is audited or charged and unknown tools retain the SDK `Unknown tool: <name>` result.

Run: `.venv/bin/pytest -q tests/test_remote_mcp_http.py::test_delegation_rate_limiter_refills_at_sixty_calls_per_minute tests/test_remote_mcp_subscription_http.py::test_invalid_registered_calls_consume_burst_before_validation_without_leaks tests/test_remote_mcp_subscription_http.py::test_valid_invalid_and_business_errors_share_one_charge_each tests/test_remote_mcp_subscription_http.py::test_same_delegation_has_independent_buckets_in_two_apps tests/test_remote_mcp_subscription_http.py::test_unauthenticated_and_unknown_tools_are_not_charged_or_audited`

Expected before the fix: five failures because invalid argument validation exits before the limiter in `run_tool()`, and `DelegationRateLimiter` has no injected clock seam.

- [x] **Step 12: Move the single charge to the authenticated outer tool boundary**

Add a monotonic `clock: Callable[[], float]` dependency to `DelegationRateLimiter`, inject one fresh limiter into each `SafeRemoteMCP`, and in `SafeRemoteMCP.call_tool()` charge only a registered tool with a claim-derived non-empty delegation ID. Perform this check before `FuncMetadata.pre_parse_json()` and Pydantic validation; a denied call returns only `ToolError("rate_limited")` and emits one fixed seven-field record with `proposal_id=-` and `action=-`. Remove the limiter check from `run_tool()` so validation, successful calls, and business errors consume exactly one token while validation/rate-limit branches and normal/business branches each have one audit owner.

- [x] **Step 13: Verify the focused GREEN and Task 8/adjacent contracts**

Run the five RED selectors, both Task 8 HTTP files, transport/diagnostics/Nginx tests, the explicit Task 1 and Task 4–7 adjacency files, `py_compile`, both JSON checks, full test gate, and `git diff --check`. Reconfirm exact unknown-tool semantics, unauthenticated no-audit behavior, 14-tool order/schema/annotations, per-app server/session/limiter isolation, and zero UI changes.

- [x] **Step 14: Record and commit the R2 fix**

Write `.superpowers/sdd/task-8-fix-r2-report.md`, append the compact `WORKLOG.md` entry, mark Steps 11–14 complete only after fresh verification, and create one independent commit containing only the Task 8 R2 fix and evidence.

### Task 9: Permission-Aware Assistant Connection UI

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/service.ts`
- Modify: `frontend/src/api/service.test.ts`
- Modify: `frontend/src/features/agents/AgentsPage.tsx`
- Modify: `frontend/src/features/agents/AgentsPage.test.tsx`
- Modify: `frontend/e2e/layout.spec.ts`

**Interfaces:**
- Consumes: Delegation GET `subscription_writes_enabled`, per-connection `access/scopes`, and POST `{name,access}`.
- Produces: explicit access selector, viewer/flag-disabled state, permission chips, and access-specific OpenClaw tool filter without storing the token.

- [ ] **Step 1: Write failing API and component tests**

```tsx
it('creates an explicit subscription-management connection and uses fourteen tools', async () => {
  const browser = userEvent.setup()
  const { api } = renderPage({ ...listing, subscription_writes_enabled: true }, member)
  await browser.click(await screen.findByRole('button', { name: '创建连接' }))
  const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
  await browser.type(within(dialog).getByRole('textbox', { name: '连接名称' }), 'Write Mac')
  await browser.click(within(dialog).getByRole('combobox', { name: '访问权限' }))
  await browser.click(screen.getByRole('option', { name: '可管理订阅' }))
  await browser.click(within(dialog).getByRole('button', { name: '生成一次性令牌' }))
  expect(api.createAgentDelegation).toHaveBeenCalledWith('Write Mac', 'subscriptions_write')
  const config = await screen.findByTestId('openclaw-config')
  expect(config).toHaveTextContent('prepare_create_subscription')
  expect(config).toHaveTextContent('apply_subscription_change')
  expect(config).toHaveTextContent('${INTELISCOPE_MCP_TOKEN}')
  expect(config).not.toHaveTextContent('ih_mcp_v1_one_time_secret')
})

it('never offers write access to a viewer', async () => {
  renderPage({ ...listing, subscription_writes_enabled: true }, viewer)
  await userEvent.click(await screen.findByRole('button', { name: '创建连接' }))
  expect(screen.queryByRole('option', { name: '可管理订阅' })).not.toBeInTheDocument()
})
```

Update service test expectation to POST `{name:'My Mac',access:'subscriptions_write'}`.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `npm --prefix frontend test -- --run src/api/service.test.ts src/features/agents/AgentsPage.test.tsx`

Expected: FAIL because access is not represented.

- [ ] **Step 3: Extend types and API without weakening token state handling**

```typescript
export type AgentDelegationAccess = 'read' | 'subscriptions_write'
export type AgentDelegation = {
  // existing fields
  access: AgentDelegationAccess
  scopes: Array<'inteliscope:read' | 'inteliscope:subscriptions:write'>
}
export type AgentDelegationsResponse = {
  enabled: boolean
  subscription_writes_enabled: boolean
  // existing fields
}
```

Change `createAgentDelegation(name, access = 'read')` to post both fields. Keep the returned token out of React Query by continuing to call it imperatively and storing the result only in local component state.

- [ ] **Step 4: Add the controlled access choice and capability labels**

Use existing MUI `TextField select` and `MenuItem` exports. Default to read access each time the dialog opens. Hide the write option for viewers; disable it with explanatory copy when the write flag is off. Add a connection Chip `只读` or `可管理订阅`, and state explicitly that write access cannot manage secrets, shared sources, jobs, Feed item state, or refreshes. Add a per-connection “复制配置” action that calls `configurationFor(mcpUrl, connection.access)` so an existing write connection never receives the six-tool read-only filter by mistake.

Represent the one-time state as:

```typescript
type OneTimeCredential = { token: string; access: AgentDelegationAccess }
const [oneTimeCredential, setOneTimeCredential] = useState<OneTimeCredential | null>(null)
```

Clearing “我已保存” sets the whole object to `null`.

- [ ] **Step 5: Generate exact tool filters by access**

```typescript
const READ_TOOLS = ['get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job'] as const
const WRITE_TOOLS = [
  ...READ_TOOLS, 'get_source_setup_guide', 'list_available_sources',
  'prepare_create_subscription', 'prepare_update_subscription',
  'prepare_delete_subscription', 'apply_subscription_change',
  'diagnose_source', 'diagnose_job',
] as const

function configurationFor(mcpUrl: string, access: AgentDelegationAccess): string {
  const tools = access === 'subscriptions_write' ? WRITE_TOOLS : READ_TOOLS
  // preserve static Authorization: Bearer ${INTELISCOPE_MCP_TOKEN}
}
```

The page-level example stays read-only; the non-dismissible token Dialog uses the newly created connection's access.

- [ ] **Step 6: Update E2E accessibility and local-probe assertions**

Seed both access types in the mocked delegation response, assert permission chips, keyboard-operable access selection, and unchanged forbidden request list for port 18789, `/mcp`, `ws:`, and `wss:`. Keep mobile bottom navigation at six links and run Axe with no serious/critical violations.

- [ ] **Step 7: Run frontend unit, type, and E2E tests**

Run: `npm --prefix frontend test -- --run src/api/service.test.ts src/features/agents/AgentsPage.test.tsx`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Run: `npm --prefix frontend run test:e2e -- --grep "assistant connection"`

Expected: all commands PASS; after Dialog dismissal the token is absent from DOM, Query cache, mutation cache, URL, localStorage, and sessionStorage.

- [ ] **Step 8: Commit the UI access selector**

```bash
git add frontend/src/api/types.ts frontend/src/api/service.ts frontend/src/api/service.test.ts frontend/src/features/agents/AgentsPage.tsx frontend/src/features/agents/AgentsPage.test.tsx frontend/e2e/layout.spec.ts
git commit -m "feat: choose agent subscription access"
```

### Task 10: OpenClaw Skill Guidance, Diagnostics, and Confirmation Workflow

> Before editing this Skill package, invoke and follow `superpowers:writing-skills`.

**Files:**
- Modify: `integrations/openclaw/inteliscope/SKILL.md`
- Modify: `integrations/openclaw/inteliscope/README.md`
- Modify: `integrations/openclaw/inteliscope/references/tool-contract.md`
- Modify: `integrations/openclaw/inteliscope/references/workflows.md`
- Modify: `tests/test_openclaw_skill.py`

**Interfaces:**
- Consumes: Exact 14-tool contract and access-specific local configuration.
- Produces: deterministic OpenClaw routing for source setup, safe diagnosis, preview/confirmation/apply, deletion choice, and secret refusal.

- [ ] **Step 1: Replace the six-tool-only test with failing 14-tool safety tests**

```python
TOOLS = {
    "get_my_feed", "get_item", "list_subscriptions", "source_health",
    "list_jobs", "get_job", "get_source_setup_guide",
    "list_available_sources", "prepare_create_subscription",
    "prepare_update_subscription", "prepare_delete_subscription",
    "apply_subscription_change", "diagnose_source", "diagnose_job",
}

def test_skill_requires_preview_confirmation_and_never_collects_secrets():
    combined = all_skill_text().lower()
    assert "每次只询问一个" in combined
    assert "source_disposition" in combined
    assert "确认短语" in combined
    assert "prepare" in combined and "apply" in combined
    assert "最多 3" in combined
    assert "不要" in combined and "令牌" in combined and "聊天" in combined
    assert "user_id" not in combined and "workspace_id" not in combined
    assert not re.search(r"ih_mcp_v1_[a-z0-9_-]{10,}", combined)
```

Add assertions that no workflow claims a write before a successful apply result, article data cannot feed write arguments, viewer/read-only connection guidance points to Web connection creation, and Apify without a preconfigured source points to Web.

- [ ] **Step 2: Run Skill tests and verify RED**

Run: `pytest tests/test_openclaw_skill.py -q`

Expected: FAIL because current Skill is read-only and names only six tools.

- [ ] **Step 3: Update the root Skill routing and security boundary**

The root workflow must say:

1. Identify the requested source type and call `get_source_setup_guide`.
2. Ask one missing required field at a time; use defaults for optional fields unless the user asks to customize.
3. For an existing configured source, call `list_available_sources`; never infer a hidden ID.
4. Call exactly one prepare tool and display the complete preview, warnings, effect, expiry, and exact confirmation phrase.
5. Call `apply_subscription_change` only after the user replies with that exact phrase.
6. Report success only from the apply result; on stale/expired mismatch, prepare again.

State that any pasted token/cookie/password/API key is compromised evidence: do not call a tool, do not repeat it, tell the user to rotate it, and direct them to Web SecretStore.

- [ ] **Step 4: Document per-source and delete workflows**

In `references/workflows.md`, include all eight guide paths and the accepted aliases from Task 1. Delete must always ask:

```text
请选择：
1. 仅取消订阅（source_disposition=keep）
2. 同时停用我创建的私有来源（source_disposition=disable_private）
```

There is no assumed selection. Shared/preconfigured sources can only use `keep`.

- [ ] **Step 5: Document bounded diagnostics behavior**

For “哪些来源异常”, call `source_health` first and diagnose only user-selected sources. For “最近有哪些任务失败并说明原因”, call `list_jobs(status=failed)` and diagnose at most the newest three; list more failures without details and ask the user to choose. Render confidence as `已确认`, `较可能`, or `无法确定`, retain safe error code/time/evidence, and describe actions as suggestions. Convert a suggested repair into a prepare call only after the user asks to make that repair.

- [ ] **Step 6: Run Skill tests and local static checks**

Run: `pytest tests/test_openclaw_skill.py -q`

Run: `openclaw skills check`

Expected: PASS; Skill frontmatter remains `name: inteliscope` and requires `mcp.servers.inteliscope`.

- [ ] **Step 7: Commit the Skill workflow**

```bash
git add integrations/openclaw/inteliscope tests/test_openclaw_skill.py
git commit -m "feat: guide OpenClaw subscription changes"
```

### Task 11: Control Contracts, Impact Mapping, and Final Acceptance

**Files:**
- Modify: `API_CONTRACT.md`
- Modify: `ARCHITECTURE_CONTRACT.md`
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `PLAN.md`
- Modify: `tests/test_impact_map.json`
- Modify: `scripts/benchmark_remote_mcp.py` only if new services make the existing 100-call acceptance fixture fail to initialize
- Modify: `tests/test_remote_mcp_performance_script.py` only if the benchmark interface changes
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: Completed implementation and all task-level tests.
- Produces: authoritative contracts, correct targeted-test routing, performance evidence, full gate evidence, and local OpenClaw canary checklist.

- [ ] **Step 1: Update control-plane assertions before editing contracts**

Add the new Python files/tests to the `Remote MCP/OpenClaw` and `API/store` impact groups. Keep `tests/test_impact_map.json` valid JSON and ensure changes to `subscription_mutation.py`, proposal service, diagnostics, UI, and Skill select their focused test groups.

Run: `python scripts/test_gate.py plan --json`

Expected: output names Remote MCP/API-store/frontend groups rather than reporting an unmapped executable file.

- [ ] **Step 2: Update each source-of-truth document once**

- `API_CONTRACT.md`: POST access input, GET access/scopes/write flag, 14 tools, input/output limits, proposal lifecycle, diagnostic shape, and stable errors.
- `ARCHITECTURE_CONTRACT.md`: REST/MCP shared mutation service, proposal ownership, diagnostics ownership, stateless MCP boundary, and no internal HTTP loop.
- `UI_CONTRACT.md`: explicit read/write creation choice, viewer state, capability labels, permission-specific tool filter, and unchanged secret/local-agent restrictions.
- `DECISION_LOG.md`: add one decision recording server-enforced prepare/apply, current OpenClaw Elicitation limitation, opt-in write delegation, and Web-only secret boundary.
- `PLAN.md`: mark implementation status separately from staging/canary; remove Remote MCP writes from non-goals while retaining OAuth/server Agent/refresh/shared-source mutation as non-goals.

- [ ] **Step 3: Run all focused backend and frontend suites**

Run:

```bash
pytest \
  tests/test_source_setup_guidance.py \
  tests/test_agent_change_proposals.py \
  tests/test_subscription_mutation_service.py \
  tests/test_agent_delegations.py \
  tests/test_agent_delegation_api.py \
  tests/test_remote_mcp_subscription_service.py \
  tests/test_remote_mcp_diagnostics.py \
  tests/test_remote_mcp_http.py \
  tests/test_remote_mcp_subscription_http.py \
  tests/test_openclaw_skill.py -q
npm --prefix frontend test -- --run src/api/service.test.ts src/features/agents/AgentsPage.test.tsx
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all commands PASS.

- [ ] **Step 4: Run bounded Remote MCP performance acceptance**

Run: `python scripts/benchmark_remote_mcp.py --calls 100`

Expected JSON: `calls=100`, `latency_pass=true`, `rss_pass=true`, MCP p95 no more than REST p95 + 150 ms, and RSS delta below 80 MiB. The benchmark stays read-only; it verifies the additional tool/service registration does not create persistent sessions or per-call memory growth.

- [ ] **Step 5: Run the repository completion gate**

Run: `python scripts/test_gate.py run --mode full`

Expected: compact summary reports every selected group PASS. Inspect only a named failing log section if the compact summary reports failure.

- [ ] **Step 6: Perform the local real-OpenClaw canary with synthetic/free data**

Start the latest local API with both flags and no external Worker/scheduler:

```bash
HORIZON_REMOTE_MCP_ENABLED=true \
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=true \
HORIZON_REMOTE_MCP_PUBLIC_URL=http://127.0.0.1:8080/mcp \
./scripts/up-latest.sh
```

Create one write connection from `/agents`, save the token in `~/.openclaw/.env` with mode `0600`, install the local Skill, and run:

```bash
openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope
openclaw skills check
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
```

In a real conversation: request a free RSS subscription, verify one-field guidance, inspect prepare preview, confirm exact phrase, verify apply; update priority/schedule with a new proposal; diagnose a seeded safe failure; delete once with `keep`; create again and delete with `disable_private`; revoke the connection and verify the next MCP request is 401. Repeat isolation checks with a second Inteliscope user and confirm neither sees the other's IDs.

- [ ] **Step 7: Append the concise worklog and commit contracts**

Append a `WORKLOG.md` entry containing task, result, verification, and remaining staging/canary boundary. Then commit only the files belonging to this implementation:

```bash
git add API_CONTRACT.md ARCHITECTURE_CONTRACT.md UI_CONTRACT.md DECISION_LOG.md PLAN.md tests/test_impact_map.json WORKLOG.md
git commit -m "docs: finalize MCP subscription management"
```

- [ ] **Step 8: Run final cleanliness checks**

Run: `python3 -m json.tool project-defaults.yaml >/dev/null`

Run: `python3 -m json.tool tests/test_impact_map.json >/dev/null`

Run: `git diff --check`

Run: `git status --short`

Expected: JSON and diff checks PASS. Status is clean except any pre-existing user-owned changes that were deliberately excluded from commits.

## Release Boundary After Local Completion

Local implementation completion does not authorize production rollout. Production still requires: service database backup; API-only staging with write flag off; schema/integrity/foreign-key checks; exact TLS `/mcp` Authorization forwarding and existing Nginx limits; one real six-read/eight-new-tool canary; immediate post-revoke 401; two-user tenant isolation; then explicit flag enablement. Rollback is only `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`; retain additive schema v7 and existing read-only MCP.
