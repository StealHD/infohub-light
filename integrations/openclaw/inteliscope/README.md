# Inteliscope OpenClaw Skill

This local Skill lets OpenClaw use the current user's read-only Inteliscope MCP connection. Create a connection on Inteliscope's “助手连接” page first; the clear-text credential is shown once.

## Install

```bash
openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope
openclaw skills check
```

Save the one-time value locally in `~/.openclaw/.env`:

```text
INTELISCOPE_MCP_TOKEN=<一次性令牌>
```

Set the file mode to `0600`. Configure the MCP server with the URL shown by Inteliscope and an environment-variable reference, never a clear-text credential:

```bash
openclaw mcp set inteliscope '{"url":"<MCP_URL>","transport":"streamable-http","connectTimeout":10,"timeout":30,"supportsParallelToolCalls":true,"headers":{"Authorization":"Bearer ${INTELISCOPE_MCP_TOKEN}"},"toolFilter":{"include":["get_my_feed","get_item","list_subscriptions","source_health","list_jobs","get_job"]}}'
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
openclaw dashboard
```

不要设置 OAuth，也不要运行 `openclaw mcp login`。如果凭证丢失或泄露，请创建新连接、更新本地环境文件，再永久吊销旧连接。
