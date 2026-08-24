# Remote MCP 只读发布运行手册

本手册只说明已启用的 Remote MCP 如何随标准 Service 版本安全发布。当前唯一升级路径是 `scripts/release_vps.sh`：VPS 只接收已验证的 `linux/amd64` 镜像并执行 `docker load`，**不得在 VPS 构建、编译或测试本仓库**。旧 API-only/RC1 手册原文位于 `archive/project-history/runbooks/remote-mcp-readonly-rollout-v1.md`，不得执行。

## 1. 固定边界

- Remote MCP 默认关闭；订阅与系统参数写入分别保持 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`、`HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED=false`。
- 正常 Service 仍运行 API + Worker，scheduler 必须停止；不要为 Remote MCP 设置 `HORIZON_REQUIRE_WORKER_FOR_READINESS=false`。
- Bearer delegation、设备 token、MCP token 和 `.env` 值不得进入命令行、聊天、Git、日志或截图。
- Nginx 仅允许在现有 HTTPS server 中最小加入 `location = /mcp` 和现有 rate-limit 模板；不得覆盖整个 server block 或改变其他站点路由。

## 2. 配置与权限

通过受控的 VPS canonical `.env` 配置以下非秘密项，并让公开地址与 Nginx 的精确 HTTPS Origin 一致：

```text
HORIZON_REMOTE_MCP_ENABLED=true
HORIZON_REMOTE_MCP_PUBLIC_URL=https://rb.jiefs.top/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED=false
HORIZON_AUTH_SECURE_COOKIE=true
```

只为 canary 用户创建 read delegation；该连接只能获得读 scope。不得创建写 scope、不得开启订阅写开关，也不得授予工作区诊断，除非相应角色和单独授权均已通过。

先以 Nginx 配置校验确认精确 `/mcp` 路由、`Authorization` 透传、256 KiB body 上限和 rate limit；确认配置变更不会把请求回退到旧 SPA HTML。再 reload Nginx，**不得整份覆盖当前 Nginx server block** 或替换线上配置。

## 3. 标准发布与 canary

从干净、与 `origin/main` 完全一致的本地 `main` 发布：

```bash
./scripts/release_vps.sh preflight vX.Y.Z
./scripts/release_vps.sh release vX.Y.Z
```

该脚本会复用精确 main SHA 的成功 Test Gate、本地构建和验证镜像、上传镜像/源包、等待 Tag smoke，并在 VPS 上验证 API、Worker、scheduler 停止、备份、readiness 与前端 revision。迁移版本必须先完成对应的显式迁移流程；普通发布会拒绝隐式迁移。

发布完成后，在本地受限环境变量中提供 canary 用户的 URL 和一次性 read token，运行：

```bash
./.venv/bin/python scripts/remote_mcp_read_canary.py verify
./.venv/bin/python scripts/remote_mcp_read_canary.py expect-unauthorized
```

验收结果必须证明：读工具可用、跨用户/跨工作区不能读取、无 token 返回 401、订阅写入保持 `subscription_writes_disabled`。canary 不运行抓取、AI、付费 Actor、Worker 操作或 scheduler，也不向更多用户扩展 allowlist。

## 4. 观察与回滚

至少观察 24 小时：API/Worker readiness、MCP 401/403 比例、脱敏 operation event、队列积压、source/AI/付费调用均应没有由 canary 引入的异常。只有经过单独授权才可扩大用户或评估写入能力。

出现权限、路由或可用性异常时，将 `HORIZON_REMOTE_MCP_ENABLED=false`，保持两个写 flag 为 false，并使用标准回滚：

```bash
./scripts/release_vps.sh rollback [release-id]
./scripts/release_vps.sh status
```

回滚后复核 `/mcp` 不再暴露、API/Worker readiness 正常且 scheduler 仍停止。不要通过 VPS 本地构建、API-only 临时切换或恢复旧 RC1 脚本来处置问题。
