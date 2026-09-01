用户 Feed schedule 规则：

1. 没有 `user_feed_schedules` row 等同于 `enabled=false`、`interval_minutes=360`；GET 不因缺 row 自动写库。
2. `GET /api/me/feed-schedule` 默认 `view=full`，成功响应的 `data` 固定包含 `schema_version=1`、`enabled`、`interval_minutes`、`allowed_intervals=[60,180,360,720,1440]`、`next_run_at`、`last_evaluated_at`、`last_enqueued_at`、`last_skip_reason`、`last_job`、`active_job` 和 `worker_status=ready|missing|stale`。没有对应时间或 job 时为 `null`；job 对象沿用公开 job shape 且不得包含 `claim_token`。`view=summary` 返回相同计划与 Worker 字段但省略 `last_job/active_job`，并且不得读取 Job 列表或结果；PATCH 仍返回完整视图。
3. `PATCH /api/me/feed-schedule` 接受 `enabled` 和/或 `interval_minutes`；至少提供一个字段。周期只允许 `60/180/360/720/1440` 分钟，否则返回 `400 invalid_feed_schedule`。开启时没有有效订阅返回 `409 no_enabled_subscriptions`；viewer 返回 `403 forbidden`；未登录返回 `401 unauthorized`。
4. 首次从关闭改为开启时 `next_run_at=now`，由下一个 Worker schedule tick 入队首次任务；已开启时修改周期改为 `now + 新周期`。关闭时 `next_run_at=null`，只取消尚在 queued 的 `reason=scheduled_service_refresh` 自动任务，running 任务继续完成。
5. `last_job` 指向该计划最近创建或复用的刷新任务，可通过 `status/result_json` 展示产出条数及 `partial` 的 issue；`active_job` 是当前用户唯一 queued/running 全量刷新。`last_skip_reason` 至少可以为 `active_user_feed_refresh`、`active_source_fetch`、`user_disabled`、`user_read_only`、`no_enabled_subscriptions`、`no_global_subscriptions`、`quota_exceeded` 或 `migration_required`。用户被降级为 viewer 时计划必须关闭并取消仍 queued 的自动刷新；已 running 的任务继续按原 claim 完成，调度 tick 还必须防御性拒绝 viewer 入队。

用户订阅级 source schedule 规则：

1. 没有 `user_source_schedules` row 等同于 `enabled=false`、`interval_minutes=60`；GET 不隐式写库。`enabled=false` 的产品语义是“跟随全局（默认）”，不是手动更新；`enabled=true` 才表示单源独立周期。允许周期固定为 `[30,60,180,360,720,1440]` 分钟。
2. 单条 GET/PATCH 响应包含 `schema_version=1`、`subscription_id`、`source_id`、计划时间、`last_job`、`active_job` 和 `worker_status`；公开 job 不得包含 `claim_token`。订阅列表默认内嵌相同完整 schedule；`GET /api/me/subscriptions?schedule_view=summary` 只省略每条 schedule 的 `last_job/active_job`，服务端必须批量读取当前用户计划并且该摘要路径不得查询 Job。
3. 首次开启默认在下一个 Worker tick 运行；已开启时修改周期从当前时间重新计算。切回跟随全局时保留 `interval_minutes`，把 `next_run_at` 清空，并取消仍 queued 且 `reason=scheduled_source_fetch` 的任务；running 任务继续完成。未来再次开启单源独立周期时可复用该周期。停用订阅或把用户降级为 viewer 时必须同步关闭计划。
4. Worker 每次 schedule tick 在 claim 普通任务前原子评估到期订阅。自动 job 固定为 `job_type=source_fetch`、`reason=scheduled_source_fetch`、`priority=-10`，沿用现有配额、claim token、Source Health 和 Feed v2 单源合并语义。public/workspace source 成功后同一事务会为全部有效订阅者写各自的安全 Feed 投影；健康仍只记录触发该 job 的用户，投影不补发通知。
5. 同一订阅最多一个 queued/running `source_fetch`；手动、自动和重复页面提交复用已有 active job。当前用户存在 active 全量刷新时延后 5 分钟；只有手动全量刷新会包含单源独立周期来源，并在成功参与该订阅后推进其下一次单源计划，避免紧邻重复抓取。自动全局刷新不包含这些来源。停用 catalog source 时，相关计划关闭并记录 `source_disabled`，仍 queued 的自动任务被取消。
6. 调度链路只由当前 Worker 与 Service `execute` 主链组成，不得重新引入第三个 scheduler/dispatcher、全局 publisher，也不得读取或写入全局静态 Feed、旧摘要/通知、Graph 或 Archive analytics。偏好来源通知只可由下述 Service outbox 在 Feed/Health/Job 提交后消费。

用户偏好来源通知规则：

1. `/api/notification-services` 是新 UI 的规范读取入口。GET 返回 `schema_version=1/services/channel_credentials/webhook_provider_options/can_manage`；service 复用 v16 target ID，只含 `id/name/scope/channel/configured/enabled/available/transport_ready/config_generation/activation_generation/enabled_at/last_test_status/last_tested_at/last_test_error_code/can_edit/can_test/can_enable/can_validate/usage/updated_at/legacy_private`，Webhook 另含安全 Provider、签名配置状态和验证模式。`channel_credentials` 只给出 Email/Telegram 的配置、ready、generation 与非秘密 Provider 能力，不得回显任何邮箱、SMTP 用户名、URL、Chat ID、Token 或凭据。`POST/PATCH/DELETE /api/admin/notification-services*` 只允许 Owner/Admin 管理新建的 shared service；Email/Telegram 请求可在同一 write-only body 中首次保存或主动更换共享 Transport 凭据。`POST /api/admin/notification-services/{id}/test-and-enable` 只发送一次测试，ACK 成功后原子确认当前目标/Transport generation 并启用服务。测试失败保留安全草稿，真实值仍不返回。旧 `/api/notification-targets` 仍可读取、修改、测试或归档既有目标，但 POST 新建 private target 返回 `notification_target_private_creation_disabled`；独立 Transport API 继续兼容。
2. 一个目标精确对应一个邮箱、Webhook 或 Telegram 会话。私有目标仅本人可见和维护；共享目标只允许 Owner/Admin 维护，其他用户只读安全状态并可选择。创建后 `scope/channel/owner` 不可修改。配置变化自动停用、推进 `config_generation` 与 `activation_generation`、清除测试并使该目标 pending delivery 失效；单纯重命名不改变 generation、水位或投递。暂停保留业务绑定，恢复推进 activation generation 和水位但沿用未变化配置的测试结果。归档前必须没有当前业务绑定和 `pending|sending` delivery，否则返回 `notification_target_in_use`；归档保留历史名称/渠道投影并清除无引用 Secret。
3. 个人通知 GET 返回 `schema_version=4`、总开关、有序 `target_ids[]`、安全 `selected_targets[]` 与兼容 `channels/channel/channel_states` 投影。规范 PATCH 使用 `enabled/target_ids`，允许选择本人私有目标或工作区共享目标，也允许多个相同渠道目标；绑定独立保存 position、enabled、generation 和水位。旧 `channels/channel` 与旧目的地字段只有在每个渠道可唯一映射到一个兼容可见目标时才执行；同渠道多目标或私有/共享歧义返回 `notification_target_legacy_conflict`，不得静默覆盖、清空或缩减绑定。管理员停用用户时原子关闭总开关并清除全局水位；重新启用账户不得自动恢复。
4. Email 地址、Webhook URL/签名和 Telegram Chat ID 只可在目标 create/update 请求内短暂出现，随后写入目标用途绑定的确定性 `SecretStore` 变量；Telegram Bot Token 只属于工作区 Telegram Transport。Service DB 仅保存名称/作用域/渠道/Provider 等非秘密元数据、确定性变量名和当前值的 SHA-256 一致性摘要；config JSON、Feed、Job、outbox、API、DOM、Toast、日志和错误 envelope 均不得保存或回显真实值。配置、staging、测试和发送必须验证变量绑定与摘要匹配；SecretStore/SQLite 中断必须补偿回滚或 fail closed。Chat ID 只接受有符号十进制数字或 `@channel`，不接受 forum topic/thread ID。
5. `user_subscriptions.notify_on_new_items` 默认 false。PATCH 从 false 切为 true 时记录 `notification_enabled_at=now` 并推进 `notification_generation`；幂等保存不得重置水位或代数。旧客户端省略该字段时已有订阅保留原状态，新订阅默认关闭。订阅或 catalog source 停用、订阅切到 `analysis_mode=personal_only` 时原子清除开关和水位；重新启用不得自动恢复。
6. 内容投递只比较本次成功/partial Feed snapshot 与紧邻上一份 snapshot 的稳定 `article_id` 差集。首份 snapshot 仅建立基线；标题变化、删除、排序、no-op、共享内容复用、reconcile、`source_test`、`content_repair` 和无 snapshot 的失败均不得生成通知。候选必须包含已开启订阅 provenance，且规范 `published_at` 与可信 delivery `created_at` 都严格晚于总开关、目标、绑定和订阅当前水位；缺失、无时区或不可解析时间 fail closed。新建/恢复目标、恢复 Transport、重新绑定目标或恢复总开关只发送此后严格新增内容，不补发停用/暂停期间历史。
7. `preferred_source_notification_deliveries` 以 `(subscription_id, article_id, target_id)` 唯一去重，并在 stage 时固化总设置、目标配置/启停、绑定与订阅 generation。候选必须与 snapshot、Source Health 和 claim-guarded Job 终态处于同一事务；claim 失效整体回滚且不得外呼。Worker 只在 Job 成功提交后按用户、Job、目标分别领取并投递，同一目标最多合并 20 个 distinct article；外呼前复查用户、来源、订阅、总开关、绑定、目标、Transport、全部 generation 和水位。任一目标 staging/claim/send 失败只更新该目标 delivery，不得阻断其他目标或把已成功的抓取 Job/snapshot 改为失败。
8. 外部通知不假设幂等。未开始的 pending 可以重试领取；领取后先写 `sending` 再外呼。只有能证明 POST 尚未开始的连接失败可安全回到可重试 unavailable；429 为明确限流。POST 已开始后的 timeout、HTTP 408/425/5xx、超限/畸形响应、ACK 不可确认或其他 TransportError 一律为 `unknown` 且永不自动重放；明确非法目的地、认证失败、目标拒绝和可验证非成功 4xx 可进入 `failed`。状态只保存稳定安全 error code，不保存响应正文、凭据或目的地。
9. Email 只读取 schema v10 工作区 Transport，绝不回退 `data/config.json.email`。Webhook 共用七类 Registry、精确 HTTPS URL、DNS/IP pinning、禁代理/重定向、Provider payload 与 ACK 规则。Telegram 只调用固定 `https://api.telegram.org/bot<TOKEN>/sendMessage`，JSON 仅含 `chat_id`、1..4096 字符纯文本和关闭链接预览参数，不发送 `parse_mode`；成功必须同时验证 HTTP 成功、`ok=true`、数字 message ID，且响应目标会话与请求 Chat ID 一致。公共网络策略只可对精确 `api.telegram.org` 接受 Clash/Docker fake-IP 网段 `198.18.0.0/15`，仍固定 HTTPS、Host/SNI、单地址单次 POST、`trust_env=false` 和禁止 redirect；Webhook、来源与任何用户输入 host 继续拒绝 synthetic/private IP，应用不得读写 Clash 配置。Email 或 Telegram Transport 暂停只让对应目标 unavailable，其他渠道与目标继续发送；Transport 恢复不移动旧 delivery。
10. 新 UI 只调用服务级 `test-and-enable`，不再调用独立 Transport test 或业务级 test。每个服务独立原子领取 60 秒冷却，并只验证已保存目的地、当前 `config_generation` 和对应 Transport generation；目的地或共享凭据变化会清除旧测试与冷却，使同一次“保存并测试”可以立即验证新 generation。成功返回安全的 `sent/enabled/target_id/channel`，Webhook 另返回 `provider/verification`，并原子启用对应 Transport 与服务；其他目的地未变化且此前已验证的同渠道服务同步恢复可用但不补发停用期内容。unknown 必须持久化并返回不可重试的 `notification_target_test_outcome_unknown`，客户端刷新服务状态并先人工核对接收端。测试不写业务 outbox、不移动历史水位、不创建 Job，也不触发来源、AI、scheduler 或付费调用。旧逐目标、独立 Transport 与个人/Apify test 接口保留兼容，不在新 UI 中出现。
11. notification targets v16 是依赖 v15 的显式重建迁移：创建目标与业务绑定，按 target 重建 delivery 唯一约束，并把既有个人渠道迁为对应用户私有目标、既有 Apify 渠道迁为共享目标；个人与 Apify 即使摘要相同也不自动合并。历史且无现行配置的 delivery 使用确定性归档占位目标，保留事件、incident、顺序、generation、水位、测试和投递历史。已有数据库必须停止 API/Worker并跨过 heartbeat 安全窗，使用 `scripts/migrate_notification_targets_v16.py --dry-run|--apply` 创建 UTC `0600` backup；apply 校验迁移前后计数、目标/绑定/索引约束、`integrity_check` 与 `foreign_key_check` 后才记录 marker。重复 apply 必须幂等，缺 v15、marker/约束损坏或活动 Worker时拒绝；readiness 和 Worker fail closed。迁移只搬运已有 SecretStore 引用与摘要，不读取目的地真实值、不调用 Transport、不创建新消息或重放旧 delivery。

工作区邮件发送服务规则：

1. 缺少 `workspace_email_transports` row 等同未配置且关闭；schema v10 只保存 `provider/sender_email/sender_name/region/smtp_username/enabled/generation/test metadata`、确定性 SecretStore 环境变量名与当前凭据 SHA-256 一致性摘要。授权码、App Password、API Key、SES SMTP Password 和测试收件人不得进入 SQLite、config JSON、Job、Feed、outbox、日志或 API 响应。
2. Provider Registry 只支持固定的 SSL/465 连接：QQ=`smtp.qq.com` 且登录名为完整 QQ/Foxmail 地址；网易=`smtp.163.com` 且接受 163/126/yeah.net 完整地址；Gmail=`smtp.gmail.com` 且登录名为完整地址；Resend=`smtp.resend.com` 且登录名固定 `resend`；Amazon SES=`email-smtp.<validated-region>.amazonaws.com` 且使用显式 SES SMTP username。API 不接受 host、port、TLS 模式或自定义 SMTP，浏览器不得覆盖派生结果。
3. PATCH 至少包含 `provider`、`sender_email`、`sender_name`、write-only `credential`、`enabled`、SES-only `region/smtp_username` 中一个。首次创建必须得到可解析 Provider 配置；Provider、发件身份、Region、SES 用户名或凭据变化会推进不可回退 `generation`、自动关闭、清除旧测试状态并要求当前 generation 重新测试。账号相关字段变化且未同时提交新凭据时清除旧凭据绑定；凭据提交后 API 永不回显。
4. `enabled=true` 只在 SecretStore 当前值与确定性变量/摘要匹配、Provider 配置有效、且 `last_test_status=sent` 与 `last_test_generation=generation` 时允许。每次 API 测试和 Worker 发送都重新读取 SecretStore 并比较摘要，无需重启容器；文件/SQLite 部分失败必须补偿或 fail closed。
5. 管理员 test 只接受一次性 `recipient_email`，按 workspace 在 SQLite 写锁内原子领取 60 秒冷却；成功只返回 `sent=true/generation`。测试通过与启用是两个独立动作，测试不创建 Feed/Job/outbox、不移动用户或订阅水位，也不把测试收件人写入任何持久状态。
6. 统一 `EmailTransport` 使用系统 CA 校验的 TLS、20 秒 timeout 和同一 MIME/HTML 转义实现；API 测试与 Worker 正式投递不得复制 Provider 发送逻辑。正式发送在 SMTP 连接中断或其他结果未知后保持 delivery=`sending` 且不自动重放；认证、发件人、收件人或 DATA 的明确拒绝可安全终结为 `failed`。
7. transport 轮换、停用或删除时，尚未开始的 workspace email `pending` delivery 原子终结为 `failed/notification_transport_changed`；已经 `sending` 的记录保持未知结果。transport 未 ready 时不创建新的 email outbox；已有用户 email opt-in 和逐来源水位均保留，因此恢复后只比较暂停期间保存的最新相邻 Feed 基线并发送之后严格新增的内容。Webhook staging 与发送不受邮件 transport 状态影响。
8. 磁盘上既有 `data/config.json.email` 与 `data/config.json.webhook` 块是 inert 数据：Service API、Worker、设置页与偏好来源通知不得投影、执行、改写或用作降级兜底。当前通知只使用 Service DB 与 SecretStore 中的通知服务/Transport 配置。

工作区 Telegram Bot 服务规则：

1. 缺少 `workspace_telegram_transports` row 等同未配置且关闭。GET 只返回 `configured/token_configured/enabled/generation/last_test_status/last_tested_at/last_test_error_code/can_enable/ready/updated_at` 等安全状态；Bot Token、确定性变量名、摘要、测试 Chat ID 与 Telegram 响应永不返回。
2. PATCH 只接受 write-only `bot_token` 和 `enabled`。Bot Token 必须符合 Telegram Bot Token 的结构约束，随后写入确定性的工作区 SecretStore 变量；SQLite 只保存 SHA-256 摘要。Token 新增或变化推进不可回退 generation、自动关闭、清除旧测试并要求当前 generation 重新测试；显式删除 Transport 同样清除 SecretStore 值并使未开始的 Telegram pending delivery 安全终结。
3. `enabled=true` 仅在当前 SecretStore 值与摘要匹配且 `last_test_status=sent`、`last_test_generation=generation` 时允许。API 测试和 Worker 每次发送都重新读取并校验，不使用请求可控 host、代理、base URL 或自定义方法。
4. POST test 只接受一次性 write-only `chat_id`，按 workspace 原子领取 60 秒冷却。成功只返回 `sent=true/generation`；测试通过与启用是两个独立动作，测试 Chat ID 不持久化、不创建 Feed/Job/outbox，也不移动用户、渠道或订阅水位。
5. 共享 `notification_telegram_transport` 固定调用 `api.telegram.org` 的 `sendMessage`，使用系统 CA、禁用环境代理和重定向，并发送 `chat_id/text/link_preview_options.is_disabled=true`；不得发送 `parse_mode`。文本为 1..4096 Unicode 字符，任何 HTML/Markdown 标记都按普通文本处理。
6. HTTP 成功仍必须验证有界 JSON 的 `ok=true`、数字 `result.message_id` 和匹配目标会话。Token/Chat ID 无效、认证失败、目标拒绝、429、服务不可用和结果未知使用稳定错误语义；POST 已开始后的 timeout、5xx 或畸形响应一律 unknown 且不自动重放，响应正文、description、parameters 和请求目的地不得持久化或记录日志。
7. Transport 轮换、停用或删除只暂停 Telegram 渠道，并只使该渠道 pending delivery 失效；Email 与 Webhook 继续运行。恢复后不补发暂停期间内容，个人与告警 Telegram Chat ID 配置仍保留且彼此独立。

用户 Source Health 规则：

1. `GET /api/me/source-health` 成功响应沿用统一 envelope；`data` 的精确 shape 为：

   ```json
   {
     "schema_version": 1,
     "scope": "user",
     "window": {
       "timezone": "Asia/Shanghai",
       "feed_days": 7,
       "today_start": "2026-07-26T16:00:00+00:00",
       "feed_start": "2026-07-20T16:00:00+00:00",
       "now": "2026-07-27T04:30:00+00:00"
     },
     "summary": {
       "total": 0,
       "unknown": 0,
       "healthy": 0,
       "degraded": 0,
       "failing": 0
     },
     "items": [
       {
         "subscription_id": "subscription-id",
         "source_id": "source-id",
         "source_display_name": "Example source",
         "source_type": "rss",
         "status": "unknown",
         "last_attempt_at": null,
         "last_success_at": null,
         "last_failure_at": null,
         "consecutive_failures": 0,
         "last_fetched_count": 0,
         "today_item_count": 0,
         "feed_item_count": 0,
         "current_item_count": 0,
         "history_item_count": 0,
         "last_issue": null,
         "last_job_id": null
       }
     ]
   }
   ```

2. `items` 只包含上述字段，并按现有订阅 priority/创建顺序稳定返回当前用户的全部订阅；禁用的 subscription 或 catalog source 仍保留并投影其健康。`window` 与 Feed API 使用同一工作区时间边界。`last_fetched_count` 只表示最近一次生产抓取 outcome 返回的条目数，不表示新增数或当前 Feed 可见数；`today_item_count` 是上海自然日当天数量，`feed_item_count` 是近 N 天 Feed 数量，兼容字段 `current_item_count` 必须始终等于 `feed_item_count`，`history_item_count` 是 `effective_at < feed_start` 的数量。四个可见性计数都必须按标量 `source_id` 与数组 provenance 完整归属并按 article ID 去重。`last_issue` 无记录时为 `null`，有记录时精确为 `{"stage", "code", "message", "retryable"}`，其中 `retryable` 是 boolean。不得返回 source key/config、secret env、job payload、claim token、原始 issue 列或其他用户记录。
3. `summary` 必须只含 `total/unknown/healthy/degraded/failing` 五个整数键，并与 `items` 逐项计数一致。缺少 `user_source_health` row 表示 `unknown`，其时间、issue 和 job 为 `null`，失败数和抓取数为 `0`；读取 unknown 不得隐式插入 row。
4. 健康只记录 `user_feed_refresh/source_fetch` 的生产 `SourceOutcome`，同一个公共 source 的不同用户订阅可以有不同状态。成功（包括抓到 `0` 条）为 `healthy`，连续失败数清零并清除 issue；第一次连续终态失败为 `degraded`，第二次及以后为 `failing`；下一次成功恢复为 `healthy`。成功保留此前 `last_failure_at`，失败保留此前 `last_success_at`。
5. 成功或 `partial` run 中的全部来源 outcome 与 snapshot/items、claim-guarded job 终态在同一事务提交；claim 已过期或不匹配时整体回滚。结构化 all-source 失败在仍会重试时不更新健康；只有 `fail_or_retry_job` 选定最终 `failed` 后，才在有效 claim 下原子提交 health + failed job，且不生成 snapshot。`source_test`、cancelled、intermediate retry、没有 `SourceOutcome` 的 job-level infrastructure error 均不更新健康。
6. 内部 `user_source_health_applications` ledger 只用于持久化 `(subscription_id, job_id)` 幂等；重复应用同一 job 不得重复增加失败数。ledger 随 job 或 subscription 清理级联删除，属于实现细节，不进入 API。
7. 持久化前把 issue message 规整为单行并限制为最多 240 个字符，移除 URL userinfo/query、Bearer/Basic auth、token/API key/password/secret、payload/config/stack/traceback 与常见裸 secret；API 只返回这份处理后的当前用户 issue。该投影不得作为保存 source 配置、请求 payload、claim 或秘密的通道。
8. `/api/ops/runtime` 增加且只增加以下 Source Health 运维聚合：
   - `source_health_counts`：精确包含 `total/unknown/healthy/degraded/failing`，以当前订阅 left join health 计算 unknown，并遵守现有 workspace/user filter；
   - `recent_source_failure_code_counts`：只统计非空 `last_issue_code`，时间窗为服务 `checked_at` 的闭区间 `[checked_at - 24 hours, checked_at]`；安全 code 必须匹配首字符为字母、总长不超过 64、其余仅字母数字及 `_.:-`，不符合或呈 secret 形状的 code 统一归并为 `Other`；
   - `source_health_failure_window_hours`：固定整数 `24`。
9. 上述 ops 字段只允许输出计数和安全 code bucket，不得返回 source/subscription/user 的名称或 ID、issue message、时间戳、配置、payload、claim、密钥、Webhook 或其他秘密。
10. source 的规范化 `config` 或 `secret_env` 实际变化时，source 更新与该 source 全部订阅健康记录的清除必须位于同一个事务；共享 source 会使所有订阅者重新显示 `unknown`，private source 因 source id/ownership 自然隔离。只改 display name、description、默认 channel/topics、enabled 或任意 subscription override/priority 时不得重置健康。
