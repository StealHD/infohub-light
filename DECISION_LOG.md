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
- 当前状态：11 个安全读工具的本地实现与发布自动化完成，默认功能关闭，待 API-only staging、Nginx 和真实 OpenClaw canary 验收后才能在生产打开；订阅写开关继续关闭。
- 决策内容：模型、对话、推理和 Skill 均运行在用户本地 OpenClaw；Inteliscope 在现有 `horizon-api` 的 `/mcp` 为 read delegation 提供 11 个无状态、用户隔离、有界的安全读、来源指导、诊断与脱敏事件工具，Web UI 只管理 delegation 凭证和配置指南。
- 原因：多人都可使用自己的本地模型与 OpenClaw 配置，服务器不承担 Agent/LLM 资源和会话状态；工具直接调用 Service/Store 可避免内部 HTTP 回环延迟。
- 影响范围：additive v6/v7 数据结构、Cookie Session 管理 API、精确 `/mcp` 路由、`/agents` 页面和本地 Skill 包。所有角色都可创建自己的 read connection，但管理员令牌仍只能读管理员自己的数据。旧 `src/mcp/server.py` 继续作为本地 stdio/legacy 能力，不对外暴露。
- 非目标：OAuth、站内聊天、本地 Agent URL、刷新/抓取、任务控制、Feed 状态写入、管理员 delegation 控制台、ClawHub 发布、服务器侧 Agent 或模型；订阅写流程由 D034 单独约束且本次生产发布不启用。
- 回退：将 `HORIZON_REMOTE_MCP_ENABLED=false` 并移除 Nginx 精确 `/mcp` 路由；保留 additive v6/v7 结构，不做降级迁移。

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
### D034 Remote MCP 订阅写入采用服务端 proposal 与显式 opt-in delegation

- 决策日期：2026-07-18
- 当前状态：本地实现与合同完成；写开关默认关闭。真实 OpenClaw canary、API-only staging 和生产启用尚未执行。
- 决策内容：保留 read delegation 的 `inteliscope:read`，其 OpenClaw toolFilter 包含全部 11 个安全读取、指导/发现、诊断与脱敏事件工具；仅 Web 显式创建的新 `subscriptions_write` connection 同时拥有 `inteliscope:subscriptions:write` 并额外暴露三个 prepare 与一个 apply。`owner/admin/member` 可选择该权限，viewer 永远只读；`HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED` 是独立的 opt-in server flag。prepare 只产生 10 分钟的密封 proposal 和完整 preview；只有带精确确认短语的 apply 能调用共享 `SubscriptionMutationService` 写入。
- 原因：把 flag、scope、实时角色、所有权、配额和指纹复查放到服务端事务内，避免 Skill 文案或一次 MCP 调用成为业务写入授权；REST 与 MCP 复用同一 mutation owner，不形成内部 HTTP loop。当前 OpenClaw 通用 `mcp.servers` 客户端没有 Elicitation handler，因此确认短语是兼容性流程，不能声称协议层已证明真人确认；未来支持 Elicitation 时可替换交互步骤而不改变 proposal 模型。
- 安全边界：诊断仅基于脱敏持久化证据并允许 `unknown`；Skill/文章内容不能驱动写参数。密钥继续只在 Web SecretStore 管理，聊天、MCP 输入、proposal、日志和 UI 配置均不得接收或回显密钥。
- 非目标：不新增 OAuth、refresh token、服务器 Agent/LLM、站内聊天、本地 Gateway 探测、共享来源管理、密钥管理、刷新/重试/取消、Feed item 状态写入或 ClawHub 发布。
- 回退：只关闭 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`；保留只读 MCP、scope 与 additive v7 proposal 表，不做 schema 回滚。

### D035 Inteliscope 浏览器直接连接用户自有 OpenClaw Gateway

- 决策日期：2026-07-19
- 当前状态：本地实现完成、功能默认关闭；待真实 Chromium/OpenClaw、本地与 API-only staging 验收后才可单独打开，生产订阅写开关继续关闭。
- 决策内容：Inteliscope 对话面板由浏览器直接使用 OpenClaw Gateway WebSocket v4，创建专属 `Inteliscope` session，支持历史、流式回复、停止、重连和独立 `tools.effective` 状态。文章上下文只发送问题与最多 8 个 article ID；OpenClaw 通过 Remote MCP 最多分三段读取 20,000 字符已存正文。首次 token 只在表单内存，配对后仅按 Inteliscope 用户和 Gateway URL 隔离保存 non-exportable Ed25519 设备私钥、exact `operator.read + operator.write` device token 与 session key。
- 原因：用户自有 OpenClaw 才是模型、费用、对话和 Skill 执行域；Remote MCP 是 Inteliscope 数据/订阅能力入口。浏览器直连让当前本地 Gateway 和未来用户专属云端 `wss://` 只差 URL 与 Origin 配置，同时无需 Inteliscope 服务器代管模型密钥、Gateway token 或对话代理。
- 取代范围：正式取代 D024/D025/D031/D033/D034 中“站内不聊天、不连接或探测本地 Gateway”的 UI 非目标和旧复制交接边界；这些决策的视觉、Remote MCP、proposal、权限和生产禁写边界继续有效。服务器无 Agent、无模型、无 OpenClaw、无 Gateway 代理的边界不变。
- 安全/兼容：本地明文 WS 只允许 `127.0.0.1/localhost`，远端必须 WSS，URL 不得携带凭证/query/fragment；返回额外权限时拒绝持久化。`HORIZON_OPENCLAW_CHAT_ENABLED=false` 时 UI 立即回到旧复制模式且不创建 WebSocket；Remote MCP 和数据库无需回滚。
- 非目标：本次不启用生产订阅写入、不提供服务器侧 Agent/LLM、共享客户 Gateway、OpenClaw 模型密钥托管、HTTP Chat API、站内直接调用 MCP 写工具或重新抓取原网页。

### D036 信息工作台采用来源优先的社交卡片与可读 Agent 上下文

- 决策日期：2026-07-19
- 当前状态：前端实现、完整门禁、三视口浏览器验收与 revision-locked 本地 RC 验收完成；已纳入 v1.7.0 集成分支
- 决策内容：桌面侧栏路由与常用视图统一使用同一交互行和分栏控制；社交内容按平台、关注对象/作者与来源表达，并只显示一次正文；Agent 上下文保存安全展示记录，历史 ID-only 草稿通过用户作用域详情查询展示头像、来源、正文首行和时间。精确视觉规则只见 `UI_CONTRACT.md`。
- 原因：快速视图独有的按压位移、社交标题/摘要/正文重复，以及直接暴露内部 ID，会破坏 Quiet Studio 的一致性和扫读效率，也无法帮助用户确认交接对象。
- 兼容/回退：仅改变前端展示模型与组件；不修改 OpenClaw `auto | fast | deep` 模型选择、API、数据库、权限、Query Key、Remote MCP、历史快照或 Worker。article ID 仍用于 sessionStorage 与确定性交接提示词，但不作为界面文案。

### D037 Feed 采用活跃来源的滚动时间窗口并收口侧栏/上下文可达性

- 决策日期：2026-07-19
- 当前状态：实现、定向/完整/release 门禁与 revision-locked 本地 RC 验收完成；精确标签 `v1.7.1` 已发布并安全部署至 `vps-tokyo`
- 决策内容：全量 Feed 不再以“成功抓取即覆盖该来源”重建，而是合并本次结果、最新 snapshot 与当前用户稳定内容索引中的 active-source 窗口内内容；取消订阅立即移除，显式 `latest_per_source` 继续替换。X/Instagram profile 的历史派生 latest 策略按 `time_window` 兼容读取，以恢复仍在窗口内的近期帖子。前端同时增加可清空筛选的“全部”常用视图、只在导航面板打开时着色的分栏按钮，以及无需独立滚动即可移除全部八条的单行 Agent 上下文。
- 原因：旧全量刷新会在 Tibo 等社交来源每次仅返回一条时，把仍在时间窗口内的上一条帖子从最新 Feed 移入历史；同时长上下文、常驻紫色入口与缺少基线视图降低了操作可达性和状态可理解性。
- 取代范围：取代 D019 中 X/Instagram profile 的派生 `latest_per_source` 默认，以及 API retention 中“成功来源本次结果替换对应来源”的旧规则；显式 retention、历史 snapshot、公开 API 形状、OpenClaw 模型选择与所有权限边界不变。
- 兼容/回退：不新增表、不重写历史 snapshot、不修改 Query Key/MCP/权限；稳定索引只用于重建当前用户最新 Feed。运行故障回退上一不可变镜像，增量生成的新 snapshot 可继续由旧版本读取。

### D038 删除生产控制面中的历史 Material UI capability 词汇

- 决策日期：2026-07-20
- 当前状态：已从默认控制面删除
- 决策内容：删除三个无消费者的 `material_ui_*_enabled` capability 字段；生产 UI 技术栈继续只由 `UI_CONTRACT.md` 定义，不新增重复的 HeroUI 技术开关。
- 原因：生产已在 D028 完成 HeroUI 单栈切换，继续暴露 MUI capability 会让控制面与实际依赖、源码和 UI 契约漂移。
- 兼容/回退：字段无运行消费者；不影响 API、数据库、权限、构建开关或部署行为。

### D039 内容工作台刷新与排序动作按数据所有权分配

- 决策日期：2026-07-20
- 当前状态：本地实现
- 决策内容：Feed 工具栏提供创建全量更新任务的“更新”动作；收藏和历史不创建更新任务，改为复用用户隔离的最新/最旧排序。精确布局与响应式规则只见 `UI_CONTRACT.md`。
- 原因：更新任务改变 Feed 数据源，应从 Feed 发起；收藏与历史是同一内容集合的派生视图，主要需要本地排序而不是重复的抓取入口。
- 取代范围：取代 D029/D031 中 Feed 隐藏手动更新以及集合路由保留刷新动作的对应部分；不修改刷新 API、任务、权限、数据库或 OpenClaw 协议。

### D040 内容格式与媒体完整性采用来源优先的统一展示投影

- 决策日期：2026-07-20
- 当前状态：已完成（本地验证）
- 决策内容：Presentation additive 增加九种 `content.format`、分类来源和原始图片总数；分类固定按上游明确类型、强确定性规则、同一次可选 AI 分析、安全兜底解析。Quiet Studio 卡片把格式、图片数量、可展开内容和来源采集不完整分别表达。
- 原因：既有 `content_kind` 只描述正文片段语义，无法回答文章/视频等扫读问题；只显示首张缓存图也无法表达社交图集，而所有卡片都伪装成可展开会误导用户。
- 兼容/回退：不替换 `content_kind`，不新增 AI 调用、表或历史回填；旧 item 通过来源/URL/现有媒体安全推断。新字段对旧客户端 additive，可回退为旧卡片展示。

### D041 OpenClaw 浏览器对话采用真实会话模型与分离显示消息

- 决策日期：2026-07-20
- 当前状态：已完成（本地验证）
- 决策内容：浏览器对话把用户可见消息与版本化 MCP Gateway Prompt 分离；发送后即时清空本轮草稿和附件，历史投影隐藏内部指令。模型、推理档位和当前覆盖值只读取 OpenClaw Gateway。D042 已取代本条中通过 `sessions.patch` 修改模型/推理的实现方式。精确布局与无横向滚动规则只见 `UI_CONTRACT.md`。
- 原因：把完整交接 Prompt 当作用户消息会让输入无法形成正常问答流；硬编码模型偏好会与本地 OpenClaw 配置漂移，长上下文与 URL 还会制造不可接受的横向滚动。
- 兼容/回退：Agent 草稿 v3 只迁移问题和上下文；旧 handoff 历史继续安全投影。Gateway、后端 API、数据库、权限、Query Key、Remote MCP 和 OpenClaw 全局默认均不改变。

### D042 Feed 右栏、当天口径、OpenClaw 运行时与媒体身份统一收口

- 决策日期：2026-07-21
- 当前状态：已完成（本地 RC 与真实浏览器验收通过）
- 决策内容：Feed 右栏统一为 `closed | insights | agent`，宽屏首次进入默认显示复用现有查询的信息概览；当天视图与统计共用浏览器本地自然日纯函数。OpenClaw 模型切换使用保留上下文的 `sessions.create` 分支并经 `sessions.describe` 验证后切换，推理档位作为 `chat.send.thinking` 的发送快照，不再调用需要 `operator.admin` 的模型/推理 `sessions.patch`。内容图片使用用户文章作用域 checksum 作为稳定身份，详情继续防御性去重历史行。
- 原因：乐观选择器曾显示与实际会话不同的模型并暴露 `missing scope: operator.admin`；同图 CDN URL 轮换会生成重复缓存；当天与概览若各自计算会产生数量漂移。统一状态机、真实会话校验和内容身份可以消除这些系统性不一致。
- 取代范围：取代 D041 中模型/推理通过 `sessions.patch` 写入当前会话的部分；不改变 OpenClaw Gateway、Remote MCP、Inteliscope API、数据库 schema、权限、Query Key 或全局模型配置。
- 兼容/回退：旧媒体行与历史快照不删除；旧 Feed 偏好缺少 `dateScope` 时读为 `all`；模型分叉失败保留原 session key，并可显式创建空白目标模型会话。

### D043 Insights 脱离固定栏，Agent 宽度可调且 OpenClaw 历史只增量对账

- 决策日期：2026-07-21
- 当前状态：本地实现
- 决策内容：Agent 保持唯一固定右栏并允许桌面按账号保存 320–720 px 宽度，Feed 至少保留 640 px；Insights 改为只在实测阅读列右侧空白充足时自动出现一次的分组浮层。Gateway 历史采用本地可见对话与远端记录的增量归并，普通断线/刷新保留，模型分叉迁移，新对话、退出和忘记设备清除。来源失败详情改为安全 Tooltip 与可访问 Dialog，独立滚动区统一使用透明轨道的 Quiet Studio 滚动条。
- 原因：把 Insights 和 Agent 都建模成固定第三栏会无谓挤压阅读宽度；固定 360 px 不能满足长回答阅读；Gateway 不完整历史整体覆盖会让刚发送的用户问题消失；来源错误常驻卡片和浏览器默认灰色轨道都会破坏信息密度与视觉一致性。
- 取代范围：取代 D042 中 `closed | insights | agent` 共用固定右栏及宽屏默认固定 Insights 的部分，不改变 D042 的本地日期、模型分叉、推理快照或媒体 checksum 决策。
- 兼容/回退：新增偏好与 transcript 均为浏览器本地、按用户隔离的 v1 数据；无 API、数据库、权限、Query Key、Gateway/MCP 协议或公网部署变化。旧客户端忽略这些本地键即可回退。

### D044 对话落盘、Agent 停靠与概览高度以运行时事实为准

- 决策日期：2026-07-22
- 当前状态：本地实现
- 决策内容：OpenClaw 每个用户轮次生成稳定 client turn ID，并在发起 Gateway 请求前原子更新 React 状态、内存引用和会话记录；远端历史缺失不具有删除语义。Agent 不再用 1440 px 固定断点决定停靠，而以当前导航宽度、640 px Feed、320 px Agent 和分隔器是否同时容纳为准。信息概览采用内容自然高度，空分组不渲染，频道和类型默认各展示前三项并由用户显式展开。
- 原因：异步 effect 落盘存在快速响应或卸载窗口，固定断点不能反映真实可用空间，固定两行网格会把少量统计撑成空白大面板。三项改为同步状态和实测布局后，界面行为与用户实际看到的内容一致。
- 取代范围：细化 D043 的实现边界，不改变其来源披露、滚动条、宽度偏好、会话隔离或清理语义；不修改 API、数据库、权限、Query Key 或 Gateway/MCP 协议。
- 兼容/回退：`clientTurnId` 是本地消息可选字段，旧 transcript 仍按既有归并签名读取；停靠和概览只改变前端布局，可回退到 D043 行为而不迁移数据。

### D045 私人来源提升复用稳定内容，订阅停用由用户决定现有内容去向

- 决策日期：2026-07-22
- 当前状态：后端接口与定向回归完成，前端接入中
- 决策内容：private owner 可把来源提升为 workspace/public，提升后来源地址和管理权归工作区管理员；新订阅或重新启用优先复用 workspace 内已索引内容并生成订阅者自己的 Feed，不创建重复抓取任务。每个用户可独立停用或取消订阅；停用时显式选择把该来源现有卡片收藏或忽略。忽略集合只在设置页恢复，来源引用计数仅按用户操作查询。
- 原因：把私人来源共享给多人后若每个成员重新抓取，会重复消耗上游配额；把 shared source 的生命周期绑定到单个订阅者又会误删其他人的来源。显式内容处置、引用按需查询和最后一个 private owner 的僵尸防护同时保持成本、所有权和用户状态隔离。
- 影响范围：catalog share/usage、subscription create/update/delete、稳定内容索引与 Feed snapshot、忽略集合、当前用户密码接口，以及对应 Web 管理入口。
- 兼容/回退：接口均为 additive；旧客户端不发送 `on_disable` 时沿用移除语义。无数据库迁移、不重抓历史来源、不修改其他用户状态，关闭前端入口即可回退交互。

### D046 刷新接管采用静态布局壳与局部内容揭示

- 决策日期：2026-07-22
- 当前状态：本地实现
- 决策内容：HTML 在 React 和认证代码执行前按本地布局快照绘制背景、导航、标题栏、Feed 轮廓和可停靠的 Agent 右栏；React 只在认证路由提交后移除静态壳。Feed 与 Agent 初始请求使用固定几何 Skeleton，数据到达后仅由局部层执行 120 ms Skeleton 淡出和 200 ms、4 px 的内容浮现，全局根节点与页面不播放透明度入场。
- 原因：把首帧交给异步 JavaScript 或对整个应用做淡入会在硬刷新时产生白屏、布局宽度跳变和“系统重新打开”的错觉；静态壳与真实布局共享快照，局部揭示则把动效限制在用户正在等待的数据上。
- 影响范围：前端 HTML bootstrap、设计系统加载模式、Feed/Agent 初始数据状态、侧栏与右栏本地布局快照及对应回归测试；精确视觉值只见 `UI_CONTRACT.md`。
- 兼容/回退：快照为浏览器本地 best-effort 数据，缺失或无效时使用折叠导航和关闭右栏；窄屏不自动恢复 Drawer。无 API、数据库、权限、Query Key、Gateway/MCP 或部署变化，删除静态壳和共享加载模式即可回退。

### D048 系统主题与更新日志由前端确定性状态驱动

- 决策日期：2026-07-22
- 当前状态：本地实现
- 决策内容：生产页面在 React 接管前读取 `prefers-color-scheme`，并在系统偏好变化时同步更新唯一设计系统主题；不保存或提供应用内主题覆盖。更新日志采用源码内受控条目、独立 `/changelog#month-YYYY-MM` 路由和响应式月份导航，不从运行日志、任务记录或后端接口动态生成。精确布局与交互只见 `UI_CONTRACT.md`。
- 原因：首帧主题若等待 React 会闪烁，浏览器本地覆盖又会与“跟随系统”语义冲突；把产品更新与运行数据混合会泄露内部状态并产生不可复现内容。确定性的前端主题和版本化日志可同时保证首帧一致、可审查与离线可用。
- 影响范围：前端 HTML bootstrap、设计系统主题、Changelog 路由与账户入口、响应式浏览器回归；不影响 API、数据库、权限、Query Key、Feed snapshot、Gateway/MCP、Worker 或部署开关。
- 兼容/回退：新路由为 additive；无 `matchMedia` 时使用明亮主题安全兜底，旧浏览器本地数据无需迁移。删除路由与日志入口即可回退，不产生服务端数据残留。

### D049 OpenClaw 会话按站点唯一命名并采用扁平时间线

- 决策日期：2026-07-22
- 当前状态：本地实现
- 决策内容：浏览器在有效设备握手后先保存最小权限配对，再以 `Inteliscope · <site> · <random suffix>` 创建会话并对标签冲突重试一次；模型目录统一为 canonical `provider/model`，模型分叉经 `sessions.describe` 验证，兼容分叉保留本轮思考档位。Agent transcript 使用 12 px 装饰时间线、同行称呼/本地时间和 13/20 px 无背景正文，仅安全链接化 http/https。
- 原因：OpenClaw 2026.7.1 对 session label 强制唯一，固定 `Inteliscope` 会让测试与生产共用 Gateway 时无法建会话，并在保存 device token 前失败而遗留重复设备；真实 `models.list` 返回裸 ID 会让模型与思考选择失配。360 px 右栏中的消息卡片又会浪费正文宽度并降低信息密度。
- 影响范围：浏览器 OpenClaw session 创建/恢复、凭据保存顺序、运行时模型投影、per-send thinking、流式消息时间、Agent transcript 视觉与安全链接渲染，以及对应前端回归和 Gateway/UI 合同。
- 兼容/回退：既有按用户/Gateway 保存的 session key 继续直接恢复，旧 transcript 无时间时不补造时间；无后端 API、数据库、权限、Query Key、Remote MCP、OpenClaw 全局默认或部署变化。关闭 Browser Chat 或回退前端即可恢复旧展示，但固定标签行为不得重新引入。

### D050 OpenClaw 浏览器配对采用服务端优先设备移除

- 决策日期：2026-07-22
- 当前状态：实现、完整门禁与本地容器验证完成；生产发布验证待执行
- 决策内容：新授权精确协商 `operator.read + operator.write + operator.pairing`，旧 read/write 凭据继续用于普通重连；浏览器先保存 identity/device token，再创建会话并立即保存 session key。“忘记此浏览器”确认后，旧凭据使用保存的 identity/device token 显式请求当前三项 scope，让 Gateway 创建可审计的 `scope-upgrade`；页面显示 request ID 与批准命令，批准前保留本地材料，批准后重试 `device.pair.remove`。仅服务端删除成功或设备已不存在时清除本地 transcript 与凭据。
- 原因：只在建会话成功后保存配对会让每次失败遗留不可复用设备；只删除浏览器 IndexedDB 则让服务端旧授权继续存在。旧凭据若在联网前被前端拦截，Gateway 也无法生成必须由用户批准的 scope-upgrade。
- 安全/兼容：不申请 `operator.admin`。普通重连仍按旧两 scope 工作；只有用户确认删除后才请求 `operator.pairing`，且 OpenClaw 限制非管理员只能删除当前设备。升级待批准或服务端删除失败都不清除本地恢复材料。本决策细化 D049，不改变 Remote MCP、Service API、数据库、模型选择或消息投影合同。

### D051 已吊销 Remote MCP 连接通过独立动作删除单条记录

- 决策日期：2026-07-23
- 当前状态：本地实现、完整门禁与本地容器验证完成；生产发布待执行
- 决策内容：保留 `DELETE /api/me/agent-delegations/{id}` 的幂等吊销语义，新增显式 `/record` DELETE，只允许当前用户删除选中的一条 `revoked_at IS NOT NULL` delegation。`/agents` 的有效连接继续显示“吊销”，已吊销连接只显示经确认的“删除”；有效、仅到期、非本人和不存在记录均不得被该动作删除。
- 原因：把“第二次吊销”解释为删除会让响应丢失后的网络重试误删记录，也混淆令牌失效与列表清理。独立端点和独立确认状态让目标、前置条件和失败语义可验证，同时满足用户只删除一个已吊销连接的需求。
- 安全/兼容：删除查询同时限定 delegation ID、当前用户 ID 与已吊销状态；既有 proposal 按外键级联删除，其他连接、订阅、Feed、来源和用户数据不变。不新增 schema 或依赖，不改变 Remote MCP 认证、权限、令牌期限、有效连接上限，也不触碰 OpenClaw Gateway 浏览器配对。

### D052 成员单元格、OpenClaw 能力与 Feed 定位按真实职责拆分

- 决策日期：2026-07-23
- 当前状态：本地实现、完整门禁与本地容器验证完成；生产发布待执行
- 决策内容：成员管理使用 HeroUI Table 的显式列定义和统一 custom-cell renderer，成员行采用渐变头像、可排序成员/角色/状态表头、无可见标签的紧凑角色选择、语义状态 Chip 与圆形图标操作，并把最小表宽封装在局部横向滚动中；OpenClaw 上下文占用只以圆环出现在模型选择旁，模型菜单按 Gateway 提供商分组，推理档位只来自精确模型或当前会话；Feed 的排序/时间基准变化统一回到列表顶部，实时新内容仍使用各自 fresh edge，深链仍独立居中。
- 原因：原成员行虽已使用 Table，但单元格逻辑散落且仍呈现为表单堆叠，成员身份、状态和动作层级不够清晰；Agent 头部背景卡重复模型和附件信息；Agent 级推理档位可能掩盖模型能力缺失；最旧优先切换到列表底部会让用户首先看到最新数据并误判排序错误。按职责拆开后，成员表格更接近高密度管理面板，界面位置、能力来源和滚动语义都与用户动作一致。
- 取代范围：取代 UI_CONTRACT 中排序变化跳到 active fresh edge、Agent 头部背景信息弹窗，以及缺少精确模型档位时使用 Agent 级回退的部分；保留 D042/D049 的验证后模型分叉、per-send thinking、失败保留原会话和重试快照。
- 安全/兼容：不新增 Service API、数据库或 Gateway 写操作；密码重置继续使用既有可选 password patch，Owner 保护和服务端权限不变。无可信 OpenClaw 用量或推理能力时显式降级，不估算也不补造。

### D053 显式明暗模式与遮挡概览采用浏览器确定性状态

- 决策日期：2026-07-23
- 当前状态：本地实现、前端验收与完整门禁完成；生产发布待执行
- 决策内容：生产外观只开放 `dark | light`，默认 dark 保留既有 graphite 视觉；HTML 与唯一 `DesignSystemProvider` 共用版本化浏览器偏好，右上角图标显式切换，操作系统外观变化不覆盖用户选择。颜色模式与 `graphite-purple` 主题家族分离，为未来新增家族保留单一扩展边界但不提前开放选择。信息概览只有在实测遮挡阅读框时才响应工作台内无交互语义的主指针点击，并以 220 ms `closing` 阶段保持 mounted、hidden、inert 后退出；实际控件、可编辑内容和概览内部不触发。
- 原因：系统跟随无法满足用户主动在白天/黑夜间切换，也会在系统变化时覆盖应用内意图；主题家族与亮度混为一体会让未来扩展重复状态。概览仅绑定 Feed 空白容器使标题、卡片正文和其他无动作区域的点击无效，立即卸载又产生突兀跳变；几何门禁、交互语义过滤和显式退出阶段把关闭范围扩大到用户预期，同时不吞掉真实操作。
- 取代范围：取代 D048 中“只跟随系统、不保存应用覆盖”的主题部分，保留 D048 的首帧确定性原则与源码更新日志决策；细化 D043/D044 的 Insights 浮层交互，不改变其自动出现、查询复用或 Agent 并存规则。
- 安全/兼容：偏好仅含固定主题家族和 `dark | light`，保存在浏览器本地，不含用户、内容或服务端数据；缺失、损坏或未知值回退 dark。无 API、数据库、权限、Query Key、Feed snapshot、Gateway/MCP、Worker、scheduler、来源抓取、AI 或部署变化。

### D054 设置页密钥管理采用局部失败反馈与安全额度投影

- 决策日期：2026-07-23
- 当前状态：本地实现与定向验收完成；未部署
- 决策内容：新增 Key 的校验与服务端失败同时留在密钥表单并发送 Toast，失败仅清空真实值；已配置 Key 使用 HeroUI v3 Table 与行级轮换/删除 Modal。仅 `owner/admin` 可通过用户隔离 Query key 查询 Apify 额度，前端缓存五分钟并允许手动刷新。
- 安全边界：服务端只从 SecretStore 读取 Token，并调用 Apify `/v2/users/me` 与 `/v2/users/me/limits`；浏览器只接收 USD 周期与非负额度数字。Token、账户资料、原始响应、错误正文、日志和数据库均不得承载秘密；额度失败不影响 Key 保存或列表。
- 原因：页面顶部的通用错误离底部表单过远，新增失败缺少可执行反馈；同时管理员需要在不暴露 Token 或账户资料的前提下判断 Apify 套餐和硬上限余量。
- 影响范围：Secret quota service、管理员 secret API、React Service API/Query cache、设置页 Key Table/Modal、API/UI 合同和测试；不新增数据库结构，不触发 Actor、抓取、AI、scheduler 或付费调用。

### D055 Apify 切换采用工作区单一有序池与 Run generation 排空屏障

- 决策日期：2026-07-23
- 当前状态：本地实现、定向验收与完整门禁完成；开关默认关闭，生产排空与 canary 待授权
- 决策内容：Service 的全部 Apify 来源只从工作区粘性 `active + ordered standby` 池取得凭证；每个 Actor Run 持久绑定 `secret_id/version + pool_generation`，start、poll、abort 和 dataset 不得跨 Key。额度/401 失效先把池置为 draining，旧 generation 全部已登记 Run 确认终态后才增加 generation 并启动全新 Run；30 秒未完成或 POST 结果未知时 fail closed。
- 原因：来源级 Key 引用会让同一额度耗尽 Key 继续被不同 Worker 使用，而在原 runId 上直接替换 Token 会把远端执行、dataset 和本地任务归属混在一起。工作区唯一顺序降低维护面，generation barrier 能保证备用 Key 不与额度恢复后的旧 Run 并发抓取。
- 安全/兼容：schema v8 只保存 secret ref、额度安全数值、generation 和内部 Run ledger，Token 仍只在 SecretStore；公共 API/日志不返回账号、runId、datasetId 或上游原文。`source_catalog.secret_env` 仅作回滚数据；`HORIZON_APIFY_KEY_POOL_ENABLED=false` 时继续走 legacy 来源级路径。正式开启前必须停 Worker、核对未登记远端 Run、备份数据库并只做一次有上限 canary。
- 影响范围：ServiceStore/schema v8、Apify client/adapter、pool/runtime services、Worker/Orchestrator/catalog runner、shared acquisition/schedule、管理员 API、source registry、React 设置与来源编辑器、合同、影响映射和回归测试；本分支未调用真实 Key、付费 Actor、AI、scheduler 或生产部署。

### D056 全站终态操作反馈使用单一顶部 Toast 队列

- 决策日期：2026-07-23
- 当前状态：本地实现、定向验收与完整门禁完成；未部署
- 决策内容：设置、订阅、来源任务、Agent、成员和 Feed 的非表单终态反馈统一进入 `DesignSystemProvider` 拥有的顶部 HeroUI Toast 队列，不再通过页面顶部 Notice 或 Feed 横幅改变文档流。成功/信息为 4 秒，警告/失败为 8 秒，最多显示三条；可重试终态在 Toast 内提供一次性重试动作。
- 原因：Key 保存等短暂结果若留在普通页面布局中，会持续占位并推动后续内容；分散的定时器、关闭按钮和反馈状态也容易在轮询重渲染时重复出现。单一设计系统入口可统一时长、覆盖层、去重和跨用户清理，同时保留触发控件上的 pending/queued/running 状态。
- 边界：字段校验、需要修正的表单/Modal 错误、加载失败、禁用/降级状态和权限升级恢复命令继续留在上下文内。Toast 只使用安全投影后的文案，不包含 Key、原始 payload、带凭证 URL 或未脱敏错误；无 API、数据库、权限、Query Key、Worker、scheduler、抓取、AI、依赖或部署变化。

### D057 产品操作手册与更新日志采用双源合并门禁

- 决策日期：2026-07-23
- 当前状态：本地 main 合并与完整门禁完成；未部署
- 决策内容：新增源码受控的 `/manual#manual-*` 操作手册，继续保留 `/changelog#month-*` 更新日志；两者只描述可审查的生产行为，不读取运行日志、任务数据或用户内容。账户菜单与独立“文档与发布”菜单均向上展开，并统一提供操作手册、更新日志和固定 GitHub Releases 目的地。
- 自动维护：任何包含产品代码的 PR/合并都必须同时修改 `manualContent.ts` 与 `changelogEntries.ts`；`scripts/check_product_docs.py` 在既有 Test Gate 的 diff 计划前自动校验，`AGENTS.md` 与 PR 模板记录同一执行要求。测试或控制文档单独变更不伪造产品更新。
- 原因：从提交主题或运行数据自动生成用户文案会混入内部实现、无法解释操作影响，也可能泄露状态；源码双源加确定性合并门禁既能让每次产品合并强制复核，又保持中文说明、页面路径和安全边界可审查。
- 兼容/回退：新路由与外链为 additive，不新增 API、数据库、权限、Query Key、Worker、scheduler 或网络代理。回退页面与门禁即可恢复原账户入口，不产生服务端数据残留。

### D058 订阅管理采用频道聚焦的紧凑列表

- 决策日期：2026-07-24
- 当前状态：本地实现、三视口验收与完整门禁完成；未部署
- 决策内容：“我的订阅”和“来源库”共享频道聚焦的响应式紧凑列表，分别保留当前频道；搜索与既有筛选仍作用于全部来源。“运行记录”、全局导航、Agent 面板和既有弹窗不随本次布局改造。
- 原因：旧的多频道卡片网格同时展开大量来源，难以快速判断当前频道的健康、周期和最近结果；频道聚焦后可以保留完整状态与直接主操作，同时把低频来源动作收进可访问菜单。
- 兼容/回退：精确布局与列定义只见 `UI_CONTRACT.md`。本决策只增加前端视图模型与展示组件，不修改 API、数据库、权限、Query Key、调度语义、来源共享或取消订阅语义；旧 `workspace` 来源继续显示为公共订阅。

### D059 订阅验收收口为低噪声来源卡与紧凑运行记录

- 决策日期：2026-07-24
- 当前状态：本地实现、三视口验收、完整门禁与本地容器复验完成；未部署
- 决策内容：“我的订阅”和“来源库”在所有宽度统一使用低噪声 HeroUI 来源卡；桌面保留频道栏，窄屏使用频道选择器。筛选改为锚定 Popover 与 Select，全局自动更新改为 Switch 与独立周期 Select；运行记录使用单行摘要/时间及默认折叠详情。来源列表不再提供“查看引用”入口。
- 原因：窄桌面和平板验收中，五列语义表、重复状态说明、阻塞式筛选弹窗和按钮式开关造成信息拥挤；引用人数不是订阅管理的高频动作。卡片分层和原位控件可减少阅读负担，同时保留健康、更新结果和主操作。
- 取代范围：取代 D058 中 768–1199 px 使用语义表、固定表格列、查看引用进入更多菜单以及运行记录保持原状的部分；频道选择、筛选作用域和失效回退语义继续有效。
- 兼容/回退：不修改 API、数据库、权限、Query Key 或调度语义；既有 usage API 保持兼容但本页面不再调用。来源健康、分享、编辑、订阅设置、任务生命周期、Toast 和 Agent 上下文行为保持不变。

### D060 订阅控件位置与运行详情采用直接、柔和的交互

- 决策日期：2026-07-24
- 当前状态：本地实现、三视口与 320 px 极窄验收、完整门禁及本地容器复验完成；未部署
- 决策内容：来源健康状态固定使用 HeroUI soft Chip。全部订阅自动更新在所有宽度直接显示无重复文字的 HeroUI Switch，并固定在卡片右上；周期 Select 固定在右下，极窄屏状态独占一行以避免挤压标题。运行记录的技术详情与响应结构改为独立按钮式 Disclosure，以旋转箭头、短过渡、明确展开态和高对比内容反馈交互。
- 原因：浏览器二次验收显示，文字式 Switch 与周期选择并排造成右侧拥挤，移动端折叠成“管理自动更新”又增加一次操作；原生 summary 缺少清楚的悬停、焦点和展开反馈。固定角落位置与受控 Disclosure 能降低阅读噪声，并让鼠标、键盘和触屏的状态一致。
- 取代范围：细化 D059 的自动更新和默认折叠详情规则，取代移动端先展开管理区才能操作 Switch/周期的实现；频道、来源卡、权限、任务和筛选语义不变。
- 兼容/回退：纯前端展示与交互调整；不修改 API、数据库、权限、Query Key、调度语义或抓取行为。`prefers-reduced-motion` 下禁用 Disclosure 过渡。
### D061 偏好来源通知采用提交后 outbox 与双启用水位

- 决策日期：2026-07-24
- 当前状态：本地实现、定向验收与完整门禁完成；未部署
- 决策内容：每个账户在邮箱或 Webhook 中选择一个活动通知通道，每个订阅再显式选择是否接收新内容。只有相邻用户 Feed 快照中新出现、且 `published_at` 严格晚于账户通知启用时间和订阅通知启用时间的稳定条目，才在 Feed 快照、来源健康和任务成功同一事务中写入幂等 outbox；账户与订阅每次关闭后再开启还会推进不可回退 generation，Worker 提交事务后只发送仍匹配当前双 generation 的 delivery。
- 原因：只比较“数据库里是否见过”会把首次快照、共享复用和重新启用前的历史误判为新消息；只用墙钟水位又无法可靠抵抗时钟回拨；把网络发送放进获取事务或任务重试路径还会让接收端故障触发重复抓取。相邻快照、双水位、双 generation、事务 outbox 和提交后发送把“什么是新内容”与“如何投递”分别固定在可验证边界。
- 安全边界：用户 Webhook 地址只经 SecretStore 写入，SQLite 仅保存用户专属环境变量名与 SHA-256 一致性摘要，API、outbox、日志和页面只暴露配置状态；摘要不匹配或文件/数据库更新中断时 fail closed，显式清空删除无引用 orphan。Webhook 仅用 HTTPS、公共网络固定解析、单地址单次 POST，并禁用代理和重定向。`personal_only`、首次快照、旧/复用数据、无任务共享协调、内容修复和模拟测试均不产生真实 outbox；测试受 SQLite 原子 60 秒用户级冷却且不移动水位。同一用户/渠道/Job 最多 20 个 distinct article ID 及其全部 provenance ledger 按文章去重后合并为一次外呼；发送前用双 generation、可信 delivery 创建时间、来源发布时间和当前双水位共同排除关闭后重开的旧 epoch。发送失败不回滚已成功的 Feed 任务，transport 结果未知时保持 `sending` 且不自动重试不具备端到端幂等保证的外部请求。
- 兼容/回退：schema v9 为 additive，缺失设置与旧订阅均视为通知关闭；旧客户端忽略新增字段即可继续工作。关闭账户或订阅通知会停止后续入队，不删除 Feed 历史，也不调用 legacy publisher、旧 webhook 或 scheduler 推送链。

### D062 Service 邮件采用工作区 Provider Registry 与测试代数门禁

- 决策日期：2026-07-24
- 当前状态：本地实现、定向验收、完整门禁与本地容器复验完成；未部署
- 决策内容：Owner/Admin 通过 schema v10 为工作区统一配置发件服务，普通用户只保存自己的收件邮箱。首版 Registry 只允许 QQ、网易、Gmail、Resend 与 Amazon SES 的固定 SSL/465 预设，host、port、TLS 与登录名由服务端根据 Provider、发件地址及受限 SES Region 派生；不开放自定义 SMTP，也不接入需要 OAuth 的 Microsoft 365。凭据只进入工作区确定性 SecretStore 变量，数据库仅保存变量名与 SHA-256 摘要。
- 门禁与故障语义：Provider、发件身份或凭据变化推进 generation、自动停用并清除测试状态；只有当前 generation 真实测试成功且每次读取的 SecretStore 值仍匹配摘要时才能启用。管理员测试使用一次性收件人和工作区 60 秒原子冷却；API 测试与 Worker 复用同一 `EmailTransport`、系统 CA、20 秒 timeout 与 MIME/HTML 转义。轮换、停用或删除只终结尚未开始的 email pending；已经 `sending` 或连接中断的结果未知记录保持未知且不自动重放。
- 原因：让每个用户配置发件账号会扩大秘密数量与支持成本；继续读取 `data/config.json.email` 又会把 Service 权威配置与 legacy CLI 混在一起。固定 Registry 可以在不允许浏览器指定任意 SMTP 主机的前提下覆盖小团体常用服务；generation 测试门禁让凭据轮换后的“已测试”状态不可误继承。暂停期间继续保存 Feed 基线且不写 email outbox，能在恢复后自然只发送之后的新差集，而不形成历史补发队列。
- 兼容/回退：schema v10 additive，缺 row 等同邮件 transport 未配置；已有 email opt-in 保留但投影为暂停，Webhook 不受影响。删除工作区 row 与确定性 SecretStore 值即可回退 Service 邮件能力，不修改 Feed、订阅水位或 legacy `data/config.json.email`；后者继续只供显式 CLI/日报兼容路径使用。

### D063 Browser 运行记录交接直接使用安全任务诊断

- 决策日期：2026-07-24
- 当前状态：本地实施与验证完成；未部署
- 决策内容：Browser Agent handoff 升级为 V4。Feed 记录继续以内部 article ID 调用 `get_item`，用户主动选择的运行记录以内部 job ID 直接调用只读 `diagnose_job`；最多八条混合上下文对应最多八次初始读取。Prompt 只要求持久化安全证据、显式未知与只读建议，禁止重试、取消、修复或其他写操作。
- 原因：运行记录此前只路由到 `get_job`，只能读取状态摘要，无法获得已经由 Remote MCP 安全投影的原因、证据与建议；先 `get_job` 再 `diagnose_job` 又会让八条上下文超过十次工具 burst。复制 UI detail/error 原文既不能提高证据质量，也会扩大不可信提示面。
- 兼容/边界：浏览器 sessionStorage v3 结构和八条上限不变；可见历史继续识别 V3 与旧无版本 handoff，并隐藏内部 Prompt 和 ID。无 Service API、MCP schema、权限、数据库、Worker、scheduler、来源抓取、AI 配置或自动任务变化。

### D064 Feed Insights 先复用居中阅读列的左侧空白

- 决策日期：2026-07-24
- 当前状态：本地实施与验证完成；未部署
- 决策内容：352 px Insights 继续作为右侧浮层而非第三列。用户手动打开时，ViewBar、Feed 卡片、Skeleton、空态和错误态作为一条 reading surface 等量左移，先消耗默认居中产生的左 gutter，并在主内容左侧保留 12 px；只有剩余空间仍不足时才允许覆盖卡片。面板位置和让位量以当前 main、侧栏及可拖拽 Agent rail 的实测几何为准。
- 原因：固定右锚点直接覆盖卡片会浪费 reading surface 左侧的可用空间；把 Insights 换到左侧或压窄 820 px 卡片列则会改变用户已确认的视觉位置与阅读排版。统一平移能利用现有空白，又保持卡片宽度和纵向虚拟列表锚点。
- 兼容/边界：自动展示仍只在原始右 gutter 至少 376 px 时发生，不因新算法扩大自动出现范围；移动端仍使用 Bottom Sheet。让位使用既有 220 ms motion，Agent 指针缩放立即跟手，Reduced Motion 立即完成。无新 API、Query、数据库、图表依赖、Feed snapshot 或运行任务变化。

### D065 诊断日志采用私有双流文件与当前用户 MCP 投影

- 决策日期：2026-07-24
- 当前状态：本地实现、定向验收与完整门禁完成；未部署
- 决策内容：API、Worker、legacy Scheduler 与 CLI 共用 UTC 每日轮转的 runtime/operation JSONL；默认保留 30 天并固定私有权限。关键状态变化只写有界 schema-v1 事件，成功必须在提交后产生。OpenClaw 新增只读 `query_operation_logs`，只投影当前 delegation workspace 中 actor 或 subject 为当前用户的脱敏事件；Owner/Admin 无跨用户例外。
- 原因：仅靠自由文本运行日志难以用 request/Job/source/subscription ID 串联问题，也不能安全进入 Agent 上下文；数据库审计表又会引入迁移、备份与产品数据生命周期。独立结构化文件可提供足够诊断关联，同时把原始 runtime、身份和文件系统细节留在服务器。
- 安全/产品边界：不新增数据库表、日志 REST API 或前端日志页面。日志不记录凭据、目的地、URL、config/payload、环境变量名、个人标签、文章 ID/正文、上游响应或确认短语；MCP 再执行白名单、扫描上限、损坏行跳过、符号链接拒绝和当前用户隔离。普通 GET、Feed 浏览、item state、空轮询与 heartbeat 成功不落 operation event。
- 兼容/回退：`HORIZON_LOG_RETENTION_DAYS` 缺省 30、合法范围 1..365；关闭 Remote MCP 或移除该 read tool 不影响文件日志。回退代码和 toolFilter 后可保留既有 JSONL 到自然过期，不需要数据库迁移或数据恢复。

### D066 Feed 数据重载与后台更新采用独立完成边界

- 决策日期：2026-07-24
- 当前状态：本地实施、三档验收与完整门禁完成；未部署
- 决策内容：Feed ViewBar 将只读 `刷新` 与后台 `更新` 拆为两个同行动作。`刷新` 对所有角色强制读取当前用户最新 snapshot，不检查 Worker、不创建 Job；pending 时保持文字和几何不变，只旋转图标并暴露忙碌状态。`更新` 保留既有权限、Worker 预检和任务语义。浏览器观察到本会话中的整份或单源 Feed 任务成功/部分成功后，必须先完成最新 Feed 读取，再发布“已完成”反馈；数量使用 Feed 写事务内相邻去重 snapshot 稳定 ID 的实际新增差集。
- 原因：任务终态只证明服务端 snapshot 已提交，不能证明浏览器缓存已经重读。此前来源任务在 inactive Feed query 上 fire-and-forget 失效缓存，并立即显示后端 item count，导致完成提示先于新卡片出现；该条数是整份 snapshot 总量，`fetched_count` 又是合并前抓取量，两者都不是用户关心的实际新增。刷新按钮把文字切成“刷新中”还会改变中等宽度 ViewBar 的固有宽度并造成横向抖动。
- 兼容/边界：复用既有 `/api/feed/latest`、`user_feed_refresh` 与 `source_fetch`；Job `result_json` 只增加可选非负整数 `new_item_count`，旧任务缺少时 UI 不推测数量。REST 路径、数据库、权限和 snapshot payload 不变。重载失败保留最后可信卡片并提供手动重试；排序、新内容边缘、虚拟列表锚点和 `N 条新内容` 行为保持不变。页头主题/Insights/Agent 顺序和卡片 Footer 顶部 Tooltip 只属于 `UI_CONTRACT.md` 的呈现规则。

### D067 RSSHub 采用单 VPS 鉴权服务与语义来源身份

- 决策日期：2026-07-25
- 当前状态：本地实现、双环境迁移、release 门禁、VPS 部署与鉴权边界验收完成；Bilibili 上游冷路由保留明确降级
- 决策内容：只在 `vps-tokyo` 运行一套 `chromium-bundled` RSSHub。容器加入生产应用网络并把 1200 仅绑定 VPS loopback；VPS Inteliscope 使用 `http://rsshub:1200`，本地项目通过现有 Nginx HTTPS 前缀使用 `https://rb.jiefs.top/rsshub`，不使用 SSH tunnel。Owner/Admin 可在 Settings 修改 RSSHub Base URL，因此自建和第三方实例可互换，本地不运行第二套 RSSHub。
- 来源与 Agent 合同：RSSHub 是 workspace runtime service，不是 catalog type。Bilibili UP 视频仍保存为 catalog `rss`，稳定身份为 `rss:rsshub:bilibili:user_video:<uid>`；OpenClaw 新增公开 `bilibili` 类型，只提交 allowlisted `site=bilibili`、`route_key=user_video`、正整数 `params.uid` 和可选 `keep_latest_item`。MCP guide、preview 与 discovery 不返回 Base URL，且不接受任意 RSSHub URL/path、Cookie、ACCESS_KEY 或凭据。
- 安全/兼容：运行 URL 只由管理员 Base URL 与服务端 allowlist 拼接，允许安全反向代理 path prefix，受控抓取禁用 redirect。自建公网入口强制使用 SecretStore `RSSHUB_ACCESS_KEY`，Worker 只发送 `md5(route path + key)` 派生的 route-scoped code；主密钥不进入 URL、配置、catalog、MCP、OpenClaw、Feed 或日志。direct RSS 的公网 egress/管理员私网信任边界不变。迁移只精确识别 `/bilibili/user/video/<uid>[/1]`，先备份 config/SQLite，再原位更新 source config/key，保留 source、subscription 和 schedule ID。切换 Base URL 不改变来源 key 或订阅状态。
- 原因：测试环境需要本地公网直连而不维护 tunnel；裸 HTTP 会暴露密钥，直接开放容器端口又绕过现有 TLS/限流。单 VPS loopback 容器、现有 Nginx HTTPS、RSSHub 原生访问控制与语义路由同时满足直接复用、可替换和小规格 VPS 资源约束。

### D068 Inteliscope 生产镜像只允许本地跨架构构建

- 决策日期：2026-07-25
- 当前状态：控制规则与旧 RC 脚本已修正；release 门禁及 revision `215aab17c37e` 首次本地 AMD64 构建、校验、上传和 VPS `docker load` 发布完成
- 决策内容：Inteliscope production image 必须从干净、revision-locked commit 在本机使用 Buildx 构建 `linux/amd64`，完成本地门禁/镜像身份检查后压缩上传，在 `vps-tokyo` 只执行校验与 `docker load`。VPS 禁止对本仓库执行 `docker compose build` 或 `docker build`；仅允许 pull RSSHub 等 pinned third-party runtime image。
- 原因：2026-07-22 已因沿用旧脚本远端构建而纠偏为本地传包，但规则只留在 WORKLOG 且旧脚本未同步；2026-07-25 再次远端构建令 1.6 GiB VPS 出现整机资源争用。把发布地点提升为硬约束并让脚本符合规则，可避免执行者忽略历史记录后重复事故。
- 安全/回退：构建位置变化不改业务镜像内容、数据库、Compose 服务或回滚模型。源码归档与镜像必须绑定同一 revision；VPS 保留旧 release/image，切换前仍执行 `0600` 数据/配置备份和 Worker-first rollback。

### D069 RSSHub 的 Bilibili 匿名运行态由隔离浏览器刷新

- 决策日期：2026-07-25
- 当前状态：VPS 配置、SecretStore 写入、真实 UID 单次成功与公网验收完成；连续不同冷请求仍可触发 Bilibili `-352` 并超时
- 决策内容：固定摘要的官方 `chromium-bundled` 镜像显式配置其实际容器内 `CHROMIUM_EXECUTABLE_PATH`，并使用 RSSHub 官方 `NO_RANDOM_UA=true`。Bilibili 公开路由所需 `_uuid`、`b_lsid`、`b_nut`、`buvid3`、`buvid4`、`buvid_fp` 只能由 `scripts/refresh_rsshub_bilibili_cookie.sh` 在无 profile、无账号的全新浏览器 context 中访问公开首页与动态页取得，缺失的 `buvid3/buvid4` 可由公开 fingerprint SPI 补齐；结果经匿名管道写入 VPS SecretStore 的 `RSSHUB_BILIBILI_ANONYMOUS_COOKIE`，再映射为 RSSHub `BILIBILI_COOKIE_0`。
- 原因：该固定镜像的 Patchright 默认查找 `/root/.cache`，但 Chromium 实际位于 `/app/node_modules/.cache`；默认随机浏览器 UA 被 Bilibili 返回 412，而不完整匿名参数会更早触发风险控制。显式浏览器路径、RSSHub FeedFetcher UA 和完整匿名参数曾让真实 UID 在约 6 秒内返回 30 条，但连续不同冷请求仍会被上游返回 `-352` 并进入浏览器 fallback 超时；这是可替换外部服务的可用性限制，不是匿名 Cookie 能消除的保证。
- 安全/回退：刷新脚本先以 `0600` 备份 SecretStore，不读取本机或用户浏览器 profile，不接受或输出账号 Cookie，真实值不进入 Git、配置、数据库、MCP、OpenClaw、Feed 或日志。失败时保留旧 SecretStore；可恢复备份、recreate RSSHub，或在 Settings 把 Base URL 切换到第三方实例。

### D070 本地初始化主动对账仓库托管的 OpenClaw Skill

- 决策日期：2026-07-25
- 当前状态：安装脚本、定向测试、本机覆盖安装、Gateway 重启与新会话只读 smoke 完成
- 决策内容：`setup_openclaw_local.py` 不再把“存在 inteliscope Skill”等同于“版本正确”。它比较 bundled 与 `openclaw skills info` 返回目录中的托管文件，忽略 OpenClaw 安装元数据；缺失时安装、内容漂移时 `--force` 刷新，且只在 Skill 或 Origin 变化时重启已运行 Gateway。刷新后用新会话验收，现有会话不作为新路由合同的证据。
- 原因：VPS MCP 已提供 `bilibili` 指南，但本机 2026-07-20 的旧 Skill 仍把 Bilibili 路由成普通 `rss`，导致模型成功调用错误类型的指南并索要公开 RSSHub URL。仅检查 Skill 是否可见无法发现这种跨版本漂移。
- 安全/兼容：该 reconcile 只管理仓库拥有的 `inteliscope` Skill，不读取或写入 MCP/Gateway token，不调用订阅 prepare/apply；`--skip-skill` 保留显式退出。旧 Skill 已以 `0600` 本地备份保留，回退时可恢复并重启 Gateway。

### D071 OpenClaw 通过固定 Bilibili 公开查询把账号名称解析为 UID

- 决策日期：2026-07-25
- 当前状态：本地实现、full/release 门禁、VPS 发布、真实 RSSHub Feed 与 OpenClaw 全新会话验收完成
- 决策内容：Remote MCP 新增只读、non-destructive、idempotent、open-world 的 `search_bilibili_users`，使 OpenClaw 可把用户明确提供的 Bilibili 账号名称解析为受控订阅所需 UID。服务只访问固定 Bilibili 首页和官方用户搜索端点，在单次内存 client 中先取得匿名设备 Cookie，再返回最多五个仅含名称、UID、官方主页和精确匹配标记的候选；只有唯一规范化精确同名时才生成 `resolved_user`。OpenClaw 必须优先复用现有来源；无现有精确名称时调用该工具，唯一精确命中可直接 prepare，多候选必须交给用户选择，仍保留 `prepare → 准确确认 → apply` 写入边界。包含“订阅/关注/添加”和“B站/Bilibili/UP主”的请求即使未提 Inteliscope 也必须进入该 Skill，禁止为名称解析调用 Chrome、浏览器、Web 搜索或 shell。
- 原因：仅把 RSSHub URL 输入收窄到 UID 仍要求用户手工查主页，不能完成“给出 UP 主名称后自行建立订阅”的产品目标。VPS 直接调用用户搜索接口会返回 `-412`，而先访问 Bilibili 首页取得无账号匿名 Cookie 后同一 VPS 可稳定得到“食贫道 → 39627524”；因此名称解析必须由服务端显式建模，而不能让模型猜 UID。
- 安全/回退：查询拒绝 URL、身份字段和凭据，禁用环境代理与 redirect，使用固定 timeout、512,000-byte 上限及 300/30 秒缓存；不接收或复用账号 Cookie，不投影签名、粉丝数、视频数或上游正文，候选名称标记为不可信公开 metadata。上游不可用返回稳定 `availability=unavailable` 且不得猜测；移除该工具和 toolFilter 后，既有 UID/主页输入、受控 RSSHub 路由与已创建订阅继续可用，不需要数据库迁移。

### D072 Browser OpenClaw 按附件存在性拆分直接请求与只读交接

- 决策日期：2026-07-26
- 当前状态：本地实现、定向回归、full/release 门禁、VPS 发布与真实 OpenClaw preview 验收完成
- 决策内容：Gateway handoff 升级为 V5，并把浏览器提交明确拆为两种模式。有一条或更多 Feed/任务记录时使用 `context_readonly`，继续按 D063 只读分析；没有记录且问题非空时使用 `direct`，保留用户直接提出的请求，允许既有订阅 Skill 执行 `prepare → preview → 准确确认 → apply`。普通 direct 请求只可 prepare；只有下一条问题与当前 proposal 返回的准确确认短语完全一致时才可 apply。
- 原因：V4 无条件追加“不得执行任何写操作”，导致用户已在浏览器明确要求创建订阅、甚至已另行回复准确确认短语时，OpenClaw 仍被前端提示词要求拒绝所有写工具。MCP delegation、写开关和 proposal 均正常，因此根因是浏览器把直接请求错误当成文章/任务交接，而不是服务端授权不足。
- 安全/兼容：direct 提示词不得代用户生成、改写或回答确认短语，也不得绕过 delegation scope、实时角色、写开关、proposal 到期/指纹与事务复查；有附件的正文和任务证据仍不可触发写入。可见历史继续投影 V4、V3 与旧无版本 handoff。回退 V5 前端即可恢复旧只读行为，不涉及 API schema、数据库、RSSHub、Worker、来源抓取或 OpenClaw 全局配置。

### D073 RSS 首次抓取窗口以首个成功健康记录为边界

- 决策日期：2026-07-26
- 当前状态：本地实现、定向回归、三视口浏览器验收与完整门禁完成
- 决策内容：直接 RSS 与受控 RSSHub 订阅在当前用户尚无 `last_success_at` 时使用可配置的 7 天或 30 天首次窗口；每条来源独立判断，抓到零条也算成功并在下一次恢复日常窗口。失败和自动重试继续使用首次窗口，显式 `hours` 始终优先。
- 原因：新订阅用日常短窗口容易看不到足够历史内容，而永久扩大所有 RSS 抓取会增加上游负载并改变日常刷新成本。复用既有用户级 Source Health 的成功事实可以同时覆盖单源、混合来源与 RSSHub，又不增加迁移或重复状态。
- 兼容/边界：缺少新配置按 168 小时处理，只允许 168/720；窗口覆盖仅放入不持久化、不对外序列化的单来源运行配置。它只改变采集起点，不改变 Feed 留存、通知水位、来源身份、共享边界、任务 API 或数据库 schema。

### D074 OpenClaw 运行反馈与紧凑 UI 按语义拆分

- 决策日期：2026-07-26
- 当前状态：本地实现、明暗主题三视口验收、完整门禁与 VPS 发布完成（revision `74c7b16d715b`）
- 决策内容：Browser OpenClaw 在发送当帧建立只存在于页面内存的运行轨迹，并把当前 session/run 的 Gateway lifecycle、tool 与 thinking 事件投影为去重、有界、可折叠的安全中文状态；不支持事件时继续显示本地可信状态。紧凑 UI 不再共用一种微型 Chip，而拆为 `StatusIndicator`、`MetaTag`、`CountBadge` 与 `RemovableTag`。来源分享/编辑收敛到一个按权限裁剪且可恢复焦点的 More 菜单，Feed 卡片则把格式/图片变为平面元数据，并保留一个弱化频道标签和 `#主题` 文本。
- 原因：Gateway 已产生工具和运行事件，但浏览器此前丢弃非 chat 事件，形成明显首字前空白；同时连接、健康、权限、范围、格式和计数使用同一种“小字、大胶囊”，使状态层级难以辨认。把运行真相投影为安全过程反馈，并按状态、元数据、数量和编辑动作分型，可以改善等待感和可扫描性而不依赖 HeroUI Pro 源码。
- 安全/兼容：原始思维、参数、结果、meta、错误、URL、令牌与确认短语不得显示或持久化；活动轨迹刷新后不恢复。无新 Service API、Gateway schema、数据库、权限、MCP 工具或后端持久化。HeroUI Pro 仅作为交互语法参考，实际组件继续基于仓库现有 HeroUI OSS 独立实现。

### D075 高密度状态、危险操作与设置导航采用渐进披露

- 决策日期：2026-07-26
- 当前状态：本地实现、定向回归、明暗主题三视口验收、完整门禁、本地重建与 VPS 发布完成（revision `74c7b16d715b`）
- 决策内容：D074 的语义分型保留，但高密度的来源健康、运行记录、自动更新、Agent 连接/配对和 OpenClaw 顶栏改为带完整辅助名称与悬浮/聚焦 Tooltip 的图标状态；Notice、Toast、Dialog、运行轨迹和恢复建议仍显示文字。来源编辑改为直接 Pencil，来源 More 只在允许分享时出现且只含分享。Agent 连接把复制、重命名及按状态裁剪的吊销/删除收进中性 More，只有最终确认使用实心 danger。桌面设置目录从正文移至侧栏设置入口的延迟悬浮/即时聚焦浮层，手机和粗指针保留页内选择器。订阅 Tab 移除常驻计数并以 `?tab=` 深链接，计数迁入信息概览的独立加载区。
- 输入边界：OpenClaw 编辑器在 composition ref、原生 `isComposing` 或 WebKit `keyCode=229` 任一成立时，把 Enter 只交给输入法确认且不发送；普通 Enter 仍单次发送，Shift+Enter 换行。不采用时间防抖，以免吞掉下一次真实提交。
- 原因：常驻红色操作和文字状态在高密度卡片中抢占了正文注意力，设置页目录长期占宽，Tab 数量又把运行历史误表现成需要持续关注的徽标；同时中文输入法确认候选会经过 Enter，若只按键名判断就会在句子未完成时误发。
- 兼容/边界：本决策明确替代 D074 中“状态必须常驻文字”和“来源分享/编辑同一 More”的呈现约定，不改变其安全事件投影。复用既有订阅、来源、任务、Agent delegation 与设备移除接口，不新增数据库、Service API、Gateway schema、权限或持久化；最近运行只陈述现有最多 100 条返回记录，不宣称全量历史。

### D076 Browser Agent 允许桌面后台运行并保留安全来源引用

- 决策日期：2026-07-27
- 当前状态：本地实现、定向回归、完整门禁与三视口浏览器验收完成；未部署
- 决策内容：桌面端 OpenClaw 运行时允许隐藏 Agent，WebSocket、session、对话和生成继续挂载；顶部 Agent 入口以带形状和文字语义的运行/完成/失败/停止状态及终态 Toast 提醒用户，重新打开后清除待查看状态。移动端运行中仍固定 Bottom Sheet 以保留 Stop。Agent 默认宽度提高到 400 px，输入区提高到 64–160 px；Feed ViewBar 增加路由隔离搜索并将排序、重载、更新和筛选收为带说明的图标操作。固定 Agent 与 Insights 在实测空间足够时共存，只有发生实际阻挡才柔和关闭 Insights。
- 来源交接：Gateway handoff 升级为 V6，Feed 上下文可附带经过协议、凭据、fragment、跟踪参数、敏感 query 和长度收口的原文 URL。发送前和发送后的用户消息都用本地 HeroUI `ChatSource` 呈现该安全引用；OpenClaw 仍须先用内部 article ID 调用 `get_item`，URL 只用于来源核验或用户请求的可选 Web 分析，网页内容不成为可信指令。模型菜单继续按 Provider 分组，思考档位只展示精确模型/会话能力，用量统一以 `k` 表示。
- 原因：强制展开运行面板会持续占用阅读空间，裸色点又不足以表达需要用户处理的终态；清空草稿后丢失来源入口也使多轮对话难以回查。保留运行实例、显式语义提醒和清洗后的来源引用，可以在不扩大数据权限的前提下兼顾工作区与可追溯性。
- 兼容/边界：浏览器继续投影 V5、V4、V3 与旧无版本 handoff，旧 ID-only 草稿按用户范围补载显示字段；无 Service API、数据库、Gateway RPC schema、MCP 权限、Worker、scheduler、来源抓取或 AI 配置变化。HeroUI Pro 只作为交互参考，组件基于仓库现有 HeroUI OSS 独立实现。

### D077 核心设置原子总保存并明确高密度交互所有权

- 决策日期：2026-07-27
- 当前状态：本地实现、完整门禁、容器重建和浏览器验收完成；未部署
- 决策内容：配置兼容 facade 增加 `set_settings_bundle`，把 AI、RSSHub、抓取/筛选和主题库作为可独立变脏、可局部保存且可一次总保存的核心分区；后端在副本上复用既有单项校验，全部通过后只写盘一次，草稿回到配置基线时实时清除假脏状态。OpenClaw transcript 成为面板唯一主滚动区，外壳与 composer 不拥有纵向滚动，textarea 只在超过 160 px 后局部滚动。订阅固定视图增加公共/私人分区，私人来源分享改为卡片直接操作，Feed/Saved/History ViewBar 的图标说明使用向下锚定预设。
- 原因：多个核心表单逐项保存容易遗漏且无法保证跨分区一致性；隐式 `overflow-x-hidden` 会形成第二个纵向滚动容器；只有一个动作的 More 增加了移动端操作成本，顶部 ViewBar 的向上说明也会挤出可视区域。
- 兼容/边界：原有单项配置动作、局部保存入口、通知、邮件和密钥安全流程继续存在；bundle 仍只允许 Owner/Admin 且不改变响应结构。旧 `workspace` 来源只在 UI 派生中归入公共订阅，不改写数据库；来源分享继续复用原权限、接口和确认对话框。Insights 的整个工作台非交互退出热区保持 D076 的测量与 220 ms 柔和退出语义；Agent 已打开时仍允许手动查看会遮挡 Feed 的概览，随后由工作台非交互点击退出。

### D078 历史列表以用户稳定内容索引为真源

- 决策日期：2026-07-27
- 当前状态：本地实现、定向回归完成；未部署
- 决策内容：`/api/feed/history` 的 item 真源从最近 20 份 Feed snapshot 拼接改为 `user_content_items`，先排除最新 Feed，再按完整 source provenance 和公开字段搜索，最后分页；最近 20 份 snapshot 只保留为摘要与 featured 历史证据。Source Health 同时投影最近抓取、当前 Feed 与稳定历史三个互不混用的计数。X/Instagram profile 只接受抓取窗口内帖子，只有旧帖时按成功空结果处理；Facebook/Telegram 的既有 stale fallback 不变。
- 原因：低频来源的稳定内容可能早于第 20 份 snapshot，数据仍在本地却无法从 UI 到达；同时 `last_fetched_count` 表达 Actor 返回量，拿它当当前 Feed 数会造成“卡片显示 2 条但列表找不到”的错误认知。稳定索引已有用户隔离、保留和 provenance，适合作为历史查询真源。
- 兼容/边界：无数据库迁移，不重写现有内容或 snapshot，不把旧帖重新放回当前 Feed，也不重新计算历史精选。原有 `item_count == len(items)`、最近 20 份 snapshot 摘要、管理员目标用户隔离和单项 Source Health 字段继续兼容；新增查询和计数字段为 additive。实现与验证不得自动触发真实 Apify 付费抓取。

### D079 稳定内容按上海自然日分层并采用预演式冷归档

- 决策日期：2026-07-27
- 当前状态：本地真实数据显式迁移、完整门禁和容器复验完成；未部署
- 决策内容：`user_content_items.effective_at` 成为 Feed、History、来源计数与搜索共同的稳定展示时间；可信发布时间优先，缺失、非法或异常未来值回退到首次入库时间，重复抓取不得改写它。工作区统一选择近 `7/14/30` 个 `Asia/Shanghai` 自然日作为 Feed，边界之前严格属于 History；当天是 Feed 的服务器分桶子集。Feed 顶部搜索改为独立的全部内容搜索，覆盖当前 Feed、在线历史和冷归档永久元数据，并按 `effective_at DESC, article_id ASC` 返回 `今天/近N天/历史` 归属。
- 存储治理：Feed Storage v3 与 content timeline v11 是清理/归档前置门禁。标准清理只处理有界临时数据、完成任务、缓存、使用记录、过量 snapshot 和孤立媒体；稳定内容永不进入自动清理。超过 90 天的在线历史可写入带校验和的冷归档，只有归档文件写入、校验和数据库提交全部成功后才移除在线正文与媒体。标题、来源、链接、摘要、展示时间、搜索字段和批次事实永久保留。Owner/Admin 只能先预演再应用清理、归档和恢复；只有 Owner 可对已经恢复且不再被在线记录引用的归档执行准确短语二次确认删除。系统不提供任意 SQL、原始路径删除、在线 `VACUUM` 或自动永久删除。
- 原因：snapshot 新鲜度、抓取结果数量和内容发布时间是不同事实；用最新 snapshot 或 `last_seen_at` 决定 Feed 会让低频旧帖不可达或反复回流。稳定时间索引可以在不抓取、不复制内容的情况下即时切换 7/14/30 天边界，并让来源计数、历史和搜索保持无重叠无遗漏。预演、候选指纹、迁移门禁与提交后文件清理把管理员日常治理限制在可核对范围，同时为后续迁移 PostgreSQL 保留明确的在线/冷数据边界。
- 兼容/回退：`feed_window_days` 缺失按 7 天；`current_item_count` 保留并等于 `feed_item_count`。旧单项配置动作、24 小时日常抓取、168 小时 RSS 首次抓取、收藏/稍后读/通知保护和最近 20 份 snapshot 摘要继续兼容。v11 为带 `0600` 备份的显式迁移；未迁移数据库的 API、Worker 与计划任务 fail closed。关闭新前端入口或恢复 7 天配置不会删除稳定内容或修改 snapshot，也不得触发真实付费来源抓取。

### D081 本地 Worktree 重建分离源码根与运行时根

- 决策日期：2026-07-28
- 当前状态：本地实现与定向回归完成；未部署
- 决策内容：`scripts/up-latest.sh` 是本地 API + Worker 重建的唯一入口。源码、构建上下文、产品版本、revision 与本地镜像标签始终取自执行脚本的目标 Worktree；`.env`、`data` 与 `logs` 默认通过 Git common directory 解析到主 checkout，并以绝对路径传给 Compose，只有显式 `--runtime-root` 才切换运行时根。脚本把 build、recreate、revision/readiness、Worker ready、API/Worker health 与 React 资源校验收进一个完成边界，并以主机级 Compose project 互斥锁阻止不同 Worktree、clone 或 runtime root 并发替换同一套本地服务。
- 原因：隔离 Worktree 不包含被 Git 忽略的真实运行配置和数据库，旧脚本却把脚本目录同时当作源码根和运行时根，导致端口回落、错误数据挂载和临时 Compose override；同时 `.env` 可以覆盖构建身份，build 与 up 分段执行又会把中间状态误当作完成。显式拆根与单一终态可让固定操作被脚本和测试表达，而不是每次由 Agent 重新推演。
- 安全/兼容：默认仍只启动 API + Worker，不启动 scheduler、来源抓取、AI 或推送；本地默认端口统一为 8080。脚本启动前拒绝符号链接或缺失的 `.env/data`，不输出配置内容；`migration_required` 会先停止并确认 API/Worker 已停，对当前已知迁移给出显式、带备份的命令，未知迁移要求人工检查，普通重建绝不自动修改数据库。生产继续使用 revision-locked 的 `release_rc1.sh`，不复用本地启动器。
