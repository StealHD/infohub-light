<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力与阶段

- 2026-09-07：新增服务端 OpenClaw 连接，凭据由 API 持有，会话按账号隔离；上线状态以部署验证为准。

当前阶段是维护现役 Service 产品、完善 OpenClaw 工作区，并按目标环境证据推进显式迁移和受控启用。下表描述代码支持与默认策略，不表示某个本地或生产环境已经启用。

| 分类 | 当前范围 |
| --- | --- |
| `core` | 小团体账号与角色、来源订阅、共享获取实现、用户作用域 Feed/History、Worker 队列、React/HeroUI、受保护媒体、可观测性及本地 OpenClaw 集成 |
| `compatibility` | 旧设置 URL、Service DB snapshot 双读、稳定 ActorOps v2 alias、离线迁移读路径、首库引导；退役 v1 API 不恢复运行语义 |
| `disabled` | 默认关闭 Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知和生产 Remote MCP 写入；按各自配置及授权启用 |
| `planned` | 根据目标环境现状推进已有迁移、付费 canary、外部通知和受控写入的上线验证；迁移工具已实现不等于目标数据库已迁移 |

当前主要实现：

- ActorOps v2 已完成单轨收口；现役接口、来源与 Worker 使用 v2。当前代码要求 global 36；缺失时 ActorOps 局部返回 migration-required。稳定控制环、Dataset 重验、InputPlan 与证明门控替换的语义见 [ActorOps 合同](docs/contracts/api/actorops-v2-planned.md)。
- 系统参数已实现 global 32 的 workspace 热调及 Owner/Admin Web/MCP proposal、确认与 CAS；配置范围与前置条件由 API/架构合同维护。
- OpenClaw 全来源订阅和平级 Agent Workspace 已合入本分支，相关实现为 `b4f45a16`，集成提交为 `736ed01b`。来源就绪条件及 Gateway 生命周期见 [OpenClaw 模块边界](docs/contracts/architecture/openclaw-module-boundaries.md) 与 [Agent Workspace](docs/contracts/ui/agent-workspace.md)。

## 验证与部署证据

- ActorOps global 33–36 的历史实施与验证状态、当时未部署 VPS 的记录见本页历史快照、决策 D189/D199 及关联工作记录；这些记录保留当时状态，不替代目标环境复核。
- Agent Workspace 的实现与边界理由见决策 D203–D205；本计划未提供该分支已部署的证据。
- 操作前核对目标环境实际 API/Worker/容器 revision、readiness 与 migration marker。验证结果须绑定相应代码版本；历史任务的真实调用证据不扩展本任务授权。
- 测试、提交、main 与发布 Gate 的顺序统一由 [验证流程](docs/dev/test-gate.md) 维护；构建、迁移、健康与回滚统一由 [运行时合同](docs/contracts/architecture/jobs-notifications-runtime-migrations.md#310-runtime--migration-boundary) 维护。

## 推进顺序

1. 对计划操作的环境确认迁移现状与前置条件，按现役合同处理待执行迁移；普通发布不隐式迁移。
2. 优先对免费公共来源验证共享获取，观察自然周期、来源就绪和用户隔离。
3. 在对应授权范围内进行 Key pool、Actor/AI、真实通知或 MCP 写入的有界验证，记录远端调用、费用和恢复证据。
4. 维持 Feed/History、通知 outbox、存储恢复、Agent 连接生命周期及三视口 UI 回归；新增平台遵循独立 Adapter 和参数化合同测试。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知、React UI、Remote MCP、Browser OpenClaw、存储治理和可观测性。

不做 archive analytics、Graph、推荐/embedding、站内原文代理、多 workspace、商业计费、OAuth、客户间共享 OpenClaw、服务器代理 Gateway 或 Inscope Agent 后端。旧 CLI、静态站、scheduler、本地 MCP、archive/Graph/feedback API 不再是兼容面。

## 历史入口

已完成的 ActorOps Phase 0–8、迁移矩阵和建设沿革原文保存在 [2026-09-05 计划快照](archive/project-history/control/PLAN-schema3-2026-09-05.md)，仅用于解释历史。其他历史按 [归档索引](archive/project-history/README.md) 定位；决策理由与任务验证分别按 [决策索引](docs/decisions/README.md) 和 [WORKLOG](WORKLOG.md) 查询。
