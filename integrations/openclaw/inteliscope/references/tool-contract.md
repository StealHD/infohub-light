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

`not_found` can mean absent or outside the current scope: do not try alternate identities. For rate limiting, reduce repeated calls. For `internal_error`, report only the returned request ID. A stale, expired, consumed, or confirmation-mismatch proposal must be prepared again; never reuse it.

A read-only connection exposes the ten read, setup, discovery, and diagnosis tools above. A subscription-management connection adds only the four `prepare_*`/`apply_subscription_change` tools; diagnosis never requires write access.

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

For a Bilibili UP 主, use the same private envelope with `type="rss"` only
after the user supplies the full public feed URL from their self-hosted RSSHub.
Use the UP 主 name as `display_name` and put `url`, optional `name`, and optional
`keep_latest_item` inside `config`. Never call Apify for Bilibili. If the RSSHub
URL is local/private/authenticated, direct the user to create it in Web and then
use the returned visible existing source ID.

When the user explicitly names an existing Bilibili RSS source as a route
template, list RSS sources with `unsubscribed_only=false`, match its returned
name, and reuse only its public HTTPS `public_target`. Replace only a separately
supplied numeric Bilibili UID; never copy the template UID or infer one from an
account name. `web_setup_required` is not a reusable target.

`get_item.presentation.content` keeps the compatibility fields and adds
`body_offset`, `body_end`, `body_total_chars`, `body_has_more`, and
`next_body_offset`. `body_has_more` describes whether another stored chunk is
available. On the final chunk, `body_truncated=true` means collection ended
before the complete original page was saved. In that case say “完整原文未保存在
Inteliscope”; do not claim that the complete webpage was read or fetched.
