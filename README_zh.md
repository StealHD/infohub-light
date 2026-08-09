# Inteliscope

Inteliscope 是基于 Horizon 演进的小团体多人信息中心。当前产品主线保持聚焦：订阅来源、获取新内容、阅读用户隔离的 Feed，并保留可搜索的 Feed 历史。

[English](README.md) · [API 合同](docs/contracts/api/) · [架构合同](docs/contracts/architecture/) · [UI 合同](docs/contracts/ui/)

## 当前能力

- `owner/admin/member/viewer` 多角色账户与用户隔离。
- Public、workspace、private 来源目录和每用户订阅。
- RSS/Atom、GitHub、Reddit、Telegram、Hacker News、OpenBB 与受控 Apify social 获取。
- 手动刷新、每用户 Feed 周期和每订阅单源周期共用 SQLite Worker 队列。
- Feed、收藏、稍后读、显式已读/未读、忽略、历史搜索、正文详情、鉴权媒体和 Source Health。
- 当前 Email、Webhook、Telegram Service 通知与每来源 opt-in。
- Owner/Admin 通过 SecretStore 管理 write-only AI、Apify 与通知凭据。
- 可选 Remote MCP `/mcp`，向每位用户自己的 OpenClaw 提供用户隔离的安全读取、诊断与受控订阅写入。

Graph、archive analytics、推荐学习、站内网页代理、日报发布、旧静态站、本地 stdio MCP 与旧 scheduler 已退役，不再作为兼容运行面。

## 运行拓扑

默认和正式部署都只有两个服务：

```text
horizon-api     FastAPI、React、认证、Service API 与 Remote MCP
horizon-worker  来源获取、Feed finalization、周期计划、通知与 Source Health
```

所有自动计划都由 `horizon-worker` 执行，不存在 scheduler profile、第三个 dispatcher 或旧 publisher 容器。React 是唯一 UI；若构建产物缺失，API 与 `/mcp` 仍可启动，非 API 页面返回 404，不会回退旧静态 UI。

## 本地 Docker 启动

```bash
cp .env.example .env

# Fresh DB 首次启动前设置 Owner：
# HORIZON_AUTH_USER=admin
# HORIZON_AUTH_PASSWORD_HASH=...

./scripts/up-latest.sh
docker compose -f docker-compose.light.yml ps
curl http://127.0.0.1:8080/api/health/live
curl http://127.0.0.1:8080/api/health/ready
```

打开 [http://127.0.0.1:8080/](http://127.0.0.1:8080/)，登录后创建或订阅来源，再选择“获取新内容”。

在任务 Worktree 中运行 `up-latest.sh` 时，脚本会使用当前 Worktree 作为构建上下文，并从主 checkout 挂载 `.env`、`data` 和 `logs`。只有明确需要其他运行根目录时才使用 `--runtime-root /absolute/path`；`--dry-run` 可只检查解析结果。

API 与 Worker 日志位于私有、UTC 每日轮转的 JSONL 文件，默认保留 30 天；前端不展示日志正文。参见[可观测性开发文档](docs/dev/observability-logging.md)。

## 前端开发

```bash
cd frontend
npm ci
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
npm run e2e:release
```

Vite 开发服务器默认把 `/api` 代理到 `127.0.0.1:8080`。历史书签 `/?view=`、`/later`、`/settings/legacy` 只做 React 客户端重定向，不依赖旧 UI 文件。

## 认证与密钥

多人 Service API 始终要求登录，不能通过环境开关关闭。Fresh DB 未配置 Owner 时 readiness 返回 `auth_not_configured`，不会开放匿名访问。HTTPS 部署使用：

```bash
HORIZON_AUTH_SECURE_COOKIE=true
HORIZON_AUTH_SESSION_TTL_SECONDS=604800
```

Fresh DB 可通过 `HORIZON_AUTH_PASSWORD` 或 `HORIZON_AUTH_PASSWORD_HASH` 引导第一个 Owner。生成 PBKDF2 hash：

```bash
uv run python -m src.auth hash-password
```

AI、Apify 和通知真实凭据只写入 Git/Docker 忽略的 `data/secrets.env`，权限为 `0600`；API 响应、浏览器缓存、日志、Job 和 `data/config.json` 不得包含真实值。

## OpenClaw 与 Remote MCP

Remote MCP 默认关闭，不在服务器运行 Agent 或模型。启用示例：

```bash
HORIZON_REMOTE_MCP_ENABLED=true
HORIZON_REMOTE_MCP_PUBLIC_URL=http://127.0.0.1:8080/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_OPENCLAW_CHAT_ENABLED=false
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789
```

本地集成使用幂等引导：

```bash
./scripts/setup_openclaw_local.sh --dry-run
./scripts/setup_openclaw_local.sh
```

然后在 `/agents` 创建连接并按页面生成的配置接入。仓库只提供 FastAPI `/mcp`，不再提供 `horizon-mcp` 或本地 stdio server。详细说明见 [`integrations/openclaw/inteliscope/README.md`](integrations/openclaw/inteliscope/README.md)。

## 配置与数据边界

`data/config.json` 继续作为当前 AI、过滤、RSSHub、标签和来源导入输入。历史文件中已存在的 `email`、`webhook`、`premium_analysis`、`article_graph` 块会原样保留，但不再通过 API 返回，也不会由现役代码执行或改写。

以下历史数据属于 operator-owned inert artifact：

- `data/site/**`
- `data/horizon.db`
- 旧 summaries
- 旧本地 MCP run
- 既有 feedback 表和行

当前 API、Worker、React、Remote MCP、初始化与迁移都不读取、迁移、改写或物理删除这些数据。Fresh DB 不再创建 feedback 表。`data/archives/**` 是现役冷归档，`data/service.db` 的 snapshot 双读兼容也继续保留。

## 发布

正常升级从与 `origin/main` 完全一致的干净 `main` 执行：

```bash
./scripts/release_vps.sh preflight vX.Y.Z
./scripts/release_vps.sh release vX.Y.Z
./scripts/release_vps.sh status
./scripts/release_vps.sh rollback [release-id]
```

镜像必须在本地以固定 revision 构建并验证 `linux/amd64`，VPS 只执行 `docker load`，不得构建仓库。切换前脚本检查活跃 Job，并在发现残留历史 scheduler 容器时阻断发布。普通升级失败回滚到上一不可变 API/Worker release。

`scripts/release_rc1.sh` 只负责首次空数据库引导。失败时它只停止新 API/Worker 容器并保留诊断数据，不恢复已退役的 Web 服务。

## 验证

```bash
python scripts/test_gate.py run --mode full
python scripts/test_gate.py run --mode release
git diff --check
```

测试门禁不会运行真实来源、AI、付费 Actor、通知发送或 scheduler。

Inteliscope 源自 [Thysrael/Horizon](https://github.com/Thysrael/Horizon)，继续采用 MIT License。
