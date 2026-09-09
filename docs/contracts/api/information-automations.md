# 个人信息提醒

## 当前实现与待验收边界

Automations 配置 v2 统一使用完整自然语言要求，关键词、语义、排除要求同时参与模型判断。触发与模型配置、批次分析及 global 40 为本地实现；不代表运行库已迁移、connector 已升级或真实通知已验收。

## HTTP 接口与规则

接口使用当前登录用户、统一 envelope 和 `Cache-Control: no-store`。Owner/Admin/Member 需要有效个人绑定；Viewer 只读。跨账号规则、运行与预览返回 404；不接受用户或 Agent 选择参数。

| 路径（前缀 `/api/me/information-automations`） | 行为 |
| --- | --- |
| GET / POST 根路径 | 分页查询／保存草稿；分页为 limit 1–100、offset 非负 |
| GET / PUT `/{rule_id}` | 读取／接收 version、config，CAS 创建不可变新版本 |
| POST `/{rule_id}/transition` | 严格整数 version；action 为 enable、pause、archive、restore |
| POST `/{rule_id}/test` | version、1–1000 个本人 article_ids；创建独立预览 |
| GET `/{rule_id}/test/{preview_id}` | 读取预览进度、综合结论和依据 |
| GET `/{rule_id}/runs` | 分页返回分析、通知、进度、模型、依据和安全回执 |
| GET `/models` / POST `/models/refresh` | 本人模型目录／请求刷新并解除显式刷新前的模型失败阻断 |

`config` 包含 `schema_version=2`、name（1–100 字）、requirement（最多 24,000 字）、本人已启用订阅 source_ids（最多 50）、可见 target_id、trigger 和 model。model 为 `{id, thinking:null|string}`，必须选择主机目录允许的模型；缺省推理沿用模型默认。草稿可以不完整，启用须补齐并验证。新 wire 不含 mode、conditions；旧输入只转换成草稿描述，没有旧执行器。

trigger.kind 为 each、count、interval、calendar。count 默认 5，范围 2–10,000；max_wait_seconds 默认 3600，可为 null 或 60–604800。interval_seconds 默认 3600，范围 60–604800。calendar 使用 time（HH:mm，默认 08:00）、timezone（有效 IANA，默认 Asia/Shanghai）及 weekdays（0 为周一，空列表每天；不得重复）。模型只接收完整要求与本批内容，不使用个人标签。

保存配置会暂停既有规则、取消未开始的旧任务，启用时确认当前版本、个人 binding、目标 config/activation generation 和 Transport generation。重复启用同一 active 版本不重置水位；其他配置变化后从当前事件水位开始，不补发暂停期间内容。仅模型变化保留已经排队的输入，在新版本确认事务内重新建批；旧判断结果不复用。归档可恢复为同版本草稿，并保留配置、不可变版本与运行记录；恢复会清除旧确认和授权上下文，不自动启用、补跑或发送通知，重新启用仍须显式确认。非归档状态调用 restore 失败关闭。

## 新内容、触发和批次

事件仍随 FeedProductionService 原提交事务持久化，覆盖全量、单源和共享来源分发，与普通新内容通知开关独立。每用户按稳定 article ID 与规范 URL 指纹双重去重；首次成功采集（包括空集合）建立基线。修订、重复采集、历史迁移与重启不生成新增事件；完整 provenance 决定订阅归属。

每条到达建立一批。条数跨所选来源累计，最长等待从最早待处理事件计算，达到 N 条或等待到期即建批。间隔以确认时间为锚点，不随 Worker 延迟漂移。calendar 使用明确时区，DST 缺失时刻跳过、重复时刻只执行一次。定期冻结到最近已到期时点的新增范围，后续到达留下一批；停机错过周期合并恢复，不逐个补跑空周期。没有内容只推进时钟，不调用模型。cursor 与批次创建同事务提交。

批次以全量稳定内容作为证据，来源、发布时间和文章标识进入有界输入。单次调用最多 20 个单元、32,000 字符（包含要求与安全余量）；大正文分段，大批量按 extract → 必要的 reduce → final 分层。模型必须返回完整 covered_ids 和有界 summary、reason、evidence；阶段结论不能投递。引用必须同时存在于原始输入及本步骤收到的正文或证据。所有步骤完成后才产生 matched、not_matched 或 insufficient；整批至多一次通知。

原始内容不完整、被截断、缺失或 personal_only 时保留 insufficient，不把缺失当作否定证据，不将该批输入送入模型。每次领取、提交和投递重新检查当前隐私和权限。进度与中间结果持久化，重启仅恢复未完成步骤。配额耗尽为 quota_wait，保留进度至上海自然日次日；每用户并发 1、每日最多 100 次领取（包括预览、分段、汇总、重试）。

## Connector 与模型目录

机器接口前缀 `/api/connector/information-automations`，只接受独立 Bearer 机器凭据，Cookie 无效，JSON 请求上限 65,536 bytes。global 40 不扩充或重建凭据。

- GET `/configuration` 返回绑定、独立 completion Agent 及协议版本 2。
- POST `/capabilities` 接收 `{protocol_version:2,models:[{id,name,thinking_levels}]}`，按 binding 与凭据 generation 保存纯模型元数据。
- POST `/claim` 要求 `{isolated_completion:true,protocol_version:2}`；旧协议返回 connector_upgrade_required。每次领取一个持久化步骤，包含 stage、完整 requirement、明确 model、有界 input。
- POST `/claims/{id}/result` 接收 claim_token 与 `{model,output}`；实际模型必须与所选模型一致。output 有 status、summary、reason、covered_ids、evidence（article_id、quote、note）。拒绝未知引用、漏单元、畸形输出及工具形状。

connector 在 Gateway 主机读取配置目录（models.list configured，指定 completion Agent）并与主机 llm-task 模型覆盖策略求交，每 30 秒同步；Service 目录超过 300 秒为 stale。默认 connector 安装只为未设置的 allowModelOverride 提供 true，保留已有明确 false 与 allowedCompletionModels。凭据和原始配置不进入 Service 或浏览器。目录配置可用不等于真实模型调用已验收；不支持独立 completion 的运行时失败关闭。

每次领取保存 token 摘要、binding、凭据代次、180 秒租约。过期最多三次领取，提交超时的 0600 journal 先重交同一结果，不重复调用模型。相同结果重复提交幂等，旧租约、旧版本、旧确认或换绑结果不覆盖。模型调用失败将该模型标记不可用并保留队列；后台同步不会自动清除此阻断，用户刷新目录后可重试，或仅更换模型后重新确认。

`llm-task` 使用显式 model 及可选 thinking；独立 prompt、空工具、无会话复用、无渠道投递、不回退普通 Agent。机器 connector 不持有通知目的地或发送权限。

## 通知与回执

沿用 Email、Telegram、Webhook transport；发送综合摘要、理由与服务端输入中的原文链接。未命中无需通知，证据不足和失败保留原因。判断与通知状态独立；正式发送前再次验证账号、binding、订阅、版本、确认、目标与 Transport generation。

每日每规则最多 20 次通知，上海自然日，已开始但未知的尝试也计数。先持久化 sending 再发送；仅 SMTP 接受、Telegram message ID 或已验证 Webhook ACK 为 sent。未知发送不自动重发；遗留 sending 五分钟后为 unknown。公开回执不含目的地或秘密。

## 迁移与操作

global 38/39 原表与校验保持原样；global 40 新增触发状态、模型目录、批次步骤和模型变更待恢复引用。非归档旧规则追加新版本，关键词条件转换完整描述，旧语义描述保留，active 改 paused；旧版本、确认、回执不改写。没有历史事件或模型／通知调用。

依次使用 `migrate_information_automations_v38.py`、`migrate_information_connector_v39.py`、`migrate_information_unified_v40.py --data-dir PATH` 预览，再显式 `--apply`。要求停 API/Worker、心跳窗安全、0600 备份、marker/shape/integrity/foreign-key 校验；失败恢复备份，重复 apply 幂等。已有数据库 initialize 不自动升级，缺 global 40 仅阻断自动化接口与执行。正常 Feed 继续遵循 global 38 事件 schema 校验。

`manage_information_connector.py` 配置机器凭据与独立 Agent；`run_information_connector.py` 沿用原 Service/Gateway SecretStore 参数并增加必填 `--gateway-config`（Gateway 主机的配置文件）。metadata 设备位于 journal 同目录的 catalog-device，须完成 Gateway 配对；自定义 CA 同时用于 HTTP 与模型目录 WebSocket。安装和目录读取不调用模型，运行测试及真实通知需独立验收。

聊天 MCP 仍只提供 list_my_information_automations 与 prepare_information_automation，授权保持本人 read/draft profile；既有 delegation 不自动扩权。聊天引用只触发当前账号重新读取可信确认卡，模型文本不能启用规则。高级 Gateway Cron 保留独立授权及入口。

仅更换模型时，同时保留已形成批次与尚未达到触发条件的事件；重新确认后继续累计，暂停期间新增内容仍跳过。超长旧关键词条件完整转换，描述上限为 24,000 字符；长描述的中间步骤使用更紧凑的证据 schema，为分层汇总保留输入空间。

统一分析 connector 将输出 schema 同时写入模型提示词和 Gateway 校验参数；请求绑定独立 Agent 的 sessionKey。格式错误、调用超时与通用调用失败分别返回 invalid_model_output、analysis_timeout、analysis_call_failed，结束当前测试或运行，不将此类错误计作模型下架。旧 connector 的 isolated_completion_failed 兼容处理保持不变。
