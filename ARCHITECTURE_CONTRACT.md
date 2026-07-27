<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=ARCHITECTURE_CONTRACT.md -->
# Inteliscope InfoHub Light 架构合同

## 1. 文档目的
本文件定义系统职责分层和不可跨越的边界。代码实现应优先遵循现有模块形状，只有在边界变化时才更新本文件。

## 2. 默认分层
当前默认分层：

1. API / CLI / event 入口层：`src/main.py`, `src/ui/server.py`, `src/api/server.py`, MCP adapter。只负责参数接收、校验和薄编排。
2. Service 层：`src/orchestrator.py`, `src/services/**`。当前 Service 路径负责抓取、去重、可选分析、用户 Feed finalization 与留存；全局发布、全文和关系图只属于 legacy publisher 路径。
3. Domain 层：`src/models.py`, `src/tag_policy.py`, `src/source_selection.py`。负责标准模型、taxonomy、source ref、状态和规则输入输出。
4. Adapter / Integration 层：`src/scrapers/**`, `src/ai/**`, webhook/email/openbb/apify client。隔离外部系统字段、协议和失败模式。
5. Storage 层：Service 状态与用户 Feed 位于 `data/service.db`；`data/site/**` 与 `data/horizon.db` 是 legacy optional 存储。两条路径共享部分 storage 模块，但 Service Feed 读取不得回退到 legacy 存储。
6. Output / Reporting 层：`src/ui/site.py`, `src/ui/static/**`, summaries, webhook rendering。负责输出组装和渲染，不直接采集数据。

<!-- init-pro:section name=boundaries -->
## 3. 关键边界
### 3.1 Source Adapter Boundary
Scraper 输出必须是 `ContentItem`，外部字段只能放入明确 metadata。上层不得直接依赖 RSS/GitHub/Reddit/Telegram/Apify/OpenBB 的原始结构。

### 3.2 Taxonomy Boundary
Hub taxonomy 的唯一规范入口是 `src/tag_policy.py`。业务层和 UI 可以消费 `channel/topics/signal_strength/signal_type/entities`，但不得散落自定义 normalization。

### 3.3 AI Boundary
AI prompt、解析、受控输入/输出和概括硬截断位于 `src/ai/**`。`personal_tags` 只能作为用户偏好信号，不得进入 AI scoring prompt。所有 Service item 在 `FeedRunResult` 前必须经过统一概括规范化；AI 失败时按来源摘要、正文、标题回退。新版分析不产出“为什么值得关注”或 `reason`，只允许补充中文概括、评分、taxonomy、signal 和可选建议动作。AI cache 必须随 prompt/schema/runtime 约束变化 bump version，截断或不可解析响应不得缓存。

Service AI cache 归 `src/services/user_analysis_cache.py` 所有，必须按 workspace/user 双重隔离；缓存连接不得在模型网络调用期间占用主 job 写事务。缓存 key 必须覆盖内容与展示事实，值只保存安全推理结果，不保存原始正文、prompt、密钥或 legacy reason，且不得跨用户命中。

### 3.3A Content Presentation Boundary
`src/services/content_presentation.py` 是所有 Service Feed item 的唯一规范展示投影器。RSS、GitHub Release/User、Reddit Subreddit/User、Telegram、Apify Social 和 Hacker News adapter 只负责把外部结构转换为 `ContentItem + metadata`；投影器再用确定性代码统一生成 Presentation v1 的来源、作者、时间、双链接、内容类型、来源摘录、taxonomy、原生互动量和分析状态。前端不得重写来源特定解析规则，adapter 也不得直接产出 UI shape。

来源摘录清洗、字段缺省、枚举、长度上限和 `reason` 禁止规则以 `API_CONTRACT.md` 为唯一 wire 真源。确定性字段先由代码提取，AI 只处理代码无法可靠推断的语义字段，以降低 token 和跨来源格式漂移。

稳定详情归 `src/services/user_content_store.py` 所有：每次 Feed finalize 将规范列表 item 写入 `user_content_items`，再把抓取器已有正文清洗为最多 20,000 字的 captured body。详情投影升级为 Presentation v2；旧 snapshot 回填只能是 `excerpt_only`。`src/services/media_cache.py` 在 Worker 内经公共网络地址固定策略下载最多 6 张内容图和一个来源头像，验证真实图片类型、8 MiB 上限并原子落盘；第三方临时媒体 URL 不得进入 snapshot 或稳定索引，浏览器只能通过登录保护的 `/api/media/*` 访问。合成 DNS 例外仅允许 Instagram 既有 CDN 与精确后缀 `pbs.twimg.com`；头像身份忽略 query/fragment，身份变化即时验证候选，同身份最多每 24 小时复验 checksum，候选失败必须保留旧 ready 版本。

### 3.4 Service Frontend Boundary
默认 Service UI 位于 `frontend/`，由 React + TypeScript 构建到独立 `src/ui/service_static` 产物，只通过 `/api/*` 消费数据；不得直接调用 scraper、AI client 或 storage，也不依赖 `data/site/*.json` 或 `data/config.json` 源列表的内部文件结构。阅读、收藏与历史只调用 `/api/feed/*`；条目提供站内查看已抓正文/图片、打开原文、显式已读/未读、复制摘要、收藏、稍后读和忽略，不提供网页全文代理/iframe、偏好 feedback 或 Graph。订阅控制台通过 catalog、subscriptions、jobs、schedule、source-health 和 users API 管理信息获取，并通过 subscription 字段逐源选择新内容通知；首页“获取新内容”创建 `user_feed_refresh`，不得退化为只重新 GET snapshot。设置页保留 `/api/config`、`/api/config/action` facade 管理全局非 source 配置，并通过用户作用域 notification settings API 管理 write-only 目的地和模拟发送测试；两者不得混用 legacy Webhook 状态。

React Query 的所有用户数据 key 必须包含当前 `user_id`；logout、401 或身份切换必须先取消旧请求并删除旧用户缓存。Vite 的 hashed `/assets/*` 可 immutable cache，`index.html` 必须 no-cache；BrowserRouter 深链接由 FastAPI 回退到 React index。`HORIZON_SERVICE_UI_VARIANT=legacy` 只作为一个发布周期的回滚入口，`src/ui/static` 继续服务 legacy CLI/horizon-web，不得重新成为默认 Service 数据路径。

React 视觉系统、组件所有权、响应式布局和视觉验收以 `UI_CONTRACT.md` 为唯一真源。Material UI theme/provider 与语义组件归 `frontend/src/ui/**` 所有；Feature 层不得绕过该边界私造 palette、shape、shadow 或受控交互组件。Feed 列表优先消费 API 的 `presentation.version=1`，按需详情优先消费 `presentation.version=2`；旧 flat 字段只作为一个兼容周期的缺失兜底；React 不显示或搜索 legacy `reason`。当前迁移覆盖 App Shell、共享 Feed workspace 与订阅/来源 workspace；设置和登录页可以暂时保留 CSS Modules，但后续迁移必须复用同一 UI 层。

Service UI 在小团体服务模式下必须先完成登录门禁，再加载用户 Feed 或控制台 API。未登录时只显示登录界面，不展示信息流、历史、订阅或配置内容。

### 3.5 Feed Retention Boundary
多人 Service 的 latest/history/search 都以 `UserContentStore` 的目标用户 `user_content_items` 稳定索引为内容真源。`src/services/content_timeline.py` 独占上海自然日、`7/14/30` 天窗口、可信 `effective_at` 与 `today|feed|history` 归属；latest 投影当前窗口，history 投影严格早于窗口的数据，search 横跨在线与冷记录但不改变归属。`UserFeedStore` 继续保存采集结果 snapshot，只提供最近 20 份历史摘要、生成元数据和已保存 featured/daily/personal 成员证据，不再决定内容的 Feed/History 可达性。精确响应以 `API_CONTRACT.md` 为唯一真源；该读取路径不得访问 `data/site/*.json`、`data/horizon.db`、`ArticleStore` 或 `articles_light`。

稳定内容默认全部保留；普通自动 retention 只能删除紧凑 snapshot、任务、缓存、使用记录、过期 session/proposal 与孤立媒体，不得删除 `user_content_items`。收藏、稍后读和按需详情同样使用稳定索引，不依赖 item 仍存在于最新 snapshot。v4 负责稳定内容表，v11 负责 `effective_at/search_text` 与用户 FTS5 trigram 索引；任一显式迁移都必须先以 SQLite backup API 创建权限 `0600` 的独立副本，再校验 integrity 与 foreign keys。

### 3.5A Legacy Archive Compatibility Boundary
`ArticleStore`、`data/horizon.db`、archive items/trends/facets/source-quality、feedback 表/API 和旧静态 history/graph 只为兼容保留，不是当前产品 UI 或后续建设目标。默认 Service UI 不依赖或调用这些接口；`/api/archive/graph` 固定返回 disabled 安全空响应。保留 compatibility surface 不得被解释为 Service Feed 的架构依赖。

### 3.5B Storage Governance Boundary
`src/services/storage_governance.py::StorageGovernanceService` 独占当前工作区的存储概览、两阶段候选计划、标准清理、90 天冷归档、恢复和归档永久删除。API 只负责 owner/admin 鉴权、请求 shape 与安全 envelope；入口层不得拼任意 SQL、接受原始路径、运行在线 `VACUUM` 或直接删除文件。每个计划绑定 actor/workspace、十分钟有效期和候选指纹；apply 在写事务内复算候选，变化即 fail closed。

冷归档文件只可写入私有 `data/archives`，先完成临时 ZIP、manifest/NDJSON/媒体写入、计数与 checksum 校验，再原子落位并提交批次；只有提交成功后才能把在线正文/分析输入/媒体降为永久可搜索元数据，并通过 post-commit cleanup 移除媒体文件。restore 必须先复验批次、workspace、文件 SHA-256、媒体成员路径和每项 checksum，再幂等恢复数据库与媒体；失败时回滚数据库并移除本次新建文件。收藏、稍后读、当前 Feed、通知 pending/sending 和未提交归档始终受保护。系统永不自动永久删除归档；owner 的永久删除必须以已恢复批次、零冷引用、独立预演和精确确认短语为前置条件。

### 3.6 Tenant/User Boundary
小团体 MVP 使用单 workspace。用户、角色、公共/私有 source catalog、订阅配置、job queue、usage event 和 secret ref 归 `src/storage/service_store.py` 管理。入口层不得直接拼 SQL 或绕过 `ServiceStore`/service helper 读写这些状态。

### 3.6A User Behavior Boundary
用户 Feed item 的已读、收藏、稍后读和忽略状态归 `src/services/user_item_state.py` 管理。写入前必须用当前 snapshot 或 `user_content_items` 稳定索引校验当前用户可见边界；不可见 item 不得落行为数据。选中内容不产生隐式已读写入。旧 feedback 写入路径只兼容保留，不进入默认 UI，也不改变 Feed 过滤、排序或推荐。

### 3.6B Source Catalog Boundary
`src/services/source_type_registry.py` 是 Service API source type 元数据、catalog config 校验、`source_key` 生成和 Worker payload 生成的唯一规则入口。`src/rsshub.py` 只拥有 workspace RSSHub Base URL、受控站点/route allowlist、语义 source key、runtime feed URL 与 route-scoped access code 解析；RSSHub 不得成为独立 catalog type。`/api/catalog/sources`、`/api/catalog/import-config-sources`、配置页兼容 source action、Remote MCP 和 Worker 都必须复用这些边界，避免在路由、前端、Skill 或任务执行层散落 source 类型与 RSSHub path 规则。

`source_catalog.source_key` 是同 workspace 内 source 的幂等身份键。旧 `data/config.json` source 导入、同一操作者的重复/并发 catalog 写入和后续 source 市场同步必须按 `source_key` 更新已有 source，不得制造重复公共源；另一用户拥有的 private source 不得因 key 碰撞被返回、接管或覆盖。Telegram 这类字段名复用的来源必须在 registry/API helper 中区分“源身份字段”和“Hub 分类字段”。

Catalog `source_fetch` 的精准抓取路径归 `src/services/catalog_source_runner.py` 管理。该 runner 只能读取 catalog source、当前用户 subscription override 和全局非 source 配置来生成单源 `Config`；不得把 UI payload 当作权威抓取配置，也不得在 Worker 中绕过用户作用域 snapshot 写入。

### 3.6C Structured Feed Production Boundary
`HorizonOrchestrator.execute()` 只负责抓取、跨源去重、可选分析并返回不可变 `FeedRunResult`；来源级成功/失败必须由 `SourceOutcome` 显式表达，抓取异常不得折叠为空列表。跨源 URL 去重必须保留完整 `source_ids/subscription_ids/source_keys` provenance，且 query identifier 属于 URL 身份。`FeedProductionService` 是全量刷新、单源合并、失败来源旧内容保留、窗口清理和排序的唯一 finalizer；partial 保留判断使用 provenance 与 failed active source 的交集，不能只看 primary `source_id`。Service Worker 与 catalog runner 必须共用该 finalizer，不得执行全局历史增量去重或写全局静态文件、摘要、legacy 通知和图谱；偏好来源事件只可交给 3.8C 的 Service outbox。

旧 CLI/scheduler 的 `run()` 先调用结构化 `execute(legacy_sources=True)`，再由 `src/services/legacy_publisher.py::LegacyPublisher` 独占全局静态站、`history-data`、摘要、通知、`ArticleStore` archive 和 graph 发布；单源 CLI 静态写入也必须通过该 publisher。该路径可以保留 legacy optional 的全局 archive/graph，但不得被 Service API/Worker 调用，也不得成为 Service UI 的读取兜底。

### 3.6D Shared Acquisition Boundary

`src/services/source_acquisition.py::SourceAcquisitionCoordinator` 是 Service 生产抓取共享的唯一边界。public/workspace source 只共享同 workspace 的规范化中性内容；private source 的 acquisition key 必须包含 user isolation。用户频道/主题/标签、priority、analysis mode、AI 分析、行为状态和 Feed snapshot 永远不进入共享池。key 还必须覆盖 source identity/type、规范化网络配置、adapter contract、secret-ref identity/version 与抓取窗口；Apify 池模式额外覆盖 pool generation，generation 变化后旧 owner 不得发布缓存。真实 secret 值不得入 key、表或诊断。

`source_acquisition_states` 只负责 claim-token lease/backoff，`source_content_snapshots/items` 只负责成功内容（包括零条结果）。TTL 由相关启用 source/feed schedule 的最短周期派生并受 5..60 分钟边界约束；等待者不计上游 attempt，只有 claim winner 在实际调用前计量。`source_test` 共用同源互斥但绕过 production cache 且不写 content pool。该能力由 `HORIZON_SHARED_ACQUISITION_ENABLED` 控制并默认关闭，不改变公开 job type、API 异步边界或默认 API + Worker 拓扑。

### 3.6E Canonical Feed Storage Boundary

`src/services/canonical_content.py` 是全量与增量 Feed 的共同 canonical identity/provenance merger；URL query 属于身份，最新 Feed article id 优先稳定复用。`UserFeedStore` 以有序公开内容 hash 判断版本：时间、job/run 诊断和 live user state 不参与；no-op 返回既有 snapshot 并显式 `snapshot_created=false`。

compact writer 只在 `HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED=true` 且目标数据库已完成 Feed storage v3 migration 时启用。storage v2 snapshot payload 保存 metadata、item id 顺序及集合成员 id，完整 item 只写 child rows；reader 必须同时支持 legacy full payload 和 compact payload。现存数据但未迁移时 writer 保持 storage v1、Worker maintenance 保持延后；真正无 v3 遗留数据的新空库可在 additive 初始化时自动记录 marker。迁移不得原地改写 legacy body，只能 backfill hash、执行 retention、记录 migration 并在 UTC backup 后校验 integrity/foreign keys。

### 3.6F Local Agent / Remote MCP Boundary

OpenClaw 的模型、对话、推理和 Skill 运行在每位用户自己的电脑或其专属云端 Gateway；Service 端不新增 Agent、LLM、Worker、端口或容器，也不代理 Gateway。浏览器的 `frontend/src/features/openclaw/` 直接实现 OpenClaw Gateway WebSocket v4、设备签名、用户/Gateway 隔离凭证库和有界聊天状态；功能关闭时不得创建 WebSocket。未来从本地切换云端只替换为用户专属 `wss://` URL 和对应 Origin allowlist，不改变 Remote MCP 或 Service 部署。

`scripts/setup_openclaw_local.py` 是仓库托管 Inteliscope Skill 的本地 reconcile 入口：比较 bundled 与已安装目录中的非隐藏文件，忽略 OpenClaw 自己的 `.openclaw` 元数据；缺失时安装，漂移时使用 `--force` 刷新，并只在 Skill 或 Origin 变化时重启已运行 Gateway。旧会话可能保留历史路由指令，刷新后必须用新会话验收；`--skip-skill` 是保留用户自主管理 Skill 的显式退出路径。该流程不得读取或写入 MCP/Gateway token，也不得触发订阅 prepare/apply。

`src/mcp/remote_server.py` 是现有 FastAPI 上的无状态 Streamable HTTP adapter；12 个读工具分别由 `remote_service.py` 的有界数据投影、`remote_subscription_service.py` 的 registry 引导/发现与 Bilibili 名称查询 facade、`remote_diagnostics.py` 的确定性只读诊断和 `operation_log.py` 的脱敏事件查询提供，diagnostics 同时承载写连接专用的 prepare facade。除 `search_bilibili_users` 通过 `src/services/bilibili_user_search.py` 访问固定 Bilibili 公开端点外，它们全部直接调用 Service/Store 或私有结构化事件文件；任何工具都禁止内部 HTTP 回环和调用用户提供的任意 URL。每个 FastAPI app 拥有独立 FastMCP 和 session manager，父 app lifespan 显式管理其生命周期，`/mcp` 与 `/api/*` 共用请求级 SQLite connection scope 和事务泄漏检查。

Remote MCP 的 16 个工具与 `src/mcp/server.py` 的本地 stdio/legacy MCP 实现物理分离。legacy 抓取、AI、配置、Webhook 和任何直接写工具不得注册到 Remote MCP。delegation 认证直接生成当前用户主体，不经管理员代理权限；所有 object lookup 都在该主体内完成。读操作要求 read scope；prepare/apply 以固定顺序检查 write flag、write scope 和实时角色，viewer 永远只读。

`SubscriptionMutationService` 是 REST 与 Remote MCP 的唯一 subscription/source/schedule 业务 mutation owner；Remote MCP 不复制 REST 写逻辑。`AgentChangeProposalService` 只拥有短期密封 proposal 的授权、指纹和 lifecycle：prepare 在自己的短事务持久化 preview/确认 hash，apply 在 `BEGIN IMMEDIATE` 内重验实时主体与 mutation 先决条件，并与业务 mutation 原子提交。proposal record 只保存安全 snapshot、preview、指纹和结果摘要；cleanup 是 commit 后 best-effort，绝不把已提交业务变化伪装成失败。

`RemoteMCPDiagnostics` 只读取用户范围内持久化的 Source Health、schedule、safe Job projection、匿名 Worker readiness 和 `secret_configured`；它不执行修复、重试、取消、网络访问或写入。`OperationLogQueryService` 只读私有 operation JSONL，并在文件解析后再次执行 workspace + 当前 actor/subject 隔离与输出白名单。二者的分类、脱敏和 unknown/unavailable 退化属于服务端合同，而不是 Skill 推理。Remote MCP adapter 保持无 session、无调用方身份参数、无服务器侧 Agent 状态；`last_used_at` 的有界 touch 和 proposal/audit 行是显式例外，不构成会话状态。

Gateway bootstrap token 只存在于 React 表单 state；API、React Query、URL、Web storage 和日志均不得接收。浏览器配对后只把 non-exportable Ed25519 CryptoKey、exact `operator.read + operator.write` device token 和 session key保存在 IndexedDB，key 必须包含当前 Inteliscope user 与规范化 Gateway URL。页面登出清空内存消息并断开 socket；忘记设备同时删除 IndexedDB 凭证。MCP delegation token 与 Gateway token 是两套独立凭证，任何 UI、日志或配置都不得混名或互相复用。

### 3.6G Observability Logging Boundary

`src/logging_utils.py` 是 API、Worker、legacy Scheduler 和 CLI 的唯一进程日志配置边界；它分别创建 `runtime-<service>.jsonl` 与 `operations-<service>.jsonl`，使用 UTC 每日轮转、私有目录/文件权限及只匹配系统文件名的保留清理。运行日志必须先格式化再统一脱敏；业务模块不得自行建立日志文件 handler、记录 query/body 或把任意业务对象序列化到日志。

`src/services/operation_log.py` 独占 schema-v1 operation event 构造、request ContextVar、严格标识符/枚举校验、白名单查询和最多 20,000 行的反向读取。workspace/actor/subject 只存在于文件内用于隔离；MCP 投影必须移除身份、文件、message、stack、URL、config/payload、文章内容和凭据。符号链接、损坏/未完成行和不可读目录必须安全退化，查询不新增数据库表、REST API 或前端状态。

API 只接受服务端生成的 request ID；路由事件只使用模板路径。成功事件由最外层请求边界在业务事务已经提交且 transaction guard 通过后写入；回滚、事务泄漏与未处理异常只能写失败。Worker 的 claim、finalize、来源获取和通知事件也只能在各自持久状态提交后写入。普通 GET、Feed 浏览、item-state 高频成功、空轮询和 heartbeat 不生成 operation event；结构化日志失败为 best-effort，不得改变业务事务或公开响应。

详细字段、敏感值禁令、事件矩阵和排障流程以 `docs/dev/observability-logging.md` 为唯一真源。

### 3.6H Apify Key Pool Boundary

`src/services/apify_key_pool.py::ApifyKeyPoolService` 独占工作区有序成员、粘性 active Key、pool generation、额度快照与 Actor Run ledger。`src/scrapers/apify_client.py::ApifyClient` 独占 Apify HTTP 生命周期和错误分类；每次 Run 启动前取得不可变的 `secret_id + secret_version + pool_generation` lease，start、poll、abort 和 dataset 读取必须使用该 lease 的同一 Token。`src/services/apify_pool_runtime.py` 独占 Worker 启动后的持久 Run reconcile；Worker、API、Orchestrator、catalog runner 和 source adapter 只能调用这些边界，不得自行选 Key、改 generation 或把来源级 `secret_env` 重新注入 Service 抓取。

切换是 generation barrier，不是请求级 token retry：池先进入 `draining` 并停止所有新 reservation，再中止旧 generation 下全部已登记的非终态 Run，并仅在确认 `SUCCEEDED/FAILED/ABORTED/TIMED-OUT` 后增加 generation、激活下一备用并由逻辑抓取创建全新 Run。30 秒未确认时保持 `apify_key_drain_pending`；Actor POST 结果未知或重启发现未登记 reservation 时保持 `blocked` 并要求人工核对，禁止猜测 runId、复用 dataset 或盲目换 Key。每个逻辑抓取对同一 Key 最多一次，全部不可用时只有 Apify outcome 失败或延后，其他来源继续执行。

额度快照最长使用 60 秒。只有 `remaining_included_credits_usd <= 0`、HTTP 402 或明确额度错误可标记 `depleted`，401/明确无效 Token 标记 `invalid`；普通 403、429、5xx 和网络错误不得污染整个 Key。周期恢复后的旧 Key经重新核验只追加到备用队尾，不抢占当前 active，也不恢复历史 Run。该能力由 `HORIZON_APIFY_KEY_POOL_ENABLED` 控制并默认关闭；关闭时 schema/状态可维护，但 Service 保留既有来源级凭证兼容路径。

### 3.7 Secret Boundary
Service DB 和 catalog 只保存环境变量名或 secret ref 元数据，不保存真实密钥或 Webhook URL。真实 AI/Apify 值与用户 write-only Webhook URL 由 `src/services/secret_store.py` 独占写入 Git/Docker 忽略的 `data/secrets.env`，必须原子替换且权限为 `0600`。API/Worker 可以热加载该文件，但 API、日志、job、Feed、outbox、DOM 和非管理员 source 投影不得返回真实值。Apify pool 表只引用 `secret_id/version` 和安全状态；活动、排空中或仍有非终态 Run 的成员不得轮换或删除，必须先走安全排空。`source_catalog.secret_env` 在池模式只保留回滚兼容，不参与读取、展示或新来源写入。

### 3.8 Job Boundary
长耗时抓取、source test 和用户 feed refresh 必须通过 job queue 表达。Web 请求只创建、取消、重试或查询 job；Worker 负责执行 job 并写入状态/result。Worker claim 在 `BEGIN IMMEDIATE` 中原子写入 `worker_id + claim_token + locked_until`；finalize、失败、续租必须带同一 claim guard。Worker 每 10 秒 heartbeat/续租，35 秒未更新视为 stale；过期 running job 会在下一次 claim 前回到 queued 或达到上限后 failed。SQLite MVP 不强杀正在执行的 Python 任务。

`src/services/response_schema.py` 独占上游与标准化响应结构摘要：adapter 在原始对象仍位于调用栈时立即转换为有界 `path + type`，只把摘要交给 Orchestrator；`safe_run_diagnostics()` 独占 `response_schemas` 的 Job 投影。共享获取命中只记录 `cached`，不得读取或复制旧 Job 的上游结构。原始响应值和结构诊断均不得进入 Feed snapshot 或 `user_content_items`。

Service API 的 SQLite 访问使用 ContextVar 隔离的请求级连接，并为每个 `/api/*` 请求创建和关闭连接；鉴权读取与路由处理必须处于同一请求边界。请求结束仍存在事务时必须回滚并返回 `database_transaction_leak`，避免 macOS Docker bind mount 下长连接停留在旧 WAL 视图而误判 Worker heartbeat 或任务状态。`/api/health/live` 不访问数据库，也不受该边界阻塞。

`user_feed_refresh` 的 `succeeded/partial` 结果必须把 schema-v2 payload 保存为当前用户 snapshot，同时 upsert 稳定内容并写入 `snapshot_id/item_count` 到 job result。snapshot、稳定 items 和 job 终态在同一短事务提交；过期 claim 无权提交。同一非空 job 最多一个 snapshot，同一 snapshot 内 article 唯一；terminal job 手动 retry 产生的新 run 原子替换该 job 的旧 snapshot 内容，但既有稳定 `effective_at` 不变。`/api/feed/latest|history|search` 只读取目标用户稳定索引并按 timeline 投影；compatibility-only archive 路由遵守上一节 legacy 边界，不能反向成为 Feed 依赖。

`source_fetch` 带 `source_id` 时属于用户作用域精准抓取，不走旧 `source_type:index` 单源刷新路径。Worker 执行后必须通过 `UserFeedStore` 保存当前用户 snapshot，并在 job result 中返回 source 和 snapshot 元数据。

所有 lifecycle mutation 必须与 schedule shutdown、queued-job invalidation 和无网络 Feed reconciliation 共处一个写事务。Worker 在网络前与 finalize 前复查同一 eligibility；失效中的 running claim 只能以 `cancelled/job_invalidated` 收口，不能写 Feed 或 Source Health。订阅名额 admission、任务 retry 与其 usage 计量也必须在 `BEGIN IMMEDIATE` 中原子提交。

### 3.8A Feed Schedule Boundary
`src/services/feed_schedule.py::FeedScheduleService` 是每用户自动刷新计划的唯一服务边界；`ServiceStore` 只提供 additive 表和 SQLite 事务，API 只做当前用户鉴权、参数校验与响应投影。schedule 缺 row 投影为默认关闭/6 小时，不允许为了读取状态隐式开启。

常驻 `horizon-worker` 在 claim 普通任务前调用 `FeedScheduleService.enqueue_due()`，主循环默认每 30 秒评估一次；该周期由 `HORIZON_SCHEDULE_POLL_SECONDS` 配置。到期读取、full-refresh 去重、配额 admission/usage、job 创建和 schedule 推进必须位于同一 `BEGIN IMMEDIATE` 写事务，保证两个 Worker/连接最多创建一个任务。自动 job 继续复用 `user_feed_refresh`、Feed v2 finalizer 和完整 `filtering.time_window_hours`，仅以 `reason=scheduled_service_refresh`、`priority=-10` 区分低优先级来源。

自动与手动全量刷新共享“每用户最多一个 queued/running”约束；active `source_fetch` 和 migration gate 延后 5 分钟，其他不可运行状态记录明确 skip reason 并推进到下一周期，避免热循环。关闭计划只取消 queued 的自动 job，不强杀 running job；`partial/failed` 不改变 enabled 状态。

静态 UI 每 30 秒低频读取当前用户 schedule，发现 active job 后复用 2 秒 job poll；terminal snapshot 由 watcher/poll 共享单次处理状态，只有 Feed 明确加载成功后才记为 handled，poll 失败时 watcher 必须可接管重试。所有 Feed/config/item-state/schedule 异步读取必须绑定当前 auth user 与 load generation；logout、unauthorized 或用户切换会失效旧 generation、清理 watcher/job timer 并阻止旧用户响应写入全局状态或重新渲染。

这条边界不得 import 或调用 `src/services/scheduler.py`、`HorizonOrchestrator.run()` 或 `LegacyPublisher`，不得新增 dispatcher 容器，也不得读取/修改 `data/site/*.json`、摘要、通知、Graph、Archive analytics 或推荐链路。`horizon-scheduler` 仍只服务 legacy 显式 profile。

### 3.8B Subscription Source Schedule Boundary

`src/services/source_schedule.py::SourceScheduleService` 是订阅级自动 `source_fetch` 的唯一调度边界。权威状态位于 additive `user_source_schedules`，以 `subscription_id` 隔离用户；缺 row 等同关闭。API 只能读写当前用户的订阅计划，静态 UI 不得自行创建定时器抓取外部来源。

现有 Worker 在用户 Feed schedule 之后、claim 普通任务之前评估到期 source schedule。到期检查、active job 去重、配额、job 创建和计划推进必须处于同一 `BEGIN IMMEDIATE` 事务；自动任务固定 `reason=scheduled_source_fetch`、`priority=-10`，并继续复用 catalog runner、结构化 run、Feed v2 finalizer、Source Health 和 claim guard。手动/自动单源任务共享“同一订阅最多一个 queued/running”；active 全量刷新会延后单源计划，参与该订阅的全量刷新也会推进下一周期。

关闭计划、停用订阅或 catalog source、用户降级为 viewer 时，只取消仍 queued 的自动单源任务，不强杀 running claim。该链路与用户 Feed schedule 共享同一个 Worker 和 30 秒 tick，不新增容器，不接触 legacy scheduler、全局静态 Feed、摘要、legacy 通知、Graph 或 Archive analytics。成功 Feed 的偏好来源 outbox 仍由 3.8C 独立判定。

### 3.8C Preferred-source Notification Boundary

`src/services/preferred_source_notifications.py::PreferredSourceNotificationService` 独占当前用户邮箱/Webhook 目的地设置、新文章差集判定、schema v9 outbox、用户级模拟测试和提交后调度。ServiceStore 只保存 write-safe setting metadata、订阅 opt-in/启用时间与不可回退 generation、Webhook 值的一致性摘要和 delivery 状态；Webhook URL 真实值只存在于 `SecretStore` 的用户专属环境变量，不能进入 SQLite、config JSON、Feed、Job、日志或 API 响应。设置 partial PATCH 必须在 SQLite 写锁内重读实时用户并合并，任何 SecretStore mutation 前再次确认 enabled/writable role；摘要与用户专属变量不匹配时配置、staging 和发送全部 fail closed，显式清空负责删除确定性变量下的 orphan 值。

`src/services/notification_email_transport.py::WorkspaceEmailTransportService` 独占 schema v10 工作区邮件发送配置、固定 Provider Registry、凭据绑定、管理员测试门禁和 MIME/SMTP 发送。QQ、网易、Gmail、Resend 与 Amazon SES 的 host/port/login 只由 Registry 派生，API 不接受自定义 host 或 TLS 模式；SES host 只能由经过格式约束的 Region 拼接。Owner/Admin mutation 在 SQLite 写锁内重读实时 actor；凭据只写确定性的工作区 SecretStore 变量，SQLite 只保存变量名与 SHA-256 摘要。API 测试与 Worker 必须复用同一发送方法，每次发送重新读取 SecretStore 并比较摘要，TLS 使用系统 CA、SSL/465 和 20 秒 timeout。

通知候选必须在 `FeedProductionService` 已生成 snapshot 后、`JobQueue.complete_job()` 的 claim-guarded 事务提交前通过局部 savepoint stage；它只接受相邻 snapshot 的稳定 article ID 新增、完整订阅 provenance、严格晚于用户与订阅启用水位的可解析 `published_at`，并跳过首份 snapshot、历史复用、reconcile、`personal_only`、source test、content repair 和失败任务。snapshot、Source Health、Job 或 claim 回滚时 outbox 同步回滚；通知 staging 自身失败只回滚该 savepoint，不得让已完成获取重跑。

外部邮箱/Webhook 只能在 Job 成功提交后由同一常驻 Worker 消费；不得在 finalizer 事务内联网，也不得调用 `LegacyPublisher`、legacy `EmailManager`/`WebhookNotifier` 或新增 dispatcher/scheduler 容器。同一用户/渠道/Job 最多 20 个 distinct article ID 及这些文章的全部 provenance ledger 在一次事务中 claim 为 `sending`，payload 按 article ID 去重后合并为一次外呼；外呼前必须复查用户、来源、订阅、设置、当前双启用水位和双 generation，同时要求可信的 delivery 创建时间和来源 `published_at` 均严格晚于该水位。generation 不受墙钟回拨影响，任何关闭后重开的旧 delivery 都必须安全终结。明确失败只写安全状态并保持 Feed/Job 成功，transport 结果未知的 `sending` 永不自动重放。工作区邮件 transport 不 ready 时 email 不进入 outbox，用户 opt-in 与 Feed 基线仍保留；恢复后只消费之后相邻快照中的严格新增内容，不补发暂停期间条目。transport 轮换、停用或删除把尚未开始的 email delivery 终结为 `notification_transport_changed`，已经 `sending` 的记录保持未知。停用用户在同一事务关闭账户通知并清除用户水位；停用 subscription、catalog source 或切到 `personal_only` 清除逐源 opt-in 与水位，重新启用不自动恢复。测试 API 发送明确模拟内容且不创建 delivery、不读取或推进内容基线、不触发抓取/AI，并分别使用用户级或工作区级 SQLite 原子 60 秒冷却限制并发滥用。

Webhook egress 只接受 SecretStore 当前保存的 credential-free HTTPS，并复用 `src/services/network_policy.py` 的公网解析和 IP pinning；它禁用环境代理、拒绝 redirect，以 bounded DNS、单地址单次 POST、5 秒 transport timeout 和 6 秒总 deadline 发送。请求只接受 identity encoding，响应正文不得读取或解压；非 identity 响应按已开始发送但结果未知处理。Service 邮箱只使用 schema v10 workspace transport 与其 SecretStore 凭据，不读取 `data/config.json.email` 或进程环境作为兜底。两种 transport 的上游正文、目的地和凭据均不得进入公开错误或日志。

### 3.9 Config Compatibility Boundary
`data/config.json` 暂时只承载 AI、过滤、workspace RSSHub Base URL、legacy Webhook、legacy SMTP transport metadata、标签库等兼容配置。多人 source 的权威状态从配置页迁移到 `source_catalog` 和 `user_subscriptions`；当前用户偏好来源通知位于 Service schema v9，工作区 Service 邮件 transport 位于 schema v10，真实值分别进入 SecretStore，不复用 legacy Webhook/SMTP 配置。RSSHub Base URL 是可切换的非密钥 runtime URL，可含安全 path prefix，但不得复制进 catalog config、MCP/Agent 输出或 Feed；可选 `RSSHUB_ACCESS_KEY` 只存在 SecretStore，Worker 只派生 route-scoped access code。VPS-only `RSSHUB_BILIBILI_ANONYMOUS_COOKIE` 也只能进入 SecretStore 和 RSSHub 容器环境，且必须由隔离的无 profile 浏览器 context 从公开页面生成，禁止复用账号 Cookie。兼容层可以把 service 状态投影成旧 `config.sources.*` 结构供静态 JS 渲染，但不得把真实密钥或同步抓取副作用带回 Web 请求。

全局非 source 配置只允许 `owner/admin` 修改；`member/viewer` 不得借兼容 facade 改写 AI、过滤、标签或 Webhook。member source action 的 topics/personal tags 只写 source/subscription；任何管理员全局标签写入也必须在 catalog/subscription 成功后执行。旧配置批量导入只能更新 scope/owner/type 兼容的 source，另一用户 private key 碰撞必须跳过。SQLite 连接必须统一开启 foreign keys 和 busy timeout；native/Linux 默认使用 WAL，但 macOS Docker bind mount 的 light Compose 必须让 API/Worker 同时使用 DELETE journal，避免跨容器 WAL 共享内存可见性漂移。journal mode 只能由 `HORIZON_SQLITE_JOURNAL_MODE=WAL|DELETE` 选择。API 连接按 ContextVar 请求作用域隔离，禁止跨并发请求共享。

member 控制的 direct catalog RSS URL 不得包含环境变量占位或 URL userinfo；Worker 必须以 catalog row 而非 job payload 为权威。初始请求和每次 redirect 都必须解析并审核全部地址，随后只连接本次审核通过的字面 IP并保留原 Host/SNI；安全请求使用隔离且 `trust_env=False` 的连接、拒绝压缩响应并执行 2 MB 流式上限。受控 RSSHub row 是单独边界：成员只能提供 allowlisted `site/route_key/params`，运行 origin 只来自管理员配置，Worker 禁止跟随 redirect。除此之外，`owner/admin` 拥有的 source 仍是本地/私网任意 RSS URL 的唯一显式信任边界。

### 3.10 Runtime / Migration Boundary
默认部署单元是独立 `horizon-api + horizon-worker`；用户 Feed schedule 内嵌在现有 Worker，不形成第三个默认进程或容器。旧 scheduler 永远位于显式 `scheduler` profile，也不参与 Service Feed 调度。旧 snapshot 到 Feed v2 的清空重建只能由 `scripts/migrate_user_feed_v2.py --apply` 在服务停止后显式执行，应用启动不得自动删除用户数据；未完成迁移时 readiness 和 Feed Worker 都必须拒绝继续。迁移工具已存在不表示真实数据库已执行迁移。

Feed storage v3 使用 `scripts/migrate_feed_storage_v3.py --dry-run|--apply`。apply 前必须停止 Worker；工具以 SQLite backup API 创建 UTC 命名、权限 `0600` 的独立副本，additive 初始化/backfill content hash，执行 retention，并通过 `integrity_check` 与 `foreign_key_check` 后才记录 version 3。Worker maintenance 以持久化小时门禁执行相同 retention，且无论时间/数量阈值都保留每用户/每 acquisition key 最新必要记录。

Content timeline v11 使用 `scripts/migrate_content_timeline_v11.py --dry-run|--apply`。apply 前同样停止 Worker并创建独立备份；迁移以首次入库时间作为缺失/非法/异常未来发布时间的稳定回退，回填用户隔离的 `effective_at/search_text`，重建 FTS5 索引并在 integrity/foreign-key 全部通过后记录 version 11。API readiness 与存储治理在存在待回填行时必须 fail closed，不得靠重新抓取修复时间边界。

生产镜像不得包含 `.env`、`service.db*`、`data/config.json`、日志或备份；运行数据只能通过 VPS shared volume 注入。API 与 Worker 必须运行同一版本化镜像，liveness 暴露 revision。Inteliscope production image 必须从干净、revision-locked commit 在本机以 `linux/amd64` 构建并验收，压缩归档经校验上传后只在 VPS 执行 `docker load`；禁止在 `vps-tokyo` 对本仓库执行 Docker build。RSSHub 作为单独的 VPS-only 容器加入生产 Compose 网络并只绑定 VPS loopback；VPS 项目使用容器 DNS，本地项目经现有 Nginx 的 HTTPS path prefix 复用同一实例，不使用 SSH tunnel，也不在本地启动第二套 RSSHub。公网入口必须启用 RSSHub `ACCESS_KEY`、关闭该 location 的 access log 并保持容器端口不直接暴露；固定摘要的 `chromium-bundled` 镜像必须显式使用已验证的容器内 Chromium 路径和 RSSHub 非随机 UA，匿名 Bilibili Cookie 只能通过受控刷新脚本写入 SecretStore。匿名参数不构成 Bilibili 可用性保证；连续冷路由出现上游 `-352` 时必须停止高频探测，等待上游窗口恢复或切换第三方实例显式降级。RSSHub 这类 pinned third-party runtime image 可以在 VPS 直接 pull。RC1 数据迁移只能使用 SQLite backup API 生成独立副本，副本清除 session、heartbeat 和 active job 后再验证 Feed v2、integrity 与 foreign keys；源码发布包必须来自同一干净 commit 的 `git archive`，VPS 采用 API-only staging、显式 promote 和 Worker-first rollback。

### 3.11 Content Repair Boundary

`scripts/repair_user_content_v5.py` 是历史内容 inspect/apply/reconcile/enqueue 的唯一维护入口，`src/services/content_repair.py` 是 Worker `content_repair` 的唯一执行边界。repair 可以复用现有 source adapter、公共网络策略和媒体缓存，但必须强制 AI disabled，只匹配 `user_content_items` 已有 article id，并禁止调用 `FeedProductionService`。因此它不创建或替换 snapshot、不更新 Feed latest/history、不接触新文章，也不评估 schedule。

v5 apply 负责备份、旧 snapshot 线索恢复、模型无关 input hash 与 unresolved reason；reconcile 是旧 `NOT NULL` reason schema 与 captured 状态冲突的唯一显式升级入口，必须在无 active Job/Worker 时备份后事务执行。运行时存储层只维持“非空 captured 正文不保留 `source_body_not_available`”的不变量，不自动重建旧表。免费来源后续通过一次性 Worker 重抓。Apify social 被视为付费边界，批量工具必须 fail closed。详情 GET 永不联网，无法恢复的正文或过期媒体保留降级原因。

### 3.12 DeepSeek Analysis Boundary

DeepSeek 继续复用 OpenAI-compatible client，缺省 Base URL 和 Key env 归 AI client 所有；Secret API 只保存 ref metadata，真实值归 `SecretStore`。`UserAnalysisCache` 先查当前模型，再查同用户/同输入哈希的安全历史投影；跨模型命中只应用安全分析字段并保留来源标识，不写当前模型 cache。`user_content_items.analysis_input_hash` 由原始 `ContentItem` 计算，历史正文修复本身不触发分析。

本地切换必须先保持 AI disabled，使用轮换后的新 Key 执行一次 retry=0 smoke：同一事件循环先调用零推理 Token 的 `models.list()`，确认精确模型后才允许一次 completion；该请求省略 `temperature` 并关闭 SDK 与应用层参数降级重试，首次失败即终止；任一预检失败都保持 completion=0。成功后才启用 DeepSeek。默认本地拓扑仍为 API + Worker；legacy scheduler 与 VPS Tokyo Worker 不因该切换获得启动授权。

## 4. 禁止事项
1. 禁止入口层直接访问外部系统细节。
2. 禁止输出层反向驱动领域模型。
3. 禁止规则散落在路由、命令入口或模板中。
4. 禁止把某个运行时来源的字段命名作为全系统标准命名。
5. 禁止在 Web UI JS 中重新实现 Python taxonomy 规则。
6. 禁止把成本型流程作为 light runtime 的默认副作用。
7. 禁止静态 UI 直接读取 `radar-data.json`、`history-data.json`、`article-graph.json` 或依赖 `data/config.json` 源列表文件结构。
8. 禁止默认 Service UI 调用 archive analytics、source-quality、Graph 或 feedback compatibility routes。
9. 禁止用 legacy scheduler、第三个 dispatcher、摘要/legacy 通知或静态 publisher 承担用户 Feed schedule；偏好来源通知只能消费 3.8C 的提交后 outbox。
10. 禁止 Remote MCP 复用 legacy MCP 工具注册、接受客户端指定的 user/workspace，或运行任何服务器侧 Agent/模型。

## 5. 扩展原则
新增来源、规则、输出或存储时，应先扩展抽象合同，再实现具体适配。

具体要求：

1. 新 source adapter：更新 source config model、adapter、tests，必要时更新 `API_CONTRACT.md` 和 `project-defaults.yaml`。
2. 新 taxonomy 字段：先更新 `tag_policy.py`、`ContentItem` 和 Service snapshot contract；只有影响 legacy compatibility 时才同步 static/archive contract，再更新 UI。
3. 新输出面：先定义 static JSON 或 API contract，再做 UI。
4. 新成本型能力：必须有配置开关、低成本验证路径和 degrade 行为。
