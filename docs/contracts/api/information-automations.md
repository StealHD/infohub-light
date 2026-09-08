# 个人信息提醒

## 当前实现与待验收边界

阶段 3 提供个人关键词规则、Feed 新增事件、Worker 判断与投递。所有代码仍为本地未提交改动；原测试库 global 38 尚未应用，生产未部署。阶段 4 已提供聊天确认卡与独立 MCP 草稿工具；阶段 5 提供独立 connector，验证就绪前禁止启用语义规则。用户要求先不发送，真实关键词与语义通知回执均待验收。

## HTTP 接口

全部接口使用当前登录用户、统一 envelope 和 `Cache-Control: no-store`。不接受用户或 Agent 选择参数；Owner/Admin/Member 需要有效个人绑定才能保存或启用，Viewer 只读。跨账号规则/运行返回 404。

| 路径 | 方法与行为 |
| --- | --- |
| `/api/me/information-automations` | GET：`limit=1..100`、非负 `offset`，返回 `items/has_more/next_offset`；POST：保存草稿 |
| `/{rule_id}` | GET 读取；PUT 接收 `version/config`，校验当前版本后创建不可变新版本 |
| `/{rule_id}/transition` | POST 接收严格整数 `version` 与 `action=enable|pause|archive` |
| `/{rule_id}/test` | POST 接收 `version/article_ids`（1–20 条本人内容），不投递、不创建正式运行、不推进水位 |
| `/{rule_id}/runs` | GET 同样分页，返回判断、通知、依据、可验证回执与安全错误原因；不返回模型完整输入或领取凭证 |

规则 `config` 包含 `name`、`mode=keyword|semantic`、本人已启用订阅的 `source_ids`、可见通知服务 `target_id`、`conditions{all,any,exclude}` 和语义 `requirement`。草稿允许缺少来源/目标/条件；启用要求补齐并验证。字面关键词按 NFKC、casefold、空白折叠规范化，不执行正则。输入不完整时返回 `insufficient`，不能把截断内容当成完整的不命中证据。

确认启用授权该版本持续投递。确认时固定个人 binding、目标 config/activation generation 和 Transport generation，水位取当前最大事件 ID；重复确认已 active 的同一版本不重置水位。修改任意 config 会新增版本、暂停、取消尚未开始的旧任务；重新启用生成新的确认标识并从当前水位开始，不补发暂停期间历史；运行引用当时的确认事实，旧确认下的结果不能用于新授权。归档不可再次启用。服务端每次投递前重新检查账号、个人绑定、订阅、规则版本、目标权限与当前 generation；失效时暂停并记录 `issue`。

## 存储和执行

global 38 新增 `information_rules`、不可变 `information_rule_versions`、确认事实 `information_rule_approvals`、`information_source_baselines`、`information_seen_items`、`information_seen_identities`、`information_events`、`information_runs`。Service 保留规则、有限判断证据与投递关联；正文复用 `user_content_items`，不复制 Gateway 会话和产物。

事件在 `FeedProductionService` 的原提交事务内写入，覆盖全量刷新和单源/共享来源发布，不依赖普通新内容通知开关。每用户按稳定 article ID 和规范 URL 身份双重去重；URL 身份仅保存 SHA-256，保留 query 对文章身份的区分。换来源 ID、离开 Feed 窗口后再次出现同一 URL 也不重放；首次成功采集（含空集合）建立来源基线，修订、重复采集、旧数据迁移和重启不生成新事件。首次来源的已有内容只加入 seen ledger。完整来源 provenance 决定可匹配的订阅，其他用户分发使用独立 ledger。

Worker 每批合并窗口 60 秒、最多 20 篇，判断输入上限 32,000 字符。规则 cursor 与新 run 同事务提交；并发 Worker 不重复创建批次。关键词不调用模型。每日通知最多 20 次（上海自然日，已开始但未知的尝试也计数）；达到上限为 `quota_wait/daily_notification_limit`，保留队列，次日继续检查授权后领取。达到额度的规则不阻塞其他规则。

判断状态：`pending/judging/matched/not_matched/insufficient/failed/cancelled/quota_wait`。通知状态独立：`not_required/pending/sending/sent/failed/unknown/cancelled/quota_wait`。先持久化 sending，再调用既有 Email/Telegram/Webhook transport；只有 SMTP 接受、匹配 Telegram message ID 或 Webhook 的已校验 ACK 可标记 sent。发送返回未知、无可验证回执或 Worker 在 sending 后中断，不自动重发；超过五分钟的遗留 sending 标记 unknown。公开回执只含渠道、验证类型与允许的消息标识，不含秘密或目的地。

## 显式迁移

`scripts/migrate_information_automations_v38.py --data-dir ABSOLUTE_PATH` 预览，`--apply` 执行。要求 global 37 完整，停止 API/Worker 并跨过心跳安全窗；先创建 0600 SQLite backup，再事务安装、建立旧内容 seen 基线、检查 schema/integrity/foreign keys。失败恢复备份，重复 apply 幂等。不创建规则或历史事件、不扩充 delegation、不读取目标凭据、不发送。既有数据库普通 initialize 不升级；只有全新数据库引导安装空表。缺 global 38 只阻断信息提醒 API/执行，已安装但损坏的事件 schema 阻止 Feed 事务提交，避免静默丢事件。

## 聊天草稿与独立 MCP 授权

`information_automations_read` profile 增加 `inteliscope:information-automations:read`；`information_automations_draft` 同时增加 `inteliscope:information-automations:draft`。既有 delegation 不自动扩权；Viewer 不能创建 draft profile。工具列表按当前有效授权过滤，调用时再次读取授权及用户角色。

`list_my_information_automations(offset)` 只查询本人；`prepare_information_automation(config)` 只保存新草稿，返回 `draft_ref`、版本与 `[[information-automation:iar_<32hex>]]` 确认卡引用。工具不包含启用、任意投递或通知目的地读取。前端以当前登录身份重新 GET 规则，模型文本中的配置不可信；启用仍由 HTTP 版本校验及用户独立确认完成。

管理员用 `scripts/manage_reminder_delegation.py export --data-dir PATH --user-id ID --bundle-dir NEW_PRIVATE_DIR` 显式导出独立授权，随后在 Gateway 主机执行 `install --root ROOT --bundle-dir DIR --openclaw EXECUTABLE`。工具使用新的 MCP 名称和 SecretStore 引用，保留原个人 read delegation，仅向本人的 Agent 添加两个提醒工具，其余 Agent 显式 deny 此命名空间。安装校验配置但不重启、不调用模型、不发送通知；运行验证需单独完成。新增 Skill 位于本人工作目录。已扩展配置重新执行基础 Agent 安装时会因差异停止，维护时应使用提醒安装工具。

## 语义 connector 与测试预览

global 39 显式新增 `information_connectors`、`information_claims`、`information_previews`。先运行 `migrate_information_automations_v38.py`，再用 `migrate_information_connector_v39.py` 预览并备份迁移；不自动创建机器凭据。机器 SecretStore 引用与 MCP delegation 完全独立，token 只绑定一个有效个人 binding。吊销 connector 会暂停本人语义规则并取消未开始投递；账号、个人绑定失效同样拒绝领取与提交。

机器接口前缀 `/api/connector/information-automations`：GET `/configuration` 返回本人绑定与独立 completion Agent；POST `/claim` 接受 `{isolated_completion:true}`；POST `/claims/{id}/result` 接受领取令牌与判断结果。仅 Bearer 机器凭据可用，登录 Cookie 无效；JSON 请求上限 65,536 bytes。空队列返回 null，不调用模型。每用户并发 1、每日最多 100 次领取（含预览与重试），按 Asia/Shanghai 日界线计数；超额保留队列至次日。

每次领取持久化独立 token 摘要、binding、凭据代次和 180 秒租约。Worker 或下一次领取回收失效租约，最多尝试 3 次；相同结果重复提交幂等，结果变更、旧租约、换绑或旧规则版本不可覆盖。提交前与投递前分别检查规则、账号和授权。connector 提交只形成判断及待投递状态，不持有通知目的地、不直接发送。

OpenClaw `llm-task` 使用已安装 2026.9.2 的 isolated completion 接口：独立 prompt、空工具面、无会话复用、无渠道投递、不回退普通 Agent turn。每人独立 `ic-<binding>` entry 只允许 `llm-task`，禁止其他 MCP/运行时/通知工具；聊天 Agent 显式禁止 `llm-task`。Gateway operator 凭据只供主机 connector 使用，单独从 Gateway SecretStore 读取，不导出至用户 MCP 授权。

输入仅含完整判断要求与本次文章 ID、标题、正文。`personal_only` 和不完整文章不进入模型，当前订阅改为 personal_only 也立即阻断后续推理。输出必须逐篇给出 matched/not_matched/insufficient、理由；matched 必须引用该文章实际存在的文字。未知/重复/缺失文章、伪造引用、工具形状、超限和畸形输出失败关闭，不产生通知授权。判断详情只保存必要证据及状态。

语义 POST `/{rule}/test` 返回独立 preview_id、status、results；GET `/{rule}/test/{preview_id}` 按本人分页之外的单条引用读取进度。预览可为 pending/judging/quota_wait/completed/failed；不写正式运行、确认事实或正式水位，不发送。每用户最多 5 个待执行预览，使用相同领取并发与日额度。前端在查看当前预览时刷新进度，修改规则后旧测试不能代表新版本。

运维：`manage_information_connector.py export --data-dir PATH --user-id ID --bundle-dir NEW_DIR` 导出私有机器凭据；`install --root GATEWAY_ROOT --bundle-dir DIR` 验证并配置独立 Agent，不重启或调用模型。`run_information_connector.py` 使用显式 Service/Gateway URL、各自 SecretStore 目录与引用、`ic-<binding>` Agent 和独立私有 journal；`--once` 只处理一次。结果提交超时保留 0600 journal，重启先重交相同结果，不重复模型调用。`manage_information_connector.py revoke --data-dir PATH --user-id ID` 吊销并暂停语义规则。真实模型/通知回执仍按用户要求待验收。

本地原库操作：先停止 API/Worker，沿用 runtime 的 `HORIZON_SQLITE_JOURNAL_MODE`（当前本地 Docker 为 `DELETE`），再依次运行 global 38、39 的预览和 `--apply`。不要在容器运行时用默认 WAL 的宿主配置工具打开原库。两次迁移均有独立 0600 备份；重建仅从任务 Worktree 运行 `./scripts/up-latest.sh`。恢复迁移前版本必须使用 global 38 前备份并按 runtime_health 核验。用户验收前不执行 Git、CI 发布、生产切换或真实通知。
