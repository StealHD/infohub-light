<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力状态

- 核心：小团体账号与角色、来源订阅、共享获取、用户作用域 Feed/History、Worker 队列、React/HeroUI Service UI、受保护媒体、可观测性和本地 OpenClaw 直连。
- 兼容：旧设置 URL、Service DB snapshot 双读、ActorOps 兼容 API、schema 迁移读路径和首库 `release_rc1.sh`。兼容接口不等于默认产品能力。
- 默认关闭：Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知与生产 Remote MCP 写入。
- 已实现但须独立批准：Feed storage v3、通知 schema v14–v16、ActorOps 现役 schema v17–v24、付费 Canary、自动新鲜度站立授权、外部 Webhook/Telegram/Email 验收。global 25 的 auto-pool 实验表若已存在仅作惰性历史数据，不属于 readiness、fresh bootstrap 或运行时依赖；后续全局迁移从 26 继续。
- 计划中：ActorOps v2 采用 stable-fetch-first、控制面/数据面隔离和 `RouteKey → Adapter` 注册架构；Phase 0 只冻结基线与合同，v2 schema、feature flag、站立授权和运行时尚未实现或启用。

当前轻量门禁任务基线为 `16014e4` / `v2.3.3`；任何运行操作前仍必须以实际 API、Worker 和容器 revision 重新核对。

## 迁移与发布矩阵

| 事项 | 先决条件 | 执行方式 | 通过条件 |
| --- | --- | --- | --- |
| Feed storage v3 | 停 API/Worker、无活跃任务 | dry-run、UTC `0600` backup、显式 apply | marker、hash backfill、integrity、foreign keys 与 readiness |
| notification v14–v16 | 上一 schema 已完成 | 同上，不调用 Transport | 表/约束/历史映射、API 与 Worker ready |
| ActorOps v17–v24 | 无 Discovery/Canary/新鲜度 Job | 同上，不联网、不调用 AI/Actor | 精确 migration checksum、完整表形状、integrity/foreign keys 与 readiness；global 25 不作为前置 |
| ActorOps v2 global 26（计划） | Phase 1 完成、停 API/Worker、无非终态 ActorOps Job | 显式 dry-run、`0600` backup、apply、v24 只读 backfill | fresh/existing/repeat apply、integrity/foreign keys、global 25 完全不读写；未启用 v2 时不改变 v1 readiness |
| 付费 Actor/AI | operator 明确授权 | 单次有上限 canary | 费用、远端 Run、来源结果与回滚证据 |
| 正式 VPS 升级 | 干净且等同 `origin/main` 的 main | `./scripts/release_vps.sh release vX.Y.Z` | 精确 SHA main Gate、Tag smoke、API/Worker/前端 revision |

## 推进顺序

1. 先处理各项生产数据库迁移；普通发布拒绝隐式迁移。
2. 只对免费公共来源启用 shared acquisition，观察自然周期和用户隔离。
3. 经独立授权后再做 Key pool、Actor/AI 或真实通知的有界 canary。
4. 维持 Feed/History、用户隔离、通知 outbox、存储预演/恢复和三视口 UI 回归。
5. 开发切片只运行直接受影响测试；任务末运行一次 impacted preflight，PR 的 Linux UI 只跑映射 spec，最终 main SHA 运行一次权威完整 Gate。已知问题进入 full/release、同根因重复和 VPS 上传前代码类失败均须为 0。

## ActorOps v2 分阶段计划

1. **Phase 0 — 已完成条件**：从 `ce12561896642684ae310ba111f2ce4efb749cf1` 建立 `codex/actorops-v2`，保存 task snapshot，完成代码/表/状态/API/UI/测试盘点、D160 与 planned 合同；不修改产品代码或运行数据。
2. **Phase 1 — Domain 与 global 26**：建立不超过七张核心表的 v2 schema、单调状态模型、Repository、显式离线迁移和 v24 只读 backfill；global 25 永久惰性。新行为只进入 `src/services/actorops/**`，旧冻结单体只能缩小。
3. **Phase 2 — 稳定获取数据面**：通用执行顺序为 Active、Standby、Last Known Good、平台明确支持的免费原生降级；一个 ready Actor 即可获取并标记 degraded，两个以上才为 healthy。Publication fence 只保护本来源目标、binding 与实际 Candidate。
4. **Phase 3 — 统一对账与 Worker 隔离**：单一 Reconciler 只读取和结算既有远端 Run；unknown start 只冻结对应 Attempt/费用预留，Actor 控制任务不再成为普通 Fetch claim 的同步前置。
5. **Phase 4 — 可恢复 Discovery**：Store、Metadata、Build/Pricing/Schema、Mapping、Ranking、Persist 每步保存 checkpoint；AI 只增强无法确定的映射，AI 不可用不能阻止确定性候选完成。
6. **Phase 5 — 站立授权**：默认关闭，管理员一次启用后按每 Probe `$0.05`、每 Route 每 UTC 日 5 次、Workspace 每 UTC 月 `$3.00` 的上限自动验证、补 Standby 并替换非最后一个不健康 Actor；最后一个可运行 Actor 永不自动移除。
7. **Phase 6 — 平台切换**：YouTube、Instagram、X 分别以独立提交执行 backfill、shadow、20 次自然获取和 3 次重启验收；shadow 不得额外启动付费 Actor，平台观察期保留冻结 v1 回退快照。
8. **Phase 7 — API/UI 收敛**：现有 `/api/admin/apify-*` 路径先作兼容 facade，新增健康、Active/Standby/LKG、degraded reason 与维护策略投影；UI 不再直接展示 Batch、Stage 和多层 generation。
9. **Phase 8 — 删除旧链与完整门禁**：删除 Mixin、`globals().update()`、重复 Router 和三套恢复链；保留历史迁移和只读审计，运行完整代码、迁移、chaos、Playwright 与控制面门禁。

每个 Phase 独立提交；行为测试先在该 Phase 内观察失败，再随实现转绿，禁止提交已知失败。Phase 6 的三个平台各自独立提交和回退边界。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知服务、React UI、Remote MCP、浏览器 OpenClaw、存储治理和可观测性。

ActorOps v2 Phase 0 仅覆盖规划和控制面合同，不创建 schema、不切流、不启动 Actor/AI、不改变现有费用审批和运行行为。后续实现仅覆盖已登记的 `platform + target_type + capability`；新增平台通过独立 Adapter 注册，不把平台分支加入通用 Runtime、Discovery、Repository 或 Reconciler。

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
