<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=DECISION_LOG.md -->
# Inteliscope InfoHub Light 决策记录

## 1. 文档目的
本文件记录重要架构决策、范围裁剪和兼容性约束，用于避免后续 AI 协作过程中反复偏航。

## 2. 决策记录格式
每条记录建议包含：

1. 决策编号
2. 决策主题
3. 决策日期
4. 当前状态
5. 决策内容
6. 原因
7. 影响范围
8. 后续待验证事项

<!-- init-pro:section name=decisions -->
## 3. 已确认决策
### D001 初始化控制面
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：项目采用 `AGENTS.md`、`PLAN.md`、`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`DECISION_LOG.md`、`CONTEXT_READ_RULES.md`、`WORKLOG.md` 和 `project-defaults.yaml` 维护 AI 协作控制面。
- 原因：减少上下文漂移，明确唯一真源，并保留每次任务的简洁执行记录。
- 影响范围：全部控制文件。
- 后续待验证事项：后续是否需要新增领域专用合同文件。

### D002 Light Runtime 默认不启动 scheduler
- 决策日期：2026-07-08
- 当前状态：已更新（2026-07-10）
- 决策内容：两份 compose 默认启动独立 `horizon-api + horizon-worker`；scheduler 需要显式 `scheduler` profile。
- 原因：多人 Feed 需要常驻 Worker 执行前台队列，但默认启动 scheduler、摘要和推送仍会带来成本与全局副作用。
- 影响范围：`scripts/up-latest.sh`、两份 compose、health/readiness 和运行验证流程。
- 后续待验证事项：每次修改 runtime 脚本后检查默认服务恰为 API + Worker，scheduler 未启动。

### D003 Hub taxonomy 取代单层 AI 标签
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：新实现优先使用 `channel/topics/signal_strength/signal_type/entities`；`category/tags` 保留为兼容 alias。
- 原因：当前阅读筛选需要按主题快速定位内容，长期归档分析需要更稳定的一等字段。
- 影响范围：`ContentItem`、source config、AI prompt/cache、static payload、UI filter、SQLite archive。
- 后续待验证事项：真实来源中 `其他` 占比、空 topics、弱信号占比是否可接受。

### D004 personal_tags 不进入 AI scoring
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：`personal_tags` 只表示用户偏好和私人 feed 信号，不发送给 AI scoring prompt。
- 原因：用户偏好会污染内容主题判断，也会增加不必要的 prompt 成本。
- 影响范围：scraper metadata、orchestrator partition、AI prompt、static payload。
- 后续待验证事项：personal-only feed 仍能进入历史和私人 feed。

### D005 Service Feed 使用结构化结果和用户 finalizer
- 决策日期：2026-07-10
- 当前状态：已确认
- 决策内容：Service Worker 只消费不可变 `FeedRunResult`；`FeedProductionService` 统一处理全量替换、失败来源保留、取消订阅删除、单源合并和 schema-v2 snapshot。Service 链路禁止读写全局 `data/site/*.json`。
- 原因：全局静态文件和全局历史去重无法表达多人隔离，空结果与失败也不能靠裸列表区分。
- 影响范围：orchestrator、source adapters、Worker、catalog runner、UserFeedStore、Feed API。
- 后续待验证事项：持续运行两个 canary 用户的私有 RSS 零交集检查；用户级 Archive/Graph 另立计划。
- 状态补充（2026-07-11）：原“用户级 Archive/Graph 另立计划”表述已被 D008 取代；这些能力现为明确非目标，不因兼容接口存在而自动进入后续路线。

### D006 SQLite Queue 使用 claim token 和 heartbeat
- 决策日期：2026-07-10
- 当前状态：已确认
- 决策内容：claim 在 `BEGIN IMMEDIATE` 内原子完成；所有 finalize/失败/续租都匹配 `job_id + worker_id + claim_token + running`。Worker 10 秒 heartbeat，35 秒为 stale；同一 job 最多一个 snapshot。
- 原因：仅靠 worker id/lease 无法阻止过期 Worker 提交，也无法可靠判断任务排队但无人执行。
- 影响范围：ServiceStore、JobQueue、Worker、RuntimeStatus、ops/readiness、UI。
- 后续待验证事项：发布门槛要求 `stale_running=0`、最老 queued `<5min`、heartbeat age `<35s`。

### D007 Feed v2 采用显式备份后重建迁移
- 决策日期：2026-07-10
- 当前状态：已确认
- 决策内容：旧用户 Feed、state 和 feedback 允许备份后清空重建，但只能在服务停止后显式运行迁移脚本；应用启动不得自动删除。未迁移时 readiness/Worker 拒绝 Feed 任务；用户级 Graph 未实现前返回安全空降级。
- 原因：旧 snapshot 缺来源归属和唯一性，无法无歧义回填；自动迁移会把启动动作变成不可见的数据删除。
- 影响范围：schema 初始化、迁移脚本、readiness、Worker、Graph API、发布/回滚流程。
- 后续待验证事项：生产窗口执行备份可读性、外键检查和迁移后首次刷新；只有确认数据库损坏才恢复备份。
- 状态补充（2026-07-11）：原“用户级 Graph 未实现前”表述中的未来路线含义已被 D008 取代；当前 Graph 仅为 fixed-disabled compatibility route，属于明确非目标。

### D008 当前产品收口为信息获取与 Feed 留存
- 决策日期：2026-07-11
- 当前状态：已确认
- 决策内容：当前 Service 产品主线只包含多人来源订阅、抓取、Feed 展示与用户 snapshot 历史留存。默认 UI 保留打开原文、标记已读、复制摘要、收藏、稍后读和忽略；不提供 Graph、站内原文代理/预览、偏好 feedback、archive analytics 或 source-quality。history v2 采用 `API_CONTRACT.md` 定义的响应与留存语义。
- 原因：全局 archive/Graph 与用户 Feed 留存的数据边界不同；继续把兼容接口描述为产品能力会放大范围、误导 UI 和路线决策，也会掩盖真实 Feed v2 数据迁移尚未执行这一发布门槛。
- 影响范围：`PLAN.md`、Service UI、Feed/history 合同、archive/feedback/Graph API 定位、Service 与 legacy publisher 依赖边界、用户文档。
- 兼容策略：archive items/trends/facets/source-quality、feedback API/表和旧 CLI 全局 archive/graph 暂不删除；Graph 路由固定 disabled 安全空，默认 UI 不调用这些 compatibility-only surface。旧 CLI publisher 可继续独占 `data/site/*`、`data/horizon.db` 和 graph 输出，Service UI/API 不得依赖它们。
- 后续待验证事项：在真实部署窗口显式执行 Feed v2 数据库迁移并完成验收；工具或代码已存在不得表述为迁移已执行或能力已发布。
- 验证状态补充（2026-07-11）：上述真实数据库显式迁移、Docker API + Worker 运行验证、管理员首次刷新和浏览器入口/历史空态验收均已完成；当前转为发布后观察。此状态补充不改变 D008 作出时的原因和兼容策略。

### D009 每用户 opt-in 周期由现有 Worker 调度
- 决策日期：2026-07-11
- 当前状态：已发布验收，进入观察
- 决策内容：多人 Service 为每个用户提供默认关闭的固定周期计划，只允许 1/3/6/12/24 小时，默认 6 小时。到期检查内嵌现有 `horizon-worker`，默认每 30 秒执行一次并复用 `user_feed_refresh`；不新增 dispatcher 容器，也不启用 legacy `horizon-scheduler`。
- 原因：用户计划需要与现有 Feed v2 用户隔离、任务去重、配额、`partial/failed` 和 snapshot 事务语义一致；独立 dispatcher 或复用旧 scheduler 会增加部署单元，并可能把全局摘要、通知、Graph/Archive 静态发布副作用带入 Service Feed。
- 影响范围：`user_feed_schedules`、FeedScheduleService、JobQueue/Quota/Worker、schedule API、ops runtime、订阅/阅读 UI、Compose 与发布观测。
- 兼容策略：旧 scheduler 继续只在显式 `scheduler` profile 中服务 legacy CLI publisher；Service 自动任务固定 `reason=scheduled_service_refresh`、`priority=-10`，不得调用 `LegacyPublisher` 或读写 `data/site/*.json`。
- 验证状态补充（2026-07-11）：真实 light Compose 已只运行 API + Worker，scheduler 未运行；管理员两个自动周期均 `succeeded`、各 21 条、各一个 snapshot，运行门槛和浏览器验收通过，计划已切回 6 小时。第二周期通过受控提前 `next_run_at` 触发，真实周期推进与用户隔离由两用户两周期 E2E 补充验证。
- 后续待验证事项：观察 6 小时自然周期及来源级 `partial/failed`，下一期候选为来源健康状态与失败诊断。

### D010 RC1 采用不可变镜像和分阶段 VPS 切换
- 决策日期：2026-07-12
- 当前状态：本地实现完成，VPS 发布待授权
- 决策内容：`rb.jiefs.top` 初版只发布同 revision 的 API + Worker 镜像；镜像不携带运行数据。VPS 先在 18080 启动 API-only staging，通过后再停止旧 Web/scheduler、切换 8080 并启动 Worker。首次 Service 数据来自脱敏 SQLite backup 副本，不复制 WAL/SHM。
- 原因：当前 VPS 仍运行 legacy Web/scheduler 且没有 Service DB；直接覆盖目录或从脏工作区构建会同时引入数据泄露、版本不可识别和不可回滚风险。
- 影响范围：Dockerfile、Compose、liveness、Cookie、deployment artifact、VPS 发布脚本、Nginx 和运维文档。
- 兼容/回滚：切换失败时先停止新 Worker/API，只允许旧 Web 作为临时维护入口；legacy scheduler 不恢复。最终 release commit/tag 仍需用户单独授权。

### D011 本地密钥使用 write-only 文件边界并为每篇文章生成受控概括
- 决策日期：2026-07-13
- 当前状态：本地实施与真实源验收中，公网发布暂停
- 决策内容：owner/admin 通过网页管理 AI/Apify Key 元数据和值；SQLite 只存 ref，真实值只存 `data/secrets.env` 且永不回显。Service item 在进入 `FeedRunResult` 前统一生成不超过 200 字的概括，Gemini 默认 800 输出 token、1000 正文字符、1500 评论字符，并保留来源摘要/正文/标题回退。
- 原因：本地信息获取需要无需重启的 Key 轮换与可读的逐篇概括，同时必须避免密钥进入数据库、日志、Feed 或浏览器，并控制单篇成本和异常输出长度。
- 影响范围：SecretStore、secret refs/API、配置与订阅 UI、AI client/prompt/cache、orchestrator、reset/bootstrap 脚本和本地 Docker 数据。
- Apify 纠正补充（2026-07-14）：旧 `altimis/scweet` 的最小 100 条输入与用户的“每次 1 条”要求根本冲突，已从 Service 路径移除。X `@thsottiaux` 改用 `apidojo/twitter-scraper-lite` 与 Apify Secondary，适配器上游精确提交 `maxItems=1`。备用 Key 的真实直连运行成功、本次返回 0 条，无最小 100 条或 Actor 权限错误。
- AI 验证状态补充（2026-07-14）：旧 `gemini-2.5-flash` 对新用户返回模型不可用；默认迁移到官方当前稳定 `gemini-3.5-flash`。新 Key 已通过单条真实结构化分析，第二次同用户同输入由 SQLite cache 命中且没有网络调用；密钥值仍不进入配置、日志或报告。

### D012 订阅级自动抓取复用现有 Worker 与单源 finalizer
- 决策日期：2026-07-13
- 当前状态：本地实现、真实 X 与连续三个自然周期验收完成
- 决策内容：在每用户 6 小时全量刷新之外，允许当前用户为单条订阅启用固定 `30/60/180/360/720/1440` 分钟的自动 `source_fetch`。计划由现有 Worker 评估，复用同一队列、配额、claim token、catalog runner、Source Health 和 Feed v2 单源合并；不新增 scheduler/dispatcher。
- 原因：X 等高频来源需要独立新鲜度，但不能用全量 Feed 周期替代，也不能重新引入 legacy scheduler 的全局发布副作用。
- 影响范围：`user_source_schedules`、SourceScheduleService、JobQueue、Worker、schedule API/ops、订阅编辑 UI 和本地 bootstrap。
- 运行约束：同一订阅最多一个 active source job；active 全量刷新延后单源计划，参与来源的全量刷新推进下一周期。当前 X 设置为 30 分钟、上游请求与本地解析均严格上限 1 条；Actor 运行次数/费用仍必须单独观测。
- 验证状态补充（2026-07-13）：连续三个自然到期 tick 均创建 `scheduled_source_fetch`，任务均 `succeeded`、各产出 1 条、各生成一个 snapshot；第三次在 DELETE journal 切换后执行，running 期间 readiness 持续 200。其间一次成功全量刷新也正确把单源计划推进 30 分钟，且无 stale job。

### D013 Service API 使用请求级连接，macOS bind mount 使用 DELETE journal
- 决策日期：2026-07-13
- 当前状态：本地验证完成
- 决策内容：小团体 Service 的 `/api/*` 使用 ContextVar 隔离的请求级数据库连接，每个请求重新打开并在结束时关闭 SQLite 连接；鉴权依赖改为同一 async 请求路径。未结束事务会被回滚并以内部错误终止请求；liveness 保持无数据库依赖。SQLite 原生/Linux 保持 WAL，macOS bind mount 的 light Compose 默认让 API/Worker 同时使用 DELETE journal。
- 原因：macOS Docker bind mount 上，即使使用请求短连接，两个容器的 WAL 共享内存视图仍可能交替滞后超过 35 秒，把最新 heartbeat 误报为 stale。DELETE journal 不依赖 `-shm` 跨容器一致性；请求作用域连接同时消除了 async 路由共享 thread-local 连接的生命周期歧义。
- 影响范围：ServiceStore journal/连接生命周期、FastAPI 中间件、两份 Compose、鉴权依赖、readiness/runtime/UI Worker 状态。
- 后续待验证事项：继续观察多次自然 X 周期与 Apify 计费；若未来 API 并发量超过小团体范围，再以数据库迁移替代当前 SQLite 单机连接模型。

### D014 默认 Service UI 迁移为 React 三栏信息雷达
- 决策日期：2026-07-13
- 当前状态：本地实现与自动化验收完成，公网发布暂停
- 决策内容：默认 `horizon-api` 托管 React 19 + TypeScript strict + Vite 构建产物，以 BrowserRouter 提供 Feed、稍后读、历史、订阅、设置和登录路由；TanStack Query 的用户数据缓存必须包含 `user_id`。`src/ui/static` 保留给 legacy CLI/horizon-web，`HORIZON_SERVICE_UI_VARIANT=legacy` 仅作为一个发布周期回滚入口。
- 原因：原生脚本已承载登录、Feed、任务、订阅、来源健康和 Key 管理，跨页面状态与跨用户异步隔离难以继续扩展；三栏主从布局需要工程化组件、类型、请求缓存和响应式测试边界。
- 影响范围：`frontend/`、FastAPI 静态托管、Docker Node 22 构建阶段、Compose UI variant、Service UI 文档和测试门槛。
- 兼容策略：所有 `/api/*` 响应保持不变；旧 `?view=` 入口在客户端重定向；React 构建缺失时 FastAPI 可回退 legacy。Service UI 仍不得调用 archive analytics、Graph、feedback 或全局静态 Feed。

### D015 React Shell 与 Feed 采用受控 Material UI 视觉系统
- 决策日期：2026-07-14
- 当前状态：本地实现与自动化验收完成；第二阶段等待 Feed 截图人工确认
- 决策内容：默认 React Shell 与 `/feed`、`/later`、`/history` 采用 Material UI v9 的单一 theme/provider、浏览器本地按用户记忆的可折叠 Drawer、Material You tonal surfaces、平衡密度列表和决策简报 reader。`UI_CONTRACT.md` 是 palette、typography、shape、组件边界、响应式布局与视觉门禁的唯一真源。
- 原因：React v1 已完成能力迁移，但分散 CSS Modules、重复 summary、单条截图 fixture 和缺少组件约束无法保证持续一致的产品视觉与可访问性。
- 影响范围：`frontend/src/ui/**`、App Shell、Feed workspace、ESLint/UI contract checks、Vitest/Playwright/Axe、Agent frontend context rules。
- 兼容策略：不修改 `/api/*`、数据库、权限、Query key、路由或 legacy fallback；订阅、设置和登录页 body 暂缓迁移，移动端只做回归保护。

### D016 Service Feed 使用确定性 Presentation v1，取消“为什么值得关注”
- 决策日期：2026-07-14
- 当前状态：Presentation v1 保持生效；可选建议动作已由 D018 取消
- 决策内容：所有 Service 来源先转换为统一 `ContentItem`，再由单一代码投影器生成 Presentation v1；来源、作者、时间、链接、内容类型、来源摘录、taxonomy 和原生互动量不调用 AI。AI 只补充受控中文概括、评分、signal、语义主题与可选建议动作，不再请求、缓存或展示“为什么值得关注”/`reason`。
- 原因：来源形态不同但展示字段高度稳定；把可确定字段交给模型既增加 token，又会造成同一事实跨源格式漂移。“为什么值得关注”对当前信息获取主线没有有效产出。
- 影响范围：source identity metadata、Presentation serializer、分析 prompt/cache、用户级分析缓存、Feed job diagnostics、React/legacy UI、真实来源 contract smoke。
- 兼容策略：API item 以 additive `presentation.version=1` 提供新合同，旧 flat 字段暂保留供 legacy publisher/history 读取；React 优先 presentation 且完全忽略 flat reason。Service 分析缓存按用户隔离，禁止跨用户复用。

### D017 Material UI 扩展到订阅控制台并采用更新前 Worker 预检
- 决策日期：2026-07-14
- 当前状态：Material UI 与 Worker 预检保持生效；范围分组已由 D018 的频道分组替代
- 决策内容：`/subscriptions` 复用统一 Material UI 主题和内部 UI 导出层，以“我的订阅 / 来源库 / 运行记录”组织内容，并按公共、团队、私有范围分组。Feed 更新操作在创建任务前强制刷新 Worker 状态，只有 `ready` 才入队；任务进度不再使用常驻 Snackbar。Drawer 使用顶部展开控制和统一账户卡片。
- 原因：旧订阅页混合来源定义、用户订阅和内部任务枚举，权限与操作含义难以理解；Worker stale 时继续入队会产生无法推进的记录，常驻提示则遮挡主要内容。
- 影响范围：React App Shell、Feed activity、筛选与已读交互、订阅/来源页面、内部 UI 导出层、UI 合同和浏览器回归。
- 兼容策略：不修改 Service API、数据库、Query key 或既有角色权限；私有来源前端判断收紧为仅创建者可编辑，与后端保持一致；legacy Service UI 回滚入口继续保留。

### D018 订阅以频道组织，主题删除非破坏，阅读详情取消建议动作
- 决策日期：2026-07-14
- 当前状态：本地实现与自动化验收完成
- 决策内容：订阅和来源库统一按后端 taxonomy 的有效频道分组，类型、范围与健康退为筛选/标签；频道使用受控候选，主题使用候选优先且允许自定义的多选。主题库删除只停用未来候选，不重写旧引用或 snapshot。React 阅读详情直接展示确定性安全正文片段，新 AI prompt/cache 不再生成或保存 `action_suggestion`。
- 原因：范围分组无法支撑大量来源，逗号/换行文本不适合日常维护；“来源摘录”空卡和模型生成的建议动作没有稳定的信息获取价值，并浪费输出 token。
- 影响范围：Service config taxonomy、主题保存语义与 cache version、React 订阅/设置/账户/reader、AI prompt/analyzer、UI/API 合同。
- 兼容策略：不新增表、不重写旧 Feed；旧 source/subscription 主题继续显示并标记停用，旧 `action_suggestion` 仍可反序列化但 React 永不读取。

### D019 公共来源共享中性获取，用户投影与 Feed 版本继续隔离
- 决策日期：2026-07-14
- 当前状态：本地实现完成，两个 rollout flag 默认关闭，等待分阶段启用
- 决策内容：public/workspace source 在同 workspace 和 freshness window 内通过 SQLite claim/content pool 最多调用一次上游；private source、订阅投影、AI cache、行为状态和 Feed snapshot 保持用户隔离。Feed 全量/增量共用 canonical merger，以内容 hash 跳过 no-op 版本，并可在显式 v3 迁移后启用 compact writer。
- 原因：原来同一公共源按用户重复抓取并重复计费，同时 lifecycle、retry、配额、增量去重和 snapshot 留存存在跨事务或语义漂移；演进式 additive 方案可以保留现有 API/job 和回滚入口。
- 影响范围：Service schema、Worker/orchestrator、抓取与 AI 计量、Feed finalizer/store、runtime ops、迁移/retention、API/架构合同和环境默认值。
- 发布门禁：先保持 shared acquisition/compact writer 关闭并运行 v3 dry-run；再只对非付费公共源观察两个自然周期。付费源必须单独显式授权且 item limit 为 1；回滚只需关闭对应 flag，additive 表可保留。

### D020 收藏与站内阅读使用稳定内容索引和受保护媒体缓存
- 决策日期：2026-07-14
- 当前状态：代码与自动化回归完成；本地 v4 apply 和付费 X canary 待完成
- 决策内容：`user_content_items` 作为用户级稳定文章索引，收藏/稍后读和 Presentation v2 详情不再依赖最近 snapshot；Worker 只缓存抓取器已获得的正文、最多 6 张图片和来源头像，并通过鉴权 `/api/media/*` 同源返回。选中文章不再自动标记已读，Feed 模式和未读优先按用户保存在浏览器。
- 社交策略：X 默认 adapter 改为 `xquik/x-tweet-scraper`，输入固定单账号/单条；X/Instagram profile 采用 `latest_per_source`，成功新帖替换旧帖，失败或空结果保留旧帖。diagnostic/demo/run-report 不得成为内容。正式配置只能在备用 Key canary 满足成本上限并返回有效帖子后切换。
- 兼容策略：Presentation v1 列表继续兼容；旧 snapshot 只以 `excerpt_only` 回填，不建设网页全文代理。v4 是 additive 且必须显式备份/回填；未迁移时 readiness、schedule 和 Worker Feed job 返回 `migration_required`。

### D021 测试门禁采用确定性影响映射和限长摘要
- 决策日期：2026-07-15
- 当前状态：实现完成，进入 0/10 个不同 CI 提交的观察期
- 决策内容：统一使用 stdlib-only `test_gate` 承载 snapshot、impact plan、targeted、full 与 release。任务快照只保存安全相关文件的相对路径和 SHA-256；PR/main 使用 base/head diff。Python 子系统、React related/full、legacy UI 和测试文件自身由版本化 JSON 映射选择，未知可执行代码、依赖或构建边界 fail-closed 到 full。
- Token 与安全边界：每条命令 stdout/stderr 写入忽略的私有 `.test-results/<run-id>/`；成功摘要最多 2 KiB，失败摘要最多 8 KiB/80 行且只含首失败。环境密钥值在日志和摘要中脱敏，命令记录不保存环境值。
- 发布边界：PR/main 永久保留 full backend/frontend；UI 改动追加 Playwright。release 在 full 之外使用独立网络、临时数据目录、无 Worker/scheduler 定义的 API-only Compose smoke，禁止真实来源、付费调用和 AI。
- 渐进策略：观察期内 AGENTS 默认完成门禁仍为 wrapper full。只有连续 10 个不同提交均满足 selector 无错误、`mapping_miss=false`、摘要/日志一致，才允许另行决策把日常默认改为 targeted；合并与发布永远保留 full/release。

### D022 Feed 通知事件化、历史内容可审计修复并切换 DeepSeek
- 决策日期：2026-07-15
- 当前状态：代码、本地 v5 apply、免费来源修复与 reconcile 完成；DeepSeek 等待轮换 Key 的模型预检与单次 smoke 后启用
- 决策内容：Feed terminal 状态与一次性通知分离，只有真实创建 snapshot 的成功任务弹更新提示；认证异步操作统一按用户/动作/实体反馈。稳定内容 v5 以备份后修复、专用 `content_repair` Job 和 unresolved report 恢复来源正文/媒体，不做网页全文代理。全局 AI 目标切至 `deepseek-v4-flash`，同输入哈希可复用同用户既有安全分析，模型切换不批量重分析。
- 原因：轮询把历史 succeeded job 当实时事件导致通知重放；旧 snapshot 只保存摘要和临时媒体线索，详情无法满足全文/多图；模型切换若忽略既有安全分析会产生无价值的批量成本。
- 安全与运行边界：对话中旧 Key 视为泄露且永不保存/调用。免费 RSS/GitHub 可批量修复，X/Instagram 付费来源必须逐条授权。本地最终运行 API + Worker、legacy scheduler 关闭；VPS Tokyo 继续 API-only，未获得 Worker 部署授权。
- 状态补充（2026-07-15）：稳定内容新增显式 reconcile，在无 active Job/Worker 时以 `0600` 备份事务性升级 nullable reason，并清理 captured 正文残留的精确 `source_body_not_available` token；本地 1 条冲突已修正，随后将旧 NOT NULL schema 遗留的 23 个空字符串占位规范化为 SQL `NULL`，最终仍为 24 captured/2 excerpt-only、snapshot/Job/media/usage 数量不变。DeepSeek smoke 增加 10 秒、retry=0 的 `models.list()` 预检，completion 省略 `temperature` 且禁用应用层参数降级重试，失败时 completion 固定为 0 或首次 completion 后立即终止；当前轮换 Key 未设置，AI 继续 disabled。

### D023 来源响应只保存有界结构摘要，头像采用验证后换版
- 决策日期：2026-07-16
- 当前状态：代码与自动化回归完成，等待本地镜像验收
- 决策内容：source adapter 在调用栈内把上游对象立即转换为仅含字段路径/类型的有界摘要，terminal Job 同时保存上游与统一 `ContentItem` 结构；不保存原始值，不新增永久响应历史表。X 头像只为 `pbs.twimg.com` 增加合成 DNS 例外，远端身份变化或 24 小时 TTL 到期后先验证候选图片/checksum，再替换旧 ready 资产。
- 原因：运行记录需要解释不同订阅/Actor 的返回形状，但保存原始 payload 会扩大凭据、个人内容和保留周期风险；按需重新抓取又会增加费用。候选先验证可避免头像 CDN 失败时把可用版本替换为空。
- 影响范围：scraper observation、Orchestrator/Job diagnostics、共享获取 origin、媒体缓存、React 运行记录、API/架构/UI 合同。
- 兼容策略：旧 Job 没有 `response_schemas` 仍可读取并显示明确降级；共享缓存命中只显示 `cached`，不会冒充本次上游响应；默认 RSS/member URL 网络策略未放宽。

### D024 每用户本地 OpenClaw 通过远程只读 MCP 访问 Inteliscope

- 决策日期：2026-07-16
- 当前状态：本地实现完成，默认功能关闭，待 API-only staging、Nginx 和真实 OpenClaw canary 验收后才能在生产打开。
- 决策内容：模型、对话、推理和 Skill 均运行在用户本地 OpenClaw；Inteliscope 在现有 `horizon-api` 的 `/mcp` 提供六个无状态、用户隔离、有界的只读工具，Web UI 只管理 delegation 凭证和配置指南。
- 原因：多人都可使用自己的本地模型与 OpenClaw 配置，服务器不承担 Agent/LLM 资源和会话状态；工具直接调用 Service/Store 可避免内部 HTTP 回环延迟。
- 影响范围：新增 schema v6 `agent_delegations`、Cookie Session 管理 API、精确 `/mcp` 路由、`/agents` 页面和本地 Skill 包。所有角色都可创建自己的连接，但管理员令牌仍只能读管理员自己的数据。旧 `src/mcp/server.py` 继续作为本地 stdio/legacy 能力，不对外暴露。
- 非目标：OAuth、站内聊天、本地 Agent URL、写操作、刷新/抓取、审批流、管理员 delegation 控制台、ClawHub 发布、服务器侧 Agent 或模型。
- 回退：将 `HORIZON_REMOTE_MCP_ENABLED=false` 并移除 Nginx 精确 `/mcp` 路由；保留 additive v6 表，不做降级迁移。

### D025 Next Web 工作台借鉴 Codex 视觉语言但以 Inteliscope 交互为准

- 决策日期：2026-07-17
- 当前状态：已由 D028 的 HeroUI 生产切换完成；本条保留为设计方向的历史依据
- 决策内容：Mac Codex 只作为暗色层级、紧凑密度、三栏结构、短刻度与克制动效的参考，不做像素复刻。Next 工作台保留 Inteliscope 的信息流、收藏、历史、订阅和 Remote MCP 边界；信息流固定为“全部”，移除精选、日报和稍后读。OpenClaw 侧栏只整理最多 8 条上下文并生成 `get_item` 交接提示词，不提供站内聊天或在线状态。
- 原因：视觉相似不能替代 Web 的滚动稳定性、操作可达性、响应式布局、键盘支持和状态解释；同时接入真实数据会让视觉问题与数据问题混在一起，增加返工成本。
- 兼容/回退：开发预览继续不需要认证且不调用 API；原计划的 `VITE_UI_EXPERIENCE` 分叉已由 D028 取代，回退使用上一不可变生产镜像而不保留双 UI 源码。

### D026 HeroUI v3 作为独立候选原型，不与生产 MUI 混用

- 决策日期：2026-07-17
- 当前状态：候选已由 D028 选为生产体系；固定数据 HeroUI 预览保留，MUI 对照预览已删除
- 决策内容：新增开发专用 `/__preview/workbench-heroui`，实际使用 HeroUI v3.2.2 与 Tailwind v4.3.3；它和 MUI 原型共用固定信息、导航与 OpenClaw 交接模型，但拥有独立主题、样式入口和渲染根。HeroUI 不进入认证、Query Client、API 或生产构建，也不允许在生产业务页面直接导入。
- 原因：用户认可 HeroUI 的卡片、胶囊控件、焦点环和按压反馈，需要以真实组件验证整体观感；并行候选比只模仿视觉语言更能公平判断组件体系，同时避免在视觉方向确认前改写现有生产 UI。
- 兼容/回退：`/__preview/workbench-heroui` 保持开发隔离和生产剔除；`/__preview/workbench` 已删除。API、Query Key、权限和数据边界仍不变。

### D027 HeroUI 生产迁移采用单一设计系统边界与渐进 bootstrap

- 决策日期：2026-07-17
- 当前状态：设计系统边界和业务迁移已由 D028 完成
- 决策内容：`frontend/src/design-system/**` 集中拥有 HeroUI v3 组件、表单能力、Lucide 图标、石墨紫主题与 React Router 导航桥接；正式业务代码只能通过该边界使用 HeroUI。固定数据 HeroUI 原型是唯一可直接导入 `@heroui/*` 的 feature 例外。
- 原因：HeroUI 方向进入正式迁移后，需要先固定组件、主题和 SPA 导航合同，再分批迁移真实页面；直接在业务页散落库导入会使主题、可访问性和最终依赖清理无法统一验证。
- 兼容/回退：D028 完成后，HeroUI provider 成为唯一生产 UI provider；Query Client、认证、`ServiceApi`、API 与 Query Key 继续保持。原型仍由开发入口隔离并从生产构建排除。

### D028 生产 UI 单一切换到 HeroUI，并删除双栈回滚

- 决策日期：2026-07-17
- 当前状态：本地实现与全量自动化验收完成
- 决策内容：生产 Shell、Feed/saved/history、subscriptions/agents/settings 与 login 统一使用 `frontend/src/design-system/**` 的 HeroUI 体系；`AppBootstrap` 是唯一 provider 所有者。MUI、MUI Icons、Emotion、旧 UI 层、MUI 原型、真实数据 preview 与 UI-experience 分叉全部删除。视觉、响应式和验收规则只以 `UI_CONTRACT.md` 为准，本决策不复制这些规则。
- 原因：保留两套 provider、页面和依赖会让路由、主题、可访问性和构建产物持续分叉，也无法用静态门禁证明生产只有一个视觉体系。单一切换把候选验证结果落实为可维护的生产边界。
- 影响范围：`frontend/` 生产 bootstrap、路由、页面、设计系统、静态 UI 契约、Playwright/Axe 与生产构建产物检查；不影响 API、数据库、角色权限、Query Key、Remote MCP、history、VPS 或运行开关。
- 兼容/回退：`/later` 仅替换到 `/saved` 并保留 `item`；固定数据 `/__preview/workbench-heroui` 只在开发存在。故障回退使用上一不可变 Docker 镜像，不在当前源码保留 MUI 双栈或 feature flag。

### D029 Feed 视觉确认先采用单页 Codex 风格微调

- 决策日期：2026-07-18
- 当前状态：已先由 D030 的 Quiet Studio 方案取代，再由 D033 扩展为全站统一；本条仅保留历史依据
- 决策内容：本轮只调整生产 `/feed`：隐藏顶部搜索和手动刷新，使用 macOS 系统字体栈，并把信息流进度改为左侧、无容器、带当前与相邻刻度动效的短轨。收藏、历史和其他页面继续保持现状；精确视觉规则只见 `UI_CONTRACT.md`。
- 原因：用户希望先用真实信息流确认版式和动效，再决定是否把该风格扩散到全局；提前同步修改其他路由会增加视觉判断变量和返工范围。
- 影响范围：Hero 工作台 Shell 的 `/feed` 路由分支、虚拟 Feed 的显式轨道变体、设计系统字体 token、相关 RTL/浏览器回归；不影响 API、数据库、Query Key、权限、Remote MCP、Worker 或刷新任务语义。
- 后续：只有用户完成 `/feed` 人工验收并明确授权后，才评估将字体、安静顶部或动态轨道扩散到收藏、历史及其他页面。

### D030 — Feed adopts the approved Quiet Studio variant

- 决策日期：2026-07-18
- 当前状态：Feed 决策已完成；其中“集合路由保持不变”已由 D033 取代
- Decision: Remove the Feed progress rail and its gutter; use the split-panel Agent glyph, centered Quiet Studio cards, route-scoped motion, and inline expansion. Keep collection routes unchanged.
- Rationale: User approved visual direction A and its interaction prototype; the result follows Apple-inspired hierarchy and restraint without copying platform chrome or applying glass to content.
- Compatibility: No API, query, permission, Worker, Remote MCP, data, or dependency changes.

### D031 Quiet Studio 采用分类导航、双向排序和确定性交接编辑器

- 决策日期：2026-07-18
- 当前状态：本地实现、聚焦自动化与完整仓库门禁均已完成
- 决策内容：在现有 HeroUI/Quiet Studio 生产树内，将展开导航组织为浏览、常用视图和管理；账户动作收进统一账户菜单；Feed 默认最新优先并允许按用户切换顺序；重复标题摘要只在展示层消除；OpenClaw 面板使用单一交接编辑器并保存提示词级模型偏好。精确视觉与响应式规则只见 `UI_CONTRACT.md`。
- 原因：原扁平图标栏、稀疏工具条、重复卡片文字和分散的 Agent 输入控件功能可用但层级不清。分类与渐进披露提高扫读和操作可理解性，同时保持 Web 信息流和本地 OpenClaw 的真实能力边界。
- 兼容/回退：不修改 API、数据库、Query Key、角色权限、Worker、Remote MCP 或历史 Feed；旧 Feed 偏好默认补为最新优先，旧 Agent 草稿默认补为自动。故障回退仍使用上一不可变 Docker 镜像。

### D032 生产 UI 采用单一字体栈与可执行语义排版契约

- 决策日期：2026-07-18
- 当前状态：实现、完整门禁与 revision-locked 本地 Docker 视觉验收完成
- 决策内容：全站统一使用设计系统拥有的 macOS/system UI 字体栈和十级语义排版；业务页面只能选择 `type-*` 角色，禁止自行使用 Tailwind 字号、字重、行高和字距工具类。精确角色和值只见 `UI_CONTRACT.md`。
- 原因：此前 Feed 使用路由级字体覆盖，业务组件同时散落 `text-xs`、`text-[13px]`、`font-semibold` 与 `leading-*`，导致同一工具栏和跨页面层级无法保持一致，也无法通过人工逐处标注可靠维护。
- 兼容/回退：不改变布局、业务行为、API、数据、权限、Query Key、Worker 或 Remote MCP；静态门禁阻止新增排版分叉，故障回退仍使用上一不可变 Docker 镜像。

### D033 Quiet Studio 成为全站自适应视觉与交互语言

- 决策日期：2026-07-19
- 当前状态：实现、完整门禁、三视口浏览器验收与 revision-locked 本地运行验收均已完成
- 决策内容：全部生产路由统一消费设计系统的 Quiet Studio 页面模式、语义排版、表面、控件、动效和状态反馈；阅读、管理与认证页面分别选择共享 `PageFrame` 宽度。收藏与历史取消 collection 进度轨并复用信息流卡片；管理路由只保留 Shell 中的唯一标题；OpenClaw 三种响应式容器复用同一交接编辑器与受控选择器。精确规则只见 `UI_CONTRACT.md`。
- 原因：仅统一字体或逐页修补无法防止卡片、页面宽度、标题和控件再次分叉。把页面结构、状态模式和宽度所有权上收至设计系统，才能让后续 UI 修改在可执行契约内持续保持一致。
- 取代范围：取代 D029 的单页扩散检查点，以及 D030 中“收藏/历史保留 collection 轨道”的部分；不改变 D030 已确认的 Quiet Studio 克制层级与内容交互。
- 兼容/回退：不修改 API、数据库、权限、Query Key、任务、Remote MCP 或历史数据；运行故障仍回退上一不可变 Docker 镜像。
