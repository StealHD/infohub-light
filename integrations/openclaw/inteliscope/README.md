# Inteliscope OpenClaw Skill

This local Skill uses the current caller's Inteliscope MCP connection. Create the connection in Inteliscope Web “助手连接” first. A viewer/read-only connection can read and diagnose but cannot prepare or apply subscription changes; create a subscription-management connection in Web when the caller needs that access.

## Install

```bash
openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope
openclaw skills check
```

Save the one-time connection credential locally in `~/.openclaw/.env`, with mode `0600`:

```text
INTELISCOPE_MCP_TOKEN=<one-time connection credential>
```

Use the Web-generated MCP URL and an environment-variable reference, never a clear-text credential. Choose the configuration that exactly matches the access of the connection created in Web.

### Viewer/read-only connection

For a viewer/read-only connection, expose exactly the ten safe read, setup,
discovery, and diagnosis tools. These tools can explain state but cannot prepare
or apply a change:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job","get_source_setup_guide","list_available_sources","diagnose_source","diagnose_job"]}}'
```

### Subscription-management connection

Only for a subscription-management connection created in Inteliscope Web, expose all fourteen tools:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job","get_source_setup_guide","list_available_sources","prepare_create_subscription","prepare_update_subscription","prepare_delete_subscription","apply_subscription_change","diagnose_source","diagnose_job"]}}'
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
```

Do not set OAuth; 不要运行 `openclaw mcp login`。Do not put a credential in chat. If one is pasted, do not use or repeat it: rotate it in Web SecretStore, create a new Web connection if needed, update the local environment file, then revoke the old connection.
