<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=CONTEXT_READ_RULES.md -->
# Inteliscope InfoHub Light 上下文读取规则

## 1. 文档目的
本文件用于控制 agent 在本项目中的上下文读取范围，减少无效 token 消耗。

目标不是极限省 token，而是：

1. 避免重复读取低价值文件。
2. 优先读取高价值控制文件和关键代码入口。
3. 让每轮只读与当前任务相关的最小集合。
4. 避免误读私密数据、历史大文件和运行日志。

## 2. 开发 token 预算策略
本文件是开发上下文 token 预算的唯一真源。后续 agent 应先根据任务类型选择最小读取集，再逐步扩展，不应把控制面文件当作每轮都要完整读取的背景材料。

默认原则：

1. 先用精准 `rg` 定位入口，再读文件片段。
2. 默认读取控制文件不超过 3 个。
3. 默认初始 Markdown 读取不超过 2 个。
4. 默认搜索结果控制在 120 行以内；需要更多时改窄路径或关键词。
5. 先跑目标测试，最后再跑全量测试。
6. 只有控制面变化才更新控制文件；普通功能开发只追加短 `WORKLOG.md`。

<!-- init-pro:section name=required-context -->
## 3. 默认必读文件
对于绝大多数普通编码任务，默认只需要先读这些内容：

1. `PLAN.md`
2. `project-defaults.yaml`
3. `CONTEXT_READ_RULES.md` 中匹配任务类型的条目

随后只读当前任务相关代码和测试。

`API_CONTRACT.md` 不再作为普通编码任务的默认必读文件。只有任务涉及 `/api/*`、CLI/public payload、错误 envelope、权限、job 状态、兼容合同或外部接口时才读取。

## 4. 第二层按需读取文件
只有在任务确实涉及对应边界时，再读以下文件：

1. `AGENTS.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `DECISION_LOG.md`
4. `docs/dev/hub-taxonomy-real-run.md`
5. `API_CONTRACT.md`
6. 当前任务相关代码
7. 当前任务相关测试

## 5. 默认不需要读取的文件
以下内容默认不应读入上下文：

1. 虚拟环境目录
2. 包管理器缓存
3. 测试缓存
4. 构建产物
5. `.env` / `.env.*`
6. 本地 agent 设置文件
7. `archive/**`
8. `data/site/**`
9. `data/*.db`
10. `logs/**`
11. `uv.lock`
12. cached media
13. generated summaries
14. 历史 smoke report
15. 不相关 Markdown
16. 多数空壳包声明文件

如确实需要追溯历史，先对 `archive/worklog`、`archive/legacy-worklog` 或 `archive/project-history` 中的目标子目录使用精确 `rg`，只读取命中片段，不整文件读取归档。

## 6. 任务类型最小读取集

| 任务类型 | 默认最小读取集 |
|---|---|
| 普通代码小改 | `PLAN.md` 当前阶段摘要、`project-defaults.yaml` 相关段落、目标代码、目标测试 |
| API / CLI / payload | `PLAN.md`、`API_CONTRACT.md` 相关章节、API/CLI 入口、对应 service、接口测试 |
| Worker / job queue | `PLAN.md`、`project-defaults.yaml` cost/job 段、`src/services/worker.py` 或 `src/services/job_queue.py`、对应测试 |
| 日志 / 故障排查 | `PLAN.md`、`docs/dev/observability-logging.md`、目标 API/Worker/MCP/transport 文件、`scripts/check_observability_contract.py`、对应测试 |
| Storage / migration | `PLAN.md`、`ARCHITECTURE_CONTRACT.md` archive/storage 边界、目标 storage 文件、对应测试 |
| React UI | `UI_CONTRACT.md`、目标 `frontend/src/*` 文件、匹配的 Vitest/Playwright 测试 |
| Legacy 静态 UI | `PLAN.md`、`project-defaults.yaml` output 段、目标 `src/ui/static/*` 文件、`tests/test_static_reading_ui.py` |
| Scraper / adapter | `PLAN.md`、`ARCHITECTURE_CONTRACT.md` adapter 边界、`src/models.py` 相关模型、目标 scraper、匹配测试 |
| Docker / 部署 | `PLAN.md`、`project-defaults.yaml` runtime/verification 段、目标 compose/script、light runtime 测试 |
| 测试修复 | 失败测试、被测代码、最小相关 fixture；不要先读全仓合同 |
| 控制面变更 | `project-controls.json`、目标 topic 的唯一真源；只有规则或理由变化时再读 `AGENTS.md` / `DECISION_LOG.md` |

## 7. 推荐读取策略
### 7.1 普通编码任务
默认读取：

1. `PLAN.md`
2. `project-defaults.yaml`
3. 当前要改的代码文件
4. 当前要改的测试文件

只有当普通编码任务碰到接口合同、权限、错误语义或公共 payload 时，再读取 `API_CONTRACT.md`。

### 7.2 架构或接口任务
再追加读取：

1. `ARCHITECTURE_CONTRACT.md`
2. `DECISION_LOG.md`
3. `API_CONTRACT.md`

### 7.3 API / 接口任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. API / CLI / event 入口文件：通常是 `src/main.py`、`src/ui/server.py` 或 `src/mcp/**`
5. 对应 service 文件
6. 对应接口测试

如涉及 breaking change、幂等、后台任务或错误格式，再追加 `DECISION_LOG.md` 和 `ARCHITECTURE_CONTRACT.md`。

### 7.4 Adapter / 外部集成任务
默认读取：

1. `PLAN.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `project-defaults.yaml`
4. 对应 adapter / integration / client 文件
5. `src/models.py`
6. 对应 adapter 测试

如确认或推翻外部能力，必须追加 `DECISION_LOG.md`。

### 7.5 规则 / 阈值 / 状态口径任务
默认读取：

1. `PLAN.md`
2. `project-defaults.yaml`
3. 规则实现文件，通常是 `src/tag_policy.py`、`src/config_migration.py` 或 filtering 相关代码
4. 规则测试文件

如规则语义、阈值含义或风险等级变化，必须追加 `DECISION_LOG.md`，并更新唯一真源中的规则说明。

### 7.6 输出 / 报告 / 返回结构任务
默认读取：

1. `API_CONTRACT.md`
2. `project-defaults.yaml`
3. 输出渲染或响应组装代码，通常是 `src/ui/site.py`、`src/ui/static/**` 或 webhook renderer
4. 输出相关测试

如输出结构变化影响调用方，必须追加 `DECISION_LOG.md`。

### 7.7 存储 / 后台任务任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `ARCHITECTURE_CONTRACT.md`
4. `project-defaults.yaml`
5. 存储或任务调度代码，通常是 `src/storage/**`、`src/services/scheduler.py`、`src/services/fulltext.py`
6. 对应测试

如新增持久化边界、任务状态、重试、超时或并发策略，必须追加 `DECISION_LOG.md`。

### 7.8 前端 / 页面任务
默认读取：

1. React 任务读取 `UI_CONTRACT.md`、当前 `frontend/src/` 页面或组件及其 Vitest/Playwright 测试。
2. Legacy UI 任务读取 `PLAN.md`、`project-defaults.yaml`、当前 `src/ui/static/` 文件及匹配测试。
3. 不得把 legacy CSS/JS 当作 React 视觉系统真源。

只有当前端任务涉及接口字段、错误处理或权限边界时，再读取 `API_CONTRACT.md`。

如 React 视觉组件边界、主题、布局或验收门禁发生变化，必须更新 `UI_CONTRACT.md` 并追加 `DECISION_LOG.md`。

### 7.9 Scraper 任务
默认读取：

1. `PLAN.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `src/models.py`
4. `src/scrapers/base.py`
5. 目标 adapter under `src/scrapers/`
6. 匹配测试

不要默认读取其他 adapter。

### 7.10 API / Worker / MCP 可观测性任务

修改 FastAPI 写路由、Worker Job 类型或生命周期、Remote MCP 诊断、通知 transport、来源头像运行路径、日志配置或 Test Gate 时，默认读取：

1. `docs/dev/observability-logging.md`
2. 目标生产文件与对应测试
3. `scripts/check_observability_contract.py`
4. `tests/test_observability_contract.py`
5. `tests/test_impact_map.json`

新增写路由必须进入 mutation operation map；新增 Worker Job 类型必须进入 trace policy。不要通过降低 checker 覆盖范围、删除关键事件要求或恢复具名 raw 日志来让门禁通过。普通业务代码不需要读取原始 `logs/**`；只有拿到 request/Job/source/subscription ID 后，才按最小服务与时间片段扩展读取。

## 8. 搜索和命令策略

推荐：

1. `rg -n "source_fetch" src/services src/api tests`
2. `rg -n "class JobQueue|create_job" src/services tests/test_job_queue.py`
3. `sed -n '1,220p' 目标文件`
4. `pytest tests/test_x.py::test_name -q`

避免：

1. `rg -n "api|config|token" .`
2. `find . -type f` 后整仓打开。
3. 默认读取 `README*`、`docs/**`、`archive/**`。
4. 失败时粘贴完整长日志；应只保留失败测试名、异常类型和关键 traceback。

## 9. 每轮不应做的事
除非当前任务明确要求，否则不要：

1. 每轮重新读取全部 Markdown 控制文件。
2. 每轮重新输出完整项目树。
3. 读取虚拟环境、缓存或归档。
4. 重复总结整个项目背景。
5. 新增额外 Markdown 设计文档。
6. 读取 `.env` 或包含真实 token 的文件。
7. 默认读取完整 `WORKLOG.md` 归档。
8. 默认读取归档的 init-pro 报告；只在控制面校验失败且当前错误不足以定位时查看相关片段。
