### 3.5 Feed Retention Boundary
多人 Service 的 latest/history/search 都以 `UserContentStore` 的目标用户 `user_content_items` 稳定索引为内容真源。`src/services/content_timeline.py` 独占上海自然日、`7/14/30` 天窗口、可信 `effective_at` 与 `today|feed|history` 归属；latest 投影当前窗口，history 投影严格早于窗口的数据，search 横跨在线与冷记录但不改变归属。`UserFeedStore` 继续保存采集结果 snapshot，只提供最近 20 份历史摘要、生成元数据和已保存 featured/daily/personal 成员证据，不再决定内容的 Feed/History 可达性。精确响应以 `docs/contracts/api/` 为唯一真源；该读取路径不得访问 `data/site/*.json`、`data/horizon.db`、`ArticleStore` 或 `articles_light`。

稳定内容默认全部保留；普通自动 retention 只能删除紧凑 snapshot、任务、缓存、使用记录、过期 session/proposal 与孤立媒体，不得删除 `user_content_items`。收藏、稍后读和按需详情同样使用稳定索引，不依赖 item 仍存在于最新 snapshot。v4 负责稳定内容表，v11 负责 `effective_at/search_text` 与用户 FTS5 trigram 索引；任一显式迁移都必须先以 SQLite backup API 创建权限 `0600` 的独立副本，再校验 integrity 与 foreign keys。

### 3.5A Retired Artifact Boundary
`data/site/**`、`data/horizon.db`、旧 summaries、本地 MCP run 与既有 feedback 表/行均为 inert operator-owned artifact。API、Worker、React、Remote MCP、初始化和迁移不得读取、写入、投影、迁移或物理删除它们；`/api/archive/*` 与 feedback POST 不在 OpenAPI 中并返回统一 404。`data/archives/**` 属于下述现役冷归档，不受本边界影响。

### 3.5B Storage Governance Boundary
`src/services/storage_governance.py::StorageGovernanceService` 独占当前工作区的存储概览、两阶段候选计划、标准清理、90 天冷归档、恢复和归档永久删除。`src/api/storage_routes.py` 只负责 owner/admin 鉴权、请求 shape、安全 envelope 与 `no-store` 响应；入口层不得拼任意 SQL、接受原始路径、运行在线 `VACUUM` 或直接删除文件。每个计划绑定 actor/workspace、十分钟有效期和候选指纹；apply 在写事务内复算候选，变化即 fail closed。

冷归档文件只可写入私有 `data/archives`，先完成临时 ZIP、manifest/NDJSON/媒体写入、计数与 checksum 校验，再原子落位并提交批次；只有提交成功后才能把在线正文/分析输入/媒体降为永久可搜索元数据，并通过 post-commit cleanup 移除媒体文件。restore 必须先复验批次、workspace、文件 SHA-256、媒体成员路径和每项 checksum，再幂等恢复数据库与媒体；失败时回滚数据库并移除本次新建文件。收藏、稍后读、当前 Feed、通知 pending/sending 和未提交归档始终受保护。系统永不自动永久删除归档；owner 的永久删除必须以已恢复批次、零冷引用、独立预演和精确确认短语为前置条件。

### 3.6 Tenant/User Boundary
小团体 MVP 使用单 workspace。用户、角色、公共/私有 source catalog、订阅配置、job queue、usage event 和 secret ref 归 `src/storage/service_store.py` 管理。入口层不得直接拼 SQL 或绕过 `ServiceStore`/service helper 读写这些状态。

### 3.6A User Behavior Boundary
用户 Feed item 的已读、收藏、稍后读和忽略状态归 `src/services/user_item_state.py` 管理。写入前必须用当前 snapshot 或 `user_content_items` 稳定索引校验当前用户可见边界；不可见 item 不得落行为数据。选中内容不产生隐式已读写入。Fresh DB 不创建 feedback 表；旧表与行只按 3.5A 原样保留，不进入任何行为路径。

### 3.6B Source Catalog Boundary
`src/services/source_type_registry.py` 是 Service API source type 元数据、Web setup alias、catalog config 校验、`source_key` 生成和 Worker payload 生成的唯一规则入口。`youtube_channel` 只是一等 Web setup alias，必须规范化并存储为 catalog `rss`；既有规范 YouTube channel RSS 由 registry 派生相同 setup type，不增加数据库 enum 或 scraper。`src/services/youtube_channel.py` 独占公开 channel ID/链接/handle 解析，只能从固定 YouTube 主机执行一次有界、无重定向的公共 HTML 读取；API、Worker 和前端不得自行解析 handle 或接受任意解析 URL。`src/rsshub.py` 只拥有 workspace RSSHub Base URL、受控站点/route allowlist、语义 source key、runtime feed URL 与 route-scoped access code 解析；RSSHub 不得成为独立 catalog type。`/api/catalog/sources`、`/api/catalog/import-config-sources`、配置页兼容 source action、Remote MCP 和 Worker 都必须复用这些边界，避免在路由、前端、Skill 或任务执行层散落 source 类型与 RSSHub path 规则。

`source_catalog.source_key` 是同 workspace 内 source 的幂等身份键。旧 `data/config.json` source 导入、同一操作者的重复/并发 catalog 写入和后续 source 市场同步必须按 `source_key` 更新已有 source，不得制造重复公共源；另一用户拥有的 private source 不得因 key 碰撞被返回、接管或覆盖。Telegram 这类字段名复用的来源必须在 registry/API helper 中区分“源身份字段”和“Hub 分类字段”。

Catalog `source_fetch` 的精准抓取路径归 `src/services/catalog_source_runner.py` 管理。该 runner 只能读取 catalog source、当前用户 subscription override 和全局非 source 配置来生成单源 `Config`；不得把 UI payload 当作权威抓取配置，也不得在 Worker 中绕过用户作用域 snapshot 写入。

### 3.6C Structured Feed Production Boundary
`HorizonOrchestrator.execute()` 只负责抓取、跨源去重、可选分析并返回不可变 `FeedRunResult`；来源级成功/失败必须由 `SourceOutcome` 显式表达，抓取异常不得折叠为空列表。跨源 URL 去重必须保留完整 `source_ids/subscription_ids/source_keys` provenance，且 query identifier 属于 URL 身份。`FeedProductionService` 是全量刷新、单源合并、失败来源旧内容保留、窗口清理和排序的唯一 finalizer；partial 保留判断使用 provenance 与 failed active source 的交集，不能只看 primary `source_id`。Service Worker 与 catalog runner 必须共用该 finalizer，不得写全局静态文件、摘要、旧通知或图谱；偏好来源事件只可交给 3.8C 的 Service outbox。

`src/services/feed_payload.py` 独占 Feed wire 序列化与 snapshot payload 规范化；`src/services/feed_read.py::FeedReadService` 必须显式接收 `ServiceStore` 并只从 Service DB 提供 latest/history/search。两者不得接受 `data_dir/site_dir`、导入 UI 模块、复制静态资源或查询 `ArticleStore`。

### 3.6D Shared Acquisition Boundary

`src/services/source_acquisition.py::SourceAcquisitionCoordinator` 是 Service 生产抓取共享的唯一边界。public/workspace source 只共享同 workspace 的规范化中性内容；private source 的 acquisition key 必须包含 user isolation。用户频道/主题/标签、priority、analysis mode、AI 分析、行为状态和 Feed snapshot 永远不进入共享池。key 还必须覆盖 source identity/type、规范化网络配置、adapter contract、secret-ref identity/version 与抓取窗口；Apify 池模式额外覆盖 pool generation，generation 变化后旧 owner 不得发布缓存。真实 secret 值不得入 key、表或诊断。

`source_acquisition_states` 只负责 claim-token lease/backoff，`source_content_snapshots/items` 只负责成功内容（包括零条结果）。TTL 由相关启用 source/feed schedule 的最短周期派生并受 5..60 分钟边界约束；等待者不计上游 attempt，只有 claim winner 在实际调用前计量。`source_test` 共用同源互斥但绕过 production cache 且不写 content pool。该能力由 `HORIZON_SHARED_ACQUISITION_ENABLED` 控制并默认关闭，不改变公开 job type、API 异步边界或默认 API + Worker 拓扑。

### 3.6E Canonical Feed Storage Boundary

`src/services/canonical_content.py` 是全量与增量 Feed 的共同 canonical identity/provenance merger；URL query 属于身份，最新 Feed article id 优先稳定复用。`UserFeedStore` 以有序公开内容 hash 判断版本：时间、job/run 诊断和 live user state 不参与；no-op 返回既有 snapshot 并显式 `snapshot_created=false`。

compact writer 只在 `HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED=true` 且目标数据库已完成 Feed storage v3 migration 时启用。代码与示例配置对新空库默认 true，但 marker 仍为硬门禁，现存未迁移数据库保持 storage v1，既有部署可显式设 false。storage v2 snapshot payload 保存 metadata、item id 顺序及集合成员 id，完整 item 只写 child rows；reader 必须同时支持 legacy full payload 和 compact payload。现存数据但未迁移时 Worker maintenance 保持延后；真正无 v3 遗留数据的新空库可在 additive 初始化时自动记录 marker。迁移不得原地改写 legacy body，只能 backfill hash、执行 retention、记录 migration 并在 UTC backup 后校验 integrity/foreign keys。
