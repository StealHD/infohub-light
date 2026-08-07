<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/api/ -->
# Inteliscope InfoHub Light API / 接口合同

## 0. 任务读取路由

先读本索引获取公共原则、标识、CLI 与本地配置契约；再按接口主题进入以下模块。


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
10. `set_feed_end_messages` 只接受 `ai_generation_enabled`、`refresh_days`、`style_preset`、`style_prompt`、`list_count`、`ai_key_env`、`model`。缺省值依次为 `false`、`7`、`restrained`、空字符串、`12`、空字符串和空字符串；`refresh_days` 只允许严格整数 `1/7/30`，`style_preset` 只允许 `restrained|warm|light_humor`，`style_prompt` trim 后最多 500 字且不得包含 NUL，`list_count` 只允许严格整数 `3..30`，`ai_key_env` 必须是合法环境变量名，`model` trim 后最多 256 字且不得包含 NUL。启用生成时 Key 和模型均为必填：Key 必须引用当前 workspace 已保存的 AI Key；该 Key 的 Provider、`base_url` 与凭据直接决定客户端，`model` 属于触底文案场景。Key 不受 `ai.provider` 限制，所有已保存 AI Key 平级可选；Worker 只按所选 Key 的 Provider 记账，不读取工作区 AI 开关、模型或连接地址，也绝不回退其他 Key。`ai_key_env` 与 `model` 计入配置指纹，工作区 AI 改动不得使显式触底绑定失效。旧空 Key/模型配置只在读取时兼容投影为工作区当前绑定，页面下一次保存后写为显式值；旧非空 Key 缺模型时按该 Key Provider 的默认模型运行。

响应规则：

1. 成功响应必须包含 `ok: true` 或明确的结果字段。
2. 失败响应必须包含人类可读 `error`。
3. 外部来源测试失败必须给出可执行下一步，不暴露敏感 token。

## 模块索引

| 任务 | 模块 |
| --- | --- |
| 登录、成员、catalog、Feed、配置、health | [Service 核心](service-core.md) |
| Remote MCP delegation、工具和权限 | [Remote MCP](remote-mcp.md) |
| Browser OpenClaw Gateway 与图片媒体票据 | [Browser OpenClaw Gateway](openclaw-gateway.md) |
| Feed/Source 周期、通知、Source Health | [Schedule、Job 与通知](schedules-jobs-notifications.md) |
| 密钥、AI、source catalog 与 Job 细则 | [Service 配置与任务](service-secrets-source-jobs.md) |
| Feed、历史、Presentation、媒体与存储 | [Feed、历史、Presentation 与存储](feed-history-presentation-storage.md) |
| static、SQLite、错误、兼容与幂等 | [Legacy/static 兼容](legacy-static-compatibility.md) |
| 后台任务、迁移、DeepSeek 与 ActorOps | [Job、迁移与 ActorOps](jobs-migrations-actorops.md) |
