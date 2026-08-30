<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力状态

- 核心：小团体账号与角色、来源订阅、共享获取、用户作用域 Feed/History、Worker 队列、React/HeroUI Service UI、受保护媒体、可观测性和本地 OpenClaw 直连。
- 兼容：旧设置 URL、Service DB snapshot 双读、ActorOps 兼容 API、迁移读路径和首库 `release_rc1.sh`；不代表默认能力。
- 默认关闭：Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知与生产 Remote MCP 写入。
- 已实现但须独立批准：Feed storage v3、通知 v14–v16、ActorOps v17–v24、付费 Canary、自动新鲜度与外部通知。global 25 仅作惰性历史数据；后续迁移从 26 继续。
- ActorOps v2 单轨：Phase 0–8 已完成，v2 独占 UI/API/来源/抓取/Worker；Route 仅 `active|disabled`。global 36 是当前 ActorOps 在线门，缺失时仅 ActorOps 返回 migration-required；不调用付费服务。
- 系统参数：global 32 提供 21 项 workspace 热调；Owner/Admin Web/MCP 共用 proposal、确认、CAS；已有库须先完成 global 31；排除秘密、端点和付费 Actor。
- ActorOps 稳定控制环：global 36 只为 untouched Route 开启 proof-gated `auto_replace_non_last`。候选须对当前 ready Binding 完成最多两个最终有效 Probe；YouTube 还须由 exact Manifest 证明 `all` 与最新排序。只替换已确认故障的非最后一路，既有预算、授权、单 Probe、对账和人工 Replacement 门不变。
- ActorOps 高适配闭环：候选获取、系统可用性判断和稳定投入使用分为三阶段；Manifest v1 可选有界 Dataset 展开，Runtime/Maintenance/Replacement/Revalidation 共享验证入口。已结算映射失败在同一 Replacement plan 内最多两轮复用原 Dataset 自动修正，新增 Actor Run 为零；真实证明完成前不得标记 `system_usable`，最终应用仍需人工确认。
- OpenClaw 全来源订阅已实现；社交源仅建 pending Binding。

当前轻量门禁任务基线为 `16014e4` / `v2.3.3`；任何运行操作前仍必须以实际 API、Worker 和容器 revision 重新核对。

## 迁移与发布矩阵

| 事项 | 先决条件 | 执行方式 | 通过条件 |
| --- | --- | --- | --- |
| Feed storage v3 | 停 API/Worker、无活跃任务 | dry-run、UTC `0600` backup、显式 apply | marker、hash backfill、integrity、foreign keys 与 readiness |
| notification v14–v16 | 上一 schema 已完成 | 同上，不调用 Transport | 表/约束/历史映射、API 与 Worker ready |
| ActorOps v17–v24 | 无 Discovery/Canary/新鲜度 Job | 同上，不联网、不调用 AI/Actor | 精确 migration checksum、完整表形状、integrity/foreign keys 与 readiness；global 25 不作为前置 |
| ActorOps v2 global 26（已实现、未启用） | 停 API/Worker，全部非终态 ActorOps 与未结费用先收敛 | 显式 dry-run、`0600` backup、apply、v24 只读摘要 backfill | fresh/existing/repeat apply、integrity/foreign keys、global 25 完全不读写；不复制 inflight，缺 marker 不改变 v1 readiness |
| ActorOps v2 global 33（本地已迁移验证、未部署 VPS） | 有效 global 32；停 API/Worker | `scripts/migrate_actorops_v2_stability.py` 先 preview、再显式 `--apply`；创建 `0600` backup | fresh/existing/repeat/partial/rollback、marker/shape、integrity/foreign keys；显式关闭策略保持关闭，旧费用/Attempt/Replacement 不丢失 |
| ActorOps v2 global 34（本地实现、未部署 VPS） | 有效 global 33；停 API/Worker | `scripts/migrate_actorops_v2_revalidation.py` 先 preview、再显式 `--apply`；创建 `0600` backup | 只替换 Candidate 生命周期触发器；有效内容恢复 probationary，无可发布内容只恢复 static_valid 且不计替换证明；原 Attempt/费用不改写 |
| ActorOps v2 global 35（本地实现、未部署 VPS） | 有效 global 34；停 API/Worker | `scripts/migrate_actorops_v2_sampling.py` 先 preview、再显式 `--apply`；创建 `0600` backup | 私有 InputPlan sidecar shape、integrity/foreign keys 与 exact marker；不联网、不调用 Actor/AI、不改写既有 Attempt/费用 |
| ActorOps v2 global 36（本地已迁移、未部署 VPS） | 有效 global 35；停 API/Worker | `migrate_actorops_v2_verified_replacement.py` preview 后显式 apply，建 `0600` backup | 仅 untouched Route 开启证明门控替换；不覆盖 operator，不联网或改历史事实 |
| 付费 Actor/AI | operator 明确授权 | 单次有上限 canary | 费用、远端 Run、来源结果与回滚证据 |
| 正式 VPS 升级 | 干净且等同 `origin/main` 的 main | `./scripts/release_vps.sh release vX.Y.Z` | 精确 SHA main Gate、Tag smoke、镜像 revision/source digest、API/Worker/前端与容器健康 |

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
8. **Phase 7B1 — 已完成**：global30 重建 v2 Route/Binding 表，只接受 `active|disabled`，将历史 `shadow` 归一为 disabled，并删除 `source_v1_generation`。fresh store 由 Adapter Registry 种入 disabled Route/Policy；已有库只可离线备份、apply、校验，不联网、不 DROP v1 历史表。
9. **Phase 7B2–8 — 已完成**：移除 feature flag 与 v1 online Runtime/API/Worker/UI；fresh DB 直接建立 v2 和 shared alerts，历史表仅用于 offline migration/audit/retirement，authorizer online allowlist 为空。

## ActorOps v2 建设沿革

- global 26 建立核心账本和 Adapter，28 建立商城/Replacement，30 完成单轨，31 建立 resilience，32 提供 typed settings，33 收口稳定环，34 支持 Dataset 重验恢复，35 保存私有 InputPlan，36 开启证明门控的非最后一路替换；global 25 永久惰性。
- 现役运行保持单一 Reconciler、费用单调、unknown-start 只读对账、Publication fence、可恢复 Discovery 和 exact Revision 合同；历史 shadow/v1 切流语义已由 D176 取代，详细理由保留在 D160–D181。
- 真实 Actor 与付费 Probe 仍须逐次独立授权并保留费用证据；本地已在本次授权范围内用单 Run 上限验证真实数据面，生产迁移与 VPS 发布均未执行，仍须各自的显式迁移/发布门。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知服务、React UI、Remote MCP、浏览器 OpenClaw、存储治理和可观测性。

Global 33 为 untouched workspace/Route 提供 `system_default` 维护；global 36 只为同一路由开启证明门控的非最后一路替换。exact-revision 预检、当前 Binding Probe、账本、预算和 Owner/Admin 仍是硬门；operator 策略不覆盖，人工 Replacement 保留事实。新增平台仍通过独立 Adapter 注册。

不做 archive analytics、Graph、推荐/embedding、站内原文代理、多 workspace、商业计费、OAuth、客户间共享 OpenClaw、服务器代理 Gateway 或未授权的真实外部调用。旧 CLI、静态站、scheduler、本地 MCP、archive/Graph/feedback API 不再是兼容面。

## 验证门禁

1. 每个任务按 `snapshot → 定向测试 → 主动审查 diff → 一次 impacted preflight` 推进；冻结单体相对 snapshot `base_sha` 不得净增长，缩小不修改策略文件。
2. `preflight` 接受 snapshot、staged 或 base/head 范围；未知可执行改动 fail closed 到无 Docker/Playwright 的全量代码检查。新文件/函数遵守 `tests/code_size_policy.json` 的唯一硬上限；目标行数、复杂度和嵌套只报告。
3. PR 的 UI 门禁按 ActorOps、Workbench、视觉归属选择 Playwright spec；应用外壳、设计系统、全局路由与未知 UI 才跑全套。最终 main SHA 运行一次权威完整 Gate；完整失败后先复验失败 spec，修复后最多再完整运行一次。
4. 正式发布复用精确 main SHA 的成功 Gate；Tag 仅做隔离 API Docker smoke。基础镜像按 digest 固定，本地构建 `linux/amd64` 后 VPS 只 `docker load`，不得构建本仓库。共享健康检查同时核对 API/Worker、双容器 healthy、前端资源、revision 与镜像 source digest；`starting` 不触发回滚。
5. 控制面变更必须运行 Markdown 控制检查、schema-v3 validator、worklog validator、JSON 校验和 `git diff --check`。
6. ActorOps v2 的通用生产模块目标不超过 400 行、硬上限遵守 `tests/code_size_policy.json`；每个订阅类型拥有独立 Adapter 和参数化合同测试。新增平台通常只能新增 Adapter、注册项与平台测试，若必须修改通用流程则先更新架构合同和决策。

## 历史入口

- 历史计划与上下文读取规则：`archive/project-history/control/`。
- 历史实施报告、设计与过期运行手册：`archive/project-history/` 下的索引目录。
- 决策理由：`docs/decisions/`；仅在任务需要时按索引读取。
- 工作执行记录：`WORKLOG.md` 与 `archive/worklog/`；原始旧日志在 `archive/legacy-worklog/`。
