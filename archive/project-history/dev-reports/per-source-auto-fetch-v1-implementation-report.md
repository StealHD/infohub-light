# 订阅级自动抓取 v1 实施报告

日期：2026-07-13

## 结论

现有 API + Worker 已支持当前用户为单条订阅配置独立自动抓取周期。X `@thsottiaux` 已完成真实 `source_test` 和 `source_fetch`，本地每次最多保留、分析并合并 1 条；X 自动计划为 30 分钟，整份 Feed 计划仍为 360 分钟。公网/VPS 未修改。

## 实现范围

- 新增 additive `user_source_schedules`，以 `subscription_id` 隔离计划，删除订阅时级联清理。
- `SourceScheduleService` 在 `BEGIN IMMEDIATE` 内完成到期判断、active job 去重、配额、job 创建和计划推进；两个 SQLite 连接竞争同一计划时最多创建一个 job。
- 自动任务复用 `source_fetch`，固定 `reason=scheduled_source_fetch`、`priority=-10`，继续走 catalog runner、结构化 `FeedRunResult`、Source Health、Feed v2 finalizer 和 claim guard。
- 手动/自动同一订阅最多一个 queued/running job；active 全量刷新将单源计划延后 5 分钟，参与该订阅的全量刷新推进下一周期。
- 停用订阅/catalog source、关闭计划或把用户降级为 viewer 时，取消仍 queued 的自动单源任务；running claim 继续完成。
- API 提供当前用户订阅级 GET/PATCH schedule，ops runtime 增加 source schedule 数量、逾期数和下一次时间；订阅编辑器提供开关和固定周期选择。

## X 与 Apify 真实验收

- 目标账号由无记录的拼写修正为 `@thsottiaux`。
- 真实 `source_test` 成功返回 1 条样例。
- 真实 `source_fetch` `succeeded`，产出 1 条并生成一个用户 Feed snapshot；来源健康恢复为 `healthy`。
- X 内容生成 142 字中文 `summary_zh`，低于 200 字硬限制。
- 2026-07-14 纠正：旧 `altimis/scweet` 与单条要求不兼容，已从 Service X 路径移除。当前使用 `apidojo/twitter-scraper-lite`，将 `fetch_limit=1` 精确传为上游 `maxItems=1`，并在本地再执行一次 1 条上限。X 订阅绑定 Apify Secondary，真实直连运行成功，本次返回 0 条。
- 2026-07-14 后续：新代码默认 adapter 已切到 `xquik/x-tweet-scraper`，但正式本地配置仍保持上一 Actor，直到 xquik 单条 canary 通过。当前 FREE tier 单条 `$0.015`，使既定 `$0.01` cap 无法运行；未获提高 cap 授权前不切正式配置。

## 本地运行状态

- `horizon-light-api + horizon-light-worker` 运行，legacy scheduler 未启动。
- API live/ready 为 200，Worker heartbeat 为 ready，`stale_running=0`。
- API 每个数据库请求使用 ContextVar 隔离短连接并执行事务泄漏保护；light Compose 的 macOS bind mount 同时改用 DELETE journal，避免两个容器的 WAL 共享内存视图交替滞后后误报 Worker stale。native/Linux 仍默认 WAL；API/Worker 已用同一镜像重建。
- X schedule：enabled、30 分钟、首次自然运行时间为成功单源抓取后 30 分钟；无重复 active X job。
- 连续三个自然 30 分钟 tick 均成功创建 `scheduled_source_fetch`，任务各产出 1 条、各生成一个 snapshot；第三次在 DELETE journal 切换后执行，running 期间 readiness 持续 200。其间成功全量刷新也正确推进下一次单源时间，且无 stale job。
- 用户 Feed schedule：enabled、360 分钟。
- 四个来源健康状态均为 `healthy`。

## 验证

- pytest：681/681 通过，包含 source schedule、队列、Worker、API 权限、bootstrap、Apify、catalog source 停用防护、请求级 SQLite 连接边界和 local DELETE journal 配置。
- Node DOM：62/62 通过，覆盖订阅编辑器 schedule 渲染、保存和跨用户 generation 防护。
- Python/全部前端 JS 语法、两份 Compose、`git diff --check` 和真实 Key 对 Git diff 的零泄露检查通过。
- init-pro v0.3 validator 需要仓库不存在的 `project-controls.json` manifest，故该结构检查明确跳过；当前 schema-2 控制文件已人工同步。

## 观察项

30 分钟意味着每天最多 48 次计划评估/Actor 调用，每次请求上限为 1 条。旧 Actor 的连续三个自然周期已成功；新 Actor 已通过一次真实直连运行，但还需在恢复 Worker 后观察一个正式 30 分钟自然周期。Apify plan 仍可能限制每日运行次数；若出现配额或成本问题，应调整周期，不得隐藏失败或绕过平台计费规则。
