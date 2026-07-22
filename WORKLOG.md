<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=WORKLOG.md -->
# 工作记录

## 说明
本文件只保留当前开发必要信息和最近记录。完整旧记录已归档到 `archive/worklog/2026-07-08-2026-07-09.md`。

后续 agent 仍需在每次任务结束后追加一条简洁记录。普通代码实现只更新 `WORKLOG.md`；控制面变化才更新对应控制文件。

## 当前状态摘要

### 系统主线

1. Inteliscope InfoHub Light 已采用 init-pro 控制面。
2. 当前正式实施范围以 `PLAN.md` 为准。
3. 当前接口、CLI、静态 payload 和归档合同以 `API_CONTRACT.md` 为准。
4. 当前架构边界以 `ARCHITECTURE_CONTRACT.md` 为准。
5. 开发上下文读取策略以 `CONTEXT_READ_RULES.md` 为唯一真源。

### 最近完成能力

1. 小团体多人 MVP 内核：FastAPI Service API、Service SQLite、用户/角色、catalog、subscriptions、job queue、quota。
2. 配置页 Service API 兼容层：配置页通过 `/api/*` 读写，source action 写入 service tables。
3. 登录门禁和订阅控制台：登录后可查看/管理公共源、私有源、订阅和任务。
4. Worker/job queue 加固：lease、stale running 恢复、重试退避、取消、重试、保留清理。
5. 用户作用域 feed/archive：`user_feed_snapshots/user_feed_items`、archive items/trends/facets/source-quality。
6. Source Catalog API v1：source type registry、`source_key`、旧配置导入、高级源最小测试面板。
7. 真实源验证 v1：catalog 精准 `source_fetch`、真实源 smoke 脚本、RSS/HN/GitHub/Telegram 闭环验证。
8. 多人 Feed v2：结构化 `FeedRunResult`、用户 finalizer、partial/failed/empty 语义和 Service 链路全局文件隔离。
9. Queue/Worker v2：原子 claim token、guarded finalize、heartbeat/续租、同事务 snapshot 和结构化日志。
10. 默认 runtime：API + Worker；scheduler 显式 profile；live/ready/ops 与 UI 自动轮询闭环。
11. Feed v2 显式迁移：只读检查、迁移前备份、幂等 apply、外键/唯一性校验和备份 Git 隔离。
12. member RSS egress 护栏：禁止 URL 环境变量占位、catalog payload 权威、初始/redirect 公网校验和管理员精确 host allowlist。

<!-- init-pro:section name=entries -->
## 最近关键记录

### 2026-07-12 12:45 Codex
- 任务：实现 `rb.jiefs.top` 初版上线收口 RC1
- 读取文件：RC1 计划、控制面、API/UI/Compose/发布脚本、测试与 VPS 只读状态
- 修改文件：跨用户 UI guard、Service Cookie/liveness、Docker/Compose、deployment DB 与 RC 脚本、Nginx、测试、README/合同/报告
- 执行验证：627 项 pytest、54 项 Node、Python/JS/Compose/shell/diff 通过；真实 Docker 镜像/容器/数据隔离和本机浏览器通过；脱敏 DB integrity/FK/0600 通过
- 结果：本地 RC 候选、分阶段 VPS 工具和完整报告就绪；审查发现并修复 Docker build context 暴露整个 data 的风险
- 未解决问题：计划要求 release commit/tag 单独授权，故尚未写入 VPS、staging 或 promote；init-pro schema-2 控制面与当前 schema-3 validator 不兼容
- 控制面变更：更新 API/架构/阶段/defaults/决策 D010，记录不可变镜像与 VPS staged promotion 边界

### 2026-07-08 09:33 Codex
- 任务：初始化项目控制面约束文件
- 读取文件：用户需求、skill `init-pro`
- 修改文件：`PLAN.md`、`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`DECISION_LOG.md`、`CONTEXT_READ_RULES.md`、`WORKLOG.md`、`project-defaults.yaml`
- 执行验证：生成控制文件；详细历史见 `archive/worklog/2026-07-08-2026-07-09.md`
- 结果：生成可复用 AI 协作约束、上下文读取规则和工作记录模板
- 未解决问题：无
- 控制面变更：初始化控制面

### 2026-07-09 09:26 Codex
- 任务：实现订阅控制台 MVP
- 读取文件：订阅控制台计划、`src/api/server.py`、`src/storage/service_store.py`、`src/ui/static/**` 相关文件、API/ServiceStore/静态 UI 测试、控制面文件
- 修改文件：`src/api/server.py`、`src/storage/service_store.py`、`src/ui/static/subscriptions.js`、`src/ui/static/subscriptions.css`、相关测试、控制面文档、`WORKLOG.md`
- 执行验证：目标 API/ServiceStore/静态 UI 测试通过；`node --check src/ui/static/*.js` 通过；`git diff --check` 通过；Docker `horizon-api` healthy；浏览器验证订阅页可用
- 结果：新增 dashboard summary、catalog subscribe/unsubscribe、user-feed-refresh job API 和静态订阅控制台
- 未解决问题：高级 source 类型仍在旧配置页；Worker 生产级加固另排计划
- 控制面变更：更新 API/架构/计划合同，记录订阅控制台边界

### 2026-07-09 09:36 Codex
- 任务：规划 Worker 和任务队列加固
- 读取文件：`PLAN.md`、`WORKLOG.md`、`src/services/job_queue.py`、`src/services/worker.py`、相关测试
- 修改文件：`docs/superpowers/plans/2026-07-09-worker-job-hardening.md`、`WORKLOG.md`
- 执行验证：只读核对当前 Worker/job queue 状态
- 结果：输出 Worker lease、stale running 恢复、失败重试、取消/重试和保留清理计划
- 未解决问题：等待执行
- 控制面变更：新增执行计划文件

### 2026-07-09 09:44 Codex
- 任务：梳理当前项目架构
- 读取文件：`AGENTS.md`、`README.md`、`README_zh.md`、架构/API/计划文件、关键入口/服务/存储/前端文件
- 修改文件：`WORKLOG.md`
- 执行验证：只读架构核对
- 结果：输出当前入口、分层、数据流、存储、前端和部署形态说明
- 未解决问题：无
- 控制面变更：无

### 2026-07-14 11:07 Codex
- 任务：修复预览服务在任务结束后被回收导致页面无法打开
- 读取文件：本地进程、8080 端口与 API 日志
- 修改文件：`WORKLOG.md`
- 执行验证：使用 `launchctl` 托管 `com.inteliscope.preview`；进程保持 running，`/api/health/live` 和 `/feed` 均返回 200
- 结果：预览服务已改为持久用户进程，内置浏览器刷新后可访问 `http://127.0.0.1:8080/feed`
- 未解决问题：Docker Desktop 仍未启动，但不影响当前本地预览
- 控制面变更：无

### 2026-07-09 09:57 Codex
- 任务：执行 Worker 和任务队列加固计划
- 读取文件：Worker/job queue 计划、ServiceStore、JobQueue、Worker、API、订阅页、相关测试和控制面文件
- 修改文件：`src/storage/service_store.py`、`src/services/job_queue.py`、`src/services/worker.py`、`src/api/server.py`、订阅页文件、相关测试、Docker/控制面文件、`WORKLOG.md`
- 执行验证：目标测试组通过；`node --check` 通过；`git diff --check` 通过；Worker `--once` 通过；init-pro 校验通过；Docker/API/浏览器 smoke 通过
- 结果：`fetch_jobs` 增加 lease/retry/cancel/retention 字段和迁移；API 与订阅页支持 cancel/retry 和 failed job 指标
- 未解决问题：SQLite 队列仍是小团体单机形态，不包含 Redis/Celery 级别调度
- 控制面变更：更新 API/架构/计划/defaults/验证报告

### 2026-07-09 10:50 Codex
- 任务：实现用户作用域 Feed 与归档分析 API v1
- 读取文件：ServiceStore、UserFeedStore、ArticleStore、FeedArchiveService、Worker、API、订阅页、相关测试和控制面文件
- 修改文件：`src/services/user_feed_store.py`、`src/services/feed_archive.py`、`src/storage/article_store.py`、`src/services/worker.py`、`src/api/server.py`、订阅页文件、相关测试、控制面文件、`WORKLOG.md`
- 执行验证：目标测试组通过；全量 pytest 通过；`node --check` 通过；Python 编译检查通过；`git diff --check` 通过；init-pro 校验通过；Docker worker/API smoke 通过
- 结果：新增用户 feed snapshot 和 visible item 边界；feed/archive API 默认用户作用域；订阅页新增 API 状态面板
- 未解决问题：未做用户反馈/收藏/已读信号和长期质量趋势
- 控制面变更：更新 API/架构/计划/defaults

### 2026-07-09 11:09 Codex
- 任务：实现 Source Catalog API v1 和高级源迁移入口
- 读取文件：API、ServiceStore、Worker、user_config_builder、订阅页、source registry/ServiceStore/API/Worker/UI 测试、控制面文件
- 修改文件：`src/services/source_type_registry.py`、`src/storage/service_store.py`、`src/api/server.py`、`src/services/worker.py`、订阅页文件、相关测试、控制面文件、`WORKLOG.md`
- 执行验证：目标测试组通过；全量 pytest 通过；`node --check` 通过；Python 编译检查通过；`git diff --check` 通过；init-pro 校验通过；Docker/API/浏览器 smoke 通过
- 结果：新增 source type registry、`source_key`、幂等旧配置导入和高级源 JSON 面板
- 未解决问题：高级源 UI 仍是最小 JSON 表单
- 控制面变更：更新 API/架构/计划/defaults

### 2026-07-09 14:42 Codex
- 任务：实现真实源验证 v1 和 catalog 精准 `source_fetch`
- 读取文件：Worker、user_config_builder、UserFeedStore、FeedArchiveService、ServiceStore、API、真实源 smoke/Worker/API 测试和控制面文件
- 修改文件：`src/services/catalog_source_runner.py`、`src/services/worker.py`、`src/services/user_feed_store.py`、`src/services/feed_archive.py`、`scripts/service_real_source_smoke.py`、相关测试、真实源文档、控制面文件、`WORKLOG.md`
- 执行验证：目标测试组通过；全量 pytest 通过；`node --check` 通过；Python 编译检查通过；`git diff --check` 通过；init-pro 校验通过；Docker API healthy；真实源 smoke 通过
- 结果：`source_fetch` 带 `source_id` 时按 catalog + 当前用户订阅 override 生成单源配置并保存用户 snapshot；真实源 smoke 验证 RSS/HN/GitHub/Telegram 闭环
- 未解决问题：Reddit/Apify 仍作为 optional degraded；长期趋势待用户行为和归档增强
- 控制面变更：更新 API/架构/计划/defaults/真实源文档/验证报告

### 2026-07-09 14:53 Codex
- 任务：实现开发省 token 控制面计划
- 读取文件：`init-pro` skill、`executing-plans` skill、`CONTEXT_READ_RULES.md`、`WORKLOG.md`、`project-defaults.yaml`
- 修改文件：`CONTEXT_READ_RULES.md`、`WORKLOG.md`、`archive/worklog/2026-07-08-2026-07-09.md`、`project-defaults.yaml`、`INIT_PRO_VALIDATION.md`
- 执行验证：init-pro validator → PASS；`git diff --check` → PASS；内容检查确认短 `WORKLOG.md`、归档文件、任务类型最小读取集和 `agent_context_budget` 存在
- 结果：将开发上下文省 token 策略纳入控制面，压缩根 `WORKLOG.md` 并归档旧记录
- 未解决问题：无
- 控制面变更：更新 `CONTEXT_READ_RULES.md` 和 `project-defaults.yaml`，原因是开发上下文读取策略变化

### 2026-07-09 15:07 Codex
- 任务：实现基本功能 API 收口 v1
- 读取文件：`executing-plans`/`test-driven-development` skill、`PLAN.md`、`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、Service API/ServiceStore/UserFeedStore/静态阅读页和目标测试
- 修改文件：`src/storage/service_store.py`、`src/services/user_item_state.py`、`src/services/feed_archive.py`、`src/api/server.py`、`src/ui/static/state.js`、`src/ui/static/utils.js`、`src/ui/static/reader.js`、`src/ui/static/app.js`、相关测试、控制面文件
- 执行验证：目标 RED 测试失败后变绿；`./.venv/bin/pytest tests/test_api_service.py tests/test_service_store.py tests/test_user_feed_store.py tests/test_static_reading_ui.py tests/test_user_item_state.py -q` 通过；`node --check` 目标静态 JS 通过；`./.venv/bin/python -m py_compile src/services/*.py src/api/server.py` 通过
- 结果：新增用户 item state/feedback 表、行为状态服务、`/api/me/item-state`/state/feedback API、feed item `user_state` 注入和阅读页最小操作按钮
- 未解决问题：不做归档趋势、source-quality 或个人排序联动
- 控制面变更：更新 API/架构/计划/defaults，记录用户行为 API 边界

### 2026-07-09 15:16 Codex
- 任务：实现核心 Service API 验收与权限矩阵 v1
- 读取文件：`executing-plans`/`test-driven-development`/`using-git-worktrees` skill、`PLAN.md`、`API_CONTRACT.md`、`WORKLOG.md`、Service API 路由、ServiceStore、真实源 smoke 脚本、API 测试
- 修改文件：`src/api/server.py`、`scripts/service_api_smoke.py`、`docs/dev/service-api-smoke.md`、`tests/test_api_permissions_matrix.py`、`tests/test_service_api_smoke_script.py`、`API_CONTRACT.md`、`PLAN.md`、`project-defaults.yaml`、`WORKLOG.md`
- 执行验证：新增 RED 测试先失败后变绿；`./.venv/bin/pytest tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_service_store.py tests/test_static_reading_ui.py tests/test_service_api_smoke_script.py -q` 通过；`./.venv/bin/python -m py_compile src/api/server.py src/services/*.py scripts/service_api_smoke.py` 通过
- 结果：新增 `/api/*` validation/404 统一错误 envelope、角色权限矩阵测试、核心 API smoke 脚本和 curl 验收文档
- 未解决问题：未运行 Docker 手动 smoke；本组不做归档分析扩展
- 控制面变更：更新 API 合同、阶段计划和 defaults，记录 API 验收边界

### 2026-07-09 15:25 Codex
- 任务：实现 Docker 组合 Smoke 与本地验收固化 v1
- 读取文件：`executing-plans`/`test-driven-development`/`using-git-worktrees` skill、现有 smoke 脚本、Docker compose、smoke 文档、计划/defaults/工作记录
- 修改文件：`scripts/service_stack_smoke.py`、`tests/test_service_stack_smoke_script.py`、`docs/dev/service-api-smoke.md`、`PLAN.md`、`project-defaults.yaml`、`INIT_PRO_VALIDATION.md`、`WORKLOG.md`
- 执行验证：`./.venv/bin/pytest tests/test_service_stack_smoke_script.py tests/test_service_api_smoke_script.py tests/test_real_source_smoke_script.py -q` 通过；Python 编译检查通过；init-pro validator 通过；`git diff --check` 通过；Docker API-only stack smoke 通过
- 结果：新增一条命令启动 Docker API、等待 health、运行核心 API smoke，并可显式追加真实源 smoke 与 worker 的汇总验收脚本
- 未解决问题：未在本记录追加时运行真实 Docker full smoke；默认 API-only 不访问外网
- 控制面变更：更新阶段计划和 defaults，记录组合 smoke 验收能力

### 2026-07-09 16:33 Codex
- 任务：实现静态 UI 最小可用闭环与浏览器验收 v1
- 读取文件：`executing-plans`/`test-driven-development`/`using-git-worktrees` skill、静态 UI JS、smoke 脚本、静态 UI 测试、smoke 文档、计划/defaults/工作记录
- 修改文件：`src/ui/static/auth.js`、`src/ui/static/subscriptions.js`、`scripts/service_ui_smoke.py`、`scripts/service_stack_smoke.py`、相关测试、`docs/dev/service-api-smoke.md`、`PLAN.md`、`project-defaults.yaml`、`WORKLOG.md`
- 执行验证：`./.venv/bin/pytest tests/test_static_reading_ui.py tests/test_service_ui_smoke_script.py tests/test_service_stack_smoke_script.py tests/test_api_service.py -q` 通过；`node --check src/ui/static/*.js` 通过；Python 编译检查通过；init-pro validator 通过；独立 `service_ui_smoke.py` 通过；`git diff --check` 通过；Docker 组合 smoke 在 `docker compose up -d --build horizon-api` 阶段被中断，未完成
- 结果：统一静态 UI auth API 路径，新增 viewer 只读提示、job 错误码显示、UI smoke 脚本和 stack smoke UI 步骤
- 未解决问题：Docker 组合 smoke 未完成；不做复杂前端工程，不扩展归档分析或推荐排序
- 控制面变更：更新阶段计划和 defaults，记录静态 UI smoke 验收能力

### 2026-07-09 19:17 Codex
- 任务：实现用户行为信号轻量阅读体验 v1
- 读取文件：`executing-plans`/`test-driven-development` skill、FeedArchiveService、UserItemStateStore、Service API、静态阅读页、目标测试和控制面文件
- 修改文件：`src/services/user_item_state.py`、`src/services/feed_archive.py`、`src/api/server.py`、`src/ui/static/state.js`、`src/ui/static/index.html`、`src/ui/static/app.js`、`src/ui/static/utils.js`、`src/ui/static/reader.js`、`src/ui/static/subscriptions.js`、相关测试、API/计划/defaults/工作记录
- 执行验证：目标 RED 测试失败后变绿；`./.venv/bin/pytest tests/test_api_service.py tests/test_user_item_state.py tests/test_static_reading_ui.py -q` 通过；`node --check src/ui/static/*.js` 通过；Python 编译检查通过；init-pro validator 通过；`git diff --check` 通过；独立 `service_ui_smoke.py` 通过
- 结果：`/api/feed/latest` 支持当前用户 state 过滤/排序，dashboard 返回 item state 计数，阅读页新增隐藏已忽略和未读优先开关
- 未解决问题：不做推荐模型，不扩展归档趋势或 source-quality
- 控制面变更：更新 API 合同、阶段计划和 defaults，记录行为信号轻量阅读体验

### 2026-07-09 20:02 Codex
- 任务：实现成员管理最小控制台与版本收口 v1
- 读取文件：`executing-plans`/`test-driven-development`/`using-git-worktrees` skill、Service API 用户路由、ServiceStore、订阅控制台、核心 API smoke、目标测试和控制面文件
- 修改文件：`src/api/server.py`、`src/storage/service_store.py`、`src/ui/static/subscriptions.js`、`src/ui/static/subscriptions.css`、`scripts/service_api_smoke.py`、相关测试、`docs/dev/service-api-smoke.md`、`API_CONTRACT.md`、`PLAN.md`、`project-defaults.yaml`、`WORKLOG.md`
- 执行验证：先提交上一组行为信号版本；新增 RED 测试先失败后变绿；`./.venv/bin/pytest tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_service_api_smoke_script.py tests/test_static_reading_ui.py -q` 通过；`node --check src/ui/static/*.js` 通过；Python 编译检查通过；init-pro validator 通过；`git diff --check` 通过
- 结果：管理员可通过 `/api/users` 和订阅控制台查看、创建、启用/禁用、调整角色和重置成员密码；核心 API smoke 覆盖 `/api/users` 和 `member-ui-smoke`
- 未解决问题：不做自助注册、邀请链接、审计日志或多 workspace
- 控制面变更：更新 API 合同、阶段计划和 defaults，记录成员管理边界

### 2026-07-10 14:41 Codex
- 任务：实施 Inteliscope 多人 Feed 产出链路修复计划
- 读取文件：Feed/Worker/API/Store/orchestrator/source adapters/UI/compose/迁移相关代码、测试与控制面文件
- 修改文件：结构化 run/finalizer/LegacyPublisher/network policy/runtime status、ServiceStore/JobQueue/Worker/API/UI、两份 compose、显式迁移脚本、目标测试和控制面文档
- 执行验证：512 项完整 pytest 通过；Node UI 行为测试 4/4、Python 编译、全部静态 JS `node --check`、两份 `docker compose config --quiet`、`git diff --check` 通过；本地 RSS 真实浏览器登录→订阅→queued/running→succeeded→自动 Feed 闭环通过；两用户隔离及连续 20 个本地确定性任务通过；迁移 dry-run 返回 `migration_required=true` 且未修改真实库；init-pro backend strict 校验 59 项全 PASS
- 结果：完成多人 Feed v2 隔离、失败语义、并发可靠性、权限止血、默认 API+Worker、UI 刷新闭环、显式迁移、RSS IP 固定/2 MB 响应上限、catalog 幂等和 auth readiness；最终审查补齐 expired lease、partial retry snapshot、旧 state/job 迁移门禁、全局 HN 继承、personal-only 合并、跨源 provenance 连续 partial、query identity、private import collision 和 member 全局标签越权边界
- 未解决问题：真实 `data/service.db` 尚未执行破坏性 v2 apply；本机 Docker daemon 未运行，故本轮只完成两份 Compose 配置解析，实际 API+Worker+RSS 浏览器闭环使用隔离本地进程完成；用户级 Archive/Graph、个人摘要和个人推送不在本期
- 控制面变更：更新 API/架构/计划/决策/defaults/README/smoke 文档，记录 Feed v2、运行时、迁移与安全边界

### 2026-07-11 12:37 Codex
- 任务：记录 Feed v2 实际迁移与 Docker/浏览器发布验收结果
- 读取文件：`docs/dev/multi-user-feed-v2-implementation-report.md`、`PLAN.md`、`README_zh.md`、`docs/usage_zh.md`、`DECISION_LOG.md`、`project-defaults.yaml`、`WORKLOG.md`
- 修改文件：`docs/dev/multi-user-feed-v2-implementation-report.md`、`PLAN.md`、`README_zh.md`、`docs/usage_zh.md`、`DECISION_LOG.md`、`project-defaults.yaml`、`WORKLOG.md`
- 执行验证：`git diff --check` 通过；未运行 init-pro validator，由主代理统一生成验证报告
- 结果：记录真实库显式迁移、备份与完整性检查、默认 Docker API + Worker、管理员 22-item 刷新和浏览器入口/历史空态验收；阶段转为发布后观察
- 未解决问题：继续观察 heartbeat、队列、snapshot 年龄和 canary 用户隔离
- 控制面变更：更新计划、决策状态和主配置阶段，移除“真实迁移待执行”的过期运行状态

### 2026-07-11 15:15 Codex backend subagent
- 任务：实现用户 Service Feed 周期自动获取的后端调度核心
- 读取文件：`AGENTS.md`、`PLAN.md`、`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、ServiceStore、JobQueue、Quota、Worker 及相关测试
- 修改文件：`src/storage/service_store.py`、`src/services/feed_schedule.py`、`src/services/job_queue.py`、`src/services/quota.py`、`src/services/worker.py`、`tests/test_feed_schedule.py`、`WORKLOG.md`
- 执行验证：目标测试先 18 项 RED；实现后 schedule/queue/store/worker/migration 63 项通过；fresh 全量 pytest 538 项通过；Python 编译、`git diff --check`、两份 Compose 默认 service 列表通过
- 结果：新增 additive 用户计划表、原子到期入队与全量刷新去重、明确 skip/推进语义、配额计数及 Worker 30 秒调度检查；自审补齐 terminal retry 绕过 active refresh 去重
- 未解决问题：API 层必须消费 `(job, created)`，只对新建手动刷新计配额；跨所有手动 job 类型的 quota admission 原子化由主任务统一收口
- 控制面变更：无；本子任务按要求不修改控制文档，由主任务统一更新 API/计划合同

### 2026-07-11 16:26 Codex release/docs subagent
- 任务：完成 Service 自动获取 v1 的 Compose 配置、公共合同、控制面和发布文档
- 读取文件：控制面权威文件、两份 Compose、环境变量示例、schedule/API/Worker 实现与目标测试、README/usage/smoke 文档
- 修改文件：两份 Compose、`.env.example`、runtime 配置测试、API/架构/计划/defaults/决策、README/usage/smoke 文档及自动获取实现报告
- 执行验证：Compose schedule-poll 回归先 RED 后 GREEN；schedule/API/权限/runtime 目标 pytest 78 项、Node DOM 16/16、两份 `docker compose config --quiet`、defaults JSON 和 `git diff --check` 通过
- 结果：Worker 获得默认 30 秒 schedule poll 配置，合同记录 schedule API、原子去重/配额和 ops 指标，用户文档补齐默认关闭周期、真实“获取新内容”和显式已读，并保留 Service 与 legacy 发布隔离
- 未解决问题：真实 Docker 重建、运行指标门槛和管理员连续两个 1 小时 canary 周期待主代理验证；当前 init-pro v0.3 不接受仓库 schema2 strict 参数，兼容 validator 由主代理统一执行；不得把配置解析写成发布通过
- 控制面变更：更新 API、架构、阶段、defaults 和 D009，确认本期仍只做信息获取与 Feed 留存

### 2026-07-11 16:47 Codex
- 任务：完成 Service 自动获取与 Feed 新鲜度 v1 的真实 Docker、两周期 canary、浏览器和发布控制面验收
- 读取文件：自动获取实现报告、`PLAN.md`、`DECISION_LOG.md`、`project-defaults.yaml`、Compose、运行数据库与 API/浏览器状态
- 修改文件：自动获取实现报告、`PLAN.md`、`DECISION_LOG.md`、`project-defaults.yaml`、`WORKLOG.md`
- 执行验证：发布前数据库备份权限与完整性通过；light Compose 重建后仅 API + Worker healthy，live/ready 200；两个真实 scheduled job 均 succeeded/21 items/单 snapshot；ops 门槛通过；两用户两周期 E2E Feed ID 交集为零；浏览器 Feed/计划/显式已读/入口清理与控制台错误检查通过；最终 551 项 pytest、23 项 Node DOM、Python/JS 语法、Compose 和 diff-check 通过
- 结果：管理员 canary 从 1 小时完成两个周期后切回 6 小时，Service 自动获取 v1 转为发布后观察；API 配额原子化问题已由同事务创建/计费/回滚实现收口；最终审查补齐常驻页面自动发现任务、terminal 单次处理与失败接管、Feed 失败重试、旧用户响应隔离、认证切换取消屏障，以及 viewer 角色降级关闭计划/取消 queued 自动任务与异常回滚防护
- 未解决问题：继续观察 6 小时自然周期和来源级 partial/failed；来源健康状态与失败诊断作为下一期候选
- 控制面变更：把自动获取状态从 Docker/canary 待验证更新为已发布验收，并记录可复查运行证据

### 2026-07-13 09:45 Codex
- 任务：停止 RC1 上线并梳理本地 AI 摘要、管理员密钥管理和正式订阅重建需求
- 读取文件：`AGENTS.md`、AI analyzer/prompt/client、Service source registry/API/store、订阅配置 UI、当前本地数据库与配置
- 修改文件：`WORKLOG.md`
- 执行验证：只读确认现有文章摘要依赖提示词长度而无输出硬截断；Apify 已支持 source 级环境变量名但没有管理员密钥注册接口；本地当前为 4 个 smoke 订阅
- 结果：上线流程取消并停在设计确认阶段，未写入密钥、未删除订阅、未修改 VPS
- 未解决问题：需要确认管理员“新增 key”是否允许网页写入真实密钥，随后才能确定安全存储和刷新机制
- 控制面变更：无

### 2026-07-13 11:21 Codex
- 任务：实现本地 AI 概括、管理员 write-only Key 管理并重建四个正式订阅
- 读取文件：AI client/analyzer/prompt/cache、Service API/store/Worker、来源 registry、配置/订阅 UI、Docker/控制面合同及相关测试
- 修改文件：新增 `SecretStore`、summary policy、reset/bootstrap 脚本、管理员 secret API/UI 和测试；更新 AI/Worker/orchestrator、ServiceStore、控制文档、README 与实现报告
- 执行验证：TDD 覆盖 Key 文件/API/UI、摘要截断/回退、Gemini bounded JSON、reset/bootstrap；658 项 pytest、61 项 Node DOM、Python/JS 语法、两份 Compose、diff-check 全通过；Docker API+Worker healthy、live/ready 200；浏览器验证 3 个 Key、4 个订阅、19 条 Feed、3 healthy/1 failing、6 小时计划和 DOM 无密钥；SQLite integrity/foreign keys 正常
- 结果：真实值只写 `data/secrets.env` 且权限 `0600`；本地 catalog/订阅重建为 Apple、OpenAI、Claude Code 和 X；Feed 每条概括非空且不超过 200 字；自动刷新已启用为 360 分钟；公网/VPS 未修改
- 未解决问题：Apify X Actor 尚需在控制台批准 full-access permission；Gemini 当前 Key 返回 429 `RESOURCE_EXHAUSTED`，额度恢复前使用来源摘要/正文/标题回退
- 控制面变更：更新 API/架构/计划/defaults/决策并新增 D011、`docs/dev/local-ai-secret-subscriptions-v1-implementation-report.md`；当前 init-pro 工具仅支持 manifest 模式，仓库 schema-2 strict 参数不兼容

## 追加记录模板

### 2026-07-13 11:50 Codex
- 任务：设计可靠信息源的订阅分类与日常管理方法
- 读取文件：`AGENTS.md`、models、Service 用户配置构建、API 和阅读 UI 的频道/主题/个人标签能力
- 修改文件：`WORKLOG.md`
- 执行验证：只读确认频道、主题、个人标签、来源优先级和分析模式均可落到当前订阅配置与阅读筛选
- 结果：给出领域频道、交叉主题、来源角色、优先级和审阅节奏组成的分类体系
- 未解决问题：尚未批量调整现有订阅或新增管理界面
- 控制面变更：无

### 2026-07-13 11:30 Codex
- 任务：调研当前订阅能力边界内的科技、全球局势、金融可靠信息源
- 读取文件：`AGENTS.md`、`project-defaults.yaml`、source type registry、models、presets、公开机构与媒体的官方订阅说明
- 修改文件：`WORKLOG.md`
- 执行验证：只读核对正式 catalog 支持 8 类来源，并通过官方页面确认主要候选源仍提供 RSS/Atom 或稳定发布入口
- 结果：形成按第一手发布、专业媒体、研究与社区信号分层的推荐清单及首批订阅组合
- 未解决问题：Reuters、AP、Bloomberg 缺少适合作为当前项目核心接入的稳定公开官方 RSS；具体源导入尚未执行
- 控制面变更：无

### 2026-07-13 14:25 Codex
- 任务：实现订阅级自动抓取，并将 X `@thsottiaux` 配置为每 30 分钟、本地每次最多 1 条
- 读取文件：source schedule 设计/执行计划、ServiceStore、JobQueue、Worker、catalog runner、Apify adapter、API/runtime、订阅 UI、bootstrap、控制面与相关测试
- 修改文件：新增 `SourceScheduleService` 与 schedule schema/API/UI/测试；更新 queue/Worker/runtime/bootstrap/Apify adapter、API/架构/计划/决策/defaults 和实施报告
- 执行验证：TDD 覆盖双连接竞争、手动/自动/全量刷新竞争、角色/订阅/catalog source 停用防护、Worker/finalizer 推进和 UI 保存；真实 X `source_test/source_fetch` 均成功，单源任务产出 1 条、单 snapshot、142 字中文概括、来源健康为 healthy；677 项 pytest、62 项 Node、Python/JS、Compose、diff check 和真实 Key 零泄露检查通过
- 结果：X 目标修正为 `@thsottiaux`，订阅级计划已启用 30 分钟，整份 Feed 保持 360 分钟；Actor 上游最小 `max_items=100`，本地严格只处理 1 条
- 未解决问题：需要观察 30 分钟自然周期、Apify 每日运行次数和真实计费；Gemini 额度不足时继续使用摘要回退
- 控制面变更：新增 D012 和 source schedule API/架构合同，更新阶段计划/defaults，并新增 `docs/dev/per-source-auto-fetch-v1-implementation-report.md`

### 2026-07-13 15:05 Codex
- 任务：收口订阅级自动抓取并修复 API 长连接误报 Worker stale
- 读取文件：ServiceStore、Service API/runtime、Docker 日志、请求事务与 heartbeat 回归测试、订阅级自动抓取实施报告
- 修改文件：`src/storage/service_store.py`、`src/api/server.py`、`Dockerfile`、API/Store 测试、架构/决策/实施报告与本记录
- 执行验证：隔离 WAL 跨容器探针、事务泄漏/请求连接/journal mode RED-GREEN；681 项 pytest、62 项 Node DOM、Python/JS、Compose、diff-check 和真实 Key 零泄露通过；Docker 慢网重试后 API/Worker 同镜像 healthy；DELETE journal 下第三个自然 X job running 期间 readiness 持续 200，最终连续三个自然 job 均 succeeded/1 item/1 snapshot；浏览器最新 Feed/中文概括/移除入口/密钥不回显通过
- 结果：API 请求改为 ContextVar 隔离的请求级短连接并拒绝未结束事务，light Compose 的 macOS bind mount 改用 DELETE journal；X 30 分钟/1 条和全量 Feed 6 小时配置保持有效，三个自然周期及全量刷新推进均已验证
- 未解决问题：继续观察 Apify 多周期实际计费；Gemini 额度不足时仍使用安全摘要回退
- 控制面变更：新增 D013 并补充 SQLite 请求连接架构边界，更新订阅级自动抓取实施报告

### 2026-07-13 18:45 Codex
- 任务：将 Service UI 全量重构为 React 三栏信息雷达，保留 Feed、阅读、订阅、设置、权限和任务闭环
- 读取文件：`AGENTS.md`、API/架构/阶段合同、Service API、原生 UI、Docker/Compose、现有 Python 与 Node 回归测试
- 修改文件：新增 `frontend/` React/Vite 工程；更新 `src/api/server.py`、Dockerfile/Compose、README、API/架构/计划/决策/defaults 和 React 实施报告
- 执行验证：684 项 pytest、49 项 Vitest、62 项 legacy Node UI 全通过；Playwright 5 通过/4 按视口条件跳过；TypeScript、ESLint、Vite build、Python/JS 语法、Compose、diff-check 通过；Docker API+Worker healthy，镜像无 Node 运行依赖、密钥或数据库；真实数据浏览器验证 4 个订阅和历史 Feed
- 结果：React 已成为 Service 默认 UI，实现三栏/平板/移动布局、用户级 Query 隔离、任务轮询、乐观阅读状态、8 类动态来源表单、来源健康和 write-only 密钥管理；legacy UI 保留一个发布周期可回退
- 未解决问题：仓库仍为 init-pro schema-2，本机 v0.3 校验器仅接受 schema-3 `project-controls.json`；应单独迁移控制面，不影响 React/Docker 运行
- 控制面变更：更新 API/Architecture/PLAN/defaults/decision/README，记录 React 默认、legacy 回退、SPA 托管和 Docker 静态构建边界，新增 `docs/dev/react-service-ui-v1-implementation-report.md`

```md
### YYYY-MM-DD HH:MM AgentName
- 任务：一句话说明当前任务
- 读取文件：列出关键控制文件、代码文件、测试文件
- 修改文件：列出本次实际修改的文件
- 执行验证：列出关键命令、测试、接口验证
- 结果：说明完成了什么
- 未解决问题：如无则写“无”
- 控制面变更：如无则写“无”；如有，写明更新了哪些控制文件以及原因
```

### 2026-07-14 10:57 Codex
- 任务：按已确认的「Material You 情报舱」方案重构 React 桌面 Shell 与 `/feed`、`/later`、`/history`
- 读取文件：`UI_CONTRACT.md`、React App Shell/Feed、API 类型与 Query key、Vitest/Playwright、现有控制面与视觉稿
- 修改文件：新增 `frontend/src/ui/**` 受控 MUI 主题/组件层、Feed filters 与 UI 契约检查；重构 AppShell/Feed workspace；更新依赖、单测、Axe/四视口截图基线、设计规格及控制文件
- 执行验证：`check:ui`、ESLint、TypeScript、58 项 Vitest、Vite build、Playwright 11 通过/7 视口条件跳过、Axe serious/critical 为零、3 项 legacy Service UI pytest、`git diff --check` 全通过；四张截图人工检查通过
- 结果：MUI v9 + Emotion + 本地 Noto Sans SC、64 px AppBar、按用户持久化的 72/240 px Drawer、1024 覆盖侧栏、Material You Feed 决策简报、单次摘要、权限降级、筛选 Popover、错误重试与无障碍门禁完成；API、数据库、权限、Query key 和 legacy 回滚保持不变
- 未解决问题：订阅/设置/登录 body 与移动端专项重设计未进入本期，须等 Feed 截图人工确认后另行实施；Vite 仍提示单主 chunk 超过 500 kB；本机 init-pro 仅支持 schema-3 manifest，无法执行仓库 schema-2 strict 命令
- 控制面变更：新增 `UI_CONTRACT.md` 与 Material UI 设计规格，更新 AGENTS/Architecture/Context Rules/PLAN/D015/defaults，登记视觉真源、前端读取边界、功能状态与验证命令

### 2026-07-14 11:02 Codex
- 任务：启动本地 Material UI Service UI 供用户查看
- 读取文件：本地启动脚本、Service API 入口与环境端口配置
- 修改文件：`WORKLOG.md`
- 执行验证：Docker daemon 不可用后改用 `.venv` 启动 FastAPI；`/api/health/live` 与 UI 均返回 200，并在 Chrome 打开 `http://127.0.0.1:8080/feed`
- 结果：新版 Material UI 已使用本地真实 Feed 数据运行，服务进程保持启动
- 未解决问题：Docker Desktop 当前未启动；本次使用本地 Python 服务，不影响界面查看
- 控制面变更：无

### 2026-07-14 12:11 Codex
- 任务：实现跨来源 Content Presentation v1 通用模板，以确定性代码统一展示字段、减少 AI token，并删除“为什么值得关注”
- 读取文件：source adapters、ContentItem/Service config、orchestrator/analyzer/cache、Feed serializer/finalizer/Worker、React/legacy reader、API/架构/UI 合同及来源测试
- 修改文件：新增 `content_presentation.py`、`user_analysis_cache.py`、`source_contract_smoke.py` 及对应测试/实施报告；更新来源身份传播、AI prompt/cache、Feed run diagnostics、Service schema、React/legacy UI、视觉 fixture 与控制文件
- 执行验证：696 项 pytest、58 项 Vitest、62 项 legacy Node、React UI contract/ESLint/TypeScript/build、Playwright 连续两次 11 通过/7 视口跳过、Axe serious/critical 为零、Python/JS 语法、两份 Compose、JSON 和 diff-check 通过；隔离真实 smoke 未调用 AI，验证 RSS/GitHub/HN/Reddit fallback，记录 Telegram 网络与 Apify 额度/Actor 权限降级
- 结果：8 类 catalog/11 种内容形态统一为 Presentation v1；代码输出来源/作者/时间/双链接/内容类型/600 字来源摘录/taxonomy/互动量，AI 只补 200 字概括等语义字段；React 不显示或搜索 reason，新增用户隔离缓存和 analysis_usage 成本诊断
- 未解决问题：Apify Primary 月额度硬限制，Secondary 需批准目标 Actor full access；Telegram 当前网络失败；Gemini 额度恢复后需复验真实 AI call 与同用户 cache hit
- 控制面变更：更新 API/Architecture/UI/PLAN/defaults/Decision Log，新增 D016 与 `docs/dev/content-presentation-v1-implementation-report.md`

### 2026-07-14 13:54 Codex
- 任务：核查 Material UI 预览中通知、已读标记、筛选控件、订阅权限、任务说明与侧栏账户区的九项反馈
- 读取文件：AppShell、Feed activity/job model、Feed workspace/page/cache/filters、Subscriptions page/model、API catalog 权限实现与权限矩阵测试
- 修改文件：`WORKLOG.md`
- 执行验证：只读追踪 UI 状态与 API 权限路径；确认 Snackbar 无关闭策略、列表选择不触发已读 mutation、native Select 标签重叠、共享来源仅管理员可改且普通成员可订阅、最近任务直接暴露内部枚举
- 结果：已将问题拆为三个确定性缺陷和一组订阅/任务/侧栏信息架构重设计，进入逐项设计确认；尚未修改产品代码
- 未解决问题：需确认“打开详情是否自动标记已读”，随后确认来源分组方式与私有来源权限表达
- 控制面变更：无

### 2026-07-14 13:59 Codex
- 任务：确认 Feed 条目打开后的已读行为
- 读取文件：上一轮问题核查结论与当前重设计计划
- 修改文件：`WORKLOG.md`
- 执行验证：用户确认采用“打开详情即自动标记已读”规则
- 结果：已读圆点将在打开详情后立即消失；Viewer 账户保持只读、不写入状态
- 未解决问题：继续确认订阅页来源分组与权限表达
- 控制面变更：无

### 2026-07-14 14:11 Codex
- 任务：接入新的 Gemini write-only Key，以最小真实调用验证当前 Flash 模型与同用户缓存，并低成本复测 Telegram
- 读取文件：AI client/analyzer/cache、SecretStore、Telegram adapter、本地 config、bootstrap/default UI、Presentation 实施报告与控制面
- 修改文件：本地 `data/config.json` 选择 `GOOGLE_API_KEY_2`/`gemini-3.5-flash`；更新 bootstrap、React/legacy 默认模型、聚焦测试、配置文档、API/PLAN/defaults/Decision/实施报告与本记录
- 执行验证：官方模型目录与新 Key 模型列表交叉确认；1 条 Gemini 真实分析成功，第二次同用户 cache hit 且零网络调用；8 项聚焦 pytest、8 项 legacy Node、5 项 Vitest、Python/JS 语法、JSON、diff-check 和密钥泄露扫描通过；Apify 未调用
- 结果：Gemini 概括恢复可用，64 字真实概括符合 200 字上限；Key 文件保持 `0600` 且跟踪/未忽略文件零真实 Key 命中；X 仍为每 30 分钟、本地 `fetch_limit=1`
- 未解决问题：本机直连 `t.me:443` 仍为 TLS `ConnectError`；前端完整 typecheck/build 被工作区内未实现的订阅模型测试导出 `groupSourcesByScope/presentJob/sourceTypeLabel` 阻塞，与本次 Gemini 变更无关
- 控制面变更：默认 Gemini 模型从对新用户不可用的 2.5 Flash 迁移到官方当前稳定 3.5 Flash，并同步 API 合同、阶段状态、defaults 与 D011 验证记录

### 2026-07-14 14:32 Codex
- 任务：纠正 X Apify 将单条订阅放大为上游 100 条的错误，切换备用 Key 并保持 30 分钟计划
- 读取文件：Apify Social/legacy Twitter adapter、models、bootstrap、Service 运行配置与数据库订阅/计划、相关测试及控制面
- 修改文件：`src/scrapers/apify_social.py`、`src/models.py`、`src/ui/server.py`、`scripts/bootstrap_local_sources.py`、配置/示例、Apify 测试、PLAN/DECISION/defaults 与实施报告
- 执行验证：TDD 确认旧代码向上游提交 100 且 bootstrap 绑定 Primary；修复后受影响 pytest 全通过，Python/JS 语法、3 份 JSON/Pydantic、diff-check 与跟踪文件密钥泄露检查通过；真实备用 Key 直连新 Actor 成功、请求 `maxItems=1`、本次返回 0 条
- 结果：X `@thsottiaux` 现绑定 Apify Secondary，Service 默认 Actor 为 `apidojo/twitter-scraper-lite`，上游和本地均严格限制 1 条，订阅级计划启用且周期 30 分钟；legacy Twitter 兼容路径不受影响
- 未解决问题：Worker 为避免验证期间继续计费保持停止，数据库尚有 2 个旧 queued job；恢复前应先处理旧队列，再观察新 Actor 的一个自然周期。init-pro schema-2 strict 命令被本机仅支持 manifest 的新校验器拒绝（exit 2）
- 控制面变更：更新 PLAN、D011/D012、project defaults 和实施报告，将旧“上游最小 100 条”从当前 Service 合同中移除

### 2026-07-14 14:30 Codex
- 任务：按确认计划修复 Material UI Feed 交互、更新任务通知，并重构订阅页、来源权限表达、运行记录和 Drawer 账户区
- 读取文件：`UI_CONTRACT.md`、AppShell/Feed activity/workspace/filters、订阅页面与权限模型、Vitest/Playwright、API 权限矩阵和现有控制面
- 修改文件：Feed 点击已读/回滚提示/受控筛选，Worker 更新预检和通知去重，MUI 订阅三标签页/范围分组/响应式 Dialog/中文任务映射，Drawer 顶部切换与账户卡片，UI 导出层、68 项 Vitest 与四视口 Playwright 回归；同步 UI/Architecture/PLAN/defaults/D017
- 执行验证：UI contract、ESLint、TypeScript、68 项 Vitest、Vite build、7 项后端权限矩阵、Playwright 13 通过/11 按视口跳过、Axe serious/critical 为零、四张截图人工检查、JSON、`git diff --check`、8080 liveness/Feed/订阅入口均通过
- 结果：未读条目仅在明确点击后乐观变为已读，失败会回滚；Worker 非 ready 不再入队；通知可关闭且自动消失；订阅按公共/团队/私有分组并使用既有角色权限；运行记录不再直接暴露内部枚举；预览服务已重启并加载最新生产资源
- 未解决问题：Vite 仍提示主 chunk 超过 500 kB；仓库沿用 init-pro schema-2，而本机校验器仅接受 schema-3，故新旧 strict 参数与 manifest 校验仍不兼容
- 控制面变更：更新 `UI_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`PLAN.md`、`project-defaults.yaml` 并新增 D017，登记订阅页 MUI 迁移、更新前 Worker 预检、通知生命周期和统一账户卡片

### 2026-07-14 15:49 Codex
- 任务：核查多成员订阅同一公共源时是否共享数据库抓取缓存
- 读取文件：`AGENTS.md`、`PLAN.md`、`API_CONTRACT.md`、Service schema、Worker、用户配置构建、单源 runner、任务队列与订阅级调度代码
- 修改文件：`WORKLOG.md`
- 执行验证：只读追踪 `user_feed_refresh` 与 `source_fetch` 两条执行路径，并核对任务去重键和 SQLite 表结构
- 结果：公共源配置共享，但抓取结果不共享；任务按用户/订阅创建并分别调用上游，Feed 与 AI 分析缓存也按用户隔离
- 未解决问题：若要降低重复上游调用，需要另行设计 workspace/source 级内容缓存与用户投影机制
- 控制面变更：无

### 2026-07-14 16:04 Codex
- 任务：审查公共源共享边界及相邻订阅、调度、缓存、配额与 Feed 留存逻辑
- 读取文件：`AGENTS.md`、`PLAN.md`、`API_CONTRACT.md`、Worker/任务队列/调度/配额、Catalog runner、Feed 生产与归档、AI 缓存与分析器、Service API、React 订阅流程及相关测试
- 修改文件：`WORKLOG.md`
- 执行验证：63 项聚焦 pytest 全通过；使用临时 SQLite 最小复现订阅失效、确定性异常重试、增量 URL 去重和 AI 缓存指纹；对现有 Service DB 做无内容的计数审计
- 结果：确认 6 类高/中风险逻辑问题：生命周期失效脱节、停用来源成为孤儿状态、配额可绕过、快照/历史持续膨胀、AI 缓存键与真实提示词不一致、增量与全量去重语义不一致；未修改业务代码
- 未解决问题：需决定是否进入修复及架构重构；跨用户共享 AI 推理缓存涉及既有隔离合同与隐私边界
- 控制面变更：无

### 2026-07-14 16:22 Codex
- 任务：执行订阅管理、主题库与阅读详情修复 v1
- 读取文件：UI/API/阶段/defaults 控制面，React 订阅/设置/Shell/Feed，Service config API、AI prompt/cache/analyzer/orchestrator 及相关测试
- 修改文件：频道/主题 taxonomy 与精确空数组保存语义、主题 hash 分析版本、无建议动作分析链路；React 频道分组/筛选/折叠、主题多选与 Chip 管理、单源立即获取、账户菜单、正文片段；同步 Vitest/Playwright/pytest、视觉基线和控制面
- 执行验证：703 项 pytest、77 项 Vitest、63 项 legacy Node 行为、Playwright 13 通过/11 按视口跳过；UI contract、ESLint、TypeScript、Vite build、Python/JS 语法、两份 Compose、JSON 与 `git diff --check` 全通过
- 结果：订阅和来源按有效频道组织并可搜索筛选，频道/主题编辑符合候选与自定义语义；主题删除不改旧引用或 snapshot；单源抓取有 Worker 预检；阅读详情直接展示 600 字安全正文片段；新 AI/cache/React 不再生成、保存、展示或搜索建议动作
- 未解决问题：Docker Desktop 未运行，无法重建容器；本机 API 使用新生产资源重启，Worker 保持停止且数据库仍有 2 个旧 queued job，避免本次 UI 验收意外触发外部抓取；Vite 主 chunk 仍有大于 500 kB 的既有警告
- 控制面变更：更新 `UI_CONTRACT.md`、`API_CONTRACT.md`、`PLAN.md`、`project-defaults.yaml`，新增 D018

### 2026-07-14 16:10 Codex
- 任务：为公共源共享及相邻六类逻辑问题生成执行计划
- 读取文件：`superpowers:brainstorming`、`superpowers:writing-plans`、`ARCHITECTURE_CONTRACT.md`、`API_CONTRACT.md`、`PLAN.md`、`project-defaults.yaml`、既有设计/计划目录与近期提交状态
- 修改文件：`WORKLOG.md`
- 执行验证：核对当前架构边界、合同约束、现有计划格式与工作区状态，确认范围横跨任务生命周期/配额、公共内容池、Feed/AI 一致性三个可独立验收子系统
- 结果：完成计划前置范围分析；按设计门禁暂停在实施范围确认，尚未修改业务代码或生成未经确认的计划文件
- 未解决问题：等待确认本次计划是覆盖全部三阶段，还是只聚焦 P0 正确性与成本控制
- 控制面变更：无

### 2026-07-14 16:11 Codex
- 任务：确认三阶段执行计划范围并提出总体架构方案
- 读取文件：`superpowers:brainstorming` 及上一轮完成的仓库架构/合同审查上下文
- 修改文件：`WORKLOG.md`
- 执行验证：将六类问题映射为 P0 生命周期与配额、P1 公共内容获取、P2 Feed/AI 一致性三个独立验收边界，并比较演进式、整体替换和补丁式三种方案
- 结果：用户选择覆盖全部三阶段；推荐采用保持现有 API/job 兼容的 additive 演进式架构，当前等待总体架构确认
- 未解决问题：数据模型、任务流、错误语义与验收矩阵将在总体架构确认后逐节设计
- 控制面变更：无

### 2026-07-14 18:33 Codex
- 任务：执行公共源共享获取与 Feed 正确性 P0–P2 计划
- 读取文件：生命周期/队列/Worker/调度/配额、Catalog runner、orchestrator、AI cache/prompt、Feed production/store/archive、Service API、React/legacy UI、迁移脚本及 API/Architecture/PLAN/defaults 控制面
- 修改文件：新增统一 job eligibility、共享 acquisition coordinator/content pool、canonical merger、maintenance 与 Feed storage v3 migration；加固 source/subscription/user 生命周期事务、逐次 fetch/AI attempt 资格复查、并发配额/计量、retry 分类/资格、Feed reconciliation/no-op/compact 双读、精确 AI prompt fingerprint、runtime 计数及相关 API/UI/测试/文档
- 执行验证：759 项 pytest 全通过；React 21 文件/77 项 Vitest、UI contract、ESLint、TypeScript、Vite build 全通过；legacy Node 63 项、Python/JS syntax、JSON、`git diff --check` 全通过；真实 SQLite 只读副本 v3 dry-run 为 49 个 snapshot/hash 待迁移，integrity `ok` 且无 foreign-key error；密钥扫描仅命中 3 个明确脱敏测试夹具
- 结果：公共/团队源已具备同 workspace freshness window 单次中性获取和逐用户投影，private/AI/state/Feed 继续隔离；停用与退订不会留下可运行任务或陈旧 provenance；配额、重试和真实调用计量原子化；P2 snapshot/retention/migration 均受显式门禁保护。两个 rollout flag 仍为 false，未修改/迁移真实库、未启动 Worker、未调用付费来源
- 未解决问题：目标库需停服务后显式 apply v3；共享获取需先用非付费源观察两个自然周期，付费源需另行授权且 `maxItems=1`；Vite 仍有既有 720.78 kB 主 chunk 警告；init-pro 仓库仍为 schema 2，而当前 validator 要求 schema-v3 `project-controls.json`，已修正文档中的失效命令但未越权迁移控制面
- 控制面变更：更新 `API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`DECISION_LOG.md` D019、`PLAN.md`、`project-defaults.yaml`、`.env.example` 与配置文档，明确共享/compact 默认关闭、v3 门禁、配额、留存和发布顺序

### 2026-07-14 19:22 Codex
- 任务：删除 `vps-tokyo` 旧版并部署当前工作区版本，明确不启动 Worker
- 读取文件：发布 Docker/Compose、前端依赖锁、阶段/defaults、RC1 报告与服务器现有部署/容器/数据库状态
- 修改文件：修复 `frontend/package-lock.json` 的 Node 22/npm 10 Linux optional peer 锁定；同步 `PLAN.md`、`project-defaults.yaml`、RC1 发布报告与本记录
- 执行验证：npm 10 全新 `ci`、77 项 Vitest、UI contract、ESLint、TypeScript、Vite build；VPS 镜像构建、18080 staging、8080 live/ready/root、TLS/Basic Auth、数据库 integrity/foreign keys、容器进程及 systemd/cron 自动拉起检查均通过
- 结果：发布 `api-20260714T110652Z-d0c8905-wt2e4cb2ea` 仅运行健康 API，ready 显示 `worker_status=missing`；旧容器/镜像/网络/源码与失败残留已删除，共享获取和 compact writer 保持关闭，校验后的旧版回滚备份保留
- 未解决问题：未使用凭据做公网应用登录/Feed 验收；Feed storage v3 仍只 dry-run 未 apply；Worker/scheduler 按用户要求继续禁用
- 控制面变更：更新当前 VPS 发布状态、API-only 运行边界和后续迁移/Worker 授权门槛

### 2026-07-14 19:35 Codex
- 任务：确认 `rb.jiefs.top` 公网与应用两层登录账号及密码来源
- 读取文件：VPS Nginx Basic Auth 配置、Service 用户表结构与部署环境变量键名
- 修改文件：`WORKLOG.md`
- 执行验证：只读取用户名与密码存储格式，未输出哈希、密钥或环境变量值
- 结果：公网 Basic Auth 用户为 `friend`，应用 owner 用户为 `admin`；两层密码均只保存不可逆哈希，无明文可恢复
- 未解决问题：如遗忘密码，需要分别重置 Basic Auth 与应用账户密码
- 控制面变更：无

### 2026-07-14 19:42 Codex
- 任务：将公网 Basic Auth 与应用 owner 两层密码重置为用户指定值
- 读取文件：Service 用户更新接口、密码哈希实现与 VPS Nginx htpasswd 配置
- 修改文件：VPS `/etc/nginx/.htpasswd_inteliscope` 与 Service 用户 `admin` 密码哈希；本地仅更新 `WORKLOG.md`
- 执行验证：重置前完成 htpasswd/SQLite `0600` 备份；Nginx config test、公网 Basic Auth + 应用登录、owner 身份、注销、session 清零、API health/restart 和 Worker 缺席均通过
- 结果：公网用户 `friend` 与应用用户 `admin` 已使用新密码，测试会话已注销，服务无需重启
- 未解决问题：用户指定密码强度很低且两层共用，建议尽快更换为两个不同的强密码
- 控制面变更：无

### 2026-07-14 19:45 Codex
- 任务：解释公网访问出现两次登录验证的原因
- 读取文件：沿用已核验的 Nginx Basic Auth 与 Service 应用登录配置
- 修改文件：`WORKLOG.md`
- 执行验证：核对两层认证边界与对应账号，不修改服务器配置
- 结果：确认第一层为 Nginx Basic Auth，第二层为应用用户/角色登录，并非 TOTP 二次验证
- 未解决问题：如需单层登录，应明确选择移除公网 Basic Auth 或应用登录；建议保留应用登录
- 控制面变更：无

### 2026-07-14 19:50 Codex
- 任务：移除 `rb.jiefs.top` 公网 Nginx Basic Auth，仅保留应用登录
- 读取文件：VPS 生效的 `/etc/nginx/sites-enabled/cfl.conf`、htpasswd 与公网反代状态
- 修改文件：删除 VPS Nginx 两条 Basic Auth 指令及活动 htpasswd；同步阶段/defaults、RC1 报告与本记录
- 执行验证：修改前 `0600` 备份；`nginx -t`、热重载、公网 root 200 且无 Basic challenge、应用保护 API 401、API health 与 Worker 缺席均通过
- 结果：浏览器不再弹出 `friend` 登录框，公网直接进入应用登录页；回滚配置保留
- 未解决问题：应用登录现在是唯一公网认证边界，必须使用强密码
- 控制面变更：更新公网认证边界与验收状态

### 2026-07-14 19:52 Codex
- 任务：将应用 owner 弱密码改为随机强密码
- 读取文件：Service 用户更新/密码哈希实现与 VPS 当前应用认证状态
- 修改文件：VPS Service 用户 `admin` 密码哈希；本地仅更新阶段记录与 `WORKLOG.md`
- 执行验证：重置前完成 SQLite `0600` 备份；公网 `admin`/owner 登录、Secure Cookie、注销、session 清零、Basic Auth 缺席、API health/restart 和 Worker 缺席均通过
- 结果：应用现使用 32 位十六进制、128-bit 随机密码；密码未写入仓库或工作日志
- 未解决问题：请妥善保存本次回复中的新密码
- 控制面变更：无

### 2026-07-14 20:28 Codex
- 任务：评估 700+ 测试对 Codex token 的影响并设计低 token 测试策略
- 读取文件：pytest/Vitest 配置、测试目录、发布脚本、CI workflows、项目验证规则与近期提交
- 修改文件：`WORKLOG.md`
- 执行验证：pytest collect-only 确认 71 个 Python 测试文件、781 个用例，约 2 秒且输出约 3.2 KB；另有 22 个前端和 3 个 legacy Node 测试文件
- 结果：测试数量本身不直接消耗模型 token，主要成本来自全量日志、失败 traceback 和无差别重复回归；进入分层方案确认
- 未解决问题：需确认日常是否允许仅跑受影响测试，把全量回归移至发布/合并门禁
- 控制面变更：无

### 2026-07-14 20:40 Codex
- 任务：执行收藏、站内阅读与社交媒体完整性修复 v1
- 读取文件：Feed/store/state、媒体/网络策略、Worker/finalizer、RSS/Apify adapters、React Feed/Shell/API、v4 迁移与相关控制面/测试
- 修改文件：稳定用户内容索引与收藏/详情/媒体 API、受保护媒体与头像缓存、Xquik/Instagram 多图和 latest-per-source、React 收藏/显式已读/正文画廊/偏好、v4 迁移、测试和实施报告
- 执行验证：782 项 pytest、82 项 Vitest、63 项 legacy Node、Playwright 13 通过/11 条件跳过；UI contract、ESLint、TypeScript、Vite build、Python/JS 语法、Compose 和 diff 检查通过；v3/v4 只读预检为 51/24
- 结果：收藏和详情不再依赖最新 snapshot，选择文章不再自动已读；已抓正文、图片和统一头像可同源受控展示；上游媒体地址不进入用户响应；社交 profile 保留最近一条
- 未解决问题：Xquik FREE tier 单条 `$0.015` 高于授权 cap `$0.01`，正式 Actor 未切换；未 apply v3/v4、未启动 Docker/Worker、未执行 X/Instagram 正式抓取和浏览器实源验收
- 控制面变更：更新 API/Architecture/UI/阶段/defaults、D020 与实施报告

### 2026-07-15 08:12 Codex
- 任务：诊断 `vps-tokyo` 后台 Worker 未启动原因
- 读取文件：VPS 当前 release/Compose、容器状态、readiness、非敏感 rollout 环境项、migration/任务/heartbeat/调度状态及本地发布记录
- 修改文件：`WORKLOG.md`
- 执行验证：确认 Compose 定义包含 Worker，但 VPS 仅创建 `horizon-light-api`；ready 为 200 且 `worker_status=missing`，`HORIZON_REQUIRE_WORKER_FOR_READINESS=false`，heartbeat 为 0
- 结果：Worker 不是崩溃，而是 2026-07-14 按“API-only、不启动 Worker”的发布授权刻意未创建；当前有一条 6 小时 Feed 计划和一条已逾期的 30 分钟 X Apify 计划，直接启动会立即补跑
- 未解决问题：数据库仅有 v2 marker，v3/v4 未发布/迁移；启动前需决定是否先部署当前代码并迁移，以及是否允许逾期 X 付费任务执行
- 控制面变更：无

### 2026-07-15 08:52 Codex
- 任务：按用户授权启动 `vps-tokyo` 当前发布版本 Worker 并完成首轮测试
- 读取文件：VPS 当前 Compose、Worker 日志、heartbeat/job/schedule/snapshot 状态、数据库完整性与公网 readiness
- 修改文件：VPS 创建并启动 `horizon-light-worker`；本地更新 `WORKLOG.md`
- 执行验证：容器 `healthy`、restart 0、heartbeat idle、active job 0；公网 ready 返回 `worker_status=ready`；SQLite integrity `ok` 且 foreign-key check 无结果
- 结果：逾期全量刷新在约 18 秒内以 partial 完成并生成 5 条 snapshot；GitHub、两个 RSS 和 Instagram 获取完成，Instagram 保留最近一条；下一次 X 单源计划为 30 分钟后
- 未解决问题：X 使用的 Actor 尚未批准 full-access 权限而返回 403；线上 AI 仍指向旧接口且 Key 无效，逐篇分析返回 401；VPS 仍是旧发布版本且 v3/v4 未部署迁移
- 控制面变更：无

### 2026-07-15 09:46 Codex
- 任务：实现低 Token 分层测试门禁、CI 与 release 验证接入
- 读取文件：测试/前端配置、发布与 smoke 脚本、Compose、AGENTS/PLAN/defaults/Decision 控制面及相关测试
- 修改文件：新增 `test_gate`、确定性 impact map、选择器/日志/CI 测试、API-only test Compose、GitHub workflow 与操作文档；发布本地门禁改走 release wrapper，并加固 smoke 脱敏/私有报告/诊断
- 执行验证：聚焦回归、Python/Bash/JSON/YAML/Compose/diff 检查通过；最新 full 22/22 子命令通过，Playwright 与隔离 API-only Docker smoke 分别通过，`mapping_miss=false`，无残留测试容器/网络
- 结果：完整日志以 `0600` 落入忽略的 `.test-results`，成功/失败摘要受 2/8 KiB 上限约束；CI 并行 full backend/frontend、UI 条件 E2E、正式发布 API-only smoke，均不启动 Worker/scheduler 或真实来源
- 未解决问题：10 个不同 CI 提交的观察期当前为 0/10；达到门槛前默认完成门禁保持 full，尚未提交、推送或创建 PR
- 控制面变更：更新 AGENTS/PLAN/defaults 并新增 D021，登记门禁定义、发布边界与渐进启用条件

### 2026-07-15 09:12 Codex
- 任务：诊断 X Actor 授权后由 403 转为 400 的原因
- 读取文件：VPS Worker 日志、失败 job/heartbeat/schedule、当前 X source 与部署版 Apify adapter/client，以及 Apify 官方 Actor schema
- 修改文件：`WORKLOG.md`
- 执行验证：复现两次 `altimis/scweet` 启动阶段 400；核对实际输入为 profiles + `max_items=1`，官方 schema 要求 `max_items>=100`；Worker healthy/idle、active job 0
- 结果：权限授权已生效，当前错误是 Actor 最小抓取量与系统单条约束不兼容，并非 Token 或网络问题；失败未形成热循环
- 未解决问题：需选择切换到支持 `maxItems=1` 的 `xquik/x-tweet-scraper` 并使用当前 adapter/成本上限，或放弃单条约束接受 Scweet 最少 100 条；线上仍为旧发布版本
- 控制面变更：无

### 2026-07-15 09:20 Codex
- 任务：启动本地 React Web 预览供用户测试
- 读取文件：launchd 预览服务状态、8080 监听进程、API 日志与健康入口
- 修改文件：`WORKLOG.md`
- 执行验证：确认旧 API 进程仍监听但请求稳定超时；通过 launchd 重启后 `/api/health/live`、`/feed`、`/subscriptions` 均返回 200，服务进程保持 running
- 结果：本地 Web 已恢复在 `http://127.0.0.1:8080`，仅启动 API/Web，未启动本地抓取 Worker
- 未解决问题：旧进程运行约 17 小时后事件循环无响应；当前重启已恢复，若再次出现需补充长时间运行诊断
- 控制面变更：无

### 2026-07-15 09:30 Codex
- 任务：诊断并恢复本地 8080 Web 页面无法加载
- 读取文件：launchd 预览状态、8080 监听、API 异常日志、SQLite 连接配置、Docker light 运行状态与数据库 journal mode
- 修改文件：重建 `com.inteliscope.preview` 启动参数，显式设置 `HORIZON_SQLITE_JOURNAL_MODE=DELETE`；更新 `WORKLOG.md`
- 执行验证：复现静态页面 200 但 `/api/auth/status` 因 `database is locked` 返回 500 并拖住事件循环；确认 Docker API/Worker 使用 DELETE、旧预览默认尝试 WAL；修复后 health/auth/Feed/订阅均 200，20 个并发鉴权请求全部 200，生产 JS 资源 200，Docker API/Worker healthy
- 结果：本地预览与 Docker 共享数据库时统一使用 DELETE journal，页面恢复可加载，Docker Worker 与现有任务未停止
- 未解决问题：launchd 预览配置为本机临时提交项，若标签被删除后重新以默认命令启动，需继续显式传入 DELETE 或改用统一启动脚本
- 控制面变更：无

### 2026-07-15 09:38 Codex
- 任务：诊断 Feed 阅读区出现 `item not found` 的原因
- 读取文件：本地 API 请求日志、Feed 查询与错误渲染代码、SQLite Feed/内容索引及迁移状态、当前 Docker Worker 镜像内容
- 修改文件：`WORKLOG.md`
- 执行验证：目标 article 在 `user_feed_items` 中有 3 行，但 `user_content_items` 为 0 且整表为空；数据库只有 v2 migration marker；当前 API 对该条目和 Instagram 条目持续返回 404；7 月 13 日创建的 Worker 镜像缺少 `user_content_store.py`，仍生成 `action_suggestion`
- 结果：本地为新 React/API 与旧 Docker Worker 混跑；旧 Worker 只写 legacy Feed snapshot，新详情 API 只查新版稳定内容索引，因此列表可见而详情 404；前端又将详情 404 提升为整个列表区错误
- 未解决问题：尚未获授权重建 Worker、应用 v3/v4 迁移并重新抓取，也未修改前端对旧条目详情 404 的降级处理
- 控制面变更：无

### 2026-07-15 09:44 Codex
- 任务：继续追溯本地新旧版本混跑的形成根因
- 读取文件：launchd 预览进程、Docker 容器/镜像/挂载与端口状态、Compose、`up-latest.sh`、迁移 readiness、Worker heartbeat schema、Git 工作区时间线
- 修改文件：`WORKLOG.md`
- 执行验证：8080 为 09:29 直接从当前工作区启动的宿主 Python API；Docker API/Worker 仍来自 7 月 13 日 `revision=unknown` 镜像，且只挂载共享 `data/logs/.env`；新版 `user_content_store.py` 于 7 月 14 日生成且未进入旧镜像；当前 `/api/health/ready` 明确以 `migration_required` 返回 503；heartbeat 不含 build/schema capability 字段
- 结果：直接触发原因是为恢复 Web 绕过标准原子启动流程，单独启动新版宿主 API，同时保留 `restart: unless-stopped` 的旧 Worker；两者通过同一 `service.db` 通信。更深根因是本地运行时缺少 API/Worker 构建版本握手和数据库协议兼容栅栏，liveness/静态页面又可在 readiness 失败时继续提供，因而没有阻止或显著暴露混跑
- 未解决问题：需另行授权修复运行拓扑、迁移并重建统一版本，以及补充版本握手/readiness 门禁；本轮未修改运行状态
- 控制面变更：无

### 2026-07-15 09:54 Codex
- 任务：用当前工作区最新代码重建并运行本地 API-only 容器
- 读取文件：Docker light Compose/Dockerfile、API readiness、user content v4 迁移脚本与本地容器/端口状态
- 修改文件：停止旧宿主 API 与旧 Worker，重建并启动 `horizon-light-api`；应用本地 user content v4 迁移；更新 `WORKLOG.md`
- 执行验证：v4 dry-run 检出 26 条缺失内容；应用后回填 26 条、foreign-key error 0、integrity `ok`；新容器 healthy，`/api/health/live`、`/api/health/ready` 与根页面均返回 200，8080 仅绑定 `127.0.0.1`
- 结果：本地最新 API/Web 已运行在 `http://127.0.0.1:8080`；生成 `0600` SQLite 一致性备份 `data/backups/service-user-content-v4-20260715T015334886063Z.db`
- 未解决问题：按 API-only 边界未启动 Worker/scheduler，readiness 中 `worker_status=stale` 为预期；镜像构建元数据 revision/built_at 仍为 `unknown`
- 控制面变更：无

### 2026-07-15 09:59 Codex
- 任务：诊断指定 Feed 详情 URL 白屏根因
- 读取文件：浏览器控制台/DOM、API 日志、目标条目 SQLite 数据、v4 迁移、详情组装、React Feed 渲染与相关测试
- 修改文件：`WORKLOG.md`
- 执行验证：同一会话 `/feed` 正常挂载，指定 `?item=` 稳定清空 React root；控制台两次复现 `Cannot read properties of undefined (reading 'canonical_url')`；详情 API 为 200，实际 presentation 仅有 version/source/content/media，缺少 links/analysis/timing/engagement 等字段
- 结果：v4 将无 presentation 的旧快照条目原样回填，详情组装只补部分 v2 字段；前端把任意 presentation 当作完整契约并直接读取 `links.canonical_url`，异常又因根节点无 ErrorBoundary 演变为整页白屏
- 未解决问题：本轮仅诊断未修复；需要以后端生成完整 presentation 为主、前端嵌套容错与 ErrorBoundary 为辅，并补迁移旧条目端到端回归
- 控制面变更：无

### 2026-07-15 10:13 Codex
- 任务：判断当前项目不稳定是否由模型导致
- 读取文件：运行容器/健康状态、Worker/API 镜像与日志、任务/心跳/调度/来源健康/AI usage 元数据、AI 客户端与分析链路、测试门禁和当前工作区状态
- 修改文件：`WORKLOG.md`
- 执行验证：最新 full gate 22/22 通过；API healthy 但 Worker 已退出且 heartbeat stale，一条 source schedule 已逾期未入队；历史 Worker 日志复现 `database is locked`；当前来源健康均为 healthy，最近可见 AI 分析无 fallback；官方模型文档确认 `gemini-3.5-flash` 为 stable GA
- 结果：首要根因是运行拓扑/版本与迁移治理、SQLite 锁竞争及外部源波动，不是模型本身；模型的串行节流、非零温度与缺少应用级显式超时会放大耗时和内容波动
- 未解决问题：当前 API-only 环境关闭 Worker readiness 强制且构建 revision 为 unknown；工作区仍有大规模未提交集成改动，需在统一版本重建与运行验收后才能视为稳定候选
- 控制面变更：无

### 2026-07-15 10:13 Codex
- 任务：修复 v4 迁移旧 Feed 详情导致 React 白屏
- 读取文件：presentation API/UI 合同、v4 迁移与详情存储、FeedWorkspace、应用路由及相关后端/Vitest 测试
- 修改文件：完整 legacy presentation 兼容投影、详情 v2 组装、Feed 嵌套字段容错、应用 ErrorBoundary、三组回归测试与 `WORKLOG.md`
- 执行验证：三组回归均先 RED 后 GREEN；相关 pytest 9 项、Vitest 13 项、类型/ESLint/UI contract/语法/diff 通过；targeted 9/9、full 22/22；重建 API-only 容器后原 URL 正常显示标题与原文链接，React root=1 且刷新后控制台错误 0
- 结果：无 presentation 或半份 presentation 的旧条目详情现在返回完整 v2 契约；前端可安全降级，未知渲染异常会显示恢复页而非整页空白
- 未解决问题：Worker/scheduler 继续按 API-only 边界保持停止；本地镜像 revision/built_at 元数据仍为 unknown
- 控制面变更：无，修复现有 API/UI 合同实现偏差

### 2026-07-15 11:34 Codex
- 任务：实现 Feed 一次性通知、全站异步反馈、历史内容 v5 修复与 DeepSeek 全局分析控制面，并运行本地最新 API + Worker
- 读取文件：Feed/Job/订阅/设置 React 链路，稳定内容、snapshot、Worker、AI cache/client、Secret API、Compose、测试门禁及 PLAN/合同/defaults/Decision 控制面
- 修改文件：新增认证 ActionFeedback、`content_repair` 与 v5 repair CLI、DeepSeek 单次 smoke、内容哈希/unresolved 字段；修复详情全文/多图降级、旧 snapshot 媒体净化、测试与控制面文档
- 执行验证：v5 备份权限 `0600`、SQLite integrity `ok`/foreign keys 0；定向与 full 门禁均 22/22、`mapping_miss=false`；桌面/390px Playwright 10 passed、6 条跨项目条件 skipped；真实浏览器 console error 0
- 结果：26 条历史内容中 23 条免费来源恢复为 captured，目标 GitHub 正文 6,671 字符；3 条付费 X/Instagram 保持可审计 unresolved；本地 API/Worker 同镜像 healthy，自动 Feed/source schedule 和活动任务均为 0，scheduler 未启动
- 未解决问题：聊天中旧 DeepSeek Key 视为泄露且未保存/调用；AI 保持 disabled，等待用户在设置页写入轮换 Key 后执行一次 retry=0 smoke；Instagram 过期媒体无法恢复；VPS Tokyo 未修改
- 控制面变更：更新 AGENTS、PLAN、API/ARCHITECTURE/UI 合同、project defaults 与 D022，并新增实施报告

### 2026-07-15 14:10 Codex
- 任务：诊断 X 单源抓取 `400 Bad Request`
- 读取文件：指定 job/result、Worker 对应日志、X catalog 配置、Apify adapter/client 及 Apify 官方 Actor OpenAPI/定价/API 限额文档
- 修改文件：`WORKLOG.md`
- 执行验证：任务在创建 Actor run 阶段 2.3 秒失败且 AI 调用为 0；实际输入 `twitterHandles/maxItems/sort` 均符合官方 schema；请求 URL 带 `maxTotalChargeUsd=0.01`，而该 Actor profile/search query 最低固定收费为 `$0.016`
- 结果：运行费用上限低于一次最小事件收费，Apify 在创建运行前返回 400；`FeedRunFailed` 只是来源失败包装，与模型、X 内容和 Token 轮换无关
- 未解决问题：当前客户端对普通 400 直接 `raise_for_status()`，未把 Apify 的结构化错误体投影到任务诊断；本轮未提高费用上限、未重试、未产生新付费调用
- 控制面变更：无

### 2026-07-15 14:40 Codex
- 任务：筛选支持严格抓取单条 X 内容的替代 Apify Actor
- 读取文件：X Actor adapter 与回归测试、Xquik/Scrape Badger/Kaito 官方 Actor 页面、API、定价与公开问题
- 修改文件：`WORKLOG.md`
- 执行验证：`xquik/x-tweet-scraper` 明确支持 `twitterHandles + maxItems=1` 且无启动费/查询费；项目已有对应输入适配和单条回归测试；官方价格表显示 Free 为 `$0.015/条`、Starter 及以上为 `$0.00015/条`
- 结果：首选 Xquik；它能严格返回单条，但 Free 计划仍高于现有 `$0.01` 运行费用上限，付费计划价格则在上限内；本轮未切换配置、未提高费用上限、未发起付费调用
- 未解决问题：执行切换前需确认当前 Apify 订阅层级；Kaito 的公开问题显示可能忽略小于 50 的 `maxItems` 或填充模拟数据，不适合作为严格单条备选
- 控制面变更：无

### 2026-07-15 14:41 Codex
- 任务：定位 X Actor 单次运行费用上限的调整位置
- 读取文件：Apify social Actor registry、Apify client 查询参数映射及对应测试
- 修改文件：`WORKLOG.md`
- 执行验证：Xquik 与 Apidojo 的 `max_total_charge_usd` 均在 `src/scrapers/apify_social.py` registry 中写死为 `0.01`，客户端将其映射为 `maxTotalChargeUsd` 请求参数
- 结果：确认当前不能从设置页调整；Xquik 应修改第 43 行，当前 Apidojo 应修改第 48 行，并同步更新费用上限测试
- 未解决问题：本轮仅定位，未改费用上限、未切换 Actor、未发起付费调用
- 控制面变更：无

### 2026-07-15 15:34 Codex
- 任务：完成 DeepSeek 稳健激活前的数据状态收尾、严格单次 smoke 护栏与本地运行验收
- 读取文件：稳定内容存储、v5 repair/reconcile、SQLite schema、AI client/SecretStore、DeepSeek smoke、API/架构/计划/决策合同、本地 Compose 与测试门禁
- 修改文件：captured reason 规范化、nullable schema、`repair_user_content_v5.py reconcile`、DeepSeek `models.list()` 预检与 one-shot smoke、回归测试、Xquik `$0.01` 费用护栏及控制面文档
- 执行验证：相关回归 64 passed；focused integration 121 passed；full test gate 22/22 且 `mapping_miss=false`；桌面/390px Playwright 10 passed、6 条条件 skipped；两轮独立审查均无遗留 finding
- 结果：inspect 发现的 1 条 stale Instagram reason 已在 Worker/API 停止后通过 `0600` 备份和事务 reconcile 清理；最终镜像复验又识别并通过第二份 `0600` 备份规范化旧 NOT NULL schema 遗留的 23 个空字符串占位，最终 reason 为 23 条 SQL `NULL` 与 1 条 `media_cache_failed:2`。数据库仍为 24 captured/2 excerpt-only，integrity `ok`、foreign keys 0，snapshot/Job/media/usage 数量不变；DeepSeek smoke 预检失败保持 0 completion，预检成功后省略 `temperature`、关闭 SDK 与应用层重试并最多一次 completion
- 未解决问题：轮换后的 `DEEPSEEK_API_KEY` 尚未由用户通过设置页保存，因此没有执行任何真实 DeepSeek 请求，AI 继续 disabled；旧聊天 Key 永不保存/调用；VPS Tokyo 未修改且 Worker/scheduler 未启动
- 控制面变更：更新 `API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`PLAN.md` 与 D022，固化 reconcile 状态约束和严格 one-shot DeepSeek 激活边界

### 2026-07-15 16:13 Codex
- 任务：修复 Instagram 图片不显示并把 X Actor 单次费用上限提高到 `$0.02`
- 读取文件：Instagram 既有成功 Actor 数据集、媒体缓存/网络安全/Feed 投影链路、X Actor registry 与相关测试
- 修改文件：`src/services/network_policy.py`、`src/services/media_cache.py`、`src/scrapers/apify_social.py`、三组回归测试与 `WORKLOG.md`
- 执行验证：RED 复现 Instagram CDN 被 Fake-IP 网络策略拒绝及两类 X Actor 仍传 `$0.01`；GREEN 后相关 5 个测试文件全通过，语法与 diff 检查通过；既有 Instagram 数据集图片经新策略真实下载为 JPEG 63,407 bytes；重建后 API/Worker healthy、ready 且活跃任务为 0
- 结果：仅 Instagram 官方 CDN 后缀可使用 `198.18.0.0/15` 合成 DNS 地址，其他私网/任意主机仍拒绝；Xquik 与 Apidojo 上限均为 `$0.02`；本地最新镜像已运行，未创建新 Apify run
- 未解决问题：当前旧 Instagram 内容没有本地媒体资产，需下一次 Instagram 获取后自动缓存；本轮未获逐条付费社交修复授权，因此未重抓或改写旧内容
- 控制面变更：无

### 2026-07-15 16:16 Codex
- 任务：确认本地容器版本并持久化“每次代码迭代保持本地容器最新”的项目偏好
- 读取文件：当前镜像/容器身份、关键运行文件哈希、API readiness 与个人工作流记忆规则
- 修改文件：个人 `workflow-rules.md`、个人 `memory-registry.json` 与 `WORKLOG.md`
- 执行验证：API/Worker 与当前 tag 使用同一 image id；三项关键运行文件的宿主机/容器 SHA-256 完全一致；API/Worker healthy、ready；个人技能校验通过 19 条记忆规则
- 结果：确认本地容器为当前代码版本；今后 Inteliscope 代码迭代改动 Docker 构建上下文时，结束前默认重建 API/Worker 并验证健康，重建前先检查付费任务风险
- 未解决问题：无
- 控制面变更：项目控制面无变化；新增一条项目作用域的个人持久偏好

### 2026-07-15 16:34 Codex
- 任务：判断当前 InfoHub 是否兼容 B 站 UP 主更新与用户关注视频流
- 读取文件：RSS source registry/抓取器、内容模型、`PLAN.md` 边界，以及 RSSHub 当前 Bilibili 路由文档与实现
- 修改文件：`WORKLOG.md`
- 执行验证：确认通用 RSS/Atom 可投影标题、链接、正文、作者、时间和封面；RSSHub `/bilibili/user/video/:uid` 无强制配置，`/bilibili/followings/video/:uid` 需要对应 Cookie；实测 `rsshub.app` 示例路由返回 403 并明示不用于生产订阅
- 结果：手工指定 UP 主可通过自建 RSSHub 作为现有 RSS 源直接兼容；B 站账号整体关注流属于需 Cookie 的外部代理集成，不是当前原生支持边界
- 未解决问题：未部署 RSSHub、未使用 B 站 Cookie、未执行带账号的真实抓取
- 控制面变更：无

### 2026-07-15 16:45 Codex
- 任务：为当前 admin 用户订阅 B 站 UP 主“超Carry的柴西”并开启更新监测
- 读取文件：B 站公开搜索结果、RSSHub 公共实例列表、本地订阅 UI/API 状态与 Service SQLite 记录
- 修改文件：Service DB 新增私有 RSS 来源/订阅/单源调度；`WORKLOG.md`
- 执行验证：确认官方 UID `383578614`；RSSHub 官方列表中 `rss.spriple.org` 实例对目标路由返回 200 XML 且频道标题/作者匹配；两次单源任务均 `succeeded`，每次返回 3-item Feed 结果且无 AI 调用；来源 health `healthy`、订阅/调度均 enabled、周期 360 分钟
- 结果：新增私有 RSS 来源“超Carry的柴西”，归入“朋友动态”，已订阅并开启每 6 小时单源更新；当前增量窗口内无新 B 站投稿，后续新视频将按调度抓取
- 未解决问题：使用第三方公共 RSSHub 实例，可用性依赖实例运维与 B 站反爬；实例先返回 200 并支撑两次成功任务，最终独立复验又返回 503，故只能视为已配置但上游可能间歇失败；最终 Feed 页浏览器核对遇到并发 API 容器重启窗口，根因为容器在 16:43:03–16:43:48 间被 SIGTERM 后重启，服务已恢复 healthy
- 控制面变更：无

### 2026-07-15 16:28 Codex
- 任务：诊断 `thsottiaux` 立即获取后进入运行记录时导航多次无法点击
- 读取文件：API/Worker 对应时段日志、`AppShell.tsx`、`ActionFeedback.tsx`、`SubscriptionsPage.tsx`，以及当前页面 DOM/控制台
- 修改文件：`WORKLOG.md`
- 执行验证：对应 `source_fetch` 运行 63.182 秒后因 Actor 返回占位记录而失败；期间 jobs/source-health API 均为 200，浏览器控制台错误为 0；在 1024px 下分别验证折叠和展开侧栏，从运行记录切换到信息流均成功
- 结果：不是 API 或 React 崩溃。任务失败会触发底部居中且持续 8 秒的 Snackbar；窗口宽度不超过 767px 时，导航栏同样固定在底部且层级低于 Snackbar，提示层会覆盖并截获导航点击，自动消失后恢复，符合“连续点好几次不行”的表现
- 未解决问题：Chrome 连接器不可用，未能读取用户当时实际 Chrome 页面的 DOM；若问题发生在大于 767px 的真正桌面左侧栏，当前版本未复现，需要以当时窗口宽度或录屏继续定位
- 控制面变更：无

### 2026-07-15 16:41 Codex
- 任务：诊断 `@kimetsu_off` 抓取显示 3 条新内容但 Feed 看不到数据
- 读取文件：指定 job、Feed snapshot/items、来源健康、Worker 时段日志、Apify run/input/dataset、React 任务展示与 Feed 筛选代码
- 修改文件：`WORKLOG.md`
- 执行验证：Apify run `SUCCEEDED` 但 dataset 为 0 条，来源健康 `last_fetched_count=0`；job 的 `item_count=3` 来自复用的上一份三条旧内容快照，且 `snapshot_created=false`；三条旧内容评分均为 0，默认高价值视图会全部过滤
- 结果：目标来源实际未抓到内容；运行记录误把最终 Feed 总数显示成“新内容”，造成成功且有 3 条的假象，并非用户遗漏数据
- 未解决问题：本轮仅诊断，尚未修正 job 结果字段/运行记录文案，也未用 `Top` 模式再次发起可能收费的 Apify 抓取
- 控制面变更：无

### 2026-07-15 16:44 Codex
- 任务：修复窄屏下来源失败提示遮挡底部导航、导致运行记录页面无法切换的问题
- 读取文件：React Shell/全局动作反馈、对应 Vitest、UI 契约与本地容器构建流程
- 修改文件：`frontend/src/app/ActionFeedback.tsx`、`frontend/src/app/ActionFeedback.test.tsx`、构建后的 React 静态资源与 `WORKLOG.md`
- 执行验证：TDD RED 证实 390px 下 Snackbar 原为 `bottom: 8px`，GREEN 后为 `76px`；相关 Vitest 3/3、完整 test gate 22/22、前端 build/UI contract 通过；390px 浏览器中用 API 预检失败触发提示时仍成功从订阅页切至信息流，未创建抓取任务
- 结果：不超过 767px 时全局终态提示固定抬高到 68px 导航上方并保留 8px 间隔，桌面行为不变；本地 API/Worker 已用最新代码无缓存重建，二者 healthy/ready、同一镜像，容器静态资源与宿主机 SHA-256 一致
- 未解决问题：无；Lint 为 0 error，保留该文件既有的 1 条 Fast Refresh warning
- 控制面变更：无

### 2026-07-15 16:55 Codex
- 任务：诊断 B 站 UP 主“超Carry的柴西”抓取显示完成但 Feed 无数据
- 读取文件：RSS 时间窗口过滤、单源 job/Feed snapshot 合并、React 运行记录字段映射、相关 SQLite 记录与 Worker 时段日志
- 修改文件：`WORKLOG.md`
- 执行验证：目标 RSS 当前可返回正确频道，最新投稿时间为 2026-07-09；当前抓取窗口为 24 小时，Worker 明确记录 `Found 0 items`；来源健康表 `last_fetched_count=0`，三次 job 均复用 16:16 生成的 3-item 旧 Feed snapshot，`snapshot_created=false`
- 结果：“已完成”仅表示任务成功跑完，目标源本次实际新增为 0；运行记录把 job 返回的最终 Feed 总数 3 误标为“3 条新内容”，造成有数据但页面没显示的假象
- 未解决问题：本轮仅诊断，尚未修正运行记录文案/计数语义，也未增加首次订阅的历史回填窗口；第三方 RSSHub 仍可能间歇返回 503
- 控制面变更：无

### 2026-07-15 17:27 Codex
- 任务：设计 B 站等个人动态 RSS 的最新一条回填与运行记录语义修复
- 读取文件：RSS 抓取/配置、Source Type Registry、共享抓取指纹、Feed 最新条目保留/替换、source fetch runner 与 React 运行记录投影
- 修改文件：`docs/superpowers/specs/2026-07-15-personal-rss-latest-fallback-design.md`、`WORKLOG.md`
- 执行验证：设计文档无 TBD/TODO/歧义占位，`keep_latest_item`、`latest_per_source`、`fetched_count`、`item_count` 和 `snapshot_created` 语义一致，`git diff --check` 通过；文档已以提交 `08fcf02` 单独固化
- 结果：用户确认只对显式开启的个人动态 RSS 生效；窗口内多条全部返回，窗口内为 0 时只回填整个 RSS 的最新一条，普通 RSS 默认不变
- 未解决问题：等待用户审阅书面设计；尚未进入实施计划、代码修改、容器重建或 B 站单源重抓
- 控制面变更：无

### 2026-07-15 17:50 Codex
- 任务：实现 B 站等个人动态 RSS 的“窗口内全量；无更新时回填最新一条”，并修正运行记录把 Feed 总数误报为新内容的问题
- 读取文件：RSS 配置/抓取器、来源类型注册、Feed 保留策略、单源任务结果、React 订阅运行记录、相关 Python/Vitest 回归与容器部署脚本
- 修改文件：`src/models.py`、`src/services/source_type_registry.py`、`src/scrapers/rss.py`、`src/ui/site.py`、`src/services/catalog_source_runner.py`、`frontend/src/features/subscriptions/subscriptionModel.ts`、对应 Python/Vitest 测试、构建后的 `src/ui/service_static` 与 `WORKLOG.md`
- 执行验证：TDD 覆盖配置、回填、`latest_per_source`、`fetched_count` 和运行记录文案；focused Python 71 passed、Vitest 17 passed；最终 full test gate 22/22、`mapping_miss=false`；API/Worker 均 healthy，readiness 为 database/worker ready，目标来源 `keep_latest_item=1`
- 结果：普通 RSS 默认行为不变；显式开启的个人动态 RSS 会返回窗口内全部条目，窗口为空时返回整个 Feed 的最新一条并按来源保留；运行记录改为展示本次抓取数与信息流是否变化，不再把最终 Feed 总数标成“新内容”；最新镜像已部署，目标订阅和 6 小时调度保持启用
- 未解决问题：真实抓取已按 3 次重试上限执行，但 `rss.spriple.org` 的 B 站路由均返回 503；官方公共实例抽样也普遍 403/502/503 或超时，因此本轮无法完成线上回填与去重验收，任务最终正确标记为失败而非完成
- 控制面变更：新增设计与实施计划文档；未修改既有 API/架构契约

### 2026-07-16 09:19 Codex
- 任务：诊断 X 订阅报错 `Apify actor returned placeholder records instead of social posts`，并复核用户提供的 Free Plan 额度证据
- 读取文件：当前 X source/job、Worker 日志、Apify social adapter/测试、该次 Actor 数据集/run/input/log、账号非敏感 plan 字段与 Apify 官方 Actor 定价/Demo Mode 说明
- 修改文件：`WORKLOG.md`
- 执行验证：账号确为 Free Plan 且每月有 `$5` usage credit；09:14 的 `apidojo/twitter-scraper-lite` run 创建、完成与 dataset GET 均成功，但 Actor 日志明确拒绝 Free Plan API，数据集 10 行均只有 `demo=true`；该 run 的 `list-query=0`、demo dataset item=10、实际 usage `$0.004`。来源输入为 `@thsottiaux`、profile、`maxItems=2`
- 结果：用户有额度的判断正确；根因不是余额，而是当前 Actor 独立禁止 Free Plan 通过 API 获取真实数据，定价表只说明事件单价，不授予 API 权限。本地 `_is_content_candidate` 正确拒绝 demo 行。替代 Actor `xquik/x-tweet-scraper` 当前 Free tier 为 `$0.015/条`，官方最新 schema 与现有 adapter 均支持 `twitterHandles + maxItems`，代码已有 `$0.02` 上限，切换不需要新增适配器即可做 1 条 canary
- 未解决问题：切换 Xquik、把 `maxItems` 固定为 1 并发起最多 `$0.02` 的真实 canary 仍需用户显式成本授权；本轮未改配置、未重试、未新增调用
- 控制面变更：无

### 2026-07-16 09:31 Codex
- 任务：按用户授权执行 1 条、最多 `$0.02` 的 Xquik 真实 canary
- 读取文件：Xquik 官方 input schema/账号级定价、Apify token ref、现有 Xquik adapter/parser 与当前 X 订阅配置
- 修改文件：`WORKLOG.md`
- 执行验证：仅一次 POST 启动 `xquik/x-tweet-scraper` run `zPZQCcl0OaiEKDIWv`，输入 `twitterHandles=[thsottiaux]`、`maxItems=1`、`maxTotalChargeUsd=0.02`；run `SUCCEEDED`，dataset 1 行、content candidate 1、现有 parser 解析 1，实际 usage `$0.015`
- 结果：成功取得真实推文 `twitter:tweet:2077271889626706300`，作者 Tibo、正文 139 字符、发布时间 2026-07-15T05:59:46Z；无 demo/diagnostic 占位。canary 为独立只读验收，没有创建本地 job、写 Feed 或调用 AI
- 未解决问题：持久配置仍是 `apidojo/twitter-scraper-lite` 且来源 `fetch_limit=2`；需用户确认后才切换为 Xquik、改为 1 并通过正常 Worker 链路再获取
- 控制面变更：无

### 2026-07-16 09:33 Codex
- 任务：确认本地 Docker 是否为最新且能否通过正常订阅链路获取 X
- 读取文件：宿主/容器 `src+scripts` 哈希清单、API/Worker 镜像与健康、容器内 Actor registry、当前运行配置与 X source
- 修改文件：`WORKLOG.md`
- 执行验证：API/Worker 同为镜像 `inteliscope-service:local-8fec1a6fa48f-dirty`，均 healthy/readiness ready；宿主与容器运行文件哈希完全一致；容器含 Xquik adapter 和 `$0.02` 上限
- 结果：Docker 是当前工作区最新版本并具备 Xquik 获取能力，但持久配置仍选择 `apidojo/twitter-scraper-lite` 且 `fetch_limit=2`，因此当前 UI“立即获取”仍会走旧 Actor，不会复用成功 canary
- 未解决问题：需显式切换持久 Actor 为 Xquik 并把 `fetch_limit` 改为 1，之后再通过正常 Worker 链路验收
- 控制面变更：无

### 2026-07-16 09:37 Codex
- 任务：正式把本地 X 订阅切换到 Xquik
- 读取文件：当前 base config、X source config、Worker 每任务配置重载链路与运行容器投影
- 修改文件：`data/config.json` 的 X Actor 改为 `xquik/x-tweet-scraper`；数据库 source `src_74592780b0be4c2da44b944b0ce96a78` 的 `fetch_limit` 改为 1；`WORKLOG.md`
- 执行验证：JSON 校验通过；在正在运行的 Worker 容器内重新构建用户配置，确认 actor=Xquik、target=thsottiaux、profile、fetch_limit=1、enabled=true；API readiness 为 database/worker ready，active X job=0
- 结果：正式切换完成，无需重建或重启；后续 UI“立即获取”和 Worker 调度均使用 Xquik，单次费用上限继续由 adapter 固定为 `$0.02`
- 未解决问题：本轮未再次发起付费抓取；正常 Worker 链路的真实结果可在用户下一次主动“立即获取”时验收
- 控制面变更：仅本地运行配置与 source 数据，未修改项目默认合同

### 2026-07-16 09:59 Codex
- 任务：诊断不同订阅头像显示不一致，并盘点所有订阅类型的上游与统一响应字段
- 读取文件：来源类型注册、RSS/GitHub/Reddit/Hacker News/Telegram/Apify social 适配器、媒体缓存和网络安全策略、Feed API/React 类型；当前 source/content/media SQLite 记录；既有 Xquik canary dataset
- 修改文件：`WORKLOG.md`
- 执行验证：当前 7 个来源仅 Instagram `tsucha_ri` 存在 1 个 ready `source_avatar` 资产，两个 X 与三个 RSS、GitHub 均为 0；Xquik canary 实际返回 `author.profilePicture`，但用当前安全下载链路复验时 `pbs.twimg.com` 被本机合成 DNS 解析为 `198.18.0.83`，因不在允许后缀中抛出 `UnsafeNetworkTarget`；B 站 RSS 路由当前返回 503 且无 feed image；未发起任何付费 POST、AI 或新抓取 Job
- 结果：X 头像缺失不是 Actor 漏字段，而是头像下载缓存被合成 DNS 安全策略拒绝；Instagram CDN 在受限例外名单中且已成功本地缓存，所以显示真实头像；无本地头像资产时 React 按来源名首字降级。已确认 catalog 的 8 类订阅与统一 `FeedItem/presentation` 字段合同
- 未解决问题：本轮仅诊断，未修改网络策略或回填头像；GitHub/Facebook/Telegram/Reddit/Hacker News 适配器目前也未映射来源头像，RSS 仅在 feed 提供 `image/icon/logo` 时支持
- 控制面变更：无

### 2026-07-16 10:04 Codex
- 任务：启动 X CDN 安全缓存、头像版本更新与运行记录响应结构视图设计
- 读取文件：`AGENTS.md`、`PLAN.md`、API/UI 合同、媒体/网络策略测试、Job 结果模型与订阅运行记录 React 实现
- 修改文件：`WORKLOG.md`
- 执行验证：确认媒体缓存已有 Instagram 合成 DNS 限定测试和“缓存一次/身份变更失效”测试；运行记录当前只显示 job 基础技术字段，Job `result_json` 可承载有界结构摘要
- 结果：确定安全设计边界为受控 X CDN 后缀、按头像远端身份变化更新、结构摘要只含字段名与类型；需先确认 UI 展示上游结构还是同时展示统一结构
- 未解决问题：等待用户确认响应结构视图范围后才能完成设计规格并进入 TDD 实现
- 控制面变更：无

### 2026-07-16 10:06 Codex
- 任务：确认运行记录响应结构视图范围
- 读取文件：上一轮媒体缓存与 Job/UI 合同核对结果
- 修改文件：`WORKLOG.md`
- 执行验证：用户选择同时展示“上游原始结构 + 系统标准化结构”，且两层均不得展示字段值
- 结果：设计范围已明确，可比较不同 Actor/来源的真实返回形状与系统最终消费合同
- 未解决问题：等待用户从持久化方案中确认推荐设计
- 控制面变更：无

### 2026-07-16 10:10 Codex
- 任务：确认响应结构方案 A 并完成实施前设计收敛
- 读取文件：结构化 Feed run/outcome、Apify client、Orchestrator source fetch、Job API/result 合同及媒体/Job 架构边界
- 修改文件：`WORKLOG.md`
- 执行验证：方案 A 可复用现有 terminal Job `result_json` 与 14 天保留策略，无需新增数据表；原始值可在适配器边界立即丢弃，仅传递有界结构摘要
- 结果：设计采用 Job 内双层结构摘要、仅允许 `pbs.twimg.com` 合成 DNS、头像远端身份变化即时替换并按 24 小时 checksum 复验
- 未解决问题：等待用户确认完整设计后写入并提交规格
- 控制面变更：无

### 2026-07-16 10:13 Codex
- 任务：固化 X CDN、头像版本与双层响应结构设计规格
- 读取文件：用户确认的完整设计、现有 API/架构/UI 权威边界
- 修改文件：`docs/superpowers/specs/2026-07-16-source-response-avatar-cache-design.md`、`WORKLOG.md`
- 执行验证：规格无 TBD/TODO/FIXME，占位、权限、上限、失败语义、测试范围和控制面更新要求一致；`git diff --check` 通过
- 结果：设计规格已单独提交为 `45c7a64`，未带入脏工作区其他改动
- 未解决问题：等待用户完成书面规格复核后进入实施计划与 TDD
- 控制面变更：新增设计规格；尚未修改运行时合同

### 2026-07-16 11:15 Codex
- 任务：修复 X CDN 头像缓存、来源头像版本更新，并在运行记录展示“上游原始结构 + 系统标准化结构”；同时纠正简单修复被重复确认的执行流程
- 读取文件：媒体/网络策略、全部 Service scraper、Orchestrator/共享获取/Job 诊断、source test、React 运行记录、测试门禁映射及 API/架构/UI 合同
- 修改文件：新增 `src/services/response_schema.py`、响应结构/媒体单测和 React `ResponseSchemaDetails`；更新 scraper observation、Feed run、共享获取 origin、媒体缓存、source test、订阅运行记录、影响映射与 API/架构/UI/Decision 合同
- 执行验证：定向 Python 167 项通过，新增/相关 React 7 项通过，lint/typecheck/UI contract/build 通过；最终 `test_gate full` 22/22 命令通过、`mapping_miss=false`、43.196 秒；SQLite integrity=`ok`、foreign keys 无行
- 运行验收：付费安全检查 active Job=0、active Apify Job=0、Apify schedule=0、Feed schedule=0；仅 1 个免费 RSS schedule 且下一次为 07:11 UTC。重建本地镜像 `inteliscope-service:local-45c7a64d9215-dirty`，API/Worker 同一 image、readiness database/worker 均 ready、scheduler 不存在；容器内模拟合成 DNS 验证仅 `pbs.twimg.com` 通过，lookalike 与 `video.twimg.com` 被拒绝
- 浏览器验收：运行记录 terminal Job 出现折叠“响应结构”；旧 Job 展开显示“本次运行未记录响应结构”；390px 下 client/scroll width 均为 390、无横向溢出、控制台 0 error。未点击“立即获取”、未创建 Job、未调用 Apify/AI/真实来源
- 结果：X 头像将在下一次成功抓取时安全缓存；远端 path 变化即时换版，同 path 24 小时后按 checksum 复验，候选失败保留旧头像。新 Job 只保存深度 6/256 字段/8 KiB 单层/64 KiB 单 Job 的字段路径与类型，不保存任何响应值；共享缓存明确标记 `cached`
- 未解决问题：现有 X 稳定内容没有保留旧 `author_avatar_url`，无法无上游调用回填当前缺失头像；为避免额外付费，本轮未触发 X 抓取。此前多次确认的根因是机械执行设计技能门槛，后续同一具体方案中的“修复/继续/可以”直接视为授权，除付费、不可逆或架构歧义外不重复确认
- 控制面变更：新增 D023；API/架构/UI 合同增加响应结构与头像换版边界；VPS Tokyo 未修改

### 2026-07-16 12:13 Codex
- 任务：发布 `v1.6.0` tag/GitHub Release，并更新 `vps-tokyo` Docker 版本
- 修改文件：版本标识与发布候选已在提交 `6585899` 固化；本条更新 `WORKLOG.md`
- 执行验证：本地 release gate 24/24 通过、`mapping_miss=false`；tag 与 GitHub Release 已发布；Tokyo 部署前数据库 integrity=`ok`、foreign keys=0、active jobs=0，旧 API/Worker 当时均 healthy
- 结果：`v1.6.0` 发布完成；tag 源码已上传至 `/opt/inteliscope/releases/v1.6.0-658589901945` 并开始构建，但尚未切换 `/opt/inteliscope/current`、`.env`、数据库或生产容器
- 未解决问题：Tokyo 在无 swap、旧 API/Worker 在线时执行远端 `npm ci` 后耗尽主机响应能力；构建已从客户端中止，但 SSH banner 与公网健康检查持续超时。必须先通过云厂商控制台重启 VPS，再停止残留构建、确认旧服务/数据库、配置 2 GB swap 后重试镜像构建与切换
- 控制面变更：项目版本从 `1.5.0` 升为 `1.6.0`；未更改 API/架构合同语义

### 2026-07-16 13:58 Codex
- 任务：恢复重启后的 `vps-tokyo`，完成 `v1.6.0` Docker 部署
- 修改文件：`WORKLOG.md`；VPS `/etc/fstab` 增加 2 GiB swap，`/opt/inteliscope/current` 切换至 `releases/v1.6.0-658589901945`
- 执行验证：镜像 `inteliscope-service:v1.6.0-658589901945` 构建成功；迁移补齐 29 条 user content 索引，数据库 integrity=`ok`、foreign keys=0；API/Worker 均 healthy、RestartCount=0；公网 root=200，live 返回 version=`1.6.0`/revision=`658589901945`，ready 返回 database/worker=`ready`
- 结果：Tokyo 已完成 `v1.6.0` 切换；发布前备份位于 `/opt/inteliscope/backups/pre-v1.6.0-658589901945-20260716T054847Z`，迁移专用备份位于 `/opt/inteliscope/data/backups/service-user-content-v4-20260716T055503103067Z.db`
- 未解决问题：无
- 控制面变更：生产运行版本更新至 `v1.6.0`；未更改 API/架构合同语义

### 2026-07-16 15:16 Codex
- 任务：实现 Inteliscope × OpenClaw 本地 Agent 的用户级只读 Remote MCP 接入
- 修改文件：新增 schema v6 delegation 生命周期、六个只读 MCP 工具与 HTTP transport、`/agents` 助手连接页面、OpenClaw Skill、Nginx 限流、性能脚本及隔离/安全/前后端测试；同步 API/架构/UI/计划/决策合同
- 执行验证：定向后端与前端测试通过；最终 `test_gate full` 22/22 命令通过、`mapping_miss=false`；Playwright 16 项通过、11 项按环境预期跳过；真实 MCP Python Client 完成 initialize/list/call；100 次 MCP 顺序调用 p95=7.499 ms、相对 REST 增量=6.411 ms、RSS 增量=0.578 MiB；Skill 校验通过；本机 OpenClaw 2026.7.1 的 MCP/Skill CLI 参数检查通过
- 结果：功能默认关闭且未改动生产；每位用户可创建最多 5 个 90 天只读连接，令牌仅显示一次且数据库只保存 hash；Remote MCP 精确暴露六个自有数据工具，Web UI 不连接本地 Gateway，Skill 使用环境变量引用令牌
- 未解决问题：尚未创建真实一次性连接或执行 `openclaw mcp doctor inteliscope --probe`，也未执行 staging、生产 Nginx/canary 和功能开关启用；这些步骤需要部署环境与真实用户凭证
- 控制面变更：新增 D024；API/架构/UI 合同和 PLAN 增加 Remote MCP、delegation、助手连接及本地 OpenClaw 边界；新增测试影响映射，`project-defaults.yaml` 能力词汇无需变更

### 2026-07-17 01:05 Codex
- 任务：实现 Codex-inspired Next Web 工作台的固定数据视觉原型
- 修改文件：新增 Next 暗色主题与 `/__preview/workbench`，实现精简导航、卡片展开、收藏切换、短刻度、新内容提示和 OpenClaw 上下文交接；同步 UI/计划/决策合同与测试
- 执行验证：基线 103 项 Vitest 通过；新增路由、收藏与交互测试完成 RED→GREEN，最终 107 项通过；三视口 Playwright/Axe 3 项通过；UI contract、TypeScript、ESLint 与 Vite build 通过；1280×720 与 658×889 人工浏览器检查无横向溢出，收藏状态可切换，并修正 Agent 面板遮挡卡片操作的问题；最终 `test_gate full` 22/22 命令通过、`mapping_miss=false`
- 结果：原型可在本地无登录打开，未调用 API、未切换默认 UI、未修改生产；等待人工视觉确认后再接真实 Feed 与连接状态
- 未解决问题：尚未执行真实数据接入、虚拟列表、legacy/next 切换和完整多视口 Playwright 基线
- 控制面变更：新增 D025；UI_CONTRACT 明确 Codex 仅为视觉语言参考且视觉原型为真实数据接入门禁

### 2026-07-17 10:17 Codex
- 任务：实现 HeroUI v3 独立工作台视觉原型，与现有 MUI 原型进行同数据、同布局和同交互对照
- 修改文件：新增开发专用 `/__preview/workbench-heroui`、HeroUI 复合卡片与响应式三栏样式、共享预览数据模型、入口隔离和生产包排除检查；更新 MUI 版本切换、UI/计划/决策合同与测试
- 执行验证：UI contract 通过；ESLint 0 error（保留既有 Fast Refresh warning）；TypeScript 通过；Vitest 27 个文件共 111 项通过；Vite 生产构建与 HeroUI 排除检查通过；MUI/HeroUI 三视口 Playwright+Axe 9 项通过；最终 `test_gate full` 22/22 命令通过、`mapping_miss=false`、48.427 秒；1440×900 人工检查显示 5 张完整卡片，无横向溢出
- 结果：HeroUI 路由在应用根入口提前分流，不进入 MUI、认证、Query Client、API 或生产全局 CSS；实现卡片展开、收藏、搜索、短刻度、新内容、最多 8 条 Agent 上下文和确定性交接复制；平板覆盖面板、手机 Bottom Sheet、Escape/关闭按钮焦点归还和 Reduced Motion 均已验证
- 未解决问题：当前仍为固定净化数据的视觉原型；等待用户与 MUI 版对比确认后，才决定是否采用 HeroUI 生产迁移或仅提取视觉语言
- 控制面变更：新增 D026；UI_CONTRACT 明确 HeroUI 原型边界、组件要求、生产排除与视觉验收门禁

### 2026-07-17 11:46 Codex
- 任务：建立 HeroUI 正式设计系统与应用 bootstrap 边界，不迁移业务页或移除 MUI
- 修改文件：新增 `frontend/src/design-system/**`、Router bridge 与静态导入契约测试；更新 `AppBootstrap`、UI/Decision 合同和全站迁移计划
- 执行验证：TDD RED→GREEN；最终 Vitest 29 文件/116 项、UI contract、TypeScript、Vite build 与 preview exclusion 通过；ESLint 0 error、保留既有 1 warning
- 结果：正式业务只能经 design-system 使用 HeroUI；固定数据原型保留直接导入例外；QueryClient、认证、ServiceApi 与现有 MUI 页面边界不变
- 未解决问题：既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning 不属于本任务
- 控制面变更：新增 D027；UI_CONTRACT 固化 HeroUI 生产迁移边界与渐进 bootstrap

### 2026-07-17 12:01 Codex
- 任务：修复 Task 1 评审发现的 HeroUI 有效圆角和动效时长越界
- 修改文件：`frontend/src/design-system/theme.css`、`frontend/e2e/design-system-contract.spec.ts`、Task 1 报告
- 执行验证：真实 Vite+Tailwind 编译 CSS 的浏览器 computed-style 测试完成 RED→GREEN；最终 Vitest 29 文件/116 项、UI contract、TypeScript、build/preview exclusion 与定向 Playwright 2 项通过，ESLint 0 error
- 结果：Tabs/Table/溢出控件圆角固定为 14/16/8px；正式主题内 transition/animation 固定为 160/220ms，Toast view transition 同步覆盖，Reduced Motion 保持 1ms
- 未解决问题：保留既有 Fast Refresh warning 与 Vite 500 kB chunk warning
- 控制面变更：无；仅修正既有 D027 主题实现偏差

### 2026-07-17 12:17 Codex
- 任务：修复 Task 1 二次评审发现的 HeroUI Portal 主题逃逸与全局动效覆盖
- 修改文件：`frontend/src/design-system/DesignSystemProvider.tsx`、`theme.css`、设计系统 Playwright 契约与隔离 fixture、Task 1 报告
- 执行验证：真实 Modal/Tooltip 与连续动画 computed-style 测试完成 RED→GREEN；Vitest 29 文件/116 项、UI contract、TypeScript、build/preview exclusion、Playwright 5 项通过；full gate 22/22 通过、`mapping_miss=false`，ESLint 0 error
- 结果：正式 provider 以引用计数同步并精确恢复文档根主题；有限动效改为组件级选择器，静态元素不新增动效，Skeleton/Spinner 保留连续节奏，Portal Reduced Motion 生效
- 未解决问题：保留既有 Fast Refresh warning 与 Vite 500 kB chunk warning
- 控制面变更：无；仅修正既有 D027 主题实现偏差

### 2026-07-17 13:00 Codex
- 任务：实现 HeroUI 正式核心工作台、虚拟信息流与本地 OpenClaw Agent 上下文交接
- 修改文件：新增 `frontend/src/features/workbench-live/**`、真实 API 开发验收路由和三视口 Playwright；提取共享乐观更新、增加 Feed v2 偏好/稳定排序/Agent session 清理，并安装精确版本 `@tanstack/react-virtual@3.14.6`
- 执行验证：TDD RED→GREEN；UI contract、TypeScript、Vite build/preview exclusion 通过；ESLint 0 error（保留既有 1 warning）；Vitest 33 文件/138 项、三视口 Playwright/Axe 3 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、56.39 秒
- 结果：开发专用认证路由 `/__preview/workbench-live` 已接真实 ServiceApi，实现 Feed/收藏/历史统一卡片、动态虚拟列表、深链降级、筛选、刷新反馈、权限与回滚、响应式 Agent 面板及确定性交接；MUI 仍为生产默认，固定数据 HeroUI 原型未变，Task 3 页面未迁移
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换等待 Task 4
- 控制面变更：无；复用现有 API、查询键、权限、Remote MCP 和 ActionGeneration 合同，仅新增开发验收入口

### 2026-07-17 14:23 Codex
- 任务：修复 Task 2 评审发现的 legacy 路由、详情合并、筛选、虚拟流锚点/新内容、Agent Drawer 与 loading 状态问题
- 修改文件：`App` 路由/回归测试、Feed/workbench 模型与虚拟列表、HeroUI Shell、design-system portal foreground、三视口 Playwright、Task 2 报告
- 执行验证：定向 Vitest 4 文件/34 项、全量 Vitest 33 文件/148 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、Portal 契约 1 项、三视口 Playwright/Axe 3 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、68.966 秒
- 结果：保留生产 `/later`；inline `?item=` 不再 remount/跳中；详情始终获取并合并 v2；深链穿透筛选；固定窗口按 ID 识别新内容；窄屏使用受控 HeroUI Drawer，delegation 加载显示中性状态，Portal 统一继承主题前景色
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；仅修复既有 D027/Task 2 实现偏差

### 2026-07-17 14:53 Codex
- 任务：修复 Task 2 二次评审发现的异步 404 误清理、失效初始深链定位、筛选钉选顺序、滚动窗口锚点、Agent loading 文案与桌面关闭空栏问题
- 修改文件：`HeroWorkbenchPage`、`VirtualFeed`、`HeroWorkbenchShell`、App/三视口 Playwright 回归、Task 2 报告与实施计划
- 执行验证：focused Vitest 23 项、全量 Vitest 33 文件/150 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、Portal 契约 1 项、三视口 Playwright/Axe 6 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、57.375 秒
- 结果：404 仅在 active source 成功且确证缺失后清理；真实缺失深链回到底部区；筛选钉选保持时序；固定长度窗口严格保持 top-visible ID 与 ≤2px 相对偏移；桌面 Agent 关闭卸载 360px 空栏并保持 Feed，loading 只显示 skeleton busy 状态
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；未修改 backend/API/query key/权限/Remote MCP/MUI 与 Task 3 边界

### 2026-07-17 15:22 Codex
- 任务：修复 Task 2 三次评审发现的 cached-success 404 竞态、pin/unread-first 排序与过滤态虚拟 fallback 索引问题
- 修改文件：`HeroWorkbenchPage`、`VirtualFeed`、App/三视口 Playwright 回归与 Task 2 报告
- 执行验证：三项 focused RED→GREEN；全量 Vitest 33 文件/152 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Playwright/Axe 9 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、53.140 秒
- 结果：404 仅在 active source 成功且停止 fetching 后确证缺失；钉选详情绕过排除筛选但保持 unread-first 稳定分组；未挂载锚点按 `props.cards` 的真实虚拟顺序恢复并严格保持 ID/≤2px 偏移
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；未修改 backend/API/query key/权限/Remote MCP/MUI 与 Task 3 边界

### 2026-07-17 16:10 Codex
- 任务：实现 Task 3 的 HeroUI 订阅、助手连接、设置与登录 DEV 验收页面
- 修改文件：新增 `frontend/src/features/admin-heroui/**` 与 `live-admin.spec.ts`，扩展 live 路由/Shell、design-system facade/theme、App 回归测试与 Task 3 报告
- 执行验证：focused RED→GREEN；Vitest 33 文件/158 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`
- 结果：复用现有 API/query key/权限/模型完成三标签订阅、Worker/任务、一次性 Agent 令牌、角色化设置/SecretStore 与登录；非工作台页面全宽且无 Agent，MUI/生产默认未变
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；一次合并 Playwright 并发运行触发既有移动端锚点波动，原用例隔离重跑通过
- 控制面变更：无；HeroUI 页面仍为 DEV-only，未修改 backend/API/Remote MCP/生产路由

### 2026-07-17 17:09 Codex
- 任务：修复 Task 3 评审发现的来源获取生命周期、成员角色编辑、运行时间字段、覆盖缺口与高级来源编辑器问题
- 修改文件：HeroUI 订阅/设置/来源表单、ActionFeedback、App/权限/响应结构测试、测试环境兼容层、Task 3 报告与本工作日志
- 执行验证：focused 3 文件/51 项、全量 Vitest 34 文件/173 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、57.642 秒
- 结果：单源获取恢复 queued→running→terminal 与终态失效/安全反馈；Owner/Admin 可编辑非 Owner 角色；运行时间拆分；筛选、权限、结构状态和登录具备行为覆盖；高级编辑器改用设计系统 Fieldset
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/权限函数/Remote MCP/生产路由

### 2026-07-17 17:31 Codex
- 任务：修复 Task 3 复评发现的 Hero 订阅实体级 mutation 反馈与来源获取通知关闭/超时问题
- 修改文件：新增 `HeroActionNotice` 及 fake-timer 测试，更新 Hero 订阅页、App 行为测试、Task 3 报告与本工作日志
- 执行验证：focused 4 文件/60 项、全量 Vitest 35 文件/182 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、60.132 秒
- 结果：schedule/subscribe/unsubscribe/retry 复用 ActionFeedback 实现实体级 pending/错误/成功状态与重复请求抑制；Hero 本地 live region 保证错误可见；来源通知支持手动关闭及 4/8 秒自动关闭，同终态轮询不重开也不重置计时
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/权限函数/Remote MCP/生产路由

### 2026-07-17 17:45 Codex
- 任务：修复 Task 3 复评发现的 mutation API 成功后、查询失效完成前提前解锁竞态
- 修改文件：Hero 订阅页四类 mutation 成功回调、App 全家族 invalidation-pending 回归、Task 3 报告与本工作日志
- 执行验证：可信 RED→GREEN（API 已完成、19 次 `invalidateQueries` 挂起）；focused 4 文件/61 项、全量 Vitest 35 文件/183 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`
- 结果：schedule/subscribe/unsubscribe/retry 在既有 query invalidation promise 完成前持续保留实体级 pending/禁用状态，并继续抑制重复提交；仅刷新后发布成功和解锁
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/失效范围/权限函数/Remote MCP/生产路由

### 2026-07-17 20:15 Codex
- 任务：完成 Task 4 HeroUI 全站生产切换、旧 MUI/Emotion 双栈清理与完整门禁
- 修改文件：生产 bootstrap/路由、Hero Shell/虚拟 Feed、ActionFeedback、固定 Hero preview、静态 UI/构建产物检查、三视口 production E2E；删除 MUI 页面、`frontend/src/ui/**`、MUI 原型/CSS/快照与依赖；更新 UI/计划/决策合同和测试影响映射
- 执行验证：TDD 覆盖生产路由/provider/依赖/侧栏/静态契约/刷新锚点/显式导航；UI contract、lint 0 warning/error、TypeScript、Vitest 28 文件/154 项、build/artifact、Playwright/Axe 36/36 通过；移动过滤锚点 20x/5-worker 压力 20/20；Python API 69 项；`test_gate full` 22/22、`mapping_miss=false`、49.076 秒
- 结果：HeroUI 成为唯一生产 UI；`/feed|saved|history` 使用工作台，admin/settings/login 使用 Hero 页面，`/later` 替换至 `/saved`；固定 `/__preview/workbench-heroui` 继续 DEV-only 且生产剔除；MUI/Emotion 与旧页面完全删除
- 未解决问题：仅保留 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：新增 D028；`UI_CONTRACT.md` 重写为唯一视觉真源，PLAN/影响映射改为引用与当前 Hero 路径；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 21:49 Codex
- 任务：修复 Task 4 评审发现的 rendered-order 锚点、导航 ownership、UI/产物门禁与 saved/history/later 验收缺口
- 修改文件：`VirtualFeed`/筛选面板、生产路由单测与三视口 Playwright、UI source/artifact checker、固定 preview marker、Task 4 报告与本工作日志
- 执行验证：四组 focused RED→GREEN；UI contract、lint 0 error/warning、TypeScript、Vitest 28 文件/160 项、build/artifact、三视口 Playwright/Axe 48/48、移动锚点 20x/5-worker 压力 20/20、Python API 69 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、65.117 秒；`git diff --check` 通过
- 结果：rendered cards 成为唯一滚动恢复边界，raw source 不再重复恢复；所有显式导航/用户取消统一释放 refresh/restoration/inline timer+RAF ownership；business CSS/CSS Module 与固定 preview 产物绕过被封堵，MUI 检测不再误报无关 `Mui` 子串；`/saved`、`/history`、`/later` 真实集合路由具备生产验收
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:08 Codex
- 任务：关闭 Task 4 二次评审中的刷新/轨道导航同事件循环竞态，并把 UI/产物负向测试升级为真实不可绕过执行门禁
- 修改文件：`VirtualFeed` 与生产竞态 Playwright；UI source/artifact checker；固定 preview fixture 运行时 marker；可执行 Vitest 负向用例；Task 4 报告与本工作日志
- 执行验证：真实负向门禁 2 文件/21 项、竞态三视口 3/3、全量 Vitest 28 文件/166 项、UI contract、lint 0 error/warning、TypeScript、build/artifact、三视口 Playwright/Axe 48/48、Python API 69 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、50.462 秒；`git diff --check` 通过
- 结果：显式导航统一清除旧 viewport fallback，刷新响应在 rail click 后 microtask 内返回也不能抢回旧锚点；真实 Vite preview-story bundle、`.Mui-disabled` 产物、动态 CSS Module 与现代 CSS 色彩均由实际 checker 失败，负向覆盖不再依赖源码字符串或可独立 tree-shake 标记
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或正式门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:44 Codex
- 任务：修复 Task 4 终审发现的列表缩短后 progress rail 待导航索引没有同步截断，导致后续卡片更新可能重新抢占滚动位置
- 修改文件：`VirtualFeed`、导航纯函数及其 Vitest、生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：RED→GREEN 导航索引截断测试；关键桌面竞态 4/4；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright、Python API 69 项、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：高索引 rail target 在 200→50 收缩时写回真实末项索引；抵达后可释放 ownership，后续 dismissed 卡片更新不会跳回旧目标
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:58 Codex
- 任务：关闭 Task 4 第四审中 cards commit 与下一帧之间用户取消无法阻止 pending-navigation RAF 回写的竞态
- 修改文件：`VirtualFeed`、生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：真实 RAF gate RED（旧实现 wheel 后回跳至 scrollTop 7231）→GREEN；关键桌面竞态 2/2；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright 54 scheduled（50 pass/4 desktop-only skip）、Python API 69 项、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：release 路径会取消 cards commit 的 pending RAF，回调亦校验仍持有同一导航对象；缩短列表回归改用 Shell 搜索触发后续 cards update，不再借由卡片 pointer action 隐式释放
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 00:10 Codex
- 任务：关闭 Task 4 第五审中 shrink + 外部搜索回归可能在过滤 cards commit 前即通过的测试时序缺口
- 修改文件：生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：关键桌面竞态 2/2；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright 54 scheduled（50 pass/4 desktop-only skip）、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：搜索后先确认过滤结果为 11 条，再完成稳定多帧视口采样，最后断言未回弹；专用 wheel/RAF gate 保持独立覆盖 commit-to-next-frame 取消窗口
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 00:40 Codex
- 任务：关闭 Task 4 终审中的门禁优先级/导入绕过、移动导航、筛选可访问性、来源选项校验、生产 E2E 与深链重复请求缺口
- 修改文件：test gate 规划器与可执行 UI/ESLint 门禁；Hero Shell/Feed/预览导航与筛选；来源注册表 Select；release Playwright 配置及 RTL/E2E 回归
- 执行验证：RED→GREEN：`UI_CONTRACT.md` 映射与 7 个模板导入负例；App RTL 44 项、全量 Vitest 29 文件/175 项、UI contract、lint、TypeScript、build/artifact；DEV preview mobile 2 项、release build+preview 三视口 29 通过/4 既定跳过、`test_gate full` 22/22、`git diff --check` 均通过
- 结果：控制文件显式规则优先于 docs-only；静态模板动态导入不能绕过 checker/ESLint；390px 可访问全部六个目的地；筛选由 HeroUI overlay 承担 Escape/焦点归还；必填 Apify 下拉项显示帮助与字段错误且阻止无效创建；已有 snapshot 展开不再请求 feedItem；release 只运行构建产物并排除 DEV-only 预览/fixture
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 01:30 Codex
- 任务：关闭 Task 4 最终复审中的 release Playwright 命令、来源表单原生校验、深链请求时序、字段帮助和筛选外点焦点归还缺口
- 修改文件：`test_gate.py` 与 Python 门禁回归、Hero 来源表单、工作台深链查询、App RTL、生产 Playwright、Task 4 报告与本工作日志
- 执行验证：RED→GREEN（exact release argv、深链 source-settle、Apify 选项错误清除、来源 URL/数值/NaN 约束）；UI contract、lint、TypeScript、Vitest 29 文件/178 项、build/artifact、release build+preview 三视口 29 通过/4 既定 skip；导航 RAF 与移动过滤锚点各 30x/5-worker 压力 30/30；`test_gate full` 22/22、`mapping_miss=false`、51.941 秒；三份 Compose config 与 `git diff --check` 均通过
- 结果：release gate 强制调用 `e2e:release`；来源表单移除 `noValidate` 并在修正输入后清除字段错误；已在 source snapshot 的深链不再提前取 detail；正常字段输出 help；筛选支持外点关闭并归还触发器焦点
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 03:19 Codex
- 任务：关闭全分支终审中的来源类型切换状态串用、必填下拉无障碍语义及整数静默截断缺口
- 修改文件：Hero 来源创建对话框/注册表选项、App RTL 回归、Task 4 报告与本工作日志
- 执行验证：可信 RED→GREEN（类型切换仍显示旧/空选项、required 语义缺失）；focused 3 项、UI contract、lint、TypeScript、全量 Vitest 29 文件/179 项通过
- 结果：来源类型变化时按 type 重建 SourceForm 并加载该定义默认值；必填选项保留 HeroUI/React Aria required 语义，同时继续由统一中文字段校验输出错误；整数型 registry 字段拒绝小数并显式使用 step=1，避免后端静默截断
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 14:00 Codex
- 任务：按用户批注仅收口 `/feed` 的 Codex-inspired 视觉基准，移除搜索/手动更新，改用 macOS 系统字体栈，并重做带动效的左侧短刻度
- 修改文件：Feed Shell 路由边界、虚拟信息流进度轨、Feed 专用字体变量、RTL/Vitest 回归、UI 契约/决策/实施计划与本工作日志
- 执行验证：两轮可信 RED→GREEN（Feed 控件隔离、Codex 轨道；4 条真实数据时仍保持 28 个视觉刻度）；focused 18 项、UI contract、lint、TypeScript、Vite build/artifact 通过；真实 API 浏览器核验 `/feed` 动画轨道及 `/saved` 未受影响；最终 `test_gate full` 22/22、`mapping_miss=false`、51.982 秒；`git diff --check` 通过
- 结果：`/feed` 顶栏只保留标题与 Agent 开关，采用系统字体；300px/28 段左轨随可见卡片以 160ms 宽度/颜色/透明度动效反馈并支持 Reduced Motion；收藏和历史继续保留原搜索、更新按钮和紧凑右轨
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：新增 D029 并更新 `UI_CONTRACT.md` 的 Feed 专属视觉边界；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 Codex
- 任务：实现 Quiet Studio Feed 顶栏、工具行和双栏 Agent 图标，并先更新 UI 契约
- 修改文件：设计系统图标出口、Hero Shell/Page、两项 focused Vitest、UI 契约与本工作日志
- 执行验证：`npm --prefix frontend run test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx src/app/App.test.tsx` RED（2 项目标行为失败）→GREEN（2 文件/52 项通过）
- 结果：Feed 使用 Quiet Studio header 标记、受控 split-panel 图标与简化工具行；收藏/历史保持原图标和 collection 工具行
- 未解决问题：后续任务仍负责移除 Feed rail 与重设卡片；本任务未执行它们的视觉/全量门禁
- 控制面变更：`UI_CONTRACT.md` 将 `/feed` rail 规则替换为 Quiet Studio 的绑定布局、动效、可访问性与受控尺寸语义

### 2026-07-18 Codex
- 任务：补齐 Quiet Studio Feed 已启用筛选数量的回归覆盖
- 修改文件：`App.test.tsx`、Task 1 报告与本工作日志
- 执行验证：`npm --prefix frontend run test -- src/app/App.test.tsx` RED（缺少 `已启用 3 项筛选`）→GREEN（1 文件/49 项通过）
- 结果：持久化的未读优先、来源和最低分筛选会显示可访问的三项计数
- 控制面变更：无

### 2026-07-18 Codex
- 任务：移除 Quiet Studio Feed 进度轨道及其留白，并保持收藏/历史的 collection 轨道
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、`HeroWorkbenchPage.tsx`、本工作日志
- 执行验证：`VirtualFeed.test.tsx` RED（Quiet Studio 仍渲染 compact rail）→GREEN（与 `App.test.tsx` 共 2 文件/58 项通过）；`git diff --check` 通过
- 结果：`/feed` 显式使用 `quiet-studio`，无进度导航/预留 gutter，列宽约 820px；`/saved` 与 `/history` 保持 12 刻度紧凑右轨和原列宽
- 控制面变更：无

### 2026-07-18 Codex
- 任务：实现 Quiet Studio Feed 卡片层级、原位展开动效与 Agent 上下文确认态
- 修改文件：Feed 圆角 token、`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、本工作日志
- 执行验证：`VirtualFeed.test.tsx` RED（2 项目标行为失败）→GREEN；聚焦 Vitest 3 文件/64 项、UI contract、TypeScript、`git diff --check` 通过
- 结果：仅 `/feed` 使用 18px 卡片、细边界悬停反馈、可动画详情与移动端 44px 操作；collection 卡片继续保持既有结构
- 控制面变更：无

### 2026-07-18 Codex
- 任务：更新 Quiet Studio Feed 的三视口生产交互与隔离回归
- 修改文件：生产工作台 Playwright、本工作日志
- 执行验证：release RED（旧轨道/刷新断言 11 项失败）→GREEN；Vite build/artifact 通过，desktop/tablet/mobile Playwright 21/21 通过，`git diff --check` 通过
- 结果：生产验收覆盖无 Feed rail、后台任务刷新、18px/820px 卡片、原位展开、Agent 图标、Reduced Motion、键盘/44px 触控与 collection 隔离；移除 Feed rail-only 用例和固定等待
- 控制面变更：无；未修改生产组件、backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 Codex
- 任务：固化 Quiet Studio Feed 合同、完成一次最终门禁并发布 revision-locked 本地 8080 预览
- 修改文件：`UI_CONTRACT.md`、`DECISION_LOG.md`、`PLAN.md`、本工作日志
- 执行验证：Task 1–3 focused TDD RED→GREEN（52 项及 49 项补充、58 项、64 项）；Task 4 release build/artifact 与三视口 Playwright 21/21、Axe 零 serious/critical；本次 `test_gate full` 22/22、`mapping_miss=false`、55.339 秒；镜像 `inteliscope-service:feed-quiet-fef5862f1c48` 的 live revision=`fef5862f1c48`、ready database/worker=`ready`、`/feed` HTTP 200，API/Worker 同镜像且 healthy
- 结果：D030 与唯一视觉真源已收口，主仓库 light Compose 的本地 API/Worker 已换为一次构建的 Quiet Studio 镜像；控制器随后在应用内浏览器完成真实运行态复核：`/feed` 显示 4 条 Quiet Studio 卡片、无进度轨及其留白，split-panel Agent 图标、原位展开与加入上下文均可用，Agent 关闭/重开前后 Feed `scrollTop` 均为 `396.5`；`/saved` 与 `/history` 继续显示 collection rail、搜索和更新入口，分别渲染 1/6 张集合卡片；三条路由 console error 均为 0，测试加入的 Agent 上下文已移除
- 控制面变更：仅 Feed 视觉合同和交付状态；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度器

### 2026-07-18 Codex
- 任务：关闭 Quiet Studio 复审中的宽屏 coarse-pointer 卡片操作目标缩为 32px，以及 PLAN 误把设计规格称为实施证据的问题
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、`PLAN.md`、忽略的 Task 5 报告与本工作日志
- 执行验证：定向 Vitest 1 项可信 RED（旧链接缺少 fine-pointer `size-8`）→GREEN（1 通过/11 跳过）；TypeScript、`git diff --check` 通过；修复后的最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、51.651 秒
- 结果：Quiet Studio 四个卡片操作以 32px 为 fine-pointer 基线，并通过 `pointer-coarse:size-11` 在任意视口保持 44px；PLAN 分开标注设计规格与 `WORKLOG.md` 实施证据；Task 5 独立复审无剩余 finding
- 运行验收：一次构建镜像 `inteliscope-service:feed-quiet-f395cbe2137f`（built at `2026-07-18T09:07:00Z`）已替换本地 8080 的 API/Worker；live revision=`f395cbe2137f`、database/worker ready、`/feed` HTTP 200、两容器同镜像且 healthy；容器生产 CSS 包含 `@media (pointer:coarse)`；应用内浏览器刷新后仍显示 4 条 Quiet Studio 卡片、无 Feed 进度轨、Agent 控件可见且 console error 为 0
- 控制面变更：仅修正 PLAN 的证据归属表述；未改变 UI 合同，也未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度器

### 2026-07-18 Codex
- 任务：关闭 Quiet Studio 终审中宽屏 coarse-pointer 卡片操作因视口断点降为 60% opacity、又缺少可靠 hover 的问题
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx` 与本工作日志
- 执行验证：定向 Vitest 1 项可信 RED（旧动作容器缺少 `pointer-fine:` 类）→GREEN（1 通过/12 跳过）；TypeScript、`git diff --check` 通过；新 HEAD 最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、54.881 秒
- 结果：动作容器默认保持 fully visible，仅 fine pointer 降为 60% opacity，并只在 fine-pointer hover/focus 时恢复 100%；coarse pointer 不再受视口宽度影响；整分支复审无剩余 Critical/Important，确认 ready to merge
- 运行验收：一次构建镜像 `inteliscope-service:feed-quiet-d4a5f0489390`（built at `2026-07-18T09:48:20Z`）已替换本地 8080 的 API/Worker；live revision=`d4a5f0489390`、database/worker ready、`/feed` HTTP 200、两容器同镜像且 healthy；容器生产 CSS 包含 `@media (pointer:fine)`；应用内浏览器刷新后显示 4 条卡片、无 Feed 进度轨、Agent 控件可见且 console error 为 0；非阻塞 Minor 为后续补一条 collection rail 行为覆盖
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/scheduler

### 2026-07-18 18:45 Codex
- 任务：执行用户确认的 A「Codex 式信息工作台」细化，仅在现有 HeroUI/Quiet Studio 生产树调整导航、Feed 卡片层级与 OpenClaw 交接区
- 修改文件：Feed v2 偏好与排序、常用视图纯函数、Hero Shell/Page/VirtualFeed/展示模型、Inteliscope 图标、Agent draft/composer、RTL/Playwright，以及 UI 契约、D031、计划与本工作日志
- 执行验证：四批 focused TDD 均 RED→GREEN；最终聚焦 Vitest 6 文件/44 项、ESLint（0 error/1 既有 warning）、TypeScript、Vite build/artifact 通过；桌面 Playwright 主流程、过滤刷新锚点与 Reduced Motion 共 3 项通过，主流程含 Axe 零 serious/critical；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、56.647 秒
- 结果：左栏按浏览/常用视图/管理分类，账户通过菜单显式退出；Feed 默认最新在上并可按用户切换顺序，工具条与 820px 卡片列对齐，重复摘要不再展示；OpenClaw 改为带模型提示偏好、实时状态和单一复制动作的紧凑交接编辑器，不产生网络执行
- 控制面变更：更新唯一视觉真源并新增 D031；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/Worker/scheduler

### 2026-07-18 20:35 Codex
- 任务：从设计系统根部修复全站字体与字号分叉，消除 Feed 工具栏“内容数 / 排序 / 筛选”及后续页面修改的排版不一致
- 修改文件：HeroUI 主题与全局字体入口、UI 静态契约和回归、工作台及管理页语义排版迁移、`UI_CONTRACT.md`、D032 与本工作日志
- 执行验证：契约测试先出现 7 项可信 RED，再完成十级 `type-*` 角色、HeroUI primitive 默认映射与 raw Tailwind 排版拦截；focused Vitest 4 文件/105 项、UI contract、TypeScript、ESLint（0 error/1 既有 warning）、Vite build/artifact 通过；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、55.633 秒，`git diff --check` 通过
- 结果：全站统一 macOS/system UI 字体栈；业务层不能再自行写字号、字重、行高或字距；真实 486px Feed 中“4 条内容 / 最新优先 / 筛选”计算样式均为 13px、500、20px，页面无横向溢出
- 运行验收：重建前确认无 queued/running Job；一次构建镜像 `inteliscope-service:ui-typography-20260718202652` 已替换本地 8080 API/Worker，live revision=`398009563055-typography-dirty`、database/worker ready；应用内浏览器刷新后完成计算样式与截图复核
- 控制面变更：更新唯一视觉真源并新增 D032；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度语义

### 2026-07-19 02:23 Codex
- 任务：执行 Quiet Studio 全站 UI 统一，将已确认的信息流视觉语言扩展至收藏、历史、订阅、助手连接、设置、登录和 OpenClaw 响应式面板
- 修改文件：设计系统共享 `PageFrame/PageHeader/ViewBar/PageSection/CompactSelect` 与状态模式、三条内容路由、OpenClaw `HandoffComposer`、四条管理/认证路由、UI 静态契约、Vitest/Playwright，以及 `UI_CONTRACT.md`、D033、PLAN 和本工作日志
- 执行验证：页面宽度契约完成可信 RED→GREEN；内容工作台聚焦 74 项、管理页 58 项、UI 契约 36 项均通过；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、58.253 秒；release build 三视口 Playwright/Axe 27/27 通过，Axe 零 serious/critical；`git diff --check` 通过
- 结果：全部生产路由统一消费 Quiet Studio 语义页面模式；收藏/历史删除 collection 轨道并复用阅读卡片和 ViewBar；管理页只保留 Shell 中的唯一 H1，登录使用 auth 框架；三种 Agent 容器复用统一交接编辑器。静态契约会拒绝业务页重新定义 820/1180/420px 页面宽度
- 运行验收：重建前确认主数据库无 queued/running Job；一次构建镜像 `inteliscope-service:quiet-studio-c6e83554a16d` 同时替换本地 8080 API/Worker，live revision=`c6e83554a16d`、database/worker ready、两容器同 image ID 且 healthy，六条生产路由 HTTP 200；应用内浏览器真实数据复核设置/订阅唯一标题与统一分区、收藏统一空态、历史 7 张 Quiet Studio 卡片、0 个进度轨且无横向溢出
- 控制面变更：Quiet Studio 成为全站生产视觉语言并新增 D033；未修改 backend/API/DB/query key/权限/任务/Remote MCP/history/VPS/数据/调度语义
### 2026-07-17 10:56 Codex subagent
- 任务：实现 Remote MCP 八类来源的双语配置指引与安全输入规范化
- 读取文件：`AGENTS.md`、任务 brief、source type registry 与相关测试
- 修改文件：`src/services/source_type_registry.py`、来源 registry/setup guidance 测试、`WORKLOG.md`
- 执行验证：新增测试先因缺少接口失败；focused 8 项通过；`test_gate` full 成功
- 结果：新增中英 setup guide、公开 URL/别名规范化和凭据/敏感 RSS 查询拒绝，REST registry 投影保持不变
- 未解决问题：无
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：修复 Task 1 Agent setup 公共类型与输入安全审查项
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`WORKLOG.md`
- 执行验证：先验证公共八类/敏感 query value 回归为 RED；focused 37 项通过，`./.venv/bin/python scripts/test_gate.py run --mode full` 通过
- 结果：Agent guide 固定为 `rss/telegram/github/reddit/twitter/website/youtube/apify`，显式映射至 catalog 类型；REST 投影不变；拒绝所有 URL userinfo/敏感 query、嵌套凭据形状、非标量字段、Telegram 私邀和畸形 URL
- 未解决问题：后续 Task 3 消费 normalization 时应读取其 `catalog_source_type/config` 结构，而非把公共类型直接写入 catalog
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第二轮复审的六项来源规范化安全与执行策略缺口
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：新增回归先出现 66 个预期失败，自审补充 mapping key 回归再确认 1 个预期失败；focused 119 项通过，Python compile 通过，full gate 22/22 通过且 `mapping_miss=false`，`git diff --check` 通过
- 结果：复合敏感 query/header/assignment 和 source type 错误均安全失败；YouTube/Reddit identity 严格规范化；自助来源显式携带 create policy，Twitter/Apify 仅返回 existing-visible lookup identity
- 未解决问题：后续 service 消费方须使用新的 policy-bearing normalization shape；本 Task 未实现 proposal/MCP/UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第三轮复审的四项 Important 与 guide summary Minor
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：review 回归先按预期覆盖五组 RED，自审的 GitHub 双斜杠 identity 再单独 RED；focused 197 项、Python compile、full gate 22/22（`mapping_miss=false`）和 `git diff --check` 通过
- 结果：凭据检测按 query name/value/free text 分层并先做 NFKC；RSS/website 输出强制公网 policy 且本地拒绝 localhost/非公网 IP literal；GitHub/YouTube identity 使用离线真实语法；Apify 仅接收 lookup identity；guide summary 补齐 `required_fields`，旧 REST 投影不变
- 未解决问题：Task 3 必须无视 owner/admin 放宽逻辑，按 `policy.public_network_only=true` 绑定既有逐跳 DNS pinning 公网执行路径；本 Task 未修改 runner/proposal/MCP/UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第四轮复审的四项 Important
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：四组回归先出现 33 个预期失败，Telegram 边界自审再确认 4 个预期失败；focused 246 项、Python compile、full gate 22/22（`mapping_miss=false`）和 `git diff --check` 通过
- 结果：凭据安全副本加入有界 percent decode 与 Unicode ignorable 折叠；RSS/website 拒绝历史 IPv4 本地地址；GitHub clone `.git` 规范化；Telegram query/fragment 与保留路由失败关闭
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第五轮复审的单项 Important（percent-escaped hostname）
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r5-report.md`、`WORKLOG.md`
- 执行验证：新增 10 个 RSS/website percent-escaped hostname 与 IPv6 zone-id 回归先均为 RED；focused 256 项、Python compile、full gate 和 `git diff --check` 通过
- 结果：主机名含 `%` 在公网 literal 分类前以固定非回显错误失败关闭；普通数字标签域名和 `policy.public_network_only=true` 回归保持
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第六轮复审的单项 Important（反斜杠 authority）
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r6-report.md`、`WORKLOG.md`
- 执行验证：RSS/website 反斜杠 authority 回归先均为 RED；focused 258 项、Python compile、full gate 和 `git diff --check` 通过
- 结果：公网 literal 分类前拒绝 authority/hostname 中的反斜杠，使用固定非回显错误；普通域名、numeric-label 域名与 `policy.public_network_only=true` 回归保持
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 schema v7 Agent 变更提案持久化、保留清理与部署数据库脱敏
- 修改文件：`src/storage/service_store.py`、`src/services/maintenance.py`、`scripts/prepare_service_deployment.py`、proposal/maintenance/deployment 测试、Task 2 报告、`WORKLOG.md`
- 执行验证：proposal 测试先出现 17 个预期 RED，自审补充未知 JSON 对象失败关闭再确认 1 个 RED；focused 27 项通过，full gate 22/22 通过且 `mapping_miss=false`，Python compile 与 `git diff --check` 通过
- 结果：新增 v7 additive proposal 表、级联外键/索引/marker、10 分钟 TTL 与 delegation 原子 pending 上限、安全 JSON 投影/写入、30 天维护清理、旧库兼容部署清空，以及 `create_source(commit=False)` 事务支持
- 未解决问题：Task 3+ 仍需在外层 `BEGIN IMMEDIATE` 中消费 `commit=False` 接口并完成业务 apply；本任务未实现 mutation service、MCP 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 复审的两个 Important（权威 proposal 时钟与 camelCase/NFKC 敏感键）
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`tests/test_maintenance.py`、`.superpowers/sdd/task-2-fix-report.md`、`WORKLOG.md`
- 执行验证：8 个针对性回归先按预期 RED；focused 36 项通过；full gate 22/22 通过且 `mapping_miss=false`；Python compile 与 `git diff --check` 通过
- 结果：create/apply 生命周期改用事务内权威 UTC now，调用参数只保留兼容校验；固定持久化 now/now+10m，未来/回填时间不能绕过配额或过期；敏感键先 NFKC/camelCase 拆词，安全业务 ID shape 保持允许
- 未解决问题：无；未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第二轮复审的 compact 敏感键 Important 与自由文本误拒 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：新增回归先出现 25 个预期 RED；proposal 56 项、focused 69 项、full gate 22/22（`mapping_miss=false`）通过；`git diff --check` 通过
- 结果：JSON/query 共用受控 compact credential key 分类并覆盖 NFKC/percent decode；明确凭据 header/assignment、已知 prefix 与 JWT 仍拒绝，`Basic Engineering News`、`Bearer Market Report` 和 `monkey`/`hockey` 等安全词允许
- 未解决问题：无；未修改权威时钟、事务、schema、cleanup、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第三轮复审的 compact credential 后缀 Important 与短 `sk-` 名称 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：新增 12 个回归先按预期 RED；proposal 与指定 focused 测试通过，full gate 通过，`git diff --check` 通过
- 结果：NFKC/camelCase/分隔归一后的 compact key 以受控 credential 后缀失败关闭，JSON 与 percent-decoded query 统一覆盖；`sk-` 仅在长连续 token 且右边界时拒绝，`SK-Engineering Weekly` 保持允许
- 未解决问题：无；未改动 schema、时钟、事务、retention、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第四轮复审的字符串值编码绕过 Important 与长 `sk-` 业务标题误拒 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：三轮回归分别出现 9、2、1 个预期 RED；proposal 86 项、指定 focused 99 项、Python compile 与 full gate 22/22（`mapping_miss=false`）通过，提交前重跑 `git diff --check`
- 结果：所有 proposal 字符串值使用 16 KiB、NFKC、最多两轮 percent-decode 的非持久化分类副本，query name/value 同步覆盖且安全 `%20` 原值不变；真实形态 `sk` 假 token 继续拒绝，两个指定长业务标题允许
- 未解决问题：无；未改动 key suffix、schema、权威时钟、事务、retention、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现共享订阅变更领域服务并让现有 REST mutation 复用
- 修改文件：`src/services/subscription_mutation.py`、`src/api/server.py`、`src/storage/service_store.py`、RSS 执行投影、Task 3/API 测试、`.superpowers/sdd/task-3-report.md`、`WORKLOG.md`
- 执行验证：初始 module、REST context、metadata/config credential 与内部标记投影均先按预期 RED；领域 36 项、指定 focused 165 项、store/config/Worker 43 项、full gate 和 `git diff --check` 通过
- 结果：typed plan/error/actor、Agent private-only planner、安全 preview/指纹、显式 delete disposition、原子 create/update/delete 与完整回滚已实现；REST admin/member/viewer 和 omission/null/list clear 合同保持；Agent RSS/website 公网执行选择持久且 owner/admin 不可绕过
- 未解决问题：Task 4+ 仍需在 proposal 转换事务内消费本服务，并继续隐藏内部公网标记；本任务未实现 proposal orchestration、MCP、delegation flag/scope、新 REST endpoint 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 独立复审的五项 Important
- 修改文件：订阅变更领域服务、来源公开投影/runner、quota、media cleanup、相关 focused 测试、`.superpowers/sdd/task-3-fix-report.md`、`WORKLOG.md`
- 执行验证：计划密封、RSS 公网 marker、quota re-enable、头像 late rollback、安全 preview 与 cleanup collector 回归均先按预期 RED；Python compile 和 focused 452 项通过；full gate 22/22（`mapping_miss=false`）及 `git diff --check` 通过
- 结果：确认后的 normalized plan 使用 canonical snapshot 且 apply 不再重规范化；Agent RSS 更新/runner fallback 均维持公网执行；来源重启用先做 quota admission；头像仅在 owner commit 后物理清理，`commit=False` 缺 collector 失败关闭；遗留不安全 catalog preview 返回稳定 opaque summary
- 未解决问题：Task 4+ 外层事务调用 `apply_plan(commit=False)` 时必须显式传入 cleanup collector，并在 commit 后执行、rollback 时丢弃；本任务未实现 Task 4+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 修正后复审的五项 Important
- 修改文件：订阅变更 plan/restore、quota、media cleanup、来源公开元数据分类器、相关 focused 测试、`.superpowers/sdd/task-3-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：五组回归先按预期 RED；Python compile 与 focused 484 项通过；full gate 22/22（`mapping_miss=false`、`ui_impacted=false`）、默认配置 JSON 校验及 `git diff --check` 通过
- 结果：planner/restore/apply 共用严格版本化 invariant builder；subscription 幂等与 source re-enable admission 分离；外层事务缺 cleanup collector 在 mutation 前失败关闭；公开投影覆盖嵌入式常见 token 且保留安全 Bearer 标题；schedule preview 展示 existing 合并态或 new 默认态
- 未解决问题：Task 4+ 外层事务调用 mutation service 时须显式传 collector，commit 后执行、rollback 时丢弃；本任务未实现 Task 4+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第三轮复审的两个 Important
- 修改文件：共享安全分类器、来源公开投影/metadata、proposal sanitizer、snapshot consumer 计划、三组合同测试、`.superpowers/sdd/task-3-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：Task 3/Task 2 新回归分别先出现 9/10 个预期 RED，`xox*` 扩展再确认 1 个 RED；focused 591 项、Python compile、full gate 22/22（`mapping_miss=false`、`ui_impacted=false`）、默认配置 JSON 校验及 `git diff --check` 通过
- 结果：Task 1/2 共用 16 KiB、NFKC、最多两轮 percent decode 的上下文凭据分类器并覆盖 query value/fragment/known prefixes；metadata parser 异常固定失败关闭；Task 5/6 计划固定为完整 versioned snapshot + restore + outer collector 生命周期，真实 proposal row seam 已验证 commit/run 与 rollback/discard
- 未解决问题：Task 5/6 仍待按已同步合同实现 proposal/MCP 业务；本任务未重开 public constructor 或实现后续业务
- 控制面变更：同步实施计划中的既有 Task 3/5/6 内部接口示例，无对外 API 变更

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第四轮复审的两个 Important
- 修改文件：Agent 来源反向规范化、订阅变更 plan/restore/apply、Task 3/5/6 内部接口计划、三组合同测试、`.superpowers/sdd/task-3-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：反向规范化回归先出现 9 个预期失败，update 共享校验再出现 3 个预期失败；schedule final-state 回归先出现 28 个预期失败；focused 657 项通过，Python compile、默认配置 JSON 校验、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：八个公开 Agent 类型均以 forward normalizer 做确定性反向校验并要求精确相等；update plan 携带 source/subscription/schedule 合并后的完整最终 schedule，禁用级联明确预览，同一计划对 disabled target 显式启用 schedule 在 prepare 阶段稳定拒绝；restore/apply 共用绑定并在 apply 后核对实际最终 schedule；snapshot 升级为 v2，v1 失败关闭且须重新 prepare
- 未解决问题：Task 5/6 仍待按已同步的 v2 snapshot 合同实现 proposal/MCP 业务；本任务未实现后续业务、迁移或兼容 fallback
- 控制面变更：同步实施计划中的 Task 3/5/6 内部 snapshot 版本与消费者合同，无对外 API 变更

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第五轮复审的两个 Important 与一个 Minor
- 修改文件：create/upsert 最终 schedule plan/restore/apply、quota final-active admission、Task 3 brief、mutation/API 回归、`.superpowers/sdd/task-3-fix-r5-report.md`、`WORKLOG.md`
- 执行验证：21 个 create/quota 回归先出现 13 个预期失败，GREEN 后补充 forged snapshot/live binding 2 项；12 文件 focused 693 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）与 `git diff --check` 通过
- 结果：create/upsert 与 update 共用最终 schedule 计算，final disabled subject 的显式 schedule enable 在 prepare 拒绝，sealed preview 与 apply 实态不一致会回滚；quota 仅对最终 inactive→active 转换 admission，真实 source re-enable 仍独立检查；brief 同步 v2/v1 fail-closed/reprepare
- 未解决问题：Task 5/6 仍待按既有 v2 snapshot 合同实现 proposal/MCP 业务；本任务未实现后续业务、迁移或兼容 fallback
- 控制面变更：仅同步忽略目录中的 Task 3 scratch brief，无对外 API 或主实施计划变更

### 2026-07-17 Codex subagent
- 任务：实现 delegation 显式订阅写权限与独立默认关闭功能开关
- 修改文件：delegation store/API、Remote MCP 配置、三组 focused 测试、`.superpowers/sdd/task-4-report.md`、`WORKLOG.md`
- 执行验证：required focused 先出现 17 个 RED，修正测试夹具后确认目标 RED；GREEN 32 项、相关 TokenVerifier/store 回归 113 项、full gate 22/22（`mapping_miss=false`）通过，提交前重跑 diff/JSON 检查
- 结果：新增 read/write canonical scope 与安全 access 投影；旧行不迁移，未知/额外 scope 失败关闭；写开关严格 `true|false` 且依赖 Remote MCP；GET/POST/PATCH 权限、viewer 稳定 403 和 rename 防升级完成
- 未解决问题：Task 8 写工具仍须在每次调用时检查 live flag；本任务未实现 proposal、MCP 写工具、UI 或生产启用
- 控制面变更：无；总方案后续文档任务统一更新 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：修复 Task 4 delegation scope 损坏值导致的 GET/TokenVerifier 异常
- 修改文件：`src/storage/service_store.py`、delegation/API/真实 MCP 回归、`.superpowers/sdd/task-4-fix-report.md`、`WORKLOG.md`
- 执行验证：四个 Task 4 模块新增回归先出现 9 个预期 RED；GREEN 64 项、full gate 22/22（`mapping_miss=false`、`first_failure=null`）及最终 `git diff --check` 通过
- 结果：scope 使用专用 512 字符、四层 JSON 容器上限解析器；原始值仅接受 `str`，BLOB（含可解码 JSON）、损坏/超长/过深/非 list/未知/重复值全部投影空 scope，GET 稳定 200，MCP 缺 read scope 返回 403
- 未解决问题：无；未修改通用 `_json_loads()`，未实现 Task 5+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 Task 5 安全来源发现与 prepare-only 订阅变更提案
- 修改文件：proposal service、Remote MCP subscription facade、source type discovery mapping、live delegation principal、Task 5 回归、`.superpowers/sdd/task-5-report.md`、`WORKLOG.md`
- 执行验证：新测试先因两个 Task 5 模块不存在按预期 RED；GREEN 15 项、指定 focused 252 项、Python compile、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：动态 flag/scope/live role/actor binding 在 planner 前失败关闭；v2 snapshot、store 权威 UTC 10 分钟、confirmation hash-only 与 proposal limit 完成；发现仅投影当前用户可见来源并限制 secret checker 与 managed Apify
- 未解决问题：Task 6 仍需实现 atomic apply/stale/single-use；本任务未实现 apply、MCP 工具注册、server wiring 或 UI
- 控制面变更：无；仅新增内部 Task 5 服务边界，外部 MCP/API 合同由后续统一任务更新

### 2026-07-17 Codex subagent
- 任务：关闭 Task 5 独立复审的两个 Important 与一个 Minor
- 修改文件：proposal service/store、source discovery registry/facade、Task 5/maintenance/deployment 回归、`.superpowers/sdd/task-5-fix-report.md`、`WORKLOG.md`
- 执行验证：facade 6 项与 store 4 项回归先按预期 RED，最终动态 flag guard mutation check 再确认 RED/GREEN；focused 594 项、maintenance/deployment 6 项、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：proposal 最终授权与 insert 由同一 `BEGIN IMMEDIATE` 锁定并增加 store active-principal 纵深条件；discovery 使用八类显式 matcher、YouTube/RSS 边界、Twitter/Apify 分区及稳定去重排序；secret checker 异常固定脱敏为 `source_discovery_unavailable`
- 未解决问题：Task 6 仍需实现 atomic apply/stale/single-use；本任务未实现 Task 6+、MCP 注册、server wiring 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 5 二次复审的一个 Important 与一个 Minor
- 修改文件：Agent-safe subscription planner/apply revalidation、source discovery public type validator、Task 5/Task 3/registry 回归、`.superpowers/sdd/task-5-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：disabled existing 与空目录 unknown type 回归先出现 6 个预期 RED；GREEN 专项 9 项、focused 433 项、Remote MCP 邻接 308 项及 Python compile 通过；最终 full gate、JSON 与 diff 检查见报告
- 结果：existing create 在 planner 与 apply 均要求 enabled/visible，facade 后竞态不生成 proposal、plan 后禁用不能应用；8 项 public source type 在目录扫描前稳定校验；REST 专用 mutation 权限保持不变
- 未解决问题：Task 6+ 未实现；本任务未新增内部 allow-disabled Agent 能力
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 Task 6 proposal 原子 apply、过期/陈旧处理与单次并发消费
- 修改文件：proposal service/facade、store 权威 transition、Task 6 回归、主实施计划、`.superpowers/sdd/task-6-report.md`、`WORKLOG.md`
- 执行验证：新增 apply 17 项与 store clock 专项先按预期 RED；Task6/mutation 280 项、delegation/media 36 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：apply 自有 `BEGIN IMMEDIATE` 并在锁内重验动态 flag/scope/live principal；store UTC 10 分钟边界、time crossing 仅提交 expired、exact HMAC compare、v2 duplicate/stale、safe summary、post-commit cleanup 与 exactly-once 并发完成；所有非 expiry 失败保持 pending 且业务零变化
- 未解决问题：Task 7+、MCP 工具注册/server wiring、UI/Skill 与生产启用仍未实现
- 控制面变更：仅勾选既有主实施计划 Task 6 执行状态；未改变对外 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：关闭 Task 6 复审的一个 Important 与一个 Minor
- 修改文件：proposal apply cleanup 边界、成功 update/delete apply 回归、主实施计划、`.superpowers/sdd/task-6-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：cleanup 抛错回归先按预期 RED，update 与 delete 两种 disposition 同轮通过；GREEN 专项 4 项、Task 6 focused 284 项、邻接 36 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：commit 后 cleanup 异常静默 best-effort，不再伪装 mutation 失败或泄露异常内容；update/delete keep/delete disable_private 均验证业务提交、proposal applied、stored/returned 精确 safe summary 与 second-use consumed
- 未解决问题：Task 7+、MCP 工具注册/server wiring、UI/Skill 与生产启用仍未实现
- 控制面变更：仅修正既有主实施计划中的 post-commit cleanup 内部错误语义；未改变对外 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：实现 Task 7 确定性来源/任务诊断与严格安全投影
- 修改文件：诊断服务、Remote MCP safe job result helper、诊断/read-service 回归、主实施计划、`.superpowers/sdd/task-7-report.md`、`WORKLOG.md`
- 执行验证：模块缺失与 safe-code retention 专项均先按预期 RED；focused 75 项、runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：固定 precedence/code/message/unknown 分类、跨用户 not_found、URL/query/Bearer 与内部字段零泄漏、secret bool/anonymous Worker evidence、ordinary list/get job 投影不变均已实现
- 未解决问题：Task 8+ 的 MCP 工具注册/server wiring、UI/Skill、生产启用与 canary 尚未实现
- 控制面变更：仅勾选既有主实施计划 Task 7；未更新对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 独立审查的三个 Important 与一个 Minor
- 修改文件：诊断 related-job/no-items/scalar/clock 边界、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：新增 18 项反例按预期 RED；GREEN 后 Task 7 focused 94 项、schedule/runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：Health/Schedule 显式 FK 完整验证并优先 active schedule、owned full-refresh 可关联；Job no-items 仅认自身 succeeded+明确零 fetched count；credential key label 在 code/result/name 零泄漏；每个公开诊断使用单一 checked_at
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步既有 Task 7 内部证据选择、安全过滤与一致时钟语义；普通六工具与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第二轮独立审查的四个 Important
- 修改文件：Job/Source 独立归因、关联 provenance、严格 count/credential-label 投影、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：34 项主反例与 1 项完整 name 标量专项按预期 RED；GREEN 后 Task 7 focused 139 项、schedule/runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：Job 仅按自身归因且 Worker readiness 仅限 active；Source 更新 Schedule terminal failure 胜过旧 Health 并标记历史 evidence；畸形 count 不再归零；完整对外标量严格拒绝 access/private/key-env/api-key-env labels
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部归因与安全投影语义；普通六工具、通用 credential mapping classifier 与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第三轮独立审查的两个 Important，并接管复核前任未提交修复
- 修改文件：active/same-ID retry 归因、完整标量安全分类与普通值保留、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：接管后新增 same-code retry 1 项与普通 Bearer/Basic 名称 4 项按预期 RED；GREEN 后 diagnostics 191 项、focused 240 项、schedule/job retry/health Worker/API/MCP 邻接 143 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`）及 `git diff --check` 通过
- 结果：active selected Job 的 status 与 historical Health role 一致；同 ID retry 使用真实 ledger+更新时间识别并由当前 terminal Job 决定 status/cause；完整标量拒绝紧凑 Bearer/Basic、terminal key/connection-string/credential labels，普通业务标量保持可见
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 attempt provenance 与严格标量投影语义；普通六工具、通用 credential mapping classifier 与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第四轮独立审查的一个 Important
- 修改文件：JobQueue retry 的 Source Health provenance 重开、diagnostics 显式 FK 归因、真实 Worker/事务/并发回归、主实施计划、`.superpowers/sdd/task-7-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：真实 catalog partial→同 ID retry→success/failed/partial 与事务边界先出现 6 个预期 RED；GREEN 后 focused 260 项、API/MCP/schedule/reliability 邻接 228 项、Python compile、两个 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`）及 `git diff --check` 通过
- 结果：retry 成功转 queued 的同一事务清除该 Job application ledger 并断开 Health `last_job_id`，保留旧健康字段；新 attempt 可重新幂等写 Health，多订阅、外事务回滚与并发语义稳定；诊断不再用状态/时间猜代际
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 retry/Health attempt provenance；普通六工具与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第五轮独立审查的一个 Important
- 修改文件：JobQueue retry attempt-local 清理、真实 Worker/read/diagnostics 与事务回归、Task 7 主计划、R5 报告、`WORKLOG.md`
- 执行验证：两项专项先精确 RED，最小修复后 GREEN；focused 288 项、R4 邻接 238 项、full gate 22/22、Python compile、两个 JSON 和 diff 检查通过
- 结果：same-ID manual retry 在成功条件 UPDATE 中原子清除旧 `result_json/started_at`；queued/running 与第二 attempt pre-result failure 的普通 list/get、Job/Source diagnostics 均不再暴露旧 summary，下一 claim 重写当前开始时间
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 retry attempt attribution；普通六工具 shape、权限、active/rollback/concurrency 与 R4 Health provenance 不变

### 2026-07-18 Codex subagent
- 任务：实现 Task 8 的 14-tool Remote MCP 注册、严格输入、claim-derived actor、服务注入与安全错误/日志
- 修改文件：MCP typed models/server、API injection、真实 MCP HTTP 回归、Task 8 主计划/报告、`WORKLOG.md`
- 执行验证：初始 7 failed / 15 passed 精确 RED；最终 transport/diagnostics/Nginx 219 项、Task1/4–7 邻接 666 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 diff 检查通过
- 结果：14 工具顺序与 annotations 精确；全局 auth 保持 read，写权限由 proposal service 重验；prepare/apply、read-scope/flag-off、跨用户隔离、extra-forbid/Task1 config 安全和固定脱敏日志均由真实 Client 覆盖
- 未解决问题：Task 9+ UI/Skill、控制面合同、impact map、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅勾选既有 Task 8 执行状态；对外合同由后续统一文档任务更新

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 独立审查的一个 Important，统一业务函数前参数验证失败的安全错误与审计
- 修改文件：app-local MCP call-tool adapter、四类真实 Client 验证回归、Task 8 主计划、R1 修复报告、`WORKLOG.md`
- 执行验证：四类 validation 4/4 按预期 RED 后 GREEN；Task 8 transport/diagnostics/Nginx 223 项、Task1/4–7 邻接 666 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：外层/nested extra、错误 discriminator 与范围错误均只返回 `invalid_request`，每次精确一条固定七字段审计且输入/ValidationError 零泄漏；14 工具 schema/annotations/顺序、正常单日志与每 app 隔离保持不变
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 验证失败安全边界与执行证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 第二轮复审的 validation 绕过 delegation limiter Important
- 修改文件：app-local MCP limiter/adapter、真实 Client 与注入时钟回归、Task 8 主计划、R2 修复报告、`WORKLOG.md`
- 执行验证：5 个专项先 5/5 RED 后 GREEN；Task 8 focused/transport/diagnostics/Nginx 228 项、Task 1/4–7 更宽邻接 854 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：已认证已注册调用在预检前共享每 delegation `60/minute, burst 10`；validation/成功/业务错误各消费一次且每 call 恰好一条七字段日志；unauthenticated/unknown 不计费不审计，每 app 独立且零敏感泄漏
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 delegation limiter 执行顺序与证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 第三轮复审的 pre-parse 异常绕过稳定错误与审计 Important
- 修改文件：app-local MCP validation adapter、两类真实 Client pre-parse 回归、Task 8 主计划、R3 报告、`WORKLOG.md`
- 执行验证：ValueError/RecursionError 两项专项先 2/2 RED 后 GREEN；Task 8 focused/transport/diagnostics/Nginx 230 项、Task 1/4–7 邻接 854 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：超长整数与深嵌套 JSON 的 SDK pre-parse 异常统一为精确 `invalid_request`，每次恰好一次 bucket charge 与一条七字段日志，输入/异常零泄漏；成功路径仍委托 SDK
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 输入拒绝边界与执行证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：实现 Task 9 权限感知助手连接 UI
- 修改文件：Agent delegation 前端 types/service、AgentsPage 与专项单测、Task 9 主计划/报告、`WORKLOG.md`
- 执行验证：指定单测先出现 7 个预期 RED，最终 service/AgentsPage 11 项通过；AgentsPage 收紧精确 6/14 工具断言后 9 项通过；TypeScript typecheck 通过
- 结果：创建连接默认只读并显式提交 access；viewer 隐藏写选项、写开关关闭时禁用并说明；连接权限 Chip、一次性 `{token, access}` 清理和按连接权限复制无明文令牌配置完成
- 未解决问题：Task 10 Skill 与 Task 11 build/E2E/Axe/full gate、控制面合同、生产启用和真实 OpenClaw canary 尚未执行
- 控制面变更：仅同步既有 Task 9 执行状态与 Task 11 验收边界；本任务未修改 API/UI 权威合同

### 2026-07-18 Codex subagent
- 任务：实现 Task 10 OpenClaw 订阅管理 Skill、诊断与确认工作流
- 修改文件：本地 Skill、README、工具合同、工作流、focused 静态测试、Task 10 计划/报告与 `WORKLOG.md`
- 执行验证：先以 `.venv/bin/pytest tests/test_openclaw_skill.py -q` 得到 3 项预期 RED；文案收紧后同一单测 6/6 通过，frontmatter/diff 静态检查通过，`openclaw skills check` 通过（仅现有 duplicate-plugin 配置警告）
- 结果：Skill 覆盖精确 14 工具、八类来源别名/Apify-Web 边界、逐字段收集、existing source list-only、prepare→完整预览→精确确认→apply、显式删除选择、受限诊断与 secret refusal；仅 apply 成功后声明写入
- 未解决问题：Task 11 控制面合同、impact map、完整验收与真实 canary 尚未执行
- 控制面变更：将 Task 10 既有计划步骤标记完成；未更改服务端、前端或生产配置

### 2026-07-18 Codex subagent
- 任务：关闭 Task 10 独立审查的 access-specific OpenClaw toolFilter Important
- 修改文件：OpenClaw Skill README、focused 静态回归、`.superpowers/sdd/task-10-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：`.venv/bin/pytest tests/test_openclaw_skill.py -q` 7 项通过，`git diff --check` 通过
- 结果：viewer/read-only 配置精确限制为六个核心读工具；仅 Inteliscope Web 创建的 subscription-management 连接配置全部 14 工具；两种配置都只使用 `${INTELISCOPE_MCP_TOKEN}` 环境变量占位符
- 未解决问题：Task 11 控制面合同、impact map、完整验收与真实 canary 尚未执行
- 控制面变更：仅修正文档化的本地 OpenClaw toolFilter 与其静态不变量；未修改服务端、前端或生产配置

### 2026-07-18 Codex subagent
- 任务：完成 Task 11 Remote MCP 订阅管理控制面合同、影响映射与最终验收边界
- 修改文件：`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`UI_CONTRACT.md`、`DECISION_LOG.md`、`PLAN.md`、`tests/test_impact_map.json`、`.superpowers/sdd/task-11-report.md` 与 `WORKLOG.md`
- 执行验证：`python` 在该 worktree 不存在；唯一一次等价 `python3 scripts/test_gate.py plan --json` 因没有 snapshot 或 `--base/--head` 输入而未生成选择计划。`project-defaults.yaml` 与 impact map JSON lint、`git diff --check` 均通过；按本任务限制未运行 pytest、Node、build、performance benchmark、full gate 或真实 OpenClaw canary
- 结果：合同现在覆盖 read/write delegation access/scopes/flag、精确 14-tool 输入边界/annotation、服务端 prepare→confirm→apply lifecycle、诊断 shape 与稳定错误；架构确认共享 mutation/proposal/diagnostics ownership、stateless MCP 与无内部 HTTP；助手连接 UI 记录 access 选择、viewer 限制、capability Chip 与权限 toolFilter；impact map 将 proposal/mutation、Remote MCP/Skill 与 focused suites 路由到 API/store。
- 未解决问题：本地 100-call performance acceptance 与真实 OpenClaw synthetic/free-data canary 均未运行；生产仍需 backup、API-only staging（写 flag 关闭）、TLS Authorization forwarding、read/write canary、revoke 401、两用户隔离及明确 flag enablement。
- 控制面变更：新增 D025；Remote MCP 订阅写入不再是非目标，但密钥/共享来源/任务和 Feed 状态管理仍不通过 MCP 开放；回滚只关闭 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`。

### 2026-07-18 Codex
- 任务：执行用户要求的唯一一次最终完整门禁，并记录本地完成证据
- 修改文件：`.superpowers/sdd/task-11-report.md`、`WORKLOG.md`
- 执行验证：`.venv/bin/python scripts/test_gate.py run --mode full` 22/22 commands 通过，0 failed/error，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 97.402 秒
- 结果：本地实现、前后端、Skill、合同和影响映射通过统一完成门禁；没有重复运行 full gate
- 未解决问题：100-call 独立性能基准与真实 OpenClaw canary 未执行，生产 staging/TLS/revoke 401/两用户隔离/显式开关授权仍是发布边界
- 控制面变更：仅记录最终验证证据；未启用任何生产 feature flag

### 2026-07-18 Codex
- 任务：收口 OpenClaw Remote MCP 只读生产发布、诊断合同、canary 与 API-only Runbook
- 修改文件：助手连接 10/14 toolFilter、OpenClaw Skill/合同、env/Compose/Nginx 文档、只读 canary、发布 Runbook、影响映射与控制文件
- 执行验证：专项 pytest 28 项、AgentsPage 9 项通过；100-call MCP p95 7.451 ms、REST p95 1.094 ms、RSS +0.812 MiB；唯一一次 release gate 因 worktree 缺少忽略的 `data/config.json` 中止，补齐后原失败用例通过，未重跑 release gate
- 结果：read connection 精确开放 10 个安全读/指导/诊断工具，write connection 保持 14 个且生产写 flag 默认关闭；canary 覆盖全部安全读、双用户隔离、禁写与吊销 401
- 未解决问题：release gate 尚无通过结论；真实 OpenClaw、独立 staging、生产 TLS/canary/切换及 24 小时观察尚未执行
- 控制面变更：Remote MCP 权威合同改为 10 安全读 + 4 写流程，生产只读边界固定保留 additive v6/v7 且不启动 Worker/Agent/模型

### 2026-07-18 Codex
- 任务：执行 OpenClaw MCP 合并与只读生产发布前的最后一次门禁
- 修改文件：API-only 发布 Runbook、Runbook 静态测试与 `WORKLOG.md`；恢复 OpenClaw approvals 并清理临时 profile
- 执行验证：Runbook 专项按预期 RED 后 GREEN；release gate 22/23 commands 通过，唯一失败为 Playwright 4 项，原因是 worktree `node_modules` 软链接位于 Vite allow list 外导致本地字体请求被拒绝
- 结果：已删除临时 `data/config.json`/`frontend/node_modules` 软链接；按批准的最终门禁硬边界停止，未合并、未构建镜像、未修改 staging/Nginx/生产容器或数据库
- 未解决问题：release gate 无通过结论；后续合并、staging、双用户 canary、生产切换与 24 小时观察保持阻塞，除非用户另行授权新的验证方案
- 控制面变更：Runbook 现在要求备份前同时停止 API/Worker、staging 独立日志，并仅增量修改线上 `cfl.conf`

### 2026-07-19 Codex
- 任务：实现浏览器直连用户自有 OpenClaw Gateway 的对话面板，并扩展 Remote MCP 文章正文分段读取
- 修改文件：OpenClaw Gateway v4 客户端、IndexedDB 设备凭证库、对话 hook/UI、文章上下文、助手连接页、Shell/Feed 集成、MCP 配置与 `get_item`、Skill、CSP/Compose/env、权威合同、影响映射和专项/E2E 测试
- 执行验证：后端相关 94 项、前端 36 files / 238 项、TypeScript typecheck、ESLint（0 error，5 个既有 Fast Refresh warning）、UI contract、生产 build 均通过；release gate 22/23 commands 通过，唯一失败为旧 E2E 文案/抽屉交互断言；修正测试后精确三视口 Playwright 3/3 通过，按约束未重跑 release gate
- 结果：功能默认关闭；启用后 Chromium 可直连 loopback `ws://` 或远端 `wss://` Gateway，完成 v3 设备签名、严格 `operator.read + operator.write` 权限校验、本地隔离存储、历史/流式/停止/重连/工具发现；文章上下文只发送 ID，`get_item` 最多三段恢复 20,000 字符已存正文；功能关闭继续保留复制模式
- 未解决问题：release gate wrapper 本身仍为失败结论；真实 OpenClaw 独立 profile 配对、本地/staging 双用户验收、生产开关与 24 小时观察尚未执行，订阅写入生产 flag 仍关闭
- 控制面变更：新增 D035，正式以浏览器 Gateway 对话替代“站内不连接 OpenClaw”边界；服务器继续无 Agent、无模型、无 Gateway 代理，生产默认不开启对话或订阅写入

### 2026-07-17 10:17 Codex
- 任务：实现 HeroUI v3 独立工作台视觉原型，与现有 MUI 原型进行同数据、同布局和同交互对照
- 修改文件：新增开发专用 `/__preview/workbench-heroui`、HeroUI 复合卡片与响应式三栏样式、共享预览数据模型、入口隔离和生产包排除检查；更新 MUI 版本切换、UI/计划/决策合同与测试
- 执行验证：UI contract 通过；ESLint 0 error（保留既有 Fast Refresh warning）；TypeScript 通过；Vitest 27 个文件共 111 项通过；Vite 生产构建与 HeroUI 排除检查通过；MUI/HeroUI 三视口 Playwright+Axe 9 项通过；最终 `test_gate full` 22/22 命令通过、`mapping_miss=false`、48.427 秒；1440×900 人工检查显示 5 张完整卡片，无横向溢出
- 结果：HeroUI 路由在应用根入口提前分流，不进入 MUI、认证、Query Client、API 或生产全局 CSS；实现卡片展开、收藏、搜索、短刻度、新内容、最多 8 条 Agent 上下文和确定性交接复制；平板覆盖面板、手机 Bottom Sheet、Escape/关闭按钮焦点归还和 Reduced Motion 均已验证
- 未解决问题：当前仍为固定净化数据的视觉原型；等待用户与 MUI 版对比确认后，才决定是否采用 HeroUI 生产迁移或仅提取视觉语言
- 控制面变更：新增 D026；UI_CONTRACT 明确 HeroUI 原型边界、组件要求、生产排除与视觉验收门禁

### 2026-07-17 10:56 Codex subagent
- 任务：实现 Remote MCP 八类来源的双语配置指引与安全输入规范化
- 读取文件：`AGENTS.md`、任务 brief、source type registry 与相关测试
- 修改文件：`src/services/source_type_registry.py`、来源 registry/setup guidance 测试、`WORKLOG.md`
- 执行验证：新增测试先因缺少接口失败；focused 8 项通过；`test_gate` full 成功
- 结果：新增中英 setup guide、公开 URL/别名规范化和凭据/敏感 RSS 查询拒绝，REST registry 投影保持不变
- 未解决问题：无
- 控制面变更：无

### 2026-07-17 11:46 Codex
- 任务：建立 HeroUI 正式设计系统与应用 bootstrap 边界，不迁移业务页或移除 MUI
- 修改文件：新增 `frontend/src/design-system/**`、Router bridge 与静态导入契约测试；更新 `AppBootstrap`、UI/Decision 合同和全站迁移计划
- 执行验证：TDD RED→GREEN；最终 Vitest 29 文件/116 项、UI contract、TypeScript、Vite build 与 preview exclusion 通过；ESLint 0 error、保留既有 1 warning
- 结果：正式业务只能经 design-system 使用 HeroUI；固定数据原型保留直接导入例外；QueryClient、认证、ServiceApi 与现有 MUI 页面边界不变
- 未解决问题：既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning 不属于本任务
- 控制面变更：新增 D027；UI_CONTRACT 固化 HeroUI 生产迁移边界与渐进 bootstrap

### 2026-07-17 12:01 Codex
- 任务：修复 Task 1 评审发现的 HeroUI 有效圆角和动效时长越界
- 修改文件：`frontend/src/design-system/theme.css`、`frontend/e2e/design-system-contract.spec.ts`、Task 1 报告
- 执行验证：真实 Vite+Tailwind 编译 CSS 的浏览器 computed-style 测试完成 RED→GREEN；最终 Vitest 29 文件/116 项、UI contract、TypeScript、build/preview exclusion 与定向 Playwright 2 项通过，ESLint 0 error
- 结果：Tabs/Table/溢出控件圆角固定为 14/16/8px；正式主题内 transition/animation 固定为 160/220ms，Toast view transition 同步覆盖，Reduced Motion 保持 1ms
- 未解决问题：保留既有 Fast Refresh warning 与 Vite 500 kB chunk warning
- 控制面变更：无；仅修正既有 D027 主题实现偏差

### 2026-07-17 12:17 Codex
- 任务：修复 Task 1 二次评审发现的 HeroUI Portal 主题逃逸与全局动效覆盖
- 修改文件：`frontend/src/design-system/DesignSystemProvider.tsx`、`theme.css`、设计系统 Playwright 契约与隔离 fixture、Task 1 报告
- 执行验证：真实 Modal/Tooltip 与连续动画 computed-style 测试完成 RED→GREEN；Vitest 29 文件/116 项、UI contract、TypeScript、build/preview exclusion、Playwright 5 项通过；full gate 22/22 通过、`mapping_miss=false`，ESLint 0 error
- 结果：正式 provider 以引用计数同步并精确恢复文档根主题；有限动效改为组件级选择器，静态元素不新增动效，Skeleton/Spinner 保留连续节奏，Portal Reduced Motion 生效
- 未解决问题：保留既有 Fast Refresh warning 与 Vite 500 kB chunk warning
- 控制面变更：无；仅修正既有 D027 主题实现偏差

### 2026-07-17 13:00 Codex
- 任务：实现 HeroUI 正式核心工作台、虚拟信息流与本地 OpenClaw Agent 上下文交接
- 修改文件：新增 `frontend/src/features/workbench-live/**`、真实 API 开发验收路由和三视口 Playwright；提取共享乐观更新、增加 Feed v2 偏好/稳定排序/Agent session 清理，并安装精确版本 `@tanstack/react-virtual@3.14.6`
- 执行验证：TDD RED→GREEN；UI contract、TypeScript、Vite build/preview exclusion 通过；ESLint 0 error（保留既有 1 warning）；Vitest 33 文件/138 项、三视口 Playwright/Axe 3 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、56.39 秒
- 结果：开发专用认证路由 `/__preview/workbench-live` 已接真实 ServiceApi，实现 Feed/收藏/历史统一卡片、动态虚拟列表、深链降级、筛选、刷新反馈、权限与回滚、响应式 Agent 面板及确定性交接；MUI 仍为生产默认，固定数据 HeroUI 原型未变，Task 3 页面未迁移
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换等待 Task 4
- 控制面变更：无；复用现有 API、查询键、权限、Remote MCP 和 ActionGeneration 合同，仅新增开发验收入口

### 2026-07-17 14:23 Codex
- 任务：修复 Task 2 评审发现的 legacy 路由、详情合并、筛选、虚拟流锚点/新内容、Agent Drawer 与 loading 状态问题
- 修改文件：`App` 路由/回归测试、Feed/workbench 模型与虚拟列表、HeroUI Shell、design-system portal foreground、三视口 Playwright、Task 2 报告
- 执行验证：定向 Vitest 4 文件/34 项、全量 Vitest 33 文件/148 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、Portal 契约 1 项、三视口 Playwright/Axe 3 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、68.966 秒
- 结果：保留生产 `/later`；inline `?item=` 不再 remount/跳中；详情始终获取并合并 v2；深链穿透筛选；固定窗口按 ID 识别新内容；窄屏使用受控 HeroUI Drawer，delegation 加载显示中性状态，Portal 统一继承主题前景色
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；仅修复既有 D027/Task 2 实现偏差

### 2026-07-17 14:53 Codex
- 任务：修复 Task 2 二次评审发现的异步 404 误清理、失效初始深链定位、筛选钉选顺序、滚动窗口锚点、Agent loading 文案与桌面关闭空栏问题
- 修改文件：`HeroWorkbenchPage`、`VirtualFeed`、`HeroWorkbenchShell`、App/三视口 Playwright 回归、Task 2 报告与实施计划
- 执行验证：focused Vitest 23 项、全量 Vitest 33 文件/150 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、Portal 契约 1 项、三视口 Playwright/Axe 6 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、57.375 秒
- 结果：404 仅在 active source 成功且确证缺失后清理；真实缺失深链回到底部区；筛选钉选保持时序；固定长度窗口严格保持 top-visible ID 与 ≤2px 相对偏移；桌面 Agent 关闭卸载 360px 空栏并保持 Feed，loading 只显示 skeleton busy 状态
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；未修改 backend/API/query key/权限/Remote MCP/MUI 与 Task 3 边界

### 2026-07-17 15:22 Codex
- 任务：修复 Task 2 三次评审发现的 cached-success 404 竞态、pin/unread-first 排序与过滤态虚拟 fallback 索引问题
- 修改文件：`HeroWorkbenchPage`、`VirtualFeed`、App/三视口 Playwright 回归与 Task 2 报告
- 执行验证：三项 focused RED→GREEN；全量 Vitest 33 文件/152 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Playwright/Axe 9 项均通过；最终 `test_gate full` 22/22、`mapping_miss=false`、53.140 秒
- 结果：404 仅在 active source 成功且停止 fetching 后确证缺失；钉选详情绕过排除筛选但保持 unread-first 稳定分组；未挂载锚点按 `props.cards` 的真实虚拟顺序恢复并严格保持 ID/≤2px 偏移
- 未解决问题：保留既有 `ActionFeedback.tsx` Fast Refresh warning 与 Vite 500 kB chunk warning；正式生产切换仍等待 Task 4
- 控制面变更：无；未修改 backend/API/query key/权限/Remote MCP/MUI 与 Task 3 边界

### 2026-07-17 16:10 Codex
- 任务：实现 Task 3 的 HeroUI 订阅、助手连接、设置与登录 DEV 验收页面
- 修改文件：新增 `frontend/src/features/admin-heroui/**` 与 `live-admin.spec.ts`，扩展 live 路由/Shell、design-system facade/theme、App 回归测试与 Task 3 报告
- 执行验证：focused RED→GREEN；Vitest 33 文件/158 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`
- 结果：复用现有 API/query key/权限/模型完成三标签订阅、Worker/任务、一次性 Agent 令牌、角色化设置/SecretStore 与登录；非工作台页面全宽且无 Agent，MUI/生产默认未变
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；一次合并 Playwright 并发运行触发既有移动端锚点波动，原用例隔离重跑通过
- 控制面变更：无；HeroUI 页面仍为 DEV-only，未修改 backend/API/Remote MCP/生产路由

### 2026-07-17 17:09 Codex
- 任务：修复 Task 3 评审发现的来源获取生命周期、成员角色编辑、运行时间字段、覆盖缺口与高级来源编辑器问题
- 修改文件：HeroUI 订阅/设置/来源表单、ActionFeedback、App/权限/响应结构测试、测试环境兼容层、Task 3 报告与本工作日志
- 执行验证：focused 3 文件/51 项、全量 Vitest 34 文件/173 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、57.642 秒
- 结果：单源获取恢复 queued→running→terminal 与终态失效/安全反馈；Owner/Admin 可编辑非 Owner 角色；运行时间拆分；筛选、权限、结构状态和登录具备行为覆盖；高级编辑器改用设计系统 Fieldset
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/权限函数/Remote MCP/生产路由

### 2026-07-17 17:31 Codex
- 任务：修复 Task 3 复评发现的 Hero 订阅实体级 mutation 反馈与来源获取通知关闭/超时问题
- 修改文件：新增 `HeroActionNotice` 及 fake-timer 测试，更新 Hero 订阅页、App 行为测试、Task 3 报告与本工作日志
- 执行验证：focused 4 文件/60 项、全量 Vitest 35 文件/182 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、60.132 秒
- 结果：schedule/subscribe/unsubscribe/retry 复用 ActionFeedback 实现实体级 pending/错误/成功状态与重复请求抑制；Hero 本地 live region 保证错误可见；来源通知支持手动关闭及 4/8 秒自动关闭，同终态轮询不重开也不重置计时
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/权限函数/Remote MCP/生产路由

### 2026-07-17 17:45 Codex
- 任务：修复 Task 3 复评发现的 mutation API 成功后、查询失效完成前提前解锁竞态
- 修改文件：Hero 订阅页四类 mutation 成功回调、App 全家族 invalidation-pending 回归、Task 3 报告与本工作日志
- 执行验证：可信 RED→GREEN（API 已完成、19 次 `invalidateQueries` 挂起）；focused 4 文件/61 项、全量 Vitest 35 文件/183 项、UI contract、lint 0 error、TypeScript、build/preview exclusion、三视口 Admin Playwright/Axe 6 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`
- 结果：schedule/subscribe/unsubscribe/retry 在既有 query invalidation promise 完成前持续保留实体级 pending/禁用状态，并继续抑制重复提交；仅刷新后发布成功和解锁
- 未解决问题：保留既有 Fast Refresh 与 Vite chunk warning；HeroUI 页面仍为 DEV-only
- 控制面变更：无；未修改 backend/API/query key/失效范围/权限函数/Remote MCP/生产路由

### 2026-07-17 20:15 Codex
- 任务：完成 Task 4 HeroUI 全站生产切换、旧 MUI/Emotion 双栈清理与完整门禁
- 修改文件：生产 bootstrap/路由、Hero Shell/虚拟 Feed、ActionFeedback、固定 Hero preview、静态 UI/构建产物检查、三视口 production E2E；删除 MUI 页面、`frontend/src/ui/**`、MUI 原型/CSS/快照与依赖；更新 UI/计划/决策合同和测试影响映射
- 执行验证：TDD 覆盖生产路由/provider/依赖/侧栏/静态契约/刷新锚点/显式导航；UI contract、lint 0 warning/error、TypeScript、Vitest 28 文件/154 项、build/artifact、Playwright/Axe 36/36 通过；移动过滤锚点 20x/5-worker 压力 20/20；Python API 69 项；`test_gate full` 22/22、`mapping_miss=false`、49.076 秒
- 结果：HeroUI 成为唯一生产 UI；`/feed|saved|history` 使用工作台，admin/settings/login 使用 Hero 页面，`/later` 替换至 `/saved`；固定 `/__preview/workbench-heroui` 继续 DEV-only 且生产剔除；MUI/Emotion 与旧页面完全删除
- 未解决问题：仅保留 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：新增 D028；`UI_CONTRACT.md` 重写为唯一视觉真源，PLAN/影响映射改为引用与当前 Hero 路径；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 21:49 Codex
- 任务：修复 Task 4 评审发现的 rendered-order 锚点、导航 ownership、UI/产物门禁与 saved/history/later 验收缺口
- 修改文件：`VirtualFeed`/筛选面板、生产路由单测与三视口 Playwright、UI source/artifact checker、固定 preview marker、Task 4 报告与本工作日志
- 执行验证：四组 focused RED→GREEN；UI contract、lint 0 error/warning、TypeScript、Vitest 28 文件/160 项、build/artifact、三视口 Playwright/Axe 48/48、移动锚点 20x/5-worker 压力 20/20、Python API 69 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、65.117 秒；`git diff --check` 通过
- 结果：rendered cards 成为唯一滚动恢复边界，raw source 不再重复恢复；所有显式导航/用户取消统一释放 refresh/restoration/inline timer+RAF ownership；business CSS/CSS Module 与固定 preview 产物绕过被封堵，MUI 检测不再误报无关 `Mui` 子串；`/saved`、`/history`、`/later` 真实集合路由具备生产验收
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:08 Codex
- 任务：关闭 Task 4 二次评审中的刷新/轨道导航同事件循环竞态，并把 UI/产物负向测试升级为真实不可绕过执行门禁
- 修改文件：`VirtualFeed` 与生产竞态 Playwright；UI source/artifact checker；固定 preview fixture 运行时 marker；可执行 Vitest 负向用例；Task 4 报告与本工作日志
- 执行验证：真实负向门禁 2 文件/21 项、竞态三视口 3/3、全量 Vitest 28 文件/166 项、UI contract、lint 0 error/warning、TypeScript、build/artifact、三视口 Playwright/Axe 48/48、Python API 69 项通过；最终 `test_gate full` 22/22、`mapping_miss=false`、50.462 秒；`git diff --check` 通过
- 结果：显式导航统一清除旧 viewport fallback，刷新响应在 rail click 后 microtask 内返回也不能抢回旧锚点；真实 Vite preview-story bundle、`.Mui-disabled` 产物、动态 CSS Module 与现代 CSS 色彩均由实际 checker 失败，负向覆盖不再依赖源码字符串或可独立 tree-shake 标记
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或正式门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:44 Codex
- 任务：修复 Task 4 终审发现的列表缩短后 progress rail 待导航索引没有同步截断，导致后续卡片更新可能重新抢占滚动位置
- 修改文件：`VirtualFeed`、导航纯函数及其 Vitest、生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：RED→GREEN 导航索引截断测试；关键桌面竞态 4/4；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright、Python API 69 项、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：高索引 rail target 在 200→50 收缩时写回真实末项索引；抵达后可释放 ownership，后续 dismissed 卡片更新不会跳回旧目标
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 23:58 Codex
- 任务：关闭 Task 4 第四审中 cards commit 与下一帧之间用户取消无法阻止 pending-navigation RAF 回写的竞态
- 修改文件：`VirtualFeed`、生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：真实 RAF gate RED（旧实现 wheel 后回跳至 scrollTop 7231）→GREEN；关键桌面竞态 2/2；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright 54 scheduled（50 pass/4 desktop-only skip）、Python API 69 项、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：release 路径会取消 cards commit 的 pending RAF，回调亦校验仍持有同一导航对象；缩短列表回归改用 Shell 搜索触发后续 cards update，不再借由卡片 pointer action 隐式释放
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-17 Codex subagent
- 任务：修复 Task 1 Agent setup 公共类型与输入安全审查项
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`WORKLOG.md`
- 执行验证：先验证公共八类/敏感 query value 回归为 RED；focused 37 项通过，`./.venv/bin/python scripts/test_gate.py run --mode full` 通过
- 结果：Agent guide 固定为 `rss/telegram/github/reddit/twitter/website/youtube/apify`，显式映射至 catalog 类型；REST 投影不变；拒绝所有 URL userinfo/敏感 query、嵌套凭据形状、非标量字段、Telegram 私邀和畸形 URL
- 未解决问题：后续 Task 3 消费 normalization 时应读取其 `catalog_source_type/config` 结构，而非把公共类型直接写入 catalog
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第二轮复审的六项来源规范化安全与执行策略缺口
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：新增回归先出现 66 个预期失败，自审补充 mapping key 回归再确认 1 个预期失败；focused 119 项通过，Python compile 通过，full gate 22/22 通过且 `mapping_miss=false`，`git diff --check` 通过
- 结果：复合敏感 query/header/assignment 和 source type 错误均安全失败；YouTube/Reddit identity 严格规范化；自助来源显式携带 create policy，Twitter/Apify 仅返回 existing-visible lookup identity
- 未解决问题：后续 service 消费方须使用新的 policy-bearing normalization shape；本 Task 未实现 proposal/MCP/UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第三轮复审的四项 Important 与 guide summary Minor
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：review 回归先按预期覆盖五组 RED，自审的 GitHub 双斜杠 identity 再单独 RED；focused 197 项、Python compile、full gate 22/22（`mapping_miss=false`）和 `git diff --check` 通过
- 结果：凭据检测按 query name/value/free text 分层并先做 NFKC；RSS/website 输出强制公网 policy 且本地拒绝 localhost/非公网 IP literal；GitHub/YouTube identity 使用离线真实语法；Apify 仅接收 lookup identity；guide summary 补齐 `required_fields`，旧 REST 投影不变
- 未解决问题：Task 3 必须无视 owner/admin 放宽逻辑，按 `policy.public_network_only=true` 绑定既有逐跳 DNS pinning 公网执行路径；本 Task 未修改 runner/proposal/MCP/UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第四轮复审的四项 Important
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：四组回归先出现 33 个预期失败，Telegram 边界自审再确认 4 个预期失败；focused 246 项、Python compile、full gate 22/22（`mapping_miss=false`）和 `git diff --check` 通过
- 结果：凭据安全副本加入有界 percent decode 与 Unicode ignorable 折叠；RSS/website 拒绝历史 IPv4 本地地址；GitHub clone `.git` 规范化；Telegram query/fragment 与保留路由失败关闭
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第五轮复审的单项 Important（percent-escaped hostname）
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r5-report.md`、`WORKLOG.md`
- 执行验证：新增 10 个 RSS/website percent-escaped hostname 与 IPv6 zone-id 回归先均为 RED；focused 256 项、Python compile、full gate 和 `git diff --check` 通过
- 结果：主机名含 `%` 在公网 literal 分类前以固定非回显错误失败关闭；普通数字标签域名和 `policy.public_network_only=true` 回归保持
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 1 第六轮复审的单项 Important（反斜杠 authority）
- 修改文件：`src/services/source_type_registry.py`、`tests/test_source_setup_guidance.py`、`.superpowers/sdd/task-1-fix-r6-report.md`、`WORKLOG.md`
- 执行验证：RSS/website 反斜杠 authority 回归先均为 RED；focused 258 项、Python compile、full gate 和 `git diff --check` 通过
- 结果：公网 literal 分类前拒绝 authority/hostname 中的反斜杠，使用固定非回显错误；普通域名、numeric-label 域名与 `policy.public_network_only=true` 回归保持
- 未解决问题：Task 3 仍须按 `policy.public_network_only=true` 绑定既有逐跳公网执行路径；本 Task 未修改执行代码
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 schema v7 Agent 变更提案持久化、保留清理与部署数据库脱敏
- 修改文件：`src/storage/service_store.py`、`src/services/maintenance.py`、`scripts/prepare_service_deployment.py`、proposal/maintenance/deployment 测试、Task 2 报告、`WORKLOG.md`
- 执行验证：proposal 测试先出现 17 个预期 RED，自审补充未知 JSON 对象失败关闭再确认 1 个 RED；focused 27 项通过，full gate 22/22 通过且 `mapping_miss=false`，Python compile 与 `git diff --check` 通过
- 结果：新增 v7 additive proposal 表、级联外键/索引/marker、10 分钟 TTL 与 delegation 原子 pending 上限、安全 JSON 投影/写入、30 天维护清理、旧库兼容部署清空，以及 `create_source(commit=False)` 事务支持
- 未解决问题：Task 3+ 仍需在外层 `BEGIN IMMEDIATE` 中消费 `commit=False` 接口并完成业务 apply；本任务未实现 mutation service、MCP 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 复审的两个 Important（权威 proposal 时钟与 camelCase/NFKC 敏感键）
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`tests/test_maintenance.py`、`.superpowers/sdd/task-2-fix-report.md`、`WORKLOG.md`
- 执行验证：8 个针对性回归先按预期 RED；focused 36 项通过；full gate 22/22 通过且 `mapping_miss=false`；Python compile 与 `git diff --check` 通过
- 结果：create/apply 生命周期改用事务内权威 UTC now，调用参数只保留兼容校验；固定持久化 now/now+10m，未来/回填时间不能绕过配额或过期；敏感键先 NFKC/camelCase 拆词，安全业务 ID shape 保持允许
- 未解决问题：无；未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第二轮复审的 compact 敏感键 Important 与自由文本误拒 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：新增回归先出现 25 个预期 RED；proposal 56 项、focused 69 项、full gate 22/22（`mapping_miss=false`）通过；`git diff --check` 通过
- 结果：JSON/query 共用受控 compact credential key 分类并覆盖 NFKC/percent decode；明确凭据 header/assignment、已知 prefix 与 JWT 仍拒绝，`Basic Engineering News`、`Bearer Market Report` 和 `monkey`/`hockey` 等安全词允许
- 未解决问题：无；未修改权威时钟、事务、schema、cleanup、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第三轮复审的 compact credential 后缀 Important 与短 `sk-` 名称 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：新增 12 个回归先按预期 RED；proposal 与指定 focused 测试通过，full gate 通过，`git diff --check` 通过
- 结果：NFKC/camelCase/分隔归一后的 compact key 以受控 credential 后缀失败关闭，JSON 与 percent-decoded query 统一覆盖；`sk-` 仅在长连续 token 且右边界时拒绝，`SK-Engineering Weekly` 保持允许
- 未解决问题：无；未改动 schema、时钟、事务、retention、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 2 第四轮复审的字符串值编码绕过 Important 与长 `sk-` 业务标题误拒 Minor
- 修改文件：`src/storage/service_store.py`、`tests/test_agent_change_proposals.py`、`.superpowers/sdd/task-2-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：三轮回归分别出现 9、2、1 个预期 RED；proposal 86 项、指定 focused 99 项、Python compile 与 full gate 22/22（`mapping_miss=false`）通过，提交前重跑 `git diff --check`
- 结果：所有 proposal 字符串值使用 16 KiB、NFKC、最多两轮 percent-decode 的非持久化分类副本，query name/value 同步覆盖且安全 `%20` 原值不变；真实形态 `sk` 假 token 继续拒绝，两个指定长业务标题允许
- 未解决问题：无；未改动 key suffix、schema、权威时钟、事务、retention、sanitizer，未实现 Task 3+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现共享订阅变更领域服务并让现有 REST mutation 复用
- 修改文件：`src/services/subscription_mutation.py`、`src/api/server.py`、`src/storage/service_store.py`、RSS 执行投影、Task 3/API 测试、`.superpowers/sdd/openclaw-task-3-report.md`、`WORKLOG.md`
- 执行验证：初始 module、REST context、metadata/config credential 与内部标记投影均先按预期 RED；领域 36 项、指定 focused 165 项、store/config/Worker 43 项、full gate 和 `git diff --check` 通过
- 结果：typed plan/error/actor、Agent private-only planner、安全 preview/指纹、显式 delete disposition、原子 create/update/delete 与完整回滚已实现；REST admin/member/viewer 和 omission/null/list clear 合同保持；Agent RSS/website 公网执行选择持久且 owner/admin 不可绕过
- 未解决问题：Task 4+ 仍需在 proposal 转换事务内消费本服务，并继续隐藏内部公网标记；本任务未实现 proposal orchestration、MCP、delegation flag/scope、新 REST endpoint 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 独立复审的五项 Important
- 修改文件：订阅变更领域服务、来源公开投影/runner、quota、media cleanup、相关 focused 测试、`.superpowers/sdd/task-3-fix-report.md`、`WORKLOG.md`
- 执行验证：计划密封、RSS 公网 marker、quota re-enable、头像 late rollback、安全 preview 与 cleanup collector 回归均先按预期 RED；Python compile 和 focused 452 项通过；full gate 22/22（`mapping_miss=false`）及 `git diff --check` 通过
- 结果：确认后的 normalized plan 使用 canonical snapshot 且 apply 不再重规范化；Agent RSS 更新/runner fallback 均维持公网执行；来源重启用先做 quota admission；头像仅在 owner commit 后物理清理，`commit=False` 缺 collector 失败关闭；遗留不安全 catalog preview 返回稳定 opaque summary
- 未解决问题：Task 4+ 外层事务调用 `apply_plan(commit=False)` 时必须显式传入 cleanup collector，并在 commit 后执行、rollback 时丢弃；本任务未实现 Task 4+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 修正后复审的五项 Important
- 修改文件：订阅变更 plan/restore、quota、media cleanup、来源公开元数据分类器、相关 focused 测试、`.superpowers/sdd/task-3-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：五组回归先按预期 RED；Python compile 与 focused 484 项通过；full gate 22/22（`mapping_miss=false`、`ui_impacted=false`）、默认配置 JSON 校验及 `git diff --check` 通过
- 结果：planner/restore/apply 共用严格版本化 invariant builder；subscription 幂等与 source re-enable admission 分离；外层事务缺 cleanup collector 在 mutation 前失败关闭；公开投影覆盖嵌入式常见 token 且保留安全 Bearer 标题；schedule preview 展示 existing 合并态或 new 默认态
- 未解决问题：Task 4+ 外层事务调用 mutation service 时须显式传 collector，commit 后执行、rollback 时丢弃；本任务未实现 Task 4+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第三轮复审的两个 Important
- 修改文件：共享安全分类器、来源公开投影/metadata、proposal sanitizer、snapshot consumer 计划、三组合同测试、`.superpowers/sdd/task-3-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：Task 3/Task 2 新回归分别先出现 9/10 个预期 RED，`xox*` 扩展再确认 1 个 RED；focused 591 项、Python compile、full gate 22/22（`mapping_miss=false`、`ui_impacted=false`）、默认配置 JSON 校验及 `git diff --check` 通过
- 结果：Task 1/2 共用 16 KiB、NFKC、最多两轮 percent decode 的上下文凭据分类器并覆盖 query value/fragment/known prefixes；metadata parser 异常固定失败关闭；Task 5/6 计划固定为完整 versioned snapshot + restore + outer collector 生命周期，真实 proposal row seam 已验证 commit/run 与 rollback/discard
- 未解决问题：Task 5/6 仍待按已同步合同实现 proposal/MCP 业务；本任务未重开 public constructor 或实现后续业务
- 控制面变更：同步实施计划中的既有 Task 3/5/6 内部接口示例，无对外 API 变更

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第四轮复审的两个 Important
- 修改文件：Agent 来源反向规范化、订阅变更 plan/restore/apply、Task 3/5/6 内部接口计划、三组合同测试、`.superpowers/sdd/task-3-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：反向规范化回归先出现 9 个预期失败，update 共享校验再出现 3 个预期失败；schedule final-state 回归先出现 28 个预期失败；focused 657 项通过，Python compile、默认配置 JSON 校验、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：八个公开 Agent 类型均以 forward normalizer 做确定性反向校验并要求精确相等；update plan 携带 source/subscription/schedule 合并后的完整最终 schedule，禁用级联明确预览，同一计划对 disabled target 显式启用 schedule 在 prepare 阶段稳定拒绝；restore/apply 共用绑定并在 apply 后核对实际最终 schedule；snapshot 升级为 v2，v1 失败关闭且须重新 prepare
- 未解决问题：Task 5/6 仍待按已同步的 v2 snapshot 合同实现 proposal/MCP 业务；本任务未实现后续业务、迁移或兼容 fallback
- 控制面变更：同步实施计划中的 Task 3/5/6 内部 snapshot 版本与消费者合同，无对外 API 变更

### 2026-07-17 Codex subagent
- 任务：关闭 Task 3 第五轮复审的两个 Important 与一个 Minor
- 修改文件：create/upsert 最终 schedule plan/restore/apply、quota final-active admission、Task 3 brief、mutation/API 回归、`.superpowers/sdd/task-3-fix-r5-report.md`、`WORKLOG.md`
- 执行验证：21 个 create/quota 回归先出现 13 个预期失败，GREEN 后补充 forged snapshot/live binding 2 项；12 文件 focused 693 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）与 `git diff --check` 通过
- 结果：create/upsert 与 update 共用最终 schedule 计算，final disabled subject 的显式 schedule enable 在 prepare 拒绝，sealed preview 与 apply 实态不一致会回滚；quota 仅对最终 inactive→active 转换 admission，真实 source re-enable 仍独立检查；brief 同步 v2/v1 fail-closed/reprepare
- 未解决问题：Task 5/6 仍待按既有 v2 snapshot 合同实现 proposal/MCP 业务；本任务未实现后续业务、迁移或兼容 fallback
- 控制面变更：仅同步忽略目录中的 Task 3 scratch brief，无对外 API 或主实施计划变更

### 2026-07-17 Codex subagent
- 任务：实现 delegation 显式订阅写权限与独立默认关闭功能开关
- 修改文件：delegation store/API、Remote MCP 配置、三组 focused 测试、`.superpowers/sdd/openclaw-task-4-report.md`、`WORKLOG.md`
- 执行验证：required focused 先出现 17 个 RED，修正测试夹具后确认目标 RED；GREEN 32 项、相关 TokenVerifier/store 回归 113 项、full gate 22/22（`mapping_miss=false`）通过，提交前重跑 diff/JSON 检查
- 结果：新增 read/write canonical scope 与安全 access 投影；旧行不迁移，未知/额外 scope 失败关闭；写开关严格 `true|false` 且依赖 Remote MCP；GET/POST/PATCH 权限、viewer 稳定 403 和 rename 防升级完成
- 未解决问题：Task 8 写工具仍须在每次调用时检查 live flag；本任务未实现 proposal、MCP 写工具、UI 或生产启用
- 控制面变更：无；总方案后续文档任务统一更新 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：修复 Task 4 delegation scope 损坏值导致的 GET/TokenVerifier 异常
- 修改文件：`src/storage/service_store.py`、delegation/API/真实 MCP 回归、`.superpowers/sdd/task-4-fix-report.md`、`WORKLOG.md`
- 执行验证：四个 Task 4 模块新增回归先出现 9 个预期 RED；GREEN 64 项、full gate 22/22（`mapping_miss=false`、`first_failure=null`）及最终 `git diff --check` 通过
- 结果：scope 使用专用 512 字符、四层 JSON 容器上限解析器；原始值仅接受 `str`，BLOB（含可解码 JSON）、损坏/超长/过深/非 list/未知/重复值全部投影空 scope，GET 稳定 200，MCP 缺 read scope 返回 403
- 未解决问题：无；未修改通用 `_json_loads()`，未实现 Task 5+
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 Task 5 安全来源发现与 prepare-only 订阅变更提案
- 修改文件：proposal service、Remote MCP subscription facade、source type discovery mapping、live delegation principal、Task 5 回归、`.superpowers/sdd/task-5-report.md`、`WORKLOG.md`
- 执行验证：新测试先因两个 Task 5 模块不存在按预期 RED；GREEN 15 项、指定 focused 252 项、Python compile、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：动态 flag/scope/live role/actor binding 在 planner 前失败关闭；v2 snapshot、store 权威 UTC 10 分钟、confirmation hash-only 与 proposal limit 完成；发现仅投影当前用户可见来源并限制 secret checker 与 managed Apify
- 未解决问题：Task 6 仍需实现 atomic apply/stale/single-use；本任务未实现 apply、MCP 工具注册、server wiring 或 UI
- 控制面变更：无；仅新增内部 Task 5 服务边界，外部 MCP/API 合同由后续统一任务更新

### 2026-07-17 Codex subagent
- 任务：关闭 Task 5 独立复审的两个 Important 与一个 Minor
- 修改文件：proposal service/store、source discovery registry/facade、Task 5/maintenance/deployment 回归、`.superpowers/sdd/task-5-fix-report.md`、`WORKLOG.md`
- 执行验证：facade 6 项与 store 4 项回归先按预期 RED，最终动态 flag guard mutation check 再确认 RED/GREEN；focused 594 项、maintenance/deployment 6 项、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：proposal 最终授权与 insert 由同一 `BEGIN IMMEDIATE` 锁定并增加 store active-principal 纵深条件；discovery 使用八类显式 matcher、YouTube/RSS 边界、Twitter/Apify 分区及稳定去重排序；secret checker 异常固定脱敏为 `source_discovery_unavailable`
- 未解决问题：Task 6 仍需实现 atomic apply/stale/single-use；本任务未实现 Task 6+、MCP 注册、server wiring 或 UI
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：关闭 Task 5 二次复审的一个 Important 与一个 Minor
- 修改文件：Agent-safe subscription planner/apply revalidation、source discovery public type validator、Task 5/Task 3/registry 回归、`.superpowers/sdd/task-5-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：disabled existing 与空目录 unknown type 回归先出现 6 个预期 RED；GREEN 专项 9 项、focused 433 项、Remote MCP 邻接 308 项及 Python compile 通过；最终 full gate、JSON 与 diff 检查见报告
- 结果：existing create 在 planner 与 apply 均要求 enabled/visible，facade 后竞态不生成 proposal、plan 后禁用不能应用；8 项 public source type 在目录扫描前稳定校验；REST 专用 mutation 权限保持不变
- 未解决问题：Task 6+ 未实现；本任务未新增内部 allow-disabled Agent 能力
- 控制面变更：无

### 2026-07-17 Codex subagent
- 任务：实现 Task 6 proposal 原子 apply、过期/陈旧处理与单次并发消费
- 修改文件：proposal service/facade、store 权威 transition、Task 6 回归、主实施计划、`.superpowers/sdd/task-6-report.md`、`WORKLOG.md`
- 执行验证：新增 apply 17 项与 store clock 专项先按预期 RED；Task6/mutation 280 项、delegation/media 36 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：apply 自有 `BEGIN IMMEDIATE` 并在锁内重验动态 flag/scope/live principal；store UTC 10 分钟边界、time crossing 仅提交 expired、exact HMAC compare、v2 duplicate/stale、safe summary、post-commit cleanup 与 exactly-once 并发完成；所有非 expiry 失败保持 pending 且业务零变化
- 未解决问题：Task 7+、MCP 工具注册/server wiring、UI/Skill 与生产启用仍未实现
- 控制面变更：仅勾选既有主实施计划 Task 6 执行状态；未改变对外 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：关闭 Task 6 复审的一个 Important 与一个 Minor
- 修改文件：proposal apply cleanup 边界、成功 update/delete apply 回归、主实施计划、`.superpowers/sdd/task-6-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：cleanup 抛错回归先按预期 RED，update 与 delete 两种 disposition 同轮通过；GREEN 专项 4 项、Task 6 focused 284 项、邻接 36 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：commit 后 cleanup 异常静默 best-effort，不再伪装 mutation 失败或泄露异常内容；update/delete keep/delete disable_private 均验证业务提交、proposal applied、stored/returned 精确 safe summary 与 second-use consumed
- 未解决问题：Task 7+、MCP 工具注册/server wiring、UI/Skill 与生产启用仍未实现
- 控制面变更：仅修正既有主实施计划中的 post-commit cleanup 内部错误语义；未改变对外 API/架构/UI 合同

### 2026-07-17 Codex subagent
- 任务：实现 Task 7 确定性来源/任务诊断与严格安全投影
- 修改文件：诊断服务、Remote MCP safe job result helper、诊断/read-service 回归、主实施计划、`.superpowers/sdd/task-7-report.md`、`WORKLOG.md`
- 执行验证：模块缺失与 safe-code retention 专项均先按预期 RED；focused 75 项、runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：固定 precedence/code/message/unknown 分类、跨用户 not_found、URL/query/Bearer 与内部字段零泄漏、secret bool/anonymous Worker evidence、ordinary list/get job 投影不变均已实现
- 未解决问题：Task 8+ 的 MCP 工具注册/server wiring、UI/Skill、生产启用与 canary 尚未实现
- 控制面变更：仅勾选既有主实施计划 Task 7；未更新对外 API/架构/UI 合同

### 2026-07-18 00:10 Codex
- 任务：关闭 Task 4 第五审中 shrink + 外部搜索回归可能在过滤 cards commit 前即通过的测试时序缺口
- 修改文件：生产工作台 Playwright、Task 4 报告与本工作日志
- 执行验证：关键桌面竞态 2/2；UI contract、lint、TypeScript、Vitest 29 文件/167 项、build/artifact、三视口 Playwright 54 scheduled（50 pass/4 desktop-only skip）、`test_gate full`、三份 Compose config 与 `git diff --check` 均通过
- 结果：搜索后先确认过滤结果为 11 条，再完成稳定多帧视口采样，最后断言未回弹；专用 wheel/RAF gate 保持独立覆盖 commit-to-next-frame 取消窗口
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 00:40 Codex
- 任务：关闭 Task 4 终审中的门禁优先级/导入绕过、移动导航、筛选可访问性、来源选项校验、生产 E2E 与深链重复请求缺口
- 修改文件：test gate 规划器与可执行 UI/ESLint 门禁；Hero Shell/Feed/预览导航与筛选；来源注册表 Select；release Playwright 配置及 RTL/E2E 回归
- 执行验证：RED→GREEN：`UI_CONTRACT.md` 映射与 7 个模板导入负例；App RTL 44 项、全量 Vitest 29 文件/175 项、UI contract、lint、TypeScript、build/artifact；DEV preview mobile 2 项、release build+preview 三视口 29 通过/4 既定跳过、`test_gate full` 22/22、`git diff --check` 均通过
- 结果：控制文件显式规则优先于 docs-only；静态模板动态导入不能绕过 checker/ESLint；390px 可访问全部六个目的地；筛选由 HeroUI overlay 承担 Escape/焦点归还；必填 Apify 下拉项显示帮助与字段错误且阻止无效创建；已有 snapshot 展开不再请求 feedItem；release 只运行构建产物并排除 DEV-only 预览/fixture
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 01:30 Codex
- 任务：关闭 Task 4 最终复审中的 release Playwright 命令、来源表单原生校验、深链请求时序、字段帮助和筛选外点焦点归还缺口
- 修改文件：`test_gate.py` 与 Python 门禁回归、Hero 来源表单、工作台深链查询、App RTL、生产 Playwright、Task 4 报告与本工作日志
- 执行验证：RED→GREEN（exact release argv、深链 source-settle、Apify 选项错误清除、来源 URL/数值/NaN 约束）；UI contract、lint、TypeScript、Vitest 29 文件/178 项、build/artifact、release build+preview 三视口 29 通过/4 既定 skip；导航 RAF 与移动过滤锚点各 30x/5-worker 压力 30/30；`test_gate full` 22/22、`mapping_miss=false`、51.941 秒；三份 Compose config 与 `git diff --check` 均通过
- 结果：release gate 强制调用 `e2e:release`；来源表单移除 `noValidate` 并在修正输入后清除字段错误；已在 source snapshot 的深链不再提前取 detail；正常字段输出 help；筛选支持外点关闭并归还触发器焦点
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 03:19 Codex
- 任务：关闭全分支终审中的来源类型切换状态串用、必填下拉无障碍语义及整数静默截断缺口
- 修改文件：Hero 来源创建对话框/注册表选项、App RTL 回归、Task 4 报告与本工作日志
- 执行验证：可信 RED→GREEN（类型切换仍显示旧/空选项、required 语义缺失）；focused 3 项、UI contract、lint、TypeScript、全量 Vitest 29 文件/179 项通过
- 结果：来源类型变化时按 type 重建 SourceForm 并加载该定义默认值；必填选项保留 HeroUI/React Aria required 语义，同时继续由统一中文字段校验输出错误；整数型 registry 字段拒绝小数并显式使用 step=1，避免后端静默截断
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 14:00 Codex
- 任务：按用户批注仅收口 `/feed` 的 Codex-inspired 视觉基准，移除搜索/手动更新，改用 macOS 系统字体栈，并重做带动效的左侧短刻度
- 修改文件：Feed Shell 路由边界、虚拟信息流进度轨、Feed 专用字体变量、RTL/Vitest 回归、UI 契约/决策/实施计划与本工作日志
- 执行验证：两轮可信 RED→GREEN（Feed 控件隔离、Codex 轨道；4 条真实数据时仍保持 28 个视觉刻度）；focused 18 项、UI contract、lint、TypeScript、Vite build/artifact 通过；真实 API 浏览器核验 `/feed` 动画轨道及 `/saved` 未受影响；最终 `test_gate full` 22/22、`mapping_miss=false`、51.982 秒；`git diff --check` 通过
- 结果：`/feed` 顶栏只保留标题与 Agent 开关，采用系统字体；300px/28 段左轨随可见卡片以 160ms 宽度/颜色/透明度动效反馈并支持 Reduced Motion；收藏和历史继续保留原搜索、更新按钮和紧凑右轨
- 未解决问题：仅保留既有 Vite >500 kB informational chunk warning；无功能或门禁失败
- 控制面变更：新增 D029 并更新 `UI_CONTRACT.md` 的 Feed 专属视觉边界；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 18:45 Codex
- 任务：执行用户确认的 A「Codex 式信息工作台」细化，仅在现有 HeroUI/Quiet Studio 生产树调整导航、Feed 卡片层级与 OpenClaw 交接区
- 修改文件：Feed v2 偏好与排序、常用视图纯函数、Hero Shell/Page/VirtualFeed/展示模型、Inteliscope 图标、Agent draft/composer、RTL/Playwright，以及 UI 契约、D031、计划与本工作日志
- 执行验证：四批 focused TDD 均 RED→GREEN；最终聚焦 Vitest 6 文件/44 项、ESLint（0 error/1 既有 warning）、TypeScript、Vite build/artifact 通过；桌面 Playwright 主流程、过滤刷新锚点与 Reduced Motion 共 3 项通过，主流程含 Axe 零 serious/critical；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、56.647 秒
- 结果：左栏按浏览/常用视图/管理分类，账户通过菜单显式退出；Feed 默认最新在上并可按用户切换顺序，工具条与 820px 卡片列对齐，重复摘要不再展示；OpenClaw 改为带模型提示偏好、实时状态和单一复制动作的紧凑交接编辑器，不产生网络执行
- 控制面变更：更新唯一视觉真源并新增 D031；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/Worker/scheduler

### 2026-07-18 20:35 Codex
- 任务：从设计系统根部修复全站字体与字号分叉，消除 Feed 工具栏“内容数 / 排序 / 筛选”及后续页面修改的排版不一致
- 修改文件：HeroUI 主题与全局字体入口、UI 静态契约和回归、工作台及管理页语义排版迁移、`UI_CONTRACT.md`、D032 与本工作日志
- 执行验证：契约测试先出现 7 项可信 RED，再完成十级 `type-*` 角色、HeroUI primitive 默认映射与 raw Tailwind 排版拦截；focused Vitest 4 文件/105 项、UI contract、TypeScript、ESLint（0 error/1 既有 warning）、Vite build/artifact 通过；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、55.633 秒，`git diff --check` 通过
- 结果：全站统一 macOS/system UI 字体栈；业务层不能再自行写字号、字重、行高或字距；真实 486px Feed 中“4 条内容 / 最新优先 / 筛选”计算样式均为 13px、500、20px，页面无横向溢出
- 运行验收：重建前确认无 queued/running Job；一次构建镜像 `inteliscope-service:ui-typography-20260718202652` 已替换本地 8080 API/Worker，live revision=`398009563055-typography-dirty`、database/worker ready；应用内浏览器刷新后完成计算样式与截图复核
- 控制面变更：更新唯一视觉真源并新增 D032；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度语义

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 独立审查的三个 Important 与一个 Minor
- 修改文件：诊断 related-job/no-items/scalar/clock 边界、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：新增 18 项反例按预期 RED；GREEN 后 Task 7 focused 94 项、schedule/runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：Health/Schedule 显式 FK 完整验证并优先 active schedule、owned full-refresh 可关联；Job no-items 仅认自身 succeeded+明确零 fetched count；credential key label 在 code/result/name 零泄漏；每个公开诊断使用单一 checked_at
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步既有 Task 7 内部证据选择、安全过滤与一致时钟语义；普通六工具与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第二轮独立审查的四个 Important
- 修改文件：Job/Source 独立归因、关联 provenance、严格 count/credential-label 投影、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r2-report.md`、`WORKLOG.md`
- 执行验证：34 项主反例与 1 项完整 name 标量专项按预期 RED；GREEN 后 Task 7 focused 139 项、schedule/runtime/MCP 邻接 70 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 `git diff --check` 通过
- 结果：Job 仅按自身归因且 Worker readiness 仅限 active；Source 更新 Schedule terminal failure 胜过旧 Health 并标记历史 evidence；畸形 count 不再归零；完整对外标量严格拒绝 access/private/key-env/api-key-env labels
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部归因与安全投影语义；普通六工具、通用 credential mapping classifier 与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第三轮独立审查的两个 Important，并接管复核前任未提交修复
- 修改文件：active/same-ID retry 归因、完整标量安全分类与普通值保留、诊断回归、主实施计划、`.superpowers/sdd/task-7-fix-r3-report.md`、`WORKLOG.md`
- 执行验证：接管后新增 same-code retry 1 项与普通 Bearer/Basic 名称 4 项按预期 RED；GREEN 后 diagnostics 191 项、focused 240 项、schedule/job retry/health Worker/API/MCP 邻接 143 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`）及 `git diff --check` 通过
- 结果：active selected Job 的 status 与 historical Health role 一致；同 ID retry 使用真实 ledger+更新时间识别并由当前 terminal Job 决定 status/cause；完整标量拒绝紧凑 Bearer/Basic、terminal key/connection-string/credential labels，普通业务标量保持可见
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 attempt provenance 与严格标量投影语义；普通六工具、通用 credential mapping classifier 与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第四轮独立审查的一个 Important
- 修改文件：JobQueue retry 的 Source Health provenance 重开、diagnostics 显式 FK 归因、真实 Worker/事务/并发回归、主实施计划、`.superpowers/sdd/task-7-fix-r4-report.md`、`WORKLOG.md`
- 执行验证：真实 catalog partial→同 ID retry→success/failed/partial 与事务边界先出现 6 个预期 RED；GREEN 后 focused 260 项、API/MCP/schedule/reliability 邻接 228 项、Python compile、两个 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`）及 `git diff --check` 通过
- 结果：retry 成功转 queued 的同一事务清除该 Job application ledger 并断开 Health `last_job_id`，保留旧健康字段；新 attempt 可重新幂等写 Health，多订阅、外事务回滚与并发语义稳定；诊断不再用状态/时间猜代际
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 retry/Health attempt provenance；普通六工具与对外注册面不变

### 2026-07-18 Codex subagent
- 任务：关闭 Task 7 第五轮独立审查的一个 Important
- 修改文件：JobQueue retry attempt-local 清理、真实 Worker/read/diagnostics 与事务回归、Task 7 主计划、R5 报告、`WORKLOG.md`
- 执行验证：两项专项先精确 RED，最小修复后 GREEN；focused 288 项、R4 邻接 238 项、full gate 22/22、Python compile、两个 JSON 和 diff 检查通过
- 结果：same-ID manual retry 在成功条件 UPDATE 中原子清除旧 `result_json/started_at`；queued/running 与第二 attempt pre-result failure 的普通 list/get、Job/Source diagnostics 均不再暴露旧 summary，下一 claim 重写当前开始时间
- 未解决问题：Task 8+ 的 MCP 注册/server wiring、UI/Skill、生产启用与 canary 仍未实现
- 控制面变更：仅同步 Task 7 内部 retry attempt attribution；普通六工具 shape、权限、active/rollback/concurrency 与 R4 Health provenance 不变

### 2026-07-18 Codex subagent
- 任务：实现 Task 8 的 14-tool Remote MCP 注册、严格输入、claim-derived actor、服务注入与安全错误/日志
- 修改文件：MCP typed models/server、API injection、真实 MCP HTTP 回归、Task 8 主计划/报告、`WORKLOG.md`
- 执行验证：初始 7 failed / 15 passed 精确 RED；最终 transport/diagnostics/Nginx 219 项、Task1/4–7 邻接 666 项、Python compile、默认配置 JSON、full gate 22/22（`first_failure=null`、`mapping_miss=false`）及 diff 检查通过
- 结果：14 工具顺序与 annotations 精确；全局 auth 保持 read，写权限由 proposal service 重验；prepare/apply、read-scope/flag-off、跨用户隔离、extra-forbid/Task1 config 安全和固定脱敏日志均由真实 Client 覆盖
- 未解决问题：Task 9+ UI/Skill、控制面合同、impact map、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅勾选既有 Task 8 执行状态；对外合同由后续统一文档任务更新

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 独立审查的一个 Important，统一业务函数前参数验证失败的安全错误与审计
- 修改文件：app-local MCP call-tool adapter、四类真实 Client 验证回归、Task 8 主计划、R1 修复报告、`WORKLOG.md`
- 执行验证：四类 validation 4/4 按预期 RED 后 GREEN；Task 8 transport/diagnostics/Nginx 223 项、Task1/4–7 邻接 666 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：外层/nested extra、错误 discriminator 与范围错误均只返回 `invalid_request`，每次精确一条固定七字段审计且输入/ValidationError 零泄漏；14 工具 schema/annotations/顺序、正常单日志与每 app 隔离保持不变
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 验证失败安全边界与执行证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 第二轮复审的 validation 绕过 delegation limiter Important
- 修改文件：app-local MCP limiter/adapter、真实 Client 与注入时钟回归、Task 8 主计划、R2 修复报告、`WORKLOG.md`
- 执行验证：5 个专项先 5/5 RED 后 GREEN；Task 8 focused/transport/diagnostics/Nginx 228 项、Task 1/4–7 更宽邻接 854 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：已认证已注册调用在预检前共享每 delegation `60/minute, burst 10`；validation/成功/业务错误各消费一次且每 call 恰好一条七字段日志；unauthenticated/unknown 不计费不审计，每 app 独立且零敏感泄漏
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 delegation limiter 执行顺序与证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：关闭 Task 8 第三轮复审的 pre-parse 异常绕过稳定错误与审计 Important
- 修改文件：app-local MCP validation adapter、两类真实 Client pre-parse 回归、Task 8 主计划、R3 报告、`WORKLOG.md`
- 执行验证：ValueError/RecursionError 两项专项先 2/2 RED 后 GREEN；Task 8 focused/transport/diagnostics/Nginx 230 项、Task 1/4–7 邻接 854 项、full gate 22/22、Python compile、两个 JSON 与 diff 检查通过
- 结果：超长整数与深嵌套 JSON 的 SDK pre-parse 异常统一为精确 `invalid_request`，每次恰好一次 bucket charge 与一条七字段日志，输入/异常零泄漏；成功路径仍委托 SDK
- 未解决问题：Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 未实现
- 控制面变更：仅补充既有 Task 8 输入拒绝边界与执行证据；未修改对外 API/架构/UI 合同

### 2026-07-18 Codex subagent
- 任务：实现 Task 9 权限感知助手连接 UI
- 修改文件：Agent delegation 前端 types/service、AgentsPage 与专项单测、Task 9 主计划/报告、`WORKLOG.md`
- 执行验证：指定单测先出现 7 个预期 RED，最终 service/AgentsPage 11 项通过；AgentsPage 收紧精确 6/14 工具断言后 9 项通过；TypeScript typecheck 通过
- 结果：创建连接默认只读并显式提交 access；viewer 隐藏写选项、写开关关闭时禁用并说明；连接权限 Chip、一次性 `{token, access}` 清理和按连接权限复制无明文令牌配置完成
- 未解决问题：Task 10 Skill 与 Task 11 build/E2E/Axe/full gate、控制面合同、生产启用和真实 OpenClaw canary 尚未执行
- 控制面变更：仅同步既有 Task 9 执行状态与 Task 11 验收边界；本任务未修改 API/UI 权威合同

### 2026-07-18 Codex subagent
- 任务：实现 Task 10 OpenClaw 订阅管理 Skill、诊断与确认工作流
- 修改文件：本地 Skill、README、工具合同、工作流、focused 静态测试、Task 10 计划/报告与 `WORKLOG.md`
- 执行验证：先以 `.venv/bin/pytest tests/test_openclaw_skill.py -q` 得到 3 项预期 RED；文案收紧后同一单测 6/6 通过，frontmatter/diff 静态检查通过，`openclaw skills check` 通过（仅现有 duplicate-plugin 配置警告）
- 结果：Skill 覆盖精确 14 工具、八类来源别名/Apify-Web 边界、逐字段收集、existing source list-only、prepare→完整预览→精确确认→apply、显式删除选择、受限诊断与 secret refusal；仅 apply 成功后声明写入
- 未解决问题：Task 11 控制面合同、impact map、完整验收与真实 canary 尚未执行
- 控制面变更：将 Task 10 既有计划步骤标记完成；未更改服务端、前端或生产配置

### 2026-07-18 Codex subagent
- 任务：关闭 Task 10 独立审查的 access-specific OpenClaw toolFilter Important
- 修改文件：OpenClaw Skill README、focused 静态回归、`.superpowers/sdd/task-10-fix-r1-report.md`、`WORKLOG.md`
- 执行验证：`.venv/bin/pytest tests/test_openclaw_skill.py -q` 7 项通过，`git diff --check` 通过
- 结果：viewer/read-only 配置精确限制为六个核心读工具；仅 Inteliscope Web 创建的 subscription-management 连接配置全部 14 工具；两种配置都只使用 `${INTELISCOPE_MCP_TOKEN}` 环境变量占位符
- 未解决问题：Task 11 控制面合同、impact map、完整验收与真实 canary 尚未执行
- 控制面变更：仅修正文档化的本地 OpenClaw toolFilter 与其静态不变量；未修改服务端、前端或生产配置

### 2026-07-18 Codex subagent
- 任务：完成 Task 11 Remote MCP 订阅管理控制面合同、影响映射与最终验收边界
- 修改文件：`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`UI_CONTRACT.md`、`DECISION_LOG.md`、`PLAN.md`、`tests/test_impact_map.json`、`.superpowers/sdd/task-11-report.md` 与 `WORKLOG.md`
- 执行验证：`python` 在该 worktree 不存在；唯一一次等价 `python3 scripts/test_gate.py plan --json` 因没有 snapshot 或 `--base/--head` 输入而未生成选择计划。`project-defaults.yaml` 与 impact map JSON lint、`git diff --check` 均通过；按本任务限制未运行 pytest、Node、build、performance benchmark、full gate 或真实 OpenClaw canary
- 结果：合同现在覆盖 read/write delegation access/scopes/flag、精确 14-tool 输入边界/annotation、服务端 prepare→confirm→apply lifecycle、诊断 shape 与稳定错误；架构确认共享 mutation/proposal/diagnostics ownership、stateless MCP 与无内部 HTTP；助手连接 UI 记录 access 选择、viewer 限制、capability Chip 与权限 toolFilter；impact map 将 proposal/mutation、Remote MCP/Skill 与 focused suites 路由到 API/store。
- 未解决问题：本地 100-call performance acceptance 与真实 OpenClaw synthetic/free-data canary 均未运行；生产仍需 backup、API-only staging（写 flag 关闭）、TLS Authorization forwarding、read/write canary、revoke 401、两用户隔离及明确 flag enablement。
- 控制面变更：新增 D025；Remote MCP 订阅写入不再是非目标，但密钥/共享来源/任务和 Feed 状态管理仍不通过 MCP 开放；回滚只关闭 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`。

### 2026-07-18 Codex
- 任务：执行用户要求的唯一一次最终完整门禁，并记录本地完成证据
- 修改文件：`.superpowers/sdd/task-11-report.md`、`WORKLOG.md`
- 执行验证：`.venv/bin/python scripts/test_gate.py run --mode full` 22/22 commands 通过，0 failed/error，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 97.402 秒
- 结果：本地实现、前后端、Skill、合同和影响映射通过统一完成门禁；没有重复运行 full gate
- 未解决问题：100-call 独立性能基准与真实 OpenClaw canary 未执行，生产 staging/TLS/revoke 401/两用户隔离/显式开关授权仍是发布边界
- 控制面变更：仅记录最终验证证据；未启用任何生产 feature flag

### 2026-07-18 Codex
- 任务：收口 OpenClaw Remote MCP 只读生产发布、诊断合同、canary 与 API-only Runbook
- 修改文件：助手连接 10/14 toolFilter、OpenClaw Skill/合同、env/Compose/Nginx 文档、只读 canary、发布 Runbook、影响映射与控制文件
- 执行验证：专项 pytest 28 项、AgentsPage 9 项通过；100-call MCP p95 7.451 ms、REST p95 1.094 ms、RSS +0.812 MiB；唯一一次 release gate 因 worktree 缺少忽略的 `data/config.json` 中止，补齐后原失败用例通过，未重跑 release gate
- 结果：read connection 精确开放 10 个安全读/指导/诊断工具，write connection 保持 14 个且生产写 flag 默认关闭；canary 覆盖全部安全读、双用户隔离、禁写与吊销 401
- 未解决问题：release gate 尚无通过结论；真实 OpenClaw、独立 staging、生产 TLS/canary/切换及 24 小时观察尚未执行
- 控制面变更：Remote MCP 权威合同改为 10 安全读 + 4 写流程，生产只读边界固定保留 additive v6/v7 且不启动 Worker/Agent/模型

### 2026-07-18 Codex
- 任务：执行 OpenClaw MCP 合并与只读生产发布前的最后一次门禁
- 修改文件：API-only 发布 Runbook、Runbook 静态测试与 `WORKLOG.md`；恢复 OpenClaw approvals 并清理临时 profile
- 执行验证：Runbook 专项按预期 RED 后 GREEN；release gate 22/23 commands 通过，唯一失败为 Playwright 4 项，原因是 worktree `node_modules` 软链接位于 Vite allow list 外导致本地字体请求被拒绝
- 结果：已删除临时 `data/config.json`/`frontend/node_modules` 软链接；按批准的最终门禁硬边界停止，未合并、未构建镜像、未修改 staging/Nginx/生产容器或数据库
- 未解决问题：release gate 无通过结论；后续合并、staging、双用户 canary、生产切换与 24 小时观察保持阻塞，除非用户另行授权新的验证方案
- 控制面变更：Runbook 现在要求备份前同时停止 API/Worker、staging 独立日志，并仅增量修改线上 `cfl.conf`

### 2026-07-18 Codex
- 任务：实现 Quiet Studio Feed 顶栏、工具行和双栏 Agent 图标，并先更新 UI 契约
- 修改文件：设计系统图标出口、Hero Shell/Page、两项 focused Vitest、UI 契约与本工作日志
- 执行验证：`npm --prefix frontend run test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx src/app/App.test.tsx` RED（2 项目标行为失败）→GREEN（2 文件/52 项通过）
- 结果：Feed 使用 Quiet Studio header 标记、受控 split-panel 图标与简化工具行；收藏/历史保持原图标和 collection 工具行
- 未解决问题：后续任务仍负责移除 Feed rail 与重设卡片；本任务未执行它们的视觉/全量门禁
- 控制面变更：`UI_CONTRACT.md` 将 `/feed` rail 规则替换为 Quiet Studio 的绑定布局、动效、可访问性与受控尺寸语义

### 2026-07-18 Codex
- 任务：补齐 Quiet Studio Feed 已启用筛选数量的回归覆盖
- 修改文件：`App.test.tsx`、Task 1 报告与本工作日志
- 执行验证：`npm --prefix frontend run test -- src/app/App.test.tsx` RED（缺少 `已启用 3 项筛选`）→GREEN（1 文件/49 项通过）
- 结果：持久化的未读优先、来源和最低分筛选会显示可访问的三项计数
- 控制面变更：无

### 2026-07-18 Codex
- 任务：移除 Quiet Studio Feed 进度轨道及其留白，并保持收藏/历史的 collection 轨道
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、`HeroWorkbenchPage.tsx`、本工作日志
- 执行验证：`VirtualFeed.test.tsx` RED（Quiet Studio 仍渲染 compact rail）→GREEN（与 `App.test.tsx` 共 2 文件/58 项通过）；`git diff --check` 通过
- 结果：`/feed` 显式使用 `quiet-studio`，无进度导航/预留 gutter，列宽约 820px；`/saved` 与 `/history` 保持 12 刻度紧凑右轨和原列宽
- 控制面变更：无

### 2026-07-18 Codex
- 任务：实现 Quiet Studio Feed 卡片层级、原位展开动效与 Agent 上下文确认态
- 修改文件：Feed 圆角 token、`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、本工作日志
- 执行验证：`VirtualFeed.test.tsx` RED（2 项目标行为失败）→GREEN；聚焦 Vitest 3 文件/64 项、UI contract、TypeScript、`git diff --check` 通过
- 结果：仅 `/feed` 使用 18px 卡片、细边界悬停反馈、可动画详情与移动端 44px 操作；collection 卡片继续保持既有结构
- 控制面变更：无

### 2026-07-18 Codex
- 任务：更新 Quiet Studio Feed 的三视口生产交互与隔离回归
- 修改文件：生产工作台 Playwright、本工作日志
- 执行验证：release RED（旧轨道/刷新断言 11 项失败）→GREEN；Vite build/artifact 通过，desktop/tablet/mobile Playwright 21/21 通过，`git diff --check` 通过
- 结果：生产验收覆盖无 Feed rail、后台任务刷新、18px/820px 卡片、原位展开、Agent 图标、Reduced Motion、键盘/44px 触控与 collection 隔离；移除 Feed rail-only 用例和固定等待
- 控制面变更：无；未修改生产组件、backend/API/DB/query key/权限/Remote MCP/history/VPS/Worker/scheduler

### 2026-07-18 Codex
- 任务：固化 Quiet Studio Feed 合同、完成一次最终门禁并发布 revision-locked 本地 8080 预览
- 修改文件：`UI_CONTRACT.md`、`DECISION_LOG.md`、`PLAN.md`、本工作日志
- 执行验证：Task 1–3 focused TDD RED→GREEN（52 项及 49 项补充、58 项、64 项）；Task 4 release build/artifact 与三视口 Playwright 21/21、Axe 零 serious/critical；本次 `test_gate full` 22/22、`mapping_miss=false`、55.339 秒；镜像 `inteliscope-service:feed-quiet-fef5862f1c48` 的 live revision=`fef5862f1c48`、ready database/worker=`ready`、`/feed` HTTP 200，API/Worker 同镜像且 healthy
- 结果：D030 与唯一视觉真源已收口，主仓库 light Compose 的本地 API/Worker 已换为一次构建的 Quiet Studio 镜像；控制器随后在应用内浏览器完成真实运行态复核：`/feed` 显示 4 条 Quiet Studio 卡片、无进度轨及其留白，split-panel Agent 图标、原位展开与加入上下文均可用，Agent 关闭/重开前后 Feed `scrollTop` 均为 `396.5`；`/saved` 与 `/history` 继续显示 collection rail、搜索和更新入口，分别渲染 1/6 张集合卡片；三条路由 console error 均为 0，测试加入的 Agent 上下文已移除
- 控制面变更：仅 Feed 视觉合同和交付状态；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度器

### 2026-07-18 Codex
- 任务：关闭 Quiet Studio 复审中的宽屏 coarse-pointer 卡片操作目标缩为 32px，以及 PLAN 误把设计规格称为实施证据的问题
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx`、`PLAN.md`、忽略的 Task 5 报告与本工作日志
- 执行验证：定向 Vitest 1 项可信 RED（旧链接缺少 fine-pointer `size-8`）→GREEN（1 通过/11 跳过）；TypeScript、`git diff --check` 通过；修复后的最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、51.651 秒
- 结果：Quiet Studio 四个卡片操作以 32px 为 fine-pointer 基线，并通过 `pointer-coarse:size-11` 在任意视口保持 44px；PLAN 分开标注设计规格与 `WORKLOG.md` 实施证据；Task 5 独立复审无剩余 finding
- 运行验收：一次构建镜像 `inteliscope-service:feed-quiet-f395cbe2137f`（built at `2026-07-18T09:07:00Z`）已替换本地 8080 的 API/Worker；live revision=`f395cbe2137f`、database/worker ready、`/feed` HTTP 200、两容器同镜像且 healthy；容器生产 CSS 包含 `@media (pointer:coarse)`；应用内浏览器刷新后仍显示 4 条 Quiet Studio 卡片、无 Feed 进度轨、Agent 控件可见且 console error 为 0
- 控制面变更：仅修正 PLAN 的证据归属表述；未改变 UI 合同，也未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/调度器

### 2026-07-18 Codex
- 任务：关闭 Quiet Studio 终审中宽屏 coarse-pointer 卡片操作因视口断点降为 60% opacity、又缺少可靠 hover 的问题
- 修改文件：`VirtualFeed.tsx`、`VirtualFeed.test.tsx` 与本工作日志
- 执行验证：定向 Vitest 1 项可信 RED（旧动作容器缺少 `pointer-fine:` 类）→GREEN（1 通过/12 跳过）；TypeScript、`git diff --check` 通过；新 HEAD 最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、54.881 秒
- 结果：动作容器默认保持 fully visible，仅 fine pointer 降为 60% opacity，并只在 fine-pointer hover/focus 时恢复 100%；coarse pointer 不再受视口宽度影响；整分支复审无剩余 Critical/Important，确认 ready to merge
- 运行验收：一次构建镜像 `inteliscope-service:feed-quiet-d4a5f0489390`（built at `2026-07-18T09:48:20Z`）已替换本地 8080 的 API/Worker；live revision=`d4a5f0489390`、database/worker ready、`/feed` HTTP 200、两容器同镜像且 healthy；容器生产 CSS 包含 `@media (pointer:fine)`；应用内浏览器刷新后显示 4 条卡片、无 Feed 进度轨、Agent 控件可见且 console error 为 0；非阻塞 Minor 为后续补一条 collection rail 行为覆盖
- 控制面变更：无；未修改 backend/API/DB/query key/权限/Remote MCP/history/VPS/数据/scheduler

### 2026-07-19 02:23 Codex
- 任务：执行 Quiet Studio 全站 UI 统一，将已确认的信息流视觉语言扩展至收藏、历史、订阅、助手连接、设置、登录和 OpenClaw 响应式面板
- 修改文件：设计系统共享 `PageFrame/PageHeader/ViewBar/PageSection/CompactSelect` 与状态模式、三条内容路由、OpenClaw `HandoffComposer`、四条管理/认证路由、UI 静态契约、Vitest/Playwright，以及 `UI_CONTRACT.md`、D033、PLAN 和本工作日志
- 执行验证：页面宽度契约完成可信 RED→GREEN；内容工作台聚焦 74 项、管理页 58 项、UI 契约 36 项均通过；最终 `test_gate full` 22/22、0 failed/error、`mapping_miss=false`、58.253 秒；release build 三视口 Playwright/Axe 27/27 通过，Axe 零 serious/critical；`git diff --check` 通过
- 结果：全部生产路由统一消费 Quiet Studio 语义页面模式；收藏/历史删除 collection 轨道并复用阅读卡片和 ViewBar；管理页只保留 Shell 中的唯一 H1，登录使用 auth 框架；三种 Agent 容器复用统一交接编辑器。静态契约会拒绝业务页重新定义 820/1180/420px 页面宽度
- 运行验收：重建前确认主数据库无 queued/running Job；一次构建镜像 `inteliscope-service:quiet-studio-c6e83554a16d` 同时替换本地 8080 API/Worker，live revision=`c6e83554a16d`、database/worker ready、两容器同 image ID 且 healthy，六条生产路由 HTTP 200；应用内浏览器真实数据复核设置/订阅唯一标题与统一分区、收藏统一空态、历史 7 张 Quiet Studio 卡片、0 个进度轨且无横向溢出
- 控制面变更：Quiet Studio 成为全站生产视觉语言并新增 D033；未修改 backend/API/DB/query key/权限/任务/Remote MCP/history/VPS/数据/调度语义

### 2026-07-19 04:16 Codex
- 任务：建立 Quiet Studio × OpenClaw 独立统一分支，补齐 HeroUI delegation 权限并发布本地 RC
- 修改文件：非 squash 合并双方历史与控制文档；HeroUI `AgentsPage`、设计系统 Select、前端 API 类型/服务、专项测试；`test_mcp_adapter` 自包含 fixture；`PLAN.md` 与本工作日志
- 执行验证：HeroUI/API 聚焦 Vitest 61/61 通过，OpenClaw 后端定向集合通过；`test_gate full` 22/22、0 failed/error、`mapping_miss=false`、99.139 秒；`test_gate release` 24/24、0 failed/error、三视口 Playwright/Axe 与 API-only Docker smoke 通过、128.206 秒；`git diff --check` 通过
- 结果：`feature/quiet-studio-openclaw-rc` 保留 OpenClaw 后端/API 与 Quiet Studio HeroUI 两侧提交历史；助手连接支持默认只读、Viewer/flag 限制、10/14 工具说明及按已保存 access 复制配置；release gate 不再依赖未跟踪 `data/config.json`
- 数据库验收：主库在线副本在断网 RC 容器中完成 v7 初始化，`agent_change_proposals_v7` marker、两项索引、三项级联外键、integrity/foreign-key 与核心表计数均通过；副本未产生 proposal 或真实外部调用
- 运行验收：备份 `data/backups/service-pre-quiet-studio-openclaw-rc-20260718T201416Z.db`（SHA-256 `acf8524d5f8db9da03390cbb1210eebd19f5784c7964cdabf53beaec5189a250`）后，本机 8080 已切换至唯一镜像 `inteliscope-service:quiet-studio-openclaw-rc-14f212c83b33` / image ID `sha256:feb6cabe86b76b2cd6cf325dd937c59f7d553486caa00acb8b443d59e9696d9e`；API/Worker 同镜像且 healthy，live revision 正确、database/worker ready，Feed/收藏/历史/订阅/助手连接/设置/登录均 HTTP 200，队列无 queued/running，两个 Remote MCP 开关保持 false
- 控制面变更：新增 PLAN 第 52 项并修正旧的 6-tool/禁写表述；未修改 `main`、来源分支、远端、公网或 VPS，未启用 Remote MCP 或订阅写入

### 2026-07-19 15:02 Codex
- 任务：修复 Quiet Studio 信息流的侧栏交互分叉、社交卡片重复与 Agent 上下文内部 ID 展示；按要求跳过 OpenClaw 模型同步
- 修改文件：共享工作台展示模型、Virtual Feed、Hero Workbench Shell、生产 Playwright、聚焦 RTL、`UI_CONTRACT.md`、D034 与本工作日志
- 执行验证：展示模型、卡片与 Shell 均完成可信 RED→GREEN；完整 `test_gate full` 22/22、0 failed/error、89.108 秒；1440/1024/390 生产工作台 Playwright/Axe 24/24 通过；`git diff --check` 通过
- 结果：桌面路由与常用视图复用同一无位移导航行和 40px 分栏按钮；X/Instagram 及旧 `apify_social` 快照使用来源优先的单正文卡片；最多 8 条 Agent 上下文通过用户作用域详情查询显示头像、平台、关注对象、正文首行与时间，原始 item ID 仅保留在 sessionStorage 和交接提示词
- 运行验收：切换前 queued/running Job 为 0，并在线备份 `data/backups/service-pre-social-20260719T065407Z.db`（SHA-256 `674b61bba862cbf7c8d4a5c0ad624a8ae4897aa24ef86ee28eca152f0f13fd87`）；固定提交 `b207250ff7da` 构建镜像 `inteliscope-service:quiet-studio-social-b207250ff7da` / image ID `sha256:9a10d79fa7a380496cddf0cf0adcb42d9dc0b6b271a330f8572fd8e2da9ba131`，API/Worker 同镜像、同主数据挂载且 healthy，live revision 正确、database/worker ready，七条生产路由 HTTP 200，Remote MCP 两个开关保持 false
- 人工复核：应用内浏览器真实 `/feed` 显示 5 条内容；X/Instagram 来源、作者与正文无重复；加入 Instagram 内容后 Agent 显示可读预览且原始 ID 计数为 0；1440px 侧栏的路由与快速视图共享相同类和交互，split-panel 控件正确；测试上下文已移除、面板已关闭、console error 为 0
- 控制面变更：新增 D034 与对应 UI 契约；未修改 `auto | fast | deep` 模型偏好、API、数据库、权限、Query Key、MCP 协议、历史数据、main、远端或 VPS

### 2026-07-19 16:54 Codex
- 任务：非 squash 整合 Quiet Studio RC 与 OpenClaw Browser Gateway，准备并发布 Inteliscope v1.7.0
- 修改文件：双方完整提交历史、版本入口、HeroUI 助手连接工具契约、生产工作台 Playwright 与本工作日志
- 执行验证：合并后 UI contract、ESLint、TypeScript、Vitest、Vite build、Python/full/Compose/JSON 等发布门禁前 22 项通过；修正过期的 Agent 按钮与自动开面板验收后，三视口定向 6/6、完整 Playwright/Axe 30/30 通过；受控配置下隔离 Docker build、ready、API smoke 与 cleanup 全部通过；`git diff --check` 通过
- 结果：`release/v1.7.0` 同时包含 Quiet Studio 全站 HeroUI、社交来源/Agent 可读上下文、10/14 工具 delegation access 与 Browser Gateway Chat；版本号统一为 `1.7.0`，原多用户工作区的未提交控制文件未被纳入发布
- 控制面变更：仅记录版本整合与发布证据；未修改 API、数据库、权限、Query Key、Remote MCP 协议、主数据、VPS 或公网运行态

### 2026-07-19 18:20 Codex
- 任务：将精确标签 `v1.7.0` 安全发布到 `vps-tokyo`，保留可验证的生产回滚点
- 修改文件：仅本工作日志；VPS 新增 revision-locked release、不可变镜像与权限受限备份，未修改 Nginx 配置
- 执行验证：归档双端 SHA-256 `ae783c9f…ed49`；脱敏 staging 完成 v6/v7、integrity/foreign-key、8 项非变更 API smoke、8 条 UI 路由及高风险开关全关；生产 live=`1.7.0/59399130846d`、ready database/worker=`ready`，API/Worker 同 image ID `sha256:7ab1c764…7413`、healthy、0 restart；本机与公网 HTTPS 8 条路由均 200、未登录 API 401、TLS 校验通过，完整 Worker 轮询后 queued/running=0、proposal=0、严重日志匹配=0
- 结果：`/opt/inteliscope/current` 已指向 `/opt/inteliscope/releases/v1.7.0-59399130846d`；切换前数据库、配置和 `.env` 备份位于 `/opt/inteliscope/backups/pre-v1.7.0-59399130846d-20260719T100150Z`，旧 v1.6.0 release/image 保留；staging 容器与脱敏副本已清理
- 控制面变更：无；Remote MCP、订阅写入、Browser Chat、共享抓取与 compact writer 均保持关闭，未触发来源抓取、AI、付费调用或公网 Nginx 变更

### 2026-07-20 00:28 Codex
- 任务：修复 Agent 长上下文可达性、导航/快速视图状态，并根治社交来源近期内容被全量 Feed 覆盖后只在历史可见的问题；按要求跳过 OpenClaw 模型同步
- 修改文件：工作台 Shell/常用视图及聚焦测试、Feed finalizer/稳定内容索引/序列化及生产回归、`UI_CONTRACT.md`、`API_CONTRACT.md`、D037 与本工作日志
- 执行验证：前端与 Feed 均完成可信 RED→GREEN；影响映射 `mapping_miss=false`，定向门禁 9/9、79.198 秒；最终 `test_gate full` 22/22、0 failed/error、88.891 秒；`git diff --check` 通过
- 结果：最多 8 条上下文采用单行截断且删除入口固定可达；分栏入口仅在打开时使用紫色选中态；“全部”快速视图清除筛选并保留排序；active source 的窗口内内容由本次结果、最新 snapshot 与用户稳定内容索引滚动合并，遗留 X/Instagram 派生 latest 帖子可恢复，显式 `latest_per_source` 仍保持替换语义
- 控制面变更：新增 D037 并更新 UI/API retention 真源；无数据库迁移或历史重写，未修改 OpenClaw 模型、权限、Query Key、MCP 协议，也未触发来源抓取、AI 或付费调用

### 2026-07-20 01:14 Codex
- 任务：准备 Inteliscope v1.7.1 revision-locked 本地 RC，为精确标签与安全 VPS 发布建立回滚点
- 修改文件：六处版本入口、D037 状态与本工作日志；运行态使用主数据挂载但未创建业务任务
- 执行验证：正式 `test_gate release` 24/24、0 failed/error、131.427 秒，含三视口 Playwright/Axe 与隔离 Docker smoke；切换前 queued/running=0，数据库 integrity/foreign-key 正常；切换后 7 条路由 200、API/Worker healthy、worker ready、0 restart，队列与 proposal 均为 0
- 结果：本地 8080 已使用唯一镜像 `inteliscope-service:v1.7.1-318c0f120ae5` / image ID `sha256:781fa8f88ccfa2b96818b4561f976a169ba4fe558eb67a5f3f96acf145da8502`；live identity=`1.7.1/318c0f120ae5`；切换前备份为 `data/backups/service-pre-v1.7.1-20260719T171209Z.db`（SHA-256 `0a34eacd12a7b1928e351cd236680b4499e14b44231cfbd6241613b651a661cb`）
- 控制面变更：D037 标记本地 RC 完成；Remote MCP、订阅写入和 Browser Chat 保持关闭，未触发真实来源、AI、付费调用或 OpenClaw 模型同步

### 2026-07-20 02:14 Codex
- 任务：发布精确标签 `v1.7.1`，并将通过隔离预演的 revision-locked 版本安全切换至 `vps-tokyo`
- 修改文件：D037 状态与本工作日志；VPS 新增不可变 release/image、权限受限备份并更新 `current` 指针，未修改 Nginx 或业务数据
- 执行验证：`release/v1.7.1` 与 annotated tag 已推送并通过远端引用校验；脱敏数据库 staging 完成 v2/v4/v5/v6/v7、integrity/foreign-key、七条 UI 路由、未登录 API 与高风险开关验证；生产 API/Worker 同 image ID `sha256:b1405ac097fce29b94a27e66c4e50a25bf62923c9e59f7c138177bedced929d6`、healthy、0 restart，live=`1.7.1/0436fdcfa3a0`、database/worker ready；本机与公网七条路由均 200、受保护 API 401、TLS 校验通过，Worker 完整轮询后 queued/running=0、proposal=0、integrity=ok、foreign-key=0、严重日志匹配=0
- 结果：`/opt/inteliscope/current` 已指向 `/opt/inteliscope/releases/v1.7.1-0436fdcfa3a0`；切换前数据库、配置和 `.env` 备份位于 `/opt/inteliscope/backups/pre-v1.7.1-0436fdcfa3a0-20260719T174745Z`，数据库 SHA-256 为 `84b83dbf59f1e93aa104e17cb410ec47795875fc6b6778637bb0c127ce461d4b`；旧 release/image 保留，staging 容器、脱敏副本和传输归档已清理
- 控制面变更：D037 标记为 v1.7.1 已发布；Remote MCP、订阅写入、Browser Chat、共享抓取与 compact writer 均保持关闭，未手动触发来源抓取、AI、付费调用或 OpenClaw 模型同步

### 2026-07-20 15:00 Codex
- 任务：以 `main@2d9d097` 的 v1.7.1 文件树重新承载工作台生命周期、订阅异常/移动端、删除确认、复制反馈与内容工具栏优化，修复此前从旧 feature dirty 树构建导致的 UI 回退
- 修改文件：应用/页面错误边界、订阅展示模型与响应式页面、密钥确认框、信息卡复制反馈、Feed/收藏/历史 ViewBar、对应 Vitest/Playwright，以及 `project-defaults.yaml`、`UI_CONTRACT.md`、D038/D039 与本工作日志
- 执行验证：聚焦 Vitest 92/92、UI contract、ESLint、TypeScript、Vite/Docker production build、三视口 Playwright/Axe 12/12 与 `git diff --check` 通过；沿用已通过的 v1.7.1 release gate 24/24，未重复完整门禁
- 结果：本地 8080 的 API/Worker 已切换至 `inteliscope-service:local-2d9d097-dirty-uxfix`，live=`1.7.1/2d9d097-dirty-uxfix`、database/worker ready；应用内浏览器确认新版 SplitPanel/侧栏代码仍在，Feed 有排序和“更新信息流”，收藏/历史有排序且无更新按钮，console error 为 0；主 dirty 工作区未被触碰
- 控制面变更：删除三个无消费者的 `material_ui_*_enabled` 历史字段，新增 D038/D039 并更新内容工具栏 UI 契约；未修改 API、数据库、权限、OpenClaw 协议、远端、VPS 或功能开关

### 2026-07-20 15:12 Codex
- 任务：将本批未提交补丁从已合并的 `feature/post-v1.7.0` worktree 迁至基于 `main@2d9d097` 的独立修复分支，并非 squash 合入本地 `main`
- 修改文件：仅增加本条迁移记录；功能补丁由提交 `21b6fa5` 完整承载
- 执行验证：tracked diff 与原 stash SHA-256 一致，新增生命周期测试文件 SHA-256 一致；合并无冲突，`git diff --check` 与提交关系检查通过；未重复已通过的功能门禁
- 结果：`fix/workbench-lifecycle-interactions` 保留可审查提交，本地 `main` 已整合该提交；原 feature worktree 恢复干净，主 dirty 工作区、`origin/main`、VPS 与本地运行容器均未被改写
- 控制面变更：无新增控制面变化；未推送远端、未部署或开启功能开关

### 2026-07-20 17:18 Codex
- 任务：为 Feed、收藏和历史增加来源优先的内容格式、原始图片总数、本地图库及真实展开/采集不完整反馈
- 修改文件：内容展示投影、RSS/Apify 抓取与媒体缓存、既有 AI 分析缓存、共享 Quiet Studio 卡片与详情查询、API/UI 契约、D040 及对应 Python/Vitest/Playwright 测试
- 执行验证：后端定向分类/媒体测试、前端模型与卡片 32/32、App 页面级 54/54 通过；最终 `test_gate full` 22/22、0 failed/error、93.301 秒；1440/1024/390 生产工作台 Playwright/Axe 27/27 通过，Axe 零 serious/critical；`git diff --check` 通过
- 结果：九种内容格式按上游、确定性规则、同次 AI、兜底顺序解析；图片保留原始总数且只展示最多 6 张本地缓存；短完整内容不再伪造展开，裁切/正文/媒体卡片提供可访问的展开、局部详情 Skeleton、列表内 404 降级和明确片段提示
- 控制面变更：API additive 增加 `content.format/format_origin` 与 `media.total_image_count/truncated`，Quiet Studio 增加格式/媒体/展开语义；无数据库迁移、历史回填、额外 AI 请求、VPS 部署或功能开关变更

### 2026-07-20 23:04 Codex
- 任务：将 OpenClaw 面板改为问答式发送、紧凑上下文摘要、原位停止操作，并用 Gateway 真实模型与推理档位替换浏览器模拟偏好
- 修改文件：OpenClaw 对话控制器与界面、Agent 草稿/交接投影、工作台响应式容器、生产工作台回归、`UI_CONTRACT.md`、D041 与本工作日志
- 执行验证：OpenClaw/Agent 聚焦 Vitest 34/34 通过；UI contract、ESLint（0 error、5 个既有 Fast Refresh warning）、TypeScript、Vite production build 与产物检查通过；1440/1024/390 受影响 Playwright/Axe 3/3 通过，并逐节点确认 Agent 面板无横向溢出
- 结果：发送后可见气泡仅保留用户问题及附件计数，V3 Gateway Prompt 与旧 handoff 历史均隐藏内部指令/ID；失败可重试或重新编辑，终止保留部分回复；上下文默认只展示两条并通过弹层管理八条；模型、上下文窗口、推理档位、默认值及会话覆盖全部来自 `models.list/agents.list/sessions.describe`，切换只调用当前会话的 `sessions.patch`
- 控制面变更：Agent 草稿升级到用户隔离的 v3 并忽略旧模拟模型偏好；未修改后端 API、数据库、权限、Query Key、MCP 协议或 OpenClaw 全局配置，未连接真实 Gateway、未调用外部模型且未部署 VPS

### 2026-07-20 23:47 Codex
- 任务：将内容/媒体与 OpenClaw 对话任务、Remote MCP/RSS 修复合并到独立本地集成分支
- 修改文件：两个功能提交的 55 个相关文件；`HandoffComposer.tsx`、`WORKLOG.md`
- 执行验证：两边分别收敛为 `686d64b`/`9d5d4a0`，在 `integration/content-openclaw-20260720` 无冲突合入；Python 538 项、前端定向 129 项通过；UI 合同修复后合同与 64 项受影响测试通过
- 结果：集成分支已保留两边历史和原始脏工作区；未切换共享 Docker；主目录原有文档归档等无关改动仍保持原状
- 未解决问题：两次 full gate 额度已用完；第二次仅剩 `App.lifecycle.test.tsx` 的旧 `useOpenClawChat` mock 缺少 `models/runtimeSelection` 字段，导致完整 Vitest 290/291，需用户确认后做定向修补与复验
- 控制面变更：无新增；仅合并两个任务已各自记录的 API/UI 合同和决策

### 2026-07-21 12:45 Codex
- 任务：修复 OpenClaw 模型选择与实际运行时不一致，增加 Feed 信息概览与“当天”视图，并以内容校验和消除 Instagram 图片重复缓存和展示
- 修改文件：OpenClaw 对话控制器与运行时选择、Feed 右栏状态机/概览/本地日期视图、媒体缓存与详情投影、生产工作台回归、`UI_CONTRACT.md`、`API_CONTRACT.md`、D042 与本工作日志
- 执行验证：UI contract、ESLint（0 error、5 个既有 Fast Refresh warning）、TypeScript、完整前端 Vitest、Vite production build、`tests/test_user_feed_store.py`、1440/1024/390 生产工作台 Playwright/Axe 27/27、测试影响映射与 `git diff --check` 通过；应用内浏览器真实 8080 验证宽屏概览、“当天”21/44 条切换与恢复、Agent 面板 `scrollWidth=clientWidth=359` 且无溢出子节点
- 结果：模型切换改为 `sessions.create` 保留上下文分叉并由 `sessions.describe` 验证，推理档位仅随 `chat.send` 发送；Feed 宽屏默认展示 360px 信息概览，侧栏新增浏览器本地自然日“当天”；内容图片按 workspace/user/article/kind/checksum 复用资产，详情继续防御性去重历史重复行
- 本地 RC：固定提交 `cb67308f9a7` 构建镜像 `inteliscope-service:local-cb67308-feed-insights-rc` / image ID `sha256:e14af4ccb57fbecdf5e9dc55f9932582e0775af3bd27e5ab554741bf5c01b754`；API/Worker 使用同一镜像并 healthy，live=`1.7.2-rc.1/cb67308f9a7`、database/worker ready；切换前 queued/running=0，数据库备份为 `data/backups/service.pre-cb67308-20260721T042444Z.db`
- 控制面变更：新增 D042 并更新 UI/API 真源；未新增数据库表、未删除历史媒体行、未修改权限、Query Key、MCP 协议或 OpenClaw 全局配置；本机 Gateway 未连接，因此未调用真实模型，也未部署或修改 VPS

### 2026-07-21 18:03 Codex
- 任务：先将 `feature/feed-insights-runtime-media-fix` 非 squash 合入最新本地基线，再实现 Quiet Studio 来源失败披露、低干扰滚动条、可调 Agent 右栏、浮动信息概览和 OpenClaw 对话保存
- 修改文件：订阅来源状态与页面测试、设计系统滚动条、工作台 Shell/信息概览/右栏偏好及测试、OpenClaw 对话归并与持久化及测试、生产工作台 Playwright、`UI_CONTRACT.md`、`PLAN.md`、D043 与本工作日志
- 执行验证：受影响 Vitest 78/78 通过，重复相同问题归并边界补测后 OpenClaw/Shell 23/23 通过；UI contract、ESLint（0 error、6 个既有 Fast Refresh warning）、TypeScript 通过；1440/1024/390 生产工作台 Playwright 27/27 通过；最终 `test_gate full` 22/22、0 failed/error、97.64 秒，`mapping_miss=false`。首次 full 调用因工作树未链接项目现有 `.venv` 而选中无 pytest 的系统 Python 3.14，在接入既有虚拟环境后完整重跑通过
- 结果：来源卡只保留可聚焦的失败状态，Tooltip 展示安全摘要、Dialog 按权限披露详情；所有独立滚动区使用透明轨道与悬停增亮滑块；桌面 Agent 栏可在 320–720px 内拖动或键盘调整、按账号保存且 Feed 至少 640px；概览仅在实测空白足够时会话内自动出现一次，Agent 打开后不抢占；用户问题与部分/完整回答按用户、Gateway 和会话隔离保存并与 Gateway 历史增量归并，重复相同问题仍保留为独立轮次
- 控制面变更：新增 D043、PLAN 第 56 项并更新全站 UI 真源；当前实现位于 `feature/quiet-studio-interactions`，未修改后端 API、数据库、权限、Query Key 或 Gateway/MCP 协议，未构建 RC、未部署 VPS、未推送远端

### 2026-07-22 00:49 Codex
- 任务：审计合并提交与运行容器差异，并完成 OpenClaw 用户轮次原子保存、动态 Agent 停靠和自然高度信息概览的交付加固
- 修改文件：OpenClaw 对话控制器及定向测试、工作台 Shell/右栏偏好/信息概览及测试、生产工作台 Playwright、`UI_CONTRACT.md`、`PLAN.md`、D044 与本工作日志
- 执行验证：首先确认本机 8080 的 API/Worker 均运行 `40e10da` 同一健康镜像，而后续 4 文件补丁尚未进入容器；补齐回归后 UI contract、ESLint（0 error、6 个既有 Fast Refresh warning）、TypeScript、定向 Vitest 30/30、Vite production build/产物检查、1440/1024/390 生产工作台 Playwright/Axe 27/27 与 `git diff --check` 通过
- 结果：用户气泡在 Gateway 请求开始前同步写入状态、内存引用和用户/Gateway/会话隔离记录，远端只返回助手消息也不会删除问题；Agent 在实测空间同时容纳 640px Feed、320px 右栏和分隔器时停靠，否则自动改为 Drawer；信息概览按有效内容自然增长，空分组隐藏，频道/类型默认前三项并可显式展开
- 控制面变更：新增 D044、PLAN 第 57 项并细化全站 UI 真源；不修改后端 API、数据库、权限、Query Key 或 Gateway/MCP 协议，不部署 VPS

### 2026-07-22 03:49 Codex
- 任务：复核合并前后代码完整性并修复 Gateway 同 ID 用户记录覆盖本地可见问题的回归
- 修改文件：`useOpenClawChat.ts`、对应 Vitest 与本工作日志
- 执行验证：功能分支 `34ab766` 与合并提交 `14c23a5` 相对共同基线的稳定 patch-id 均为 `10cfde3489401572c100d13de0313f8518280c60`；OpenClaw 定向测试连续 3 次均为 10/10 通过
- 结果：合并未丢失或改写来源分支补丁；对话归并现在只匹配相同角色，并在 Gateway 返回内部交接 Prompt 时保留本地用户问题与本地来源标识
- 控制面变更：无；尚未重建本地 RC，后续目标完成后统一切换 8080

### 2026-07-22 04:21 Codex
- 任务：重新审计合并前文件树、当前分支、未提交开发状态与 localhost:8080 运行镜像，确认用户看不到修改的直接原因
- 修改文件：仅本工作日志；未修改产品代码
- 执行验证：`34ab766^{tree}` 与 `14c23a5^{tree}` 同为 `7ba4214`；OpenClaw 10/10、当前新增 API 4/4、UI contract、ESLint（0 error）、TypeScript、Vite build、Python compileall 与 `git diff --check` 通过
- 结果：合并本身零文件差异；当前 HEAD=`7317da8`，另有 6 文件 +642/-7 的未提交后端改动，而 8080 仍运行 revision=`be54ee7` 的健康 RC，因此容器未包含最新 OpenClaw 修复和当前开发改动
- 控制面变更：无；本轮仅审计，不构建、不切换容器、不提交功能代码

### 2026-07-22 04:45 Codex
- 任务：固定来源分享、稳定内容复用、订阅停用处置、忽略集合与当前用户改密的后端基线
- 修改文件：Service API、订阅 mutation、Feed/内容存储、ServiceStore、API 合同、D045、定向 API 回归与本工作日志
- 执行验证：四条新增 API 回归 4/4、Python compileall 与 `git diff --check` 通过；同时复核 `34ab766` 与合并提交 `14c23a5` tree 完全一致
- 结果：私人来源可提升为 workspace/public 并按需查看引用；新订阅复用既有内容且不抓取；停用可收藏或忽略现有卡片；最后一个私人订阅取消后软停用僵尸来源；用户可恢复忽略内容并修改自己的密码
- 控制面变更：API additive 增加 share/usage、ignored、me/password 与 `on_disable/reused_item_count`，由 API 合同和 D045 固定；无数据库迁移、外网抓取或 VPS 变更

### 2026-07-22 07:14 Codex
- 任务：只读核对功能分支合并前后、当前提交与 localhost:8080 容器的真实差异
- 修改文件：仅本工作日志；未修改产品代码
- 执行验证：`34ab766` 与合并提交 `14c23a5` 的 tree 均为 `7ba4214`且 diff 为空；OpenClaw/Shell/右栏/App 定向 Vitest 84/84、新增 API 4/4、UI contract、TypeScript 与 `git diff --check` 通过
- 结果：合并未丢失代码；当前分支 HEAD=`3138295`，8080 仍运行 `7317da8-dirty` 旧镜像，因此容器没有包含后续 `aa6da79`/`3138295` 改动；当前整批需求尚未全部完成

### 2026-07-22 12:19 Codex
- 任务：收口来源分享/订阅生命周期、忽略集合、用户管理、Feed 排序与动作语义、任务上下文以及宽屏概览与 Agent 共存，并修复完整门禁中的兼容回归
- 修改文件：Quiet Studio UI 契约、设置/订阅页、Feed 展示模型与偏好、虚拟列表、工作台 Shell、Agent 上下文、信息概览、订阅 mutation 及对应前后端测试
- 执行验证：新增来源生命周期 API 4/4、受影响前端 129/129、生命周期回归 1/1 通过；最终 `test_gate full` 22/22、0 failed/error、96.729 秒，涵盖 Python full、UI contract、ESLint、TypeScript、完整 Vitest、Vite build、Compose、Playwright/Axe 与 `git diff --check`
- 结果：分享来源复用内容并阻止私人僵尸来源；订阅可独立停用并选择保留或忽略卡片；忽略内容仅在设置恢复；Feed 可按发布时间/入库时间排序且反转顺序保持阅读锚点；评分与标记已读 UI 隐藏；任务可加入 OpenClaw 上下文；卡片动作使用延迟说明和固定紫色上下文图标；宽屏信息概览与 Agent 栏可同时显示
- 控制面变更：更新 Quiet Studio 全站 UI 真源；API、数据库结构、权限、Query Key 与 Gateway/MCP 协议保持不变，尚未推送远端或部署 VPS

### 2026-07-22 13:32 Codex
- 任务：修复干净 Linux ARM Docker 构建遗漏 `lightningcss` 原生可选依赖的问题
- 修改文件：`Dockerfile` 与本工作日志
- 执行验证：在 `node:22-slim` ARM 容器中以现有 lockfile 执行 `npm ci --include=optional`，365 个包安装成功且 `lightningcss-linux-arm64-gnu` 存在
- 结果：前端构建阶段显式安装 lockfile 中的平台可选包，避免无缓存构建因缺少原生模块失败；未修改运行时依赖版本
- 控制面变更：无；仅收紧 Docker 构建可复现性

### 2026-07-22 16:14 Codex
- 任务：在独立分支实现硬刷新稳定首帧、固定几何 Feed/Agent Skeleton 与局部内容浮现
- 修改文件：HTML/bootstrap 壳、应用认证接管、设计系统加载模式、工作台 Feed/Agent、布局偏好、Vitest/Playwright、`UI_CONTRACT.md`、D046、影响映射与本工作日志
- 执行验证：聚焦 Vitest 105/105、刷新专项 Chromium 1/1、UI contract、ESLint（0 error、6 个既有 Fast Refresh warning）、TypeScript 与差异审查通过；最终 `test_gate full` 22/22、0 failed/error、108.835 秒，`mapping_miss=false`
- 结果：首帧直接绘制原背景和上次导航/可停靠右栏布局；数据区以 1.4 秒低干扰呼吸占位，120 ms 淡出并由内容以 200 ms/4 px 局部浮现；Feed 和 Agent 宽度在静态壳、Skeleton 与真实内容间保持稳定，窄屏不自动弹出 Drawer
- 未解决问题：单独运行既有生产工作台全链路用例仍会命中 HeroUI Tooltip 包装层的重复 button 角色；已在不含本次修改的 `4d66886` 临时 worktree 同样复现并清理。继续执行后还会被同根因的 Axe `nested-interactive` 阻断；刷新专项不依赖该路径，本分支未扩大范围修复
- 控制面变更：新增 D046 并更新 Quiet Studio 加载真源；无 API、数据库、权限、Query Key、Gateway/MCP、部署或运行容器变化

### 2026-07-22 16:26 Codex
- 任务：构建稳定刷新分支的本地 Docker 镜像并切换 localhost:8080 供人工验收
- 修改文件：仅本工作日志；运行态重建本地 API/Worker，未修改业务数据或远端
- 执行验证：无缓存 Docker build、前端 production build/产物检查通过；API/Worker 同 image ID `sha256:4408576a9b2c` 且 healthy，live=`1.7.1/a3711b0d1beb-stable-refresh`、database/worker ready、integrity=ok、queued/running=0；`/feed` 初始 HTML 包含导航、标题、Feed、Agent bootstrap 区域
- 结果：本地 8080 已切换至 `inteliscope-service:local-a3711b0d1beb-stable-refresh`，旧镜像 `inteliscope-service:local-4d668868a283` 保留用于回退
- 控制面变更：无；未部署 VPS、未推送分支、未触发来源抓取、AI、付费调用或任务调度

### 2026-07-22 16:34 Codex
- 任务：复现并定位 Web 工作台挤压 OpenClaw 输入区的问题，准备快速重构方案
- 修改文件：仅本工作日志；尚未修改产品代码
- 执行验证：在 localhost:8080 的应用内浏览器复现窄屏 Agent Drawer，并核对已连接态 composer、运行设置控件、320–720px 可调右栏及 360px Drawer 实现
- 结果：输入框本体已独占整行，主要拥挤源是 composer 底部把动态模型/推理标签与固定发送按钮绑定在同一横向 flex；单纯加宽右栏会继续挤压 Feed，待确认后改为稳定的分层输入布局
- 控制面变更：无；未连接 Gateway、未调用模型、未重建容器或修改远端

### 2026-07-22 16:45 Codex
- 任务：执行已确认的 A 方案，重构 Web OpenClaw composer 并更新本地 Docker 预览
- 修改文件：OpenClaw 对话组件与聚焦测试、设计规格、执行计划及本工作日志；本机 API/Worker 切换至新镜像
- 执行验证：OpenClaw 基线 11/11；新增布局合同依次完成两轮 RED→GREEN，OpenClaw/Shell 30/30、完整前端 Vitest 321/321、TypeScript、production build/产物检查与 `git diff --check` 通过；Docker image=`sha256:8eefec3932fa`，API/Worker healthy，live=`1.7.1/56f62ea5e311-openclaw-composer`、database/worker ready；8080 bundle 含 composer grid 标记，548px Agent Drawer `scrollWidth=clientWidth=548` 且溢出节点 0
- 结果：输入区获得 96px 稳定最小高度；运行设置与 36px 发送/停止动作使用显式 `minmax(0,1fr) + 36px` 工具栏轨道，长模型名只在自身区域截断，不再参与挤压按钮或输入区；Feed 与 Agent 右栏宽度保持不变
- 未解决问题：当前应用内浏览器没有已配对 Gateway，连接页可见但未代替用户连接；连接成功后即可直接查看已部署的 connected composer
- 控制面变更：仅更新本地 UI 与 Docker 运行态；未修改 API、数据库、权限、Query Key、Gateway/MCP 协议、远端或 VPS，未触发模型调用、来源抓取或付费操作

### 2026-07-22 16:58 Codex
- 任务：根据 Chrome 已连接长对话截图，修复 transcript 争抢高度导致 OpenClaw composer 被压缩裁切的问题并重新部署
- 修改文件：OpenClaw 对话组件与长历史回归测试、UI 契约、执行计划及本工作日志；本机 API/Worker 切换至新镜像
- 执行验证：24 条长历史回归先因缺少 `flex-1` 精确 RED，修复后 OpenClaw 13/13、完整前端 Vitest 322/322、TypeScript、production build/产物检查与 `git diff --check` 通过；Docker image=`sha256:d1dd43f2913f`，API/Worker healthy，live=`1.7.1/93fc44e180a7-openclaw-dock`、database/worker ready；8080 bundle 为 `index-CaGmP4KC.js` 并包含 `openclaw-composer-dock`
- 结果：已连接长对话现在由 transcript 独占剩余高度并内部滚动，composer dock 禁止收缩、完整固定在面板底部；未修改右栏宽度、消息语义或 Gateway 行为
- 未解决问题：当前环境没有可接管的 Chrome 浏览器连接，需用户在现有已配对 Chrome 标签页强制刷新后进行最终视觉确认
- 控制面变更：仅更新本地 UI 与 Docker 运行态；未修改 API、数据库、权限、Query Key、Gateway/MCP 协议、远端或 VPS，未触发模型调用、来源抓取或付费操作

### 2026-07-22 17:05 Codex
- 任务：将用户确认的 `feature/stable-refresh-loading` 快进合入本地 `main`，并清理废弃开发分支与 worktree
- 修改文件：仅本工作日志；目标功能树由 `ddbdb39` 原样进入 `main`
- 执行验证：合并后 `test_gate full` 22/22、0 failed/error、104.142 秒，覆盖 Python、前端 Vitest/TypeScript/build、UI contract、Compose、Playwright/Axe 与差异检查
- 结果：稳定刷新与固定 OpenClaw composer 已进入 `main`；`feature/multi-user-mvp-core` 的未提交内容未混入，保留为本地恢复 stash 后按用户指示清理其他本地分支/worktree
- 控制面变更：无新增；未推送远端、未删除远端分支、未修改当前 localhost:8080 运行镜像

### 2026-07-22 17:12 Codex
- 任务：从本地 `main` 无缓存构建 Docker 镜像并切换 localhost:8080，同时确认原数据库数据保留
- 修改文件：仅本工作日志；本机 API/Worker 切换至 main 镜像，未修改数据库内容
- 执行验证：production Docker build 通过；API/Worker 使用同一 image ID `sha256:25ae1e833561` 且 healthy，live=`1.5.0/c762fea20268-main`、database/worker ready，`/feed` 返回 200；宿主机 `data/` 继续 bind mount，`service.db` 9.0 MB、SQLite quick check=`ok`，3 个用户、9 个订阅、89 个 Feed 快照和 662 条 Feed 记录仍在
- 结果：本地 8080 已运行 `inteliscope-service:local-c762fea20268-main`，稳定刷新与固定 OpenClaw composer 可直接刷新验收；未执行 `down -v`、未删除 volume 或数据库
- 控制面变更：无；未推送远端、未部署 VPS、未触发抓取、AI、付费调用或调度

### 2026-07-22 18:11 Codex
- 任务：提交稳定刷新/OpenClaw UI 修复至 `main`，并以保留生产数据库的方式发布到 `vps-tokyo`
- 修改文件：Tooltip 触发器与相关 Vitest、生产 Playwright/发布配置、本工作日志；VPS 新增 revision-locked release、镜像和权限受限备份
- 执行验证：正式 `test_gate release` 24/24、192.451 秒；`origin/main=614793f045a8`；本机 Buildx 产出 `linux/amd64` 镜像包并以 SHA-256 `7f0f8bd7…e54f` 双端校验，脱敏 staging 的 live/ready、7 路由、401、integrity/foreign-key/active-job 与高风险开关均通过；生产 API/Worker 同 image ID `sha256:41764b04502d…8f945`、healthy、0 restart，公网 7 路由 200、受保护 API 401、严重日志匹配 0
- 结果：`/opt/inteliscope/current` 已指向 `/opt/inteliscope/releases/v1.7.1-614793f045a8`；生产库仍为 16,568,320 bytes、1 用户、3 会话、integrity=`ok`、foreign-key=0、queued/running=0；切换前备份位于 `/opt/inteliscope/backups/pre-v1.7.1-614793f045a8-20260722T095658Z`，数据库 SHA-256 `09904e14…5b81`，旧 release/image 保留
- 发布纠偏：首次沿用旧 `release_rc1.sh` 在 VPS 构建，虽构建成功但切换断言失败并自动恢复旧版；随后按用户要求改为本机跨架构构建、传包、`docker load` 后成功发布；当前 `AGENTS.md` 尚未明确“禁止 VPS 构建”，旧脚本仍执行远端 build，建议单独固化该发布规则并同步脚本
- 控制面变更：无；Remote MCP、订阅写入、Browser Chat 保持关闭，未启动 scheduler，未手动触发来源抓取、AI、付费调用或数据库恢复

### 2026-07-22 21:38 Codex
- 任务：为测试/生产共用 OpenClaw Gateway 的会话标签冲突建立隔离修复分支与设计规格
- 修改文件：新增会话隔离设计规格并更新本工作日志；创建 `codex/fix-openclaw-session-isolation` 独立 worktree，尚未修改业务代码或运行环境
- 执行验证：新 worktree 安装前端依赖与隔离 Python 开发环境；未修改代码的 `test_gate full` 22/22 通过、0 failed/error、179.436 秒
- 结果：固化已批准的站点来源化唯一标签、单次冲突重试、分阶段设备/session 凭据保存、真实错误提示、无旧会话接管/删除以及测试与双环境发布边界
- 未解决问题：按设计流程等待用户复核书面规格，批准后编写实施计划并开始 RED→GREEN 修复
- 控制面变更：仅新增设计规格；UI 合同和决策记录将在实际行为实现时同步更新

### 2026-07-22 22:21 Codex
- 任务：核对 VPS 已知正常版本与当前 OpenClaw 修复分支基线之间的 UI 差异
- 修改文件：仅本工作日志；未修改产品代码或运行环境
- 执行验证：VPS current/live/容器均确认运行 `c762fea20268`；VPS 保留的 `c762fea` 与 `614793f` 镜像标签、release 源码哈希一致；Git 逐提交比对确认两者之间只有 `dc6719b` 修改业务 UI，其余提交仅修改测试或文档
- 结果：当前分支以 `de8b146` 为基线，继承了 `dc6719b` 对 Feed 卡片、订阅页和 OpenClaw Tooltip trigger/DOM 的 UI 回归；VPS 使用回退后的 `c762fea` 因而显示正常，当前分支暂停部署
- 控制面变更：无；未切换 VPS 镜像、未修改数据库、未运行调度或模型调用

### 2026-07-23 00:13 Codex
- 任务：为新增“令牌吊销后删除”要求核对现有凭据流程与 OpenClaw 2026.7.1 本机协议实现
- 修改文件：仅本工作日志；尚未修改产品代码、权限合同或运行环境
- 执行验证：确认当前“忘记此浏览器”只清理 transcript/IndexedDB；OpenClaw 提供 `device.token.revoke` 与 `device.pair.remove`，两者均要求当前未申请的 `operator.pairing`，且非管理员只能管理自身 operator 设备
- 结果：因助手连接页同时存在 OpenClaw device token 与 Inteliscope Remote MCP token，需先确认目标令牌再确定最小权限与失败语义
- 控制面变更：无；未扩大 scope、未吊销或删除任何真实凭据

### 2026-07-23 00:27 Codex
- 任务：无缓存构建并启动当前 OpenClaw 会话隔离分支的本地 Docker 预览
- 修改文件：仅本工作日志；本机 API/Worker 从 `653b1e4d3fc6-openclaw-latest` 切换到当前分支镜像，原数据、`.env`、日志与旧镜像保留
- 执行验证：production build/产物检查通过；API/Worker 同 image ID `sha256:9a415fba3d36…05ec`、healthy、0 restart，live=`1.7.1/32a4d7fd881b-openclaw-session`、ready；7 个页面 200、受保护 API 401、SQLite integrity=`ok`、foreign-key=0、queued/running=0、数据计数 `3/9/89`、scheduler 未运行、严重启动日志 0；bundle `index-BZVDMzrl.js` 含唯一标签与会话冲突映射，Gateway 2026.7.1 probe=ok
- 结果：`localhost:8080` 已运行本分支，可立即验证测试/生产共享 Gateway 的连接修复；附带的服务端吊销后本地删除仍处于已批准规格阶段，尚未进入该镜像
- 回退与备份：旧镜像 `inteliscope-service:local-653b1e4d3fc6-openclaw-latest` 保留；切换前数据库备份为 `data/backups/pre-openclaw-session-20260722T162525Z.db`，SHA-256 `45bf812a…b87`
- 控制面变更：无；未修改 VPS、数据库内容或功能开关，未启动 scheduler、来源抓取、模型或付费调用

### 2026-07-23 00:52 Codex
- 任务：续完 OpenClaw 测试/生产共用 Gateway 的连接修复，并新增服务端设备移除成功后再删除本地凭据
- 修改文件：OpenClaw Gateway scope 协商、凭据仓、聊天 Hook、设备移除服务、助手连接确认 UI 与测试；同步 UI 合同、D048 和实施计划
- 执行验证：修复分支已从 `de8b146` 安全迁移到 VPS 已知正常基线 `c762fea20268`，确认不含 UI 回归 `dc6719b`；scope RED 5 项、device service RED 1 suite、Hook/UI RED 各 1 组后转 GREEN；定向 29/29、前端 42 files/338 tests、lint 0 error、TypeScript、production build 通过；`test_gate full` 22/22、0 failed/error、99.485 秒
- 结果：所有新会话使用来源化唯一标签并只对明确冲突重试一次；新授权精确请求 read/write/pairing，旧 read/write 凭据继续普通重连；“忘记此浏览器”确认后只调用当前 identity 的 `device.pair.remove`，成功或 unknown-device 才清 transcript/IndexedDB，其他失败完整保留本地恢复状态
- 控制面变更：`UI_CONTRACT.md` 与 D048 固化最小 pairing scope、旧凭据兼容和服务端优先删除语义；Remote MCP、订阅写入、Service API、数据库、scheduler、模型与 VPS 均未修改
