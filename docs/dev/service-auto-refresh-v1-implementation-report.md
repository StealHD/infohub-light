# Service 自动获取与 Feed 新鲜度 v1 实现报告

日期：2026-07-11

## 状态

代码、API/UI 合同、Compose 配置、确定性测试和真实 Docker 发布验收均已完成。2026-07-11 使用现有管理员完成两个自动周期 canary：两个任务均为 `scheduled_service_refresh`、优先级 `-10`、状态 `succeeded`、各产出 21 条且各生成一个 snapshot；随后计划周期已从 1 小时切回 6 小时。

当前产品主线仍是订阅、抓取、Feed 展示与用户历史留存。自动链路未新增 dispatcher，也未启用 legacy scheduler、摘要、通知、Graph、Archive analytics、推荐或全局静态 Feed 发布。

## 当前实现证据

- `ServiceStore` 以 additive schema 提供 `user_feed_schedules`；缺 row 投影为默认关闭、6 小时。
- `FeedScheduleService` 实现允许周期、首次/改周期/关闭语义、明确 skip reason、5 分钟冲突延后、离线只补一个周期和 SQLite 原子到期入队。
- 用户降级为 viewer 时，用户更新事务会关闭计划并取消 queued 自动任务；调度 tick 同时以 `user_read_only` 防御性拒绝入队，running 任务不被越权抢断。
- 自动 job 复用 `user_feed_refresh`，固定 `reason=scheduled_service_refresh`、`priority=-10`；手动、多标签页和自动提交共享每用户唯一 active refresh 与原子配额事务。
- Worker 在普通 claim 前检查计划，主循环默认每 30 秒评估；两份 Compose 都把 `HORIZON_SCHEDULE_POLL_SECONDS=${HORIZON_SCHEDULE_POLL_SECONDS:-30}` 注入现有 Worker，默认服务仍只有 API + Worker。
- `GET/PATCH /api/me/feed-schedule` 返回计划、last/active job 和 Worker 状态；viewer 只读。`/api/ops/runtime` 返回 schedule 数量、逾期、下一次时间和最近统计。
- 订阅页显示自动更新卡片、固定周期、last/next/status/item count/partial/Worker 状态；首页“获取新内容”和订阅页“立即刷新”共用 job 轮询。已读只由显式点击写 Service API。
- 页面常驻时每 30 秒低频检查 schedule：发现新 active job 后复用现有 2 秒 job poll；若错过 running 状态但发现新的 terminal snapshot，也会重新加载 Feed 与新鲜度。
- watcher 与 job poll 对 terminal snapshot 使用单次处理/失败接管状态；Feed 只有明确加载成功后才标记完成。Feed、item state、config 和 schedule 请求绑定当前用户及 load generation，登出或切换用户时旧响应不能覆盖新用户页面。

## 已执行验证

1. TDD RED：新增 Compose schedule-poll 回归后，默认服务与 scheduler profile 断言通过，仅因两份 Worker block 缺 schedule poll 环境变量失败。
2. TDD GREEN：补齐两份 Compose 与 `.env.example` 后，`tests/test_light_runtime_scripts.py` 6 项通过。
3. `tests/test_feed_schedule.py tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_light_runtime_scripts.py` 目标回归通过；覆盖双连接竞争、禁用/viewer/无订阅/migration、quota/source-fetch 延后、手动并发去重、公开 job 脱敏和 ops 指标，并补充 viewer 角色降级的事务关闭与 tick 防御。
4. Node DOM 行为测试：23/23 通过；覆盖显式已读、schedule 卡、刷新去重、页面重载恢复 active job、常驻页面发现后续 active/terminal job、watcher/poll 单次处理、poll 失败接管、Feed 失败重试、旧用户慢响应隔离、认证切换取消屏障、partial 和 Feed 自动更新。
5. `docker compose -f docker-compose.yml config --quiet` 与 light 版本均退出 0；`docker-compose.light.yml` 已真实重建并只运行 `horizon-api + horizon-worker`，scheduler 未运行，live/ready 均返回 200。
6. Docker 运行观测：最终重建后 Worker heartbeat age 为 0.98 秒，`overdue_schedule_count=0`、`stale_running_count=0`、无 queued job，下一次计划时间为切回 6 小时后的时间点。
7. 发布前创建一致性备份 `data/backups/service-auto-refresh-v1-20260711T083926Z.db`，权限 `0600`，备份与运行库 `PRAGMA integrity_check=ok`，运行库无外键错误。
8. 两用户、两周期隔离 E2E 使用独立临时数据库与本地私有 RSS：4 个 scheduled job 均唯一、每 job 一个 snapshot、两用户最新 Feed ID 交集为 0，且未创建或修改全局静态 Feed/Graph 文件。
9. 浏览器验收：Feed 显示 21 条和相对更新时间，首篇保持“标记已读”而非自动已读；订阅页显示自动刷新已开启、周期 6 小时、最近任务成功、Worker ready；Graph、站内预览和三个偏好反馈入口均不存在，控制台无错误。
10. 最终完整 pytest：551/551 通过；Python 编译、全部静态 JS `node --check`、两份 Compose 解析和 `git diff --check` 均通过。
11. 当前安装的 init-pro v0.3 只接受 schema 3 `project-controls.json`，本仓库仍使用 schema 2 `project-defaults.yaml`；本期未把控制面迁移混入功能发布，并保留既有兼容验证报告。该工具版本差异不影响 API、Worker、数据库或 UI 运行验收。

## 发布记录

```text
release_revision: d0c8905 + preserved working-tree changes on feature/multi-user-mvp-core
deployed_at_utc: 2026-07-11T09:29:22Z (final rebuild)
compose_variant: docker-compose.light.yml
default_running_services: horizon-api, horizon-worker
legacy_scheduler_running: false
worker_heartbeat_age_seconds: 0.98
enabled_schedule_count: 1
overdue_schedule_count: 0
stale_running_count: 0
oldest_queued_age_seconds: none
canary_label: existing_admin_canary
canary_interval_minutes: 60 for two cycles, then 360
cycle_1_job_status/item_count/snapshot_count: succeeded / 21 / 1
cycle_2_job_status/item_count/snapshot_count: succeeded / 21 / 1
cross_user_feed_id_intersection_count: 0 (isolated two-user/two-cycle E2E)
schedule_disable_semantics: automated tests passed; live canary intentionally remains enabled at 360 minutes
rollback_readiness_result: backup readable, mode 0600, integrity_check ok
```

第二周期通过受控地把 `next_run_at` 提前到当前时间触发，以避免真实等待一小时；周期推进和离线仅补一个任务的语义由独立两周期 E2E 验证。该操作只改变 canary 的下一次到期时间，任务仍由真实 Docker Worker 的正常 30 秒调度路径创建和执行。

## 发布后观察

- 保持管理员计划为 6 小时，继续观察 heartbeat、队列年龄、`partial/failed` 来源和 snapshot 增长。
- 下一期只考虑来源健康状态与失败诊断；Graph、Archive analytics、推荐、摘要和推送仍不进入当前产品范围。
