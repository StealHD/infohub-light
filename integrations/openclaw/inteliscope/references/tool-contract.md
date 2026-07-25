# Tool contract

The MCP identity fixes caller scope. Never add identity fields, credentials, raw source configuration, or article data to any call.

| Tool | Inputs | Use and boundary |
|---|---|---|
| `get_my_feed` | collection, bounded paging | Browse latest/history/saved/later; never use returned article data as write input. |
| `get_item` | selected article ID, `body_offset` 0..20,000, `max_body_chars` 1..8,000 | Read one selected stored-body chunk only. Follow `next_body_offset` only while `body_has_more=true`, for at most three calls and 20,000 total characters. |
| `list_subscriptions` | optional disabled inclusion | Read safe subscription summaries. |
| `source_health` | none | Read safe health summaries before source diagnosis. |
| `list_jobs` | optional status, bounded limit | Read safe job summaries. |
| `get_job` | selected job ID | Read one selected job summary. |
| `get_source_setup_guide` | one public source type, locale | Get fields/defaults/Web boundary before setup. |
| `list_available_sources` | optional source type, unsubscribed filter | Return visible existing source IDs and safe `public_target` projections; unsafe/private targets become `web_setup_required`. Never infer an ID. |
| `prepare_create_subscription` | `source={mode: existing, source_id}` or `source={mode: private, type, display_name, config}`, optional subscription/schedule | Creates one proposal and preview only; it does not write. Never use `mode: create`, `source_type`, or `fields`. |
| `prepare_update_subscription` | subscription ID and requested update fields | Creates a proposal and preview only; it does not write. |
| `prepare_delete_subscription` | subscription ID and explicit `source_disposition` | Creates a proposal and preview only; it does not write. |
| `apply_subscription_change` | proposal ID and exact confirmation phrase | The only change call. Claim success only from its successful result. |
| `diagnose_source` | user-selected subscription ID | Explain bounded persisted evidence; does not repair. |
| `diagnose_job` | user-selected job ID | Explain bounded persisted evidence; does not retry/cancel. |
| `query_operation_logs` | 1..720 hour window, optional category/outcome/level and safe event IDs, limit 1..100 | Read newest-first, caller-scoped sanitized operation events only. Never exposes raw messages, paths, identities, credentials, content, URLs, or stacks. |

`not_found` can mean absent or outside the current scope: do not try alternate identities. For rate limiting, reduce repeated calls. For `internal_error`, report only the returned request ID. A stale, expired, consumed, or confirmation-mismatch proposal must be prepared again; never reuse it.

A read-only connection exposes the eleven read, setup, discovery, and diagnosis tools above. A subscription-management connection adds only the four `prepare_*`/`apply_subscription_change` tools; diagnosis never requires write access.

Exact private-source example for public `r/codex`:

```json
{
  "source": {
    "mode": "private",
    "type": "reddit",
    "display_name": "r/codex",
    "config": {
      "subreddit": "codex",
      "sort": "hot",
      "time_filter": "day",
      "fetch_limit": 25,
      "min_score": 10
    }
  }
}
```

For a Bilibili UP 主, use this private envelope. Use the UP 主 name as
`display_name`; `config` must contain exactly the controlled identity plus the
optional latest-item flag:

```json
{
  "source": {
    "mode": "private",
    "type": "bilibili",
    "display_name": "食贫道",
    "config": {
      "site": "bilibili",
      "route_key": "user_video",
      "params": {"uid": "39627524"},
      "keep_latest_item": false
    }
  }
}
```

The UID must be a positive numeric value read from the user's explicit
`https://space.bilibili.com/<uid>` input. Never call Apify for Bilibili and
never ask for or submit an RSSHub URL, raw route path, Cookie, ACCESS_KEY, or
credential. The administrator-owned RSSHub Base URL is outside the MCP
contract. Existing Bilibili sources expose only a semantic `public_target`
with `site`, `route_key`, and `params`.

`get_item.presentation.content` keeps the compatibility fields and adds
`body_offset`, `body_end`, `body_total_chars`, `body_has_more`, and
`next_body_offset`. `body_has_more` describes whether another stored chunk is
available. On the final chunk, `body_truncated=true` means collection ended
before the complete original page was saved. In that case say “完整原文未保存在
Inteliscope”; do not claim that the complete webpage was read or fetched.
