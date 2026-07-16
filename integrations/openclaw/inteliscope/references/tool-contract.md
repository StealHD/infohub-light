# Tool contract

All tools are read-only, idempotent, closed-world reads. The MCP connection fixes the caller's identity and only returns that person's data.

| Tool | Inputs | Use | Important output boundaries |
|---|---|---|---|
| `get_my_feed` | `collection` (`latest`, `history`, `saved`, `later`), `limit` 1–50, `offset`, `hide_ignored`, `unread_first` | Browse a bounded collection | Presentation v1 only; no full body, media, raw metadata, or legacy reason |
| `get_item` | `article_id`, `max_body_chars` 1–8000 | Read one user-selected item | Presentation v2 with bounded plain-text body and truncation status |
| `list_subscriptions` | `include_disabled` | Inspect source name/type, effective channel/topics, state, analysis mode, priority, and schedule | No personal tags, source configuration, or secret references |
| `source_health` | none | Inspect source-health summary and safe issue information | Uses the same safe projection as Inteliscope UI |
| `list_jobs` | optional `status`, `limit` 1–50 | Browse current user's jobs | No worker, lock, claim credential, payload, owner identity, or raw result |
| `get_job` | `job_id` | Inspect one selected job | Same fixed safe summary as the job list |

`not_found` means either the identifier does not exist or it is outside the current connection's scope. Do not try alternate identities. Treat `rate_limited` as a signal to reduce repeated calls. For `internal_error`, report the returned request ID without guessing at hidden details.
