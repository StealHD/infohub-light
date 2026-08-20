<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/api/ -->
# Inteliscope InfoHub Light API / 接口合同

## 0. 任务读取路由

先读本索引获取公共原则、标识、CLI 与本地配置契约；再按接口主题进入以下模块。


<!-- init-pro:section name=interface -->
## 1. 文档目的
本目录定义当前 FastAPI、Worker、React UI、Remote MCP、Service DB 与运维接口。产品面是来源获取、用户 Feed/History、通知、存储治理和受控 Agent 集成；历史 CLI、静态站、scheduler、本地 stdio MCP、Graph/archive analytics 与偏好 feedback 已退役。

## 2. 公共原则
1. 入口层只接收、校验并编排；领域规则位于 Service/Store。
2. Service API 成功返回 `{"ok":true,"data":...}`，失败返回 `{"ok":false,"error":{"code","message","retryable","action"}}`；未知 `/api/*` 同样返回 `not_found` envelope。
3. 外部字段先规范化为 `ContentItem` 或 source config；新字段使用 `channel/topics`，Service DB snapshot 读取继续兼容 `category/tags`。
4. 密钥、目的地、上游正文和原始异常不得进入公开响应、日志或配置 JSON。
5. breaking change 必须由 `docs/decisions/` 记录，并同步 OpenAPI、测试、合同、产品手册与 changelog。

## 3. 标识与幂等
1. `ContentItem.id` 与 `article_id` 使用稳定 `{source}:{subtype}:{native_id}`；`normalized_url` 只作内容身份与去重证据。
2. `source_catalog.source_key` 由 `src/services/source_type_registry.py` 生成，同一操作者重复/并发写入必须返回同一 source，不能跨用户接管 private source。
3. Feed snapshot 以非空 `job_id` 幂等，snapshot item 以 `article_id` 去重；Source Health 与通知 outbox 使用各自 ledger/唯一键抑制重放。
4. 会创建 Job、调用付费 Actor 或发送通知的接口必须明确幂等键、超时后的安全重试方式和未知结果的 fail-closed 行为。

## 4. 当前运行入口与配置
1. 可安装入口仅为 `horizon-api` 与 `horizon-worker`；HTTP `/mcp` 由 Remote MCP 模块承载。默认 Docker 入口是 `horizon-api`，Compose 只运行 API/Worker。
2. `src/services/config_runtime.py` 负责 `data/config.json` 的读取、校验、结构化 action 与环境变量状态；`src/services/source_probe.py` 负责不保存、不调用 AI 的来源探测。
3. `GET /api/config` 不返回 `email/webhook/premium_analysis/article_graph` 旧块；结构化 action 必须保留磁盘中未知旧块原文，不主动迁移或删除。旧块不再执行。
4. `GET /api/feed/{latest,history,search}` 只通过强制注入 `ServiceStore` 的 `FeedReadService` 读取；payload 由 `feed_payload.py` 生成。Service DB snapshot 的双读兼容保留，但不存在 `data/site` 或 `ArticleStore` fallback。
5. `/?view=`、`/later` 与 `/settings/legacy` 只是 React 历史书签重定向，不恢复旧 UI 或旧 API。

## 5. 已退役边界
1. `horizon`、`horizon-web`、`horizon-scheduler`、`horizon-mcp`、`horizon-wizard`、`horizon-webhook` 与 `horizon-sources` 不再安装；旧静态资产、publisher、Graph/fulltext/ArticleStore、旧通知和本地 MCP 模块不存在。
2. `/api/archive/{graph,items,trends,facets,source-quality}` 与 `POST /api/me/items/{id}/feedback` 返回统一 404，且不进入 OpenAPI。
3. React 是唯一 UI。构建目录缺失时 API 仍可启动，非 API 页面返回 404；不存在环境变量切换或静默 legacy fallback。
4. 现存 `data/site/**`、`data/horizon.db`、summaries 和旧 MCP runs 是 inert operator data。当前初始化、读取与迁移不得访问、改写、DROP 或 DELETE；物理清理需要独立授权。
5. `data/archives` 与 `/api/admin/storage/*` 是现役冷归档/恢复能力，不属于上述退役 archive analytics。

## 6. 通用错误与兼容合同
公共错误至少表达稳定 code、人类可读说明、可执行下一步与 retryable；参数缺失、格式错误、业务冲突和外部失败必须区分。当前单版本仍保持新增字段向后兼容，并明确缺省值；删除字段或接口必须有决策、负向回归与 OpenAPI 证据。

## 模块索引

| 任务 | 模块 |
| --- | --- |
| 登录、成员、catalog、Feed、配置、health | [Service 核心](service-core.md) |
| Remote MCP delegation、工具和权限 | [Remote MCP](remote-mcp.md) |
| Browser OpenClaw Gateway 与图片媒体票据 | [Browser OpenClaw Gateway](openclaw-gateway.md) |
| Feed/Source 周期、通知、Source Health | [Schedule、Job 与通知](schedules-jobs-notifications.md) |
| 密钥、AI、source catalog 与 Job 细则 | [Service 配置与任务](service-secrets-source-jobs.md) |
| Feed、历史、Presentation、媒体与存储 | [Feed、历史、Presentation 与存储](feed-history-presentation-storage.md) |
| 后台任务、迁移、DeepSeek 与 ActorOps | [Job、迁移与 ActorOps](jobs-migrations-actorops.md) |
| ActorOps auto-pool 退役、双确认与 global 25 惰性兼容 | [ActorOps auto-pool 退役](actorops-retired-auto-pool.md) |
| ActorOps v2 stable-fetch、Adapter、global 26 与站立授权计划合同 | [ActorOps v2 计划合同](actorops-v2-planned.md) |
