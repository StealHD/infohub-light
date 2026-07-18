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
