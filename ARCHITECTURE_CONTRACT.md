# Inteliscope InfoHub Light 架构合同

## 1. 文档目的
本文件定义系统职责分层和不可跨越的边界。代码实现应优先遵循现有模块形状，只有在边界变化时才更新本文件。

## 2. 默认分层
当前默认分层：

1. API / CLI / event 入口层：`src/main.py`, `src/ui/server.py`, MCP adapter。只负责参数接收、校验和薄编排。
2. Service 层：`src/orchestrator.py`, `src/services/**`。负责抓取、去重、分析、发布、单源刷新、全文抓取、关系图等流程编排。
3. Domain 层：`src/models.py`, `src/tag_policy.py`, `src/source_selection.py`。负责标准模型、taxonomy、source ref、状态和规则输入输出。
4. Adapter / Integration 层：`src/scrapers/**`, `src/ai/**`, webhook/email/openbb/apify client。隔离外部系统字段、协议和失败模式。
5. Storage 层：`src/storage/**`, `data/site/**`, `data/horizon.db`。隐藏持久化细节和兼容迁移。
6. Output / Reporting 层：`src/ui/site.py`, `src/ui/static/**`, summaries, webhook rendering。负责输出组装和渲染，不直接采集数据。

## 3. 关键边界
### 3.1 Source Adapter Boundary
Scraper 输出必须是 `ContentItem`，外部字段只能放入明确 metadata。上层不得直接依赖 RSS/GitHub/Reddit/Telegram/Apify/OpenBB 的原始结构。

### 3.2 Taxonomy Boundary
Hub taxonomy 的唯一规范入口是 `src/tag_policy.py`。业务层和 UI 可以消费 `channel/topics/signal_strength/signal_type/entities`，但不得散落自定义 normalization。

### 3.3 AI Boundary
AI prompt 与解析位于 `src/ai/**`。`personal_tags` 只能作为用户偏好信号，不得进入 AI scoring prompt。AI cache 必须随 prompt schema 变化 bump version。

### 3.4 Static UI Boundary
静态 UI 只消费 `radar-data.json`、history JSON 和 article graph JSON，不直接调用 scraper、AI client 或 storage。

### 3.5 Archive Boundary
`ArticleStore` 负责 SQLite schema、migration、upsert 和 load compatibility。上层不得手写 SQL 访问 `articles_light`，除非是测试或运维诊断。

## 4. 禁止事项
1. 禁止入口层直接访问外部系统细节。
2. 禁止输出层反向驱动领域模型。
3. 禁止规则散落在路由、命令入口或模板中。
4. 禁止把某个运行时来源的字段命名作为全系统标准命名。
5. 禁止在 Web UI JS 中重新实现 Python taxonomy 规则。
6. 禁止把成本型流程作为 light runtime 的默认副作用。

## 5. 扩展原则
新增来源、规则、输出或存储时，应先扩展抽象合同，再实现具体适配。

具体要求：

1. 新 source adapter：更新 source config model、adapter、tests，必要时更新 `API_CONTRACT.md` 和 `project-defaults.yaml`。
2. 新 taxonomy 字段：先更新 `tag_policy.py`、`ContentItem`、static payload、archive contract，再更新 UI。
3. 新输出面：先定义 static JSON 或 API contract，再做 UI。
4. 新成本型能力：必须有配置开关、低成本验证路径和 degrade 行为。
