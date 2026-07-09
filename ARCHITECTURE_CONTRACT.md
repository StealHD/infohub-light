# Inteliscope InfoHub Light 架构合同

## 1. 文档目的
本文件定义系统职责分层和不可跨越的边界。代码实现应优先遵循现有模块形状，只有在边界变化时才更新本文件。

## 2. 默认分层
当前默认分层：

1. API / CLI / event 入口层：`src/main.py`, `src/ui/server.py`, `src/api/server.py`, MCP adapter。只负责参数接收、校验和薄编排。
2. Service 层：`src/orchestrator.py`, `src/services/**`。负责抓取、去重、分析、发布、单源刷新、全文抓取、关系图等流程编排。
3. Domain 层：`src/models.py`, `src/tag_policy.py`, `src/source_selection.py`。负责标准模型、taxonomy、source ref、状态和规则输入输出。
4. Adapter / Integration 层：`src/scrapers/**`, `src/ai/**`, webhook/email/openbb/apify client。隔离外部系统字段、协议和失败模式。
5. Storage 层：`src/storage/**`, `data/site/**`, `data/horizon.db`, `data/service.db`。隐藏持久化细节和兼容迁移。
6. Output / Reporting 层：`src/ui/site.py`, `src/ui/static/**`, summaries, webhook rendering。负责输出组装和渲染，不直接采集数据。

## 3. 关键边界
### 3.1 Source Adapter Boundary
Scraper 输出必须是 `ContentItem`，外部字段只能放入明确 metadata。上层不得直接依赖 RSS/GitHub/Reddit/Telegram/Apify/OpenBB 的原始结构。

### 3.2 Taxonomy Boundary
Hub taxonomy 的唯一规范入口是 `src/tag_policy.py`。业务层和 UI 可以消费 `channel/topics/signal_strength/signal_type/entities`，但不得散落自定义 normalization。

### 3.3 AI Boundary
AI prompt 与解析位于 `src/ai/**`。`personal_tags` 只能作为用户偏好信号，不得进入 AI scoring prompt。AI cache 必须随 prompt schema 变化 bump version。

### 3.4 Static UI Boundary
静态 UI 只通过 `/api/*` 消费数据，不直接调用 scraper、AI client、storage，也不依赖 `data/site/*.json` 或 `data/config.json` 源列表的内部文件结构。`data/site/*.json` 只作为 service API facade 的兼容输入；订阅控制台通过 `/api/dashboard/summary`、`/api/catalog/sources`、`/api/me/subscriptions` 和 `/api/jobs/*` 管理公共源市场、用户订阅、私有源和抓取任务。配置页保留 `/api/config`、`/api/config/action`、`/api/source/test`、`/api/source/update` 的 FastAPI facade 作为高级兼容入口。

静态 UI 在小团体服务模式下必须先完成登录门禁，再加载 `/api/feed/*` 或 `/api/archive/*`。未登录时只显示登录界面，不展示信息流、历史、图谱或配置内容。

### 3.5 Archive Boundary
`ArticleStore` 负责 SQLite schema、migration、upsert、load compatibility 和归档查询。多人 Service API 的 feed/archive 默认使用 `user_feed_snapshots` 和 `user_feed_items` 表达用户可见边界；上层不得绕过 `ArticleStore`、`ServiceStore` 或 `UserFeedStore` 散落手写 SQL 访问 `articles_light`，除非是测试或运维诊断。

### 3.6 Tenant/User Boundary
小团体 MVP 使用单 workspace。用户、角色、公共/私有 source catalog、订阅配置、job queue、usage event 和 secret ref 归 `src/storage/service_store.py` 管理。入口层不得直接拼 SQL 或绕过 `ServiceStore`/service helper 读写这些状态。

### 3.6A User Behavior Boundary
用户 feed item 的已读、收藏、稍后读、忽略和反馈事件归 `src/services/user_item_state.py` 管理。写入前必须用 `user_feed_items` 校验当前用户可见边界；不可见 item 不得落行为数据。用户行为 v1 不改变归档分析、source-quality 或推荐排序。

### 3.6B Source Catalog Boundary
`src/services/source_type_registry.py` 是 Service API source type 元数据、catalog config 校验、`source_key` 生成和 Worker payload 生成的唯一规则入口。`/api/catalog/sources`、`/api/catalog/import-config-sources`、配置页兼容 source action 和 Worker 都必须复用该 registry，避免在路由、前端或任务执行层散落 source 类型字段规则。

`source_catalog.source_key` 是同 workspace 内 source 的幂等身份键。旧 `data/config.json` source 导入、重复 catalog 写入和后续 source 市场同步必须按 `source_key` 更新已有 source，不得制造重复公共源。Telegram 这类字段名复用的来源必须在 registry/API helper 中区分“源身份字段”和“Hub 分类字段”。

Catalog `source_fetch` 的精准抓取路径归 `src/services/catalog_source_runner.py` 管理。该 runner 只能读取 catalog source、当前用户 subscription override 和全局非 source 配置来生成单源 `Config`；不得把 UI payload 当作权威抓取配置，也不得在 Worker 中绕过用户作用域 snapshot 写入。

### 3.7 Secret Boundary
Service API 和 catalog 只保存环境变量名或 secret ref，不保存真实密钥。API 响应不得返回真实 token、API key、webhook URL 或模型 key。

### 3.8 Job Boundary
长耗时抓取、source test 和用户 feed refresh 必须通过 job queue 表达。Web 请求只创建、取消、重试或查询 job；Worker 负责执行 job 并写入状态/result。Worker claim 使用 SQLite lease (`locked_until`)；过期 running job 会在下一次 claim 前回到 queued；失败 job 在 `max_attempts` 内重试，超过上限后进入 failed。SQLite MVP 不强杀正在执行的 Python 任务。

`user_feed_refresh` 成功后必须把生成 payload 保存为当前用户 snapshot，并写入 `snapshot_id/item_count` 到 job result。`/api/feed/*` 和 `/api/archive/*` 默认只读取用户作用域 snapshot/visible items；全局 `data/site/*.json` 仅保留给 CLI/static 兼容或 article graph facade。

`source_fetch` 带 `source_id` 时属于用户作用域精准抓取，不走旧 `source_type:index` 单源刷新路径。Worker 执行后必须通过 `UserFeedStore` 保存当前用户 snapshot，并在 job result 中返回 source 和 snapshot 元数据。

### 3.9 Config Compatibility Boundary
`data/config.json` 暂时只承载 AI、过滤、Webhook、标签库等全局配置。多人 source 的权威状态从配置页迁移到 `source_catalog` 和 `user_subscriptions`；兼容层可以把 service 状态投影成旧 `config.sources.*` 结构供静态 JS 渲染，但不得把真实密钥或同步抓取副作用带回 Web 请求。

## 4. 禁止事项
1. 禁止入口层直接访问外部系统细节。
2. 禁止输出层反向驱动领域模型。
3. 禁止规则散落在路由、命令入口或模板中。
4. 禁止把某个运行时来源的字段命名作为全系统标准命名。
5. 禁止在 Web UI JS 中重新实现 Python taxonomy 规则。
6. 禁止把成本型流程作为 light runtime 的默认副作用。
7. 禁止静态 UI 直接读取 `radar-data.json`、`history-data.json`、`article-graph.json` 或依赖 `data/config.json` 源列表文件结构。

## 5. 扩展原则
新增来源、规则、输出或存储时，应先扩展抽象合同，再实现具体适配。

具体要求：

1. 新 source adapter：更新 source config model、adapter、tests，必要时更新 `API_CONTRACT.md` 和 `project-defaults.yaml`。
2. 新 taxonomy 字段：先更新 `tag_policy.py`、`ContentItem`、static payload、archive contract，再更新 UI。
3. 新输出面：先定义 static JSON 或 API contract，再做 UI。
4. 新成本型能力：必须有配置开关、低成本验证路径和 degrade 行为。
