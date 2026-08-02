<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 1. 计划用途

本文件只保留下一轮开发需要的当前阶段、实施顺序、非目标和验证门禁。已完成阶段的完整原文保存在 `archive/project-history/control/PLAN-schema2-2026-07-28.md`；长期理由见 `DECISION_LOG.md`，历史执行证据见归档工作日志。

<!-- init-pro:section name=phase -->
## 2. 当前阶段

当前产品主线仅为“小团体多人的信息获取 + Feed 留存”。

当前基线：

1. Feed 一次性通知、认证异步反馈、user content v5 备份/apply、免费来源修复和显式 reconcile 已完成。26 条历史内容为 24 条 captured、2 条 excerpt-only；旧 schema 空字符串占位已在 `0600` 备份后规范化，snapshot、Job、媒体和 AI usage 未变化。
2. 公共源共享获取、既有部署数据库的 Feed storage v3 compact writer 和工作区 Apify Key 池 rollout flag 均保持关闭；新空库在自动记录 v3 marker 后默认使用 compact writer，未迁移数据库仍强制回退 storage v1。
3. Apify Key 池 schema v8、固定凭证 Run ledger、30 秒排空屏障、重启对账、管理员 API 和设置页已在本地实现；启用仍需停 Worker、核对远端 Run、备份数据库和有上限 canary。
4. X/profile 的 Apify 三 Actor 路由、schema v13 账本、语义占位拦截、费用熔断、管理员状态页与工作区告警已在本地实现；默认顺序为 ScrapeBadger、Dami、Xquik，真实付费 Canary 与 48 小时观察仍需 operator 单独确认。
4A. 个人新内容通知与 Apify 运行告警的七类 Webhook Provider Registry、平台业务 ACK、飞书/钉钉可选签名和 schema v14 显式门禁已在本地实现并通过完整 Test Gate；未迁移数据库必须保持 API readiness 与 Worker fail closed，真实 Webhook 验收和部署均未执行。
4B. 通用 ActorOps schema v15、受限 Manifest v1、三槽 Route Profile、来源级验证、发现设置与管理 UI 已在本地任务分支完成；Discovery 继承全局 AI 的 provider/model/Base URL，并由管理员从同 Provider 的已登记 Key 中人工固定一个 opaque 选择，首期 tuple 只允许 X Profile、YouTube Channel 与 Instagram Profile。单次 AI 调用要求 3–6 个 best-first proposal，每个输出 Pointer 必须在精确 Build Dataset Schema 中可证，Profile/Channel items 不得复用内容 URL 证明来源身份；逐项验证并保留有效的部分 Revision。生产激活优先完整 2+1；若尚无完整池，但已有两个不同发布者、不同 Actor、固定 Build 且各成功一次 Canary 的 probationary/certified Revision，则允许管理员一次确认后以 `2/3 degraded` 快速上线，第三槽留空热补位，少于两路仍 fail closed。新来源只串行验证当前实际运行的两或三槽。v16 Token 实测扩展以 global migration 18 离线加列，生产输出上限热配置为 4096–65536，AI 单次调用超时 180 秒；管理员可确认后对 YouTube/Instagram 顺序执行 32K 容量测试，64K 只用于 length 重测，且不启动 Actor/Canary。Route Canary 默认等待 300 秒且不自动重试，终态费用从远端账本回写；已有安全两路时不因五次上限要求重新 Discovery。受控 v15 离线修复会在证据全空时删除误建的 `youtube/profile/items`，并保持合法 Route CAS 单调。X 既有候选与历史只投影为 `legacy_builtin`。真实容量测试、每次付费 Canary、首次启用、分支集成与 VPS 发布仍需后续独立授权。
5. AI 目标预置为 `deepseek-v4-flash` 但保持 disabled；对话中旧 Key 视为泄露，只能使用用户重新写入 SecretStore 的轮换 Key。
6. HeroUI 已完成全站生产切换；视觉、响应式、交互和浏览器验收只以 `UI_CONTRACT.md` 为真源。
7. API、Worker、Scheduler 和 CLI 私有双流 JSONL 已完成故障排查加固：请求/Job/source/subscription/stage 可串联，未知 API 异常返回安全 request ID，Worker 覆盖边界、租约恢复、逐来源和通知终态，readiness 独立披露 sink 降级；OpenClaw 缺省只查本人，Owner/Admin 可在新连接上显式授权有界工作区诊断。静态日志合同已进入全部 Test Gate scope；不包含日志 REST API、前端日志页、自动修复或部署。
8. 最近记录的 VPS 发布基线为 revision `74c7b16d715b` 的 API、Worker 与同机 RSSHub；执行任何运行操作前必须重新核对实际容器状态，legacy scheduler 继续保持关闭。
9. 低 Token `test_gate` 仍处于 0/10 提交观察期，任务完成门禁保持 `python scripts/test_gate.py run --mode full`。

当前推进顺序：

1. 停止 API/Worker，对目标数据库再次 dry-run，使用 UTC `0600` backup 显式 apply Feed storage v3；验收 marker、hash backfill、integrity 和 foreign keys，并明确核对目标运行环境的 compact flag 后才允许既有部署打开 compact writer。
2. 只对非付费公共源开启 shared acquisition，观察两个自然周期的 cache hit/miss、upstream attempt、Feed 用户隔离和 Source Health，通过后再扩大范围。
3. 付费来源必须取得 operator 再次明确授权，并确认上游严格单次有界输入，才能进入独立 canary；X/profile Canary 每次只能从管理员路由卡二次确认启动，terminal Job 不允许通用 retry。
4. 开启 `HORIZON_APIFY_KEY_POOL_ENABLED` 前暂停 Worker、确认无 running Job、核对并终止未登记远端 Run、备份 Service 数据库，只执行一次有上限 canary；无法核对的启动结果保持 blocked。
5. X/profile 上线先迁移 schema v13，再分别对两个现有 X 来源执行一次 ScrapeBadger Canary；Dami 仅在各自 Canary 通过后进入 48 小时 probation，Xquik 保持 open 并只由自然任务探测。未经再次明确授权，不得触发这些付费调用。
5A. 部署包含 Webhook Registry 的 revision 前必须先完成 schema v13，停止 API/Worker并跨过 heartbeat 安全窗，再对目标数据库执行 Webhook providers v14 dry-run、`0600` backup 与 apply；只有两表约束、integrity、foreign keys、API readiness 和 Worker ready 全部通过后才可恢复通知。迁移与发布不得触发真实 Webhook。
5B. ActorOps 引擎切换前必须在 v13/v14 已完成后停止 API/Worker并跨过 heartbeat 安全窗，对目标数据库执行 v15 dry-run、SQLite `0600` backup 与 apply；只有 X 历史/费用/健康保留、三条 Route Profile、attempt 冻结列、integrity、foreign keys、API/Worker readiness 全部通过后才可恢复。迁移不联网、不调用 AI 或付费 Actor。
5C. Token 测量上线前必须在 v15 已完成后停止 API/Worker并确认无活跃 Discovery/Canary Job，对目标数据库执行 v16 dry-run、`0600` backup、apply、integrity 与 foreign-key check；旧 Run usage 保持 NULL。自动化验证不得调用真实 AI，8080 重建后真实 32K 测试仍由管理员单独确认。
6. 用户写入 DeepSeek 轮换 Key 后，只对一篇 captured article 执行零 Token 模型预检和一次省略 `temperature`、SDK/application retry 均关闭的 completion smoke；成功后才启用。
7. Telegram adapter 与 fixture 已通过；本机到 `t.me:443` 的 TLS 仍失败，网络出口恢复后只做 1 条公开频道复验。
8. VPS 的 Feed storage v3 apply、rollout flag 开启和任何付费 canary 必须分别满足门禁并取得对应授权；Bilibili 冷路由受风控时不得高频重试。
9. HeroUI 生产体验继续按 `UI_CONTRACT.md` 的三视口、可访问性、锚点和构建产物门禁维护。
10. 固定数据 `/__preview/workbench-heroui` 只用于开发验收并保持生产构建剔除；不得恢复已删除的 MUI 对照原型、真实数据 preview 或 `VITE_UI_EXPERIENCE` 分叉。
11. 现有并行开发分支不做原地强改；由单一 integration owner 依次合入最新日志基线。每个分支一旦触及新增写路由、Job 类型或受保护运行路径，必须修复 observability contract 报错，并在组合结果上重跑 full；正式发布再跑 release。

兼容说明：archive items/trends/facets/source-quality、feedback API/表、disabled Graph API 和旧 CLI 全局 archive/graph 可继续保留；兼容接口存在不等于当前产品能力或后续建设承诺。

<!-- init-pro:section name=scope -->
## 3. 当前范围

本阶段继续做：

1. 小团体用户、角色、公共源市场、个人订阅和用户作用域 Feed。
2. Hub taxonomy 与 legacy alias 的兼容迁移。
3. 来源配置、抓取任务、可选 AI、Service UI、Feed snapshot 和稳定历史的字段合同。
4. 任务队列、配额、Source Health、确定性优先级及明确的 capability/degrade 表达。
5. 管理员 write-only AI/Apify Key、默认关闭的 Apify Key 池、X/profile 三 Actor 路由与工作区运行告警，以及受控长度概括。
6. React/HeroUI Service UI、用户作用域 Query cache、任务轮询、三视口与浏览器验收。
7. 默认关闭的 OpenClaw Remote MCP、用户自管 delegation、安全读工具、受控订阅流程和浏览器直连用户 Gateway。
8. 上海自然日内容分层、用户隔离全局搜索，以及 Owner/Admin 的预演式标准清理、冷归档与恢复。
9. `test_gate` 10 个不同 CI 提交的 selector、`mapping_miss` 和摘要一致性观察。

本阶段不做：

1. 第三方 AIHub/AIHOT 逆向或依赖。
2. 私密群组、好友流、Cookie、Session 或账号密码采集。
3. 未授权的生产通知 rollout、邮件群发、scheduler、Worker 启动、付费抓取或 AI 调用。
4. Archive analytics、Graph、个性化推荐、站内原文代理、大规模 embedding、复杂可视化、任意 SQL 或路径级存储管理。
5. 多 workspace、商业计费、自助注册、独立移动 App。
6. 个人摘要、推荐型/评分型推送，或把 compatibility-only API 扩展为默认 UI 能力。
7. 服务器侧 Agent/LLM/Gateway 代理、客户间共享 OpenClaw、生产 Remote MCP 写入、OAuth、ClawHub 或模型密钥托管。

<!-- init-pro:section name=priorities -->
## 4. 实施优先级

1. 保持 `/api/*` envelope、鉴权、权限和错误语义稳定。
2. 保持 Service SQLite schema、用户、catalog、订阅和 job queue 稳定。
3. 保持 catalog/subscription 到现有 `Config`、source registry 和 Worker payload 的兼容路径稳定。
4. 默认 UI 只使用用户 Feed、订阅、任务和配置 API，不调用 archive analytics、source-quality、Graph 或 feedback。
5. 持续回归 Feed history、上海自然日分层、用户隔离搜索、通知 outbox 和 preview/apply 存储治理。
6. 持续观察 API、Worker、RSSHub、数据库、资源和 React UI；legacy scheduler 保持停止。
7. 每个兼容边界先补目标测试；观察期未完成前仍以 full gate 作为完成依据。

## 5. 实现强约束

1. 外部系统原始字段不得扩散到业务层；taxonomy、阈值和成本开关不得写死在入口层。
2. 输出层不得直接访问运行时来源；能力缺口必须显式表达 capability/degrade、unsupported 或 unknown。
3. `personal_tags` 不得进入 AI prompt；`category/tags` 只作兼容 alias，新实现优先使用 `channel/topics`。
4. Service Worker 不得读写 legacy site/history/graph 静态产物，也不得使用旧全局历史去重。
5. Feed snapshot finalize 必须持有有效 `worker_id + claim_token`；数据库迁移必须显式执行、先备份并做完整性检查。
6. 未经任务明确要求，不得读取大历史数据、启动 scheduler、访问真实密钥或触发真实来源、AI、推送和付费调用。
7. 存储治理只允许固定策略、预演式清理和冷归档；不开放任意 SQL、原始路径删除、在线 `VACUUM` 或自动永久删除。

## 6. 验证顺序

1. 日常迭代先运行任务相关测试；可用 `snapshot` 和 `plan` 查看影响映射。
2. 观察期内任务完成、PR/main 和合并前统一运行 `python scripts/test_gate.py run --mode full`；targeted/full/release 的每个 scope 都先执行 `scripts/check_observability_contract.py`。
3. UI 相关 CI 追加 Playwright；正式发布运行 `python scripts/test_gate.py run --mode release`，其中 Docker smoke 只启动隔离 API。
4. 完整日志只保存在 `.test-results/<run-id>/` 的脱敏 `0600` 文件；不得保留具名 raw 临时日志。先读限长摘要，仅在诊断需要时读取指定失败片段。
5. 任何 test gate 都不得启动真实来源、AI、Worker 或 scheduler。
6. 控制面变更同时运行 schema-v3 项目校验、紧凑工作日志校验、JSON 校验和 `git diff --check`。

## 7. 历史入口

1. schema-v2 完整计划：`archive/project-history/control/PLAN-schema2-2026-07-28.md`。
2. 历史设计、规格和实施报告：`archive/project-history/superpowers/`、`archive/project-history/sdd-reports/`。
3. 历史 init-pro 报告与项目地图：`archive/project-history/init-pro/`、`archive/project-history/reference/`。
4. 旧原始工作日志：`archive/legacy-worklog/`；后续紧凑日志归档：`archive/worklog/`。
5. 只有任务需要追溯历史时才对上述目录做定向 `rg`，不得默认整文件读取。
