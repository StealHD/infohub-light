<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=API_CONTRACT.md -->
# Inteliscope InfoHub Light API / 接口合同

<!-- init-pro:section name=interface -->
## 1. 文档目的
本文件定义当前系统的公共接口合同，并区分当前 Service 产品面与 legacy compatibility surface。当前产品面是信息获取、用户 Feed 展示与历史留存；旧 CLI、静态 JSON、SQLite archive、feedback 和 Graph 只在明确标注的兼容边界内保留。

## 2. 设计原则
当前接口必须遵守：

1. 入口层只做请求接收、参数校验和应用编排。
2. 业务层不直接依赖外部系统原始字段。
3. 返回结果必须显式表达 capability / degrade 状态。
4. 输出结构必须对 Service UI、用户 Feed latest/history 和现有兼容调用方稳定。
5. 新字段优先使用 `channel/topics`，旧字段 `category/tags` 保持兼容 alias。
6. Service API 必须返回统一 envelope：成功为 `{"ok": true, "data": ...}`，失败为 `{"ok": false, "error": {"code", "message", "retryable", "action"}}`。
7. `/api/*` 的请求校验错误和未知路径也必须使用统一 envelope；静态资源 404 不属于 Service API 合同。

## 3. 标识合同
稳定标识：

1. `ContentItem.id`: `{source}:{subtype}:{native_id}`，由 scraper 适配层生成。
2. `normalized_url`: 内容去重使用的 URL 归一化键；legacy SQLite archive/Graph 可继续兼容读取。
3. `source_ref`: 单源刷新使用的引用，如 `rss:0`、`github:1`、`apify_social:0`、`hackernews`。
4. `article_id`: Feed item state 的稳定文章键，等同 `ContentItem.id`；legacy archive/Graph 沿用同一键。
5. `source_catalog.source_key`: catalog source 的幂等身份键，由 `src/services/source_type_registry.py` 生成，例如 `rss:https://example.com/feed.xml`、`rss:rsshub:bilibili:user_video:39627524`、`github_release:owner/repo`、`reddit_subreddit:localllama`。受控 RSSHub 来源的 key 不包含当前服务 Base URL，因此切换自建/第三方实例不改变订阅身份。

要求：

1. 多来源字段必须先进入 `ContentItem` 或 source config 模型，再给上层消费。
2. 不允许把某个上游字段名作为全系统标准名。
3. 历史 JSON 和旧 SQLite row 必须通过兼容层读回。

## 4. CLI 合同
### 4.1 `uv run horizon --hours <N>`
用途：运行一次完整抓取、去重、分析、静态 UI 写入，并按配置执行摘要、通知、归档或图谱。

请求参数：

1. `--hours`: 可选，覆盖配置中的时间窗口。

返回/输出：

1. 命令行阶段日志。
2. `data/site/radar-data.json`。
3. 可选 summaries、webhook/email 发送、`data/horizon.db` 和 `data/site/article-graph.json`。

capability / degrade：

1. `ai.enabled=false` 时跳过 AI scoring、enrichment、summaries、notifications、article graph，并写入可阅读静态数据。
2. source adapter 失败不应泄露密钥；错误应记录为可读日志。

### 4.2 `uv run horizon --source <source_ref> --hours <N>`
用途：立即刷新一个显式来源，服务于配置 UI 的低成本验证。

范围：

1. 跳过 notifications、summaries、enrichment、full-text、article graph。
2. 只发布该来源新增 item 到静态 UI。

返回字段：

1. `ok`
2. `source_ref`
3. `hours`
4. `fetched`
5. `raw_before_merge`
6. `merged`
7. `skipped_existing`
8. `analyzed`
9. `passthrough`
10. `web_ui_updated`

## 5. 本地 Web 配置 API 合同
入口：`src/ui/server.py`。

当前路由合同（兼容面单独标注）：

1. `GET /api/config`: 返回当前配置，必须隐藏密钥值，并附加 `taxonomy.channels/topics` 供频道 Select 与主题候选组件使用。
2. `POST /api/config/action`: 结构化修改配置。
3. `POST /api/source/test`: 测试单个来源可抓取性。
4. `POST /api/source/update`: 触发单源刷新。

请求规则：

1. 配置 API 只保存环境变量名，不保存密钥值。
2. 来源 topics 应写入 `topics`，同时保留 legacy `tags`。
3. Hub channel 应写入 `channel`；Telegram 的平台频道名继续使用 `channel`，Hub 频道使用 `hub_channel` 或兼容 `category`。
4. legacy CLI 的 `apify_social.subscriptions[].token_env` 可为单条 Apify 订阅指定 key 环境变量名；为空时使用全局 `sources.apify_social.token_envs` 轮换。该兼容规则不进入启用工作区池后的 Service API/Worker 路径。
5. `set_tags` 优先接受 `payload.topics` 数组，同时兼容旧 `tags` 换行/逗号字符串；值会 trim、去空并按大小写无关去重，每项最多 40 字、总数最多 100。显式空数组表示清空主题库，不得恢复内置默认主题。
6. `set_rsshub` 只接受 `payload.base_url`，保存为不含 userinfo、query 或 fragment 的 HTTP(S) Base URL；允许安全的反向代理 path prefix。该地址可指向工作区自建或第三方 RSSHub，但不进入 catalog source config、MCP guide/preview、Job result 或 Feed。可选主密钥只允许使用固定 SecretStore 环境变量 `RSSHUB_ACCESS_KEY`；`source_test` 与 Worker 抓取都按 RSSHub 的 `md5(route path + key)` 规则只发送 route-scoped `code`，配置/API/测试结果/日志不得保存或返回主密钥或派生 code。
7. `set_filtering` 的 additive `payload.rss_initial_fetch_window_hours` 只接受严格整数 `168` 或 `720`，boolean、浮点数、字符串及其他整数均返回可读配置错误；缺失配置按 `168` 处理。`payload.feed_window_days` 只接受严格整数 `7/14/30`，缺失按 `7` 处理；它只控制工作区统一的 Feed/History 展示边界。既有 `filtering.time_window_hours` 继续表示 24 小时日常抓取窗口，RSS 首次抓取窗口与 Feed 展示窗口互不替代。
8. 删除主题只改变未来候选词和 AI 分类偏好，不级联修改 catalog source、用户订阅或历史 snapshot；这些对象中的旧引用继续按兼容值返回。
9. `set_settings_bundle` 只接受非空 `payload`，其可选顶层字段精确为 `ai`、`feed_end_messages`、`rsshub`、`filtering`、`topics`，并分别复用 `set_ai`、`set_feed_end_messages`、`set_rsshub`、`set_filtering`、`set_tags` 的载荷与校验。每个已提交分区必须是 JSON object；空载荷、未知分区或任一非法分区返回 400。服务端必须在配置副本上完成全部分区的校验和应用，全部成功后只写盘一次；任一分区失败时不得写入任何分区。权限与响应结构保持不变，原有单项动作继续兼容。
10. `set_feed_end_messages` 只接受 `ai_generation_enabled`、`refresh_days`、`style_preset`、`style_prompt`、`list_count`。缺省值依次为 `false`、`7`、`restrained`、空字符串和 `12`；`refresh_days` 只允许严格整数 `1/7/30`，`style_preset` 只允许 `restrained|warm|light_humor`，`style_prompt` trim 后最多 500 字且不得包含 NUL，`list_count` 只允许严格整数 `3..30`。该开关独立于全局 AI 开关；只有两者都开启时 Worker 才可生成。

响应规则：

1. 成功响应必须包含 `ok: true` 或明确的结果字段。
2. 失败响应必须包含人类可读 `error`。
3. 外部来源测试失败必须给出可执行下一步，不暴露敏感 token。

## 5A. Service API 合同
入口：`src/api/server.py`，默认脚本：`uv run horizon-api`。

稳定接口：

1. `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/status`：基于数据库 cookie session 的用户登录状态。Service session 有效期读取 `HORIZON_AUTH_SESSION_TTL_SECONDS`；`HORIZON_AUTH_SECURE_COOKIE=true` 时登录与退出 Cookie 均带 `Secure`，始终带 `HttpOnly` 和 `SameSite=Lax`。
2. `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`：管理员管理小团体成员。`PATCH` 可更新 `role/enabled/display_name`，可选非空 `password` 表示重置成员密码；空字符串或未传表示不改密码。响应不得包含 `password_hash`。`POST /api/me/password` 允许任意已登录用户在验证当前密码后修改自己的密码；新密码长度为 8..200，当前密码错误返回 `400 invalid_current_password`。
3. `GET /api/dashboard/summary`：登录后订阅控制台汇总，返回当前用户、可见 source 数、订阅数、queued/running/failed job 数、最新 feed 时间和当前用户 `item_state_counts`。
4. `GET /api/catalog/source-types`：返回 Web setup type registry 元数据、必填字段、config template、additive `catalog_source_type` 和 `fields`。每个 field 精确包含 `name/label/input_type/required/default/options/min/max/help` 九个键；`input_type` 只允许 `text/url/number/select/boolean`，默认值、选项和范围必须与 registry validator 一致。`fields` 不包含 token、API key 或 `secret_env`；`secret_env` 仍是 catalog source 的独立属性。存储类型仍为既有八种；additive setup alias `youtube_channel` 的 `catalog_source_type=rss`。
5. `GET /api/catalog/sources`, `POST /api/catalog/sources`, `PATCH /api/catalog/sources/{id}`, `DELETE /api/catalog/sources/{id}`：公共、workspace、private source catalog；创建/更新必须通过 registry 校验 config 并写入 `source_key`；同一操作者重复或并发 POST 同一 key 必须幂等返回同一 source，跨用户 private key 碰撞和 PATCH key 碰撞返回统一 `409 source_key_conflict`；删除为软删除。公开 source 响应增加派生 `setup_type`；规范 channel feed 的 RSS 行投影为 `youtube_channel`，数据库 `type` 仍返回 `rss`。每个可见 source 同时返回当前 `avatar_url`，有 ready 头像时为登录保护的 `/api/media/*`，否则为空字符串。
5A. `POST /api/catalog/sources` 接受 `type=youtube_channel`，config `url` 可为 `UC…` channel ID、`/channel/UC…` 公开频道链接、规范 `channel_id` Feed、`@handle` 或 handle 频道页；服务统一保存 `https://www.youtube.com/feeds/videos.xml?channel_id=…` 并继续使用 `rss:<canonical-url>`。handle 只可通过固定 `youtube.com` 公共页的一次 10 秒、2 MB、零重定向请求读取 RSS link，不使用 API Key、Cookie 或登录状态；输入非法、未找到和上游异常分别返回 `invalid_source_config`、`youtube_channel_not_found`、`youtube_channel_resolution_failed`，失败不得落库。该 setup 默认 `keep_latest_item=true`，时间窗口为空时只补最近一条；创建并订阅不自动抓取。
6. `POST /api/catalog/import-config-sources`：管理员把 `data/config.json` 中旧 source 列表幂等导入 `source_catalog`，可 `dry_run`，默认为当前管理员创建 subscriptions。
7. `POST /api/catalog/sources/{id}/subscribe`, `DELETE /api/catalog/sources/{id}/subscription`：当前用户订阅或取消订阅一个可见 catalog source。新增或重新启用订阅时必须先复用 workspace 内该来源已经索引的稳定内容并返回 additive `reused_item_count`，不得因此创建抓取任务；取消 shared source 只删除当前用户订阅，最后一个 private owner 取消订阅时软停用无人引用来源。
7A. `GET /api/catalog/sources/{id}/usage` 仅在客户端显式请求时计算并返回 `subscriber_count/enabled_subscriber_count`；`POST /api/catalog/sources/{id}/share` 只允许 private owner 把自己的来源提升为 `workspace|public`。提升后 `owner_user_id=null`，来源地址和管理权转交管理员，原订阅者随后取消订阅不得影响其他成员。
8. `GET /api/me/subscriptions`, `POST /api/me/subscriptions`, `PATCH /api/me/subscriptions/{id}`, `DELETE /api/me/subscriptions/{id}`：当前用户订阅配置。列表 GET 可选 `schedule_view=full|summary`，默认 `full` 保持兼容；`summary` 只从每条内嵌 schedule 省略 `last_job/active_job`，其他订阅与计划字段、排序、用户隔离均不变。`PATCH` 在 `enabled=false` 时可携带 `on_disable=keep|save|dismiss`；`save` 在从 Feed 移除前收藏该来源现有内容，`dismiss` 把它们归入忽略集合，`keep` 仅为兼容调用方保留且不作为默认 UI 选项。其他情形携带 `on_disable` 返回 `400 invalid_disable_disposition`。
9. `GET /api/me/source-health`：读取当前登录用户每条订阅的生产抓取健康状态；精确 schema、权限、状态与聚合语义见下文。
10. `GET /api/me/feed-schedule`, `PATCH /api/me/feed-schedule`：读取或修改当前用户自己的 Feed 自动刷新计划；GET 可选 `view=full|summary`，默认 `full` 保持兼容，精确字段、权限和错误语义见下文。
10A. `GET /api/me/subscriptions/{id}/schedule`, `PATCH /api/me/subscriptions/{id}/schedule`：读取或修改当前用户指定订阅的自动单源抓取计划；只创建现有 `source_fetch`，不新增同步抓取入口。
10B. `GET /api/me/notification-settings`、`PATCH /api/me/notification-settings`：读取或修改当前用户自己的偏好来源通知渠道；`POST /api/me/notification-settings/test` 只向已保存渠道发送一条明确的模拟消息，不创建抓取任务、Feed snapshot 或内容投递记录，也不移动任何新内容基线。精确字段、write-only 目的地和旧数据规则见下文。
10C. `GET/PATCH/DELETE /api/admin/notification-email-transport`：Owner/Admin 读取、修改或删除工作区唯一的 Service 邮件发送配置；`POST /api/admin/notification-email-transport/test` 使用请求内一次性 `recipient_email` 验证当前 generation。精确 Provider、SecretStore、测试门禁和暂停规则见下文。
11. `POST /api/jobs/source-test`, `POST /api/jobs/source-fetch`, `POST /api/jobs/user-feed-refresh`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `GET /api/jobs/{id}`, `GET /api/jobs`：创建、取消、重试和查询异步任务。`source_fetch` 带 `source_id` 时表示按 catalog source 精准抓取当前用户作用域。Job 列表默认 `view=full&scope=workspace&include_active=false` 保持兼容；`view=summary` 只返回列表展示字段及有界结果摘要，并把 `error_code/error_message` 分别限制为 64/240 字符；`scope=me` 限定当前用户，`include_active=true` 在无 status 过滤时确保 queued/running Job 不因 limit 被裁掉。可重复的 `job_type` 同时过滤最近记录和补入的 active 记录；单次最多 20 个、每个只允许 1–64 个安全字母数字、下划线或连字符，非法输入返回 `400 invalid_request`。`GET /api/jobs/{id}` 始终返回既有完整详情。
12. `GET /api/feed/latest`, `GET /api/feed/history`, `GET /api/feed/search`：登录后访问目标用户的时间分层内容。`latest` 支持 `hide_dismissed=true`、`unread_first=true`、`saved_first=true`，并默认 `view=compat` 保留 `today_items`；`view=canonical` 仅省略可由 `items[].timeline_bucket` 推导的 `today_items`，其余字段与顺序不变。`history` 返回当前 Feed 窗口之前的 schema-v2 用户历史；`search` 检索当前用户 Feed、在线历史和冷归档元数据，精确语义见下文。
12A. `GET /api/feed/saved?limit=200&offset=0` 按 `saved_at DESC` 返回当前用户稳定收藏；`GET /api/feed/ignored?limit=200&offset=0` 按 `dismissed_at DESC` 返回当前用户忽略集合；`GET /api/feed/items/{article_id}` 按需返回 Presentation v2 详情。三者只读 `user_content_items + user_item_state`，不得用另一用户或最近 snapshot 兜底。
12B. `GET /api/media/{asset_id}` 登录后读取 Worker 已缓存的同源图片或头像。内容图片只允许所属用户读取；workspace/public 来源头像允许同 workspace 用户读取；private 来源头像只允许 owner 读取；越权和不存在统一返回 404。Feed、历史、搜索、收藏、忽略和详情响应不得暴露上游临时媒体 URL，所有可展示图片 URL 必须是 `/api/media/*`。这些内容集合在读取时按 `source_id` 覆盖投影当前 ready `presentation.source.avatar_url`，没有 ready 头像时固定为空字符串，不得继续返回 snapshot 中过期的 asset ID。内容图片的稳定身份为 `workspace + user + article + asset_kind + checksum`；同内容的 CDN 域名或查询签名变化只更新远端线索并复用既有 ready asset，不得写重复本地文件。
12C. `GET /api/feed/end-messages` 允许所有登录用户读取当前 workspace 的三个共享文案列表。`data` 精确包含 `schema_version=1/source/status/generation/generated_at/last_attempt_at/next_refresh_at/retry_at/last_error_code/scenes`；`source` 为 `builtin|ai`，`status` 为 `disabled|pending|refreshing|ready|degraded`，`scenes` 的键精确为 `empty/first_end/repeat_end`。时间字段允许 `null`，错误只返回安全 code，不返回模型正文、提示词、凭据或异常。响应使用 `Cache-Control: no-store`。
12D. `POST /api/admin/feed-end-messages/refresh` 只允许 `owner/admin`，且只把当前 workspace 幂等标记为待刷新，不在请求内调用模型或创建普通 Job。全局 AI 或触底文案 AI 开关关闭时返回 `409 feed_end_messages_disabled`；成功返回与 GET 相同的状态 envelope 并使用 `Cache-Control: no-store`。
13. `GET /api/me/item-state`, `PATCH /api/me/items/{article_id}/state`：当前产品使用的已读、收藏、稍后读和忽略状态接口。`POST /api/me/items/{article_id}/feedback` 与 feedback 表只为既有调用方兼容保留，默认 UI 不调用。
14. `GET /api/archive/items`, `GET /api/archive/trends`, `GET /api/archive/facets`, `GET /api/archive/source-quality` 是 compatibility-only archive analytics；默认阅读 UI 和订阅 UI 均不调用，接口存在不等于当前产品能力或路线承诺。`GET /api/archive/graph` 同为兼容路由，但固定返回 disabled 安全空响应。
15. `GET /api/config`, `POST /api/config/action`：配置页兼容 facade。读取时返回旧配置页可消费的 `config/env_status`，并附加 `taxonomy{channels,topics}`；source 列表由 `source_catalog + user_subscriptions` 合成，非 source 全局配置仍写 `data/config.json`。`set_tags` 的精确数组/空数组/兼容字符串语义及 `set_rsshub` 的 credential-free Base URL 语义见上文。
16. `POST /api/source/test`, `POST /api/source/update`：配置页兼容 facade。只创建 `source_test/source_fetch` job，不在 Web 请求内同步抓取。
17. `scripts/service_api_smoke.py`：运行中核心 API smoke，不访问外网源，不执行抓取，只验证登录、读 API、管理员 `/api/users` 读取、可选 private source/job/item-state 和 `member-ui-smoke` 写路径。
18. `GET /api/health/live`：表达 API 进程存活，并返回 `status/version/revision/built_at` 以识别不可变镜像；`GET /api/health/ready`：依次检查数据库、Feed v2、user content v4、content timeline v11、Apify Actor routing v13、Webhook providers v14、ActorOps logical-v15（global version 17）、Discovery limits v16（global version 18）与 Canary batches logical-v17（global version 19）migration、数据库内至少一个 enabled user 和可选 Worker readiness，未就绪返回 503 的统一 error envelope。Webhook v14 不只检查 marker，还校验两张设置表的必需列、Provider/签名组合和约束 trigger；ActorOps 后续迁移也同时校验 version/name/checksum 三元组与完整安全表形状，任一缺失都 fail closed。fresh DB 没有可登录用户时返回 `auth_not_configured`，action 要求设置 `HORIZON_AUTH_PASSWORD` 或 `HORIZON_AUTH_PASSWORD_HASH` 后重启；一旦数据库已有 enabled user，后续 readiness 不再依赖 bootstrap 密码环境变量。ready 成功响应额外返回 `logging_status=ready|degraded`；日志 sink 降级只用于运维诊断，不单独把 readiness 从 200 改为 503。
19. `GET /api/ops/runtime`：仅 `owner/admin` 可读，返回 Worker heartbeat、队列积压、最老 queued job、stale running、最新 snapshot 年龄，以及用户 Feed 计划字段、`source_schedule_count/overdue_source_schedule_count/next_source_scheduled_at` 和三个 Source Health 聚合字段；`schedule_stats` 包含最近评估、最近入队和 skip reason 计数。响应不返回 claim token、source payload、密钥或 Webhook。
20. `GET /api/admin/secrets`、`POST /api/admin/secrets`、`PUT /api/admin/secrets/{id}/value`、`DELETE /api/admin/secrets/{id}`：仅 `owner/admin` 管理 AI/Apify 密钥引用和值。值只在 create/rotate 请求中出现，任何成功或失败响应都不得回显。`GET /api/admin/secrets/{id}/quota` 同样仅允许 `owner/admin`，且只为同 workspace、已配置的 Apify secret 返回下述安全额度投影；非 Apify 不触发上游请求。
20A. `GET /api/admin/apify-key-pool`：仅 `owner/admin` 读取当前 workspace 的池。`data` 精确包含 `schema_version=1/enabled/generation/status/active_secret_id/draining_secret_id/blocked_reason/retry_at/members`；`status` 为 `empty|ready|draining|blocked|exhausted`。每个 member 只含 `secret_id/position/status/blocked_until/cycle_end_at/last_checked_at/last_error_code/active_run_count`，其中 member status 为 `active|standby|draining|depleted|invalid`。不得返回 env、Token、账号资料、额度原始响应、远端 runId 或 datasetId。
20B. `PUT /api/admin/apify-key-pool/order` 接受完整且无重复的 `secret_ids` 与整数 `expected_generation`；集合缺失/多余为 `invalid_request`，generation 不匹配为 `apify_key_pool_conflict`，成功后 generation 原子加一。启用池时 active/draining/仍有非终态 Run 的 Key 不得通过排序替换。`POST /api/admin/apify-key-pool/{secret_id}/drain` 只操作同 workspace 成员并保持幂等；没有活跃 Run 时可直接完成切换，有 Run 时返回当前 `draining` 状态并由 Worker 持续 reconcile。
20C. `GET /api/admin/apify-actor-routes/x/profile` 返回 `schema_version=1/route/generation/status/active_candidate_id/last_switch_reason/last_switch_at/retry_at/blocked_reason/quota/limits/candidates`；route status 只允许 `ready|degraded|exhausted|budget_blocked|blocked`，候选 state 只允许 `closed|open|half_open|disabled|probationary`。candidate 只含公开 Actor 名、顺序、24 小时成功率、商城估价、最近/平均实际费用、安全时间/错误码和动作能力；quota 只含 USD 已知总剩余额度、X 可分配额、24 小时消费、预计天数和快照时间。不得返回 Token、Key env/account、目标账号、远端 Run/Dataset、Actor input 或原始错误。
20D. `PUT /api/admin/apify-actor-routes/x/profile/order` 接受完整无重复 `candidate_ids + expected_generation`；enable/disable mutation 只接受 `expected_generation`，均以 generation conflict fail closed。`POST .../candidates/{id}/canary` 精确接受同 workspace 已启用 X/profile `source_id`、`expected_generation` 与 `confirmation="确认付费试跑"`，只创建 `priority=100/max_attempts=1` 的 `source_test`；Canary 的 Actor input 强制最多一条结果，同候选已有 queued/running Canary 或自然 paid attempt 时拒绝创建，自然任务也必须跳过 queued/running Canary 占用的候选，路由或 Key Pool 运行开关关闭时 fail closed。每次付费尝试必须重新确认，通用 Job retry 永远拒绝该 payload。Dami 必须由至多两个当前已启用的不同 X/profile source 分别成功返回真实帖子后才进入 probationary；只有一个已启用 source 时只要求该 source。48 小时到期即使零样本也按 0% 自动禁用，达到 95% 才转为 closed。
20E. `GET/PATCH /api/admin/apify-actor-alert-settings` 与 `POST .../test` 管理工作区运行告警。PATCH 接受 `enabled/channel/events`、显式 `webhook_provider` 与 write-only `email_address/webhook_url/webhook_signing_secret`；channel 为 `email|webhook`，events 为 `actor_switched|route_exhausted|quota_low|budget_blocked|start_outcome_unknown|recovered` 的唯一集合，首次 partial PATCH 未提交 events 时默认全开。GET 返回 `schema_version=2`、configured/readiness 布尔值、当前有效 Provider、Provider 是否显式选择、签名是否配置、验证模式、七类安全 Provider options 和最近测试/告警状态，不回显目的地或签名 Secret；最近告警状态只投影与当前 settings generation 一致的 delivery，配置变化后不得用新渠道或验证模式重解释旧成功。`GET /api/admin/apify-actor-alert-incidents?limit=20` 返回最多 100 条安全 incident，公开 delivery status 为 `pending|sent|failed|unknown|skipped`，不得返回 payload 或 transport 细节。Webhook 使用下述共享 Provider Registry、精确 URL 校验和 ACK 语义；只有飞书/Lark V2 与钉钉允许可选签名。保存成功仅表示配置原子写入，测试结果中的 `verification=provider_accepted|http_accepted` 才分别表示平台业务响应通过或通用端点返回 HTTP 2xx，两者都不保证终端已经展示。
20F. `GET /api/admin/storage/summary`、`POST /api/admin/storage/plans`、`POST /api/admin/storage/plans/{id}/apply`、`GET /api/admin/storage/archives`：仅 `owner/admin` 管理当前工作区的存储预演、标准清理、冷归档和恢复；永久删除归档只允许 `owner`。精确两阶段、安全删除和归档语义见下文。
21. `GET /api/me/agent-delegations`、`POST /api/me/agent-delegations`、`PATCH /api/me/agent-delegations/{id}`、`DELETE /api/me/agent-delegations/{id}`、`DELETE /api/me/agent-delegations/{id}/record`：当前用户管理自己的 OpenClaw 数据连接。GET 返回 `enabled/mcp_url/subscription_writes_enabled/token_ttl_days/max_active/connections`，并返回 `openclaw_chat{enabled,default_gateway_url,protocol_version=4,target_version="2026.7.1"}`；该对象只是公共运行配置，不包含或接收 Gateway 凭证。每个 connection 返回稳定的 `access=read|subscriptions_write`、`diagnostics_scope=self|workspace` 与 `scopes`。POST 接受 `name`、可选 `access`（缺省 `read`）和可选 `diagnostics_scope`（缺省 `self`）；`read` 授予 `inteliscope:read`，`subscriptions_write` 另授予 `inteliscope:subscriptions:write`，只有显式 workspace 诊断连接再授予 `inteliscope:diagnostics:read`。workspace 诊断连接只允许当前实时角色为 `owner/admin` 的用户新建，既有连接永远保持原 scopes，PATCH 不能提权，角色降级后工作区查询立即拒绝。写连接仅 `owner/admin/member` 可在 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=true` 时新建；viewer 返回 `forbidden`，开关关闭返回 `subscription_writes_disabled`。令牌固定 90 天、最多 5 个有效连接，且只在 201 + `Cache-Control: no-store` 响应中返回一次明文令牌；PATCH 仅重命名；基础 DELETE 保持幂等吊销。显式 `/record` DELETE 只允许当前用户永久删除一条 `revoked_at IS NOT NULL` 的记录并返回 `deleted=true`；有效或仅到期的记录返回 `agent_delegation_not_revoked`（409），非本人或不存在返回 `not_found`（404），既有 proposal 依外键级联删除，其他连接与业务数据不变。Remote MCP 总开关关闭时仍可查看、吊销和删除已吊销记录，但创建返回 `remote_mcp_disabled`。
22. FastAPI 默认托管 React Service UI：`/assets/*` 为带内容哈希的 immutable 资源，构建根目录中真实存在的静态文件按实际 MIME 返回；`/favicon.ico` 是显式可缓存的空兼容响应。只有不含文件扩展名的前端深链可回退到 no-cache `index.html`，不存在的带扩展名路径返回普通静态 404；`/api/*`、`/mcp`、`/mcp/*` 和任何路径穿越输入永不进入 SPA fallback。支持且未以 `q=0` 明确拒绝 gzip 的客户端，对不小于 1024 bytes 的合格响应使用压缩级别 5；流式或不适合压缩的响应仍由框架保持原语义。`HORIZON_SERVICE_UI_VARIANT=react|legacy` 控制 Service 前端，默认 `react`；React 构建缺失时可安全回退 legacy。`/mcp` 为精确协议路由，不通过重定向修正路径。
23. API 为每个请求生成不可伪造的 `req_<uuid>`，忽略客户端 `X-Request-ID`，并在应用返回的 `/api/*` 与 `/mcp` 响应中写入 `X-Request-ID`。未知服务端异常固定返回 HTTP 500 的 `internal_error` 安全 envelope 与相同 request ID，不向测试客户端或调用方传播原异常文本。诊断日志没有 REST 路由、SPA 页面或前端数据接口；浏览器只能取得上述 request ID，不能取得日志文件或事件正文。

稳定前端路由为 `/feed?mode=featured|all|daily&item=<id>`、`/later?item=<id>`、`/saved?item=<id>`、`/history?item=<id>`、`/subscriptions`、`/agents`、`/settings`、`/login`。旧根路径 `?view=featured|all|daily|readLater|history|subscriptions|config` 只做客户端重定向，不改变 API 合同。

权限规则：

1. 第一版固定单 workspace。
2. 角色为 `owner/admin/member/viewer`。
3. `owner/admin` 可管理用户、重置成员密码和 public/workspace source。
4. 普通用户只能创建和修改自己的 private source，只能管理自己的 subscriptions。
5. job 查询仅允许 job owner 或管理员访问。
6. 配置页 source action 中，`owner/admin` 新建 source 默认 `public`，`member` 新建 source 默认 `private`，`viewer` 不能创建或修改 source。
7. 配置页删除 source 对管理员和 private owner 表示软删除 catalog source；普通成员删除 shared source 表示取消自己的订阅。
8. 私人信息流、Feed 历史和兼容 archive 路由默认不公开，未登录访问 `/api/feed/*` 和 `/api/archive/*` 返回统一 `unauthorized` error envelope。
9. `viewer` 为只读角色：可登录查看 feed、catalog、subscriptions、jobs 和 item state，但不得创建/修改 source、订阅配置、抓取任务、item state 或兼容 feedback。
10. `owner/admin` 可使用 `user_id` 查询同 workspace 成员的 Feed 及兼容 archive；`member/viewer` 查询他人时返回 `forbidden`。
11. `member` 不能修改或删除 public/workspace source；只能管理自己的 private source、自己的 subscriptions、自己的 jobs 和自己可见 feed item 的行为状态。
12. AI、过滤、全局标签库、Webhook 及其他非 source 全局配置只允许 `owner/admin` 修改；`member/viewer` 必须返回 `forbidden`。member 通过兼容 source action 提交的 topics/personal tags 只能写目标 source/subscription，不得回写全局 `data/config.json`。
13. `owner/admin/member` 只能读取和修改自己的 Feed schedule；该接口不接受 `user_id` 代查。`viewer` 可以 GET 自己的状态，但 PATCH 返回 `forbidden`。
13A. 订阅级 schedule 同样只允许操作当前用户自己的订阅，不接受 `user_id` 代查；`viewer` 可以 GET，PATCH 返回 `forbidden`。订阅、来源或用户未启用时不得开启。
13B. 偏好来源通知设置和测试同样只操作当前用户，不接受 `user_id` 代查。所有角色可以 GET；`viewer` 的 PATCH 与测试返回 `forbidden`。订阅通知开关只能修改当前用户自己的订阅，且 `personal_only` 或已停用订阅不得开启。
13C. 工作区邮件发送配置的 GET/PATCH/DELETE/test 只允许当前 workspace 的 `owner/admin`；`member/viewer` 均返回 `forbidden`。服务层在持有 SQLite 写锁后必须重读 actor，防止并发降权后的旧请求修改配置或 SecretStore。
14. `owner/admin/member/viewer` 都可以读取自己的 Source Health；`GET /api/me/source-health` 不提供跨用户代理，即使 `owner/admin` 附带 `user_id` 查询参数也仍只返回当前登录用户的数据。
15. 密钥列表、创建、轮换、删除、额度查询、Apify Key 池读取/排序/排空、X Actor 路由读取/管理/Canary、Apify 运行告警设置/测试/incident 读取以及 legacy catalog `secret_env` 选择只允许 `owner/admin`；`member/viewer` 均返回 `forbidden`。池模式下任何角色都不再得到 Apify 来源级 `secret_env`；非管理员其他 source 响应只给出 `secret_configured`，不得暴露环境变量名。
16. `owner/admin/member/viewer` 都可创建、查看、重命名和吊销自己的 read Agent delegation，也可显式删除自己已吊销的单条记录；只有 `owner/admin/member` 可创建 subscription-write delegation，且受写开关约束。不存在把既有 read connection 提升为 write 或 workspace 诊断的接口；不提供管理员代管或跨用户删除接口。delegation 令牌始终映射其创建者，所有 Feed、来源、订阅、Job 与确定性诊断工具即使面对 `owner/admin` 也只读取创建者数据；唯一例外是显式授予的新连接可让 `query_operation_logs` 读取同 workspace 的脱敏故障事件，不能据此读取其他用户业务对象。禁用用户时必须在同一事务永久吊销其全部连接，重新启用不恢复旧令牌。
17. 触底文案 GET 只返回 workspace 共享且不含用户内容的文案池，所有登录角色可读；立即刷新和触底文案配置只允许 `owner/admin`，`member/viewer` 返回 `forbidden`。

错误 envelope 规则：

1. 未登录返回 `unauthorized`，权限不足返回 `forbidden`，不可见或不存在资源返回 `not_found`。
2. Pydantic/body/query 校验失败返回 `invalid_request`，HTTP status 使用 400。
3. 不存在的 `/api/*` 路径返回 `not_found` envelope；不得返回 FastAPI 默认 `{"detail": ...}`。
4. 核心错误码包括：`unauthorized`、`forbidden`、`not_found`、`invalid_request`、`invalid_source_config`、`invalid_feedback_type`、`invalid_feed_schedule`、`invalid_source_schedule`、`invalid_disable_disposition`、`invalid_subscription_notification`、`invalid_notification_settings`、`invalid_notification_destination`、`notification_destination_required`、`notification_channel_unavailable`、`notification_test_failed`、`notification_test_outcome_unknown`、`notification_test_rate_limited`、`invalid_current_password`、`source_schedule_unavailable`、`no_enabled_subscriptions`、`quota_exceeded`、`job_not_cancelable`、`job_not_retryable`、`feed_end_messages_disabled`。Webhook 配置与投递另外区分 `invalid_webhook_provider`、`invalid_webhook_url_for_provider`、`invalid_webhook_signing_secret`、`webhook_signing_not_supported`、`webhook_url_required_for_provider_change`、`notification_webhook_target_blocked`、`notification_webhook_unavailable`、`notification_webhook_rate_limited`、`notification_webhook_outcome_unknown`、`notification_webhook_response_invalid` 与 `notification_webhook_provider_rejected`。工作区邮件服务另外区分 `invalid_email_transport_provider`、`invalid_email_transport_sender`、`invalid_email_transport_region`、`invalid_email_transport_username`、`email_transport_not_configured`、`email_transport_test_required`、`email_transport_test_rate_limited`、`email_transport_credential_unavailable`、`notification_email_authentication_failed`、`notification_email_recipient_rejected`、`notification_email_rejected` 与 `notification_email_unavailable`。密钥额度查询另外区分 `quota_not_supported`（400、不可重试）、`secret_not_configured`（409、不可重试）、`apify_quota_unauthorized`（422、不可重试）、`apify_quota_forbidden`（422、不可重试且不切 Key）、`apify_quota_rate_limited`（429、可重试）、`apify_quota_unavailable`（503、可重试）和 `apify_quota_invalid_response`（502，响应畸形时可重试、其他上游 4xx 时不可重试）。Apify 池/Actor 管理与任务还区分 `apify_key_pool_managed`、`apify_key_busy`、`apify_key_pool_conflict`、`apify_key_drain_pending`、`apify_key_pool_exhausted`、`apify_key_pool_blocked`、`apify_key_rejected`、`apify_start_outcome_unknown`、`apify_run_reconcile_required`、`invalid_apify_actor_route`、`apify_actor_routing_disabled`、`apify_actor_route_generation_conflict`、`apify_actor_route_exhausted`、`apify_actor_job_active`、`apify_actor_job_budget_exhausted`、`apify_actor_budget_blocked`、`apify_actor_quota_unknown`、`apify_actor_canary_unavailable`、`apify_actor_canary_source_required`、`apify_actor_canary_active`、`apify_actor_canary_required`、`invalid_apify_actor_alert_settings`、`apify_actor_alert_test_failed`、`apify_actor_alert_test_outcome_unknown` 与 `apify_actor_alert_test_rate_limited`；公开 message 只描述安全状态和下一步，不得拼接上游正文、Token、runId、datasetId 或告警目的地。Feed 搜索另有 `invalid_query`、`query_requires_submit`、`invalid_limit`、`invalid_cursor`（均 400）与可重试 `search_timeout`（503）。存储治理稳定错误为 `storage_operation_invalid`、`storage_plan_invalid|not_found|unavailable|expired|changed`、`storage_migration_required`、`storage_confirmation_required`、`storage_archive_required|not_found|invalid|corrupt|unavailable|not_restored|in_use|deleted` 和 `storage_restore_conflict`；公开 message 不得包含路径、SQL、确认短语、候选 ID、正文或归档 manifest。

## 5B. Remote MCP 合同

1. Remote MCP 由现有 `horizon-api` 以 Streamable HTTP 精确暴露在 `/mcp`，固定 `stateless_http=true` 且不保存会话。功能默认关闭；启用时 `HORIZON_REMOTE_MCP_PUBLIC_URL` 必须以 `/mcp` 结束，loopback 可用 HTTP，其他主机必须 HTTPS。Host/Origin 白名单从该 URL 推导；无 Origin 的原生客户端允许，其他浏览器 Origin 拒绝。MCP adapter 直接使用 Service/Store，禁止内部 HTTP 回环。
2. 认证只接受 `Authorization: Bearer <delegation token>`。所有调用均需 `inteliscope:read`；写工具还需 `inteliscope:subscriptions:write`、写开关开启和实时可写角色；工作区诊断还需 `inteliscope:diagnostics:read` 与实时 `owner/admin` 角色。无效、过期、吊销、用户禁用或 scope 状态不一致统一 HTTP 401，写 scope 缺失为 `write_scope_required`（403），workspace 诊断授权/角色不足为 `diagnostics_scope_required`（403），viewer 写入为 `forbidden`；不提供 OAuth、登录、刷新或动态客户端注册。数据库仅保存完整令牌 SHA-256 和展示前缀，令牌格式为 `ih_mcp_v1_` 加 32-byte URL-safe 随机值。
3. 工具清单精确为 17 个：13 个读工具 `get_my_feed`、`get_item`、`list_subscriptions`、`source_health`、`list_jobs`、`get_job`、`get_source_setup_guide`、`search_bilibili_users`、`resolve_source`、`list_available_sources`、`diagnose_source`、`diagnose_job`、`query_operation_logs`；三个 prepare `prepare_create_subscription`、`prepare_update_subscription`、`prepare_delete_subscription`；唯一 apply `apply_subscription_change`。读工具均标记 read-only、non-destructive、idempotent；会访问固定公开端点的 `search_bilibili_users` 与 registry 驱动的 `resolve_source` 标记 open-world，其余读工具均为 closed-world。prepare 标记非只读、non-destructive、非幂等、closed-world；apply 标记非只读、destructive、非幂等、closed-world。工具结果直接返回 structured content，不包装 REST `{ok,data}`。
   OpenClaw read connection 的客户端 `toolFilter` 精确包含上述 13 个读、引导/查询/发现与诊断工具；subscription-write connection 才额外包含三个 prepare 与一个 apply。已知旧版标准 12/16 工具过滤可由本地 setup 脚本精确升级；自定义过滤必须原样保留并提示人工加入 `resolve_source`。该过滤只控制客户端可见性，不改变服务端 scope 与逐调用鉴权。
4. 所有输入拒绝未声明字段与身份字段 `user_id/workspace`，以及合同未注册的任意 URL、SQL、文件路径或密钥。ID 最长 128；确认短语 1..160；Feed/Job 列表 `limit` 默认 20、最大 50；`get_my_feed` 的 `offset` 最大 10,000；`get_item.body_offset` 为 0..20,000，`max_body_chars` 默认 4000、范围 1..8000。`search_bilibili_users.query` 只接受规范化后 1..50 字符的账号名称并拒绝 URL，`limit` 默认 5、范围 1..5。`resolve_source.source_type` 与 private create 的 `type` 是 1..64 的 registry 字符串，未知值运行时统一 `invalid_request`；`input` 为 1..2,048 字符，`candidate_urls` 最多 5 个且每个 1..2,048 字符，`limit` 默认/最大 5。候选 URL 只有在对应 adapter 已注册固定官方主机和路径语法时才可联网。`query_operation_logs` 的 `scope=self|workspace` 缺省 `self`，`lookback_hours` 默认 24、范围 `1..720`，`limit` 默认 50、最大 100，可选 category、outcome、`minimum_level=info|warning|error` 以及 Job/source/subscription/request ID，单次最多扫描 20,000 行；workspace scope 必须提供任一 ID，或把最低级别设为 warning/error，否则返回 `diagnostics_filter_required`（400）。详情保持原字段兼容并增加 `body_offset/body_end/body_total_chars/body_has_more/next_body_offset`；`body_truncated=true` 在最后一段仍成立时表示采集阶段已经截断，客户端不得声称已读取完整网页。来源类型、创建/更新字段、计划周期、priority 及 scope 均由严格 Pydantic 模型和 registry/共享 mutation service 校验。`get_my_feed` 只接受 `latest/history/saved/later`；列表不返回完整正文、媒体、原始 metadata 或 legacy reason。跨用户 ID 与不存在 ID 统一 `not_found`。
5. `get_source_setup_guide` 仅返回九类公开来源的 registry 指导和 Web/密钥前置条件；新增公开类型 `bilibili` 映射到 catalog `rss`，且 private create 的 config 精确为 `{"site":"bilibili","route_key":"user_video","params":{"uid":"<positive numeric UID>"}}`，可选 `keep_latest_item`。`search_bilibili_users` 只访问固定的 Bilibili 首页与官方用户搜索端点：先在单次内存 client 中取得匿名设备 Cookie，再禁用环境代理和 redirect，每个固定请求使用 4 秒 connect/8 秒 I/O timeout，搜索响应最多读取 512,000 bytes；成功/空结果缓存 300 秒，上游不可用缓存 30 秒。结果只含 `availability`、`match_status`、唯一精确命中的 `resolved_user`、最多五个 `{uid,name,profile_url,exact_name_match}` 候选、计数/截断和稳定错误码；不返回签名、粉丝数、视频数、Cookie、上游正文或请求细节。候选名称是 `untrusted_public_metadata`；只有唯一规范化精确同名才自动解析 UID，同名多候选必须由用户选择，上游不可用不得猜测。OpenClaw 不得提供 RSSHub URL、任意 route path、账号 Cookie、ACCESS_KEY 或其他凭据。`list_available_sources` 只返回当前用户可见、启用来源的安全摘要、`secret_configured` 布尔值与经过投影的 `public_target`；受控 Bilibili target 精确为 `site/route_key/params` 且不含 Base URL。公网 direct RSS 可返回完整公开 feed URL；含凭证、私网、loopback 或无法安全分类的 direct target 统一返回 `web_setup_required`。它们不返回原始 source config、`secret_env`、其他用户身份或任何密钥。普通 subscription/job/health 投影继续排除 `personal_tags`、source config、secret ref、workspace/user、worker、claim/lock、payload 和原始 result。
5A. `resolve_source` 是唯一通用来源解析入口；服务端不做开放式网页搜索。仅名称且没有候选时返回 `discovery_required`，由 OpenClaw `web_search` 收集最多五个官方候选并将结果按不可信公开 metadata 处理。第一批只有 `youtube` adapter：直接接受 `@handle`、官方 `/@handle` 或 `/channel/UC…` 页面、UC channel ID 与规范 channel Feed；候选数组只接受 `https://www.youtube.com` 的 handle/channel 路径，在任何联网前拒绝 watch、video、Shorts、playlist、Music、第三方、userinfo、query、fragment 与显式端口。handle 页面固定 10 秒、零重定向、`Accept-Encoding: identity`，使用公共网络 DNS pinning 和显式 2,000,000-byte 前缀模式；该模式最多保留上限字节并通过 `infohub_body_truncated` 标记截断，默认网络 fetch 仍对超长声明或流严格失败。找到唯一规范 Feed 后再固定读取不超过 512,000 bytes 的官方 Atom，核对 `yt:channelId`、title、alternate channel link 与请求 Feed 身份；前缀已截断且未找到 link、多个 link、畸形或身份不一致均为可重试上游失败。不得为 YouTube 或生产 VPS 放宽 RFC1918、loopback、任意 RSS 或 `198.18.0.0/15`。
   结果状态固定为 `resolved|ambiguous|discovery_required|not_found|unavailable|web_setup_required`。候选只含 `display_name/public_url/source_type/subscription_state/data_trust` 与可选 `resolution_ref/expires_at`，不得返回单独 channel ID 字段、规范 Feed、source config 或内部 source ID。已订阅候选不生成 ref。其余唯一候选生成 `asr_<uuidhex>`：绑定同一 workspace/user/delegation、10 分钟到期、每 delegation 最多 20 个有效引用，同一 actor + 规范来源在有效期内复用；引用 envelope 只保存经 registry 验证的 existing/private planner 输入。跨 actor 或不存在统一 `not_found`，同 actor 过期为 `source_resolution_expired`，损坏为 `invalid_source_resolution`。隐藏 catalog source 不得被投影；若其 source key 冲突，prepare 仍只返回既有通用 `source_key_conflict`。
6. 每项订阅变更固定为 `prepare → preview → exact confirmation → apply`：prepare 只写一条密封 proposal 与安全 preview，不修改业务订阅；apply 是唯一业务写入入口。create source union 精确支持 `{mode:existing,source_id}`、`{mode:resolved,resolution_ref}` 与 `{mode:private,type,display_name,config}`；resolved ref 只在 prepare 内投影为原有 existing/private 输入，不改变 plan snapshot v2 或 apply 语义。proposal 绑定同一 delegation/user/workspace，10 分钟到期、每 delegation 最多 10 个 pending，确认短语只保存 hash。apply 在 `BEGIN IMMEDIATE` 内重新检查开关、scope、实时角色、所有权、可见性、配额、source key 和目标指纹；成功一次后为 `proposal_consumed`，过期为 `proposal_expired`，目标变化为 `proposal_stale`，确认不匹配为 `confirmation_mismatch`，任一失败不得部分写入或消费 proposal。删除必须显式 `source_disposition=keep|disable_private`；后者只限调用者拥有的 private source。
7. `diagnose_source(subscription_id)` 与 `diagnose_job(job_id)` 只读取当前用户范围内脱敏、持久化的 Health/Schedule/Job 证据，返回固定 `target/status/cause/evidence/suggested_actions/related_job_id` shape。cause 分类仅为 `auth_missing`、`rate_limited`、`network_timeout`、`upstream_rejected`、`invalid_source_config`、`source_disabled`、`subscription_disabled`、`schedule_blocked`、`worker_unavailable`、`no_items`、`unknown`；无充分证据必须返回 `unknown`，诊断不修复、重试或取消任务。
7A. `query_operation_logs` 只读取系统管理的 schema-v1 operation JSONL。`scope=self` 按时间倒序返回当前 delegation workspace 内、actor 或 subject 为当前用户的白名单事件；`scope=workspace` 仅在上述显式诊断授权、实时角色和查询过滤全部通过后，返回同 workspace 的白名单故障事件，并为本次工作区查询写入安全 MCP 审计。结果精确包含 `scope`、`availability=available|empty|unavailable`、`window`、`events`、`returned` 与 `truncated`；事件可含时间、event/request/Job/source/subscription ID、stage、稳定 error fingerprint、服务、级别、类别、动作、结果、错误码、耗时、变更字段名和计数，不得含 workspace/user、文件名、路径、原始 message、stack、文章 ID/正文、URL、config/payload、环境变量名或凭据。损坏/未完成行安全跳过，目录不可安全读取时稳定返回 `unavailable`；self scope 的跨用户对象 ID 过滤返回空结果，不形成存在性侧信道。
8. 稳定 MCP 错误包括 `unauthorized`、`forbidden`、`not_found`、`invalid_request`、`remote_mcp_disabled`、`subscription_writes_disabled`、`write_scope_required`、`diagnostics_scope_required`、`diagnostics_filter_required`、`proposal_limit`、`proposal_expired`、`proposal_consumed`、`proposal_stale`、`confirmation_mismatch`、`source_requires_web_setup`、`source_discovery_unavailable`、`source_resolution_limit`、`source_resolution_expired`、`invalid_source_resolution`、`rate_limited` 和含 request ID 的 `internal_error`。`prepare_create_subscription` 的 source union 缺少或误用 discriminator 时，`invalid_request` 可附加不含输入值的固定正确 envelope 提示。应用内按 delegation 限制 60 次/分钟、burst 10；请求 body 上限 256 KiB。固定 MCP 审计与结构化 operation event 只记 delegation 关联、工具名、proposal ID（如有）、结果、安全错误码、耗时和 request ID，不记令牌、参数、确认短语、正文、文章 ID、source config 或错误 message；MCP 查询返回时再移除 delegation 与用户/工作区关联。普通工具调用不写 `usage_events`，只允许每 15 分钟最多一次的 `last_used_at` 写入。

## 5C. Browser OpenClaw Gateway 合同

1. `HORIZON_OPENCLAW_CHAT_ENABLED=false` 默认关闭站内对话；`HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789` 只作为 GET delegation 响应中的公共默认值。开启后浏览器直接连接用户的 OpenClaw Gateway WebSocket v4，Inteliscope API 不接收、保存或代理 Gateway token、device token、对话、模型请求或费用。
2. 未加密 `ws://` 只允许 `127.0.0.1` 或 `localhost`；其他主机必须 `wss://`。Gateway URL 禁止 username/password、query 和 fragment。完整 dashboard 地址只允许在浏览器内解析 fragment token，规范化后的 WebSocket URL不得保留 token。
3. 初始 Gateway token 仅位于对话框内存，连接成功立即清空。浏览器使用不可导出的 Ed25519 私钥和 OpenClaw v3 device signature 配对；IndexedDB 只保存按 `Inteliscope user + normalized Gateway URL` 隔离的 CryptoKey、exact `operator.read + operator.write` device token 与 session key。有效握手返回的 exact device credential 必须先于 `sessions.create` 持久化，session key 只在创建成功后追加；返回 admin、pairing、approvals、缺少预期 scope 或其他额外权限时必须拒绝持久化。
4. 每个标签页最多一个 Gateway WebSocket。连接创建专属 `Inteliscope · <site> · <random suffix>` session，标签不包含 Inteliscope user ID，发生 label conflict 时用新后缀重试一次，并通过按用户/Gateway 隔离保存的 session key 恢复原会话。调用 `tools.effective` 单独判断 MCP/Skill 可用性，并支持 `chat.history`、流式 `chat` event、`chat.abort`、断线重连和新 session。`models.list(view=configured)` 的裸 ID 必须先规范化为 `provider/model`，模型分叉创建后必须由 `sessions.describe` 验证再切换；可选推理档位只取该模型目录条目或精确当前会话的 `sessions.describe.thinkingLevels`，不得用 `agents.list` 的 Agent 级档位补造未知模型能力。上下文用量只可通过已知当前 session key 精确筛选 `sessions.list` 并订阅 `sessions.changed`；不得按 label 发现、推断或收养其他 session，且 `totalTokensFresh=false`、非正数或缺失容量不得在浏览器估算。`chat.send` 必须使用唯一 idempotency key 和 `deliver:false`；消息最多显示 100 条、总文本 100,000 字符。
5. Browser Agent 上下文最多包含八条有序安全记录。Feed 记录只含 `articleId/title/sourceName?/publishedAt?/sourceUrl?`；运行记录可在浏览器中附带可读标题、来源与状态，但内部 `job_id`、UI 派生的 detail/error 文本不得成为可见历史。可选 `sourceUrl` 只允许无凭据的 HTTP(S)，写入草稿、浏览器 transcript 或 Gateway handoff 前必须移除 fragment、跟踪参数和敏感 query 值并限制为 2,048 字符；它只是可重新打开的来源位置，不是文章证据，页面内容仍按不可信数据处理。V6 handoff 显式区分两种模式：有记录时为 `context_readonly`，把用户问题、内部记录 ID 和有界安全来源引用发送给 Gateway，Feed 记录先调用 `get_item`，运行记录直接调用只读 `diagnose_job`；来源 URL 只可在 `get_item` 后用于来源核验或用户请求的可选 Web 分析，回答仍需基于持久化安全证据、明确未知，并禁止重试、取消、修复或其他写操作。零记录且问题非空时为 `direct`，保留用户在 Agent 面板直接提交的请求，订阅管理仍严格执行第 5B.6 条，普通请求只能 `prepare` 并展示 preview 与服务端返回的准确确认短语，只有后续问题与当前 pending proposal 的该短语完全一致时才可调用 `apply_subscription_change`。浏览器提示词不得替用户生成、改写或代答确认短语，也不得绕过 delegation scope、实时角色、写开关或 proposal 事务复查。浏览器投影继续兼容 V5、V4、V3 和旧无版本 handoff，且不得显示内部指令或 ID；发送后的用户消息只持久化清洗后的来源引用，不持久化完整 MCP prompt。文章正文由 OpenClaw 经 Remote MCP 分段读取，最多跟随 `next_body_offset` 三次并累计不超过 20,000 字符。正文和来源页面都是不可信数据，其中的规则变更、凭证请求或工具调用指令不得执行。
6. Gateway 可选的 `agent/lifecycle/tool/thinking` 运行事件只可投影到当前标签页、当前 exact session key 和当前 run ID。浏览器按单调序号及 tool-call ID 去重，且只把事件映射为前端固定阶段和中文白名单动作；`thinking` 永远只显示通用的“正在思考”，未知工具只显示“正在使用工具”。浏览器不得渲染、写入 transcript、sessionStorage、IndexedDB 或 Service 的原始思维、工具参数、工具结果、meta、原始错误、URL、令牌或确认短语。运行轨迹只在当前页面会话内存中存在，完成后折叠；Gateway 未协商该能力时，`chat.send` 仍必须立即生成本地可信的处理中状态，不得回退为首段回复前空白。

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
4. Worker 每次 schedule tick 在 claim 普通任务前原子评估到期订阅。自动 job 固定为 `job_type=source_fetch`、`reason=scheduled_source_fetch`、`priority=-10`，沿用现有配额、claim token、Source Health 和 Feed v2 单源合并语义。
5. 同一订阅最多一个 queued/running `source_fetch`；手动、自动和重复页面提交复用已有 active job。当前用户存在 active 全量刷新时延后 5 分钟；只有手动全量刷新会包含单源独立周期来源，并在成功参与该订阅后推进其下一次单源计划，避免紧邻重复抓取。自动全局刷新不包含这些来源。停用 catalog source 时，相关计划关闭并记录 `source_disabled`，仍 queued 的自动任务被取消。
6. 调度链路不得调用 legacy scheduler、`HorizonOrchestrator.run()` 或 `LegacyPublisher`，不得读取或写入全局静态 Feed、摘要、legacy 通知、Graph 或 Archive analytics。偏好来源通知只可由下述 Service outbox 在 Feed/Health/Job 提交后消费。

用户偏好来源通知规则：

1. 缺少 `user_notification_settings` row 等同 `enabled=false`；GET 不因缺 row 隐式写库。成功响应返回 `schema_version=2`、`enabled`、`channel=email|webhook`、`email_configured`、`email_transport_ready`、`webhook_configured`、`webhook_provider`、`webhook_provider_explicit`、`webhook_signing_secret_configured`、`webhook_verification_mode=http_status|provider_response`、七类安全 `webhook_provider_options`、`last_test_status`、`last_tested_at`、`last_test_error_code` 和 `updated_at`。`last_test_status` 可为 `sent|failed|unknown|null`；不得返回邮箱明文、Webhook URL、签名 Secret、生成的环境变量名、SMTP 凭据或上游响应。
2. PATCH 接受 `enabled`、`channel`、显式 `webhook_provider`、write-only `email_address`、write-only `webhook_url` 和 write-only `webhook_signing_secret`；至少提供一个字段。邮箱与 Webhook 可以分别预配置，但任一时刻只有 `channel` 指定的单一渠道生效；开启时该渠道必须已有目的地，否则返回 `notification_destination_required`。显式 Provider 只允许 `generic_event|generic_text|feishu_lark_v2|wecom|dingtalk|slack|discord`，`legacy_auto` 不能由请求直接选择。兼容 v14 前客户端时，省略 Provider 的 URL-only PATCH（包括尚无 setting row 的首次 PATCH）可以创建或保留内部 `legacy_auto`；新 UI 不得依赖该例外，修改兼容配置时必须显式选择 Provider 并重输匹配 URL。切换显式 Provider 必须在同次请求重输匹配 URL；只有飞书/Lark V2 与钉钉可保存可选签名，通用事件/通用文本均为 URL-only，不接受 Bearer Token 或自定义 header。当目标渠道为 email 时还必须满足当前工作区 `email_transport_ready=true`，否则返回 `notification_channel_unavailable`；已经开启的 email opt-in 在 transport 暂停后仍保留，但暂停期间不产生 outbox，也不补发。partial PATCH 必须在同一 `BEGIN IMMEDIATE` 内重读实时用户并按 omission 合并，管理员刚完成的停用或降权不得被旧请求覆盖。Provider、URL 或签名变化即使设置关闭也推进不可回退 generation，并清除旧测试状态；从关闭变为开启时还记录新的用户级 `enabled_at`，停用期间发布的内容不得补发。管理员停用用户时必须在同一事务关闭其通知设置并清除该水位；重新启用账户不得恢复通知开关。
3. Webhook URL 与可选签名 Secret 只可在请求内短暂出现，随后原子写入 `SecretStore` 中不同的用户专属环境变量；Service DB 只保存 Provider、环境变量名和当前值的内部 SHA-256 一致性摘要，config JSON、outbox、API、DOM、Job、日志和错误 envelope 均不得保存或回显真实值。配置状态、staging 和发送都必须同时验证用户专属变量绑定与摘要匹配；SecretStore/SQLite 更新中断时补偿回滚或 fail closed，显式清空还必须删除确定性变量下没有 DB 引用的 orphan 值。投递时重新执行 Provider 对应的精确 HTTPS URL 校验；固定到公网地址后使用 bounded DNS、单地址单次 POST、5 秒 transport timeout 与 6 秒总 deadline，禁用环境代理并拒绝重定向。G1/G2 响应正文始终丢弃且仅以 HTTP 2xx 验收；P1-P5 只接受 identity 响应，最多读取 4096 bytes 用于业务 ACK 校验。任何响应正文都不得持久化、写日志或进入错误/API。
4. `user_subscriptions.notify_on_new_items` 默认 false。PATCH 从 false 切为 true 时记录 `notification_enabled_at=now` 并把内部 `notification_generation` 原子加一；已是 true 的幂等保存不得重置水位或代数。旧客户端或重复 create 请求省略该 additive 字段时，已有订阅必须保留原开关、水位与代数，新订阅仍默认关闭。订阅或 catalog source 停用、订阅切到 `analysis_mode=personal_only` 时原子清除通知开关和时间；重新启用不得自动恢复 opt-in。在同一请求中显式提交 `personal_only + notify_on_new_items=true` 或给已停用订阅开启时返回 `invalid_subscription_notification`。
5. 内容投递只比较本次成功/partial Feed snapshot 与其紧邻上一份 snapshot 的稳定 `article_id` 差集。用户首份 snapshot 仅建立基线；标题变化、删除、排序、no-op、共享内容复用、生命周期 reconcile、`source_test`、`content_repair` 和无 snapshot 的失败均不得生成内容通知。
6. 差集 item 还必须包含已开启订阅的 provenance，且其规范 `published_at` 必须严格晚于用户通知 `enabled_at` 与该订阅 `notification_enabled_at` 两者；缺失、无时区或不可解析时间一律 fail closed 跳过。`personal_only` item 永远不进入 outbox。
7. `preferred_source_notification_deliveries` 以订阅和稳定文章 ID 唯一去重，并在 stage 时固化账户与订阅两层 generation。候选 outbox 必须与 snapshot、Source Health 和 claim-guarded Job 终态处于同一事务；claim 失效时整体回滚且不得外呼。Worker 只在 `complete_job` 成功提交后发送，并在外呼前复查用户、来源、订阅、通知开关和渠道仍然有效，还必须同时要求 delivery 双 generation 与当前值完全相等、可信的 delivery `created_at` 与来源 `published_at` 严格晚于“当前”账户和订阅双水位；关闭后重新开启的旧 epoch pending 即使墙钟回拨或伪造未来发布时间也要安全终结且不外呼。通知发送或 staging 的局部失败只更新/跳过通知状态，绝不把已成功的抓取 Job 或 snapshot 改成失败或触发重新抓取。
8. 外部通知不假设幂等。未开始的 `pending` delivery 可由后续 Worker tick 领取；领取后先写 `sending`，再外呼。DNS、Connect 或 Pool 在请求尚未开始前失败可安全标记为可重试 unavailable；HTTP 429 为明确限流。Write/Read/其他 TransportError、HTTP 408/425/5xx、平台 ACK 超限/畸形/非 identity 或其他已开始发送但无法验证的结果必须保持 `sending`/`unknown` 且永不自动重放；发送前 URL/公网校验失败、非成功 4xx 或平台明确非零业务码可进入 `failed` 并记录有界安全 code。任何状态都不保存上游正文或目的地。
9. Service 邮箱投递只读取 schema v10 工作区 transport 与其 SecretStore 凭据，绝不回退到 `data/config.json.email`；收件地址仍仅属于当前用户。Webhook 必须共用 `notification_webhook_transport` 的七类 Registry：G1 `generic_event` 发送 `{"event","data"}` 并仅要求 HTTP 2xx；G2 `generic_text` 发送 `{"text":"..."}`、URL-only 并仅要求 HTTP 2xx；P1 `feishu_lark_v2` 发送原生 text、允许可选签名并要求 JSON `code==0` 或 legacy `StatusCode==0`；P2 `wecom` 发送原生 text 并要求 `errcode==0`；P3 `dingtalk` 发送原生 text、允许可选签名并要求 `errcode==0`；P4 `slack` 发送 text 并要求 HTTP 200 且正文精确等于 `ok`；P5 `discord` 发送禁用 mentions 的 `content`、强制 `wait=true` 并要求 HTTP 200 JSON 中 `id` 为纯数字字符串。每个 P1-P5 URL 必须精确匹配官方 host/path/query，显式 G1/G2 拒绝已知官方 Provider host，防止误配绕过 ACK；只有迁移或旧 URL-only 客户端创建/保留的 `legacy_auto` setting 允许精确飞书/Lark V2 自动映射到 P1，其余 legacy setting 映射 G1。文本只由既有有界安全字段构造，不发送 cards 或 mentions；密集批次可压缩次要字段，但最多 20 个 article 的每个编号标题都必须保留。Worker 对同一用户、渠道和 Job 原子领取最多 20 个 distinct article ID 及这些文章的全部 eligible provenance ledger，按 article ID 去重后合并为一次外呼；Email 展开条目列表，而 outbox 仍对批内每个 `(subscription_id, article_id)` 保留唯一记录与一致终态。
10. POST test 使用模拟标题和正文，只验证已保存的当前渠道。Webhook 成功返回安全的 `sent/channel/provider/verification`，其中 `verification=provider_accepted` 表示 P1-P5 平台业务 ACK 已验证，`verification=http_accepted` 表示 G1/G2 仅返回 HTTP 2xx；保存成功不等于测试成功，两类结果都不承诺终端实际展示。结果无法验证时必须持久化并投影为 `unknown`，不能伪装为 sent；个人通知返回不可重试的 `notification_test_outcome_unknown`，Apify 运行告警返回不可重试的 `apify_actor_alert_test_outcome_unknown`，action 必须要求先刷新状态、核对接收端并禁止盲目重复发送。失败使用稳定安全错误，不回显目的地或上游正文。外呼前必须在 SQLite 写事务中原子领取当前用户 60 秒测试冷却，并发或冷却内重复请求返回 429 `notification_test_rate_limited`。测试结果按发起时 generation 条件写回，配置并发变化后旧结果不得覆盖当前状态；测试不写内容 outbox、不读写 Feed 基线、不创建 Job，也不触发来源、AI、scheduler 或付费调用。
11. Webhook providers v14 为显式 additive 迁移：为 `user_notification_settings` 与 `apify_actor_alert_settings` 增加 Provider/签名元数据和写入约束，清除旧 Webhook test 状态，并把旧 row 及兼容旧客户端省略 Provider 的 URL-only PATCH 保持为 `legacy_auto`。已有数据库必须先完成 v13，停止 API/Worker并跨过 heartbeat 安全窗，使用 `scripts/migrate_webhook_providers_v14.py --dry-run|--apply` 生成 UTC `0600` backup；只有 row/trigger、`integrity_check` 与 `foreign_key_check` 全部通过才记录 marker。缺 marker、列、约束或存在非法组合时 readiness、通知/告警设置与测试路由、Worker 全部 fail closed；迁移不发送 Webhook、不读取真实 Secret，也不重放旧 delivery。

工作区邮件发送服务规则：

1. 缺少 `workspace_email_transports` row 等同未配置且关闭；schema v10 只保存 `provider/sender_email/sender_name/region/smtp_username/enabled/generation/test metadata`、确定性 SecretStore 环境变量名与当前凭据 SHA-256 一致性摘要。授权码、App Password、API Key、SES SMTP Password 和测试收件人不得进入 SQLite、config JSON、Job、Feed、outbox、日志或 API 响应。
2. Provider Registry 只支持固定的 SSL/465 连接：QQ=`smtp.qq.com` 且登录名为完整 QQ/Foxmail 地址；网易=`smtp.163.com` 且接受 163/126/yeah.net 完整地址；Gmail=`smtp.gmail.com` 且登录名为完整地址；Resend=`smtp.resend.com` 且登录名固定 `resend`；Amazon SES=`email-smtp.<validated-region>.amazonaws.com` 且使用显式 SES SMTP username。API 不接受 host、port、TLS 模式或自定义 SMTP，浏览器不得覆盖派生结果。
3. PATCH 至少包含 `provider`、`sender_email`、`sender_name`、write-only `credential`、`enabled`、SES-only `region/smtp_username` 中一个。首次创建必须得到可解析 Provider 配置；Provider、发件身份、Region、SES 用户名或凭据变化会推进不可回退 `generation`、自动关闭、清除旧测试状态并要求当前 generation 重新测试。账号相关字段变化且未同时提交新凭据时清除旧凭据绑定；凭据提交后 API 永不回显。
4. `enabled=true` 只在 SecretStore 当前值与确定性变量/摘要匹配、Provider 配置有效、且 `last_test_status=sent` 与 `last_test_generation=generation` 时允许。每次 API 测试和 Worker 发送都重新读取 SecretStore 并比较摘要，无需重启容器；文件/SQLite 部分失败必须补偿或 fail closed。
5. 管理员 test 只接受一次性 `recipient_email`，按 workspace 在 SQLite 写锁内原子领取 60 秒冷却；成功只返回 `sent=true/generation`。测试通过与启用是两个独立动作，测试不创建 Feed/Job/outbox、不移动用户或订阅水位，也不把测试收件人写入任何持久状态。
6. 统一 `EmailTransport` 使用系统 CA 校验的 TLS、20 秒 timeout 和同一 MIME/HTML 转义实现；API 测试与 Worker 正式投递不得复制 Provider 发送逻辑。正式发送在 SMTP 连接中断或其他结果未知后保持 delivery=`sending` 且不自动重放；认证、发件人、收件人或 DATA 的明确拒绝可安全终结为 `failed`。
7. transport 轮换、停用或删除时，尚未开始的 workspace email `pending` delivery 原子终结为 `failed/notification_transport_changed`；已经 `sending` 的记录保持未知结果。transport 未 ready 时不创建新的 email outbox；已有用户 email opt-in 和逐来源水位均保留，因此恢复后只比较暂停期间保存的最新相邻 Feed 基线并发送之后严格新增的内容。Webhook staging 与发送不受邮件 transport 状态影响。
8. `data/config.json.email` 与 legacy `EmailManager` 只服务显式 CLI/日报兼容路径，Service API、Worker、设置页与偏好来源通知不得读取它们作为配置或降级兜底。

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

密钥规则：

1. `secret_env` 必须是环境变量名，不得是疑似真实密钥；`secret_refs` 只保存 `name/kind/provider/env_name/version` 等元数据，`kind` 仅为 `ai|apify`。每次原地轮换必须令 `version` 原子加一。
2. 真实值只保存在 Git/Docker 忽略的 `data/secrets.env`，由 `SecretStore` 以临时文件、`fsync`、原子替换和固定 `0600` 权限维护；Service DB、API、日志、job、Feed 和 DOM 均不得包含真实值。
3. API 和 Worker 在需要配置或执行任务时重新加载密钥文件；新增/轮换无需重启。密钥列表及 create/rotate 响应只返回 `id/name/kind/provider/env_name/is_set/used_by` 和时间元数据，不返回 `value`。
4. 同 workspace 的 `env_name` 唯一，重复创建返回 `409 secret_env_conflict`。被 AI 配置或 legacy catalog source 引用时删除返回 `409 secret_in_use`。池模式下 active、draining 或仍有非终态 Actor Run 的 Apify Key 轮换/删除返回 `409 apify_key_busy`，必须先安全排空；新建 Apify secret 在 secret ref 与真实值均成功后自动追加为备用，追加失败必须回滚两者。空闲 Key 成功轮换后必须清除旧额度/周期/错误状态并令 generation 加一；已有 active 时把该 Key 放到备用队尾，只有池原本无 active 时才把它激活。
5. Apify 额度接口从 `SecretStore` 读取目标 Token，以 Authorization header 分别调用官方 `/v2/users/me` 和 `/v2/users/me/limits`，不把 Token 放入 URL。成功响应的 `data` 精确包含 `secret_id/provider/currency/cycle_start_at/cycle_end_at/checked_at/monthly_included_credits_usd/monthly_usage_usd/remaining_included_credits_usd/max_monthly_usage_usd/remaining_hard_limit_usd`；`provider=apify`、`currency=USD`，金额为非负有限数字，两个 remaining 字段最低为 `0`。Token、账户 ID、用户名、邮箱、profile、proxy、原始响应和其他套餐字段不得进入浏览器、数据库、日志或错误 envelope。
6. 单个额度上游请求失败不得影响密钥列表。跨 workspace secret 与不存在 secret 统一 `not_found`；非 Apify 返回 `quota_not_supported`；SecretStore 中无值返回 `secret_not_configured`。保存或轮换 Key 只验证本地元数据和值格式，不得以额度上游可用性作为成功前提。
7. additive schema v8 包含 `apify_key_pool_state`、`apify_key_pool_members` 和 `apify_actor_runs`。数据库只保存 workspace、`secret_id/version`、有序位置、安全状态/额度周期与数值、generation、内部远端 run/dataset 标识和终止状态；真实 Token 仍只来自 `SecretStore`。初始化幂等地把现有 Apify refs 加入池：被 enabled Apify source 引用次数最多者为初始 active，其余按创建时间进入 standby；同次 initialize 不改变已存在顺序或 generation。
8. `HORIZON_APIFY_KEY_POOL_ENABLED=false` 为默认。开启后 Service Apify 来源统一使用工作区池，`source_catalog.secret_env` 仅保留回滚兼容且不再读取、展示或新增；registry 返回 `credential_mode=workspace_apify_pool`、`supports_secret_env=false`，创建或 PATCH 中只要提交 Apify `secret_env`（包括 `null`）就返回 `409 apify_key_pool_managed`。
9. 每次 Actor Run 启动前必须在 SQLite 写事务内预留固定的 `secret_id + secret_version + pool_generation`；同一 Run 的 POST、轮询、中止和 dataset 读取始终使用该 lease 的同一 Token。新 Run 只接受最近不超过 60 秒且 `remaining_included_credits_usd > 0` 的额度快照；单次逻辑抓取对每个可用 Key 最多尝试一次，Actor route 还必须在每次新 POST 前持有独立费用预留。
10. 只有 HTTP 402、明确 Apify 额度错误或额度快照 `remaining_included_credits_usd <= 0` 标记 `depleted`；HTTP 401 或明确无效 Token 标记 `invalid`。只有启动 POST 明确返回 401/402 且没有 remote run 标识、可以证明未开始计费时，才允许换 Key 创建新 POST。已取得 remote run 后的 poll/dataset 401/402 必须停止自动重放并进入可恢复或 blocked 状态；普通 403 只失败当前请求，429、幂等 GET 的 5xx/连接失败只在原 Key 有界重试，均不得污染整个 Key。
11. Key 失效时池先进入 `draining`，禁止任何 Worker 预留新 Run；旧 generation 下所有已登记非终态 Run 必须经 `POST /actor-runs/{runId}/abort` 并轮询确认 `SUCCEEDED/FAILED/ABORTED/TIMED-OUT`。30 秒仍未全部确认则保持 fail closed 并返回 `apify_key_drain_pending`；只有排空完成才把 generation 加一、启用下一 standby，并让原逻辑抓取创建全新 Run，禁止复用旧 runId 或 dataset。
12. Actor POST 的结果未知、remote run 已存在但当前无法安全恢复 dataset，或进程重启后发现无法证明是否已创建远端 Run 的 reservation，必须把池与对应 Actor route 都置为 `blocked` 并返回安全的 `apify_start_outcome_unknown`/`apify_key_pool_blocked`，由人工核对 Apify 控制台；不得猜测远端标识、把已收费 Run 标成未启动或盲目切换。Worker 启动时必须先 reconcile 已登记 Run 与 Actor attempt，再领取新 Job。
13. 全部 Key 耗尽时返回 `apify_key_pool_exhausted`，Apify 单源任务失败，完整 Feed 可为 partial 且其他免费来源继续运行；来源 schedule 延后到已知最早 `blocked_until/cycle_end_at`。周期到期后重新查询额度，恢复的旧 Key只追加到备用队尾，不抢占 active，也不恢复历史 Run。
14. Catalog RSS URL 禁止 `${ENV_VAR}` 占位和 URL userinfo，避免把环境值或凭据写入 catalog/API；member 拥有的 RSS 在抓取前及每次 redirect 都必须只解析到公网地址，并只连接该次已验证的字面 IP，同时保留原 Host 与 HTTPS SNI。安全请求不得使用环境代理或跨 hostname 复用连接，响应拒绝压缩且流式硬限制为 2,000,000 bytes。只有 `owner/admin` 拥有的 source 可默认访问本地/私网 RSS；确定性的本地测试例外必须由管理员通过 `HORIZON_MEMBER_RSS_HOST_ALLOWLIST` 精确列出 host，默认空。
15. `member` 创建的 source job 必须引用可见 `source_id`；Worker 以 catalog config 为权威并忽略 job payload 对 URL/source 字段的覆盖。
16. additive schema v13 包含 `apify_actor_routes`、`apify_actor_candidates`、`apify_actor_attempts`、`apify_actor_target_health`、`apify_actor_alert_settings`、`apify_actor_alert_incidents`、`apify_actor_alert_deliveries`，并为 `apify_actor_runs` 增加预留/实际/终态费用列。数据库可保存内部 source/job/run/dataset 关联用于恢复和核账，但所有公共 API、Job 诊断、Feed 与日志必须移除这些关联和原始错误。
16A. additive schema v14 为 `user_notification_settings` 与 `apify_actor_alert_settings` 增加 `webhook_provider`、签名 SecretStore 变量名与摘要，并安装两表 INSERT/UPDATE 约束 trigger；只允许七类显式 Provider 和内部 `legacy_auto`，签名字段必须成对出现且只可绑定飞书/Lark V2 或钉钉。v14 不修改既有 outbox/incident/delivery payload，不读取或复制真实 URL/Secret。
17. X/profile 候选初始顺序固定为 ScrapeBadger、Dami、Xquik。ScrapeBadger 初始 closed；Dami 在成功 Canary 前不得承接自然流量，成功后从该时刻进入 48 小时 probationary，真实帖子成功率达到 95% 才转 closed，否则 disabled；Xquik 初始 open。half-open 的 `valid_empty` 不算恢复，只有连续两次 `valid_nonempty` 才恢复 closed。

AI 概括规则：

1. Service 单篇分析使用 `summary_max_chars`（100..500，默认 200）、`analysis_max_output_tokens`（256..2048，默认 800）、`analysis_content_chars`（默认 1000）和 `analysis_comments_chars`（默认 1500）。
2. Gemini 默认使用当前稳定的 `gemini-3.5-flash`；Flash 分析请求关闭额外 thinking budget，使受控输出预算用于完整 JSON。解析失败的结果不得写入 analysis cache，prompt/cache schema 变化必须 bump version。
3. 最终 snapshot 前每篇文章都执行统一概括规范化：优先 AI 中文概括，其次来源摘要、清洗正文、标题；压缩空白并在句界或省略号处硬截断，最终长度包含省略号且绝不超过 `summary_max_chars`。AI 失败、空响应或 `personal_only` 均不得产生空概括。
4. 新版分析提示词和 Presentation v1 不生成“为什么值得关注”/`reason` 或 `action_suggestion`；AI 只补充中文概括、评分、taxonomy 和 signal。legacy flat `reason/action_suggestion` 只为静态与历史反序列化兼容保留，不得成为 React 展示或搜索输入。
5. Service Worker 的成功分析缓存必须按 `workspace_id + user_id + article_id + input_hash + model + prompt_version` 隔离，默认保留 30 天。`input_hash` 覆盖影响推理的标题、受控正文、作者、发布时间和来源身份；`prompt_version` 必须覆盖实际发送的完整 system prompt、经过运行上限裁剪后的完整 user prompt、model、analysis mode、运行限制和 cache version。只持久化 hash 与安全推理字段，绝不保存 prompt、原始正文、密钥、`reason` 或 `action_suggestion`，不得跨用户复用。
6. `analysis_usage` 在既有字段之外增加非负整数 `provider_attempts`。`item_count` 是逻辑 cache-miss item 数，`provider_attempts` 是实际网络调用数；429/5xx/连接或超时重试逐次计量，命中缓存不计调用。

Source catalog 规则：

1. `src/services/source_type_registry.py` 是 catalog source type、config 校验、`source_key` 和 Worker payload 的统一合同入口。
2. 当前 registry 支持 `rss`、`github_release`、`github_user`、`reddit_subreddit`、`reddit_user`、`telegram_channel`、`apify_social`、`hackernews`。
2A. RSSHub 是 workspace runtime service，不是第九种 catalog type。受控 Bilibili row 继续保存为 `type=rss`，config 只允许 `provider=rsshub/site=bilibili/route_key=user_video/params.uid` 加既有安全 RSS 展示/保留字段；catalog URL 固定投影为公开 Bilibili profile，Worker 才用当前 `rsshub.base_url` 解析 `/bilibili/user/video/<uid>/1`。Base URL 可含管理员控制的反向代理 path prefix；若 SecretStore 存在 `RSSHUB_ACCESS_KEY`，请求只附加对应 route-scoped access code。受控请求禁用 redirect，且不经过 member 任意 URL 的公网 egress 路径。
3. `source_key` 在同一 workspace 内唯一；导入旧配置和重复写入必须按 `source_key` 更新兼容的已有 source，而不是重复创建。旧配置导入碰到另一用户 private source 必须跳过并记录 `source_key_conflict`，不得覆盖其 metadata/config/secret_env。
4. Telegram 源身份字段使用 config 内的 `channel`；Hub 分类频道使用 `hub_channel` 或兼容 `category`，不得混淆。
5. 无效 source config 返回 `invalid_source_config`；疑似真实密钥返回 `invalid_secret_env`。
6. `PATCH /api/catalog/sources/{id}` 中未出现的字段必须保持原值。显式 `default_channel: null`、`secret_env: null` 分别清空可空标量，`default_topics: []` 清空列表；`config` 仍按 source 的既有 type 通过 registry 校验，source type 不可通过 PATCH 改变，key 冲突保持 `409 source_key_conflict`。
7. `PATCH /api/me/subscriptions/{id}` 同样区分 omission 与显式清空：`override_channel: null` 清空 override，`override_topics: []`、`personal_tags: []` 清空列表。subscription `priority` 默认 `0`，创建和更新只接受严格整数 `0..100`；显式 `null`、boolean、浮点数、字符串或越界值均为 `400 invalid_request`。additive `notify_on_new_items` 为严格 boolean，时间水位与内部 generation 只由服务端维护并按上文规则清除或推进；create 对已有订阅省略此字段也必须保持原值。
8. API 使用 Pydantic field-set 信息，storage 使用私有 sentinel，确保 omission/null/空列表语义不会在入口到 SQLite 的传递中丢失；读取既有 subscription 时继续返回整数 priority。
9. `GET /api/catalog/sources?include_disabled=true` 只允许 `owner/admin`；`member/viewer` 返回 `403 forbidden`。管理权限检查不得依赖来源是否 enabled，普通成员取消订阅必须使用自己的 subscription id，即使 catalog source 已停用也可完成。
10. 启用订阅时，100 条默认上限的检查与 subscription upsert 必须处于同一个 `BEGIN IMMEDIATE`；并发请求最多一个越过最后名额。任务 retry 的重新排队、配额检查和 usage 写入也必须同事务提交或回滚。
11. private source 提升为 workspace/public 时只改变 catalog 管理边界并把该来源的共享媒体投影为 workspace/public；不重新抓取、不批量重写历史 snapshot。新订阅者从 `user_content_items` 复用最多 200 条去重稳定内容，重写为自己的 subscription provenance 并创建自己的 Feed snapshot。
12. 来源引用人数不得成为 catalog 列表的常驻聚合查询；客户端只在用户展开引用信息时调用 usage 接口。shared source 的最后一个普通订阅者取消订阅不软停用 catalog，只有最后一个 private owner 取消订阅时防御性软停用僵尸来源。
13. 池模式下 Apify source 的公开 `secret_configured` 只表示当前 active 池成员在 `SecretStore` 中有值；不得从 legacy `source_catalog.secret_env` 推断。配置兼容 facade、catalog runner、`source_test`、`source_fetch` 与 `user_feed_refresh` 必须使用同一个 workspace pool coordinator。

任务规则：

1. 创建 job 返回 queued 状态，不在 Web 请求内执行长耗时抓取。
2. Worker 使用 `uv run horizon-worker` 执行 runnable queued job，并写入 `succeeded/failed/partial`；claim 必须在 `BEGIN IMMEDIATE` 内原子写入 `worker_id + claim_token + locked_until`，公共 API 永不返回 `claim_token`。
3. `source_test/source_fetch/user_feed_refresh` 计入每日 fetch job 配额。
4. 配置页测试和立即更新按钮必须显示 queued job id，而不是同步抓取结果。
5. 订阅控制台的“刷新我的信息流”“测试”“抓取”按钮只创建 queued job，并在 UI 中显示 job id。
6. Worker 每次 claim 前恢复 lease 过期的 running job；只有 `failed` 且包含 retryable issue 才在 `max_attempts` 内退避重试，`partial` 是保留可用 snapshot 的终态且不自动重试。
7. `POST /api/jobs/{id}/cancel` 只取消 queued job；SQLite MVP 不强杀 running job，running cancel 返回 `job_not_cancelable`。
8. `POST /api/jobs/{id}/retry` 只把 failed、partial 或 cancelled job 重新排队，并重置 attempts；同一 job 的新 run 必须在最终 claim 事务内原子替换已有 snapshot payload/items，不得复用旧 partial 内容或创建第二个 snapshot。
9. terminal job 可按 `expires_at` 清理；默认保留天数由 `HORIZON_JOB_RETENTION_DAYS` 控制。
10. `user_feed_refresh` 成功后必须保存 `user_feed_snapshots/user_feed_items`，job result 至少包含 `snapshot_id`、`item_count` 和 `new_item_count`。
11. `source_fetch` 带 `source_id` 时，Worker 必须从 `source_catalog + 当前用户 subscription override` 合成单源 `Config`，跳过 legacy notifications、summaries、enrichment、full-text 和 scheduler 副作用；成功后保存当前用户 feed snapshot，job result 至少包含 `snapshot_id`、`item_count`、`new_item_count`、`source_id`、`source_type` 和 `source_key`。只有 snapshot/health/job 同事务内的偏好来源 outbox 与提交后发送属于允许的 additive Service 副作用。
12. 真实源 smoke gate 使用 `scripts/service_real_source_smoke.py` 创建/更新 catalog sources、订阅当前用户、创建 `source_test/source_fetch` job，并验证 RSS、Hacker News、GitHub Releases、Telegram public channel 的闭环；Reddit/Apify 只能作为 optional degraded 记录。
13. Worker 每 10 秒写 heartbeat 并在任务执行中续租；heartbeat age 达到 35 秒即视为 stale。完成、失败、续租和 snapshot finalize 都必须匹配 `job_id + worker_id + claim_token + running`。
14. schema-v2 snapshot、`user_feed_items` 和 job 终态必须在同一短事务提交；同一非空 `job_id` 最多生成一个 snapshot，同一 snapshot 内 `article_id` 唯一。
15. `POST /api/jobs/user-feed-refresh` 的 data 增加 `deduplicated`。同一用户已有 queued/running 全量刷新时返回原 job 且 `deduplicated=true`；真正新建时为 false。手动、多标签页和自动刷新共同受同一原子去重约束。
16. 手动全量刷新必须在同一个 `BEGIN IMMEDIATE` 事务中完成“查找/创建 active job、配额 admission、usage 记录”；只有真正新建 job 才计一次配额，配额失败同时回滚 job 和 usage。复用已有 active job 不重复计费，也不因当日配额后来耗尽而拒绝读取该 job。
17. Worker 在 claim 普通 job 前按 `HORIZON_SCHEDULE_POLL_SECONDS` 检查到期计划，默认 30 秒。自动任务复用 `user_feed_refresh`，固定 `payload.reason=scheduled_service_refresh`、`priority=-10`，只从 `user_source_schedules.enabled=false` 或缺 row 的有效订阅合成 Config；`enabled=true` 的单源独立周期来源必须排除。自动任务仍使用用户完整 `filtering.time_window_hours`，刷新周期不替代抓取窗口。手动“更新整个信息流”继续合成全部有效订阅。
17A. 没有 `last_success_at` 健康记录的直接 RSS 与受控 RSSHub 订阅，生产 `source_fetch/user_feed_refresh` 按单来源使用 `filtering.rss_initial_fetch_window_hours`（只允许 `168|720`，缺省 `168`）；同一次混合刷新可因此具有不同来源窗口。抓到零条的成功 outcome 同样建立成功边界，之后恢复 `filtering.time_window_hours`；失败及中间重试保持首次窗口。Job payload 或调用方显式传入的 `hours` 始终覆盖首次窗口。单来源窗口只存在于 Worker 合成的内部运行配置，必须从持久化 config 与所有公共序列化中排除；该规则只改变上游采集范围，不改变 Feed 留存，也不需要数据库迁移。
18. 到期检查、active job 去重、usage 记录和 schedule 推进必须处于同一 SQLite 写事务；两个连接竞争同一计划最多创建一个 job。重启或长时间离线只补一个任务并把下一次推进到 `now + interval`，不追赶全部漏跑周期。全部有效来源均启用单源独立周期时，全局计划仍保持设置，但以 `no_global_subscriptions` 推进到下一周期且不创建 job；切换后遗留的 queued 自动全局任务在 claim 时以同一原因安全取消。
19. active `source_fetch` 或 migration 未完成时计划延后 5 分钟，避免 snapshot 竞争或热循环；disabled user、无有效订阅、无跟随全局订阅或配额耗尽时不入队并推进到下一周期。`partial/failed` 不关闭计划，后续仍按已计算的下一周期继续。
20. `user_feed_refresh` 的 `succeeded/partial` job `result_json` 必须包含 `run_id/run_status/item_count/new_item_count/source_outcomes/issues/analysis_usage`，并保留既有 `snapshot_id/snapshot_created`；`source_fetch` 的 `succeeded/partial` 结果同样包含 `new_item_count`。该字段是在 Feed 写事务内，以最终 canonical merge 与稳定 ID 去重后的 snapshot 相对紧邻上一份 snapshot 实际新增的唯一文章 ID 数：首份 snapshot 的全部唯一条目计为新增，重排或 metadata 变化不计新增，删除不抵扣，旧 Job 缺少该 additive 字段继续有效。`analysis_usage` 精确包含非负整数 `item_count/cache_hits/ai_calls/provider_attempts/fallbacks/skipped`，只用于成本与降级诊断，不包含 token 文本或原始内容。每个公开 source outcome 精确包含 `source_id/subscription_id/source_key/analysis_mode/status/fetched_count/issue`；issue 为 `null` 或精确的 `stage/code/message/retryable`，不得包含 source config。
21. 结构化 refresh 最终 `failed` 且不生成 snapshot 时，`result_json` 仍保存同一诊断 shape，`run_status=failed`、`item_count=0`，同时保留 job 的 `failed/error_code/error_message`。可重试的中间 attempt 可以保存本次诊断，但不得提前更新 Source Health；只有 claim-guarded `fail_or_retry_job` 选定最终失败后才能原子提交健康与 job 终态。
22. job result、Service snapshot 和 job error 中的 issue/source key 必须先使用与 Source Health 相同的单行、240 字符上限脱敏器，删除 URL userinfo/query、认证信息、secret、payload/config/stack/traceback；公共结果不得记录 source payload、真实密钥、带认证 URL 或堆栈。`fail_or_retry_job` 的可选结构化 result 不改变既有 worker/claim/lease guard 和退避决策。
23. 停用/删除订阅、停用来源、停用用户或把用户降级为 viewer 时，相关 schedule shutdown、queued job 取消和 Feed reconciliation 必须在同一事务。失效任务终态为 `cancelled/error_code=job_invalidated`，并只附带有界 `invalidation_reason`。
24. Worker 在 claim 后、每次网络调用前和 claim-guarded finalize 前复查统一 eligibility。自动全局任务在 claim 时还必须存在至少一个有效的跟随全局订阅。调用前失效不得访问网络；调用中失效的结果不得更新 Feed 或 Source Health。
24A. 自动全局刷新只用本次实际抓取来源的 outcome 更新 Source Health；Feed finalizer 的 active source 集合仍必须取当前用户全部有效订阅，使局部全局刷新保留单源独立周期来源的既有内容。手动全量继续以全部有效来源更新、合并并推进参与的单源计划。
25. 默认未知异常不可重试。只重试显式 retryable source issue、连接/超时、HTTP 429 与 5xx；每个真实 scraper/provider/AI 网络调用（包括自动重试和人工 retry）均原子计量。
26. `HORIZON_SHARED_ACQUISITION_ENABLED=true` 时，public/workspace source 在同 workspace、相同 acquisition key 与 freshness window 内最多一次上游获取；private source 按 user 隔离。key 覆盖 source/type、规范化网络配置、adapter contract、secret-ref identity/version 和抓取窗口，不包含频道、主题、标签、优先级等用户投影字段。
27. shared acquisition 成功必须缓存零条结果；TTL 取相关启用计划最短周期并默认夹在 5..60 分钟、无计划回退 30 分钟。并发 loser 最多等待 5 秒且不计 attempt；stale lease 可恢复，失败退避最多 5 分钟。`source_test` 绕过成功缓存且不写 content pool，但仍受同源并发和成本 admission 约束。
28. Feed/source job result 增加精确 `acquisition_usage{cache_hits,cache_misses,upstream_attempts,waits}`；只包含非负计数。`/api/ops/runtime.operational_counts` 只聚合这些计数、`invalidated_jobs` 与 `quota_rejects`，不得输出 source/user id、配置、prompt 或 secret。
29. terminal `source_test/source_fetch/user_feed_refresh` 的 `result_json` 可增加 `response_schemas[]`，每项精确包含 `source_id/catalog_type/capture_status/upstream/normalized`，可选 `job_truncated=true`。`capture_status` 只允许 `captured/empty/cached/unavailable`；两层结构只含 `root_type`、`fields[{path,type}]`、`truncated`，type 只允许 `object/array/string/integer/number/boolean/null/mixed`。每层最多深度 6、256 个路径、8 KiB，每个 Job 合计最多 64 KiB。结构摘要不得包含字段值、正文、source config、请求 URL、Actor input、header、token、secret 或密码；旧 Job 缺少该字段继续有效。共享缓存命中必须标记 `cached` 且不得复用旧 Job 的上游结构。
29A. `GET /api/jobs?view=summary` 的每项精确保留 `id/user_id/source_id/subscription_id/job_type/status/error_code/error_message/created_at/started_at/finished_at` 中存在的字段；可选 `result` 只含 `message/snapshot_created/new_item_count/failed_source_count` 中合法的有界值，不返回 payload、完整 result、response schema、worker、lease 或 claim 字段。旧 result 缺少 `failed_source_count` 时可从 `source_outcomes[].status=failed` 计算；列表需要响应结构时必须再读取目标用户可见的 `GET /api/jobs/{id}`。
30. 池模式下 Apify shared acquisition fingerprint 必须包含 reservation 时的 pool generation；缓存 owner 在发布前重新读取 generation，发生变化就放弃旧结果并禁止写入共享缓存。其他 source type 的 fingerprint 与缓存语义不变。
31. Apify source schedule 在池 `draining/blocked/exhausted` 时只延后该来源，分别使用 30 秒 reconcile 窗口、人工解阻或最早额度恢复时间；完整 Feed 的非 Apify 来源照常获取。公开 schedule/job error 只保存有界 `apify_key_*` code 和通用安全 message，不得保存内部 pool row、远端 run/dataset 标识或上游正文。
32. Worker 启动时在 claim 任意业务 Job 前按 workspace reconcile Apify Key ledger 与 Actor attempt。已知远端 Run 必须使用登记的旧 lease 继续 poll，并在 succeeded 时从既有 dataset 执行同一语义校验与 attempt 结算；route attempt 已成功但 Job 尚未完成时，同一 Job 只能 GET 重读该 terminal Dataset，不能新 POST。无法完成该恢复时保持 route/job blocked，绝不能让 stale Job 新 POST。只有完全没有 Key reservation，或明确 `start_rejected/cancelled`、无 remote run 且零费用，才可安全取消 attempt 并重新排队。
33. `x/profile` 默认按管理员候选顺序串行选择健康 Actor；同一逻辑 source 最多依次调用三个不同候选，同一 Worker Job 内多个 X/profile 来源也不得并发 Actor。单 Run `maxTotalChargeUsd=$0.02`，attempt group 累计预留最多 `$0.06`；有 `job_id` 时 group 必须由 `(workspace, route, job, source)` 稳定复用，Worker/Job 重试不得生成新费用组，已有 active attempt 时不得并发第二路。已经远端启动、产生结算费用或因 route generation 冲突而作废的 `cancelled` attempt 仍占用原组预留并计入失败消费；只有可证明未 POST 的取消才可从费用组排除。所有 Key Run 的最终实际费用必须按 logical attempt 聚合，不能只记最后一把 Key。
34. 语义校验必须先拒绝 placeholder/diagnostic/demo/mock/paywall/control/error row，再检查真实帖子的稳定 id、非空文本与可解析时间；可解析时间包括带时区 ISO 值以及 2000–2100 范围内的 Unix 秒/毫秒。混合 dataset 只保留真实帖子，只映射账号身份而缺少内容字段的元数据行不得使后续真实帖子失败；全为元数据时返回 `apify_actor_metadata_only`，全占位结果为 Actor failure，二者都永不写 Feed。Actor 明确声明 no-results 的控制行是 `valid_empty`；没有任何声明的原始空 dataset 先记为 suspicious evidence，只有在 15 分钟内命中两个此前返回过真实帖子的不同 source 才熔断 Actor，否则按该 source 的合法无新帖完成且不污染 Feed。
35. Actor 404/410 映射为 `apify_actor_deleted`，明确 build unavailable 映射为 `apify_actor_build_unavailable`，二者与合同严重漂移一次即 open 并切下一候选；普通系统性异常必须在 15 分钟内跨两个此前 `valid_nonempty` 的不同 source 才 open。单 source 连续两次异常只暂停该来源六小时。
36. 冷却依次为 1/3/6/24 小时；到期只转 half-open 并等待自然任务，禁止额外健康检查。全候选不可用时只延后 X 调度到最近 retry time，Feed 保留历史 X 内容并标记 partial，非 X 来源继续。
37. 费用 admission 只在 active/standby/draining 全部可用 Key 都具有不超过 60 秒的完整额度快照时计算：X 可用额为总剩余减 `max($1, 20%)`。未知、缺失、过旧或异常未来快照全部 fail closed，Worker 启动先刷新所有此类 Key。滚动六小时 Actor failure 的最终实际费用达到 `$0.08` 立即 `budget_blocked`；准入还必须原子满足 `failed_spend + outstanding_reservations + $0.02 <= $0.08`，仅在途预留占满时只暂拒新 Run，不误触发六小时熔断。额度低于 20% 或预计不足 48 小时只产生运行告警而不重复付费探测。
38. Actor route generation 必须进入 shared acquisition fingerprint；同次合法 failover 的成功值只有携带 route 服务签发、等于发布时最终 generation 的证明才可迁移原 acquisition claim，Key generation 同时变化或无证明则拒绝。管理员禁用、排序或其他 generation 变化后到达的旧结果只能结算已发生费用，不能增加候选成功数、写 target health、缓存或 Feed；路由服务自身的 reconcile/恢复变化必须把 attempt 采纳到最终 generation 后才可 GET-only 重放。

Feed retention / legacy archive compatibility 规则：

1. `GET /api/feed/latest` 从当前用户隔离的 `user_content_items` 稳定索引投影 `feed_start <= effective_at <= now` 的内容，按 `effective_at DESC, article_id ASC` 稳定返回；最新 schema-v2 snapshot 只提供生成元数据和已保存集合成员证据。不得读取全局 `data/site/radar-data.json`、`history-data.json` 或 `article-graph.json`。响应增加 `window{timezone="Asia/Shanghai",feed_days,today_start,feed_start,now}`，`feed_days` 来自工作区 `filtering.feed_window_days` 且只允许 `7/14/30`。
2. `effective_at` 是稳定展示时间：优先使用可解析且不超过当前时间五分钟的可信 `published_at`，否则使用首次入库时间。缺失、非法或异常未来发布时间不得进入未来；同一稳定 article ID 的重复抓取只更新展示内容和 `last_seen_at`，不得改写已有 `effective_at` 把旧内容重新移回 Feed。v11 以带备份的显式迁移回填 `effective_at/search_text` 和增量 FTS5 索引。
3. 上海当天为当地 `00:00` 到 `window.now`，Feed 为当天及之前 N-1 个自然日，History 严格为 `effective_at < feed_start`。compat view 的 `today_items` 只是最终 `items` 中 `timeline_bucket=today` 的子集；canonical view 省略该重复集合，客户端必须从同一 `items` 过滤。Feed 与 History 必须无重叠、无遗漏。管理员调整 `feed_window_days` 后下一次读取立即重新分层，不抓取、不创建 snapshot，也不删除内容。
4. `GET /api/feed/latest` 的 item 包含当前用户 `user_state`，最少表达 `is_read/is_saved/is_later/dismissed` 和对应时间字段；无状态时返回 false/空时间。每项增加 `timeline_bucket=today|feed` 和 `presentation.timing.effective_at`。
5. `GET /api/feed/latest?hide_dismissed=true` 不返回当前用户已忽略 item；`unread_first=true` 将未读稳定排到已读前；`saved_first=true` 将收藏稳定排到未收藏前。默认参数全部为 false，保持稳定时间顺序。
6. `GET /api/feed/history` 支持 `q`、`source_id`、`limit` 和 `offset`；`limit` 必须为 `1..200`，默认 200，`offset` 为非负整数。响应至少返回 `schema_version=2`、`scope=user`、`window`、`snapshots`、`items`、`featured_items`、`item_count`、`total_count`、`limit`、`offset` 和 `has_more`；`item_count == len(items)`，`total_count` 是分页前命中数。无历史时 items/featured 为空且两个计数为 0。
7. `snapshots` 保留目标用户最近 20 个 snapshot 的摘要，按新到旧排列；每项包含 `snapshot_id/generated_at/item_count/job_id`。History item 真源是同用户稳定索引中 `effective_at < feed_start` 的行，不读取 `data/site/history-data.json`、`data/horizon.db`、`ArticleStore` 或旧 snapshot item 拼接结果，因此超过最近 20 份 snapshot 的稳定内容仍可达。
8. History 先在完整历史集合上执行来源和文本过滤，再按稳定时间排序并分页。`source_id` 同时匹配稳定行标量、item 标量、Presentation source ID 与 `source_ids` 数组 provenance；查询来源对目标用户不可见时返回 404。`q` 最多 160 字符，覆盖标题、来源、作者、摘要/正文、频道和主题等公开展示字段，不得通过原始 JSON 模糊匹配泄露内部 ID 或配置。管理员 `user_id` 代查仍严格使用目标用户的 workspace/user 数据和可见来源权限。
9. `featured_items` 只沿用最近 snapshot 中已有 `featured_items` / `featured_item_ids` 的历史成员证据，不按当前分数重新计算；顺序跟随最终 page items。每个 item 补充目标用户当前 `user_state` 和 `timeline_bucket=history`；sources/channels/categories/tags/topics/personal_tags 等筛选集合从当前 page items 稳定重建。
10. `GET /api/feed/search?q=&limit=&cursor=&submitted=` 只搜索当前登录用户的 Feed、在线历史和冷归档元数据，不接受管理员 `user_id` 代理。结果按 `effective_at DESC, article_id ASC`，每项标记 `timeline_bucket=today|feed|history`，响应返回 `item_count/total_count/has_more/next_cursor/window`。`limit` 为 `1..50`，默认 50；空词或超过 160 字返回 400，单字符必须显式 `submitted=true`。三字符及以上走增量 FTS5 trigram，两个字符走用户隔离的有界 `LIKE`，任何 SQLite 搜索超过一秒中止并返回可重试 `503 search_timeout`。冷归档搜索只含永久保留的标题、来源、作者、摘要、频道和主题索引；搜索旧内容不改变其时间归属或 Feed 成员。
10A. 跨 source URL 去重后的 item 必须保存完整 `source_ids/subscription_ids/source_keys` provenance；partial refresh 只要该 provenance 与失败的 active source 有交集，就保留窗口内旧 item。URL query 是内容身份的一部分，不得把不同 query identifier 的文章误合并。
10B. 全量刷新把本次结果与当前用户稳定内容索引及最新 snapshot 中“仍属 active source 且仍在采集窗口内”的内容合并；同一 canonical identity 由本次结果覆盖展示字段，但窗口内的不同文章不得因该来源本次抓到新内容或成功返回空集合而消失。已取消订阅来源立即排除；失败来源同样保留窗口内旧内容。全部来源失败不生成 snapshot；只有 active source 没有任何本次或索引中的采集窗口内容时，全部成功且为空才生成空 snapshot。
10C. `latest_per_source` 只对显式声明该 retention 的来源生效：序列化 item 以 additive `retention_policy_explicit=true` 标记该事实，同一 provenance 的新 latest 替换旧 latest。X/Instagram profile 未显式声明时统一采用 `time_window`；读取缺少该标记的遗留 `latest_per_source` 社交快照时按 `time_window` 规范化，并可从用户稳定内容索引恢复仍在采集窗口内但已被旧 snapshot 替换的帖子。该兼容不迁移或重写历史 snapshot。
10D. X/Instagram profile adapter 只返回 acquisition time window 内的帖子；Actor 成功但只返回超窗旧帖时结果为成功空集合，Source Health 记录 `last_fetched_count=0`，内容未变化时复用 snapshot。Facebook page/group/post 与 Telegram channel 保留既有 stale fallback；本规则不触发额外 Actor 调用。
10E. `source_fetch` 按 canonical identity 合并目标来源结果到最新采集 snapshot，不替换其他来源；目标来源的普通采集窗口内容继续累计，只有显式 `latest_per_source` 会替换其旧 latest。Service Feed 随后独立从稳定索引按 `feed_window_days` 投影；`personal_only` 内容进入用户稳定索引和 Feed，但跳过 AI、精选和推送。
11. `GET /api/archive/graph` 固定返回 `{"nodes": [], "edges": [], "scope": "user", "capability": "disabled", "degraded": true, "reason": "user_scoped_graph_not_available"}`，不得读取全局图文件；默认 Service UI 无 Graph 入口。
12. compatibility-only `GET /api/archive/items` 返回 `{items, page, filters, scope}`，支持 `channel/topic/source/date_from/date_to/min_score/limit/offset/sort/order`。
13. compatibility-only `GET /api/archive/trends` 支持 `group_by=channel|topic|entity|source` 和 `bucket=none|day|week`。
14. compatibility-only `GET /api/archive/facets` 返回既有 `channels/topics/sources/entities` 计数；`GET /api/archive/source-quality` 返回既有 source 质量字段。默认 UI 不调用这些路由。
15. 兼容 archive 路由的非法 query 参数仍返回统一 error envelope，例如 `invalid_sort`、`invalid_order`、`invalid_date_range`、`invalid_group_by`、`invalid_bucket`。
16. Service source config 把 subscription `priority` 以 `source_priority` 传入所有 adapter 输出；snapshot item 顶层保存整数 `source_priority`。旧 snapshot/item 缺该字段时按 `0` 处理。
17. 跨 source URL 去重时，合并 item 的 `source_priority` 取参与组的最大值，并继续保留全部 `source_ids/subscription_ids/source_keys` provenance；不能因选择内容最丰富的 primary item 而丢失较高 priority。
18. Feed finalizer 的 canonical `items/today_items` 排序精确为 `(score DESC, source_priority DESC, published_at 或 fetched_at 的 UTC instant DESC, id DESC)`。score 永远是第一排序键，较低 score 不得靠 priority 越过较高 score；全部 score 缺失或为零时自然变为 priority 优先。
19. `source_fetch` 创建新 snapshot 前必须把目标源新结果与最新 Feed 的全部保留 item 合并后统一按上述规则重排；既有历史 snapshot 的 payload/items 不得被原地改写。
20. latest/history 的每个新 item 必须提供 additive `presentation` 对象，`version=1`。该对象是 React 的规范展示投影，至少包含：
   - `source{id,catalog_type,platform,name}`；
   - `author{name,kind}`，其中 `kind=person|account|channel|organization|unknown`；
   - `timing{published_at,fetched_at}` 和 `links{canonical_url,source_url}`；
   - `content{title,title_origin,excerpt,content_kind,excerpt_truncated,format,format_origin}`；
   - `taxonomy{channel,configured_topics,inferred_topics,topics,entities}`；
   - `engagement{native_score,likes,comments,reposts,shares,upvote_ratio}`；
   - `analysis{status,score,signal_strength,signal_type,summary_zh}`；旧 snapshot 可能附带可选 `action_suggestion`，仅供兼容读取。
21. `presentation` 由 `src/services/content_presentation.py` 统一生成，不允许各 adapter 或前端自行拼不同结构。`content.excerpt` 必须清洗 HTML/脚本、排除评论附录并硬限制 600 字；`analysis.summary_zh` 遵守全局 100..500 字配置且默认不超过 200 字。新分析不得生成 `action_suggestion`，React 不得读取它；`presentation.analysis` 禁止出现 `reason`。内容格式按“上游明确类型 → 强确定性 URL/来源规则 → 同一次可选 AI 分析 → 安全来源兜底”解析，不得为了格式分类新增独立 AI 请求。YouTube channel Atom 条目沿用 RSS adapter，不过滤普通视频、Shorts、公开直播或回放；YouTube 内容链接必须确定性投影为 `source.platform=youtube`、`author.kind=channel`、`content.format=video`，既有 RSS snapshot 缺失或仍标成 RSS/person 时也按链接补全。
21A. `GET /api/feed/items/{article_id}` 把规范详情升级为 `presentation.version=2`，在 v1 基础上增加 `source.avatar_url`、`content.body_text/body_truncated/body_completeness` 与 `media.images/count/total_image_count/truncated`。`source.avatar_url` 遵守第 12B 条的当前 ready 投影，不以条目是否在本次抓取窗口内为前置条件。`body_text` 只来自抓取器已经捕获的正文，清洗为纯文本并硬限制 20,000 字；旧 snapshot 只能回填已有摘要并标记 `excerpt_only`，不得请求网页代理或由 AI 编造正文。详情先按 checksum（缺失时回退 asset ID）去重 ready 内容图片，再按最新记录取最多 6 张；`count` 是实际可展示的唯一图片数，`total_image_count` 优先使用上游可信原始总数并至少为 `count`，`truncated=true` 仅表示确有图片未缓存。历史重复行不做破坏性删除，也不得重复投影。
21B. 收藏和稍后读状态使对应 `user_content_items` 跨普通 snapshot retention 保留；取消两者后恢复普通内容保留策略。文章被选中或打开详情不得自动修改已读；只能由显式 PATCH 切换已读/未读。
22. `content_kind` 只允许 `feed_summary|release_notes|event_description|post_body|message|caption|discussion|metadata_only`；它描述来源片段语义，不等同于展示格式。`content.format` 只允许 `article|video|image|gallery|audio|social_post|discussion|release|other`，`content.format_origin` 只允许 `upstream|deterministic|ai|fallback`；`title_origin` 只允许 `native|generated`；`analysis.status` 只允许 `ai|fallback|personal_only|disabled`。缺失的原生互动量以 `null` 表达，不得伪造为零；Service API item 不返回原始 `content`。
23. 全量与增量合并必须共用 canonical URL merger；host 规范化不删除 query。合并保留全部 `source_ids/subscription_ids/source_keys`，优先复用最新 Feed 的 article id，再按 priority/source/native id 稳定选择内容。
24. 每次 finalization 对有序公开 Feed 内容和 featured/daily/personal 成员集合计算 `content_hash`，排除生成时间、job/run 诊断和实时 user state。hash 未变化时复用最新 snapshot id 并返回 `snapshot_created=false`；内容变化才创建新版本。最后一个订阅失效只创建一个空版本，后续重复 reconciliation 为 no-op。
25. 只有 `HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED=true` 且目标数据库已记录 Feed storage v3 migration 时，新 snapshot 才使用 `storage_version=2`：完整 item 只写 `user_feed_items.item_json`，snapshot payload 只留 metadata、item id 顺序及 featured/daily/personal id 集合。代码与示例配置对新空库默认 true，但 migration marker 仍是不可绕过的硬门禁；现存数据但未迁移的数据库继续写 legacy storage v1，既有部署也可显式设为 false 保持关闭。Reader 必须双读 legacy 完整 payload 与 compact payload，旧 snapshot 不原地重写。真正无 v3 遗留数据的新空库可在 additive 初始化时自动记录 marker。
26. v3 migration 完成后，Worker 每小时至多一次执行固定轻量 retention：Feed snapshot 最长 30 天且每用户最多 20 份、source content snapshot 7 天、AI cache 30 天、usage 90 天、terminal jobs 14 天、过期 session/旧 proposal 和孤立媒体；始终保留每用户最新 Feed snapshot 与每 acquisition key 最新 source snapshot。该自动任务不得删除 `user_content_items` 或仍有稳定内容引用的媒体。存在旧数据但尚未记录 v3 时 Worker 不执行 retention，避免仅因部署新代码而自动删除历史。
27. 存储治理必须先完成 Feed Storage v3 与 content timeline v11。`GET /api/admin/storage/summary` 返回固定策略、数据库/媒体/归档字节数、在线/冷归档内容及 snapshot/media/batch 计数、迁移 readiness 和最近清理时间；响应使用 `Cache-Control: no-store`，不得包含原始路径、SQL、正文或用户内容。
28. `POST /api/admin/storage/plans` 接受 `{"operation":"cleanup|archive|restore|delete_archive","payload":{...}}`。cleanup/archive 不接受 payload 字段；restore/delete_archive 只接受字符串 `batch_id`。成功只创建当前 actor 绑定、10 分钟有效的 `previewed` 计划，返回有界计数、候选 SHA-256 指纹和有效期，不修改候选业务数据。执行只能调用 `POST /api/admin/storage/plans/{id}/apply`；目标 workspace、actor、状态、有效期和候选指纹任一变化均 fail closed，失败不得清除或归档部分候选。
29. 标准 cleanup 只处理第 26 条轻量记录和孤立媒体，`permanent_content_deletes` 固定为 0；不提供任意 SQL、原始路径删除或在线 `VACUUM`。cleanup/archive/restore 允许 owner/admin，归档永久删除只允许 owner，且必须先恢复归档、确认没有在线冷引用，再提交精确短语 `永久删除归档 <batch_id>`。
30. archive 只选择 `effective_at` 早于 90 天、仍在线且未被收藏/稍后读、未处于通知 pending/sending 的稳定内容。服务端先在私有 `data/archives` 写临时 ZIP（manifest、NDJSON、媒体），校验 batch/workspace/计数并计算文件 SHA-256，原子落位与数据库批次提交全部成功后，才把在线正文/分析输入/媒体降为可搜索冷元数据并在提交后移除本地媒体文件；任一步失败必须回滚数据库并删除未提交归档。
31. 冷记录永久保留 article ID、标题、来源、链接、摘要、`effective_at`、频道、主题、搜索文本和归档批次，`GET /api/feed/search` 可继续命中；不得把它重新加入 Feed。restore 在读取前校验归档 SHA-256、manifest/workspace、条目数、媒体成员和每个媒体 checksum，安全原子恢复正文、搜索索引与媒体且保持幂等。`GET /api/admin/storage/archives` 只返回安全批次元数据；永不自动永久删除归档。

用户行为规则：

1. `GET /api/me/item-state?article_ids=a,b` 返回当前用户这些 article id 的状态 map；不可见或不存在的 id 返回默认 false 状态，不泄露其他用户数据。
2. `PATCH /api/me/items/{article_id}/state` 只允许当前用户写自己 feed 中可见的 item；不可见 item 返回 `not_found`。
3. compatibility-only `POST /api/me/items/{article_id}/feedback` 只允许当前用户对自己可见 item 提交 `more_like_this/less_like_this/not_relevant/wrong_topic/quality_issue`；默认 UI 不提供这些操作。
4. feedback 只做兼容入库，不驱动 Feed 过滤、排序、推荐、archive trends 或 source-quality；当前产品行为只使用已读、收藏、稍后读和忽略状态。
5. 忽略是当前用户作用域的可逆隐藏：设置 `dismissed=true` 后条目从默认 Feed 隐藏并进入 `/api/feed/ignored`；设置 `dismissed=false` 后从忽略集合移除。恢复只修改当前用户状态，不重抓来源、不重写其他用户数据。

## 6. 静态 JSON 输出合同
入口：`src/ui/site.py`；本节只描述 legacy CLI/static publisher 的兼容输出，不是默认 Service UI 数据源。

`radar-data.json` item 必须包含：

1. `id`, `title`, `source_type`, `source`, `url`
2. `published_at`, `fetched_at`
3. `score`, `reason`, `summary_zh`
4. `channel`, `topics`
5. legacy aliases: `category`, `tags`
6. `signal_strength`, `signal_type`, `entities`
7. `personal_tags`, `interest_score`, `show_in_personal_feed`

兼容要求：

1. 新 UI 优先读 `channel/topics`。
2. 历史数据只有 `category/tags` 时，必须 backfill 成 `channel/topics`。
3. 非 canonical 的阅读主题可以作为 custom topic 保留，不应自动变成 `personal_tags`。
4. 默认 Service UI 不直接读取 `radar-data.json`、`history-data.json` 或 `article-graph.json`；阅读与历史只通过 `/api/feed/*`，且默认不调用 archive analytics、Graph 或 feedback 路由。

## 7. SQLite 归档合同
入口：`src/storage/article_store.py`。本节属于 legacy CLI/archive compatibility；Service latest/history 不得依赖 `ArticleStore` 或 `data/horizon.db`。

`articles_light` 必须保留：

1. 旧字段：`category`, `tags_json`
2. 新字段：`channel`, `topics_json`, `signal_strength`, `signal_type`, `entities_json`
3. 兼容读取：旧库缺新列时由 `ArticleStore.initialize()` 迁移。

读取合同：

1. `load_articles_light()` 和 `load_premium_articles()` 返回 dict 时必须同时包含 `channel/topics` 与 `category/tags`。
2. 旧 row 缺 `channel/topics_json` 时，使用 `category/tags_json` 兜底。

<!-- init-pro:section name=errors -->
## 8. 错误响应合同
所有公共接口必须定义稳定错误语义。

错误响应至少说明：

1. 错误码或异常类型
2. 人类可读错误说明
3. 调用方可执行的下一步动作
4. 是否可重试
5. 相关请求标识或资源标识

要求：

1. 不允许只返回裸字符串错误给 Web API 调用方。
2. 参数校验错误必须区分字段缺失、格式非法和业务约束冲突。
3. 外部系统失败必须表达为标准错误，不得泄露上游原始错误结构或敏感信息。

<!-- init-pro:section name=compatibility -->
## 9. 兼容性合同
当接口、命令、事件或模块函数发生变化时，必须说明兼容策略。

至少覆盖：

1. 新增字段是否向后兼容
2. 字段删除或语义变化的迁移方式
3. 旧版本调用方的保留周期
4. 默认值和缺省行为
5. capability / degrade 状态变化

要求：

1. 不允许无记录地改变已有字段语义。
2. breaking change 必须进入 `DECISION_LOG.md`。
3. 当前项目默认单版本，但必须保持字段语义稳定。

## 10. 幂等性合同
会创建、导入、触发任务、写入状态或调用外部副作用的接口必须说明幂等策略。

至少说明：

1. 幂等键来源
2. 重复请求返回既有结果还是创建新任务
3. 超时后客户端如何安全重试
4. 服务端如何记录重复请求

当前约定：

1. 静态 payload 写入按 item `id` 合并。
2. `ArticleStore.upsert_articles_light()` 以 `id` 为幂等键。
3. 单源刷新以 `source_ref + ContentItem.id` 避免重复发布已知历史 item。
4. 通知、邮件、webhook 不默认视为幂等，触发前必须确认配置和运行路径。
5. Service Feed snapshot 以非空 `job_id` 为幂等键；重复 finalize 返回既有 snapshot，不得创建第二份。snapshot item 以 `article_id` 稳定去重。
6. Source Health 以内部 `(subscription_id, job_id)` application ledger 保证 outcome 重放幂等；同一 job 的重复应用不重复累计失败。
7. 偏好来源通知以 `(subscription_id, article_id)` outbox 唯一键抑制全量/单源/重试重放；测试通知是显式非幂等人工动作，但不会消费内容唯一键或移动基线。
8. 触底文案立即刷新以 workspace 唯一状态行为幂等键；重复请求只保留同一个 pending/refreshing 状态。Worker 用 `BEGIN IMMEDIATE` 与原子 claim token/75 秒租约确保同一时刻最多一个执行者接管一个 workspace，过期租约才可重新抢占。
9. Apify 运行告警以 workspace、route、incident kind 与未解决状态抑制重复首报；升级到全挂创建独立 incident，恢复只关闭对应 open incident。明确失败 delivery 最多三次技术尝试，`unknown` 永不重放；测试告警是显式人工副作用但不创建 incident。每个付费 Canary 管理员动作生成一个不透明 `approval_id`；同一 ID 的传输重放只返回原 validation/job，不得再次扣费，真正发起下一次 Canary 必须重新打开确认、生成新 ID。数据库只保存 approval 摘要、批准时 generation 与不可变 USD 上限，不保存原 ID 或确认短语。
10. X/profile Actor attempt 以稳定 Job/source group 约束最多三次与 `$0.06`；同一 Job 的 terminal successful Dataset 是可重放的只读结果，重复执行只 GET 既有 Dataset，不创建新 attempt 或 Actor POST。缺少可验证 Dataset 时 fail closed。

## 11. 后台任务合同
异步、批量、定时、长耗时任务必须定义任务状态合同。

至少说明：

1. 任务 ID
2. 状态枚举
3. 进度字段
4. 成功 / 失败 / 部分成功结果结构
5. 超时策略
6. 重试策略
7. 并发或速率限制
8. 结果保留周期

当前任务边界：

1. 两份 compose 默认运行单元固定为 `horizon-api + horizon-worker`；`horizon-scheduler` 只在显式启用 `scheduler` profile 时运行。
2. 单源刷新是 Worker 异步任务，不启动 scheduler。
3. Full-text 和 article graph 仅可由旧 CLI/scheduler publisher 在对应配置启用时运行；Service Worker 和默认 UI 不运行或消费它们。
4. API、Worker、Scheduler 与 CLI 的 runtime/operation 日志写入 `logs/**`，UTC 每日轮转且默认保留 30 天；原始文件不进入 Agent 上下文，只有 5B 定义的当前用户脱敏结构化事件可由 OpenClaw 查询。
5. 响应结构诊断只在 adapter 收到上游值时即时提取字段路径/类型，原始值随调用栈释放；Job 只保留有界双层摘要，Feed snapshot、稳定内容索引和媒体记录不得保存该诊断。

### 11.1 信息流触底文案生成

1. `workspace_feed_end_messages` 是幂等新增的 workspace 级 SQLite 缓存表，保存三个列表、非敏感配置指纹、generation、刷新状态、原子租约、最近尝试/成功/下次刷新/退避时间和安全错误码；不保存提示词、模型原文、用户内容或密钥。指纹必须包含当前文案安全合同版本，因此 prompt、白名单或校验语义升级会把旧缓存标成待刷新而不需要数据库迁移。
2. 始终存在内置中文列表。全局 AI 或独立生成开关关闭时，GET 必须忽略旧 AI 缓存并返回 `source=builtin,status=disabled`；重新开启后，配置变化、手动刷新、到期或首次缺少缓存均可进入 pending，后台生成期间仍可返回上次通过校验的 AI 列表。
3. Worker 只有在普通任务队列无法 claim Job 时才检查触底文案；一次 idle 轮询最多 claim 一个 workspace、记录一个 workspace AI attempt，并发起至多一次 60 秒模型请求。该调用关闭 SDK 自动重试，不创建普通 Job，也不由 scheduler 驱动。
4. 模型结果必须是只含 `empty/first_end/repeat_end` 的 JSON object；每个数组恰好等于配置条数，三个数组全局去重。每句必须为 trim 后 4–40 字的单行简体中文纯文本，禁止 HTML、Markdown、URL、催促、羞辱、焦虑表达和虚假完成声明。每句可选且最多带一个克制装饰，白名单为 `🙂/😊/🌿/☕/✨/📚/🍵/🌙/🫧/^_^/:)/:-)/(・ω・)/(´▽｀)/(｡･ω･｡)`；`☕` 的标准 emoji variation selector 视为同一装饰，其他 Emoji、颜文字或多个装饰均拒绝。自定义风格不得覆盖这些约束。
5. 成功后 generation 原子加一并按 `refresh_days` 安排下次刷新。超时、配额、调用或输出校验失败只写安全错误码，保留上次成功列表；从未成功则回退内置列表。失败固定六小时后才可自动再试，手动刷新或配置指纹变化可提前触发。

## 12. Feed v2 显式迁移合同

实现中存在迁移脚本不代表任意部署数据库已迁移；当前本地目标部署已于 2026-07-11 显式迁移并验收，是否完成仍必须逐个目标数据库以 migration marker 与 readiness 为准。其他旧库不得沿用本地部署结论，仍需逐库显式执行并验收。

1. 未记录 v2 migration 且存在旧 snapshot/item/state/feedback，或存在 queued/running 的 `source_fetch/user_feed_refresh` 时，readiness 返回 `migration_required`，Worker 拒绝执行 Feed 任务；只有真正无这些遗留产物的新库才可自动记录空库 v2 marker。
2. 应先停止 API、Worker 和 scheduler，再运行 `python scripts/migrate_user_feed_v2.py --data-dir data --backup-dir data/backups --apply`；不带 `--apply` 使用 SQLite 只读连接检查，不建表、不增列、不写 migration marker。
3. apply 必须先生成 UTC 时间戳 SQLite 备份，再取消未完成 Feed job、清空旧 snapshot/item/state/feedback、创建 v2 唯一索引、写 migration 记录并通过 `PRAGMA foreign_key_check`。
4. 应用启动不得自动清空旧 Feed 数据；真实环境迁移属于显式运维动作。
5. 已完成迁移时重复 `--apply` 必须返回 `already_migrated` 且不备份、不清空 v2 数据；备份权限固定为 `0600`，`data/backups/` 不进入 Git。

## 13. User content v5 与 DeepSeek 分析合同

`user_content_items` additive 增加 `analysis_input_hash` 与 `unresolved_reason`。`analysis_input_hash` 是模型无关的来源输入 SHA-256；正文或来源元数据真正变化时才变化，不得因模型切换或历史修复而伪造新分析。

历史修复 CLI 固定为：

```bash
python scripts/repair_user_content_v5.py inspect --data-dir data --output /tmp/content-repair.json
python scripts/repair_user_content_v5.py apply --data-dir data --backup-dir data/backups --cache-legacy-media
python scripts/repair_user_content_v5.py reconcile --data-dir data --backup-dir data/backups
python scripts/repair_user_content_v5.py enqueue --data-dir data --free-only
```

1. 报告固定包含 `status/counts/repaired_body/repaired_media/enqueued_sources/unresolved/backup_path`。
2. inspect 使用只读 SQLite；apply 必须拒绝活跃 Worker、先生成 `0600` 备份，再校验 integrity/foreign keys 并写 version 5 marker。
3. reconcile 必须在任何 `queued/running` Job 或活跃 Worker 存在时于备份前拒绝；有变更时先生成 `0600` 备份，再事务性把 `unresolved_reason` 升级为 nullable，并只从非空 `captured` 正文移除精确 token `source_body_not_available`。其他 reason 必须保留；无剩余 reason 时写 SQL `NULL`。重复运行返回 `already_reconciled` 且不创建备份。
4. `content_repair` 只更新已有 `user_content_items` 的正文、媒体、哈希和 unresolved reason；新抓到的 article 必须忽略，结果固定声明 `snapshot_created=false`、`analysis_calls=0`。
5. 免费来源允许批量入队；Apify social 等付费来源不得由 `--free-only` 入队，必须报告 `paid_source_requires_authorization`。不建设网页全文代理。
6. 详情 `captured` 返回来源接口已有正文；`excerpt_only` 明确降级。媒体最多 6 张且只返回鉴权 `/api/media/*`，不得返回上游临时 URL。

AI Secret metadata 的 `kind=ai` provider 允许 `deepseek`；真实值仍为 write-only。DeepSeek 默认模型和环境变量名固定为 `deepseek-v4-flash`、`DEEPSEEK_API_KEY`，Base URL 缺省时由客户端使用官方地址。

分析复用顺序固定为：当前模型精确 cache → 同用户、同 article、同 input hash 的其他模型安全 cache → 同 input hash 的稳定安全 AI 投影 → 当前 provider。跨用户、输入变化、fallback/excerpt 原文均不得复用。跨模型复用必须记录原模型或 `stored-content`，不得把旧结果标记为 DeepSeek 产物。真实启用前，`scripts/deepseek_analysis_smoke.py` 必须先以 10 秒超时、SDK retry=0 调用 `models.list()` 并确认精确模型；预检失败时 completion 为 0，成功后才允许对一篇 captured article 做恰好一次 completion。该 completion 必须省略 `temperature` 并禁用通用客户端的应用层参数降级重试，首次失败即终止。stdout 只含 provider、model、token 用量和 status。

## 14. Apify ActorOps v15 合同

1. Route 身份为 `platform + target_type + capability`，并有 opaque `route_id`；首期支持 Profile 严格限定为 `x/profile/items`、`youtube/channel/items`、`instagram/profile/items`，其中 X 的永久兼容 `route_key` 保持 `x/profile`。不支持的 tuple 必须在事务与 CAS 前以 `422 apify_actor_route_profile_unsupported` 原子拒绝，不得创建 Route、run 或 Job。每条 Route 固定三槽、`required_slots=3`、`min_runtime_healthy=2`、`min_publishers=2`，缺省单 Run 上限 `$0.02`。
2. Adapter Revision 不可变，生命周期只允许 `proposed → static_valid → probationary → certified` 或 `quarantined/superseded/rejected`；迁移兼容可使用 `legacy_builtin`，但不得伪造 Build、Manifest 或认证证据。attempt 在启动前冻结 `adapter_revision_id/build_id/build_number/manifest_hash/target_fingerprint`；来源与参考 Canary 使用 workspace/Route 加盐的规范目标指纹，X/Instagram 的 URL 与同一 handle 必须归一，不保存明文 target。
3. `GET /api/admin/apify-routes/{route_id}` 必须投影服务端计算的 `activation_recommendation` 与 `activation_mode`。服务端优先选择前两槽 certified、第三槽 probationary/certified 的完整 `standard_2plus1`；完整池暂不可达时，可选择两个各成功一次 Canary 的 probationary/certified exact-Build Revision 组成 `expedited_2of3`，两者 Actor 与发布者均不同，第三槽保持 NULL 且不参与运行或费用。管理员首次或补位激活只向 `POST /api/admin/apify-routes/{route_id}/active-pool/activate` 提交 `expected_generation` 与 `confirmation="确认启用 Actor 主备"`；浏览器不得提交推荐 Revision ID，服务端必须在同一写事务中重新计算方案、执行 CAS 与完整 Manifest/Build 校验后原子增加 Route generation。没有安全两路返回 `412 apify_actor_active_pool_not_ready`，已生效方案不得重复激活。低层 `PUT .../active-pool` 仍用于 CAS 调费、显式回滚和兼容管理，接受两或三条已填充 Revision；槽位未变化的调费不得重置 Candidate circuit、Route/Key 阻断或来源验证，部分槽变化也必须保留未变化槽 runtime state。显式回滚必须携带唯一 `rollback_revision_id`、只改变该 Revision 所在槽，并按 `superseded_from_lifecycle` 恢复旧认证等级，历史 `legacy_builtin` 不得伪装成普通新激活。少于两个 runnable 时 schedule/Worker 返回安全阻断，不产生付费 Run。
4. Manifest v1 的 input 只能是 JSON literal 或精确引用 `target.canonical_url/native_id/handle`、`runtime.max_items/since_iso/until_iso`；output 只能使用 RFC 6901 Pointer 与 `pick_first/to_string/to_integer/to_number/to_boolean/parse_datetime/normalize_url/strip_html`。每个 Pointer 必须能在已拉取的精确 Build Dataset Schema 中确定性解析；无法证明的路径在官方 input validation 和付费 Canary 前以 `apify_manifest_output_pointer_unverifiable` 淘汰。统一输出必须有 `native_id/url/published_at` 与 `title|text`，并通过目标身份、URL host、占位/付费墙、时间与非空校验；Profile/Channel 的 items Route 不得把内容条目的 `url` 同时当作 `source_url` 身份证据，也不得只用 `channel/profile` 自身的 ID 或 URL 充当内容条目身份；带有 `video/post/tweet/item/media/short/reel` 语义的字段仍属于内容身份。
5. Discovery 最多三轮官方 Store 搜索，缺省采用 agent response 且不包含不可运行 Actor；三条首期 Route 使用内容类型专属查询，YouTube 精确检索 channel videos，Instagram 精确检索 profile/user posts 与 profile feed，避免账户资料型 Actor 挤占内容候选。每个 run 接受的候选数由热配置 `max_candidates` 有界为 3–30（默认 12）。非公开、不可运行、deprecated、full-permission、月租或最低费用超 Route 上限、无成功精确 Build/可验证 Schema、无法从公开 input schema 安全映射目标、重复 Actor/发布者不足必须先由确定性代码淘汰。YouTube Channel Items 的 pay-per-event 定价若除启动费外只声明 channel/profile/statistics/subscriber/enrichment 等元数据事件，必须以 `actor_items_capability_unproven` 在 AI 与付费前淘汰；`result` 等泛化事件不作为正向证明也不单独拒绝，仍由 Manifest 与 Canary 验真。Actor 使用官方 opaque `id` 与 `username/name` 归一化身份，Build 从 tagged build 读取精确 ID/number；input schema 和 Dataset `fields` 构成合同，presentation `views` 不参与合同哈希。pricing 取当前最新生效记录并校验最低费用、单价与 pay-per-event 分层价格。目标 URL/handle/native ID 在 string、array 或标准 `startUrls` object 中的形状及一个有界 max-items 字段由确定性代码从公开 Schema 生成受限模板；AI 只能复制该模板，并负责对已拉取候选排序、生成输出映射和语义规则。AI 在一次调用中被要求返回当前目标数的 3–6 个 best-first Manifest proposal，至少覆盖两个已拉取发布者；Prompt 必须包含 Manifest v1 完整合同、精确数组 cardinality 与结构示例，少于目标数记录安全 shortfall，非法 JSON、未知 Actor/Build 或 README 指令不得进入 Canary。系统先完整拒绝 AI Manifest 中的危险输入，再用确定性模板规范化 input，依次静态校验并调用指定 Build input validation；后续 proposal 可补位前序无效项。每个通过项立即保存为 `static_valid` Revision并关联当前 Run，即使最终不足三 Actor 或两发布者也不得整批丢弃。Store/Actor/Build GET 与 input validation 都显式请求 identity encoding；429、5xx、网络或响应解码错误最多重试三次并遵守最长 30 秒的 `Retry-After`。input validation 的 `200 valid=false` 及候选相关 400/403/404 只淘汰当前候选，后续 proposal 必须继续；401 终止整个 Run 为 Apify Key 认证失败，其他请求合同错误以 `failure_phase=input_validation` 终止，重试耗尽只记录安全 unavailable reason。只有当前 Run 至少三个有效 Revision且覆盖两个发布者时才进入 `awaiting_canary_approval`。Discovery settings schema v4 保存管理员从当前全局 Provider 的安全 Key 列表中人工选择的 opaque `ai_config_id`、内部 SecretStore 引用、enabled、调用边界、`max_output_tokens`（4096–65536）与 generation；PATCH 拒绝旧 provider/model/secret 字段。每个 Job 开始时冻结全局 AI 的 provider/model/base URL、该人工选择的唯一 Key 和输出上限，不回退其他 Key，单次调用超时为 180 秒。所选 Key 不可用时，启用返回 `409 apify_actor_discovery_global_ai_unavailable`，Job 必须在 Store、模型和付费 Actor 调用前进入 `blocked_ai_unavailable`；被 Discovery 选择的 Secret 不可删除，AI SDK transport 必须在当前 Job 的 event loop 退出前显式关闭。
6. Route 认证缺少安全两路时，管理员先读取 `GET .../canary-plan` 核对服务端选出的最多三个候选，再以一次 `confirmation="确认付费验证主备"`、不可复用到其他动作的 `approval_id`、plan hash、Route generation 和批次总 USD 上限提交 `POST .../canary-batches`。同一事务必须创建不可变 batch、逐候选 validation 与唯一 one-shot Job；浏览器不得提交 Revision 列表或改变顺序。批次严格串行，并在每次付费 POST 前免费读取公开 Actor 与精确 Build：Actor/Build 已删除、私有、不可运行、Build 漂移或确定性 403/404/410 时必须停用该 Revision、以 `$0.00` 终结且不占五次 Canary；只有免费预检通过后才创建 attempt 和远端 Run。两个不同 Actor、来自两个不同发布者且均返回有效内容或可信空结果后立即停止，所有未启动候选以 `$0.00` 终结。每候选默认封顶 `$0.02`、单批最多 `$0.06`，Discovery cycle 默认总上限 `$0.10` 且最多五次真实启动；远端实际费用可以合法为 `$0.00`。`start_outcome_unknown` 必须阻断整批、Route 与 Key，禁止继续候选。每次 Actor 最长等待默认 300 秒，可由 `HORIZON_APIFY_ACTOR_CANARY_TIMEOUT_SECONDS` 在 180–900 秒内为下一 Job 热加载；超时必须中止已知 Run且禁止自动重试。远端终态费用以 `apify_actor_runs` 为真源回写 attempt/validation，Worker 启动时幂等修复旧的不完整对账。Route 参考 Canary 若确认不可变 Build 只返回元数据、占位内容或违反统一内容合同，Revision 必须从 `static_valid` 进入 `rejected`、从 `probationary` 进入 `quarantined`，历史失败证据也必须阻止重复付费；超时和暂时系统故障不属于该永久判定。达到两个安全 probationary/certified Revision 后批次进入 `activation_ready` 并允许独立确认快速激活；候选耗尽仍不足两路时保留成功证据、批次进入 `partial`，Worker 自动创建一次不运行 Actor 的 Discovery 补位任务。approval 重放返回原 batch/Job，参数、plan 或 generation 不一致则冲突，不得产生第二个付费 Run。旧的单 Revision Route Canary 接口只作兼容；来源级 Canary 继续使用 `confirmation="确认付费试跑"` 并逐槽确认。每条 validation 冻结其 `discovery_run_id`，已终结实际成本与仍排队的批准上限分开投影并合并占用预算，Revision 被后续 discovery 复用也不得篡改历史费用归属。完整 2+1 的 Primary/Backup 1 仍需两个不同公开参考来源成功、48 小时观察且有效 attempt 成功率至少 95% 才 certified；快速模式的两路各成功一次即可 probationary 运行。
7. 新来源按当前实际运行槽位串行验证，默认总上限 `$0.06`；两槽快速池全部通过后为 `ready_2of2`，完整三槽全部通过后为 `ready_3of3`。每个运行 Actor 都必须确认身份并返回真实内容或可信显式空结果。首次启用另需 `confirmation="确认首次启用"`，binding 状态切换与 source enabled 必须在同一事务中原子完成，同 generation 重放幂等。第三槽后续补位或 Revision 变化只使变化槽待复验，既有成功验证仍有效。
8. Worker 开始时冻结 Route、binding、Key generation 与三 Revision；每个 Run 传精确 `build`、`maxItems=1`、Route `maxTotalChargeUsd`，Dataset GET 另有行数与字节上限。所有 Apify 请求显式发送 `Accept-Encoding: identity`；幂等 GET 的网络或解码错误最多使用同一 Key 重试三次。已启动 Run 的 Dataset 重读绝不创建第二次 Actor POST或切换槽位；重试耗尽转换为安全 reconciliation 阻断并保留远端 Run 与费用账本。Key 401/402 只交 Key Pool；Actor Build 消失/合同漂移/系统故障才切下一槽；目标私有/删除只更新 target health；`start_outcome_unknown` 的 attempt 终结、validation 终结与 Route/Key 阻断必须在一个事务提交，任一步失败则全部回滚为可由重启恢复扫描处理的 running 状态，且禁止切槽；`valid_empty` 成功，`suspicious_empty` 可串行回退。
9. 所有结果在写共享缓存或 Feed 前再次通过 publication fence。该 fence、source avatar/media cache 引用、Feed snapshot、source health 和 schedule advancement 必须完成于同一 `BEGIN IMMEDIATE` 发布事务；缓存文件使用双向 journal，提交后才删除旧文件，回滚时删除新文件，不得留下断开的 DB/文件引用。运行中旧 generation 可以完成和结算，但 Route、binding、revision set 或 Key generation 任一变化都使结果过期，不得写入新状态。
10. 新 Apify-primary source config 为 `profile_id + target`，不重复保存平台、Actor 或 Build；旧 `platform/kind/target` 继续兼容。YouTube 始终保存为 RSS，原生成功/可信空不调用 Apify；允许回退的错误只使用已验证 binding，结果保持原 source 与稳定 Feed ID。
11. 管理 API 为：
    - `GET /api/admin/apify-routes`
    - `GET /api/admin/apify-routes/{route_id}`
    - `POST /api/admin/apify-support-checks`
    - `GET /api/admin/apify-discovery-runs/{run_id}`
    - `GET /api/admin/apify-discovery-runs/{run_id}/canary-plan`
    - `POST /api/admin/apify-discovery-runs/{run_id}/canary-batches`
    - `GET /api/admin/apify-canary-batches/{batch_id}`
    - `POST /api/admin/apify-discovery-runs/{run_id}/candidates/{revision_id}/canary`
    - `PUT /api/admin/apify-routes/{route_id}/active-pool`
    - `POST /api/admin/apify-routes/{route_id}/active-pool/activate`
    - `GET /api/admin/sources/{source_id}/apify-support`
    - `POST /api/admin/sources/{source_id}/apify-validations/{revision_id}/canary`
    - `POST /api/admin/sources/{source_id}/apify-binding/activate`
    - `GET|PATCH /api/admin/apify-discovery-settings`
    - `POST /api/admin/apify-discovery-measurements`
12. 所有 mutation 必须带 `expected_generation`；support check 使用列表 envelope 的 workspace catalog `generation`，成功响应的 `generation` 仍为最新 catalog CAS token，另以 `route_generation` 返回对应 Route token；Route、binding、settings 等 mutation 使用各自对象的 generation，客户端不得混用。只有 owner/admin 可 Canary、调费、激活、替换或回滚，member 只可提交 support check。API 不返回 Token、Actor input、真实 target、远端 Run/Dataset、原始错误、README、原始 Dataset、approval ID 或 Manifest 中的 target 值。旧 `/api/admin/apify-actor-routes/x/profile*` 保留一个兼容版本：读取与排序代理到 v15 状态；旧 Canary mutation 因缺少显式费用上限和 approval 幂等键而安全拒绝，调用方必须升级到 v15 Canary 接口。
13. `GET /api/catalog/source-capabilities` 的 envelope `generation` 是 workspace catalog CAS token；items 只返回可创建来源需要的已认证 Route 元数据与安全表单字段，其中 Apify-primary 使用 `profile_id + target`，YouTube native-first fallback 使用 `url + keep_latest_item`。未知能力只创建 discovery request，不创建可调度付费 source。AI/Store 不可用只阻断新发现，既有 Route 继续运行。
14. Worker maintenance 最多每七天读取一次已激活 Actor/Build/Schema/权限/定价指纹；只持久化有界 SHA-256 observation，不保存原始元数据。相同 observation 的重复检查不得再次创建 proposal 或调用 AI；有 Build 消失、槽位不足、Schema/权限/价格漂移或人工请求时只创建 proposal，绝不自动付费、替换或激活。Store/AI 不可用时既有精确 Revision 继续运行。
15. 只有 owner/admin 可执行 `force_discovery=true`；member 每日最多提交 10 次 support check，同 workspace 最多保留 20 条未结束 Route 请求。强制重新发现 ready Route 只创建独立 discovery run，生产三槽在管理员后续激活前保持不变。
16. `GET /api/catalog/source-capabilities` 在完整 2+1 或快速两路池达到运行门槛时投影对应 Route 的安全创建字段；所有已填充 Revision 必须固定 exact Build、probationary/certified、Actor 唯一且至少两个发布者，旧 `legacy_builtin` 两路仍只服务兼容来源。Apify-primary 字段为 `profile_id + target`，YouTube fallback 保持原生字段。
17. Discovery run schema v4 在 `candidate_shortfall` 阶段也投影已持久化但不可付费审批的部分候选；只有没有静态能力冲突或历史永久输出失败的 Revision 才可进入服务端 batch plan，被阻断候选保留展示安全 rejection reason 且 `can_canary=false`。响应返回稳定 rank、`candidate_count/candidate_shortfall`、`publisher_count/publisher_shortfall`、已终结实际费用 `spent_usd`、仍排队批准上限 `reserved_usd` 和按安全 reason code 聚合的淘汰计数，不得把已通过的 `1/3|2/3` 显示成 `0/3`，也不得把批准上限伪装成实际费用。最近 batch 以安全投影随 Run 返回，刷新页面后仍可恢复 `queued|preflighting|running|activation_ready|partial|blocked_unknown_start|failed|cancelled`、成功 Actor/发布者数、实际费用及逐项 `$0`/终态；不得返回 validation ID、Run/Dataset ID、真实 target、Actor input 或上游正文。Canary plan 只返回 Route/模式、服务端顺序、Actor/发布者、精确 Build、商城定价摘要、逐项/总封顶、五次真实启动与 `$0.10` 周期预算的剩余量及 plan hash。管理员容量测试必须携带 `confirmation="确认AI容量测试"` 与 settings generation；首次只允许 YouTube/Instagram 顺序各一次 32768 上限的单模型调用，只有 32K `finish_reason=length` 的 Route 才可单独确认 65536 重测。测试不启动 Actor/Canary。Run 只保存请求上限、输入/completion/reasoning/content Token（供应商不返回时为 NULL）、finish reason、耗时、响应字节数及 JSON/Manifest 状态；不得保存 Prompt、正文、Key 或原始异常。两个 Route 均成功且非 length 时，建议值取最大 completion 的 1.5 倍向上取整到 1024，并限制在 8192–65536；建议只展示，不自动修改生产上限。淘汰 Actor ID、原始 metadata/错误、候选与真实 target 的关联不得返回。
18. ActorOps 的 feature/DSL 名称保持 v15，但共享运行库的 global migration 15/16 已由通知 schema 占用，`schema_migrations` 必须以 version 17、name `apify_actor_ops_v15` 和固定 checksum 三元组识别；不得仅凭 version 猜测或覆盖既有 marker。普通 API/Worker initialize 不得安装或修补 ActorOps 表，只有显式离线迁移可在 `0600` backup 后执行。支持的自动升级起点是已通过检查的 v13/v14；任何未发布 partial ActorOps 形状都 fail closed 并恢复备份。已安装旧 checksum 的受控修复只可删除完全无槽位引用、候选、Revision、binding、validation、attempt、target health、费用或非终态/已调用 AI 证据的误建 `youtube/profile/items`；否则中止并恢复备份。修复同时增加 `youtube/channel/items` generation，并清除旧独立 Discovery AI 字段；曾启用的旧设置强制停用并增加 generation。
19. Token 测量字段通过独立离线 migration `apify_discovery_limits_v16`（global version 18）安装；API/Worker 普通初始化不得静默加列。迁移要求 v15 已通过，停止 API/Worker且无 queued/running Discovery/Canary Job，使用 SQLite backup API 生成 `0600` 备份，并在提交 marker 前通过 integrity 与 foreign-key check；旧 Run 的用量保持 NULL，不伪造为 0。
20. 批次审批账本与精确费用证据通过独立离线 migration `apify_actor_canary_batches_v17`（global version 19）安装；API/Worker 普通初始化不得静默建表或加列。迁移要求 global version 18 已通过，停止 API/Worker、跨过 heartbeat 安全窗且不存在 queued/running Discovery、单 Canary 或 batch Job，使用 SQLite backup API 生成 `0600` 备份，并在提交 marker 前通过 integrity 与 foreign-key check。旧 validation 的批准上限不再当作实际费用：只有 Run/attempt 账本证明的终态实际费用才标记 `cost_final=1`；`start_rejected` 且没有 remote Run/Dataset、预留为零的记录修复为 `$0.00`、不计 Canary，并停用已失效 Revision。不能证明未启动的历史记录保持费用未知，不得伪造为零；任一失败恢复备份。
