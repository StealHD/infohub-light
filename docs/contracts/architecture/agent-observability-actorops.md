### 3.6F Local Agent / Remote MCP Boundary

OpenClaw 的模型、对话、推理和 Skill 运行在每位用户自己的电脑或其专属云端 Gateway；Service 端不新增 Agent、LLM、Worker、端口或容器，也不代理 Gateway。浏览器的 `frontend/src/features/openclaw/` 直接实现 OpenClaw Gateway WebSocket v4、设备签名、用户/Gateway 隔离凭证库和有界聊天状态；功能关闭时不得创建 WebSocket。未来从本地切换云端只替换为用户专属 `wss://` URL 和对应 Origin allowlist，不改变 Remote MCP 或 Service 部署。

`scripts/setup_openclaw_local.py` 是仓库托管 Inteliscope Skill 的本地 reconcile 入口：比较 bundled 与已安装目录中的非隐藏文件，忽略 OpenClaw 自己的 `.openclaw` 元数据；缺失时安装，漂移时使用 `--force` 刷新，并只在 Skill 或 Origin 变化时重启已运行 Gateway。旧会话可能保留历史路由指令，刷新后必须用新会话验收；`--skip-skill` 是保留用户自主管理 Skill 的显式退出路径。该流程不得读取或写入 MCP/Gateway token，也不得触发订阅 prepare/apply。

`src/mcp/remote_server.py` 是现有 FastAPI 上的无状态 Streamable HTTP adapter；13 个读工具分别由 `remote_service.py` 的有界数据投影、`remote_subscription_service.py` 的 registry 引导/发现与公开来源解析 facade、`remote_diagnostics.py` 的确定性只读诊断和 `operation_log.py` 的脱敏事件查询提供，diagnostics 同时承载写连接专用的 prepare facade。`search_bilibili_users` 继续通过 `src/services/bilibili_user_search.py` 访问固定 Bilibili 公开端点；`resolve_source` 只把 adapter 预先核准的官方候选交给下述固定主机解析边界。其余工具全部直接调用 Service/Store 或私有结构化事件文件；任何工具都禁止内部 HTTP 回环、开放式网页搜索或调用未经 adapter 校验的任意 URL。每个 FastAPI app 拥有独立 FastMCP 和 session manager，父 app lifespan 显式管理其生命周期，`/mcp` 与 `/api/*` 共用请求级 SQLite connection scope 和事务泄漏检查。

`src/services/source_resolution.py::SourceResolutionService` 是 Agent 公开来源解析的唯一通用编排边界。adapter registry 决定 source type、可接受 locator、固定官方主机、验证方法和规范 planner envelope；新增媒体 adapter 不新增 MCP 工具、source union 分支或 OpenClaw 连接。服务端不承担开放式搜索：仅名称返回 `discovery_required`，OpenClaw core `web_search` 提供最多五个不可信官方页候选，adapter 必须在任何联网前逐个拒绝未注册主机与路径。第一批 YouTube adapter 复用 `youtube_channel.py`：handle 页只对 `www.youtube.com` 做零重定向、public-only DNS pinning 的显式 2 MB 前缀读取，再完整读取不超过 512 KB 的规范 Atom 并交叉验证频道身份；默认网络请求仍严格拒绝截断响应，不为 Fake-IP、RFC1918、loopback、任意 RSS 或 VPS 放宽网络边界。Bilibili 的既有 `search_bilibili_users` 路径不迁移。

`agent_source_resolutions` 是 schema v12 的短期、actor-bound planner envelope 表；只保存 registry 已验证的 existing/private 输入、安全指纹和到期时间，envelope 内的规范 Feed/config 只供服务端 planner 使用且任何解析工具都不得回传。引用绑定 workspace、user 和 delegation，十分钟到期、每 delegation 最多二十个有效值，并由 maintenance 与 storage governance 清理。`prepare_create_subscription` 只能把同 actor 的有效引用投影回既有 mutation planner；跨 actor、隐藏来源、过期或损坏引用必须 fail closed。

Remote MCP 是唯一 Service MCP，入口固定为 FastAPI `/mcp`；仓库不再提供本地 stdio server、run store 或 legacy adapter。抓取、AI、配置、通知和任何直接写工具不得注册到 Remote MCP。delegation 认证直接生成当前用户主体，不经管理员代理权限；所有业务 object lookup 都在该主体内完成。读操作要求 read scope；prepare/apply 以固定顺序检查 write flag、write scope 和实时角色，viewer 永远只读。唯一工作区诊断例外只存在于 `query_operation_logs`：新 connection 必须由实时 `owner/admin` 显式持有 diagnostic scope，查询还必须带关联 ID 或 warning/error 门槛；既有连接不升级，角色降级立即失效。

`SubscriptionMutationService` 是 REST 与 Remote MCP 的唯一 subscription/source/schedule 业务 mutation owner；Remote MCP 不复制 REST 写逻辑。`AgentChangeProposalService` 只拥有短期密封 proposal 的授权、指纹和 lifecycle：prepare 在自己的短事务持久化 preview/确认 hash，apply 在 `BEGIN IMMEDIATE` 内重验实时主体与 mutation 先决条件，并与业务 mutation 原子提交。proposal record 只保存安全 snapshot、preview、指纹和结果摘要；cleanup 是 commit 后 best-effort，绝不把已提交业务变化伪装成失败。

`RemoteMCPDiagnostics` 只读取用户范围内持久化的 Source Health、schedule、safe Job projection、匿名 Worker readiness 和 `secret_configured`；它不执行修复、重试、取消、网络访问或写入。`OperationLogQueryService` 只读私有 operation JSONL，先强制 workspace 隔离；self scope 再执行当前 actor/subject 隔离，经过显式授权的 workspace scope 只移除该身份条件，仍使用同一输出白名单。二者的分类、脱敏和 unknown/unavailable 退化属于服务端合同，而不是 Skill 推理。Remote MCP adapter 保持无 session、无调用方身份参数、无服务器侧 Agent 状态；`last_used_at` 的有界 touch 和 proposal/audit 行是显式例外，不构成会话状态。

Gateway bootstrap token 只存在于 React 表单 state；API、React Query、URL、Web storage 和日志均不得接收。浏览器配对后只把 non-exportable Ed25519 CryptoKey、exact `operator.read + operator.write` device token 和 session key保存在 IndexedDB，key 必须包含当前 Inteliscope user 与规范化 Gateway URL。页面登出清空内存消息并断开 socket；忘记设备同时删除 IndexedDB 凭证。MCP delegation token 与 Gateway token 是两套独立凭证，任何 UI、日志或配置都不得混名或互相复用。

### 3.6G Observability Logging Boundary

`src/logging_utils.py` 是 API 与 Worker 的唯一进程日志配置边界；它分别创建 `runtime-<service>.jsonl` 与 `operations-<service>.jsonl`，使用 UTC 每日轮转、私有目录/文件权限及只匹配系统文件名的保留清理。运行日志必须先格式化再统一脱敏；业务模块不得自行建立日志文件 handler、记录 query/body、使用生产 `print` 或把任意业务对象序列化到日志。Uvicorn 只复用该边界，不建立自己的 access/error handler。

`src/observability_context.py` 独占跨 API/MCP/Worker 的安全 `ContextVar` 生命周期；`src/services/operation_log.py` 独占 schema-v1 operation event 构造、严格标识符/枚举校验、白名单查询和最多 20,000 行的反向读取。workspace/actor/subject 只存在于文件内用于隔离；MCP 投影必须移除身份、文件、message、stack、URL、config/payload、文章内容和凭据。符号链接、损坏/未完成行和不可读目录必须安全退化，查询不新增数据库表、REST API 或前端状态。

API 只接受服务端生成的 request ID；路由事件只使用模板路径。成功事件由最外层请求边界在业务事务已经提交且 transaction guard 通过后写入；回滚、事务泄漏与未处理异常只能写失败。未知异常由统一边界转换成带 request ID 的安全 500。Worker 的 claim、eligibility、execute、finalize、finish、pre-claim boundary、lease recovery、invalidation、逐来源获取、头像和通知事件只能在对应持久状态明确后写入；Job 类型必须先注册 trace policy。普通 GET、Feed 浏览、空轮询和 heartbeat 不生成成功 operation event；所有 API 写路由都必须映射 mutation operation。

managed handler 每次 emit 都必须确认 write/flush 结果，并把 runtime/operation sink 健康投影到 readiness 的 additive `logging_status`；日志降级不得改变已提交业务结果。`scripts/check_observability_contract.py` 是上述架构的静态执行门禁，并由 targeted/full/release 每个 Test Gate scope 先行调用；Test Gate 持久化输出必须复用运行时脱敏器且不得保留具名 raw 临时日志。

详细字段、敏感值禁令、事件矩阵和排障流程以 `docs/dev/observability-logging.md` 为唯一真源。

### 3.6H Apify Key Pool Boundary

`src/services/apify_key_pool.py::ApifyKeyPoolService` 独占工作区有序成员、粘性 active Key、pool generation、额度快照与 Actor Run ledger。`src/scrapers/apify_client.py::ApifyClient` 独占 Apify HTTP 生命周期和错误分类；每次 Run 启动前取得不可变的 `secret_id + secret_version + pool_generation` lease，start、poll、abort 和 dataset 读取必须使用该 lease 的同一 Token。`src/services/apify_pool_runtime.py` 独占 Worker 启动后的持久 Run reconcile；Worker、API、Orchestrator、catalog runner 和 source adapter 只能调用这些边界，不得自行选 Key、改 generation 或把来源级 `secret_env` 重新注入 Service 抓取。

切换是 generation barrier，不是请求级 token retry：池先进入 `draining` 并停止所有新 reservation，再中止旧 generation 下全部已登记的非终态 Run，并仅在确认 `SUCCEEDED/FAILED/ABORTED/TIMED-OUT` 后增加 generation、激活下一备用并由逻辑抓取创建全新 Run。30 秒未确认时保持 `apify_key_drain_pending`；Actor POST 结果未知或重启发现未登记 reservation 时保持 `blocked` 并要求人工核对，禁止猜测 runId、复用 dataset 或盲目换 Key。唯一的零费用恢复例外是原始 POST 已返回同一 remote Run ID、客户端已请求中止且对该精确 ID 的 GET 确认 `ABORTED` 与 `usageTotalUsd=0`：只可把原 reservation 记为终态 `aborted/$0`、保留远端 Run/Dataset 审计字段并解除该未知启动锁，绝不搜索匹配 Run 或重发 POST。每个逻辑抓取对同一 Key 最多一次，全部不可用时只有 Apify outcome 失败或延后，其他来源继续执行。

额度快照最长使用 60 秒；Worker 启动必须刷新 active/standby/draining 中缺失、过期或异常未来的全部快照，任一可用 Key 未取得完整新鲜余额时 paid route admission fail closed。只有 `remaining_included_credits_usd <= 0`、HTTP 402 或明确额度错误可标记 `depleted`，401/明确无效 Token 标记 `invalid`；普通 403、429、5xx 和网络错误不得污染整个 Key。周期恢复后的旧 Key经重新核验只追加到备用队尾，不抢占当前 active，也不恢复历史 Run。该能力由 `HORIZON_APIFY_KEY_POOL_ENABLED` 控制并默认关闭；关闭时 schema/状态可维护，但 Service 保留既有来源级凭证兼容路径。

### 3.6I Apify X Actor Route Boundary

`src/services/apify_actor_route.py::ApifyActorRouteService` 独占 `x/profile` 的候选顺序、`closed|open|half_open|disabled|probationary` 状态、路由 generation、目标健康、付费预留、实际费用账本与 `ready|degraded|exhausted|budget_blocked|blocked` 路由状态。`src/scrapers/apify_social.py` 只负责三个 Actor 的官方输入适配、结果映射和语义分类；placeholder、diagnostic、demo、mock、付费墙、错误控制行与严重合同漂移必须在生成 `ContentItem` 前拒绝。API、Worker、schedule、Orchestrator 与 catalog runner 只能调用路由服务，不得自行切 Actor 或把 Actor 故障转成 Key 轮换。

一次逻辑 X/profile 获取按候选串行执行，每个 Worker Job 内多个 X/profile 来源也必须共享单并发锁，禁止付费竞速。有 `job_id` 时费用组稳定绑定 workspace/route/job/source；同一组已有 active attempt 时拒绝第二路并发，重试复用历史候选与预算。每 Run 固定预留 `$0.02`，同一逻辑任务最多三个不同候选且累计预留不超过 `$0.06`；已远端启动、已结算费用或因 route generation 冲突而作废的 cancelled attempt 仍占用原预留并进入失败消费，只有可证明未 POST 的取消才可排除。滚动六小时 Actor 失败的最终实际费用达到 `$0.08` 后进入 `budget_blocked`，准入还必须在同一写事务满足失败消费、全局在途预留和下一次 `$0.02` 合计不超过 `$0.08`。X 可分配额度只取全部可用 Key 的已知新鲜剩余额度减去 `max($1, 20%)`，未知额度不得被当作零或充足。401/402 只交由 3.6H Key Pool；429、Apify 5xx 和可确认未启动的 transport 失败先在同一 Actor 的安全读阶段重试；Actor POST 结果未知时 Key Pool 与 Actor route 都保持 blocked，禁止切源或重复 POST。

Actor 全局熔断必须在十五分钟内至少两个不同、此前成功返回真实帖子的来源出现系统性语义异常；单来源连续异常只暂停该来源六小时。冷却按 1/3/6/24 小时递增，到期只把候选置为 half-open 并复用下一次自然任务；连续两次真实成功才恢复 closed，恢复候选不抢占当前 active。Dami 在成功 Canary 前保持 disabled；由至多两个当前已启用的不同 X/profile source 分别成功返回真实帖子后进入 48 小时 probation，真实帖子成功率达到 95% 才转正，零样本或低于门槛都自动禁用。Canary 强制最多一条结果且与自然 paid attempt 在同候选上双向互斥；这种临时 busy 不得污染候选健康或 route 状态。管理员完整排序是健康候选的选择优先级，reorder 必须能影响下一次选择，但不得中断已取得 lease 的调用。

route generation 与 Key pool generation 都进入 shared acquisition fingerprint。正常抓取开始时取得 route generation；同一调用内发生合法切换时，成功结果必须携带路由服务签发的最终 generation 证明，coordinator 才可在一个事务中把旧 acquisition claim 迁移到新 key 并发布；没有证明、Key generation 同时变化、目标 generation 已有 owner 或 finalize 前再次变化时全部拒绝写缓存与 Feed。管理员或并发路由变化后的迟到结果只结算费用并终止 attempt，禁止更新候选/目标健康或签发新 generation 证明。Worker 在领取新 Job 前必须先对账 Key Run 与 Actor attempt；可安全恢复的已启动 Run 必须继续 poll/dataset/语义校验，已语义成功但 Job 未完成的 attempt 只 GET 重读原 Dataset，无法确认是否启动或缺少可验证 Dataset 时保持 blocked，不得靠 Job lease 过期重复 POST。

### 3.6J Generic Apify ActorOps Boundary

`ApifyActorOpsService` 独占 workspace/Route 加盐的统一目标指纹、attempt `target_fingerprint` 冻结、`superseded_from_lifecycle` 和单槽显式回滚；历史认证证据不得由当前可变 binding 重解释。`apify_actor_discovery_run_revisions` 只表达候选关联，付费归属的唯一真源是 validation 冻结的 `discovery_run_id`，同一 Revision 被多个 run 复用不会串账。

当前能力矩阵是平台能力的唯一注册点：只复用无平台语义的 Stage/CAS/审计编排；执行器、输入映射、输出验证和费用策略必须按 `platform + target_type + capability` 显式登记，未知组合在写入或调用前拒绝。X、Instagram、YouTube 的标准运行最低值统一为两个不同发布者的 Actor，第三槽可选；只有独立的 X `compatibility_single` 能降为单路。浏览器目录只读取已完成 Route Canary、所有启用来源 Canary 和费用对账的 Revision；Worker 重启时将 attempt、validation、batch、stage 与 Job 同步阻断，随后只免费读取原远端 Run，成功后才续跑原批准的冻结 batch，绝不重发该 Actor。

Worker 与 catalog runner 的最终 publication transaction 同时包含 Route/binding/Key 栅栏、avatar/media 数据库引用、Feed snapshot、source health 与 Job 终态。媒体文件由双向 journal 跨越该事务：新文件在 rollback 删除，旧文件仅在 commit 后删除；best-effort 缓存步骤使用独立 savepoint journal，避免 DB 回滚后留下 orphan 或丢失仍有效的旧头像。

`src/services/apify_actor_ops.py::ApifyActorOpsService` 是所有 `platform + target_type + capability` Route Profile、不可变 Adapter Revision、固定三槽、来源绑定、Canary 证据、CAS generation、Pool Stage 与发布栅栏的唯一所有者；`x/profile` 只是永久兼容 route key。运行门槛由 Route Profile 决定：X、Instagram 与 YouTube 的标准模式都需要两个 Actor、两个发布者和固定 Build 的 probationary/certified Revision，第三槽只按管理员动作补充；公开频道 URL/Feed 只作 YouTube 稳定身份且不得作为 HTTP Atom/RSS 运行回退；`compatibility_single` 只可在独立风险、费用和生效确认后以一个公开可运行 Actor 恢复 X 功能。管理员从服务端过滤后的 Candidate 列表决定 allow-list：`initial_pool` 的目标数等于 Route 实际最低槽位，`upgrade_legacy` 严格选择原三个 Actor，`complete_third` 只处理管理员明确选择的额外 Actor；浏览器只提交 opaque Candidate ID、goal、Route generation 和目标槽数，服务端重新解析 Revision、决定安全槽位顺序并冻结可取得的 Build/Manifest。legacy 只能旁路建立新的 exact 3/3 池，不能原地伪造认证。stage 冻结基础 pool hash、人工候选集合、服务端顺序和 enabled source binding generation/fingerprint；active slots 与来源 ready 状态在 staged Route/来源 Canary 完成前完全不变。后续浏览器只提交服务端 plan hash、费用 cap、opaque 幂等键与固定确认词，不得指定 Revision、槽位名或来源集合。apply 在一个事务中重验当前所有 enabled 来源证据并原子写入目标槽、Route generation 和对应 `ready_1of1|ready_2of2|ready_3of3` 来源状态；新增、变化或失败来源只能产生覆盖缺失证据的增量审批，不能丢弃已验证账本。一次逻辑任务冻结 Route/binding/Key generation、当前实际运行的 Revision、Actor ID、可取得的精确 Build 和 Manifest hash，串行调用并在写共享缓存或 Feed 前重新校验；旧 generation 可以完成远端结算但不得污染新配置。

`src/services/apify_actor_manifest.py` 独占 Manifest v1 解析、规范哈希、输入渲染、RFC 6901 输出映射和语义验证。Manifest 只能使用六个固定 target/runtime 引用、JSON literal、固定类型/时间/URL/HTML 转换与 host allowlist；禁止代码、插值、任意 JSONPath、网络请求、Header/Cookie/Token/代理或凭据字段。`parse_datetime` 确定性接受带时区 ISO 时间以及 2000–2100 范围内的 Unix 秒/毫秒；混合 Dataset 中只映射身份元数据但没有内容合同字段的行必须隔离，后续真实内容行继续验证，全为元数据时以 `apify_actor_metadata_only` 失败。原始 Dataset 只在当前进程有界存在，数据库和 AI 只接收无值字段路径/类型摘要。`src/services/apify_actor_observed_probe.py` 只允许已完成免费 Build、输入、权限和定价检查的 YouTube 旧占位 Manifest，对一个固定公开频道做一次受控内容试跑；它只从匹配的 `videoId/videoUrl/publishedAt/title/channelId` 这类实际内容字段导出无值、不可变的标准 Manifest，绝不保存 Dataset 值，也不让 X/Instagram 兼容输入或映射参与。`src/services/apify_actor_compatibility_preflight.py` 独占免费兼容候选的 exact-Build、输入、输出和 Route 语义证明；`src/services/apify_actor_discovery.py` 只能从该证明及已拉取的公开 Actor/Build 元数据确定性过滤后让 AI 一次生成 3–6 个 best-first Manifest proposal，模型不得创造 Actor 或 Build。Worker 的 Store query preset 必须按 Route 内容合同检索 YouTube channel videos、Instagram profile/user posts 等 item Actor，不能用宽泛 profile metadata 查询替代。目标输入的 string/array/标准 `startUrls` shape、handle/URL/native-ID reference 和一个 max-items reference 由代码从公开 Build Schema 生成，无法无代码安全映射的候选提前淘汰；AI 复制该模板并只决定排序、输出 mapping 和 semantics。单次 Prompt 要求返回与当前 proposal target 精确相同的排序备选，少返回只能记录 shortfall，不能放松 Manifest 或发布者门槛。服务仍先完整解析 AI Manifest 以拒绝危险输入，再以确定性模板规范化并逐项执行 Build input validation，保留通过的部分 Revision并由后续 proposal 补位无效项。官方 input validation 的候选不兼容错误隔离在单个 proposal，认证与请求合同错误才终止 Run；Store/metadata/validation 只做三次有界网络/解码/429/5xx 重试并使用 identity encoding，且 Discovery event loop 退出前关闭 AI transport。严格 Discovery 进入付费审批的 Actor/发布者数量由 Route Profile 决定：X、Instagram 与 YouTube 标准模式均为 2/2；`upgrade_legacy` 固定要求原三 Actor和至少两个发布者，`compatibility_single` 只在风险与费用独立确认后进入。兼容候选也必须公开、非 deprecated、可运行、不要求完整权限、在 Route 单次价格上限内，拥有精确成功 Build、可验证 input/output Schema、受控输入模板、官方免费 input validation 与该 Route 的内容语义证明；任一项缺失只返回不可用原因，不能在 UI 中作为可付费 Candidate。部分保留不得越过对应门槛。候选数使用数据库热配置的有界 `max_candidates`，发现止于待审批，不得启动付费 Run。`src/services/apify_actor_maintenance.py` 只在 Worker 既有 maintenance 周期读取官方 Actor/Build/Schema/权限/定价元数据并持久化有界哈希 observation；展示用 Dataset `views` 不参与合同指纹，未变化 observation 不重复生成 proposal，元数据不可用不得中断已固定 Revision 的 Route。

`src/services/apify_actor_canary.py` 只执行已由 `ApifyActorOpsService` 原子批准并入队的 one-shot Canary；Route 认证由 `apify_actor_canary_batches` 协调一次管理员确认下的有序人工 Candidate allow-list。manual `initial_pool` 以 Route 实际最低值为目标：X、Instagram 与 YouTube 都需要两个不同 Actor与两个发布者；`upgrade_legacy` 以原三个不同 Actor、至少两个发布者全部成功为目标，`complete_third` 只计入管理员明确选择的新 Actor，`compatibility_single` 只允许一个固定公开参考目标返回真实非空内容后成功。Worker 不得因已有 legacy 或其他池 runnable 而提前停止，也不得尝试未被管理员选择的后备 Actor；YouTube 不得自动为第二或第三槽产生额外付费。staged batch 随后在同一 approval/cap 内串行执行审批快照中每个 enabled source 的缺失目标槽 Canary；`apify_actor_pool_stage_sources` 是 inactive staged Revision 获得来源验证授权的唯一关联，runner 必须同时校验 stage、workspace/source/slot、binding generation/fingerprint 与 base pool。普通新来源继续逐槽确认。每个管理员动作携带唯一 `approval_id`，服务端只保存其摘要、批准 generation、plan hash 与费用上限；同一动作的网络重放必须返回原 batch/validation/job，任何参数漂移都冲突。Worker 在每个付费 POST 前免费核对公开、可运行、权限与价格；标准/legacy 必须核对精确 Build，兼容流程在取得实际 Build 时自动固定，否则继续以 `execution_mode=current` 执行完整输出合同和 publication fence。确定性不存在、私有、不可运行、价格超限或标准流程 Build 漂移必须以 `$0` 停用 Revision且不创建 attempt。未知启动结果阻断整批、stage、Route 与 Key且不得继续或自动重放。Canary timeout 缺省 300 秒并在 180–900 秒内按下一 Job 热加载；超时只中止已知远端 Run，不自动重试。远端终态费用由 `apify_actor_runs` 向 attempt/validation/batch 幂等对账，批准上限与实际已终结费用始终分开；确认明文、approval ID、validation ID、真实 target/fingerprint 与远端标识不得进入公共 API、Job 结果或日志。

Discovery 持久化前必须让 Manifest 的每个输出 Pointer 在精确 Build Dataset Schema 中确定性可达；Profile/Channel items 不允许用内容条目 URL 证明来源身份。AI Prompt 优先使用内容行中的 author/owner handle 或 source native ID，profile metadata-only Dataset 不得进入付费 Canary。Discovery AI 仍继承全局 provider/model/Base URL，但管理员从当前 Provider 的已登记 Key 中人工固定一个 opaque 选择；Worker 冻结该 Key且不建立自动回退池。

`src/services/apify_native_fallback.py` 是原生优先的付费准入规则。YouTube catalog/source identity 始终是 RSS 与规范 `youtube.com` URL；成功或可信空结果不调用 Actor，只有 timeout/DNS/429/5xx/schema drift、历史非空后的可疑空和已验证目标的未确认 404 可回退。无效配置、SSRF 拒绝和已确认私有/删除必须 fail closed。Actor 回退结果重新归属原 `source_id/source_key` 并使用与 RSS 兼容的稳定内容 ID，不得把固定传输 IP、Actor identity 或远端 Run/Dataset 投影到 Feed。

ActorOps feature schema v15 依赖 v13/v14，已有数据库普通初始化不得静默安装。本地共享 migration ledger 的 15/16 已由通知 schema 占用，因此 ActorOps 使用 global 17；Discovery limits、Canary batches、Pool Stage、人工选择、validation tuning、resilience 与槽位管理依次使用 global 18–24，其中 `apify_actor_pool_management_v22` 固定为 global 24。所有迁移都必须停止 API/Worker、跨过 heartbeat 安全窗并确认无对应非终态 ActorOps Job，以 SQLite backup API 创建 `0600` 备份，离线安装后检查精确 marker/checksum、完整 table shape、integrity 与 foreign keys；不得联网、调用 AI/Actor或产生费用，任一失败必须恢复备份。global 24 只为 batch/stage 持久化 `add_slot|replace_slot` 和安全 operation slot，不改写既有 X 来源、历史内容、费用或当前池，也不自动指定 validation Key、启用 compatibility 或开启新鲜度。实验性 global 25 auto-pool 若已存在只作惰性历史证据，日常 runtime、readiness、maintenance 与 fresh bootstrap 均不读取或要求，后续 migration 从 global 26 继续。日常 Actor、Build、Manifest、槽位顺序和 Discovery 调用边界按 generation 从 SQLite 热加载；Discovery Job 只冻结全局 AI 当前 provider/model/base URL、管理员首选 Key 与生产输出上限，不建立自动 Key 回退池。

固定三槽的新增、替换与移出均归 `ApifyActorOpsService` 的单一写事务所有：读模型先投影每槽 action 与理由，浏览器不能自行计算可操作性。新增只填首个空槽、替换只改已占用槽，二者先冻结 base pool、operation slot、候选 Revision/Build/Manifest、来源指纹和费用上限，再走既有 Stage/Canary/activation；未完成前 active pool 不变。移出只压紧活动引用并把旧 Revision 保留为 superseded/history，先拒绝 unknown-start、active attempt、freshness、Stage、CAS 与保留后低于 Route 实际最低 Actor/发布者门槛；它不得创建 Actor 调用，现有 source Canary 证据仅可按保留槽复用。

### 3.6K ActorOps v2 计划适配器边界

Phase 2 已实现本边界中的 Domain、Port、Registry、Policy、分拆 Repository、三类 Adapter、Runtime、薄 Service、条件 feature flag 与 global 26；Discovery、Reconciler、Maintenance 和平台切流仍为 planned。全部 Route 默认 disabled，因此第 3.6J 的现役 v1 所有权不变。v2 使用通用编排服务调用每个订阅能力独立的 Adapter，不使用承载默认实现的大型继承基类。

```text
src/services/actorops/
├── domain.py
├── ports.py
├── registry.py
├── repository.py
├── policy.py
├── runtime.py
├── discovery.py
├── reconciliation.py
├── maintenance.py
├── service.py
└── adapters/
    ├── x/common.py + profile_items.py
    ├── youtube/common.py + channel_items.py
    └── instagram/common.py + profile_items.py
```

`ports.py` 的平台端口固定为小接口，不提供可被子类继续堆积的默认工作流：

```python
class ActorRouteAdapter(Protocol):
    route_key: RouteKey
    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec: ...
    def discovery_spec(self) -> DiscoverySpec: ...
    def build_actor_input(self, target: TargetSpec, manifest: ActorManifest, window: FetchWindow) -> Mapping[str, object]: ...
    def validate_output(self, rows: Sequence[Mapping[str, object]], target: TargetSpec, manifest: ActorManifest, window: FetchWindow) -> NormalizedBatch: ...
    async def fetch_native_fallback(self, target: TargetSpec, window: FetchWindow) -> NativeFallbackResult: ...
```

1. `domain.py` 独占无 I/O 的实体、状态、错误分类与 transition；`ports.py` 定义 `ActorRouteAdapter`、远端 Client 和时钟/ID 等端口；`registry.py` 是 `RouteKey(platform,target_type,capability) → Adapter` 的唯一注册点。未知 RouteKey fail closed。
2. `repository.py` 是唯一公开 Repository；其 focused `repository_*` 内部模块分担 read、Candidate、Attempt、Discovery 与 publication SQL，避免单文件增长。其他通用模块和 Adapter 不得直接导入 SQLite、旧 `ServiceStore` 私有方法或表名。`policy.py` 只根据领域快照计算候选顺序、熔断、健康、补池和预算决定，不执行网络或写入。
   global 26 的建表、只读 v1 摘要 backfill 与离线迁移是唯一 storage 例外，分别归 `src/storage/actorops_v2_*` 与 `scripts/migrate_actorops_v2.py`；它们不得成为在线 Repository 或 Runtime 依赖。
3. `runtime.py` 只编排 Active、Standby、Last Known Good 与发布凭据；Apify remote wrapper 把 unknown-start 保留在单 Attempt/reservation，禁止调用 v1 workspace barrier。`discovery.py` 只推进可恢复 checkpoint；`reconciliation.py` 只读取/结算既有远端 Run；`maintenance.py` 只在已冻结站立授权内生成 Probe、补位或替换意图；`service.py` 为 Worker 和 source acquisition 提供薄 facade。
4. 每个 `platform + target_type + capability` 使用独立 Adapter，例如 `youtube/channel/items` 与未来 `youtube/video/comments` 必须是两个 Adapter，可复用 `youtube/common.py` 的身份规范化。Adapter 实现上述端口而不继承通用工作流，只负责目标规范化、Store 查询/静态能力描述、Actor input 构造、输出身份/内容验证、`ContentItem` 映射和可选原生降级；不得选择 Candidate、管理 Key/预算、写状态、创建 Job、发布 Feed 或处理重启恢复。
5. 通用 Runtime、Discovery、Repository、Reconciler 和 Worker handler 不得包含 `if platform == ...` 或平台 host/字段知识；平台名称只允许出现在 Adapter、公共平台 helper、Registry 组合根和平台测试。新增平台通常只新增 Adapter、注册项和测试；若必须改变通用端口，先更新本架构合同和决策记录。
6. source acquisition 先从 source config 得到 RouteKey 和通用 `TargetSpec`，再由 Registry 解析 Adapter。Actor 链全部失败后，只有 Adapter 返回明确 supported 的原生降级才能执行；原生结果仍必须转换为通用 `ContentItem` 并通过相同来源身份与 publication boundary。
7. API 与 React 只消费通用 Route/Candidate/Binding/Attempt 投影，不依赖 YouTube、X 或 Instagram 的 input/output shape。平台差异只通过稳定能力标签和安全 degraded/unsupported reason 暴露。
8. 每个已注册 Adapter 必须通过同一参数化合同套件：RouteKey 唯一、目标规范化幂等、指纹稳定、危险目标拒绝、输入有界、跨平台/跨目标输出拒绝、ContentItem 身份稳定、空结果语义明确、秘密和 SQL 依赖缺失。平台自身再补充专用映射与原生降级测试。

新生产文件遵守 `tests/code_size_policy.json`；通用模块目标不超过 400 行，Adapter 目标不超过约 300 行。现有冻结的 `apify_actor_ops.py`、`apify_actor_route.py`、`service_store.py` 和 ActorOps React 巨型组件只能通过兼容 facade 缩小，不得承载 v2 新行为。
