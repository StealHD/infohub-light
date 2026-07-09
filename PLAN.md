# Inteliscope InfoHub Light 实施计划

## 1. 计划目的
本文件定义当前阶段、实施顺序和默认验证策略。后续 agent 应以本文件作为开发入口之一，但不得用它覆盖更细的 API、架构、上下文和决策合同。

## 2. 当前阶段状态
结论：当前阶段是小团体多人可用的私人信息高定服务 MVP 内核。

已完成：

1. Light runtime 方向：默认只启动 Web，避免误启 scheduler。
2. No-AI / personal-only 成本护栏。
3. Hub taxonomy 基础：`channel/topics/signal_strength/signal_type/entities`，并保留 `category/tags` 兼容。
4. 静态阅读 UI 的频道优先筛选。
5. `ArticleStore` 对 Hub taxonomy 字段的归档落库。
6. init-pro 控制面初始化。
7. FastAPI service API 入口、Service SQLite 库、单 workspace 用户体系、公共/私有订阅源市场、用户订阅配置、SQLite job queue、配额记录、feed/archive API facade。
8. 配置页 Service API 兼容层：`/api/config` 投影 service catalog/subscriptions 为旧 UI 结构，source action 写入 service tables，测试/更新按钮创建 queued jobs。
9. 登录后的订阅控制台 MVP：公共源市场、我的订阅、私有 RSS 源创建、任务队列和手动刷新入口。
10. Worker/job queue 加固：SQLite lease、stale running 恢复、失败重试退避、取消、重试和任务保留清理。
11. 用户作用域 Feed 与归档分析 API v1：`user_feed_snapshots/user_feed_items`、用户可见 archive items/trends/facets/source-quality、管理员 `user_id` 排查和订阅页 API 状态面板。
12. Source Catalog API v1：`source_type_registry`、`source_key` 幂等导入、catalog config 校验、旧 `data/config.json` 高级源导入和订阅页高级源最小测试面板。
13. 真实源验证 v1：catalog `source_fetch` 按 `source_id` 精准合成用户作用域单源配置，Worker 保存用户 feed snapshot，并提供 RSS/Hacker News/GitHub Releases/Telegram 的 Service API smoke 脚本。
14. 基本功能 API 收口 v1：当前用户 feed item 的已读、收藏、稍后读、忽略和反馈入库，并在静态阅读页提供最小操作按钮。
15. 核心 Service API 验收与权限矩阵 v1：统一 `/api/*` validation/404 error envelope，补齐角色权限矩阵测试，并新增无外网依赖的核心 API smoke 脚本和 curl 文档。

当前仍需推进：

1. 在 Docker 本地环境中固定运行 `service_api_smoke.py` 与 `service_real_source_smoke.py` 的组合验收。
2. 后续再决定是否把用户行为信号用于个人排序或推荐；当前不改排序。
3. 对登录、订阅、阅读三个静态页面做小范围可用性修补，不引入复杂前端工程。
4. 清理或归档过期计划，保持唯一真源。

## 3. Agent 开工前默认读取
默认先读：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. 当前任务直接相关代码
5. 当前任务直接相关测试

按需再读：

1. 架构任务：`ARCHITECTURE_CONTRACT.md`
2. 决策核对：`DECISION_LOG.md`
3. 上下文策略任务：`CONTEXT_READ_RULES.md`
4. 真实数据验证：`docs/dev/hub-taxonomy-real-run.md`

默认不读：

1. `data/site/history-data.json`
2. `data/site/history/**`
3. `data/horizon.db`
4. `logs/**`
5. `.env*`
6. `.venv/**`
7. 不相关 Markdown

## 4. 当前实施范围
本阶段继续做：

1. 小团体用户、角色、公共源市场和个人订阅配置。
2. Hub taxonomy 与 legacy alias 的兼容迁移。
3. 来源配置、抓取任务、AI 分析、静态 UI、SQLite 归档之间的稳定字段合同。
4. 低成本验证路径、任务队列、配额记录和明确的 capability / degrade 表达。
5. 面向长期归档分析的最小可查询 API。

本阶段不做：

1. 第三方 AIHub/AIHOT API 逆向或依赖。
2. 私密群组、好友流、cookie、session、账号密码采集。
3. 未确认的生产推送、邮件群发或 scheduler 启动。
4. 大规模 embedding、实时模型图谱、复杂可视化，除非单独立项。
5. 多 workspace、商业计费、自助注册或复杂前端工程化。

## 5. API / 模块实现优先级
当前优先级：

1. 稳定 `/api/*` service API envelope、鉴权、权限和错误语义。
2. 稳定 Service SQLite schema、用户、订阅源市场、用户订阅和 job queue。
3. 稳定从 catalog/subscription 合成现有 `Config` 的兼容路径。
4. 稳定 source type registry、`source_key`、旧配置导入和 Worker payload 生成。
5. 稳定静态 UI 只通过 `/api/*` 读写数据和配置。
6. 稳定 `ArticleStore` 归档字段与旧库迁移。
7. 用目标测试覆盖每个兼容边界。

## 6. 当前实现强约束
1. 不得把外部系统原始字段扩散到业务层。
2. 不得把 taxonomy、阈值、成本开关写死在入口层。
3. 不得让输出层直接访问运行时来源。
4. 不得静默跳过能力缺口，必须显式表达 capability / degrade、unsupported 或 unknown。
5. 不得读取大历史数据或启动 scheduler，除非任务明确要求。
6. `personal_tags` 不进入 AI prompt。
7. `category/tags` 只作为兼容 alias；新实现应优先读写 `channel/topics`。

## 7. 建议测试顺序
1. 运行当前任务相关单测。
2. 运行 Python 或 JavaScript 语法检查。
3. 运行受影响范围的回归测试。
4. 如涉及静态 UI，验证 `data/site/radar-data.json` 字段兼容。
5. 如涉及归档，验证 `articles_light` schema 和旧库迁移。
6. 如涉及控制面，运行 init-pro validator。

## 8. 执行后可视化校验
完成控制面、阶段计划、接口合同或架构合同修改后，生成一次控制面校验报告：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" \
  --project-root . \
  --primary-config project-defaults.yaml \
  --output INIT_PRO_VALIDATION.md
```

报告会输出：

1. 控制文件覆盖检查
2. 默认读取范围检查
3. API 错误 / 兼容 / 幂等 / 后台任务合同检查
4. `WORKLOG.md` 和主 YAML 记录检查
5. Mermaid 约束图与业务变更影响图
