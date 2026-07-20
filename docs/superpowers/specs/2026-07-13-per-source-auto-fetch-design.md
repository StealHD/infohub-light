# Inteliscope 订阅级自动抓取设计 v1

日期：2026-07-13

## 目标

在保留用户整份 Feed 每 6 小时自动刷新的同时，为单个订阅提供独立自动抓取能力。本期将 `X · @thsottiaux` 配置为每 30 分钟抓取一次、每次最多保留 1 条内容。

该能力继续复用现有 Service Worker、`source_fetch`、Feed v2 finalizer、配额、任务轮询和来源健康状态，不增加容器，不调用 legacy scheduler、静态 Feed、摘要、通知或 Graph 链路。

## 用户语义

- 用户级 `user_feed_refresh` 保持每 6 小时执行，覆盖 Apple、OpenAI、Claude 和 X。
- X 订阅额外启用订阅级自动抓取，周期为 30 分钟，`fetch_limit=1`。
- Scweet Actor 的 `max_items` 最小值为 100；上游请求按 100 执行，Inteliscope 在解析后只保留最新 1 条。Apify 成本按 Actor 实际执行量计算。
- 订阅级任务使用现有 `source_fetch` 合并语义，只更新目标来源，不替换其他来源内容。
- 成功但没有新内容仍记为成功，并更新来源健康和下一次执行时间。
- 相同推文继续按现有 `article_id` 去重，不在 Feed 中生成重复文章。
- 停用或取消订阅时不再创建新的订阅级任务；已经 running 的任务允许完成。

## 数据模型

新增 additive 表 `user_source_schedules`：

```text
subscription_id       PRIMARY KEY
workspace_id          NOT NULL
user_id               NOT NULL
source_id              NOT NULL
enabled                BOOLEAN DEFAULT false
interval_minutes       30 | 60 | 180 | 360 | 720 | 1440
next_run_at
last_evaluated_at
last_enqueued_at
last_job_id
last_skip_reason
created_at
updated_at
```

约束：

- `subscription_id` 外键关联 `user_subscriptions` 并级联删除。
- `workspace_id/user_id/source_id` 必须和订阅记录一致，服务层和事务内 SQL 同时校验。
- 没有计划记录等同于关闭，默认周期为 60 分钟；本地 X 订阅显式设置为 30 分钟。
- 首次开启时 `next_run_at=now`，由下一个 Worker tick 入队。
- 修改已启用周期后，`next_run_at=now+新周期`。
- 服务重启或长时间离线后只补一个任务，不追赶错过的所有周期。

## 调度与并发

新增 `SourceScheduleService.enqueue_due(...)`，由现有 Worker 每 30 秒、在普通 job claim 前执行：

1. 原子查询到期且订阅、来源和用户均启用的计划。
2. 检查同一订阅是否已有 queued/running `source_fetch`。
3. 检查同一用户是否有 running `user_feed_refresh`。
4. 在同一 `BEGIN IMMEDIATE` 事务中创建任务并推进 `next_run_at`。
5. 自动任务标记 `reason=scheduled_source_fetch`，优先级低于手动任务。

并发规则：

- 两个 Worker/SQLite 连接竞争同一计划时最多创建一个 job。
- 同一订阅最多存在一个 queued/running `source_fetch`。
- 手动重新抓取与自动抓取竞争时复用已有 active job。
- 有 running 全量刷新时，订阅级计划延后 5 分钟，不并发更新 snapshot。
- 全量刷新成功或 partial 且包含该来源的 `SourceOutcome` 时，将该订阅计划的 `next_run_at` 重置为完成时间加周期，避免紧接着重复抓取。
- 任务配额不足、Worker stale、迁移未完成等情况不产生热循环，保存明确的 `last_skip_reason` 并推迟下一次检查。

## 任务结果与失败语义

- 自动任务继续走现有 `source_fetch` runner 和 claim-guarded finalize。
- `succeeded`：更新 Feed、Source Health 和计划状态。
- 成功空结果：不新增文章，来源状态为 healthy，正常安排下一周期。
- `failed`：保留当前 Feed；来源健康按现有规则累计失败；计划保持启用并按下一周期继续。
- retryable job 按现有退避规则重试，但一个周期只对应一个逻辑 job，不重复推进失败次数。
- stale claim 无权写 Feed、健康状态或计划完成信息。

## API 与界面

新增：

```http
GET   /api/me/subscriptions/{subscription_id}/schedule
PATCH /api/me/subscriptions/{subscription_id}/schedule
```

PATCH 请求：

```json
{
  "enabled": true,
  "interval_minutes": 30
}
```

响应包含开关、允许周期、下次执行时间、最近任务、跳过原因和 Worker 状态，不返回来源密钥或内部 payload。

权限：

- owner/admin/member 只能修改自己的订阅计划。
- viewer 可读取，PATCH 返回 `forbidden`。
- 已停用订阅不能开启计划。

订阅编辑面板增加“自动抓取此来源”开关和周期选择。页面继续复用任务状态与 Source Health 展示，不新增独立任务页面。

## 本地 X 配置

部署该能力后，对现有 `X · @thsottiaux` 执行：

- 将 catalog source config 的 `fetch_limit` 从 20 改为 1。
- 启用其订阅级计划，周期 30 分钟。
- 保持 `analysis_mode=full`、private scope、Apify Primary 和优先级 50。
- 用户级 Feed 自动刷新继续保持 360 分钟。

修改后先执行一次 `source_test`，确认授权后的 Actor 能创建 Run 并返回样例；再执行一次 `source_fetch`，确认 X 内容进入 Feed，最后开启 30 分钟计划。

## 可观测性与安全

- 结构化日志记录 `worker_id/job_id/subscription_id/source_id/status/duration`，不记录 token、认证 URL、source payload 或完整错误堆栈。
- `/api/ops/runtime` 增加启用的订阅级计划数、逾期数和最近到期时间。
- Apify 错误继续使用统一脱敏和 240 字符上限。
- 订阅级计划只引用 catalog/source/subscription ID，不复制 Key 值。

## 验收标准

- Apify 授权后 X `source_test` 成功并在 Apify 控制台生成 Run。
- X 每次向 Actor 传递其允许的最小 `max_items=100`，但 Feed 最多合并 1 条 X 内容。
- 30 分钟到期计划只创建一个 `source_fetch`。
- X 自动任务不触发 Apple、OpenAI 或 Claude 抓取。
- 其他来源的 6 小时全量刷新保持不变。
- 全量刷新包含 X 后，不会立即再产生重复 X 自动任务。
- 两个 Worker 并发只生成一个任务；页面重复操作不生成重复 active job。
- 成功空结果、失败重试、停用订阅、配额耗尽和 Worker 重启语义符合设计。
- 两用户的订阅计划、任务、Feed 和来源健康完全隔离。
- API、日志、DOM 和 job result 不泄露 Apify Key。
- Python、JS、Node DOM、完整 pytest、Compose、`git diff --check` 和 Docker API + Worker 验收通过。

## 非目标

- 不实现 cron 表达式、每日固定时刻或秒级周期。
- 不为不同来源创建独立 Worker 或容器。
- 不自动轮换 Apify Primary/Secondary。
- 不引入推送、推荐、Graph、Archive analytics 或网页代理。
- 不修改 VPS，也不执行 commit 或 push。
