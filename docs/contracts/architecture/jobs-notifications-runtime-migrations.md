### 3.7 Secret Boundary
Service DB 和 catalog 只保存环境变量名或 secret ref 元数据，不保存真实密钥、Webhook URL/签名、Telegram Bot Token 或 Telegram Chat ID。真实 AI/Apify 值、write-only 通知目的地与 Transport 凭据由 `src/services/secret_store.py` 独占写入 Git/Docker 忽略的 `data/secrets.env`，多值变更必须先构造完整新状态再原子替换且权限为 `0600`；SQLite 只保存用途绑定的确定性变量名、SHA-256 摘要和非秘密 Provider 元数据。API/Worker 可以热加载该文件，但 API、日志、job、Feed、outbox、DOM、Toast 和非管理员 source 投影不得返回真实值。Apify pool 表只引用 `secret_id/version` 和安全状态；活动、排空中或仍有非终态 Run 的成员不得轮换或删除，必须先走安全排空。`source_catalog.secret_env` 在池模式只保留回滚兼容，不参与读取、展示或新来源写入。

### 3.8 Job Boundary
长耗时抓取、source test 和用户 feed refresh 必须通过 job queue 表达。Web 请求只创建、取消、重试或查询 job；Worker 负责执行 job 并写入状态/result。Worker claim 在 `BEGIN IMMEDIATE` 中原子写入 `worker_id + claim_token + locked_until`；finalize、失败、续租必须带同一 claim guard。Worker 每 10 秒 heartbeat/续租，35 秒未更新视为 stale；过期 running job 会在下一次 claim 前回到 queued 或达到上限后 failed。SQLite MVP 不强杀正在执行的 Python 任务。

`src/services/response_schema.py` 独占上游与标准化响应结构摘要：adapter 在原始对象仍位于调用栈时立即转换为有界 `path + type`，只把摘要交给 Orchestrator；`safe_run_diagnostics()` 独占 `response_schemas` 的 Job 投影。共享获取命中只记录 `cached`，不得读取或复制旧 Job 的上游结构。原始响应值和结构诊断均不得进入 Feed snapshot 或 `user_content_items`。

Service API 的 SQLite 访问使用 ContextVar 隔离的请求级连接，并为每个 `/api/*` 请求创建和关闭连接；鉴权读取与路由处理必须处于同一请求边界。请求结束仍存在事务时必须回滚并返回 `database_transaction_leak`，避免 macOS Docker bind mount 下长连接停留在旧 WAL 视图而误判 Worker heartbeat 或任务状态。`/api/health/live` 不访问数据库，也不受该边界阻塞。

`user_feed_refresh` 的 `succeeded/partial` 结果必须把 schema-v2 payload 保存为当前用户 snapshot，同时 upsert 稳定内容并写入 `snapshot_id/item_count` 到 job result。snapshot、稳定 items 和 job 终态在同一短事务提交；过期 claim 无权提交。同一非空 job 最多一个 snapshot，同一 snapshot 内 article 唯一；terminal job 手动 retry 产生的新 run 原子替换该 job 的旧 snapshot 内容，但既有稳定 `effective_at` 不变。`/api/feed/latest|history|search` 只通过强制持有 `ServiceStore` 的 `FeedReadService` 读取目标用户稳定索引并按 timeline 投影，不存在文件或 ArticleStore fallback。

`source_fetch` 带 `source_id` 时属于用户作用域精准抓取，不走旧 `source_type:index` 单源刷新路径。Worker 执行后必须通过 `UserFeedStore` 保存当前用户 snapshot，并在 job result 中返回 source 和 snapshot 元数据。

所有 lifecycle mutation 必须与 schedule shutdown、queued-job invalidation 和无网络 Feed reconciliation 共处一个写事务。Worker 在网络前与 finalize 前复查同一 eligibility；失效中的 running claim 只能以 `cancelled/job_invalidated` 收口，不能写 Feed 或 Source Health。订阅名额 admission、任务 retry 与其 usage 计量也必须在 `BEGIN IMMEDIATE` 中原子提交。

### 3.8A Feed Schedule Boundary
`src/services/feed_schedule.py::FeedScheduleService` 是每用户自动刷新计划的唯一服务边界；`ServiceStore` 只提供 additive 表和 SQLite 事务，API 只做当前用户鉴权、参数校验与响应投影。schedule 缺 row 投影为默认关闭/6 小时，不允许为了读取状态隐式开启。

常驻 `horizon-worker` 在 claim 普通任务前调用 `FeedScheduleService.enqueue_due()`，主循环默认每 30 秒评估一次；该周期由 `HORIZON_SCHEDULE_POLL_SECONDS` 配置。到期读取、full-refresh 去重、配额 admission/usage、job 创建和 schedule 推进必须位于同一 `BEGIN IMMEDIATE` 写事务，保证两个 Worker/连接最多创建一个任务。自动 job 继续复用 `user_feed_refresh`、Feed v2 finalizer 和完整 `filtering.time_window_hours`，仅以 `reason=scheduled_service_refresh`、`priority=-10` 区分低优先级来源。

自动与手动全量刷新共享“每用户最多一个 queued/running”约束；active `source_fetch` 和 migration gate 延后 5 分钟，其他不可运行状态记录明确 skip reason 并推进到下一周期，避免热循环。关闭计划只取消 queued 的自动 job，不强杀 running job；`partial/failed` 不改变 enabled 状态。

React UI 低频读取当前用户 schedule，并在发现 active job 后复用有界 job poll；terminal snapshot 只有在 Feed 明确加载成功后才记为 handled。所有 Feed/config/item-state/schedule 异步读取必须绑定当前 auth user 与 query generation；logout、unauthorized 或用户切换会取消旧请求、删除旧用户缓存并阻止旧响应重新渲染。

这条边界只依赖常驻 Worker，不得新增 scheduler/dispatcher 容器，也不得读取或修改 `data/site/*.json`、旧摘要、图谱或 archive analytics。已退役的 scheduler、publisher 与全局 `run()` 不得重新成为调度依赖。

### 3.8B Subscription Source Schedule Boundary

`src/services/source_schedule.py::SourceScheduleService` 是订阅级自动 `source_fetch` 的唯一调度边界。权威状态位于 additive `user_source_schedules`，以 `subscription_id` 隔离用户；缺 row 等同关闭。API 只能读写当前用户的订阅计划，React 不得自行创建定时器抓取外部来源。

现有 Worker 在用户 Feed schedule 之后、claim 普通任务之前评估到期 source schedule。到期检查、active job 去重、配额、job 创建和计划推进必须处于同一 `BEGIN IMMEDIATE` 事务；自动任务固定 `reason=scheduled_source_fetch`、`priority=-10`，并继续复用 catalog runner、结构化 run、Feed v2 finalizer、Source Health 和 claim guard。手动/自动单源任务共享“同一订阅最多一个 queued/running”；active 全量刷新会延后单源计划，参与该订阅的全量刷新也会推进下一周期。

关闭计划、停用订阅或 catalog source、用户降级为 viewer 时，只取消仍 queued 的自动单源任务，不强杀 running claim。该链路与用户 Feed schedule 共享同一个 Worker 和 30 秒 tick，不新增容器，不接触旧全局 Feed、摘要、图谱或 archive analytics。成功 Feed 的偏好来源 outbox 仍由 3.8C 独立判定。

### 3.8C Preferred-source Notification Boundary

`src/services/notification_targets.py::NotificationTargetService` 是 Email/Webhook/Telegram 业务目的地与规范“通知服务”投影的唯一配置边界：底层继续复用 schema v16 target ID、绑定和 delivery 身份，它独占私有/共享目标的 CRUD、权限、write-only SecretStore 绑定、配置与启停 generation、水位、测试冷却、Transport readiness、归档占用保护和安全公开投影。新的服务固定为 workspace shared，由 Owner/Admin 通过组合 API 保存目的地与可选共享凭据并执行一次 `test-and-enable`；历史 private target 不提权、不迁移作用域，原 owner 仅继续使用或归档。业务服务不得复制目的地字段、测试流程、SecretStore mutation 或 Provider/Transport 选择逻辑。

`src/services/preferred_source_notifications.py::PreferredSourceNotificationService` 只拥有当前用户总开关、有序目标绑定、订阅 opt-in、新文章差集、outbox 和提交后调度；公共 settings schema v4 投影 `target_ids/selected_targets`，旧 `channels/channel/channel_states` 仅为兼容视图。schema v16 的绑定独立保存 position、generation 与水位，旧渠道写入只在能唯一映射到一个兼容可见目标时执行。设置 partial PATCH 必须在 SQLite 写锁内重读实时用户；业务层不得修改目标配置或测试结果。

`src/services/notification_webhook_transport.py` 独占 `generic_event|generic_text|feishu_lark_v2|wecom|dingtalk|slack|discord` Registry、精确 URL 校验、文本/事件 payload、飞书与钉钉签名、平台 ACK 判定及安全错误分类。偏好来源通知与 Apify 运行告警只能调用该 transport，不得复制 Provider host/path、签名或响应解析。`legacy_auto` 只用于迁移前 row 或兼容旧客户端省略 Provider 的 URL-only PATCH（包括首次创建 setting）：精确飞书/Lark V2 URL 解析为对应平台，其余解析为通用事件；请求不能直接选择该值，新 UI 必须显式选择七类 Provider。

`src/services/notification_email_transport.py::WorkspaceEmailTransportService` 独占 schema v10 工作区邮件发送配置、固定 Provider Registry、凭据绑定、管理员测试门禁和 MIME/SMTP 发送。QQ、网易、Gmail、Resend 与 Amazon SES 的 host/port/login 只由 Registry 派生，API 不接受自定义 host 或 TLS 模式；SES host 只能由经过格式约束的 Region 拼接。Owner/Admin mutation 在 SQLite 写锁内重读实时 actor；凭据只写确定性的工作区 SecretStore 变量，SQLite 只保存变量名与 SHA-256 摘要。API 测试与 Worker 必须复用同一发送方法，每次发送重新读取 SecretStore 并比较摘要，TLS 使用系统 CA、SSL/465 和 20 秒 timeout。

`src/services/notification_telegram_transport.py` 独占 Bot Token/Chat ID 语法校验、固定 Telegram Bot API `sendMessage` 请求、4096 字符纯文本边界、ACK 校验和稳定错误分类；业务服务不得接受自定义 API host、复制请求或解析响应。工作区 `WorkspaceTelegramTransportService` 独占 Bot Token SecretStore 绑定、generation 与 enable gate；规范 UI 通过某个 Telegram 服务的组合测试同时验证当前 Bot generation 与 Chat ID，旧独立 Transport test 只保留兼容。请求只含 `chat_id/text/link_preview_options.is_disabled=true`，不发送 `parse_mode`；HTTP 成功还必须校验 `ok=true`、数字 message ID 和目标会话一致。POST 已开始后的 timeout、5xx 或畸形响应为 unknown 且不自动重放。

通知候选必须在 `FeedProductionService` 已生成 snapshot 后、`JobQueue.complete_job()` 的 claim-guarded 事务提交前通过局部 savepoint stage；它只接受相邻 snapshot 的稳定 article ID 新增、完整订阅 provenance、严格晚于总开关、目标、绑定与订阅水位的可解析 `published_at`，并跳过首份 snapshot、历史复用、reconcile、`personal_only`、source test、content repair 和失败任务。snapshot、Source Health、Job 或 claim 回滚时 outbox 同步回滚；通知 staging 自身失败只回滚该目标 savepoint，不得让已完成获取重跑或阻断其他目标。

外部 Email/Webhook/Telegram 只能在 Job 成功提交后由同一常驻 Worker 消费；不得在 finalizer 事务内联网，也不得调用 legacy notifier 或新增 dispatcher/scheduler 容器。同一用户、Job、目标最多 20 个 distinct article ID 及其全部 provenance ledger 在一次事务中 claim，payload 按 article ID 去重后合并为一次外呼；outbox 的稳定身份为 `(subscription_id, article_id, target_id)`。外呼前必须复查用户、来源、订阅、总设置、目标绑定、目标配置/启停 generation、对应 Transport generation 和全部水位；generation 不受墙钟回拨影响，关闭后重开的旧 delivery 必须安全终结。任一目标 staging、claim 或发送失败只更新该目标，绝不阻断其他目标或改变 Feed/Job 成功。Email/Telegram Transport 暂停、轮换或删除只使对应目标 unavailable 并终结其未开始 pending；选择、目的地和 Feed 基线保留，恢复后只消费之后严格新增内容，不补发暂停期间条目。逐目标测试使用独立 60 秒冷却和 generation guard，不创建 delivery、不移动水位、不触发抓取/AI。

Webhook egress 只接受 SecretStore 当前保存并与所选 Provider 精确匹配的 HTTPS，复用 `src/services/network_policy.py` 的公网解析和 IP pinning；它禁用环境代理、拒绝 redirect，以 bounded DNS、单地址单次 POST、5 秒 transport timeout 和 6 秒总 deadline 发送。G1/G2 采用 URL-only，不接收 Bearer 或自定义 header，正文在网络层直接丢弃且只校验 2xx；P1-P5 只接受 identity 响应并最多读取 4096 bytes 交给共享 transport 校验业务 ACK。超限、畸形、压缩或已开始发送后的 transport 错误一律投影为 unknown 且不自动重放，上游正文永不持久化或进入日志/错误。Telegram 在同一 pinning 层拥有唯一的 exact-host synthetic DNS 例外：仅 `api.telegram.org` 可接受 `198.18.0.0/15`，连接仍固定原 Host/SNI、HTTPS、零 redirect、`trust_env=false` 和单次 POST；Webhook、来源及其他 host 继续拒绝 fake/private IP，代码不得修改 Clash 配置。Service Email 只使用 schema v10 workspace transport 与其 SecretStore 凭据，不读取 `data/config.json.email` 或进程环境兜底；Telegram 只使用 schema v15 workspace transport。三种 transport 的响应正文、目的地和凭据均不得进入公开错误或日志。

### 3.8D Apify Operational Alert Boundary

`src/services/apify_actor_alerts.py::ApifyActorAlertService` 独占工作区 Actor 告警总开关、共享目标绑定、incident、delivery outbox、首报/升级/恢复去重和提交后投递；`src/services/apify_actor_monitoring.py::ApifyActorAlertBridge` 只把已提交的路由、费用与额度状态转换成安全事件。告警与 3.8C 的个人新内容通知拥有独立业务绑定，但必须复用同一 `NotificationTargetService`、工作区 Email/Telegram Transport 和 Webhook Registry；系统告警不得读取或绑定私有目标。

同一 incident 首次打开只创建一次告警；持续相同状态只更新 `last_seen_at`，从 degraded 升级到全挂必须创建独立 critical incident，精确恢复只解决对应 open incident 并各发送一次 recovery。每个事件按 `(incident_id, event_type, target_id)` 唯一 stage；各目标独立配置/启停/绑定/Transport generation 与水位，incident schema v3 按目标返回 `target_id/target_name/channel` 并保留确定性聚合的兼容状态。明确的临时投递失败最多技术重试三次；已开始发送但结果未知保持 `unknown` 且永不自动重放。旧业务 test 仅为兼容入口；新 UI 只在目标管理处测试。任一目标失败不得改变其他目标、Actor 路由、费用账本、抓取 Job 或 Feed。

### 3.9 Config Compatibility Boundary
`data/config.json` 当前承载 AI、过滤、workspace RSSHub Base URL、标签库和可导入 source 输入；多人 source 的权威状态位于 `source_catalog` 和 `user_subscriptions`。当前用户通知 outbox 源于 Service schema v9，工作区邮件 transport 位于 schema v10，Webhook Provider 位于 schema v14，多渠道状态与 Telegram Transport 位于 schema v15，统一目标、业务绑定和按 target delivery 约束位于 schema v16；通知真实值只进入 SecretStore。磁盘上既有 `email/webhook/premium_analysis/article_graph` 块必须保持字节语义不变，但 API 不投影、当前代码不执行、配置 action 不改写。内部 `legacy_auto` 只用于读取 v14 前的 Service Webhook row 或承接旧客户端省略 Provider 的 URL-only PATCH，不能写入旧 config 或由请求显式选择。RSSHub Base URL 是可切换的非密钥 runtime URL，可含安全 path prefix，但不得复制进 catalog config、MCP/Agent 输出或 Feed；可选 `RSSHUB_ACCESS_KEY` 只存在 SecretStore，Worker 只派生 route-scoped access code。VPS-only `RSSHUB_BILIBILI_ANONYMOUS_COOKIE` 也只能进入 SecretStore 和 RSSHub 容器环境，且必须由隔离的无 profile 浏览器 context 从公开页面生成，禁止复用账号 Cookie。

全局非 source 配置只允许 `owner/admin` 修改；`member/viewer` 不得借兼容 facade 改写 AI、过滤、标签或 Webhook。member source action 的 topics/personal tags 只写 source/subscription；任何管理员全局标签写入也必须在 catalog/subscription 成功后执行。旧配置批量导入只能更新 scope/owner/type 兼容的 source，另一用户 private key 碰撞必须跳过。SQLite 连接必须统一开启 foreign keys 和 busy timeout；native/Linux 默认使用 WAL，但 macOS Docker bind mount 的 light Compose 必须让 API/Worker 同时使用 DELETE journal，避免跨容器 WAL 共享内存可见性漂移。journal mode 只能由 `HORIZON_SQLITE_JOURNAL_MODE=WAL|DELETE` 选择。API 连接按 ContextVar 请求作用域隔离，禁止跨并发请求共享。

member 控制的 direct catalog RSS URL 不得包含环境变量占位或 URL userinfo；Worker 必须以 catalog row 而非 job payload 为权威。初始请求和每次 redirect 都必须解析并审核全部地址，随后只连接本次审核通过的字面 IP并保留原 Host/SNI；安全请求使用隔离且 `trust_env=False` 的连接、拒绝压缩响应并执行 2 MB 流式上限。受控 RSSHub row 是单独边界：成员只能提供 allowlisted `site/route_key/params`，运行 origin 只来自管理员配置，Worker 禁止跟随 redirect。除此之外，`owner/admin` 拥有的 source 仍是本地/私网任意 RSS URL 的唯一显式信任边界。

### 3.10 Runtime / Migration Boundary
部署单元固定为独立 `horizon-api + horizon-worker`；用户 Feed schedule 内嵌在现有 Worker，不形成第三个进程或容器，也不存在 scheduler profile。发布脚本必须在切换前阻断仍在运行的历史 scheduler 容器，避免旧镜像继续写数据或发送通知。旧 snapshot 到 Feed v2 的清空重建只能由 `scripts/migrate_user_feed_v2.py --apply` 在服务停止后显式执行，应用启动不得自动删除用户数据；未完成迁移时 readiness 和 Feed Worker 都必须拒绝继续。迁移工具已存在不表示真实数据库已执行迁移。

Feed storage v3 使用 `scripts/migrate_feed_storage_v3.py --dry-run|--apply`。apply 前必须停止 Worker；工具以 SQLite backup API 创建 UTC 命名、权限 `0600` 的独立副本，additive 初始化/backfill content hash，执行 retention，并通过 `integrity_check` 与 `foreign_key_check` 后才记录 version 3。Worker maintenance 以持久化小时门禁执行相同 retention，且无论时间/数量阈值都保留每用户/每 acquisition key 最新必要记录。

Content timeline v11 使用 `scripts/migrate_content_timeline_v11.py --dry-run|--apply`。apply 前同样停止 Worker并创建独立备份；迁移以首次入库时间作为缺失/非法/异常未来发布时间的稳定回退，回填用户隔离的 `effective_at/search_text`，重建 FTS5 索引并在 integrity/foreign-key 全部通过后记录 version 11。API readiness 与存储治理在存在待回填行时必须 fail closed，不得靠重新抓取修复时间边界。

Apify Actor routing v13 使用 `scripts/migrate_apify_actor_routing_v13.py --dry-run|--apply`。已有数据库的普通 `ServiceStore.initialize()` 不得创建或标记 v13；版本缺失时 API readiness、Actor 管理接口与 Worker 在领取 Job 前统一返回 migration required。apply 前必须停止 API/Worker并跨过 Worker heartbeat 安全窗；工具以 SQLite backup API 生成 UTC `0600` 副本，additive 创建 route/candidate/attempt/target-health/alert setting/incident/delivery 表及 Run 费用列，幂等种入 ScrapeBadger closed、Dami disabled/canary_required、Xquik open，随后通过 `integrity_check` 与 `foreign_key_check` 才记录版本。迁移不得启动 Actor、发送告警、读取 Token 或改变非 X 来源。

Webhook providers v14 使用 `scripts/migrate_webhook_providers_v14.py --dry-run|--apply`，并以已完成 v13 为前置条件。已有数据库的普通 `ServiceStore.initialize()` 不得创建或标记 v14；版本缺失，或 marker 对应的必需列、Provider/签名组合、INSERT/UPDATE trigger 任一不完整时，API readiness、两组通知/告警设置与测试接口、Worker 都必须 fail closed。apply 前必须停止 API/Worker并跨过 heartbeat 安全窗；工具通过 SQLite backup API 生成 UTC `0600` 副本，为两张 setting 表 additive 安装 Provider/签名列与约束，清除旧 Webhook test metadata，并只在 row/trigger、`integrity_check` 与 `foreign_key_check` 全部通过后记录 marker。迁移不得发出 Webhook、读取真实 URL/签名 Secret 或重放旧 delivery。

Notification channels v15 使用 `scripts/migrate_notification_channels_v15.py --dry-run|--apply` 并要求 v14 已完成。普通 `ServiceStore.initialize()` 不得为已有库自动创建或标记 v15；缺 marker、逐渠道表/列、唯一索引或约束 trigger 时，readiness、通知/告警 API 与 Worker 全部 fail closed。apply 必须拒绝活动 Worker，跨过 heartbeat 安全窗，通过 SQLite backup API 创建 UTC `0600` 副本，重建两类渠道设置与 delivery 约束，并保留所有既有 Email/Webhook 设置和 delivery 历史，只把旧标量 active channel 迁为 enabled；Telegram 初始未配置。只有迁移前后计数、schema、`integrity_check` 与 `foreign_key_check` 全部通过后才记录 marker；重复 apply 幂等，迁移不读取 Secret、不外呼也不补发历史。

生产镜像不得包含 `.env`、`service.db*`、`data/config.json`、日志或备份；运行数据只能通过 VPS shared volume 注入。API 与 Worker 必须运行同一版本化镜像，liveness 暴露 revision。Inteliscope production image 必须从干净、revision-locked commit 在本机以 `linux/amd64` 构建并验收，压缩归档经校验上传后只在 VPS 执行 `docker load`；禁止在 `vps-tokyo` 对本仓库执行 Docker build。RSSHub 作为单独的 VPS-only 容器加入生产 Compose 网络并只绑定 VPS loopback；VPS 项目使用容器 DNS，本地项目经现有 Nginx 的 HTTPS path prefix 复用同一实例，不使用 SSH tunnel，也不在本地启动第二套 RSSHub。公网入口必须启用 RSSHub `ACCESS_KEY`、关闭该 location 的 access log 并保持容器端口不直接暴露；固定摘要的 `chromium-bundled` 镜像必须显式使用已验证的容器内 Chromium 路径和 RSSHub 非随机 UA，匿名 Bilibili Cookie 只能通过受控刷新脚本写入 SecretStore。匿名参数不构成 Bilibili 可用性保证；连续冷路由出现上游 `-352` 时必须停止高频探测，等待上游窗口恢复或切换第三方实例显式降级。RSSHub 这类 pinned third-party runtime image 可以在 VPS 直接 pull。RC1 数据迁移只能使用 SQLite backup API 生成独立副本，副本清除 session、heartbeat 和 active job 后再验证 Feed v2、integrity 与 foreign keys；源码发布包必须来自同一干净 commit 的 `git archive`，VPS 采用 API-only staging、显式 promote 和 Worker-first rollback。

### 3.11 Content Repair Boundary

`scripts/repair_user_content_v5.py` 是历史内容 inspect/apply/reconcile/enqueue 的唯一维护入口，`src/services/content_repair.py` 是 Worker `content_repair` 的唯一执行边界。repair 可以复用现有 source adapter、公共网络策略和媒体缓存，但必须强制 AI disabled，只匹配 `user_content_items` 已有 article id，并禁止调用 `FeedProductionService`。因此它不创建或替换 snapshot、不更新 Feed latest/history、不接触新文章，也不评估 schedule。

v5 apply 负责备份、旧 snapshot 线索恢复、模型无关 input hash 与 unresolved reason；reconcile 是旧 `NOT NULL` reason schema 与 captured 状态冲突的唯一显式升级入口，必须在无 active Job/Worker 时备份后事务执行。运行时存储层只维持“非空 captured 正文不保留 `source_body_not_available`”的不变量，不自动重建旧表。免费来源后续通过一次性 Worker 重抓。Apify social 被视为付费边界，批量工具必须 fail closed。详情 GET 永不联网，无法恢复的正文或过期媒体保留降级原因。

### 3.12 DeepSeek Analysis Boundary

DeepSeek 继续复用 OpenAI-compatible client，缺省 Base URL 和 Key env 归 AI client 所有；Secret API 只保存 ref metadata，真实值归 `SecretStore`。`UserAnalysisCache` 先查当前模型，再查同用户/同输入哈希的安全历史投影；跨模型命中只应用安全分析字段并保留来源标识，不写当前模型 cache。`user_content_items.analysis_input_hash` 由原始 `ContentItem` 计算，历史正文修复本身不触发分析。

本地切换必须先保持 AI disabled，使用轮换后的新 Key 执行一次 retry=0 smoke：同一事件循环先调用零推理 Token 的 `models.list()`，确认精确模型后才允许一次 completion；该请求省略 `temperature` 并关闭 SDK 与应用层参数降级重试，首次失败即终止；任一预检失败都保持 completion=0。成功后才启用 DeepSeek。默认本地拓扑仍为 API + Worker；VPS Tokyo Worker 不因该切换获得启动授权。

## 4. 禁止事项
1. 禁止入口层直接访问外部系统细节。
2. 禁止输出层反向驱动领域模型。
3. 禁止规则散落在路由、命令入口或模板中。
4. 禁止把某个运行时来源的字段命名作为全系统标准命名。
5. 禁止在 Web UI JS 中重新实现 Python taxonomy 规则。
6. 禁止把成本型流程作为 light runtime 的默认副作用。
7. 禁止 API、Worker、React 或 Remote MCP 读写 `radar-data.json`、`history-data.json`、`article-graph.json`、`data/horizon.db` 或旧 MCP run。
8. 禁止重新暴露 archive analytics、source-quality、Graph 或 feedback 路由。
9. 禁止用第三个 scheduler/dispatcher、旧摘要/通知或静态 publisher 承担用户 Feed schedule；偏好来源通知只能消费 3.8C 的提交后 outbox。
10. 禁止 Remote MCP 接受客户端指定的 user/workspace，或运行任何服务器侧 Agent/模型。

## 5. 扩展原则
新增来源、规则、输出或存储时，应先扩展抽象合同，再实现具体适配。

具体要求：

1. 新 source adapter：更新 source config model、adapter、tests，必要时更新 `docs/contracts/api/` 和 `project-defaults.yaml`。
2. 新 taxonomy 字段：先更新 `tag_policy.py`、`ContentItem` 和 Service snapshot contract，再更新 API/UI 合同。
3. 新输出面：先定义 API contract，再做 UI。
4. 新成本型能力：必须有配置开关、低成本验证路径和 degrade 行为。
