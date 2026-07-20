# 本地 AI 概括、管理员 Key 管理与正式订阅重建 v1 实施报告

日期：2026-07-13

## 结论

本地 Service 已完成 write-only AI/Apify Key 管理、单篇概括硬限制、Smoke 数据清理和四个正式订阅重建。默认运行仍只有 API + Worker，公网 RC1/VPS 未修改。

当前本地状态：

- 3 个 Key ref：Gemini Primary、Apify Primary、Apify Secondary；真实值只在 `data/secrets.env`，权限 `0600`。
- 4 个订阅：Apple Developer News、OpenAI News、Claude Code Releases、X `@thsottiaux`。
- Apple/OpenAI/Claude 来源测试成功；用户批准 Apify Actor 权限后，X `@thsottiaux` 的真实测试和单源抓取也已成功。
- 初次 7 天验收刷新为 `partial`，生成 19 条用户 Feed；随后 X 单源抓取合并 1 条，且每条概括非空、不超过 200 字。
- Gemini 真实调用已生成中文概括；随后当前 Key 返回 `429 RESOURCE_EXHAUSTED`，最新刷新按合同回退到来源摘要/正文/标题。
- 来源健康现为 4 个 `healthy`；整份 Feed 自动计划为 360 分钟，X 另启用 30 分钟单源计划。

## 实现

### 密钥边界

- `SecretStore` 使用锁、临时文件、`fsync`、原子替换和 `0600` 权限维护 `data/secrets.env`。
- SQLite `secret_refs` 只保存名称、kind、provider 和环境变量引用。
- admin API 支持列表、新增、轮换和删除未引用 Key；member/viewer 全部禁止。
- API/Worker 在配置读取或任务开始前热加载密钥文件，无需重启。
- 管理页面只显示名称、类型、provider、使用状态和“已设置”；4 个 password 输入初始均为空，DOM 不含 Google/Apify Key 形状。

### 概括与成本控制

- Gemini 默认模型已于 2026-07-14 迁移为官方当前稳定的 `gemini-3.5-flash`，默认正文 1000 字、评论 1500 字、最大输出 800 token、最终概括 200 字。
- Gemini Flash 禁用额外 thinking budget，避免思考 token 挤占结构化 JSON 输出。
- 解析失败响应不写 analysis cache，cache version 已升级。
- FeedRunResult 前统一执行空白压缩、句界截断和回退，保证 snapshot 每条均有受限概括。
- 本地 Gemini 请求间隔设为 6.5 秒；额度耗尽时不中断 Feed 产出。

### 本地重建

- reset 脚本事务清理 catalog、订阅、Feed、状态、健康、job、usage 和 heartbeat，保留 owner/workspace/全局非来源配置。
- bootstrap 脚本登记 3 个 Key ref，写入四个精确来源和订阅，并将 AI 设置切换为 Gemini。
- 数据库 `integrity_check=ok`，`foreign_key_check` 为 0。

## 真实验收

- Docker：`horizon-api`、`horizon-worker` 均 healthy，live/ready 为 200，scheduler 未启动。
- 来源测试：Apple RSS 144 条样例、OpenAI RSS 1040 条样例、Claude Code Releases 5 条样例；X `@thsottiaux` 返回 1 条可解析样例。
- Feed：扩大到 168 小时的验收刷新抓取 Claude 6、Apple 2、OpenAI 11、X 0，共 19 条；任务为有 snapshot 的 `partial`。
- 概括：19/19 非空，长度上限检查为 0 条超限；真实 AI 成功批次验证到 9 条中文概括，最长 156 字。
- 浏览器：Key 管理、Gemini 参数、四订阅、6 小时计划、3 正常/1 连续失败健康状态、19 条 Feed 和 partial 横幅均可见；控制台无 error/warn。

## 外部遗留

1. X 已改用 Apify Secondary 和 `apidojo/twitter-scraper-lite`；`fetch_limit=1` 会精确传为上游 `maxItems=1`，且 parser 再执行 1 条上限。真实直连运行成功但本次返回 0 条；待 Worker 恢复后观察一个 30 分钟自然周期。
   后续完整性修复已实现 xquik adapter，但正式配置在 `$0.01` canary 因 FREE tier 单条 `$0.015` 被拒绝后继续保持旧 Actor，等待单独成本授权。
2. 新 Gemini Key 已完成 1 条真实分析和同用户缓存命中验证；生产任务仍保留额度不足时的安全回退。
3. 公网 `rb.jiefs.top` 发布保持暂停；本报告不构成 VPS 发布通过。

## 最终验证

- `pytest`：658/658 通过。
- Node DOM：61/61 通过。
- Python `compileall`、全部前端 JS `node --check`、两份 Compose 配置和 `git diff --check` 通过。
- Docker API + Worker 最终镜像重建后均 healthy，live/ready 为 200。
- `data/secrets.env` 为 `0600` 且被 Git ignore；工作区 diff 中未发现 Google/Apify Key 特征。
- 当前 init-pro validator 只接受 manifest 模式，而仓库仍使用 schema-2 `project-defaults.yaml`，因此旧 strict 命令不可用；API、架构、计划、决策和 defaults 已人工同步。
