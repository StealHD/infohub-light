<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前能力状态

- 核心：小团体账号与角色、来源订阅、共享获取、用户作用域 Feed/History、Worker 队列、React/HeroUI Service UI、受保护媒体、可观测性和本地 OpenClaw 直连。
- 兼容：旧设置 URL、Service DB snapshot 双读、ActorOps 兼容 API、schema 迁移读路径和首库 `release_rc1.sh`。兼容接口不等于默认产品能力。
- 默认关闭：Remote MCP、OpenClaw chat、图片 I/O、Apify Key 池、付费 Actor/AI、真实通知与生产 Remote MCP 写入。
- 已实现但须独立批准：Feed storage v3、通知 schema v14–v16、ActorOps 现役 schema v17–v24、付费 Canary、自动新鲜度站立授权、外部 Webhook/Telegram/Email 验收。global 25 的 auto-pool 实验表若已存在仅作惰性历史数据，不属于 readiness、fresh bootstrap 或运行时依赖；后续全局迁移从 26 继续。

当前轻量门禁任务基线为 `16014e4` / `v2.3.3`；任何运行操作前仍必须以实际 API、Worker 和容器 revision 重新核对。

## 迁移与发布矩阵

| 事项 | 先决条件 | 执行方式 | 通过条件 |
| --- | --- | --- | --- |
| Feed storage v3 | 停 API/Worker、无活跃任务 | dry-run、UTC `0600` backup、显式 apply | marker、hash backfill、integrity、foreign keys 与 readiness |
| notification v14–v16 | 上一 schema 已完成 | 同上，不调用 Transport | 表/约束/历史映射、API 与 Worker ready |
| ActorOps v17–v24 | 无 Discovery/Canary/新鲜度 Job | 同上，不联网、不调用 AI/Actor | 精确 migration checksum、完整表形状、integrity/foreign keys 与 readiness；global 25 不作为前置 |
| 付费 Actor/AI | operator 明确授权 | 单次有上限 canary | 费用、远端 Run、来源结果与回滚证据 |
| 正式 VPS 升级 | 干净且等同 `origin/main` 的 main | `./scripts/release_vps.sh release vX.Y.Z` | 精确 SHA main Gate、Tag smoke、API/Worker/前端 revision |

## 推进顺序

1. 先处理各项生产数据库迁移；普通发布拒绝隐式迁移。
2. 只对免费公共来源启用 shared acquisition，观察自然周期和用户隔离。
3. 经独立授权后再做 Key pool、Actor/AI 或真实通知的有界 canary。
4. 维持 Feed/History、用户隔离、通知 outbox、存储预演/恢复和三视口 UI 回归。
5. 开发切片只运行直接受影响测试；任务末运行一次 impacted preflight，PR 的 Linux UI 只跑映射 spec，最终 main SHA 运行一次权威完整 Gate。已知问题进入 full/release、同根因重复和 VPS 上传前代码类失败均须为 0。

## 范围与非目标

本阶段覆盖来源、订阅、Feed、稳定历史、任务、受控 AI/Apify、通知服务、React UI、Remote MCP、浏览器 OpenClaw、存储治理和可观测性。

不做 archive analytics、Graph、推荐/embedding、站内原文代理、多 workspace、商业计费、OAuth、客户间共享 OpenClaw、服务器代理 Gateway 或未授权的真实外部调用。旧 CLI、静态站、scheduler、本地 MCP、archive/Graph/feedback API 不再是兼容面。

## 验证门禁

1. 每个任务按 `snapshot → 定向测试 → 主动审查 diff → 一次 impacted preflight` 推进；冻结单体相对 snapshot `base_sha` 不得净增长，缩小不修改策略文件。
2. `preflight` 接受 snapshot、staged 或 base/head 范围；未知可执行改动 fail closed 到无 Docker/Playwright 的全量代码检查。新文件/函数遵守 `tests/code_size_policy.json` 的唯一硬上限；目标行数、复杂度和嵌套只报告。
3. PR 的 UI 门禁按 ActorOps、Workbench、视觉归属选择 Playwright spec；应用外壳、设计系统、全局路由与未知 UI 才跑全套。最终 main SHA 运行一次权威完整 Gate；完整失败后先复验失败 spec，修复后最多再完整运行一次。
4. 正式发布复用精确 main SHA 的成功 Gate；Tag 仅做隔离 API Docker smoke。VPS 只 `docker load`，不得构建本仓库。共享健康检查等待 API/Worker、双容器 healthy、前端与公网 revision；`starting` 不触发回滚。
5. 控制面变更必须运行 Markdown 控制检查、schema-v3 validator、worklog validator、JSON 校验和 `git diff --check`。

## 历史入口

- 历史计划与上下文读取规则：`archive/project-history/control/`。
- 历史实施报告、设计与过期运行手册：`archive/project-history/` 下的索引目录。
- 决策理由：`docs/decisions/`；仅在任务需要时按索引读取。
- 工作执行记录：`WORKLOG.md` 与 `archive/worklog/`；原始旧日志在 `archive/legacy-worklog/`。
