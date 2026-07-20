# Content Presentation v1 实施报告

日期：2026-07-14
范围：本地 Service API + Worker + React Feed；不修改 VPS，不运行 legacy scheduler。

## 1. 结果

已将不同订阅源统一为一个可稳定展示的 `presentation.version=1`。来源、作者、时间、链接、内容类型、来源摘录、主题和原生互动量全部由代码提取；AI 不再生成“为什么值得关注”，只保留受控中文概括、评分、signal、语义主题和可选建议动作。

该方案把可确定事实移出 prompt，减少重复 token，并避免 RSS、GitHub、Reddit、Telegram、Apify 和 Hacker News 在前端形成各自的展示结构。

## 2. 通用模板

每个 Service Feed item 新增 additive `presentation`：

| 区域 | 字段 | 规则 |
|---|---|---|
| source | id / catalog_type / platform / name | 由 catalog 与 adapter identity 提供 |
| author | name / kind | kind 固定为 person/account/channel/organization/unknown |
| timing | published_at / fetched_at | ISO-8601，前端同时支持相对时间与精确时间 |
| links | canonical_url / source_url | 原文与原帖可分离 |
| content | title / title_origin / excerpt / content_kind | excerpt 清洗 HTML、排除评论附录、最多 600 字 |
| taxonomy | channel / configured_topics / inferred_topics / topics / entities | 配置主题与 AI 推断主题分开保留 |
| engagement | native_score / likes / comments / reposts / shares / upvote_ratio | 缺失为 null，不伪造为 0 |
| analysis | status / score / signal_strength / signal_type / summary_zh / action_suggestion | summary 默认最多 200 字，action 最多 80 字，禁止 reason |

原始 `content` 不进入 Service API item。旧 flat 字段暂时保留给 legacy publisher/history 兼容，React 优先读取 `presentation`，不显示或搜索 `reason`。

## 3. 来源覆盖

确定性 fixture 使用真实 adapter 解析入口覆盖 8 类 catalog source 和 11 种内容形态：

| Catalog 类型 | 内容形态 | content_kind |
|---|---|---|
| RSS/Atom | feed item | feed_summary |
| GitHub Release | release | release_notes |
| GitHub User | event | event_description |
| Reddit Subreddit | post/discussion | discussion |
| Reddit User | post/discussion | discussion |
| Telegram Channel | message | message |
| Apify Social | X post | post_body |
| Apify Social | Instagram post | caption |
| Apify Social | Facebook post | post_body |
| Apify Social | Telegram message | message |
| Hacker News | story/discussion | discussion |

新增 `scripts/source_contract_smoke.py` 用于隔离真实源验证：不写数据库、显式禁用 AI，只输出 source id、状态、数量、字段路径和安全错误码，不输出标题、正文、URL 或密钥。

## 4. Token 与用户隔离

- 分析 prompt 只接收最多 1000 字正文和 1500 字评论，输出最多 800 token；中文概括仍执行服务端硬截断。
- prompt/cache 版本升级为 `content-analysis-v6-presentation-no-reason`。
- 新增 `user_analysis_cache`，命中边界包含 workspace、user、article、input hash、model 和 prompt version；不同用户绝不复用。
- 缓存只保存安全推理字段，不保存原始正文、prompt、密钥或 reason，默认保留 30 天。
- `FeedRunResult` 和 job diagnostics 新增 `analysis_usage`：item_count、cache_hits、ai_calls、fallbacks、skipped。

## 5. 真实源验证

2026-07-14 的来源隔离 smoke 未调用 Gemini；随后另行完成 1 条 Gemini 真实分析与缓存验证。来源结果如下：

- 通过通用模板：RSS 10 条、GitHub Release 30 条、GitHub User 2 条、Hacker News 5 条、Reddit Subreddit RSS fallback 1 条。
- Reddit User：上游阻断，返回 `RedditBlockedError`。
- Telegram：adapter fixture 通过，但本机到 `t.me:443` 的 TLS 连接仍失败，返回 `ConnectError`。
- Apify Primary 的月额度错误与旧 Actor 权限错误已通过切换路径解除：X 改用 Apify Secondary 和 `apidojo/twitter-scraper-lite`。
- 后续代码默认已增加 xquik 单条 adapter；正式配置仍以真实 canary 成功为门禁，当前 `$0.01` cap 在 FREE tier 无法容纳 `$0.015` 的一个结果。
- 真实直连运行已确认上游请求为 `maxItems=1`，运行成功、返回 0 条，无 100 条最小限制或 full-access 错误。确定性 parser contract 同时由 fixture 覆盖新 Actor 字段形状。

## 6. UI 结果

- 列表优先显示规范来源、作者、相对时间、规范标题和概括。
- 详情显示来源/作者/精确时间、来源健康、最多四个原生互动事实、来源摘录和建议动作。
- canonical/source URL 不同时分别展示“打开原文”和“查看原帖”。
- 删除“为什么值得关注”及其搜索输入；旧 UI 同样不再展示该内容。
- 1024px 验收发现文章滚动区缺少键盘焦点，已增加可聚焦滚动容器并通过 Axe serious/critical 门禁。

## 7. 验证结果

- pytest：696 项通过。
- React：UI contract、ESLint、TypeScript、58 项 Vitest 和 production build 通过。
- Legacy UI：62 项 Node 行为测试通过。
- Playwright：11 项通过、7 项按视口条件跳过；桌面/平板/移动视觉基线已按有意布局变更更新，Axe serious/critical 为零。
- Python 编译、全部 legacy JS `node --check`、两份 Compose config、`git diff --check` 通过。

## 8. 遗留项

1. X 的备用 Key/新 Actor 直连已通过；待 Worker 恢复后只观察一个正式 30 分钟自然周期，确认 job、Feed 合并和实际计费。
2. 在 Telegram 网络出口可用后只复验 1 条公开频道抓取。

Gemini 已切换到官方当前稳定的 `gemini-3.5-flash`：新 Key 的单条真实分析成功，中文概括为 64 字；同用户同输入第二次命中缓存，`ai_calls=0/cache_hits=1`，且测试客户端确认没有网络调用。全过程未恢复 reason 字段。
