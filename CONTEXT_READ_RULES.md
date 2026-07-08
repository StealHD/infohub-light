# Inteliscope InfoHub Light 上下文读取规则

## 1. 文档目的
本文件用于控制 agent 在本项目中的上下文读取范围，减少无效 token 消耗。

目标不是极限省 token，而是：

1. 避免重复读取低价值文件。
2. 优先读取高价值控制文件和关键代码入口。
3. 让每轮只读与当前任务相关的最小集合。
4. 避免误读私密数据、历史大文件和运行日志。

## 2. 默认必读文件
对于绝大多数编码任务，默认只需要先读这 3 个文件：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`

随后只读当前任务相关代码和测试。

## 3. 第二层按需读取文件
只有在任务确实涉及对应边界时，再读以下文件：

1. `AGENTS.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `DECISION_LOG.md`
4. `docs/dev/project-map.md`
5. `docs/dev/hub-taxonomy-real-run.md`
6. 当前任务相关代码
7. 当前任务相关测试

## 4. 默认不需要读取的文件
以下内容默认不应读入上下文：

1. 虚拟环境目录
2. 包管理器缓存
3. 测试缓存
4. 构建产物
5. `.env` / `.env.*`
6. 本地 agent 设置文件
7. `archive/**`
8. `data/site/history-data.json`
9. `data/site/history/**`
10. `data/horizon.db`
11. `logs/**`
12. cached media
13. generated summaries
14. 不相关 Markdown
15. 多数空壳包声明文件

## 5. 推荐读取策略
### 5.1 普通编码任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. 当前要改的代码文件
5. 当前要改的测试文件

### 5.2 架构或接口任务
再追加读取：

1. `ARCHITECTURE_CONTRACT.md`
2. `DECISION_LOG.md`

### 5.3 API / 接口任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. API / CLI / event 入口文件：通常是 `src/main.py`、`src/ui/server.py` 或 `src/mcp/**`
5. 对应 service 文件
6. 对应接口测试

如涉及 breaking change、幂等、后台任务或错误格式，再追加 `DECISION_LOG.md` 和 `ARCHITECTURE_CONTRACT.md`。

### 5.4 Adapter / 外部集成任务
默认读取：

1. `PLAN.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `project-defaults.yaml`
4. 对应 adapter / integration / client 文件
5. `src/models.py`
6. 对应 adapter 测试

如确认或推翻外部能力，必须追加 `DECISION_LOG.md`。

### 5.5 规则 / 阈值 / 状态口径任务
默认读取：

1. `PLAN.md`
2. `project-defaults.yaml`
3. 规则实现文件，通常是 `src/tag_policy.py`、`src/config_migration.py` 或 filtering 相关代码
4. 规则测试文件

如规则语义、阈值含义或风险等级变化，必须追加 `DECISION_LOG.md`，并更新唯一真源中的规则说明。

### 5.6 输出 / 报告 / 返回结构任务
默认读取：

1. `API_CONTRACT.md`
2. `project-defaults.yaml`
3. 输出渲染或响应组装代码，通常是 `src/ui/site.py`、`src/ui/static/**` 或 webhook renderer
4. 输出相关测试

如输出结构变化影响调用方，必须追加 `DECISION_LOG.md`。

### 5.7 存储 / 后台任务任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `ARCHITECTURE_CONTRACT.md`
4. `project-defaults.yaml`
5. 存储或任务调度代码，通常是 `src/storage/**`、`src/services/scheduler.py`、`src/services/fulltext.py`
6. 对应测试

如新增持久化边界、任务状态、重试、超时或并发策略，必须追加 `DECISION_LOG.md`。

### 5.8 前端 / 页面任务
默认读取：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. 当前页面或组件文件 under `src/ui/static/`
5. 当前页面或组件测试

如当前阶段从“light reading UI”变为“正式复杂前端”，必须追加 `AGENTS.md`、`ARCHITECTURE_CONTRACT.md` 和 `DECISION_LOG.md`。

### 5.9 Scraper 任务
默认读取：

1. `PLAN.md`
2. `ARCHITECTURE_CONTRACT.md`
3. `src/models.py`
4. `src/scrapers/base.py`
5. 目标 adapter under `src/scrapers/`
6. 匹配测试

不要默认读取其他 adapter。

## 6. 每轮不应做的事
除非当前任务明确要求，否则不要：

1. 每轮重新读取全部 Markdown 控制文件。
2. 每轮重新输出完整项目树。
3. 读取虚拟环境、缓存或归档。
4. 重复总结整个项目背景。
5. 新增额外 Markdown 设计文档。
6. 读取 `.env` 或包含真实 token 的文件。
