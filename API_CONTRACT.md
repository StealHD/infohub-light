<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=API_CONTRACT.md -->
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
5. `source_catalog.source_key`: catalog source 的幂等身份键，由 `src/services/source_type_registry.py` 生成，例如 `rss:https://example.com/feed.xml`、`github_release:owner/repo`、`reddit_subreddit:localllama`。

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
6. 删除主题只改变未来候选词和 AI 分类偏好，不级联修改 catalog source、用户订阅或历史 snapshot；这些对象中的旧引用继续按兼容值返回。

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
4. `GET /api/catalog/source-types`：返回 source type registry 元数据、必填字段、config template 和 additive `fields`。每个 field 精确包含 `name/label/input_type/required/default/options/min/max/help` 九个键；`input_type` 只允许 `text/url/number/select/boolean`，默认值、选项和范围必须与 registry validator 一致。`fields` 不包含 token、API key 或 `secret_env`；`secret_env` 仍是 catalog source 的独立属性。
5. `GET /api/catalog/sources`, `POST /api/catalog/sources`, `PATCH /api/catalog/sources/{id}`, `DELETE /api/catalog/sources/{id}`：公共、workspace、private source catalog；创建/更新必须通过 registry 校验 config 并写入 `source_key`；同一操作者重复或并发 POST 同一 key 必须幂等返回同一 source，跨用户 private key 碰撞和 PATCH key 碰撞返回统一 `409 source_key_conflict`；删除为软删除。
6. `POST /api/catalog/import-config-sources`：管理员把 `data/config.json` 中旧 source 列表幂等导入 `source_catalog`，可 `dry_run`，默认为当前管理员创建 subscriptions。
7. `POST /api/catalog/sources/{id}/subscribe`, `DELETE /api/catalog/sources/{id}/subscription`：当前用户订阅或取消订阅一个可见 catalog source。新增或重新启用订阅时必须先复用 workspace 内该来源已经索引的稳定内容并返回 additive `reused_item_count`，不得因此创建抓取任务；取消 shared source 只删除当前用户订阅，最后一个 private owner 取消订阅时软停用无人引用来源。
7A. `GET /api/catalog/sources/{id}/usage` 仅在客户端显式请求时计算并返回 `subscriber_count/enabled_subscriber_count`；`POST /api/catalog/sources/{id}/share` 只允许 private owner 把自己的来源提升为 `workspace|public`。提升后 `owner_user_id=null`，来源地址和管理权转交管理员，原订阅者随后取消订阅不得影响其他成员。
8. `GET /api/me/subscriptions`, `POST /api/me/subscriptions`, `PATCH /api/me/subscriptions/{id}`, `DELETE /api/me/subscriptions/{id}`：当前用户订阅配置。`PATCH` 在 `enabled=false` 时可携带 `on_disable=keep|save|dismiss`；`save` 在从 Feed 移除前收藏该来源现有内容，`dismiss` 把它们归入忽略集合，`keep` 仅为兼容调用方保留且不作为默认 UI 选项。其他情形携带 `on_disable` 返回 `400 invalid_disable_disposition`。
9. `GET /api/me/source-health`：读取当前登录用户每条订阅的生产抓取健康状态；精确 schema、权限、状态与聚合语义见下文。
10. `GET /api/me/feed-schedule`, `PATCH /api/me/feed-schedule`：读取或修改当前用户自己的 Feed 自动刷新计划；精确字段、权限和错误语义见下文。
10A. `GET /api/me/subscriptions/{id}/schedule`, `PATCH /api/me/subscriptions/{id}/schedule`：读取或修改当前用户指定订阅的自动单源抓取计划；只创建现有 `source_fetch`，不新增同步抓取入口。
10B. `GET /api/me/notification-settings`、`PATCH /api/me/notification-settings`：读取或修改当前用户自己的偏好来源通知渠道；`POST /api/me/notification-settings/test` 只向已保存渠道发送一条明确的模拟消息，不创建抓取任务、Feed snapshot 或内容投递记录，也不移动任何新内容基线。精确字段、write-only 目的地和旧数据规则见下文。
10C. `GET/PATCH/DELETE /api/admin/notification-email-transport`：Owner/Admin 读取、修改或删除工作区唯一的 Service 邮件发送配置；`POST /api/admin/notification-email-transport/test` 使用请求内一次性 `recipient_email` 验证当前 generation。精确 Provider、SecretStore、测试门禁和暂停规则见下文。
11. `POST /api/jobs/source-test`, `POST /api/jobs/source-fetch`, `POST /api/jobs/user-feed-refresh`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `GET /api/jobs/{id}`, `GET /api/jobs`：创建、取消、重试和查询异步任务。`source_fetch` 带 `source_id` 时表示按 catalog source 精准抓取当前用户作用域。
12. `GET /api/feed/latest`, `GET /api/feed/history`：登录后访问目标用户的 Feed snapshot。`latest` 支持 `hide_dismissed=true`、`unread_first=true`、`saved_first=true`；`history` 返回 schema-v2 用户历史留存 payload，精确语义见下文。
12A. `GET /api/feed/saved?limit=200&offset=0` 按 `saved_at DESC` 返回当前用户稳定收藏；`GET /api/feed/ignored?limit=200&offset=0` 按 `dismissed_at DESC` 返回当前用户忽略集合；`GET /api/feed/items/{article_id}` 按需返回 Presentation v2 详情。三者只读 `user_content_items + user_item_state`，不得用另一用户或最近 snapshot 兜底。
12B. `GET /api/media/{asset_id}` 登录后读取 Worker 已缓存的同源图片或头像。内容图片只允许所属用户读取；workspace/public 来源头像允许同 workspace 用户读取；private 来源头像只允许 owner 读取；越权和不存在统一返回 404。Feed、收藏和详情响应不得暴露上游临时媒体 URL，所有可展示图片 URL 必须是 `/api/media/*`。内容图片的稳定身份为 `workspace + user + article + asset_kind + checksum`；同内容的 CDN 域名或查询签名变化只更新远端线索并复用既有 ready asset，不得写重复本地文件。
13. `GET /api/me/item-state`, `PATCH /api/me/items/{article_id}/state`：当前产品使用的已读、收藏、稍后读和忽略状态接口。`POST /api/me/items/{article_id}/feedback` 与 feedback 表只为既有调用方兼容保留，默认 UI 不调用。
14. `GET /api/archive/items`, `GET /api/archive/trends`, `GET /api/archive/facets`, `GET /api/archive/source-quality` 是 compatibility-only archive analytics；默认阅读 UI 和订阅 UI 均不调用，接口存在不等于当前产品能力或路线承诺。`GET /api/archive/graph` 同为兼容路由，但固定返回 disabled 安全空响应。
15. `GET /api/config`, `POST /api/config/action`：配置页兼容 facade。读取时返回旧配置页可消费的 `config/env_status`，并附加 `taxonomy{channels,topics}`；source 列表由 `source_catalog + user_subscriptions` 合成，非 source 全局配置仍写 `data/config.json`。`set_tags` 的精确数组/空数组/兼容字符串语义见上文。
16. `POST /api/source/test`, `POST /api/source/update`：配置页兼容 facade。只创建 `source_test/source_fetch` job，不在 Web 请求内同步抓取。
17. `scripts/service_api_smoke.py`：运行中核心 API smoke，不访问外网源，不执行抓取，只验证登录、读 API、管理员 `/api/users` 读取、可选 private source/job/item-state 和 `member-ui-smoke` 写路径。
18. `GET /api/health/live`：表达 API 进程存活，并返回 `status/version/revision/built_at` 以识别不可变镜像；`GET /api/health/ready`：依次检查数据库、Feed v2 migration、user content v4 migration、数据库内至少一个 enabled user 和可选 Worker readiness，未就绪返回 503 的统一 error envelope。fresh DB 没有可登录用户时返回 `auth_not_configured`，action 要求设置 `HORIZON_AUTH_PASSWORD` 或 `HORIZON_AUTH_PASSWORD_HASH` 后重启；一旦数据库已有 enabled user，后续 readiness 不再依赖 bootstrap 密码环境变量。
19. `GET /api/ops/runtime`：仅 `owner/admin` 可读，返回 Worker heartbeat、队列积压、最老 queued job、stale running、最新 snapshot 年龄，以及用户 Feed 计划字段、`source_schedule_count/overdue_source_schedule_count/next_source_scheduled_at` 和三个 Source Health 聚合字段；`schedule_stats` 包含最近评估、最近入队和 skip reason 计数。响应不返回 claim token、source payload、密钥或 Webhook。
20. `GET /api/admin/secrets`、`POST /api/admin/secrets`、`PUT /api/admin/secrets/{id}/value`、`DELETE /api/admin/secrets/{id}`：仅 `owner/admin` 管理 AI/Apify 密钥引用和值。值只在 create/rotate 请求中出现，任何成功或失败响应都不得回显。`GET /api/admin/secrets/{id}/quota` 同样仅允许 `owner/admin`，且只为同 workspace、已配置的 Apify secret 返回下述安全额度投影；非 Apify 不触发上游请求。
20A. `GET /api/admin/apify-key-pool`：仅 `owner/admin` 读取当前 workspace 的池。`data` 精确包含 `schema_version=1/enabled/generation/status/active_secret_id/draining_secret_id/blocked_reason/retry_at/members`；`status` 为 `empty|ready|draining|blocked|exhausted`。每个 member 只含 `secret_id/position/status/blocked_until/cycle_end_at/last_checked_at/last_error_code/active_run_count`，其中 member status 为 `active|standby|draining|depleted|invalid`。不得返回 env、Token、账号资料、额度原始响应、远端 runId 或 datasetId。
20B. `PUT /api/admin/apify-key-pool/order` 接受完整且无重复的 `secret_ids` 与整数 `expected_generation`；集合缺失/多余为 `invalid_request`，generation 不匹配为 `apify_key_pool_conflict`，成功后 generation 原子加一。启用池时 active/draining/仍有非终态 Run 的 Key 不得通过排序替换。`POST /api/admin/apify-key-pool/{secret_id}/drain` 只操作同 workspace 成员并保持幂等；没有活跃 Run 时可直接完成切换，有 Run 时返回当前 `draining` 状态并由 Worker 持续 reconcile。
21. `GET /api/me/agent-delegations`、`POST /api/me/agent-delegations`、`PATCH /api/me/agent-delegations/{id}`、`DELETE /api/me/agent-delegations/{id}`、`DELETE /api/me/agent-delegations/{id}/record`：当前用户管理自己的 OpenClaw 数据连接。GET 返回 `enabled/mcp_url/subscription_writes_enabled/token_ttl_days/max_active/connections`，并返回 `openclaw_chat{enabled,default_gateway_url,protocol_version=4,target_version="2026.7.1"}`；该对象只是公共运行配置，不包含或接收 Gateway 凭证。每个 connection 返回稳定的 `access=read|subscriptions_write` 与 `scopes`。POST 接受 `name` 和可选 `access`（缺省 `read`）；`read` 仅授予 `inteliscope:read`，`subscriptions_write` 同时授予 `inteliscope:read` 与 `inteliscope:subscriptions:write`。写连接仅 `owner/admin/member` 可在 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=true` 时新建；viewer 返回 `forbidden`，开关关闭返回 `subscription_writes_disabled`。令牌固定 90 天、最多 5 个有效连接，且只在 201 + `Cache-Control: no-store` 响应中返回一次明文令牌；PATCH 仅重命名；基础 DELETE 保持幂等吊销。显式 `/record` DELETE 只允许当前用户永久删除一条 `revoked_at IS NOT NULL` 的记录并返回 `deleted=true`；有效或仅到期的记录返回 `agent_delegation_not_revoked`（409），非本人或不存在返回 `not_found`（404），既有 proposal 依外键级联删除，其他连接与业务数据不变。Remote MCP 总开关关闭时仍可查看、吊销和删除已吊销记录，但创建返回 `remote_mcp_disabled`。
22. FastAPI 默认托管 React Service UI：`/assets/*` 为带内容哈希的 immutable 资源，非 `/api/*` 路径回退到 no-cache `index.html`。`HORIZON_SERVICE_UI_VARIANT=react|legacy` 控制 Service 前端，默认 `react`；React 构建缺失时可安全回退 legacy。`/mcp` 为精确协议路由，不参与 SPA fallback，不通过重定向修正路径。

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
15. 密钥列表、创建、轮换、删除、额度查询、Apify Key 池读取/排序/排空以及 legacy catalog `secret_env` 选择只允许 `owner/admin`；`member/viewer` 均返回 `forbidden`。池模式下任何角色都不再得到 Apify 来源级 `secret_env`；非管理员其他 source 响应只给出 `secret_configured`，不得暴露环境变量名。
16. `owner/admin/member/viewer` 都可创建、查看、重命名和吊销自己的 read Agent delegation，也可显式删除自己已吊销的单条记录；只有 `owner/admin/member` 可创建 subscription-write delegation，且受写开关约束。不存在把既有 read connection 提升为 write 的接口；不提供管理员代查、代管或跨用户删除接口。delegation 令牌始终只映射其创建者，即使创建者是 `owner/admin`，Remote MCP 也不得使用管理员跨用户读权限。禁用用户时必须在同一事务永久吊销其全部连接，重新启用不恢复旧令牌。

错误 envelope 规则：

1. 未登录返回 `unauthorized`，权限不足返回 `forbidden`，不可见或不存在资源返回 `not_found`。
2. Pydantic/body/query 校验失败返回 `invalid_request`，HTTP status 使用 400。
3. 不存在的 `/api/*` 路径返回 `not_found` envelope；不得返回 FastAPI 默认 `{"detail": ...}`。
4. 核心错误码包括：`unauthorized`、`forbidden`、`not_found`、`invalid_request`、`invalid_source_config`、`invalid_feedback_type`、`invalid_feed_schedule`、`invalid_source_schedule`、`invalid_disable_disposition`、`invalid_subscription_notification`、`invalid_notification_settings`、`invalid_notification_destination`、`notification_destination_required`、`notification_channel_unavailable`、`notification_test_failed`、`notification_test_rate_limited`、`invalid_current_password`、`source_schedule_unavailable`、`no_enabled_subscriptions`、`quota_exceeded`、`job_not_cancelable`、`job_not_retryable`。工作区邮件服务另外区分 `invalid_email_transport_provider`、`invalid_email_transport_sender`、`invalid_email_transport_region`、`invalid_email_transport_username`、`email_transport_not_configured`、`email_transport_test_required`、`email_transport_test_rate_limited`、`email_transport_credential_unavailable`、`notification_email_authentication_failed`、`notification_email_recipient_rejected`、`notification_email_rejected` 与 `notification_email_unavailable`。密钥额度查询另外区分 `quota_not_supported`（400、不可重试）、`secret_not_configured`（409、不可重试）、`apify_quota_unauthorized`（422、不可重试）、`apify_quota_forbidden`（422、不可重试且不切 Key）、`apify_quota_rate_limited`（429、可重试）、`apify_quota_unavailable`（503、可重试）和 `apify_quota_invalid_response`（502，响应畸形时可重试、其他上游 4xx 时不可重试）。Apify 池管理/任务还区分 `apify_key_pool_managed`、`apify_key_busy`、`apify_key_pool_conflict`、`apify_key_drain_pending`、`apify_key_pool_exhausted`、`apify_key_pool_blocked`、`apify_key_rejected` 和 `apify_start_outcome_unknown`；公开 message 只描述安全状态和下一步，不得拼接上游正文、Token、runId 或 datasetId。

## 5B. Remote MCP 合同

1. Remote MCP 由现有 `horizon-api` 以 Streamable HTTP 精确暴露在 `/mcp`，固定 `stateless_http=true` 且不保存会话。功能默认关闭；启用时 `HORIZON_REMOTE_MCP_PUBLIC_URL` 必须以 `/mcp` 结束，loopback 可用 HTTP，其他主机必须 HTTPS。Host/Origin 白名单从该 URL 推导；无 Origin 的原生客户端允许，其他浏览器 Origin 拒绝。MCP adapter 直接使用 Service/Store，禁止内部 HTTP 回环。
2. 认证只接受 `Authorization: Bearer <delegation token>`。所有调用均需 `inteliscope:read`；写工具还需 `inteliscope:subscriptions:write`、写开关开启和实时可写角色。无效、过期、吊销、用户禁用或 scope 状态不一致统一 HTTP 401，写 scope 缺失为 `write_scope_required`（403），viewer 写入为 `forbidden`；不提供 OAuth、登录、刷新或动态客户端注册。数据库仅保存完整令牌 SHA-256 和展示前缀，令牌格式为 `ih_mcp_v1_` 加 32-byte URL-safe 随机值。
3. 工具清单精确为 14 个：10 个安全读工具 `get_my_feed`、`get_item`、`list_subscriptions`、`source_health`、`list_jobs`、`get_job`、`get_source_setup_guide`、`list_available_sources`、`diagnose_source`、`diagnose_job`；三个 prepare `prepare_create_subscription`、`prepare_update_subscription`、`prepare_delete_subscription`；唯一 apply `apply_subscription_change`。安全读工具标记 read-only、non-destructive、idempotent、closed-world；prepare 标记非只读、non-destructive、非幂等、closed-world；apply 标记非只读、destructive、非幂等、closed-world。工具结果直接返回 structured content，不包装 REST `{ok,data}`。
   OpenClaw read connection 的客户端 `toolFilter` 精确包含上述 10 个读、引导/发现与诊断工具；subscription-write connection 才额外包含三个 prepare 与一个 apply。该过滤只控制客户端可见性，不改变服务端 scope 与逐调用鉴权。
4. 所有输入拒绝未声明字段与身份字段 `user_id/workspace`，以及任意 URL、SQL、文件路径或密钥。ID 最长 128；确认短语 1..160；Feed/Job 列表 `limit` 默认 20、最大 50；`get_my_feed` 的 `offset` 最大 10,000；`get_item.body_offset` 为 0..20,000，`max_body_chars` 默认 4000、范围 1..8000。详情保持原字段兼容并增加 `body_offset/body_end/body_total_chars/body_has_more/next_body_offset`；`body_truncated=true` 在最后一段仍成立时表示采集阶段已经截断，客户端不得声称已读取完整网页。来源类型、创建/更新字段、计划周期、priority 及 scope 均由严格 Pydantic 模型和 registry/共享 mutation service 校验。`get_my_feed` 只接受 `latest/history/saved/later`；列表不返回完整正文、媒体、原始 metadata 或 legacy reason。跨用户 ID 与不存在 ID 统一 `not_found`。
5. `get_source_setup_guide` 仅返回八类公开来源的 registry 指导和 Web/密钥前置条件；`list_available_sources` 只返回当前用户可见、启用来源的安全摘要、`secret_configured` 布尔值与经过投影的 `public_target`。公网 RSS 可返回完整公开 feed URL；含凭证、私网、loopback 或无法安全分类的目标统一返回 `web_setup_required`。它们不返回原始 source config、`secret_env`、其他用户身份或任何密钥。普通 subscription/job/health 投影继续排除 `personal_tags`、source config、secret ref、workspace/user、worker、claim/lock、payload 和原始 result。
6. 每项订阅变更固定为 `prepare → preview → exact confirmation → apply`：prepare 只写一条密封 proposal 与安全 preview，不修改业务订阅；apply 是唯一业务写入入口。proposal 绑定同一 delegation/user/workspace，10 分钟到期、每 delegation 最多 10 个 pending，确认短语只保存 hash。apply 在 `BEGIN IMMEDIATE` 内重新检查开关、scope、实时角色、所有权、可见性、配额、source key 和目标指纹；成功一次后为 `proposal_consumed`，过期为 `proposal_expired`，目标变化为 `proposal_stale`，确认不匹配为 `confirmation_mismatch`，任一失败不得部分写入或消费 proposal。删除必须显式 `source_disposition=keep|disable_private`；后者只限调用者拥有的 private source。
7. `diagnose_source(subscription_id)` 与 `diagnose_job(job_id)` 只读取当前用户范围内脱敏、持久化的 Health/Schedule/Job 证据，返回固定 `target/status/cause/evidence/suggested_actions/related_job_id` shape。cause 分类仅为 `auth_missing`、`rate_limited`、`network_timeout`、`upstream_rejected`、`invalid_source_config`、`source_disabled`、`subscription_disabled`、`schedule_blocked`、`worker_unavailable`、`no_items`、`unknown`；无充分证据必须返回 `unknown`，诊断不修复、重试或取消任务。
8. 稳定 MCP 错误包括 `unauthorized`、`forbidden`、`not_found`、`invalid_request`、`remote_mcp_disabled`、`subscription_writes_disabled`、`write_scope_required`、`proposal_limit`、`proposal_expired`、`proposal_consumed`、`proposal_stale`、`confirmation_mismatch`、`source_requires_web_setup`、`source_discovery_unavailable`、`rate_limited` 和含 request ID 的 `internal_error`。`prepare_create_subscription` 的 source union 缺少或误用 discriminator 时，`invalid_request` 可附加不含输入值的固定正确 envelope 提示。应用内按 delegation 限制 60 次/分钟、burst 10；请求 body 上限 256 KiB。日志只记 delegation ID、工具名、proposal ID（如有）、结果、耗时和 request ID，不记令牌、参数、确认短语、正文、文章 ID、source config 或错误 message。普通工具调用不写 `usage_events`，只允许每 15 分钟最多一次的 `last_used_at` 写入。

## 5C. Browser OpenClaw Gateway 合同

1. `HORIZON_OPENCLAW_CHAT_ENABLED=false` 默认关闭站内对话；`HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789` 只作为 GET delegation 响应中的公共默认值。开启后浏览器直接连接用户的 OpenClaw Gateway WebSocket v4，Inteliscope API 不接收、保存或代理 Gateway token、device token、对话、模型请求或费用。
2. 未加密 `ws://` 只允许 `127.0.0.1` 或 `localhost`；其他主机必须 `wss://`。Gateway URL 禁止 username/password、query 和 fragment。完整 dashboard 地址只允许在浏览器内解析 fragment token，规范化后的 WebSocket URL不得保留 token。
3. 初始 Gateway token 仅位于对话框内存，连接成功立即清空。浏览器使用不可导出的 Ed25519 私钥和 OpenClaw v3 device signature 配对；IndexedDB 只保存按 `Inteliscope user + normalized Gateway URL` 隔离的 CryptoKey、exact `operator.read + operator.write` device token 与 session key。有效握手返回的 exact device credential 必须先于 `sessions.create` 持久化，session key 只在创建成功后追加；返回 admin、pairing、approvals、缺少预期 scope 或其他额外权限时必须拒绝持久化。
4. 每个标签页最多一个 Gateway WebSocket。连接创建专属 `Inteliscope · <site> · <random suffix>` session，标签不包含 Inteliscope user ID，发生 label conflict 时用新后缀重试一次，并通过按用户/Gateway 隔离保存的 session key 恢复原会话。调用 `tools.effective` 单独判断 MCP/Skill 可用性，并支持 `chat.history`、流式 `chat` event、`chat.abort`、断线重连和新 session。`models.list(view=configured)` 的裸 ID 必须先规范化为 `provider/model`，模型分叉创建后必须由 `sessions.describe` 验证再切换；可选推理档位只取该模型目录条目或精确当前会话的 `sessions.describe.thinkingLevels`，不得用 `agents.list` 的 Agent 级档位补造未知模型能力。上下文用量只可通过已知当前 session key 精确筛选 `sessions.list` 并订阅 `sessions.changed`；不得按 label 发现、推断或收养其他 session，且 `totalTokensFresh=false`、非正数或缺失容量不得在浏览器估算。`chat.send` 必须使用唯一 idempotency key 和 `deliver:false`；消息最多显示 100 条、总文本 100,000 字符。
5. Browser Agent 上下文最多包含八条有序安全记录。Feed 记录只含 `articleId/title/sourceName?/publishedAt?`；运行记录可在浏览器中附带可读标题、来源与状态，但内部 `job_id`、UI 派生的 detail/error 文本不得成为可见历史。V4 handoff 只把用户问题和内部记录 ID 发送给 Gateway：Feed 记录调用 `get_item`，运行记录直接调用只读 `diagnose_job`，要求仅依据持久化安全证据回答、明确未知，并禁止重试、取消、修复或其他写操作；浏览器投影继续兼容 V3 和旧无版本 handoff，且不得显示内部指令或 ID。文章正文由 OpenClaw 经 Remote MCP 分段读取，最多跟随 `next_body_offset` 三次并累计不超过 20,000 字符。正文是不可信数据，正文中的规则变更、凭证请求或工具调用指令不得执行。

用户 Feed schedule 规则：

1. 没有 `user_feed_schedules` row 等同于 `enabled=false`、`interval_minutes=360`；GET 不因缺 row 自动写库。
2. `GET /api/me/feed-schedule` 成功响应的 `data` 固定包含 `schema_version=1`、`enabled`、`interval_minutes`、`allowed_intervals=[60,180,360,720,1440]`、`next_run_at`、`last_evaluated_at`、`last_enqueued_at`、`last_skip_reason`、`last_job`、`active_job` 和 `worker_status=ready|missing|stale`。没有对应时间或 job 时为 `null`；job 对象沿用公开 job shape 且不得包含 `claim_token`。
3. `PATCH /api/me/feed-schedule` 接受 `enabled` 和/或 `interval_minutes`；至少提供一个字段。周期只允许 `60/180/360/720/1440` 分钟，否则返回 `400 invalid_feed_schedule`。开启时没有有效订阅返回 `409 no_enabled_subscriptions`；viewer 返回 `403 forbidden`；未登录返回 `401 unauthorized`。
4. 首次从关闭改为开启时 `next_run_at=now`，由下一个 Worker schedule tick 入队首次任务；已开启时修改周期改为 `now + 新周期`。关闭时 `next_run_at=null`，只取消尚在 queued 的 `reason=scheduled_service_refresh` 自动任务，running 任务继续完成。
5. `last_job` 指向该计划最近创建或复用的刷新任务，可通过 `status/result_json` 展示产出条数及 `partial` 的 issue；`active_job` 是当前用户唯一 queued/running 全量刷新。`last_skip_reason` 至少可以为 `active_user_feed_refresh`、`active_source_fetch`、`user_disabled`、`user_read_only`、`no_enabled_subscriptions`、`quota_exceeded` 或 `migration_required`。用户被降级为 viewer 时计划必须关闭并取消仍 queued 的自动刷新；已 running 的任务继续按原 claim 完成，调度 tick 还必须防御性拒绝 viewer 入队。

用户订阅级 source schedule 规则：

1. 没有 `user_source_schedules` row 等同于 `enabled=false`、`interval_minutes=60`；GET 不隐式写库。允许周期固定为 `[30,60,180,360,720,1440]` 分钟。
2. GET/PATCH 响应包含 `schema_version=1`、`subscription_id`、`source_id`、计划时间、`last_job`、`active_job` 和 `worker_status`；公开 job 不得包含 `claim_token`。
3. 首次开启默认在下一个 Worker tick 运行；已开启时修改周期从当前时间重新计算。关闭计划会取消仍 queued 且 `reason=scheduled_source_fetch` 的任务，running 任务继续完成。停用订阅或把用户降级为 viewer 时必须同步关闭计划。
4. Worker 每次 schedule tick 在 claim 普通任务前原子评估到期订阅。自动 job 固定为 `job_type=source_fetch`、`reason=scheduled_source_fetch`、`priority=-10`，沿用现有配额、claim token、Source Health 和 Feed v2 单源合并语义。
5. 同一订阅最多一个 queued/running `source_fetch`；手动、自动和重复页面提交复用已有 active job。当前用户存在 active 全量刷新时延后 5 分钟；全量刷新成功参与该订阅后也推进其下一次单源计划，避免紧邻重复抓取。停用 catalog source 时，相关计划关闭并记录 `source_disabled`，仍 queued 的自动任务被取消。
6. 调度链路不得调用 legacy scheduler、`HorizonOrchestrator.run()` 或 `LegacyPublisher`，不得读取或写入全局静态 Feed、摘要、legacy 通知、Graph 或 Archive analytics。偏好来源通知只可由下述 Service outbox 在 Feed/Health/Job 提交后消费。

用户偏好来源通知规则：

1. 缺少 `user_notification_settings` row 等同 `enabled=false`；GET 不因缺 row 隐式写库。成功响应只返回 `schema_version=1`、`enabled`、`channel=email|webhook`、`email_configured`、`email_transport_ready`、`webhook_configured`、`last_test_status`、`last_tested_at`、`last_test_error_code` 和 `updated_at`，不得返回邮箱明文、Webhook URL、生成的环境变量名、SMTP 凭据或上游响应。
2. PATCH 只接受 `enabled`、`channel`、write-only `email_address` 和 write-only `webhook_url`；至少提供一个字段。邮箱与 Webhook 可以分别预配置，但任一时刻只有 `channel` 指定的单一渠道生效；开启时该渠道必须已有目的地，否则返回 `notification_destination_required`。当目标渠道为 email 时还必须满足当前工作区 `email_transport_ready=true`，否则返回 `notification_channel_unavailable`；已经开启的 email opt-in 在 transport 暂停后仍保留，但暂停期间不产生 outbox，也不补发。partial PATCH 必须在同一 `BEGIN IMMEDIATE` 内重读实时用户并按 omission 合并，管理员刚完成的停用或降权不得被旧请求覆盖。从关闭变为开启时记录新的用户级 `enabled_at` 并把内部 `notification_generation` 原子加一；停用期间发布的内容不得补发。管理员停用用户时必须在同一事务关闭其通知设置并清除该水位；重新启用账户不得恢复通知开关。
3. Webhook URL 只可在请求内短暂出现，随后写入 `SecretStore` 生成的用户专属环境变量；Service DB 只保存环境变量名和当前值的内部 SHA-256 一致性摘要，config JSON、outbox、API、DOM、Job、日志和错误 envelope 均不得保存或回显 URL。配置状态、staging 和发送都必须同时验证用户专属变量绑定与摘要匹配；SecretStore/SQLite 更新中断时只能 fail closed，显式清空还必须删除该用户确定性变量下没有 DB 引用的 orphan 值。投递时重新校验无 userinfo 的 HTTPS；固定到公网地址后使用 bounded DNS、单地址单次 POST、5 秒 transport timeout 与 6 秒总 deadline，禁用环境代理并拒绝重定向。请求声明 `Accept-Encoding: identity`，响应只检查状态与 encoding header，不读取或解压正文；非 identity 响应属于已开始发送后的未知结果。
4. `user_subscriptions.notify_on_new_items` 默认 false。PATCH 从 false 切为 true 时记录 `notification_enabled_at=now` 并把内部 `notification_generation` 原子加一；已是 true 的幂等保存不得重置水位或代数。旧客户端或重复 create 请求省略该 additive 字段时，已有订阅必须保留原开关、水位与代数，新订阅仍默认关闭。订阅或 catalog source 停用、订阅切到 `analysis_mode=personal_only` 时原子清除通知开关和时间；重新启用不得自动恢复 opt-in。在同一请求中显式提交 `personal_only + notify_on_new_items=true` 或给已停用订阅开启时返回 `invalid_subscription_notification`。
5. 内容投递只比较本次成功/partial Feed snapshot 与其紧邻上一份 snapshot 的稳定 `article_id` 差集。用户首份 snapshot 仅建立基线；标题变化、删除、排序、no-op、共享内容复用、生命周期 reconcile、`source_test`、`content_repair` 和无 snapshot 的失败均不得生成内容通知。
6. 差集 item 还必须包含已开启订阅的 provenance，且其规范 `published_at` 必须严格晚于用户通知 `enabled_at` 与该订阅 `notification_enabled_at` 两者；缺失、无时区或不可解析时间一律 fail closed 跳过。`personal_only` item 永远不进入 outbox。
7. `preferred_source_notification_deliveries` 以订阅和稳定文章 ID 唯一去重，并在 stage 时固化账户与订阅两层 generation。候选 outbox 必须与 snapshot、Source Health 和 claim-guarded Job 终态处于同一事务；claim 失效时整体回滚且不得外呼。Worker 只在 `complete_job` 成功提交后发送，并在外呼前复查用户、来源、订阅、通知开关和渠道仍然有效，还必须同时要求 delivery 双 generation 与当前值完全相等、可信的 delivery `created_at` 与来源 `published_at` 严格晚于“当前”账户和订阅双水位；关闭后重新开启的旧 epoch pending 即使墙钟回拨或伪造未来发布时间也要安全终结且不外呼。通知发送或 staging 的局部失败只更新/跳过通知状态，绝不把已成功的抓取 Job 或 snapshot 改成失败或触发重新抓取。
8. 外部通知不假设幂等。未开始的 `pending` delivery 可由后续 Worker tick 领取；领取后先写 `sending`，再外呼。Webhook timeout/连接中断、SMTP 连接中断、非 identity 响应或其他已开始发送但结果未知的 delivery 必须保持 `sending` 且永不自动重放；只有发送前校验失败或明确上游拒绝才进入 `failed` 并记录有界安全 code。任何状态都不保存上游正文或目的地。
9. Service 邮箱投递只读取 schema v10 工作区 transport 与其 SecretStore 凭据，绝不回退到 `data/config.json.email`；收件地址仍仅属于当前用户。Webhook 使用固定的安全 JSON 事件，真实批次为 `inteliscope.preferred_source.new_items` + `data.items[]`，模拟测试为 `inteliscope.preferred_source.test` + `data.test=true`。Worker 对同一用户、渠道和 Job 原子领取最多 20 个 distinct article ID 及这些文章的全部 eligible provenance ledger，按 article ID 去重后合并为一次外呼；Email 展开条目列表，而 outbox 仍对批内每个 `(subscription_id, article_id)` 保留唯一记录与一致终态。
10. POST test 使用模拟标题和正文，只验证已保存的当前渠道。成功只返回安全的 `sent/channel`；失败使用 `notification_test_failed` 等稳定错误，不回显目的地或上游正文。外呼前必须在 SQLite 写事务中原子领取当前用户 60 秒测试冷却，并发或冷却内重复请求返回 429 `notification_test_rate_limited`。测试只更新内部 attempt 时间与 `last_tested_at/last_test_status/last_test_error_code`，不写内容 outbox、不读写 Feed 基线、不创建 Job，也不触发来源、AI、scheduler 或付费调用。

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
         "last_issue": null,
         "last_job_id": null
       }
     ]
   }
   ```

2. `items` 只包含上述字段，并按现有订阅 priority/创建顺序稳定返回当前用户的全部订阅；禁用的 subscription 或 catalog source 仍保留并投影其健康。`last_issue` 无记录时为 `null`，有记录时精确为 `{"stage", "code", "message", "retryable"}`，其中 `retryable` 是 boolean。不得返回 source key/config、secret env、job payload、claim token、原始 issue 列或其他用户记录。
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
9. 每次 Actor Run 启动前必须在 SQLite 写事务内预留固定的 `secret_id + secret_version + pool_generation`；同一 Run 的 POST、轮询、中止和 dataset 读取始终使用该 lease 的同一 Token。新 Run 只接受最近不超过 60 秒且 `remaining_included_credits_usd > 0` 的额度快照；单次逻辑抓取对每个可用 Key 最多尝试一次。
10. 只有 HTTP 402、明确 Apify 额度错误或额度快照 `remaining_included_credits_usd <= 0` 标记 `depleted`；HTTP 401 或明确无效 Token 标记 `invalid`。普通 403 只失败当前请求，429 在原 Key 退避，5xx/网络错误按原 Key 的可重试规则处理，均不得污染整个 Key。
11. Key 失效时池先进入 `draining`，禁止任何 Worker 预留新 Run；旧 generation 下所有已登记非终态 Run 必须经 `POST /actor-runs/{runId}/abort` 并轮询确认 `SUCCEEDED/FAILED/ABORTED/TIMED-OUT`。30 秒仍未全部确认则保持 fail closed 并返回 `apify_key_drain_pending`；只有排空完成才把 generation 加一、启用下一 standby，并让原逻辑抓取创建全新 Run，禁止复用旧 runId 或 dataset。
12. Actor POST 的结果未知，或进程重启后发现无法证明是否已创建远端 Run 的 reservation，必须把池置为 `blocked` 并返回安全的 `apify_start_outcome_unknown`/`apify_key_pool_blocked`，由人工核对 Apify 控制台；不得猜测远端标识或盲目切换。Worker 启动时必须先 reconcile 已登记非终态 Run，再领取新 Job。
13. 全部 Key 耗尽时返回 `apify_key_pool_exhausted`，Apify 单源任务失败，完整 Feed 可为 partial 且其他免费来源继续运行；来源 schedule 延后到已知最早 `blocked_until/cycle_end_at`。周期到期后重新查询额度，恢复的旧 Key只追加到备用队尾，不抢占 active，也不恢复历史 Run。
14. Catalog RSS URL 禁止 `${ENV_VAR}` 占位和 URL userinfo，避免把环境值或凭据写入 catalog/API；member 拥有的 RSS 在抓取前及每次 redirect 都必须只解析到公网地址，并只连接该次已验证的字面 IP，同时保留原 Host 与 HTTPS SNI。安全请求不得使用环境代理或跨 hostname 复用连接，响应拒绝压缩且流式硬限制为 2,000,000 bytes。只有 `owner/admin` 拥有的 source 可默认访问本地/私网 RSS；确定性的本地测试例外必须由管理员通过 `HORIZON_MEMBER_RSS_HOST_ALLOWLIST` 精确列出 host，默认空。
15. `member` 创建的 source job 必须引用可见 `source_id`；Worker 以 catalog config 为权威并忽略 job payload 对 URL/source 字段的覆盖。

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
10. `user_feed_refresh` 成功后必须保存 `user_feed_snapshots/user_feed_items`，job result 至少包含 `snapshot_id` 和 `item_count`。
11. `source_fetch` 带 `source_id` 时，Worker 必须从 `source_catalog + 当前用户 subscription override` 合成单源 `Config`，跳过 legacy notifications、summaries、enrichment、full-text 和 scheduler 副作用；成功后保存当前用户 feed snapshot，job result 至少包含 `snapshot_id`、`item_count`、`source_id`、`source_type` 和 `source_key`。只有 snapshot/health/job 同事务内的偏好来源 outbox 与提交后发送属于允许的 additive Service 副作用。
12. 真实源 smoke gate 使用 `scripts/service_real_source_smoke.py` 创建/更新 catalog sources、订阅当前用户、创建 `source_test/source_fetch` job，并验证 RSS、Hacker News、GitHub Releases、Telegram public channel 的闭环；Reddit/Apify 只能作为 optional degraded 记录。
13. Worker 每 10 秒写 heartbeat 并在任务执行中续租；heartbeat age 达到 35 秒即视为 stale。完成、失败、续租和 snapshot finalize 都必须匹配 `job_id + worker_id + claim_token + running`。
14. schema-v2 snapshot、`user_feed_items` 和 job 终态必须在同一短事务提交；同一非空 `job_id` 最多生成一个 snapshot，同一 snapshot 内 `article_id` 唯一。
15. `POST /api/jobs/user-feed-refresh` 的 data 增加 `deduplicated`。同一用户已有 queued/running 全量刷新时返回原 job 且 `deduplicated=true`；真正新建时为 false。手动、多标签页和自动刷新共同受同一原子去重约束。
16. 手动全量刷新必须在同一个 `BEGIN IMMEDIATE` 事务中完成“查找/创建 active job、配额 admission、usage 记录”；只有真正新建 job 才计一次配额，配额失败同时回滚 job 和 usage。复用已有 active job 不重复计费，也不因当日配额后来耗尽而拒绝读取该 job。
17. Worker 在 claim 普通 job 前按 `HORIZON_SCHEDULE_POLL_SECONDS` 检查到期计划，默认 30 秒。自动任务复用 `user_feed_refresh`，固定 `payload.reason=scheduled_service_refresh`、`priority=-10`，仍使用用户完整 `filtering.time_window_hours`，刷新周期不替代抓取窗口。
18. 到期检查、active job 去重、usage 记录和 schedule 推进必须处于同一 SQLite 写事务；两个连接竞争同一计划最多创建一个 job。重启或长时间离线只补一个任务并把下一次推进到 `now + interval`，不追赶全部漏跑周期。
19. active `source_fetch` 或 migration 未完成时计划延后 5 分钟，避免 snapshot 竞争或热循环；disabled user、无有效订阅或配额耗尽时不入队并推进到下一周期。`partial/failed` 不关闭计划，后续仍按已计算的下一周期继续。
20. `user_feed_refresh` 的 `succeeded/partial` job `result_json` 必须包含 `run_id/run_status/item_count/source_outcomes/issues/analysis_usage`，并保留既有 `snapshot_id/snapshot_created`。`analysis_usage` 精确包含非负整数 `item_count/cache_hits/ai_calls/provider_attempts/fallbacks/skipped`，只用于成本与降级诊断，不包含 token 文本或原始内容。每个公开 source outcome 精确包含 `source_id/subscription_id/source_key/analysis_mode/status/fetched_count/issue`；issue 为 `null` 或精确的 `stage/code/message/retryable`，不得包含 source config。
21. 结构化 refresh 最终 `failed` 且不生成 snapshot 时，`result_json` 仍保存同一诊断 shape，`run_status=failed`、`item_count=0`，同时保留 job 的 `failed/error_code/error_message`。可重试的中间 attempt 可以保存本次诊断，但不得提前更新 Source Health；只有 claim-guarded `fail_or_retry_job` 选定最终失败后才能原子提交健康与 job 终态。
22. job result、Service snapshot 和 job error 中的 issue/source key 必须先使用与 Source Health 相同的单行、240 字符上限脱敏器，删除 URL userinfo/query、认证信息、secret、payload/config/stack/traceback；公共结果不得记录 source payload、真实密钥、带认证 URL 或堆栈。`fail_or_retry_job` 的可选结构化 result 不改变既有 worker/claim/lease guard 和退避决策。
23. 停用/删除订阅、停用来源、停用用户或把用户降级为 viewer 时，相关 schedule shutdown、queued job 取消和 Feed reconciliation 必须在同一事务。失效任务终态为 `cancelled/error_code=job_invalidated`，并只附带有界 `invalidation_reason`。
24. Worker 在 claim 后、每次网络调用前和 claim-guarded finalize 前复查统一 eligibility。调用前失效不得访问网络；调用中失效的结果不得更新 Feed 或 Source Health。
25. 默认未知异常不可重试。只重试显式 retryable source issue、连接/超时、HTTP 429 与 5xx；每个真实 scraper/provider/AI 网络调用（包括自动重试和人工 retry）均原子计量。
26. `HORIZON_SHARED_ACQUISITION_ENABLED=true` 时，public/workspace source 在同 workspace、相同 acquisition key 与 freshness window 内最多一次上游获取；private source 按 user 隔离。key 覆盖 source/type、规范化网络配置、adapter contract、secret-ref identity/version 和抓取窗口，不包含频道、主题、标签、优先级等用户投影字段。
27. shared acquisition 成功必须缓存零条结果；TTL 取相关启用计划最短周期并默认夹在 5..60 分钟、无计划回退 30 分钟。并发 loser 最多等待 5 秒且不计 attempt；stale lease 可恢复，失败退避最多 5 分钟。`source_test` 绕过成功缓存且不写 content pool，但仍受同源并发和成本 admission 约束。
28. Feed/source job result 增加精确 `acquisition_usage{cache_hits,cache_misses,upstream_attempts,waits}`；只包含非负计数。`/api/ops/runtime.operational_counts` 只聚合这些计数、`invalidated_jobs` 与 `quota_rejects`，不得输出 source/user id、配置、prompt 或 secret。
29. terminal `source_test/source_fetch/user_feed_refresh` 的 `result_json` 可增加 `response_schemas[]`，每项精确包含 `source_id/catalog_type/capture_status/upstream/normalized`，可选 `job_truncated=true`。`capture_status` 只允许 `captured/empty/cached/unavailable`；两层结构只含 `root_type`、`fields[{path,type}]`、`truncated`，type 只允许 `object/array/string/integer/number/boolean/null/mixed`。每层最多深度 6、256 个路径、8 KiB，每个 Job 合计最多 64 KiB。结构摘要不得包含字段值、正文、source config、请求 URL、Actor input、header、token、secret 或密码；旧 Job 缺少该字段继续有效。共享缓存命中必须标记 `cached` 且不得复用旧 Job 的上游结构。
30. 池模式下 Apify shared acquisition fingerprint 必须包含 reservation 时的 pool generation；缓存 owner 在发布前重新读取 generation，发生变化就放弃旧结果并禁止写入共享缓存。其他 source type 的 fingerprint 与缓存语义不变。
31. Apify source schedule 在池 `draining/blocked/exhausted` 时只延后该来源，分别使用 30 秒 reconcile 窗口、人工解阻或最早额度恢复时间；完整 Feed 的非 Apify 来源照常获取。公开 schedule/job error 只保存有界 `apify_key_*` code 和通用安全 message，不得保存内部 pool row、远端 run/dataset 标识或上游正文。
32. Worker 启动时在 claim 任意业务 Job 前按 workspace reconcile Apify ledger；已知远端 Run 使用其登记的旧 lease 执行 abort/poll，未知启动结果保持 blocked。重启 reconcile 和正常 failover 均不得启动 Actor，只有排空完成后的原逻辑抓取重试可以创建新 Run。

Feed retention / legacy archive compatibility 规则：

1. `GET /api/feed/latest` 默认返回当前用户最新 schema-v2 snapshot；不得在多人 Service API 中读取全局 `data/site/radar-data.json`、`history-data.json` 或 `article-graph.json`。v2 以 `items` 为唯一规范集合，`today_items` 必须与最终过滤/排序后的 `items` 同值。
2. `GET /api/feed/latest` 的 item 应包含当前用户的 `user_state`，最少表达 `is_read/is_saved/is_later/dismissed` 和对应时间字段；无状态时返回 false/空时间。
3. `GET /api/feed/latest?hide_dismissed=true` 不返回当前用户已忽略 item；`unread_first=true` 将未读 item 稳定排到已读前；`saved_first=true` 将收藏 item 稳定排到未收藏前。默认参数全部为 false，保持 snapshot 原始顺序。
4. `GET /api/feed/history` 至少返回 `schema_version=2`、`scope=user`、`snapshots`、`items`、`featured_items`、`item_count`。无 snapshot 时这些集合为空且 `item_count=0`。
5. `snapshots` 保留目标用户最近 20 个 snapshot 的摘要，按新到旧排列；每项包含 `snapshot_id/generated_at/item_count/job_id`。最新 snapshot 只保留在摘要和兼容元数据中，其 items 不进入历史列表。
6. history 只读取目标用户的 snapshot payload，不读取 `data/site/history-data.json`、`data/horizon.db` 或 `ArticleStore`。它先排除仍存在于最新 snapshot 的全部 ID，再从第二新 snapshot 起按新到旧、snapshot 内原顺序稳定去重；同一 ID 保留最靠新的历史版本，`items` 最多 200 条。
7. `featured_items` 沿用对应历史 snapshot 已保存的 `featured_items` / `featured_item_ids` 成员关系，不按当前分数重新计算；顺序跟随最终 `items`。每个历史 item 补充请求目标用户当前的 `user_state`，`item_count == len(items)`；sources/channels/categories/tags/topics/personal_tags 等筛选集合从最终历史 items 稳定重建。
8. 跨 source URL 去重后的 item 必须保存完整 `source_ids/subscription_ids/source_keys` provenance；partial refresh 只要该 provenance 与失败的 active source 有交集，就保留窗口内旧 item。URL query 是内容身份的一部分，不得把不同 query identifier 的文章误合并。
9. 全量刷新把本次结果与当前用户稳定内容索引及最新 snapshot 中“仍属 active source 且仍在全局时间窗口内”的内容合并；同一 canonical identity 由本次结果覆盖展示字段，但窗口内的不同文章不得因该来源本次抓到新内容或成功返回空集合而消失。已取消订阅来源立即排除；失败来源同样保留窗口内旧内容。全部来源失败不生成 snapshot；只有 active source 没有任何本次或索引中的窗口内内容时，全部成功且为空才生成空 snapshot。
9A. `latest_per_source` 只对显式声明该 retention 的来源生效：序列化 item 以 additive `retention_policy_explicit=true` 标记该事实，同一 provenance 的新 latest 替换旧 latest。X/Instagram profile 未显式声明时统一采用 `time_window`；读取缺少该标记的遗留 `latest_per_source` 社交快照时按 `time_window` 规范化，并可从用户稳定内容索引恢复仍在窗口内但已被旧 snapshot 替换的帖子。该兼容不迁移或重写历史 snapshot。
10. `source_fetch` 按 canonical identity 合并目标来源结果到最新 Feed，不替换其他来源；目标来源的普通窗口内容继续累计，只有显式 `latest_per_source` 会替换其旧 latest。`personal_only` 内容进入 Feed，但跳过 AI、精选和推送。
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
21. `presentation` 由 `src/services/content_presentation.py` 统一生成，不允许各 adapter 或前端自行拼不同结构。`content.excerpt` 必须清洗 HTML/脚本、排除评论附录并硬限制 600 字；`analysis.summary_zh` 遵守全局 100..500 字配置且默认不超过 200 字。新分析不得生成 `action_suggestion`，React 不得读取它；`presentation.analysis` 禁止出现 `reason`。内容格式按“上游明确类型 → 强确定性 URL/来源规则 → 同一次可选 AI 分析 → 安全来源兜底”解析，不得为了格式分类新增独立 AI 请求。
21A. `GET /api/feed/items/{article_id}` 把规范详情升级为 `presentation.version=2`，在 v1 基础上增加 `source.avatar_url`、`content.body_text/body_truncated/body_completeness` 与 `media.images/count/total_image_count/truncated`。`body_text` 只来自抓取器已经捕获的正文，清洗为纯文本并硬限制 20,000 字；旧 snapshot 只能回填已有摘要并标记 `excerpt_only`，不得请求网页代理或由 AI 编造正文。详情先按 checksum（缺失时回退 asset ID）去重 ready 内容图片，再按最新记录取最多 6 张；`count` 是实际可展示的唯一图片数，`total_image_count` 优先使用上游可信原始总数并至少为 `count`，`truncated=true` 仅表示确有图片未缓存。历史重复行不做破坏性删除，也不得重复投影。
21B. 收藏和稍后读状态使对应 `user_content_items` 跨普通 snapshot retention 保留；取消两者后恢复普通内容保留策略。文章被选中或打开详情不得自动修改已读；只能由显式 PATCH 切换已读/未读。
22. `content_kind` 只允许 `feed_summary|release_notes|event_description|post_body|message|caption|discussion|metadata_only`；它描述来源片段语义，不等同于展示格式。`content.format` 只允许 `article|video|image|gallery|audio|social_post|discussion|release|other`，`content.format_origin` 只允许 `upstream|deterministic|ai|fallback`；`title_origin` 只允许 `native|generated`；`analysis.status` 只允许 `ai|fallback|personal_only|disabled`。缺失的原生互动量以 `null` 表达，不得伪造为零；Service API item 不返回原始 `content`。
23. 全量与增量合并必须共用 canonical URL merger；host 规范化不删除 query。合并保留全部 `source_ids/subscription_ids/source_keys`，优先复用最新 Feed 的 article id，再按 priority/source/native id 稳定选择内容。
24. 每次 finalization 对有序公开 Feed 内容和 featured/daily/personal 成员集合计算 `content_hash`，排除生成时间、job/run 诊断和实时 user state。hash 未变化时复用最新 snapshot id 并返回 `snapshot_created=false`；内容变化才创建新版本。最后一个订阅失效只创建一个空版本，后续重复 reconciliation 为 no-op。
25. 只有 `HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED=true` 且目标数据库已记录 Feed storage v3 migration 时，新 snapshot 才使用 `storage_version=2`：完整 item 只写 `user_feed_items.item_json`，snapshot payload 只留 metadata、item id 顺序及 featured/daily/personal id 集合。现存数据但未迁移的数据库继续写 legacy storage v1；Reader 必须双读 legacy 完整 payload 与 compact payload，旧 snapshot 不原地重写。真正无 v3 遗留数据的新空库可在 additive 初始化时自动记录 marker。
26. v3 migration 完成后，Worker 每小时至多一次清理：Feed 90 天且每用户最多 100、source content 7 天、AI cache 30 天、usage 90 天、terminal jobs 14 天及过期 session；始终保留每用户最新 Feed snapshot 和每 acquisition key 最新 source snapshot。存在旧数据但尚未记录 v3 时 Worker 不执行 retention，避免仅因部署新代码而自动删除历史。

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
4. 后台任务日志写入 `logs/**`，默认不进入 agent 上下文。
5. 响应结构诊断只在 adapter 收到上游值时即时提取字段路径/类型，原始值随调用栈释放；Job 只保留有界双层摘要，Feed snapshot、稳定内容索引和媒体记录不得保存该诊断。

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
