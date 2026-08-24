# Inteliscope 使用说明

这份说明面向日常使用和小范围分享。当前部署入口为 `https://rb.jiefs.top/`，本地默认入口为 `http://127.0.0.1:8080/`。

## 1. 登录与角色

Service API 始终要求应用账号登录。角色分为 `owner/admin/member/viewer`：

- Owner/Admin 管理成员、工作区来源、AI/Apify Key、通知服务、ActorOps 与存储治理。
- Member 管理自己的 private 来源、订阅、Feed 状态和允许的 Agent 连接。
- Viewer 可阅读自己的 Feed、历史、来源和运行记录，但不能执行写操作。

Nginx Basic Auth 只能作为可选外层门禁，不能替代应用登录和角色权限。

## 2. Feed、收藏与历史

主要页面为：

- `/feed`：当前用户时间窗口内的 Feed，支持时间流和来源概览。
- `/saved`：收藏与稍后读集合；历史 `/later` 会重定向到这里。
- `/history`：当前 Feed 窗口之前的稳定内容。
- `/subscriptions`：我的订阅、来源库和运行记录。
- `/agents`：Remote MCP delegation 与浏览器 OpenClaw 连接。
- `/settings/*`：通知、AI、获取、忽略、密钥、ActorOps 和存储治理。

选中或打开条目不会自动标记已读。收藏、稍后读、忽略和已读/未读只修改当前用户的 item state。Feed 搜索覆盖当前窗口、在线历史和现役冷归档元数据，但不会把旧内容移回 Feed。

右上角“重新载入”只读取最新投影；“获取新内容”创建或复用 `user_feed_refresh` Job。任务完成后页面重新读取 Feed，同一账号重复提交不会创建并发刷新。

## 3. 来源与计划

来源可见范围为 public、workspace 或 private。创建来源后可订阅；订阅 shared 来源不会改变其他用户，最后一个 private owner 取消订阅时会软停用无人引用来源。

自动计划全部由现有 Worker 执行：

- 每用户 Feed 周期：1/3/6/12/24 小时，默认关闭。
- 每订阅单源周期：30 分钟或 1/3/6/12/24 小时，默认跟随全局。

它们创建普通 `user_feed_refresh` 或 `source_fetch` Job，共用去重、配额、Source Health、Feed finalization 和通知规则。没有 scheduler 服务或 profile。

## 4. 通知服务

`/settings/notifications` 使用统一“通知服务”界面：

- Owner/Admin 创建和维护 workspace Email、Webhook、Telegram 服务。
- 目的地和凭据只在写请求中出现，提交后不回显。
- `保存并测试` 只发送一次明确的模拟消息；成功后启用该 service generation。
- 用户在“个人新内容通知”中选择服务，并在订阅卡片上逐源 opt-in。

首份 snapshot、历史复用内容、通知关闭期间发现的内容都不补发。通知失败不会改变 Feed 或重跑来源获取。

## 5. 设置与密钥

Owner/Admin 可在原生设置页管理：

- AI Key、Provider/Model 和安全输入输出上限。
- RSSHub Base URL、获取窗口与主题库。
- Apify Key Pool、ActorOps、发现与付费 Canary 审批。
- 存储概览、标准清理、冷归档与恢复。

真实 Key、Token、Webhook URL、SMTP 密码和 Chat ID 只写入 `data/secrets.env`，权限为 `0600`；页面、API、日志、Job 和数据库只保存安全引用/摘要。

## 6. OpenClaw 与 Remote MCP

`/agents` 可创建当前用户自己的 delegation。Read 连接只访问该用户的安全 Feed、来源、健康、Job 和脱敏诊断；受控订阅写入需要单独选择权限、服务端开关和实时角色校验。

浏览器 OpenClaw 对话是另一条 opt-in 连接，浏览器直接连接用户自己的 Gateway；Inteliscope 不代理 Gateway，也不保存 bootstrap token。Remote MCP 的唯一服务端入口是 `/mcp`，仓库不再提供本地 stdio MCP。

## 7. 数据边界

当前 latest/history/search 真源是 `data/service.db`。Service DB 继续双读既有完整 snapshot 与 compact snapshot；现役冷归档位于 `data/archives/**`，由 `/api/admin/storage/*` 管理。

以下历史数据已经停止读写，但本次退役不会物理删除：

- `data/site/**`
- `data/horizon.db`
- 旧 summaries
- 旧本地 MCP run
- 既有 feedback 表和行

Fresh DB 不再创建 feedback 表。旧 `/api/archive/{graph,items,trends,facets,source-quality}` 与 feedback POST 已删除，访问时返回统一 404，OpenAPI 不再列出。

`data/config.json` 中历史 `email/webhook/premium_analysis/article_graph` 块会原样保留在磁盘，但 API 不返回、现役代码不执行、配置 action 不改写。

## 8. 管理员运维

查看服务与日志：

```bash
ssh vps-tokyo
cd /opt/inteliscope/current
docker compose ps
docker compose logs -f horizon-api horizon-worker
```

正常发布从本地、干净且与 `origin/main` 一致的 `main` 执行：

```bash
./scripts/release_vps.sh preflight vX.Y.Z
./scripts/release_vps.sh release vX.Y.Z
./scripts/release_vps.sh status
./scripts/release_vps.sh rollback [release-id]
```

镜像必须在本地构建并验证 `linux/amd64`，VPS 只执行 `docker load`。切换前脚本检查活跃 Job，并在发现残留历史 scheduler 容器时阻断。普通发布失败回滚到上一不可变 API/Worker release；包含数据库迁移的版本必须走独立 runbook。

ActorOps Global 31 是独立停机迁移：停止 API/Worker 后，先只读检查，再显式应用；它不会调用 Actor 或真实来源。

```bash
.venv/bin/python scripts/migrate_actorops_v2_resilience.py --data-dir data
.venv/bin/python scripts/migrate_actorops_v2_resilience.py --data-dir data --apply
```

应用会创建 `0600` 备份并验证完整性和外键。迁移完成前，只有 ActorOps 来源和管理链路提示需要迁移；普通 RSS/GitHub 不受影响。

首次空数据库只使用 `scripts/release_rc1.sh`。失败时停止新 API/Worker 并保留诊断数据，不恢复旧 Web。

## 9. 本地启动与验证

```bash
cp .env.example .env
./scripts/up-latest.sh
curl http://127.0.0.1:8080/api/health/live
curl http://127.0.0.1:8080/api/health/ready
```

全量验证：

```bash
python scripts/test_gate.py run --mode full
python scripts/test_gate.py run --mode release
git diff --check
```

门禁不会运行真实来源、AI、付费 Actor、通知发送或 scheduler。
