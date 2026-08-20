# ActorOps v2 实施盘点

> 状态：Phase 0 基线盘点，基于 `ce12561896642684ae310ba111f2ce4efb749cf1`。本文只记录实现路由、迁移映射和测试证据；当前/计划产品语义分别以 `docs/contracts/api/`、`docs/contracts/architecture/`、`PLAN.md` 和 D160 为唯一真源。

## 1. 基线与结论

- 分支：`codex/actorops-v2`，从本地 `main` 精确建立；task snapshot 为 `/tmp/actorops-v2-impact.json`。
- 本阶段不读取真实 `data/service.db`、日志、历史站点或 `data/horizon.db`，不启动 Actor、AI、通知或真实 Provider。
- 后端定向基线：481 个 ActorOps、迁移、Worker Discovery 与 YouTube 测试全部通过。
- 前端定向基线：`frontend/src/features/apify-actors` 共 9 个 Vitest 文件、35 个测试全部通过。
- Playwright 映射为 `actorops-pool-management.spec.ts` 与 `production-admin.spec.ts`；Phase 0 未重建目标 revision 的本地服务，因此只记录映射，不声称浏览器基线已执行。
- 当前测试充分验证了 v1 fail-closed 合同，但其中部分断言（2/2 才运行、unknown start 全局阻断、恢复时回退 generation/重开终态）是 v2 需要替换的旧产品规则，不是长期不变量。

## 2. 当前实现清单

### 2.1 服务与状态机

| 责任 | 当前主要位置 | 观察 |
| --- | --- | --- |
| 总服务、Route、Candidate、Discovery、Stage、Binding | `src/services/apify_actor_ops.py` | 10,550 行，混合领域、SQL、事务、投影和兼容逻辑 |
| 来源执行、Attempt、publication fence | `src/services/apify_actor_route.py` | 4,042 行，平台执行和恢复事实耦合 |
| Discovery | `apify_actor_discovery*.py`、`apify_actor_youtube_*.py` | 通用流程仍包含 X/YouTube/Instagram 条件分支 |
| Runtime、Manifest、Canary | `apify_actor_runtime.py`、`apify_actor_manifest.py`、`apify_actor_canary.py` | 平台 target/host/字段知识进入通用模块 |
| Pool/Stage | `apify_actor_pool_*.py` | 多个 Mixin 通过 `globals().update(vars(ops))` 读取主模块私有符号 |
| 恢复与对账 | `apify_actor_restart_recovery.py`、`apify_registered_run_reconciliation.py`、`apify_actor_recovery_continuation.py` | 同一远端 Run 事实存在多条恢复入口 |
| Resilience/新鲜度 | `apify_actor_resilience.py`、`apify_actor_freshness.py` | Route、来源、Key、Stage 和费用状态交叉写入 |
| Worker 编排 | `worker_cycle.py`、`worker_actor_cycle.py`、`worker_actor_*_handler.py` | Actor 控制维护位于普通 claim 前置路径 |

当前 `src/services/apify_actor*.py`、ActorOps API 和 schema helper 合计约 38,893 行。冻结文件包括 `apify_actor_ops.py`、`apify_actor_route.py`、`apify_actor_discovery.py`、`apify_actor_runtime.py`、`apify_actor_manifest.py`、`apify_actor_canary.py`、`apify_actor_resilience.py` 和 `service_store.py`；v2 不得让它们相对 task snapshot 增长。

### 2.2 平台与订阅类型

现有 `apify_actor_capability_matrix.py` 已用 `platform + target_type + capability` 登记：

- `x/profile/items`；
- `youtube/channel/items`；
- `instagram/profile/items`。

但它目前只登记能力和门槛，没有真正绑定完整 Adapter。平台知识仍分散在 Runtime、Discovery、Manifest、YouTube input/observation、source projection 和原生 fallback 中。因此新增平台或同平台新订阅类型仍需修改通用模块。

YouTube 已存在 `youtube_actor_source.py` 和 `apify_native_fallback.py`；实际代码可以在来源认证 Actor 失败后执行受限 Atom/RSS 降级。X、Instagram 没有等价的可信免费降级。

### 2.3 API 与 UI

- 现役读入口集中在 `/api/admin/apify-routes*`、Discovery Run、Canary plan/batch、freshness 和 diagnostic events。
- 写入口覆盖 pool refresh、Canary batch、active pool、verified activation、来源 Canary/binding、preference、freshness 和 Key role。
- API adapter 已部分拆到 `src/api/actor_ops_*.py`，但大量写路由和 SQL 仍位于冻结的 `src/api/server.py`。
- React ActorOps feature 有 27 个实现/测试文件；`HeroActorOpsControlPlane.tsx` 仍是冻结巨型组件，直接组合 Discovery、Pool、来源验证、费用、事件与多类确认框。
- v2 先保持现有 URL 为 facade，内部 Batch/Stage 字段只在兼容期存在；UI 切流后只消费通用 Route/Candidate/Binding/Attempt 投影。

### 2.4 Worker Job

当前核心 Actor Job 为：

- `apify_actor_discovery`；
- `apify_actor_canary_batch`；
- `apify_actor_freshness_check`；
- 来源获取与普通 Feed Job 中的 Actor 路由执行。

Discovery、Canary、freshness、restart recovery、registered Run reconciliation 和 maintenance 在多个周期入口互相调用。v2 将控制任务保留为普通有界 Job，但从普通 Fetch claim 的同步前置路径移出。

### 2.5 数据表与迁移

fresh bootstrap 当前创建 31 个与 ActorOps/Apify/队列相关的表：

- Route/池：`apify_actor_route_profiles`、`apify_actor_routes`、`apify_route_active_slots`、`apify_source_route_bindings`、`apify_actor_candidates`、`apify_actor_adapter_revisions`；
- 执行/费用：`apify_actor_attempts`、`apify_actor_runs`、`apify_actor_validations`、`apify_actor_target_health`；
- Discovery：`apify_actor_discovery_runs`、`apify_actor_discovery_run_revisions`、`apify_actor_discovery_settings`、`apify_actor_metadata_observations`；
- Canary/Stage：`apify_actor_canary_batches`、`apify_actor_canary_batch_items`、`apify_actor_pool_stages`、`apify_actor_pool_stage_sources`、`apify_actor_pool_stage_candidate_settings`；
- Resilience/诊断：`apify_actor_freshness_checks`、`apify_actor_freshness_results`、`apify_actor_evaluation_history`、`apify_actor_diagnostic_events`；
- Key/告警：`apify_key_pool_members`、`apify_key_pool_state` 与五张 Actor alert 表；
- 队列：共享 `fetch_jobs`。

现役 ActorOps global migration 为 17–24。global 25 auto-pool 不在 fresh bootstrap、readiness 或 runtime 中；其 marker/表/历史行若存在必须永久惰性。下一版本只能使用 global 26。

## 3. v2 目标代码架构

```text
Source config
  → RouteKey(platform, target_type, capability)
  → ActorRouteAdapter Registry
  → TargetSpec
  → generic Runtime: Active → Standby → Last Known Good
  → Adapter.build_actor_input
  → generic remote Client + Attempt ledger
  → Adapter.validate_output / map ContentItem
  → generic publication fence
  → optional Adapter native fallback
```

目标包：

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

`ActorRouteAdapter` 的职责固定为：

1. 规范化并验证目标，生成稳定 `TargetSpec`；
2. 声明平台专用 Store 查询和确定性能力检查；
3. 从受控 Manifest 和 FetchWindow 构造 Actor input；
4. 验证输出属于正确平台、目标和内容类型；
5. 映射为通用 `ContentItem`；
6. 可选实现安全原生降级，未支持时明确返回 unsupported。

Adapter 不得访问 SQL、选择 Candidate、管理 Key/预算、推进状态、创建 Job、恢复远端 Run或发布 Feed。通用 Runtime/Discovery/Reconciler 不得出现平台 host、字段或 `if platform == ...`。

同一平台的不同订阅类型必须分开，例如未来 `youtube/video/comments` 不得塞入 `youtube/channel/items`；二者只共享 `youtube/common.py`。新增平台通常只新增 Adapter、Registry 项和测试。

## 4. 文件分类与删除地图

| 分类 | 内容 | 处理 |
| --- | --- | --- |
| KEEP | Apify HTTP client、SecretStore、Key quota primitives、ContentItem、source catalog、alerts/operation event、安全网络策略 | 通过端口复用，不搬入 v2 核心 |
| REWRITE | ActorOps domain、repository、runtime、discovery、policy、reconciler、maintenance、Worker control jobs | 在 `src/services/actorops/**` 新建小模块 |
| TEMPORARY_COMPATIBILITY | 现有 `/api/admin/apify-*` 路由/投影、v1 表读取、`ApifyActorOpsService` 导入面、冻结 v1 平台回退快照 | 逐平台切流期间只作 facade，不新增领域行为 |
| DELETE_AFTER_CUTOVER | Pool Mixins、`globals().update()`、Batch/Stage runtime、三套恢复链、v1 平台条件路由、retired auto-pool runtime | X 切流和兼容期结束后删除 |
| HISTORICAL_ONLY | global 17–25 migration、旧费用/Canary/Stage/Attempt 历史、D103–D159 理由 | 永久保留，不进入新 runtime；global 25 不读写 |

## 5. global 26 数据模型与 backfill

v2 核心最多七张表：

1. `actor_routes_v2`；
2. `actor_candidates_v2`；
3. `actor_source_bindings_v2`；
4. `actor_attempts_v2`，同时承载 fetch/probe 和一对一 remote Run/费用事实；
5. `actor_discovery_jobs_v2`；
6. `actor_discovery_job_candidates_v2`；
7. `actor_maintenance_policies_v2`。

不再为 Batch、Batch Item、Stage、Stage Source、Validation 和恢复补偿形状建立并行状态表。Route health 由 ready Candidate 数实时计算；Discovery stage 与执行状态分离；Attempt/Probe/Discovery terminal 不可重开。

backfill 只读取 global 17–24：

- Route/Profile/active slots → v2 Route 与当前 Candidate 顺序；
- Candidate/Revision/Canary 证据 → Candidate 身份、不可变 Build/Manifest 与初始 readiness；
- Source binding/水位 → v2 Binding、Last Known Good 与 target fingerprint；
- 所有非终态 Job/Stage/Batch/Validation/Attempt/Run、unknown start 和未结费用必须先在 v1 收敛，global 26 拒绝导入 inflight；
- 每 Candidate/Binding 最近成功和失败证据 → 初始健康/LKG 摘要；v2 Attempt/Discovery 从空表开始，不复制完整历史。

完整旧审计历史继续留在 v1 表中只读。global 26 migration 不联网、不调用 AI/Actor、不创建 Feed snapshot；existing DB 显式 apply 前先停 API/Worker、跨 heartbeat 安全窗、拒绝非终态 ActorOps Job并创建 `0600` backup。

## 6. 分阶段测试矩阵

| 阶段 | 必须证明 |
| --- | --- |
| Domain/schema | 合法/非法 transition、generation 单调、terminal 不重开、fresh/existing/repeat migration、global 25 不访问 |
| Adapter contract | RouteKey 唯一、目标规范化幂等、危险目标拒绝、输入有界、跨目标输出拒绝、ContentItem ID 稳定、SQL/Secret 依赖缺失 |
| Runtime | 1 Actor degraded 可获取、Active→Standby→LKG、YouTube 原生降级、X/Instagram unsupported、publication fence 局部化 |
| Reconciler | POST 六个崩溃点、无重复 POST、费用最终收敛、单记录异常不队头阻塞、其他 Job 继续 |
| Discovery | 每 stage 中断恢复、AI off、重放不重复 Candidate/Probe、确定性失败记忆 |
| Maintenance | 单次/每日/月度预算并发原子性、自动补位、非最后一路替换、最后一路保护 |
| Cutover | 每平台 shadow 无额外付费 POST、20 次自然获取、3 次重启、v1 冻结快照回退 |
| API/UI | additive facade、Owner/Admin、CAS、脱敏、健康/LKG/预算投影、旧 Batch/Stage 兼容负向测试 |

每个 Phase 内先写并观察行为测试失败，再完成实现使其通过；提交前运行直接受影响测试、主动 diff 审查和一次 impacted preflight。Phase 7/8 再运行映射 Playwright，最终 main SHA 运行权威完整 Gate。

## 7. Phase 0 退出条件

- [x] 新 worktree、分支和 schema-v2 impact snapshot 已创建；
- [x] 当前生产代码、API、Worker、表、迁移、UI 和测试已盘点；
- [x] 通用流程与每订阅类型独立 Adapter 的边界已进入架构合同；
- [x] stable-fetch-first、standing authorization、native fallback 和 global 26 已进入 D160/API planned 合同；
- [x] 后端与 Vitest 定向基线通过；

任务最终的控制面校验、impacted preflight、worklog 与提交证据由 `WORKLOG.md` 和 Git 记录，不在本盘点文档复制。

## 8. Phase 1 实施结果

- Domain、Adapter Port/Registry、Policy 和 caller-owned SQLite Repository 已建立，通用模块不含真实平台分支；
- global 26 七表、单调 trigger、fresh bootstrap、v24 摘要 backfill 与离线 CLI 已建立；
- global 25 保持惰性，existing v24 缺少 26 时现役 API/Worker readiness 不变；
- global 26、Domain、Repository 与迁移保持不变，Phase 2 在其上继续实现数据面。

## 9. Phase 2 实施结果

- `ACTOROPS_V2_ENABLED` 默认关闭；关闭时不读 global 26，开启后才条件 gate API/Worker readiness；
- Active→Standby→LKG、Attempt 幂等账本、局部 publication fence 与 Feed 事务内 LKG/水位已进入通用 Runtime；
- X Profile Items、Instagram Profile Items、YouTube Channel Items 使用独立 Adapter，只有 YouTube 明确提供公共 Atom 降级；
- disabled/shadow Route 继续 v1，shadow 不创建 v2 Attempt 或额外付费 POST；本阶段未把任何 Route 切为 active；
- Reconciler、Discovery、站立授权、API/UI 投影和平台自然流量观察仍留在后续 Phase。

## 10. Phase 3 实施结果

- 通用 Reconciler 只读取并结算已存在的 Attempt/Run/费用事实；不创建、重试、中止 Actor，也不恢复或发布 Dataset；
- Apify durable-run 关联被限制在 `apify_ledger.py`，以 `logical_run_id=attempt_id` 精确关联 reservation；unknown start 仅可由账户空窗口证明终结；
- 远端成功但丢失 publication proof 终结为安全失败，不推进 Feed、LKG 或水位；已结算/未结算逻辑重放分别返回稳定 settled/recovery 错误，均不再次 POST；
- Worker 先 claim 普通 Job，Provider/v1/v2 reconcile 移至 post-job 或 idle housekeeping，异常按 workspace/组件隔离；不新增 Job 类型、global schema、API/UI 或平台切流；
- 下一阶段为可恢复 Discovery checkpoint，不改变默认 flag、Route disabled 或真实来源流量。

## 11. Phase 4 实施结果

- 通用 Discovery 使用 Store Search、Metadata、Validation、Mapping、Ranking、Persist 六个单调阶段；checkpoint 只保存安全 Actor/Build/Schema hash、Candidate ID、rank 和 rejection 摘要，恢复不回退 stage；
- X Profile Items、Instagram Profile Items、YouTube Channel Items 分别提供 schema-proven 确定性 Manifest 映射；通用层没有平台条件，AI 只补充 unresolved mapping 并经 exact Schema 复核；
- `mapping_pending`、`static_valid` 和 `rejected` Candidate 均保持 inactive，不创建 Actor Run、Probe、Dataset、费用 reservation 或 Route assignment；
- Worker 只在 flag 开启且 idle housekeeping 时有界入队既有 `actorops_v2_discovery` Job；flag=false 不读 global 26/global 25，v1 Discovery handler 和表不变；
- 下一阶段为站立授权，不改变默认 flag、Route disabled 或真实来源流量。

## 12. Phase 5 实施结果

- `actor_maintenance_policies_v2` 继续是唯一授权与额度事实：workspace 与 Route 都必须由 enabled Owner/Admin 以 generation CAS 显式启用；默认仍 disabled，没有 HTTP API/UI 或真实授权操作；
- `maintenance.py` 只执行单 Candidate Probe：先经公开 Actor/Build/Schema/价格免费预检，再原子冻结 policy、Route、Candidate、Binding 与目标指纹；每 Route 最多一个未结 Probe，单次 `$0.05`、每 UTC 日 5 次，Workspace 跨 Route 月度实际费用与预留合计最多 `$3.00`；
- Probe 最多一项输出与一次远端启动，不使用 native fallback，不发布 Feed 或 Dataset，也不更新 LKG/水位。可信非空结果才推进 Candidate 证据与 lifecycle；空结果是 no-evidence；未知启动保留给 Reconciler；
- 成功 Candidate 自动补 Standby，或仅在仍有其他 runnable 路径时原子隔离异常 Candidate 并重排 Active/Standby；最后一个 runnable Candidate 保持 assignment 并留下安全保护码；
- Worker 仅在 flag=true 的 idle/post-job housekeeping 以低优先级 `actorops_v2_maintenance` Job 入队；正常 claim、v1 来源获取、API/UI、Route runtime mode 与真实平台流量均未改变。下一阶段才是分平台 shadow/观察/切流。

## 13. Phase 6 切流护栏（尚未执行平台操作）

- `repository_cutover.py` 为单 Route 提供 expected mode/generation CAS，限制相邻 `disabled → shadow → active` 与正常 `active → shadow → disabled`；前进时拒绝本 Route 未结 Attempt/费用，回退不重写远端或 Feed 事实。
- `scripts/actorops_v2_cutover.py` 只读汇总 global 26 marker/shape、Route health、runnable 顺序、Binding readiness、v1/v2 摘要、费用与 blocker；可创建 `0600` 私有 SQLite backup，且只有显式 apply 才切 mode。它不查询 global 25，也不调用来源、Actor、AI、通知或 Feed。
- shadow 选择仅发出无值 operation event 后继续 v1；跨 v1/v2 的 X/Instagram 内容身份统一，YouTube 保持 RSS identity。YouTube 旧 RSS wrapper 遇到 v2 handle 直达通用 v2 executor，避免把 v2 snapshot 交给 v1 Runtime。
- 下一步仍是本地离线 migration/摘要对照，并在每个 Route 输出精确 `20 × candidate × cap` 后逐平台取得费用确认；截至本文更新没有真实 shadow、active、20 次自然获取或重启验收证据，因此 `PLAN.md` 继续停在 Phase 6。
