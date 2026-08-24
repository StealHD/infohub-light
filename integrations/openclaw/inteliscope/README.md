# Inteliscope OpenClaw Skill

This local Skill uses the current caller's Inteliscope MCP connection. Create the connection in Inteliscope Web “助手连接” first. A viewer/read-only connection can read and diagnose but cannot prepare or apply subscription changes; create a subscription-management connection in Web when the caller needs that access.

Diagnostics default to the connection owner's own safe events. An Owner/Admin may explicitly enable workspace diagnostics only while creating a new connection; existing connections are never upgraded, and a later role downgrade blocks workspace queries immediately. Workspace diagnosis still exposes only bounded sanitized events, requires a request/job/source/subscription ID or warning/error level, and never grants access to another user's business data or permission to repair anything.

## Install

```bash
openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope --force
openclaw gateway restart
openclaw skills check
```

Re-run `./scripts/setup_openclaw_local.sh` after updating Inteliscope. It
compares the installed managed Skill with the bundled files, refreshes a stale
copy with `--force`, and restarts a running Gateway only when the Skill or
allowed Origin changed. Start a new OpenClaw conversation after a Skill refresh
so an existing transcript cannot preserve obsolete routing instructions.

Save the one-time connection credential locally in `~/.openclaw/.env`, with mode `0600`:

```text
INTELISCOPE_MCP_TOKEN=<one-time connection credential>
```

Use the Web-generated MCP URL and an environment-variable reference, never a clear-text credential. Choose the configuration that exactly matches the access of the connection created in Web.

### Viewer/read-only connection

For a viewer/read-only connection, expose exactly the thirteen safe read, setup,
public-account lookup, discovery, and diagnosis tools. These tools can explain state but cannot prepare
or apply a change:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job","get_source_setup_guide","search_bilibili_users","resolve_source","list_available_sources","diagnose_source","diagnose_job","query_operation_logs"]}}'
```

### Subscription-management connection

Only for a subscription-management connection created in Inteliscope Web, expose all seventeen tools:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job","get_source_setup_guide","search_bilibili_users","resolve_source","list_available_sources","prepare_create_subscription","prepare_update_subscription","prepare_delete_subscription","apply_subscription_change","diagnose_source","diagnose_job","query_operation_logs"]}}'
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
```

### Admin system-settings connection

Only for an Owner/Admin system-settings connection created in Inteliscope Web,
expose the thirteen read tools plus the three system-settings tools. This
connection does not include subscription mutations:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job","get_source_setup_guide","search_bilibili_users","resolve_source","list_available_sources","diagnose_source","diagnose_job","query_operation_logs","list_system_settings","prepare_update_system_settings","apply_system_settings_change"]}}'
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
```

Do not set OAuth; 不要运行 `openclaw mcp login`。Do not put a credential in chat. If one is pasted, do not use or repeat it: rotate it in Web SecretStore, create a new Web connection if needed, update the local environment file, then revoke the old connection.

When Inteliscope enables browser chat, the Web page connects directly to the
user's OpenClaw Gateway. The Gateway token and the Inteliscope MCP token are
different credentials: the Gateway token is entered only in the browser pairing
dialog, while `INTELISCOPE_MCP_TOKEN` remains only in the local OpenClaw env
file. Neither credential belongs in an Agent conversation.
