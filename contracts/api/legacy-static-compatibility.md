## 6. 静态 JSON 输出合同
入口：`src/ui/site.py`；本节只描述 legacy CLI/static publisher 的兼容输出，不是默认 Service UI 数据源。

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
4. 默认 Service UI 不直接读取 `radar-data.json`、`history-data.json` 或 `article-graph.json`；阅读与历史只通过 `/api/feed/*`，且默认不调用 archive analytics、Graph 或 feedback 路由。

## 7. SQLite 归档合同
入口：`src/storage/article_store.py`。本节属于 legacy CLI/archive compatibility；Service latest/history 不得依赖 `ArticleStore` 或 `data/horizon.db`。

`articles_light` 必须保留：

1. 旧字段：`category`, `tags_json`
2. 新字段：`channel`, `topics_json`, `signal_strength`, `signal_type`, `entities_json`
3. 兼容读取：旧库缺新列时由 `ArticleStore.initialize()` 迁移。

读取合同：

1. `load_articles_light()` 和 `load_premium_articles()` 返回 dict 时必须同时包含 `channel/topics` 与 `category/tags`。
2. 旧 row 缺 `channel/topics_json` 时，使用 `category/tags_json` 兜底。

<!-- init-pro:section name=errors -->
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

<!-- init-pro:section name=compatibility -->
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
2. breaking change 必须进入 `docs/decisions/`。
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
5. Service Feed snapshot 以非空 `job_id` 为幂等键；重复 finalize 返回既有 snapshot，不得创建第二份。snapshot item 以 `article_id` 稳定去重。
6. Source Health 以内部 `(subscription_id, job_id)` application ledger 保证 outcome 重放幂等；同一 job 的重复应用不重复累计失败。
7. 偏好来源通知以 `(subscription_id, article_id)` outbox 唯一键抑制全量/单源/重试重放；测试通知是显式非幂等人工动作，但不会消费内容唯一键或移动基线。
8. 触底文案立即刷新以 workspace 唯一状态行为幂等键；重复请求只保留同一个 pending/refreshing 状态。Worker 用 `BEGIN IMMEDIATE` 与原子 claim token/75 秒租约确保同一时刻最多一个执行者接管一个 workspace，过期租约才可重新抢占。
9. Apify 运行告警以 workspace、route、incident kind 与未解决状态抑制重复首报；升级到全挂创建独立 incident，恢复只关闭对应 open incident。明确失败 delivery 最多三次技术尝试，`unknown` 永不重放；测试告警是显式人工副作用但不创建 incident。每个付费 Canary 管理员动作生成一个不透明 `approval_id`；同一 ID 的传输重放只返回原 validation/job，不得再次扣费，真正发起下一次 Canary 必须重新打开确认、生成新 ID。数据库只保存 approval 摘要、批准时 generation 与不可变 USD 上限，不保存原 ID 或确认短语。
10. X/profile Actor attempt 以稳定 Job/source group 约束最多三次与 `$0.06`；同一 Job 的 terminal successful Dataset 是可重放的只读结果，重复执行只 GET 既有 Dataset，不创建新 attempt 或 Actor POST。缺少可验证 Dataset 时 fail closed。
