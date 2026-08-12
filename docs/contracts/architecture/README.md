<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/architecture/ -->
# Inteliscope InfoHub Light 架构合同

## 0. 任务读取路由

先读本索引了解默认分层、来源/AI/前端边界；再按责任边界进入模块。


## 1. 文档目的
本文件定义系统职责分层和不可跨越的边界。代码实现应优先遵循现有模块形状，只有在边界变化时才更新本文件。

## 2. 默认分层
当前默认分层：

1. API / event 入口层：`src/api/server.py` 作为 composition root，`src/api/context.py` 提供 typed request-independent 依赖，system/auth、member administration、Feed/read-media、schedule、storage governance、queued-job 与 Agent delegation HTTP 适配分别归 `src/api/system_auth.py`、`src/api/user_routes.py`、`src/api/feed_routes.py`、`src/api/schedule_routes.py`、`src/api/storage_routes.py`、`src/api/job_routes.py`、`src/api/agent_delegation_routes.py`；Worker 入口保留在 `src/services/worker.py`，claim 前周期编排、Actor 周期维护和提交后分发/终态遥测分别归 `src/services/worker_cycle.py`、`src/services/worker_actor_cycle.py` 与 `src/services/worker_post_commit.py`，Remote MCP HTTP 与 Worker job handler 同属入口层。这里只负责参数接收、认证、校验和薄编排，领域服务与事务语义不得搬进入口模块。
2. Service 层：`src/orchestrator.py`, `src/services/**`。负责抓取、去重、可选分析、用户 Feed finalization、读取与留存；配置运行时、来源探测、Feed payload/read 都归中性 Service 模块。
3. Domain 层：`src/models.py`, `src/tag_policy.py`。负责标准模型、taxonomy、source ref、状态和规则输入输出。
4. Adapter / Integration 层：`src/scrapers/**`, `src/ai/**` 与当前 notification/OpenBB/Apify client。隔离外部系统字段、协议和失败模式。
5. Storage 层：Service 状态与用户 Feed 位于 `data/service.db`，当前冷归档位于受治理的 `data/archives/**`。`data/site/**`、`data/horizon.db`、旧摘要和本地 MCP run 是 inert operator-owned artifact，任何运行路径都不得读写、迁移或删除。
6. Presentation 层：`src/services/feed_payload.py` 生成 wire payload，`frontend/` 负责 React 展示；两者均不直接采集数据或访问旧文件产物。

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

来源摘录清洗、字段缺省、枚举、长度上限和 `reason` 禁止规则以 `docs/contracts/api/` 为唯一 wire 真源。确定性字段先由代码提取，AI 只处理代码无法可靠推断的语义字段，以降低 token 和跨来源格式漂移。

稳定详情归 `src/services/user_content_store.py` 所有：每次 Feed finalize 将规范列表 item 写入 `user_content_items`，再把抓取器已有正文清洗为最多 20,000 字的 captured body。详情投影升级为 Presentation v2；旧 snapshot 回填只能是 `excerpt_only`。`src/services/media_cache.py` 在 Worker 内经公共网络地址固定策略下载最多 6 张内容图和一个来源头像，分别验证真实图片类型、内容图 8 MiB/头像 2 MiB 上限并原子落盘；第三方临时媒体 URL 不得进入 snapshot 或稳定索引，浏览器只能通过登录保护的 `/api/media/*` 访问。合成 DNS 例外仅允许 Instagram 既有 CDN 与精确后缀 `pbs.twimg.com`；头像身份忽略 query/fragment，身份变化即时验证候选，同身份最多每 24 小时复验 checksum，候选失败必须保留旧 ready 版本。

来源头像证据归 scraper 的内部 `SourceAvatarHint` 与 `src/services/source_avatar.py` 所有，不属于 `ContentItem` 选择结果：RSS Feed 元数据和 Apify profile row 必须在时间窗口过滤之前采集，GitHub 可由已验证 owner/user 确定候选，Worker 与单源 runner 即使最终选中 0 条内容也先处理头像再 finalization。缺失头像只允许使用免费且身份有界的回退：Bilibili 搜索结果必须精确匹配已保存 UID，Reddit 必须匹配 about identity，通用 RSS 最多读取有界 Feed 与主页 favicon；Apify 社交来源不得为回填额外启动付费 Actor。头像失败不改变 Feed/Source Job 状态，不写 Source Health，不创建 snapshot、通知或 AI 调用。

### 3.4 Service Frontend Boundary
默认 Service UI 位于 `frontend/`，由 React + TypeScript 构建到独立 `src/ui/service_static` 产物，只通过 `/api/*` 消费数据；不得直接调用 scraper、AI client 或 storage，也不依赖 `data/site/*.json` 或 `data/config.json` 源列表的内部文件结构。应用外壳、Feed、收藏与历史属于认证后的首屏主链路；登录页、Settings 外壳、OpenClaw 对话视图以及订阅、Agent、设置子页、用户、手册与更新日志必须保持按需动态加载。OpenClaw 的连接与运行 Hook 继续常驻应用外壳，打开对话视图不得重置后台运行、重连或终态提醒。生产构建检查首屏 JavaScript Brotli 合计不超过 240 KiB。阅读、收藏与历史只调用 `/api/feed/*`；条目提供站内查看已抓正文/图片、打开原文、显式已读/未读、复制摘要、收藏、稍后读和忽略，不提供网页全文代理/iframe、偏好 feedback 或 Graph。订阅控制台通过 catalog、subscriptions、jobs、schedule、source-health 和 users API 管理信息获取，并通过 subscription 字段逐源选择新内容通知；首页“获取新内容”创建 `user_feed_refresh`，不得退化为只重新 GET snapshot。`/settings/*` 由独立 Settings Workspace 外壳承载，导航与 UI primitives 分别归 `frontend/src/features/settings/` 和 `frontend/src/components/settings/`；原生页面为 Overview、Appearance、Notifications、AI、fetching/topic、ignored-content、secrets、ActorOps 与 storage/archive。AI payload/diff 纯函数归 `settingsAiModel.ts`，获取 payload/diff/主题规范化归 `settingsFetchingModel.ts`，密钥校验、状态展示和错误映射归 `settingsSecretsModel.ts`。`/settings/fetching` 独占 config Query 与 `set_settings_bundle` mutation；`/settings/actorops` 仅组合既有 ActorOps route、alert 与 incident Query/mutation，控制面业务实现继续归 `frontend/src/features/apify-actors/`；ActorOps 的付费审批、CAS、Query/mutation 和真实目标继续由控制器持有，确认对话框只消费剔除内部标识的展示投影并回调语义动作。`/settings/storage` 独占现有 storage summary/archive Query 与 preview/apply mutation。原生页只重组视图，不复制业务逻辑；`/settings/legacy` 只作历史链接重定向，不保留 Settings 业务 UI。原生密钥页独占 SecretStore、额度与 Apify Key 池的前端查询/mutation 所有权。

React Query 的所有用户数据 key 必须包含当前 `user_id`；logout、401 或身份切换必须先取消旧请求并删除旧用户缓存。Vite 的 hashed `/assets/*` 可 immutable cache，`index.html` 必须 no-cache；BrowserRouter 深链接由 FastAPI 回退到 React index。React 是唯一 UI；构建产物缺失时 API 与 Remote MCP 仍可启动，非 API/MCP 页面统一 404，不存在环境开关或旧静态 UI fallback。

React 视觉系统、组件所有权、响应式布局和视觉验收以 `docs/contracts/ui/` 为唯一真源。HeroUI provider、设计 token 与通用语义组件归 `frontend/src/design-system/**` 所有；Settings 专用组合 primitives 归 `frontend/src/components/settings/**`，Feature 层不得绕过这些边界私造 palette、shape、shadow 或受控交互组件。Feed 列表优先消费 API 的 `presentation.version=1`，按需详情优先消费 `presentation.version=2`；旧 flat 字段只作为一个兼容周期的缺失兜底；React 不显示或搜索 legacy `reason`。当前迁移覆盖 App Shell、共享 Feed workspace、订阅/来源 workspace 与独立 Settings Workspace；legacy settings bridge 只保留历史 URL 重定向。

Service UI 在小团体服务模式下必须先完成登录门禁，再加载用户 Feed 或控制台 API。未登录时只显示登录界面，不展示信息流、历史、订阅或配置内容。

## 模块索引

| 任务 | 模块 |
| --- | --- |
| Feed、冷归档、存储与租户/用户隔离 | [Feed、存储与租户](feed-storage-tenancy.md) |
| OpenClaw、MCP、日志、Key pool 与 ActorOps | [Agent、可观测性与 ActorOps](agent-observability-actorops.md) |
| Job、周期、通知、运行时、迁移、repair 与 AI | [Job、通知、运行时与迁移](jobs-notifications-runtime-migrations.md) |
