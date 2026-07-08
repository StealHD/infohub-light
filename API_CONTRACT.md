# Inteliscope InfoHub Light API / 接口合同

## 1. 文档目的
本文件定义当前系统的公共接口合同。这里的“API”包括 CLI 命令、本地 Web 配置 API、静态 JSON payload、SQLite 归档读取路径，以及 MCP 集成边界。

## 2. 设计原则
当前接口必须遵守：

1. 入口层只做请求接收、参数校验和应用编排。
2. 业务层不直接依赖外部系统原始字段。
3. 返回结果必须显式表达 capability / degrade 状态。
4. 输出结构必须对静态 UI、历史数据和后续归档分析稳定。
5. 新字段优先使用 `channel/topics`，旧字段 `category/tags` 保持兼容 alias。

## 3. 标识合同
稳定标识：

1. `ContentItem.id`: `{source}:{subtype}:{native_id}`，由 scraper 适配层生成。
2. `normalized_url`: SQLite 归档去重和关系分析使用的 URL 归一化键。
3. `source_ref`: 单源刷新使用的引用，如 `rss:0`、`github:1`、`apify_social:0`、`hackernews`。
4. `article_id`: 归档表和 article graph 的稳定文章键，等同 `ContentItem.id`。

要求：

1. 多来源字段必须先进入 `ContentItem` 或 source config 模型，再给上层消费。
2. 不允许把某个上游字段名作为全系统标准名。
3. 历史 JSON 和旧 SQLite row 必须通过兼容层读回。

## 4. CLI 合同
### 4.1 `uv run horizon --hours <N>`
用途：运行一次完整抓取、去重、分析、静态 UI 写入，并按配置执行摘要、通知、归档或图谱。

请求参数：

1. `--hours`: 可选，覆盖配置中的时间窗口。

返回/输出：

1. 命令行阶段日志。
2. `data/site/radar-data.json`。
3. 可选 summaries、webhook/email 发送、`data/horizon.db` 和 `data/site/article-graph.json`。

capability / degrade：

1. `ai.enabled=false` 时跳过 AI scoring、enrichment、summaries、notifications、article graph，并写入可阅读静态数据。
2. source adapter 失败不应泄露密钥；错误应记录为可读日志。

### 4.2 `uv run horizon --source <source_ref> --hours <N>`
用途：立即刷新一个显式来源，服务于配置 UI 的低成本验证。

范围：

1. 跳过 notifications、summaries、enrichment、full-text、article graph。
2. 只发布该来源新增 item 到静态 UI。

返回字段：

1. `ok`
2. `source_ref`
3. `hours`
4. `fetched`
5. `raw_before_merge`
6. `merged`
7. `skipped_existing`
8. `analyzed`
9. `passthrough`
10. `web_ui_updated`

## 5. 本地 Web 配置 API 合同
入口：`src/ui/server.py`。

稳定接口：

1. `GET /api/config`: 返回当前配置，必须隐藏密钥值。
2. `POST /api/config/action`: 结构化修改配置。
3. `POST /api/source/test`: 测试单个来源可抓取性。
4. `POST /api/source/update`: 触发单源刷新。

请求规则：

1. 配置 API 只保存环境变量名，不保存密钥值。
2. 来源 topics 应写入 `topics`，同时保留 legacy `tags`。
3. Hub channel 应写入 `channel`；Telegram 的平台频道名继续使用 `channel`，Hub 频道使用 `hub_channel` 或兼容 `category`。
4. `apify_social.subscriptions[].token_env` 可为单条 Apify 订阅指定 key 环境变量名；为空时使用全局 `sources.apify_social.token_envs` 轮换。

响应规则：

1. 成功响应必须包含 `ok: true` 或明确的结果字段。
2. 失败响应必须包含人类可读 `error`。
3. 外部来源测试失败必须给出可执行下一步，不暴露敏感 token。

## 6. 静态 JSON 输出合同
入口：`src/ui/site.py`。

`radar-data.json` item 必须包含：

1. `id`, `title`, `source_type`, `source`, `url`
2. `published_at`, `fetched_at`
3. `score`, `reason`, `summary_zh`
4. `channel`, `topics`
5. legacy aliases: `category`, `tags`
6. `signal_strength`, `signal_type`, `entities`
7. `personal_tags`, `interest_score`, `show_in_personal_feed`

兼容要求：

1. 新 UI 优先读 `channel/topics`。
2. 历史数据只有 `category/tags` 时，必须 backfill 成 `channel/topics`。
3. 非 canonical 的阅读主题可以作为 custom topic 保留，不应自动变成 `personal_tags`。

## 7. SQLite 归档合同
入口：`src/storage/article_store.py`。

`articles_light` 必须保留：

1. 旧字段：`category`, `tags_json`
2. 新字段：`channel`, `topics_json`, `signal_strength`, `signal_type`, `entities_json`
3. 兼容读取：旧库缺新列时由 `ArticleStore.initialize()` 迁移。

读取合同：

1. `load_articles_light()` 和 `load_premium_articles()` 返回 dict 时必须同时包含 `channel/topics` 与 `category/tags`。
2. 旧 row 缺 `channel/topics_json` 时，使用 `category/tags_json` 兜底。

## 8. 错误响应合同
所有公共接口必须定义稳定错误语义。

错误响应至少说明：

1. 错误码或异常类型
2. 人类可读错误说明
3. 调用方可执行的下一步动作
4. 是否可重试
5. 相关请求标识或资源标识

要求：

1. 不允许只返回裸字符串错误给 Web API 调用方。
2. 参数校验错误必须区分字段缺失、格式非法和业务约束冲突。
3. 外部系统失败必须表达为标准错误，不得泄露上游原始错误结构或敏感信息。

## 9. 兼容性合同
当接口、命令、事件或模块函数发生变化时，必须说明兼容策略。

至少覆盖：

1. 新增字段是否向后兼容
2. 字段删除或语义变化的迁移方式
3. 旧版本调用方的保留周期
4. 默认值和缺省行为
5. capability / degrade 状态变化

要求：

1. 不允许无记录地改变已有字段语义。
2. breaking change 必须进入 `DECISION_LOG.md`。
3. 当前项目默认单版本，但必须保持字段语义稳定。

## 10. 幂等性合同
会创建、导入、触发任务、写入状态或调用外部副作用的接口必须说明幂等策略。

至少说明：

1. 幂等键来源
2. 重复请求返回既有结果还是创建新任务
3. 超时后客户端如何安全重试
4. 服务端如何记录重复请求

当前约定：

1. 静态 payload 写入按 item `id` 合并。
2. `ArticleStore.upsert_articles_light()` 以 `id` 为幂等键。
3. 单源刷新以 `source_ref + ContentItem.id` 避免重复发布已知历史 item。
4. 通知、邮件、webhook 不默认视为幂等，触发前必须确认配置和运行路径。

## 11. 后台任务合同
异步、批量、定时、长耗时任务必须定义任务状态合同。

至少说明：

1. 任务 ID
2. 状态枚举
3. 进度字段
4. 成功 / 失败 / 部分成功结果结构
5. 超时策略
6. 重试策略
7. 并发或速率限制
8. 结果保留周期

当前任务边界：

1. `horizon-scheduler` 只在显式启用 scheduler profile 时运行。
2. 单源刷新是低成本前台任务，不启动 scheduler。
3. Full-text 和 article graph 仅在对应配置启用时运行。
4. 后台任务日志写入 `logs/**`，默认不进入 agent 上下文。
