# 多人 Feed v2 实施报告

日期：2026-07-11
状态：Feed v2 显式迁移、Docker 运行验证与浏览器验收已完成；进入发布后观察。

## 1. 结论

本期功能可以实际产出多人 Feed。Service Worker 已不再通过全局 `data/site/*.json` 交换 Feed 结果，用户刷新、单源抓取、部分失败保留、空结果、任务重试和并发提交均由用户作用域 snapshot v2 完成。

2026-07-11 已在真实 Service 数据库上完成显式 Feed v2 迁移。迁移前先执行只读预检；首次 `--apply` 因检测到活跃 Worker heartbeat 而安全拒绝，等待 35 秒 stale 阈值后再次执行成功。随后完成备份、双库完整性/外键检查、Docker API + Worker 启动、管理员刷新和浏览器验收。后续新环境或其他旧库仍必须按显式迁移流程操作，应用不会自动清空数据。

## 2. 已交付能力

| 领域 | 交付结果 |
| --- | --- |
| 结构化产出 | 新增不可变 `FeedRunResult`、`SourceOutcome`、`RunIssue`；`HorizonOrchestrator.execute()` 只做抓取、去重和分析。 |
| 旧链路兼容 | CLI/scheduler 的静态站、摘要、Graph 和通知副作用集中到 `LegacyPublisher`，原 `run()` 入口保留。 |
| 用户 Feed | `FeedProductionService` 统一全量替换、失败来源保留、取消订阅清理、成功空 snapshot 和单源合并；跨源去重保留完整 provenance。 |
| 失败语义 | 来源异常不再折叠为空列表；支持 `succeeded/partial/failed`，全部失败不生成 snapshot，partial 不自动重试。 |
| 私人内容 | `personal_only` 进入个人 Feed但跳过 AI、精选和推送；同 URL 混合来源采用 most-restrictive-wins。 |
| 队列可靠性 | 原子 claim、`claim_token`、lease、10 秒 heartbeat、35 秒 stale、过期 claim 拒绝、snapshot/items/job 同事务。 |
| 重试幂等 | terminal job 手动重试沿用同一 job 时，新的 run 原子替换已有 snapshot 内容，不产生第二个 snapshot。 |
| SQLite | 每线程独立 connection，统一 foreign keys、WAL、busy timeout；同用户并发 source fetch 不丢更新。 |
| 权限与隔离 | 全局 AI/过滤/标签/Webhook 仅 owner/admin 可写；member source 标签只写 source/subscription；Graph 固定返回用户作用域安全空降级。 |
| RSS 安全 | 成员 URL 拒绝占位符和 userinfo；逐跳解析并固定连接公网 IP，保留 Host/SNI，禁代理/跨域连接复用，响应流式限制 2 MB。 |
| Catalog | 同一操作者重复/并发 POST 按 `source_key` 原子幂等；跨用户 private key 和 PATCH key 碰撞返回结构化 409。 |
| 运行时 | 默认 Compose 服务为 API + Worker，scheduler 仅显式 profile；新增 live/ready/ops，未配置用户时 ready 返回 `auth_not_configured`。 |
| UI | 创建任务立即禁用控件；2 秒轮询、180 秒上限、3 次网络失败停止；reload 恢复任务并精确禁用所有当前用户 active job 控件。 |
| 迁移 | 提供并实际执行只读预检与显式 `--apply`：活跃 heartbeat 会安全拒绝；成功后完成备份、旧 Feed/state/feedback 清理、约束与 marker 写入、完整性和外键检查。 |

## 3. 最终审查补出的关键边界

最终审查不只做静态确认，还补了可复现测试并修复以下问题：

1. lease 已过期但尚未 requeue 时仍可 finalize；现已按 `locked_until` 拒绝并回滚未提交 snapshot。
2. partial job 重试会直接返回旧 snapshot；现以新 `run_id` 原子替换 payload 和 items。
3. 只有旧 state/feedback 或待执行 Feed job 时会绕过迁移；现都计入 migration gate。
4. 无订阅用户和非 HN 单源任务会继承全局 Hacker News；现已强制关闭非 catalog 来源。
5. 同 URL 的 full 与 personal-only 合并后可能进入 AI；现以最严格模式为准。
6. Hacker News 子请求及 Reddit fallback 错误会伪装成成功空结果；strict 模式现明确上抛。
7. RSS 仅预解析域名仍有 DNS rebinding 窗口；现使用已审核 IP直接建连，并隔离连接池和代理。
8. 重复 catalog POST 会触发 SQLite IntegrityError/500；现为事务安全幂等写入和统一冲突响应。
9. 页面只跟踪一个 active job，切换任务后旧按钮可能重新可点；现结合持久化 jobs 列表禁用全部匹配控件。
10. 同 URL A+B 去重后只保留 primary `source_id`，连续 partial 会丢失失败来源内容；现持久化 `source_ids/subscription_ids/source_keys`，覆盖时继续合并失败 provenance。
11. URL query 被去重键忽略，不同 `?id=` 文章可能误合并；现 query identifier 属于内容身份。
12. 管理员导入旧配置可覆盖成员 private source；现 scope/owner/type 不兼容时跳过并返回 `source_key_conflict`。
13. member 兼容 source action 会提前回写全局 tags/personal_tags；现成员标签只落 source/subscription，管理员全局写入也排在 catalog 成功之后。

## 4. 验证证据

- 完整 pytest：519 项全部通过。
- 真实本地 RSS Worker E2E：两个用户顺序和并发刷新均隔离；连续 20 个确定性任务无串用户、重复 snapshot 或外键错误。
- 浏览器闭环：登录后确认默认入口不再包含 Graph、站内预览和偏好反馈操作；历史空态显示正确。
- Node UI 行为测试：5/5，通过请求顺序、管理员成员映射、任务恢复和 UI 范围收口验证。
- Python 全量编译检查：通过。
- 全部前端 JS `node --check`：通过。
- Docker 运行验证：默认仅启动 API + Worker，scheduler 未进入默认服务集。
- `git diff --check`：通过。
- init-pro backend strict：59 PASS，0 WARN，0 FAIL。
- 两路 post-fix 只读复审重新执行 provenance 与授权原始复现，最终结论均为 READY，无残留 Critical/Important finding。

发布运行验证由 Docker API + Worker 完成。管理员触发刷新任务后状态按 `queued → running → succeeded` 收敛，最终生成 22 个 Feed items；浏览器自动加载 Feed，入口清理和历史空态均验收通过。

## 5. 真实数据库显式迁移实绩

只读命令：

```bash
./.venv/bin/python scripts/migrate_user_feed_v2.py \
  --data-dir data \
  --backup-dir data/backups
```

2026-07-11 实际执行结果：

1. 只读预检确认需要迁移，旧数据包括 7 个 snapshots、140 个 items、1 条 item state 和 11 条 feedback。
2. 首次 `--apply` 检测到活跃 Worker heartbeat，按安全门禁拒绝修改数据库。
3. 等待 35 秒 stale 阈值后再次执行，迁移成功。
4. 生成备份 `data/backups/service-20260711T040241615616Z.db`，文件 mode 为 `0600`。
5. 主库与备份库的 `PRAGMA integrity_check` 均为 `ok`，迁移后 `PRAGMA foreign_key_check` 返回 0 条。
6. 清理计数为 snapshots 7、items 140、state 1、feedback 11；migration marker 和 v2 约束写入完成。

## 6. 发布与运行验收

本次实际发布按以下顺序完成：

1. 先执行只读预检，再执行显式迁移：

   ```bash
   ./.venv/bin/python scripts/migrate_user_feed_v2.py \
     --data-dir data \
     --backup-dir data/backups \
     --apply
   ```

2. 首次因 heartbeat 安全拒绝后等待 stale 阈值，再次运行并核对备份、清理计数、完整性与外键。
3. 启动 Docker API + Worker，确认默认服务集中没有 scheduler。
4. 管理员在订阅页触发刷新，任务由 `queued` 进入 `running`，最终 `succeeded` 并生成 22 个 items。
5. 浏览器验证阅读入口已移除 Graph、站内预览和偏好反馈；打开原文、标记已读、复制摘要、收藏、稍后读和忽略仍可用。
6. 验证迁移后的首次历史为空态正常，不回退到全局 `history-data.json` 或 legacy archive。

通用约束不变：不要在活跃 API/Worker 上强行绕过 `--apply` 安全门禁；其他数据库仍需独立预检、备份和显式迁移。只有确认数据库损坏时才恢复备份。

## 7. 本期明确不交付

- 用户级 Archive/Graph；Graph API 目前安全降级为空。
- 个人摘要和个人推送。
- PostgreSQL、多 workspace 和复杂前端工程化。

## 8. 工作区状态

实施保留了进入任务时已有的未提交修改，没有执行 reset、checkout、覆盖性清理、commit、push 或 PR。发布前应由维护者审阅当前 diff，按项目流程拆分提交。
