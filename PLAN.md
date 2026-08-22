<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力状态

- 核心：小团体账号与角色、来源订阅、共享获取、用户作用域 Feed/History、Worker 队列、React/HeroUI Service UI、受保护媒体、可观测性和本地 OpenClaw 直连。
- 兼容：旧设置 URL、Service DB snapshot 双读、ActorOps 兼容 API、schema 迁移读路径和首库 `release_rc1.sh`。兼容接口不等于默认产品能力。
- 默认关闭：Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知与生产 Remote MCP 写入。
- 已实现但须独立批准：Feed storage v3、通知 schema v14–v16、ActorOps 现役 schema v17–v24、付费 Canary、自动新鲜度站立授权、外部 Webhook/Telegram/Email 验收。global 25 的 auto-pool 实验表若已存在仅作惰性历史数据，不属于 readiness、fresh bootstrap 或运行时依赖；后续全局迁移从 26 继续。
- ActorOps v2 单轨退役：Phase 0–6 已完成 v2 Binding/Admin/UI/API/Worker 接管；前端只呈现 `active|disabled`，旧 Admin URL 返回 410，Worker 只执行四种 v2 Job，未知 v1 Job 保持离线隔离。最终 schema/Runtime 删除仍按 Phase 7–8 推进；不部署、不切真实流量或调用付费 Actor/AI。

当前轻量门禁任务基线为 `16014e4` / `v2.3.3`；任何运行操作前仍必须以实际 API、Worker 和容器 revision 重新核对。

## 迁移与发布矩阵

| 事项 | 先决条件 | 执行方式 | 通过条件 |
| --- | --- | --- | --- |
| Feed storage v3 | 停 API/Worker、无活跃任务 | dry-run、UTC `0600` backup、显式 apply | marker、hash backfill、integrity、foreign keys 与 readiness |
| notification v14–v16 | 上一 schema 已完成 | 同上，不调用 Transport | 表/约束/历史映射、API 与 Worker ready |
| ActorOps v17–v24 | 无 Discovery/Canary/新鲜度 Job | 同上，不联网、不调用 AI/Actor | 精确 migration checksum、完整表形状、integrity/foreign keys 与 readiness；global 25 不作为前置 |
| ActorOps v2 global 26（已实现、未启用） | 停 API/Worker，全部非终态 ActorOps 与未结费用先收敛 | 显式 dry-run、`0600` backup、apply、v24 只读摘要 backfill | fresh/existing/repeat apply、integrity/foreign keys、global 25 完全不读写；不复制 inflight，缺 marker 不改变 v1 readiness |
| 付费 Actor/AI | operator 明确授权 | 单次有上限 canary | 费用、远端 Run、来源结果与回滚证据 |
| 正式 VPS 升级 | 干净且等同 `origin/main` 的 main | `./scripts/release_vps.sh release vX.Y.Z` | 精确 SHA main Gate、Tag smoke、API/Worker/前端 revision |

## 推进顺序

1. 先处理各项生产数据库迁移；普通发布拒绝隐式迁移。
2. 只对免费公共来源启用 shared acquisition，观察自然周期和用户隔离。
3. 经独立授权后再做 Key pool、Actor/AI 或真实通知的有界 canary。
4. 维持 Feed/History、用户隔离、通知 outbox、存储预演/恢复和三视口 UI 回归。
5. 开发切片只运行直接受影响测试；任务末运行一次 impacted preflight，PR 的 Linux UI 只跑映射 spec，最终 main SHA 运行一次权威完整 Gate。已知问题进入 full/release、同根因重复和 VPS 上传前代码类失败均须为 0。

## ActorOps 单轨退役当前计划

1. **Phase 0–1 — 已完成**：机器可复现的 v1 runtime 引用边界已建立；v2 Attempt 使用持久 logical identity、请求窗口、结果重放和费用单调规则，同一 logical Job 不重复 POST。
2. **Phase 2 — 已完成**：`ActorOpsBindingService` 接管平台来源的 ensure/rebind/verify/disable/reenable/soft-delete；现役来源 projection、schedule、acquisition、catalog fetch 和 user feed refresh 只读 v2。pending/disabled 不执行；disabled/shadow 不回退 v1；YouTube 仅使用受控免费 RSS fallback。
3. **Phase 3 — 已完成**：直接 `ActorOpsAdminService` 读取 v2 Route/Candidate/Binding/Attempt/Discovery/Maintenance/Replacement/Store metadata；Route list/detail 固定 schema 2，Operation Events 改读脱敏 Operation Log，缺 schema 与其他不可用分别返回稳定 503。旧 Pool/Canary/Freshness 兼容接口暂留至 API retirement。
4. **Phase 4 — 已完成**：`/settings/actorops` 永久移除 Hero v1 fallback，仅请求 schema-2 v2 Route/详情、共享 alerts 与 v2 Operation Events；Route view 只呈现 `active|disabled`，遗留 shadow 安全归一为 disabled。旧 Pool/Canary/Freshness 组件、types、query keys、服务与浏览器流程已删除。
5. **Phase 5 — 已完成**：现役 Admin read/write 和稳定兼容 alias 均只读写 v2；v1 Pool/Stage/Freshness/Validation/Canary/Discovery/X profile URL 不列入 OpenAPI，并以已认证的稳定 410 `actorops_v1_retired` 返回。API Context 不再构造 v1 ActorOps Factory，v1 表 authorizer deny 下 v2 alias 仍可运行。
6. **Phase 6 — 已完成**：Worker registry、claim 与 stale lease recovery 使用显式允许列表，只执行 `actorops_v2_discovery`、`actorops_v2_maintenance`、`actorops_v2_replacement`、`actorops_v2_metadata_refresh` 与既有普通 Job；四种 v1 ActorOps Job 不再生产、claim、requeue 或执行。未开始且零费用的 v1 Job 在 `fetch_jobs` 内原子标记 `actorops_v1_retired`，已 claim/运行或费用不明的事实不改写，留给离线退役工具。v1 schema 不再阻断普通 RSS/GitHub/source fetch；v2 schema 只在 v2 Job 执行时局部检查。
7. **Phase 7A — 已完成**：离线工具只安全取消未启动 v1 Job；snapshot/receipt、精确隔离、未知费用阻断与 verify 已覆盖，不 DROP 表、不联网。
8. **Phase 7B–8 — 后续**：安装 global 30 单轨 schema，移除 flag/shadow/source-v1 generation，最后删除零在线 import 的 v1 Runtime 并把 authorizer allowlist 收敛为空。

## ActorOps v2 历史建设阶段

1. **Phase 0 — 已完成条件**：从 `ce12561896642684ae310ba111f2ce4efb749cf1` 建立 `codex/actorops-v2`，保存 task snapshot，完成代码/表/状态/API/UI/测试盘点、D160 与 planned 合同；不修改产品代码或运行数据。
2. **Phase 1 — 已完成：Domain 与 global 26**：七张核心表、单调状态模型、Adapter Port/Registry、Repository、显式离线迁移和 v24 只读摘要 backfill 已建立；global 25 永久惰性。迁移前必须排空 inflight/未结费用，v2 Attempt/Discovery 从空表开始。
3. **Phase 2 — 已完成：稳定获取数据面**：Active、Standby、Last Known Good、免费原生降级、Attempt 账本和局部 Publication fence 已实现；feature flag 与 Route 默认关闭，未切真实流量。
4. **Phase 3 — 已完成：统一对账与 Worker 隔离**：单一 Reconciler 只读取和结算既有远端 Run；unknown start 只冻结对应 Attempt/费用预留，Actor 控制任务不再成为普通 Fetch claim 的同步前置。
5. **Phase 4 — 已完成：可恢复 Discovery**：Store、Metadata、Build/Pricing/Schema、Mapping、Ranking、Persist 每步保存安全 checkpoint；AI 只增强无法确定的映射，AI 不可用不能阻止确定性候选完成；不启动 Actor、Probe 或切流。
6. **Phase 5 — 已完成：站立授权**：默认关闭，Owner/Admin 双策略授权后才按每 Probe `$0.05`、每 Route 每 UTC 日 5 次、Workspace 每 UTC 月 `$3.00` 的上限执行单 Candidate Probe；免费 exact-revision 预检、原子预算 reservation、自动补 Standby 与非最后一路替换均已实现，最后一个可运行 Actor 永不自动移除。无 HTTP API/UI，未执行真实调用。
7. **历史 Phase 6 — 已完成离线护栏**：离线 Route CAS、历史费用审计和备份/receipt 机制已实现；其 shadow→v1 语义已被单轨退役计划取代，不再是现役来源路径。
   - D173 的受控前置：为使已证实的 v1 Actor 输出合同以其实际费用完成 promotion，global 27 仅将 v1 Canary ledger 的单 Candidate 批准上限升至 `$0.20`、批次总额升至 `$0.60`。它必须显式离线安装；默认 `$0.02` 不变，未迁移数据库不得发起更高 cap 请求，也不改变 v2 schema、Route mode 或 Phase 6 切流条件。
   - 精确 Revision 失败不复活：一次 final `contract_mismatch` 后，同一 Actor/Build/Manifest 不得在后续 Discovery 中重新计入新 Candidate 或再被批准；只有 Build 或 Manifest 改变才能形成新的验证合同。
8. **历史 Phase 7.1 — 已完成控制面基础**：global 28、商城快照、费用上限、Replacement Plan 和 v2 UI 基础已经建立；全面 Admin/UI 单轨化由当前退役计划继续完成。
9. **历史 Phase 8 — 已由单轨退役计划取代**：发布、VPS 与 Tag 仍是本地验收之后的独立决定。

每个 Phase 独立提交；行为测试先在该 Phase 内观察失败，再随实现转绿，禁止提交已知失败。Phase 6 的三个平台各自独立提交和回退边界。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知服务、React UI、Remote MCP、浏览器 OpenClaw、存储治理和可观测性。

ActorOps v2 Phase 5 已提供默认停用的站立维护：Owner/Admin 双策略授权、免费 exact-revision 预检、单 Candidate Probe、独立 Probe 账本、UTC 日/月预算与安全补位/替换均不改变 Route runtime mode、Feed、LKG 或水位。Phase 6 的通用 guardrail 只提供安全的离线切换准备；收到逐平台费用授权后才按平台独立 shadow/观察/切流。新增平台继续通过独立 Adapter 注册，不把平台分支加入通用 Runtime、Discovery、Repository 或 Reconciler。

不做 archive analytics、Graph、推荐/embedding、站内原文代理、多 workspace、商业计费、OAuth、客户间共享 OpenClaw、服务器代理 Gateway 或未授权的真实外部调用。旧 CLI、静态站、scheduler、本地 MCP、archive/Graph/feedback API 不再是兼容面。

## 验证门禁

1. 每个任务按 `snapshot → 定向测试 → 主动审查 diff → 一次 impacted preflight` 推进；冻结单体相对 snapshot `base_sha` 不得净增长，缩小不修改策略文件。
2. `preflight` 接受 snapshot、staged 或 base/head 范围；未知可执行改动 fail closed 到无 Docker/Playwright 的全量代码检查。新文件/函数遵守 `tests/code_size_policy.json` 的唯一硬上限；目标行数、复杂度和嵌套只报告。
3. PR 的 UI 门禁按 ActorOps、Workbench、视觉归属选择 Playwright spec；应用外壳、设计系统、全局路由与未知 UI 才跑全套。最终 main SHA 运行一次权威完整 Gate；完整失败后先复验失败 spec，修复后最多再完整运行一次。
4. 正式发布复用精确 main SHA 的成功 Gate；Tag 仅做隔离 API Docker smoke。VPS 只 `docker load`，不得构建本仓库。共享健康检查等待 API/Worker、双容器 healthy、前端与公网 revision；`starting` 不触发回滚。
5. 控制面变更必须运行 Markdown 控制检查、schema-v3 validator、worklog validator、JSON 校验和 `git diff --check`。
6. ActorOps v2 的通用生产模块目标不超过 400 行、硬上限遵守 `tests/code_size_policy.json`；每个订阅类型拥有独立 Adapter 和参数化合同测试。新增平台通常只能新增 Adapter、注册项与平台测试，若必须修改通用流程则先更新架构合同和决策。

## 历史入口

- 历史计划与上下文读取规则：`archive/project-history/control/`。
- 历史实施报告、设计与过期运行手册：`archive/project-history/` 下的索引目录。
- 决策理由：`docs/decisions/`；仅在任务需要时按索引读取。
- 工作执行记录：`WORKLOG.md` 与 `archive/worklog/`；原始旧日志在 `archive/legacy-worklog/`。
