<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 实施计划

## 1. 计划目的
本文件定义当前阶段、实施顺序和默认验证策略。后续 agent 应以本文件作为开发入口之一，但不得用它覆盖更细的 API、架构、上下文和决策合同。

<!-- init-pro:section name=phase -->
## 2. 当前阶段状态
结论：当前主线仅为“小团体多人的信息获取 + Feed 留存”。本地已完成 Feed 一次性通知、认证异步反馈、user content v5 备份/apply、免费来源修复与显式 reconcile：26 条历史内容当前为 24 条 captured、2 条 excerpt-only，冲突的 `source_body_not_available` 及旧 NOT NULL schema 遗留的 23 个空字符串占位已在 `0600` 备份后规范化为 nullable reason（23 条 `NULL`、1 条保留 `media_cache_failed:2`）；snapshot、Job、媒体和 AI usage 未变化。全局 AI 目标已预置为 `deepseek-v4-flash` 但保持 disabled，对话中旧 Key 视为泄露，必须由用户写入轮换 Key 并通过零 Token 模型预检与一次 retry=0 completion 后才能启用。公共源共享获取与 Feed storage v3 的两个 rollout flag 继续默认关闭。`vps-tokyo` 仍运行既有 API-only 版本，Worker 与 scheduler 没有新的启动或部署授权。低 Token `test_gate` 仍处于 0/10 提交观察期，完成门禁保持 wrapper `full`。

前端当前已完成 HeroUI 全站生产切换；视觉、响应式和浏览器验收只以 `UI_CONTRACT.md` 为真源，旧 MUI/Emotion 双栈不再存在。该切换不改变上述运行、发布或数据授权状态。

已完成：

1. 默认 runtime 固定启动独立 API + Worker，scheduler 仅在显式 profile 中启用。
2. No-AI / personal-only 成本护栏。
3. Hub taxonomy 基础：`channel/topics/signal_strength/signal_type/entities`，并保留 `category/tags` 兼容。
4. 静态阅读 UI 的频道优先筛选。
5. `ArticleStore` 对 Hub taxonomy 字段的归档落库。
6. init-pro 控制面初始化。
7. FastAPI service API 入口、Service SQLite 库、单 workspace 用户体系、公共/私有订阅源市场、用户订阅配置、SQLite job queue、配额记录、Feed API 与 compatibility-only archive facade。
8. 配置页 Service API 兼容层：`/api/config` 投影 service catalog/subscriptions 为旧 UI 结构，source action 写入 service tables，测试/更新按钮创建 queued jobs。
9. 登录后的订阅控制台 MVP：公共源市场、我的订阅、私有 RSS 源创建、任务队列和手动刷新入口。
10. Worker/job queue 加固：SQLite lease、stale running 恢复、失败重试退避、取消、重试和任务保留清理。
11. 用户作用域 Feed 与历史留存 API v1：`user_feed_snapshots/user_feed_items`、`/api/feed/latest`、`/api/feed/history`、管理员 `user_id` 排查和订阅页 API 状态面板。
12. Source Catalog API v1：`source_type_registry`、`source_key` 幂等导入、catalog config 校验、旧 `data/config.json` 高级源导入和订阅页高级源最小测试面板。
13. 真实源验证 v1：catalog `source_fetch` 按 `source_id` 精准合成用户作用域单源配置，Worker 保存用户 feed snapshot，并提供 RSS/Hacker News/GitHub Releases/Telegram 的 Service API smoke 脚本。
14. 基本行为状态 v1：当前用户 Feed item 的已读、收藏、稍后读和忽略入库；默认阅读 UI 保留打开原文、标记已读、复制摘要、收藏、稍后读和忽略。旧 feedback API/表仅兼容保留，不进入默认 UI。
15. 核心 Service API 验收与权限矩阵 v1：统一 `/api/*` validation/404 error envelope，补齐角色权限矩阵测试，并新增无外网依赖的核心 API smoke 脚本和 curl 文档。
16. Docker 组合 Smoke 与本地验收固化 v1：一条命令启动 Docker API、等待 health、运行核心 API smoke，并可显式追加真实源 smoke 与 worker 验收，输出统一汇总报告。
17. 静态 UI 最小可用闭环 v1：登录、订阅、阅读页统一走 `/api/*`，补齐 viewer 只读提示、job 错误显示、UI smoke 和浏览器验收清单。
18. 用户行为信号轻量阅读体验 v1：`/api/feed/latest` 支持当前用户 state 过滤/排序，dashboard 返回 item state 计数，静态阅读页提供隐藏已忽略和未读优先开关。
19. 成员管理最小控制台 v1：管理员可在订阅控制台查看、创建、启用/禁用、调整角色和重置成员密码；普通成员和 viewer 不展示管理入口。
20. 结构化产出核心 v2：`FeedRunResult/SourceOutcome/RunIssue`、来源级明确失败、`partial` 终态和 Service 链路无全局静态文件副作用。
21. 用户 Feed finalizer v2：全量刷新替换/保留/删除语义、单源合并、`personal_only` 护栏、schema-v2 canonical `items` 和 job 幂等 snapshot。
22. Queue/Worker 可靠性 v2：原子 claim token、guarded finalize、heartbeat/续租、stale 拒绝、snapshot/items/job 同事务和 SQLite 每线程 connection。
23. 运行/UI 闭环 v2：live/ready/ops、默认 API + Worker、2 秒任务轮询、刷新恢复、Worker missing/stale 提示和自动 Feed 加载。
24. Feed v2 显式迁移与真实库验收：工具支持备份、活跃 heartbeat 安全拒绝、旧用户 Feed/状态/反馈清理、唯一索引、migration record 和外键检查；2026-07-11 已在真实部署数据库完成显式迁移。
25. Feed 历史留存响应 v2：已实现 `API_CONTRACT.md` 定义的 history v2 响应与留存语义。
26. 默认 UI 范围收口：删除 Graph、站内原文预览和偏好反馈按钮；订阅控制台不调用 archive/source-quality。
27. 发布运行验收：Docker 默认仅运行 API + Worker；管理员刷新任务完成 `queued → running → succeeded` 并生成 22 个 items，浏览器入口清理与历史空态通过。
28. Service 自动获取与 Feed 新鲜度 v1 代码：additive `user_feed_schedules`、手动/自动 full-refresh 原子去重和配额、Worker 30 秒到期检查、schedule API/ops 投影、订阅页控制卡、首页真实获取任务、显式已读和 DOM 行为测试；未新增 dispatcher，也未启用 legacy scheduler。
29. Service 自动获取与 Feed 新鲜度 v1 发布验收：light Compose 只运行 API + Worker，live/ready 200，heartbeat/overdue/stale/queue 门槛通过；管理员两个真实 Worker 自动周期各成功产出 21 条并各生成一个 snapshot，周期已切回 6 小时；浏览器 UI、常驻页面 schedule watcher、viewer 降级防护和两用户两周期隔离 E2E 通过，最终 551 项 pytest 通过。
30. Source Health v1 代码与独立审查：用户订阅级 `unknown/healthy/degraded/failing`、生产 outcome 原子落库、最终失败语义、API/ops 安全投影、脱敏与订阅页诊断闭环均已实现；代码完成检查点为 603 项 pytest、35 项 Node 行为测试，三项独立审查最终均通过。
31. Source Health v1 真实运行验收：默认只运行 API + Worker，live/ready 正常；4 条订阅刷新前均为 `unknown`，一次真实 `user_feed_refresh` 成功产出 25 条，刷新后 4 条均为 `healthy`，SQLite integrity 与 foreign-key 检查无错误。该证据不包含浏览器人工验收。
32. Acquisition Loop v1 后端实现与 focused verification：8 种 source type 的九键字段元数据、source/subscription PATCH 清空语义、priority `0..100`、config/secret 变化的健康重置、priority 全链路与四键排序、safe refresh diagnostics 和 final failed `result_json` 已完成；Task 1 为 106 项 focused tests 并经复审通过，Task 2 为 117 项相关回归并经独立审查通过。
33. Acquisition Loop v1 静态 UI implementation：全局 Feed activity banner、registry 驱动的 source/subscription editor、测试预览、来源健康筛选与 save/test/refetch 已完成；独立审查发现的跨用户异步响应、当前用户任务恢复和最近任务提升问题均由 RED 测试覆盖并修复，当前 45 项订阅 Node 行为测试与完整 pytest 通过。
34. RC1 本地发布护栏：Service Cookie 使用环境 TTL/Secure 配置，liveness 暴露不可变构建身份，生产镜像不复制运行数据，API/Worker 共用版本化镜像；新增脱敏 SQLite deployment artifact 和 `prepare/promote/rollback/status` 分阶段 VPS 发布工具。该项只表示本地代码与测试已就绪，不表示 VPS 已切换。
35. 本地 AI/Key/订阅 v1：`SecretStore + secret_refs` 管理 write-only AI/Apify Key；Gemini 单篇输入、输出 token 和 200 字概括均有硬限制及失败回退；本地 Smoke 数据已重建为 Apple、OpenAI、Claude Code 和 X 四个正式订阅。
36. 订阅级自动抓取 v1：additive `user_source_schedules`、原子到期入队、手动/自动/全量刷新竞争保护、API/ops/UI 和角色降级防护已完成。X `@thsottiaux` 已改用 `apidojo/twitter-scraper-lite` 和备用 Key，上游严格传递 `maxItems=1`，真实直连运行成功且无 100 条最小限制；X 计划为 30 分钟，整份 Feed 仍为 6 小时。
37. React 三栏 Service UI v1：React 19 + TypeScript strict + Vite + TanStack Query + BrowserRouter 工程已建立；默认路由、三栏 Feed/稍后读/历史、任务轮询、订阅健康与 registry 表单、管理员配置/成员/write-only Key、响应式布局和 legacy UI 回滚开关均已接通现有 API。
38. Material UI Shell 与 Feed v1（历史阶段，已由第 48 项 HeroUI 生产切换取代）：该阶段曾建立视觉契约、受控导出层与自动化门禁；其 MUI/Emotion 实现不再属于当前源码或依赖。
39. Content Presentation v1：8 种 catalog 类型、11 种内容形态统一投影为来源/作者/时间/双链接/内容类型/正文片段/taxonomy/互动量/分析状态；确定性字段不调用 AI，中文概括继续硬限制，删除“为什么值得关注”，新增用户隔离分析缓存、运行 usage 诊断和无 AI/无 DB 写的真实来源 contract smoke。
40. 订阅管理与阅读详情收口 v1：订阅和来源按有效频道分组并支持搜索、类型、健康和范围筛选；频道使用后端候选 Select，主题使用可自定义多选与停用标记；来源卡提供 Worker 预检的单源立即获取；设置页改为非破坏主题 Chip 管理；阅读详情直接显示安全正文片段，并停止新生成和展示 `action_suggestion`。
41. 公共源共享获取与 Feed 正确性 P0–P2：生命周期失效、schedule shutdown、queued job 取消与 Feed reconciliation 已原子化；停用源仍可管理/退订；订阅、任务和上游 attempt 配额并发安全，fetch/AI 每次真实调用前复查当前任务与来源资格；public/workspace 中性内容池、private 隔离、canonical merge、no-op snapshot、compact 双读、精确 AI prompt fingerprint、v3 迁移门禁与 retention 已实现。共享获取和 compact writer 均保持关闭，真实库只读副本 dry-run 显示 49 个 snapshot/hash 待迁移。
42. VPS API-only 发布：当前工作区以版本化镜像 `inteliscope-service:api-20260714T110652Z-d0c8905-wt2e4cb2ea` 发布，18080 staging 与 8080 promote 的 live/ready/root 均通过；ready 明确返回 `worker_status=missing`，数据库 integrity/foreign keys 正常，session/heartbeat/active job 均为 0。旧容器、旧镜像、旧网络和旧源码已删除，回滚备份保留；共享获取与 compact writer 继续为 false。
43. 低 Token 分层测试门禁 v1：`scripts/test_gate.py` 提供 snapshot/plan/targeted/full/release，`tests/test_impact_map.json` 负责确定性映射，完整日志私有落盘并只输出 2 KiB 成功或 8 KiB 首失败摘要；PR/main 并行跑 full backend/frontend，UI 改动追加 Playwright，正式发布追加隔离的 API-only Docker smoke。
43. 收藏、站内阅读与社交媒体完整性 v1：additive `user_content_items/media_assets`、Presentation v2 详情、用户隔离收藏/媒体 API、显式已读/未读、按用户持久化 Feed 偏好、RSS/Instagram/X 图片和统一头像缓存、社交 profile 最新一条保留、Xquik adapter 与 v4 显式迁移已实现。Xquik 真实 canary 尚未通过：当前备用 Key 所在 FREE tier 单条价格为 `$0.015`，因此计划固定的 `$0.01` 运行上限被 Apify 拒绝；正式 X Actor 配置仍保持旧值，等待明确授权把 canary cap 提升到至少 `$0.02`。
44. Feed 事件、历史修复与 DeepSeek v1：Feed terminal 通知只消费当前会话观察到的真实 snapshot 事件；认证动作按 user/action/entity 提供局部状态；v5 显式修复、reconcile 和 `content_repair` 保持零 snapshot/AI，当前内容为 24 captured/2 excerpt-only；DeepSeek Secret/UI、`deepseek-v4-flash`、模型无关 input hash、安全跨模型复用、零 Token 预检与单次 smoke 已实现。真实 DeepSeek 启用仍等待轮换 Key。
45. OpenClaw Remote MCP subscription management v1：本地实现已完成 14 个工具（10 个安全读、3 个 prepare、1 个 apply）、additive v6/v7 结构、显式 read/write delegation、共享 mutation service、`/agents` capability/tool-filter UI、本地 Skill、只读 canary 与 API-only 发布 Runbook；read/write flags 默认关闭。100-call 性能基准已通过；真实 OpenClaw canary、API-only staging、TLS `/mcp`、吊销立即 401 与两用户隔离仍是发布前人工边界，生产只能先保持写 flag 关闭。
46. Codex-inspired Next Web 工作台视觉原型（历史阶段，已由第 48 项完成生产化）：开发专用无认证原型曾验证暗色层级、精简导航、旧上新下卡片流、短刻度、新内容提示和最多 8 条 OpenClaw 上下文交接。
47. HeroUI v3 独立候选原型：开发专用 `/__preview/workbench-heroui` 使用 HeroUI v3/Tailwind v4；三档响应式、Axe、焦点归还及生产构建剔除已建立。候选已被第 48 项选为生产体系，固定数据预览继续作为开发验收面。
48. HeroUI 全站生产切换：`AppBootstrap` 的单一 HeroUI provider、Feed/saved/history 工作台、subscriptions/agents/settings、独立 login、`/later → /saved` 替换、MUI/Emotion/旧 UI 层删除、静态契约和三视口 Playwright/Axe 已完成。当前视觉与交互规则只见 `UI_CONTRACT.md`；API、权限、Query key、Remote MCP 和运行边界均未改变。
49. Quiet Studio Feed 视觉确认批次：`/feed` 实现、三视口生产自动化、revision-locked 本地 API/Worker 运行及 `/feed`、`/saved`、`/history` 应用内浏览器复核均已完成；权威规则只见 `UI_CONTRACT.md`，设计规格见 `docs/superpowers/specs/2026-07-18-feed-quiet-studio-design.md`，实施证据见 `WORKLOG.md`。
50. Codex 式信息工作台细节批次：在 Quiet Studio 上完成分类导航、常用视图、账户菜单、Feed 最新优先/可切换顺序、重复摘要抑制和 OpenClaw 单体交接编辑器；权威规则只见 `UI_CONTRACT.md`，设计规格与实施计划分别见 `docs/superpowers/specs/2026-07-18-codex-navigation-feed-details-design.md` 和 `docs/superpowers/plans/2026-07-18-codex-navigation-feed-details.md`，实施证据见 `WORKLOG.md`。
51. Quiet Studio 全站统一：阅读、管理和认证页面使用设计系统拥有的共享页面模式；收藏/历史删除 collection 进度轨并复用阅读卡片；管理路由只保留唯一标题；OpenClaw 响应式容器复用统一交接编辑器。权威视觉与交互规则只见 `UI_CONTRACT.md`，实施证据见 `WORKLOG.md`。
52. 用户自有 OpenClaw 对话接入：浏览器直连 Gateway v4、Ed25519 设备配对、按 Inteliscope 用户/Gateway URL 隔离凭证、流式/停止/重连/工具发现和最多 8 篇文章 ID 上下文已本地实现；`get_item` 支持最多 20,000 字符分段读取。功能默认关闭，生产订阅写开关保持关闭，真实 Chromium/OpenClaw 与 API-only staging 验收仍是发布前边界。
53. Quiet Studio × OpenClaw 本地 RC：从 `4445df1` 创建独立 `feature/quiet-studio-openclaw-rc` worktree，以非 squash merge 保留两条来源分支历史；HeroUI 助手连接页已接入 read/subscriptions_write delegation，测试环境不再隐式依赖忽略的 `data/config.json`。revision-locked 镜像通过数据库副本 v7、full/release gate 与本机 8080 切换验证；`main` 与 VPS 均未改变。
54. 来源优先信息流与可读 Agent 上下文：社交卡片按平台、关注对象/作者和来源表达且正文只显示一次；侧栏导航统一交互；Agent 草稿保存安全展示记录并对历史 ID-only 草稿按用户查询详情，界面不显示内部 article ID。
55. Feed Insights 与 OpenClaw 运行时一致性：Feed 增加浏览器本地自然日“当天”视图和复用既有查询的宽屏信息概览；右栏统一为 closed/insights/agent；OpenClaw 模型通过可验证分支会话切换、推理随请求发送；媒体缓存与详情按 checksum 去重。权威交互与数据规则见 `UI_CONTRACT.md`、`API_CONTRACT.md` 和 D042。

当前仍需推进：

1. 停止 API/Worker 后，对目标数据库再次 dry-run，使用 UTC `0600` backup 显式 apply Feed storage v3；成功验收 marker、hash backfill、integrity 和 foreign keys 后，才允许打开 compact writer。
2. 只对非付费公共源打开 shared acquisition，观察两个自然周期的 cache hit/miss、upstream attempt、Feed 用户隔离和 Source Health；通过后再扩大范围。
3. 付费来源只有在 operator 再次明确授权且上游 `maxItems=1` 时才可纳入共享获取 canary；本次实施没有进行任何付费真实调用。
4. X 已改用 Apify Secondary 和支持精确 `maxItems=1` 的 Actor；真实直连运行成功但本次返回 0 条。VPS Worker 按用户要求保持停止；只有再次明确授权后才允许启动，并只观察一个 30 分钟自然周期的任务、计费和 Feed 合并结果。
5. 本地 AI 已预置 `deepseek-v4-flash`、`DEEPSEEK_API_KEY` 且保持 disabled；用户写入轮换 Key 后，只对一篇 captured article 运行一次省略 `temperature`、SDK/application retry 均关闭的 smoke，成功后才启用。既有 Gemini 安全分析可按同用户/同 input hash 复用，不得冒充 DeepSeek 结果或恢复 `reason`。
6. Telegram adapter 与 fixture 已通过；本机到 `t.me:443` 的 TLS 连接仍失败，待网络出口可用时只做 1 条公开频道复验。
7. 保持“信息获取 + Feed 留存”为唯一当前主线；Graph、Archive analytics、推荐、摘要推送、OPML、历史分页和数据库备份治理均不进入本期。
8. VPS 当前固定为 API-only 发布，Nginx Basic Auth 已移除且公网应用 owner 登录已验证；Feed/订阅/历史人工验收、Feed storage v3 apply、rollout flag 开启和 Worker 自然周期仍未执行，必须分别满足门禁并获得对应授权。
9. HeroUI 生产体验继续按 `UI_CONTRACT.md` 的三视口、可访问性、锚点和构建产物门禁维护；视觉变更必须先修改该唯一真源。
10. 固定数据 `/__preview/workbench-heroui` 只用于开发验收并保持生产构建剔除；已删除的 MUI 对照原型、真实数据 preview 和 `VITE_UI_EXPERIENCE` 分叉不得恢复。

兼容说明：archive items/trends/facets/source-quality、feedback API/表、disabled Graph API 和旧 CLI 全局 archive/graph 仍可保留；兼容接口存在不等于当前产品能力，也不构成后续建设承诺。

## 3. Agent 开工前默认读取
默认先读：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. 当前任务直接相关代码
5. 当前任务直接相关测试

按需再读：

1. 架构任务：`ARCHITECTURE_CONTRACT.md`
2. 决策核对：`DECISION_LOG.md`
3. 上下文策略任务：`CONTEXT_READ_RULES.md`
4. 真实数据验证：`docs/dev/hub-taxonomy-real-run.md`

默认不读：

1. `data/site/history-data.json`
2. `data/site/history/**`
3. `data/horizon.db`
4. `logs/**`
5. `.env*`
6. `.venv/**`
7. 不相关 Markdown

<!-- init-pro:section name=scope -->
## 4. 当前实施范围
本阶段继续做：

1. 小团体用户、角色、公共源市场和个人订阅配置。
2. Hub taxonomy 与 legacy alias 的兼容迁移。
3. 来源配置、抓取任务、可选 AI 分析、Service UI 与用户 Feed snapshot 之间的稳定字段合同。
4. 低成本验证路径、任务队列、配额记录和明确的 capability / degrade 表达。
5. 用户 Feed latest/history 的稳定读取、历史留存和行为状态补全。
6. 用户订阅级来源健康、registry 驱动的来源/订阅编辑、全局 Feed activity 和确定性的 source priority 排序。
7. 管理员 write-only AI/Apify Key 管理，以及每篇 Feed item 的受控长度概括。
8. React 三栏 Service UI、用户作用域 Query cache、任务轮询和移动端主从阅读布局。
9. Presentation v1 通用展示合同、来源解析 fixture、用户级 AI cache 和按 run 的 `analysis_usage` 成本诊断。
10. HeroUI 订阅/来源 workspace、按范围分组、中文运行记录、Worker 更新预检与共享导航账户区域；视觉规则只见 `UI_CONTRACT.md`。
11. `test_gate` 映射观察期：保留全量覆盖，记录连续 10 个不同 CI 提交的 selector、`mapping_miss` 和日志/摘要一致性。
12. 默认关闭的 OpenClaw Remote MCP、用户自管 delegation、10 个安全读/诊断工具与 4 个受控订阅流程工具、浏览器直连用户 Gateway 的对话 UI 和本地 Skill；生产订阅写开关保持关闭。

本阶段不做：

1. 第三方 AIHub/AIHOT API 逆向或依赖。
2. 私密群组、好友流、cookie、session、账号密码采集。
3. 未确认的生产推送、邮件群发或 scheduler 启动。
4. Archive analytics、Graph、个性化推荐、站内原文代理/预览、大规模 embedding 和复杂可视化。
5. 多 workspace、商业计费、自助注册、全站明暗主题切换或独立移动 App；当前 HeroUI 生产体验仅提供暗色主题，视觉规则只见 `UI_CONTRACT.md`。
6. 个人摘要、个人推送，以及把 compatibility-only API 扩展为默认 UI 能力。
7. 服务器侧 Agent/LLM/Gateway 代理、客户间共享 OpenClaw、生产 Remote MCP 写入、OAuth、ClawHub 或模型密钥托管；浏览器直连用户自有 Gateway 只在独立开关下实现。

<!-- init-pro:section name=priorities -->
## 5. API / 模块实现优先级
当前优先级：

1. 稳定 `/api/*` service API envelope、鉴权、权限和错误语义。
2. 稳定 Service SQLite schema、用户、订阅源市场、用户订阅和 job queue。
3. 稳定从 catalog/subscription 合成现有 `Config` 的兼容路径。
4. 稳定 source type registry、`source_key`、旧配置导入和 Worker payload 生成。
5. 稳定默认 UI 只通过用户 Feed、订阅、任务和配置 API 读写，不调用 archive analytics、source-quality、Graph 或 feedback。
6. 稳定 `/api/feed/history`；其精确响应与算法以 `API_CONTRACT.md` 为唯一真源。
7. 持续观察 VPS API-only 部署的 live/ready、数据库和 React UI；Worker/队列自然周期保持冻结。
8. 在本地自动化中持续回归每用户 schedule 的到期入队、手动/自动竞争、skip reason 和 Worker stale/missing；VPS 不执行 canary 周期。
9. 稳定 React Service UI 的 Docker 与浏览器闭环；公网入口已切至 API-only 版本并仅保留应用登录，owner 登录已通过，Feed/订阅/历史仍待人工验收。
10. 用目标测试覆盖每个兼容边界。
11. 完成 `test_gate` 的 10 提交观察期；未达标前默认完成门禁保持 `full`，不得只凭本地 targeted 结果宣称完成。

## 6. 当前实现强约束
1. 不得把外部系统原始字段扩散到业务层。
2. 不得把 taxonomy、阈值、成本开关写死在入口层。
3. 不得让输出层直接访问运行时来源。
4. 不得静默跳过能力缺口，必须显式表达 capability / degrade、unsupported 或 unknown。
5. 不得读取大历史数据或启动 scheduler，除非任务明确要求。
6. `personal_tags` 不进入 AI prompt。
7. `category/tags` 只作为兼容 alias；新实现应优先读写 `channel/topics`。
8. Service Worker 不得读写 `data/site/radar-data.json`、`history-data.json`、`article-graph.json`，也不得走旧全局历史去重。
9. Feed snapshot finalize 必须持有有效 `worker_id + claim_token`，迁移必须显式执行且先备份。

## 7. 建议测试顺序
1. 任务开始时可用 `python scripts/test_gate.py snapshot --output /tmp/impact.json` 建立当前脏工作区的任务级哈希基线。
2. 日常迭代可用 `plan` 检查选择理由并显式运行 `targeted`；未知可执行路径必须 fail-closed 到 full。
3. 观察期内任务完成、PR/main 与合并前统一运行 `python scripts/test_gate.py run --mode full`。
4. UI 相关 CI 追加 Playwright；正式发布统一运行 `python scripts/test_gate.py run --mode release`，其中 Docker smoke 只启动隔离 API。
5. 完整日志只保存在 `.test-results/<run-id>/`；先读限长摘要，只有诊断需要才读取指定失败日志区段。
6. 每个观察提交必须同时满足 selector 无错误、`mapping_miss=false`、摘要与完整日志一致；累计 10 个不同提交后才可另行修改规则，把日常默认切为 targeted。
7. 如涉及 Feed 留存，仍按 `API_CONTRACT.md` 验证用户隔离、history 与显式迁移门禁；不得用任何 test gate 启动真实来源、AI、Worker 或 scheduler。

## 8. 执行后可视化校验
本仓库控制头当前仍是 init-pro `schema=2`，而本机现有 validator 已切换到以 `project-controls.json` 为 manifest 的 schema-v3 接口；旧的 `--primary-config/--profile/--mode` 参数不再受支持。在显式控制面迁移前，不得为让 validator 通过而临时伪造 manifest，也不得把该工具失败误报为业务实现失败。

schema-v2 阶段默认运行：

```bash
python3 -m json.tool project-defaults.yaml >/dev/null
git diff --check
```

未来经明确授权迁移并生成 `project-controls.json` 后，改用当前 validator 接口：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" \
  --project-root . \
  --format markdown
```
