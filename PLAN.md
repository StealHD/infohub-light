<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力状态

- 核心：小团体账号与角色、来源订阅、共享获取、用户作用域 Feed/History、Worker 队列、React/HeroUI Service UI、受保护媒体、可观测性和本地 OpenClaw 直连。
- 兼容：旧设置 URL、Service DB snapshot 双读、ActorOps 兼容 API、schema 迁移读路径和首库 `release_rc1.sh`。兼容接口不等于默认产品能力。
- 默认关闭：Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知与生产 Remote MCP 写入。
- 已实现但须独立批准：Feed storage v3、通知 schema v14–v16、ActorOps schema v17–v23、付费 Canary、自动新鲜度站立授权、外部 Webhook/Telegram/Email 验收。

本任务代码基线为 `32fc41e`（发布流程优化）；最近记录的生产基线为 `8ef4c6bf6491` / `v2.2.13`，任何运行操作前必须以实际 API、Worker 和容器 revision 重新核对。

## 迁移与发布矩阵

| 事项 | 先决条件 | 执行方式 | 通过条件 |
| --- | --- | --- | --- |
| Feed storage v3 | 停 API/Worker、无活跃任务 | dry-run、UTC `0600` backup、显式 apply | marker、hash backfill、integrity、foreign keys 与 readiness |
| notification v14–v16 | 上一 schema 已完成 | 同上，不调用 Transport | 表/约束/历史映射、API 与 Worker ready |
| ActorOps v17–v23 | 无 Discovery/Canary/新鲜度 Job | 同上，不联网、不调用 AI/Actor | 精确 migration checksum、完整表形状、integrity/foreign keys 与 readiness |
| 付费 Actor/AI | operator 明确授权 | 单次有上限 canary | 费用、远端 Run、来源结果与回滚证据 |
| 正式 VPS 升级 | 干净且等同 `origin/main` 的 main | `./scripts/release_vps.sh release vX.Y.Z` | 精确 SHA main Gate、Tag smoke、API/Worker/前端 revision |

## 推进顺序

1. 先处理各项生产数据库迁移；普通发布拒绝隐式迁移。
2. 只对免费公共来源启用 shared acquisition，观察自然周期和用户隔离。
3. 经独立授权后再做 Key pool、Actor/AI 或真实通知的有界 canary。
4. 维持 Feed/History、用户隔离、通知 outbox、存储预演/恢复和三视口 UI 回归。
5. 后续十个独立 CI 提交记录 preflight 提前拦截数、full/CI/release 失败根因和 mapping miss；验收要求已知问题进入 full/release 为 0、同一根因重复为 0、VPS 上传前代码类失败为 0。观察期结束前完成门禁仍使用 full。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知服务、React UI、Remote MCP、浏览器 OpenClaw、存储治理和可观测性。

不做 archive analytics、Graph、推荐/embedding、站内原文代理、多 workspace、商业计费、OAuth、客户间共享 OpenClaw、服务器代理 Gateway 或未授权的真实外部调用。旧 CLI、静态站、scheduler、本地 MCP、archive/Graph/feedback API 不再是兼容面。

## 验证门禁

1. 每个任务按 `snapshot → 主动审查任务 diff → 修复已知问题 → preflight → 完整门禁` 推进；失败先定向修复和复验，禁止把 full/CI/部署当成首次发现明显问题的步骤。
2. `preflight` 接受 snapshot、staged 或 base/head 范围，运行产品文档、控制、语法和受影响测试；未知可执行改动 fail closed 到无 Docker/Playwright 的全量代码检查。
3. 任务完成、合并前和十提交观察期仍使用 `python scripts/test_gate.py run --mode full`；preflight/targeted 只负责快速反馈，不降低完成标准。
4. 正式发布复用精确 main SHA 的成功 Gate；Tag 仅做隔离 API Docker smoke。VPS 只 `docker load`，不得构建本仓库。
5. 控制面变更必须运行 Markdown 控制检查、schema-v3 validator、worklog validator、JSON 校验和 `git diff --check`。

## 历史入口

- 历史计划与上下文读取规则：`archive/project-history/control/`。
- 历史实施报告、设计与过期运行手册：`archive/project-history/` 下的索引目录。
- 决策理由：`docs/decisions/`；仅在任务需要时按索引读取。
- 工作执行记录：`WORKLOG.md` 与 `archive/worklog/`；原始旧日志在 `archive/legacy-worklog/`。
