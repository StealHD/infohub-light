# Inteliscope InfoHub Light API / 接口合同

## 1. 文档目的
本文件定义当前系统的公共接口合同。这里的“API”包括 CLI 命令、本地 Web 配置 API、静态 JSON payload、SQLite 归档读取路径，以及 MCP 集成边界。

## 2. 设计原则
当前接口必须遵守：

1. 入口层只做请求接收、参数校验和应用编排。
2. 业务层不直接依赖外部系统原始字段。
3. 返回结果必须显式表达 capability / degrade 状态。
4. 输出结构必须对静态 UI、历史数据和后续归档分析稳定。
5. 新字段优先使用 `channel/topics`，旧字段 `category/tags` 保持兼容 alias。
6. Service API 必须返回统一 envelope：成功为 `{"ok": true, "data": ...}`，失败为 `{"ok": false, "error": {"code", "message", "retryable", "action"}}`。
7. `/api/*` 的请求校验错误和未知路径也必须使用统一 envelope；静态资源 404 不属于 Service API 合同。

## 3. 标识合同
稳定标识：

1. `ContentItem.id`: `{source}:{subtype}:{native_id}`，由 scraper 适配层生成。
2. `normalized_url`: SQLite 归档去重和关系分析使用的 URL 归一化键。
3. `source_ref`: 单源刷新使用的引用，如 `rss:0`、`github:1`、`apify_social:0`、`hackernews`。
4. `article_id`: 归档表和 article graph 的稳定文章键，等同 `ContentItem.id`。
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

稳定接口：

1. `GET /api/config`: 返回当前配置，必须隐藏密钥值。
2. `POST /api/config/action`: 结构化修改配置。
3. `POST /api/source/test`: 测试单个来源可抓取性。
4. `POST /api/source/update`: 触发单源刷新。

请求规则：

1. 配置 API 只保存环境变量名，不保存密钥值。
2. 来源 topics 应写入 `topics`，同时保留 legacy `tags`。
3. Hub channel 应写入 `channel`；Telegram 的平台频道名继续使用 `channel`，Hub 频道使用 `hub_channel` 或兼容 `category`。
4. `apify_social.subscriptions[].token_env` 可为单条 Apify 订阅指定 key 环境变量名；为空时使用全局 `sources.apify_social.token_envs` 轮换。

响应规则：

1. 成功响应必须包含 `ok: true` 或明确的结果字段。
2. 失败响应必须包含人类可读 `error`。
3. 外部来源测试失败必须给出可执行下一步，不暴露敏感 token。

## 5A. Service API 合同
入口：`src/api/server.py`，默认脚本：`uv run horizon-api`。

稳定接口：

1. `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/status`：基于 cookie session 的用户登录状态。
2. `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`：管理员管理小团体成员。响应不得包含 `password_hash`。
3. `GET /api/dashboard/summary`：登录后订阅控制台汇总，返回当前用户、可见 source 数、订阅数、queued/running/failed job 数、最新 feed 时间和当前用户 `item_state_counts`。
4. `GET /api/catalog/source-types`：返回 source type registry 元数据、必填字段和 config template。
5. `GET /api/catalog/sources`, `POST /api/catalog/sources`, `PATCH /api/catalog/sources/{id}`, `DELETE /api/catalog/sources/{id}`：公共、workspace、private source catalog；创建/更新必须通过 registry 校验 config 并写入 `source_key`；删除为软删除。
6. `POST /api/catalog/import-config-sources`：管理员把 `data/config.json` 中旧 source 列表幂等导入 `source_catalog`，可 `dry_run`，默认为当前管理员创建 subscriptions。
7. `POST /api/catalog/sources/{id}/subscribe`, `DELETE /api/catalog/sources/{id}/subscription`：当前用户订阅或取消订阅一个可见 catalog source。
8. `GET /api/me/subscriptions`, `POST /api/me/subscriptions`, `PATCH /api/me/subscriptions/{id}`, `DELETE /api/me/subscriptions/{id}`：当前用户订阅配置。
9. `POST /api/jobs/source-test`, `POST /api/jobs/source-fetch`, `POST /api/jobs/user-feed-refresh`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `GET /api/jobs/{id}`, `GET /api/jobs`：创建、取消、重试和查询异步任务。`source_fetch` 带 `source_id` 时表示按 catalog source 精准抓取当前用户作用域。
10. `GET /api/feed/latest`, `GET /api/feed/history`：登录后访问当前用户作用域 feed snapshot；无 snapshot 时返回空 payload，并标记 `scope=user/degraded/no_user_snapshot`。`latest` 支持 `hide_dismissed=true`、`unread_first=true`、`saved_first=true`，只使用目标用户自己的 item state。
11. `GET /api/me/item-state`, `PATCH /api/me/items/{article_id}/state`, `POST /api/me/items/{article_id}/feedback`：当前用户 feed item 的已读、收藏、稍后读、忽略和简单反馈 API。
12. `GET /api/archive/graph`, `GET /api/archive/items`, `GET /api/archive/trends`, `GET /api/archive/facets`, `GET /api/archive/source-quality`：登录后访问的用户作用域归档和关系分析读取 API。
13. `GET /api/config`, `POST /api/config/action`：配置页兼容 facade。读取时返回旧配置页可消费的 `config/env_status`，但 source 列表由 `source_catalog + user_subscriptions` 合成；非 source 全局配置仍写 `data/config.json`。
14. `POST /api/source/test`, `POST /api/source/update`：配置页兼容 facade。只创建 `source_test/source_fetch` job，不在 Web 请求内同步抓取。
15. `scripts/service_api_smoke.py`：运行中核心 API smoke，不访问外网源，不执行抓取，只验证登录、读 API、可选 private source/job/item-state 写路径。

权限规则：

1. 第一版固定单 workspace。
2. 角色为 `owner/admin/member/viewer`。
3. `owner/admin` 可管理用户和 public/workspace source。
4. 普通用户只能创建和修改自己的 private source，只能管理自己的 subscriptions。
5. job 查询仅允许 job owner 或管理员访问。
6. 配置页 source action 中，`owner/admin` 新建 source 默认 `public`，`member` 新建 source 默认 `private`，`viewer` 不能创建或修改 source。
7. 配置页删除 source 对管理员和 private owner 表示软删除 catalog source；普通成员删除 shared source 表示取消自己的订阅。
8. 私人信息流、历史数据和归档图谱默认不公开，未登录访问 `/api/feed/*` 和 `/api/archive/*` 返回统一 `unauthorized` error envelope。
9. `viewer` 为只读角色：可登录查看 feed、catalog、subscriptions、jobs 和 item state，但不得创建/修改 source、订阅配置、抓取任务、item state 或 feedback。
10. `owner/admin` 可使用 `user_id` 查询同 workspace 成员的 feed/archive；`member/viewer` 查询他人时返回 `forbidden`。
11. `member` 不能修改或删除 public/workspace source；只能管理自己的 private source、自己的 subscriptions、自己的 jobs 和自己可见 feed item 的行为状态。

错误 envelope 规则：

1. 未登录返回 `unauthorized`，权限不足返回 `forbidden`，不可见或不存在资源返回 `not_found`。
2. Pydantic/body/query 校验失败返回 `invalid_request`，HTTP status 使用 400。
3. 不存在的 `/api/*` 路径返回 `not_found` envelope；不得返回 FastAPI 默认 `{"detail": ...}`。
4. 核心错误码包括：`unauthorized`、`forbidden`、`not_found`、`invalid_request`、`invalid_source_config`、`invalid_feedback_type`、`quota_exceeded`、`job_not_cancelable`、`job_not_retryable`。

密钥规则：

1. `secret_env` 必须是环境变量名，不得是疑似真实密钥。
2. Service DB 和 API 响应不得包含真实密钥值。
3. Worker 执行时只按环境变量名从运行环境读取真实值。

Source catalog 规则：

1. `src/services/source_type_registry.py` 是 catalog source type、config 校验、`source_key` 和 Worker payload 的统一合同入口。
2. 当前 registry 支持 `rss`、`github_release`、`github_user`、`reddit_subreddit`、`reddit_user`、`telegram_channel`、`apify_social`、`hackernews`。
3. `source_key` 在同一 workspace 内唯一；导入旧配置和重复写入必须按 `source_key` 更新已有 source，而不是重复创建。
4. Telegram 源身份字段使用 config 内的 `channel`；Hub 分类频道使用 `hub_channel` 或兼容 `category`，不得混淆。
5. 无效 source config 返回 `invalid_source_config`；疑似真实密钥返回 `invalid_secret_env`。

任务规则：

1. 创建 job 返回 queued 状态，不在 Web 请求内执行长耗时抓取。
2. Worker 使用 `uv run horizon-worker` 执行 runnable queued job，并写入 succeeded/failed/partial；claim 时写入 `locked_until` lease。
3. `source_test/source_fetch/user_feed_refresh` 计入每日 fetch job 配额。
4. 配置页测试和立即更新按钮必须显示 queued job id，而不是同步抓取结果。
5. 订阅控制台的“刷新我的信息流”“测试”“抓取”按钮只创建 queued job，并在 UI 中显示 job id。
6. Worker 每次 claim 前恢复 lease 过期的 running job；失败 job 在 `max_attempts` 内按退避重新 queued，超过上限后 failed。
7. `POST /api/jobs/{id}/cancel` 只取消 queued job；SQLite MVP 不强杀 running job，running cancel 返回 `job_not_cancelable`。
8. `POST /api/jobs/{id}/retry` 只把 failed、partial 或 cancelled job 重新排队，并重置 attempts。
9. terminal job 可按 `expires_at` 清理；默认保留天数由 `HORIZON_JOB_RETENTION_DAYS` 控制。
10. `user_feed_refresh` 成功后必须保存 `user_feed_snapshots/user_feed_items`，job result 至少包含 `snapshot_id` 和 `item_count`。
11. `source_fetch` 带 `source_id` 时，Worker 必须从 `source_catalog + 当前用户 subscription override` 合成单源 `Config`，跳过 notifications、summaries、enrichment、full-text 和 scheduler 副作用；成功后保存当前用户 feed snapshot，job result 至少包含 `snapshot_id`、`item_count`、`source_id`、`source_type` 和 `source_key`。
12. 真实源 smoke gate 使用 `scripts/service_real_source_smoke.py` 创建/更新 catalog sources、订阅当前用户、创建 `source_test/source_fetch` job，并验证 RSS、Hacker News、GitHub Releases、Telegram public channel 的闭环；Reddit/Apify 只能作为 optional degraded 记录。

Feed / archive 规则：

1. `GET /api/feed/latest` 默认返回当前用户最新 snapshot；不得在多人 Service API 中把全局 `data/site/radar-data.json` 当作用户默认 feed。
2. `GET /api/feed/latest` 的 item 应包含当前用户的 `user_state`，最少表达 `is_read/is_saved/is_later/dismissed` 和对应时间字段；无状态时返回 false/空时间。
3. `GET /api/feed/latest?hide_dismissed=true` 不返回当前用户已忽略 item；`unread_first=true` 将未读 item 稳定排到已读前；`saved_first=true` 将收藏 item 稳定排到未收藏前。默认参数全部为 false，保持 snapshot 原始顺序。
4. `GET /api/feed/history` 返回 `{snapshots, scope}`，snapshot 摘要包含 `snapshot_id/generated_at/item_count/job_id`。
4. `GET /api/archive/items` 返回 `{items, page, filters, scope}`，支持 `channel/topic/source/date_from/date_to/min_score/limit/offset/sort/order`。
5. `GET /api/archive/trends` 支持 `group_by=channel|topic|entity|source` 和 `bucket=none|day|week`。
6. `GET /api/archive/facets` 返回当前用户可见归档的 `channels/topics/sources/entities` 计数。
7. `GET /api/archive/source-quality` 返回每个 source 的 `total_items/hit_rate/empty_topics_rate/other_channel_rate/thin_signal_rate/last_seen_at`。
8. 非法 query 参数必须返回统一 error envelope，例如 `invalid_sort`、`invalid_order`、`invalid_date_range`、`invalid_group_by`、`invalid_bucket`。

用户行为规则：

1. `GET /api/me/item-state?article_ids=a,b` 返回当前用户这些 article id 的状态 map；不可见或不存在的 id 返回默认 false 状态，不泄露其他用户数据。
2. `PATCH /api/me/items/{article_id}/state` 只允许当前用户写自己 feed 中可见的 item；不可见 item 返回 `not_found`。
3. `POST /api/me/items/{article_id}/feedback` 只允许当前用户对自己可见 item 提交 `more_like_this/less_like_this/not_relevant/wrong_topic/quality_issue`。
4. 用户行为 v1 只负责基本状态和反馈入库，不改变归档趋势、source-quality 或推荐排序。

## 6. 静态 JSON 输出合同
入口：`src/ui/site.py`。

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
4. 浏览器静态 UI 不直接读取 `radar-data.json`、`history-data.json` 或 `article-graph.json`，必须通过 `/api/feed/*` 和 `/api/archive/*` 获取数据。

## 7. SQLite 归档合同
入口：`src/storage/article_store.py`。

`articles_light` 必须保留：

1. 旧字段：`category`, `tags_json`
2. 新字段：`channel`, `topics_json`, `signal_strength`, `signal_type`, `entities_json`
3. 兼容读取：旧库缺新列时由 `ArticleStore.initialize()` 迁移。

读取合同：

1. `load_articles_light()` 和 `load_premium_articles()` 返回 dict 时必须同时包含 `channel/topics` 与 `category/tags`。
2. 旧 row 缺 `channel/topics_json` 时，使用 `category/tags_json` 兜底。

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

1. `horizon-scheduler` 只在显式启用 scheduler profile 时运行。
2. 单源刷新是低成本前台任务，不启动 scheduler。
3. Full-text 和 article graph 仅在对应配置启用时运行。
4. 后台任务日志写入 `logs/**`，默认不进入 agent 上下文。
