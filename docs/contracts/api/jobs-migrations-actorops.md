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

1. 两份 compose 默认运行单元固定为 `horizon-api + horizon-worker`；`horizon-scheduler` 只在显式启用 `scheduler` profile 时运行。
2. 单源刷新是 Worker 异步任务，不启动 scheduler。
3. Full-text 和 article graph 仅可由旧 CLI/scheduler publisher 在对应配置启用时运行；Service Worker 和默认 UI 不运行或消费它们。
4. API、Worker、Scheduler 与 CLI 的 runtime/operation 日志写入 `logs/**`，UTC 每日轮转且默认保留 30 天；原始文件不进入 Agent 上下文，只有 5B 定义的当前用户脱敏结构化事件可由 OpenClaw 查询。
5. 响应结构诊断只在 adapter 收到上游值时即时提取字段路径/类型，原始值随调用栈释放；Job 只保留有界双层摘要，Feed snapshot、稳定内容索引和媒体记录不得保存该诊断。

### 11.1 信息流触底文案生成

1. `workspace_feed_end_messages` 是幂等新增的 workspace 级 SQLite 缓存表，保存三个列表、非敏感配置指纹、generation、刷新状态、原子租约、最近尝试/成功/下次刷新/退避时间和安全错误码；不保存提示词、模型原文、用户内容或密钥。指纹必须包含当前文案安全合同版本，因此 prompt、白名单或校验语义升级会把旧缓存标成待刷新而不需要数据库迁移。
2. 始终存在内置中文列表。显式触底 Key/模型或独立生成开关未就绪时，GET 必须忽略旧 AI 缓存并返回 `source=builtin,status=disabled`；重新开启后，配置变化、手动刷新、到期或首次缺少缓存均可进入 pending，后台生成期间仍可返回上次通过校验的 AI 列表。旧空绑定仅保留读取兼容，仍临时受工作区 AI 开关控制。
3. Worker 只有在普通任务队列无法 claim Job 时才检查触底文案；一次 idle 轮询最多 claim 一个 workspace、记录一个 workspace AI attempt，并发起至多一次 60 秒模型请求。该调用关闭 SDK 自动重试，不创建普通 Job，也不由 scheduler 驱动。
4. 模型结果必须是只含 `empty/first_end/repeat_end` 的 JSON object；每个数组恰好等于配置条数，三个数组全局去重。每句必须为 trim 后 4–40 字的单行简体中文纯文本，禁止 HTML、Markdown、URL、催促、羞辱、焦虑表达和虚假完成声明。每句可选且最多带一个克制装饰，白名单为 `🙂/😊/🌿/☕/✨/📚/🍵/🌙/🫧/^_^/:)/:-)/(・ω・)/(´▽｀)/(｡･ω･｡)`；`☕` 的标准 emoji variation selector 视为同一装饰，其他 Emoji、颜文字或多个装饰均拒绝。自定义风格不得覆盖这些约束。
5. 成功后 generation 原子加一并按 `refresh_days` 安排下次刷新。超时、配额、调用或输出校验失败只写安全错误码，保留上次成功列表；从未成功则回退内置列表。失败固定六小时后才可自动再试，手动刷新或配置指纹变化可提前触发。

## 12. Feed v2 显式迁移合同

实现中存在迁移脚本不代表任意部署数据库已迁移；当前本地目标部署已于 2026-07-11 显式迁移并验收，是否完成仍必须逐个目标数据库以 migration marker 与 readiness 为准。其他旧库不得沿用本地部署结论，仍需逐库显式执行并验收。

1. 未记录 v2 migration 且存在旧 snapshot/item/state/feedback，或存在 queued/running 的 `source_fetch/user_feed_refresh` 时，readiness 返回 `migration_required`，Worker 拒绝执行 Feed 任务；只有真正无这些遗留产物的新库才可自动记录空库 v2 marker。
2. 应先停止 API、Worker 和 scheduler，再运行 `python scripts/migrate_user_feed_v2.py --data-dir data --backup-dir data/backups --apply`；不带 `--apply` 使用 SQLite 只读连接检查，不建表、不增列、不写 migration marker。
3. apply 必须先生成 UTC 时间戳 SQLite 备份，再取消未完成 Feed job、清空旧 snapshot/item/state/feedback、创建 v2 唯一索引、写 migration 记录并通过 `PRAGMA foreign_key_check`。
4. 应用启动不得自动清空旧 Feed 数据；真实环境迁移属于显式运维动作。
5. 已完成迁移时重复 `--apply` 必须返回 `already_migrated` 且不备份、不清空 v2 数据；备份权限固定为 `0600`，`data/backups/` 不进入 Git。

## 13. User content v5 与 DeepSeek 分析合同

`user_content_items` additive 增加 `analysis_input_hash` 与 `unresolved_reason`。`analysis_input_hash` 是模型无关的来源输入 SHA-256；正文或来源元数据真正变化时才变化，不得因模型切换或历史修复而伪造新分析。

历史修复 CLI 固定为：

```bash
python scripts/repair_user_content_v5.py inspect --data-dir data --output /tmp/content-repair.json
python scripts/repair_user_content_v5.py apply --data-dir data --backup-dir data/backups --cache-legacy-media
python scripts/repair_user_content_v5.py reconcile --data-dir data --backup-dir data/backups
python scripts/repair_user_content_v5.py enqueue --data-dir data --free-only
```

1. 报告固定包含 `status/counts/repaired_body/repaired_media/enqueued_sources/unresolved/backup_path`。
2. inspect 使用只读 SQLite；apply 必须拒绝活跃 Worker、先生成 `0600` 备份，再校验 integrity/foreign keys 并写 version 5 marker。
3. reconcile 必须在任何 `queued/running` Job 或活跃 Worker 存在时于备份前拒绝；有变更时先生成 `0600` 备份，再事务性把 `unresolved_reason` 升级为 nullable，并只从非空 `captured` 正文移除精确 token `source_body_not_available`。其他 reason 必须保留；无剩余 reason 时写 SQL `NULL`。重复运行返回 `already_reconciled` 且不创建备份。
4. `content_repair` 只更新已有 `user_content_items` 的正文、媒体、哈希和 unresolved reason；新抓到的 article 必须忽略，结果固定声明 `snapshot_created=false`、`analysis_calls=0`。
5. 免费来源允许批量入队；Apify social 等付费来源不得由 `--free-only` 入队，必须报告 `paid_source_requires_authorization`。不建设网页全文代理。
6. 详情 `captured` 返回来源接口已有正文；`excerpt_only` 明确降级。媒体最多 6 张且只返回鉴权 `/api/media/*`，不得返回上游临时 URL。

AI Secret metadata 的 `kind=ai` provider 允许 `deepseek`；真实值仍为 write-only。DeepSeek 默认模型和环境变量名固定为 `deepseek-v4-flash`、`DEEPSEEK_API_KEY`，Base URL 缺省时由客户端使用官方地址。

分析复用顺序固定为：当前模型精确 cache → 同用户、同 article、同 input hash 的其他模型安全 cache → 同 input hash 的稳定安全 AI 投影 → 当前 provider。跨用户、输入变化、fallback/excerpt 原文均不得复用。跨模型复用必须记录原模型或 `stored-content`，不得把旧结果标记为 DeepSeek 产物。真实启用前，`scripts/deepseek_analysis_smoke.py` 必须先以 10 秒超时、SDK retry=0 调用 `models.list()` 并确认精确模型；预检失败时 completion 为 0，成功后才允许对一篇 captured article 做恰好一次 completion。该 completion 必须省略 `temperature` 并禁用通用客户端的应用层参数降级重试，首次失败即终止。stdout 只含 provider、model、token 用量和 status。

## 14. Apify ActorOps v15 合同

1. Route 身份为 `platform + target_type + capability`，并有 opaque `route_id`；首期支持 Profile 严格限定为 `x/profile/items`、`youtube/channel/items`、`instagram/profile/items`，其中 X 的永久兼容 `route_key` 保持 `x/profile`。不支持的 tuple 必须在事务与 CAS 前以 `422 apify_actor_route_profile_unsupported` 原子拒绝，不得创建 Route、run 或 Job。每条 Route 固定三槽、`required_slots=3`、`min_runtime_healthy=2`、`min_publishers=2`，缺省单 Run 上限 `$0.02`。
2. Adapter Revision 不可变，生命周期只允许 `proposed → static_valid → probationary → certified` 或 `quarantined/superseded/rejected`；迁移兼容可使用 `legacy_builtin`，但不得伪造 Build、Manifest 或认证证据。attempt 在启动前冻结 `adapter_revision_id/build_id/build_number/manifest_hash/target_fingerprint`；来源与参考 Canary 使用 workspace/Route 加盐的规范目标指纹，X/Instagram 的 URL 与同一 handle 必须归一，不保存明文 target。
3. `GET /api/admin/apify-routes/{route_id}` 必须投影服务端计算的 `activation_recommendation` 与 `activation_mode`。服务端优先选择前两槽 certified、第三槽 probationary/certified 的完整 `standard_2plus1`；完整池暂不可达时，可选择两个各成功一次 Canary 的 probationary/certified exact-Build Revision 组成 `expedited_2of3`，两者 Actor 与发布者均不同，第三槽保持 NULL 且不参与运行或费用。管理员首次或补位激活只向 `POST /api/admin/apify-routes/{route_id}/active-pool/activate` 提交 `expected_generation` 与 `confirmation="确认启用 Actor 主备"`；浏览器不得提交推荐 Revision ID，服务端必须在同一写事务中重新计算方案、执行 CAS 与完整 Manifest/Build 校验后原子增加 Route generation。没有安全两路返回 `412 apify_actor_active_pool_not_ready`，已生效方案不得重复激活。低层 `PUT .../active-pool` 仍用于 CAS 调费、显式回滚和兼容管理，接受两或三条已填充 Revision；槽位未变化的调费不得重置 Candidate circuit、Route/Key 阻断或来源验证，部分槽变化也必须保留未变化槽 runtime state。显式回滚必须携带唯一 `rollback_revision_id`、只改变该 Revision 所在槽，并按 `superseded_from_lifecycle` 恢复旧认证等级，历史 `legacy_builtin` 不得伪装成普通新激活。少于两个 runnable 时 schedule/Worker 返回安全阻断，不产生付费 Run。
4. Manifest v1 的 input 只能是 JSON literal 或精确引用 `target.canonical_url/native_id/handle`、`runtime.max_items/since_iso/until_iso`；output 只能使用 RFC 6901 Pointer 与 `pick_first/to_string/to_integer/to_number/to_boolean/parse_datetime/normalize_url/strip_html`。每个 Pointer 必须能在已拉取的精确 Build Dataset Schema 中确定性解析；无法证明的路径在官方 input validation 和付费 Canary 前以 `apify_manifest_output_pointer_unverifiable` 淘汰。统一输出必须有 `native_id/url/published_at` 与 `title|text`，并通过目标身份、URL host、占位/付费墙、时间与非空校验；Profile/Channel 的 items Route 不得把内容条目的 `url` 同时当作 `source_url` 身份证据，也不得只用 `channel/profile` 自身的 ID 或 URL 充当内容条目身份；带有 `video/post/tweet/item/media/short/reel` 语义的字段仍属于内容身份。
5. Discovery 最多三轮官方 Store 搜索，缺省采用 agent response 且不包含不可运行 Actor；三条首期 Route 使用内容类型专属查询，YouTube 精确检索 channel videos，Instagram 精确检索 profile/user posts 与 profile feed，避免账户资料型 Actor 挤占内容候选。每个 run 接受的候选数由热配置 `max_candidates` 有界为 3–30（默认 12）。非公开、不可运行、deprecated、full-permission、月租或最低费用超 Route 上限、无成功精确 Build/可验证 Schema、无法从公开 input schema 安全映射目标、重复 Actor/发布者不足必须先由确定性代码淘汰。YouTube Channel Items 的 pay-per-event 定价若除启动费外只声明 channel/profile/statistics/subscriber/enrichment 等元数据事件，必须以 `actor_items_capability_unproven` 在 AI 与付费前淘汰；`result` 等泛化事件不作为正向证明也不单独拒绝，仍由 Manifest 与 Canary 验真。Actor 使用官方 opaque `id` 与 `username/name` 归一化身份，Build 从 tagged build 读取精确 ID/number；input schema 和 Dataset `fields` 构成合同，presentation `views` 不参与合同哈希。pricing 取当前最新生效记录并校验最低费用、单价与 pay-per-event 分层价格。目标 URL/handle/native ID 在 string、array 或标准 `startUrls` object 中的形状及一个有界 max-items 字段由确定性代码从公开 Schema 生成受限模板；AI 只能复制该模板，并负责对已拉取候选排序、生成输出映射和语义规则。AI 在一次调用中被要求返回当前目标数的 3–6 个 best-first Manifest proposal，至少覆盖两个已拉取发布者；Prompt 必须包含 Manifest v1 完整合同、精确数组 cardinality 与结构示例，少于目标数记录安全 shortfall，非法 JSON、未知 Actor/Build 或 README 指令不得进入 Canary。系统先完整拒绝 AI Manifest 中的危险输入，再用确定性模板规范化 input，依次静态校验并调用指定 Build input validation；后续 proposal 可补位前序无效项。每个通过项立即保存为 `static_valid` Revision并关联当前 Run，即使最终不足三 Actor 或两发布者也不得整批丢弃。Store/Actor/Build GET 与 input validation 都显式请求 identity encoding；429、5xx、网络或响应解码错误最多重试三次并遵守最长 30 秒的 `Retry-After`。input validation 的 `200 valid=false` 及候选相关 400/403/404 只淘汰当前候选，后续 proposal 必须继续；401 终止整个 Run 为 Apify Key 认证失败，其他请求合同错误以 `failure_phase=input_validation` 终止，重试耗尽只记录安全 unavailable reason。只有当前 Run 至少三个有效 Revision且覆盖两个发布者时才进入 `awaiting_canary_approval`。Discovery settings schema v4 保存管理员从当前工作区 Provider 的安全 Key 列表中人工选择的 opaque `ai_config_id`、内部 SecretStore 引用、enabled、调用边界、`max_output_tokens`（4096–65536）与 generation；PATCH 拒绝旧 provider/model/secret 字段。每个 Job 开始时冻结工作区 AI 的 provider/model、该人工选择的唯一 Key、该 Key 独立连接地址和输出上限，不回退其他 Key；Key 地址为空时使用 Provider 默认地址，单次调用超时为 180 秒。所选 Key 不可用时，启用返回 `409 apify_actor_discovery_global_ai_unavailable`，Job 必须在 Store、模型和付费 Actor 调用前进入 `blocked_ai_unavailable`；被 Discovery 选择的 Secret 不可删除，AI SDK transport 必须在当前 Job 的 event loop 退出前显式关闭。
6. Route 认证缺少安全两路时，管理员先读取 `GET .../canary-plan` 核对服务端选出的最多三个候选，再以一次 `confirmation="确认付费验证主备"`、不可复用到其他动作的 `approval_id`、plan hash、Route generation 和批次总 USD 上限提交 `POST .../canary-batches`。同一事务必须创建不可变 batch、逐候选 validation 与唯一 one-shot Job；浏览器不得提交 Revision 列表或改变顺序。批次严格串行，并在每次付费 POST 前免费读取公开 Actor 与精确 Build：Actor/Build 已删除、私有、不可运行、Build 漂移或确定性 403/404/410 时必须停用该 Revision、以 `$0.00` 终结且不占五次 Canary；只有免费预检通过后才创建 attempt 和远端 Run。两个不同 Actor、来自两个不同发布者且均返回有效内容或可信空结果后立即停止，所有未启动候选以 `$0.00` 终结。每候选默认封顶 `$0.02`、单批最多 `$0.06`，Route 认证默认总上限 `$0.10` 且最多五次真实启动；成功证据、真实启动次数、费用占用和仍可试跑的不可变 Revision 必须跨该 Route 的所有 Discovery Run 累计，`candidate_shortfall` 补位 Run 不得丢弃旧 Run 尚未试跑的候选。远端实际费用可以合法为 `$0.00`。`start_outcome_unknown` 必须先阻断整批、Route 与 Key并禁止继续候选；30 秒安全窗后，Worker 只可用原 Key 查询覆盖完整 reservation 窗口的账号级 Run 列表，且仅当权威 `total=0` 时将其终结为 `apify_start_not_created/$0`、归还 Canary 次数并解除对应阻断，任何 Run、响应歧义或读取失败都继续 fail closed。该恢复绝不自动重发 Actor POST，下一次付费启动仍需新的管理员确认。每次 Actor 最长等待默认 300 秒，可由 `HORIZON_APIFY_ACTOR_CANARY_TIMEOUT_SECONDS` 在 180–900 秒内为下一 Job 热加载；超时必须中止已知 Run且禁止自动重试。远端终态费用以 `apify_actor_runs` 为真源：首次终态后至少等待 Apify `finishedAt` 10 秒并再次 GET 相同 Run，Worker 还要幂等刷新过早终结的既有记录并回写 attempt/validation/batch；读取失败时金额保持待对账而不是伪造为 0。Route 参考 Canary 若确认不可变 Build 只返回元数据、占位内容或违反统一内容合同，Revision 必须从 `static_valid` 进入 `rejected`、从 `probationary` 进入 `quarantined`，历史失败证据也必须阻止重复付费；超时和暂时系统故障不属于该永久判定。达到两个安全 probationary/certified Revision 后批次进入 `activation_ready` 并允许独立确认快速激活；批次不足两路时先以 Route 全部历史证据生成后续人工审批计划，只有现有未试候选确实无法补齐两路才自动创建一次不运行 Actor 的 Discovery 补位任务。approval 重放返回原 batch/Job，参数、plan 或 generation 不一致则冲突，不得产生第二个付费 Run。旧的单 Revision Route Canary 接口只作兼容；来源级 Canary 继续使用 `confirmation="确认付费试跑"` 并逐槽确认。每条 validation 冻结其 `discovery_run_id`，已确认实际成本、待远端对账笔数和仍排队的批准上限按 Route 分开投影；`$0.10` 是认证预算上限而不是预留或扣款，Revision 被后续 discovery 复用也不得篡改历史费用归属。完整 2+1 的 Primary/Backup 1 仍需两个不同公开参考来源成功、48 小时观察且有效 attempt 成功率至少 95% 才 certified；快速模式的两路各成功一次即可 probationary 运行。
7. 新来源按当前实际运行槽位串行验证，默认总上限 `$0.06`；两槽快速池全部通过后为 `ready_2of2`，完整三槽全部通过后为 `ready_3of3`。每个运行 Actor 都必须确认身份并返回真实内容或可信显式空结果。首次启用另需 `confirmation="确认首次启用"`，binding 状态切换与 source enabled 必须在同一事务中原子完成，同 generation 重放幂等。第三槽后续补位或 Revision 变化只使变化槽待复验，既有成功验证仍有效。
8. Worker 开始时冻结 Route、binding、Key generation 与三 Revision；每个 Run 传精确 `build`、`maxItems=1`、Route `maxTotalChargeUsd`，Dataset GET 另有行数与字节上限。所有 Apify 请求显式发送 `Accept-Encoding: identity`；幂等 GET 的网络或解码错误最多使用同一 Key 重试三次。已启动 Run 的 Dataset 重读绝不创建第二次 Actor POST或切换槽位；重试耗尽转换为安全 reconciliation 阻断并保留远端 Run 与费用账本。Key 401/402 只交 Key Pool；Actor Build 消失/合同漂移/系统故障才切下一槽；目标私有/删除只更新 target health；`start_outcome_unknown` 的 attempt 终结、validation 终结与 Route/Key 阻断必须在一个事务提交，任一步失败则全部回滚为可由重启恢复扫描处理的 running 状态，且禁止切槽；`valid_empty` 成功，`suspicious_empty` 可串行回退。
9. 所有结果在写共享缓存或 Feed 前再次通过 publication fence。该 fence、source avatar/media cache 引用、Feed snapshot、source health 和 schedule advancement 必须完成于同一 `BEGIN IMMEDIATE` 发布事务；缓存文件使用双向 journal，提交后才删除旧文件，回滚时删除新文件，不得留下断开的 DB/文件引用。运行中旧 generation 可以完成和结算，但 Route、binding、revision set 或 Key generation 任一变化都使结果过期，不得写入新状态。
10. 新 Apify-primary source config 为 `profile_id + target`，不重复保存平台、Actor 或 Build；旧 `platform/kind/target` 继续兼容。YouTube 始终保存为 RSS，原生成功/可信空不调用 Apify；允许回退的错误只使用已验证 binding，结果保持原 source 与稳定 Feed ID。
11. 管理 API 为：
    - `GET /api/admin/apify-routes`
    - `GET /api/admin/apify-routes/{route_id}`
    - `POST /api/admin/apify-support-checks`
    - `GET /api/admin/apify-discovery-runs/{run_id}`
    - `GET /api/admin/apify-discovery-runs/{run_id}/canary-plan?goal=initial_pool|complete_third|upgrade_legacy`
    - `POST /api/admin/apify-discovery-runs/{run_id}/canary-batches`（body 的 `goal` 缺省为 `initial_pool`）
    - `GET /api/admin/apify-canary-batches/{batch_id}`
    - `POST /api/admin/apify-discovery-runs/{run_id}/candidates/{revision_id}/canary`
    - `PUT /api/admin/apify-routes/{route_id}/active-pool`
    - `POST /api/admin/apify-routes/{route_id}/active-pool/activate`
    - `GET /api/admin/sources/{source_id}/apify-support`
    - `POST /api/admin/sources/{source_id}/apify-validations/{revision_id}/canary`
    - `POST /api/admin/sources/{source_id}/apify-binding/activate`
    - `GET|PATCH /api/admin/apify-discovery-settings`
    - `POST /api/admin/apify-discovery-measurements`
12. 所有 mutation 必须带 `expected_generation`；support check 使用列表 envelope 的 workspace catalog `generation`，成功响应的 `generation` 仍为最新 catalog CAS token，另以 `route_generation` 返回对应 Route token；Route、binding、settings 等 mutation 使用各自对象的 generation，客户端不得混用。只有 owner/admin 可 Canary、调费、激活、替换或回滚，member 只可提交 support check。API 不返回 Token、Actor input、真实 target、远端 Run/Dataset、原始错误、README、原始 Dataset、approval ID 或 Manifest 中的 target 值。旧 `/api/admin/apify-actor-routes/x/profile*` 保留一个兼容版本：读取与排序代理到 v15 状态；旧 Canary mutation 因缺少显式费用上限和 approval 幂等键而安全拒绝，调用方必须升级到 v15 Canary 接口。
13. `GET /api/catalog/source-capabilities` 的 envelope `generation` 是 workspace catalog CAS token；items 只返回可创建来源需要的已认证 Route 元数据与安全表单字段，其中 Apify-primary 使用 `profile_id + target`，YouTube native-first fallback 使用 `url + keep_latest_item`。未知能力只创建 discovery request，不创建可调度付费 source。AI/Store 不可用只阻断新发现，既有 Route 继续运行。
14. Worker maintenance 最多每七天读取一次已激活 Actor/Build/Schema/权限/定价指纹；只持久化有界 SHA-256 observation，不保存原始元数据。相同 observation 的重复检查不得再次创建 proposal 或调用 AI；有 Build 消失、槽位不足、Schema/权限/价格漂移或人工请求时只创建 proposal，绝不自动付费、替换或激活。Store/AI 不可用时既有精确 Revision 继续运行。
15. 只有 owner/admin 可执行 `force_discovery=true`；member 每日最多提交 10 次 support check，同 workspace 最多保留 20 条未结束 Route 请求。强制重新发现 ready Route 只创建独立 discovery run，生产三槽在管理员后续激活前保持不变。
16. `GET /api/catalog/source-capabilities` 在完整 2+1 或快速两路池达到运行门槛时投影对应 Route 的安全创建字段；所有已填充 Revision 必须固定 exact Build、probationary/certified、Actor 唯一且至少两个发布者，旧 `legacy_builtin` 两路仍只服务兼容来源。Apify-primary 字段为 `profile_id + target`，YouTube fallback 保持原生字段。
17. Discovery run schema v5 在 `candidate_shortfall` 阶段也投影已持久化但不可付费审批的部分候选；只有没有静态能力冲突或历史永久输出失败的 Revision 才可进入服务端 batch plan，被阻断候选保留展示安全 rejection reason 且 `can_canary=false`。响应返回稳定 rank、`candidate_count/candidate_shortfall`、`publisher_count/publisher_shortfall`、Route 级已确认实际费用 `spent_usd`、待远端对账笔数 `unreconciled_cost_count`、仍排队批准上限 `reserved_usd` 和按安全 reason code 聚合的淘汰计数，不得把已通过的 `1/3|2/3` 显示成 `0/3`，不得把批准上限或 `$0.10` 认证预算伪装成实际费用。最近 batch 以安全投影随 Run 返回，刷新页面后仍可恢复 `queued|preflighting|running|activation_ready|partial|blocked_unknown_start|failed|cancelled`、成功 Actor/发布者数、实际费用及逐项 `$0`/终态；不得返回 validation ID、Run/Dataset ID、真实 target、Actor input 或上游正文。Canary plan 只返回 Route/模式、服务端顺序、Actor/发布者、精确 Build、商城定价摘要、逐项/总封顶、五次真实启动与 `$0.10` 周期预算的剩余量及 plan hash。管理员容量测试必须携带 `confirmation="确认AI容量测试"` 与 settings generation；首次只允许 YouTube/Instagram 顺序各一次 32768 上限的单模型调用，只有 32K `finish_reason=length` 的 Route 才可单独确认 65536 重测。测试不启动 Actor/Canary。Run 只保存请求上限、输入/completion/reasoning/content Token（供应商不返回时为 NULL）、finish reason、耗时、响应字节数及 JSON/Manifest 状态；不得保存 Prompt、正文、Key 或原始异常。两个 Route 均成功且非 length 时，建议值取最大 completion 的 1.5 倍向上取整到 1024，并限制在 8192–65536；建议只展示，不自动修改生产上限。淘汰 Actor ID、原始 metadata/错误、候选与真实 target 的关联不得返回。
18. ActorOps 的 feature/DSL 名称保持 v15，但共享运行库的 global migration 15/16 已由通知 schema 占用，`schema_migrations` 必须以 version 17、name `apify_actor_ops_v15` 和固定 checksum 三元组识别；不得仅凭 version 猜测或覆盖既有 marker。普通 API/Worker initialize 不得安装或修补 ActorOps 表，只有显式离线迁移可在 `0600` backup 后执行。支持的自动升级起点是已通过检查的 v13/v14；任何未发布 partial ActorOps 形状都 fail closed 并恢复备份。已安装旧 checksum 的受控修复只可删除完全无槽位引用、候选、Revision、binding、validation、attempt、target health、费用或非终态/已调用 AI 证据的误建 `youtube/profile/items`；否则中止并恢复备份。修复同时增加 `youtube/channel/items` generation，并清除旧独立 Discovery AI 字段；曾启用的旧设置强制停用并增加 generation。
19. Token 测量字段通过独立离线 migration `apify_discovery_limits_v16`（global version 18）安装；API/Worker 普通初始化不得静默加列。迁移要求 v15 已通过，停止 API/Worker且无 queued/running Discovery/Canary Job，使用 SQLite backup API 生成 `0600` 备份，并在提交 marker 前通过 integrity 与 foreign-key check；旧 Run 的用量保持 NULL，不伪造为 0。
20. 批次审批账本与精确费用证据通过独立离线 migration `apify_actor_canary_batches_v17`（global version 19）安装；API/Worker 普通初始化不得静默建表或加列。迁移要求 global version 18 已通过，停止 API/Worker、跨过 heartbeat 安全窗且不存在 queued/running Discovery、单 Canary 或 batch Job，使用 SQLite backup API 生成 `0600` 备份，并在提交 marker 前通过 integrity 与 foreign-key check。旧 validation 的批准上限不再当作实际费用：只有 Run/attempt 账本证明的终态实际费用才标记 `cost_final=1`；`start_rejected` 且没有 remote Run/Dataset、预留为零的记录修复为 `$0.00`、不计 Canary，并停用已失效 Revision。不能证明未启动的历史记录保持费用未知，不得伪造为零；任一失败恢复备份。
21. 第三槽补位与 legacy 旁路升级通过持久 Pool Stage 完成，浏览器不得提交 Actor、Revision、槽位或来源集合。`complete_third` 只允许现有 exact-Build Primary/Backup 1 均已 certified 且 Backup 2 为 NULL：计划冻结基础 generation/pool hash、服务端选择的不同 Actor/发布者候选与当时所有 enabled source 的 binding generation/target fingerprint；`upgrade_legacy` 只允许当前池含 `legacy_builtin`，旁路选择两个不同 Actor/发布者的 exact-Build Revision，旧池在最终 apply 前持续服务且旧 lifecycle 不得改写。一次 `确认付费验证主备` 审批创建 batch、stage、候选 validation、来源快照和唯一 one-shot Job；Worker 先串行验证 Route 候选，再在同一批准上限内仅验证每个快照来源缺少的目标槽证据。新增、binding 变化或失败来源使 stage 保持未就绪，下一 plan 只覆盖当前缺失证据并要求新的有界付费审批；禁用或删除来源不再阻塞。plan hash 必须覆盖 goal、Route/base pool、候选顺序、来源 binding 快照与费用上限，重放只可返回精确同一账本。
22. Staged apply 复用 `POST /api/admin/apify-routes/{route_id}/active-pool/activate`，并携带 `stage_id`、`expected_plan_hash`、`apply_id`、最新 Route generation 与既有确认词。服务在一个 `BEGIN IMMEDIATE` 中重新校验基础池、exact Build/Manifest、Actor/发布者多样性、batch 所有 item 与费用均已终结、无 inflight/unknown-start、以及当前所有 enabled source 对目标池都有匹配当前 fingerprint 的成功证据；任一条件变化必须零写入 fail closed。成功时原子写入槽位、Route generation、来源 `ready_2of2|ready_3of3` 与 stage 终态；精确 `apply_id` 重放返回同一结果，跨 stage/plan 复用冲突。Route detail 只投影服务端计算的 `workflow/next_action/progress/blockers` 和每个 Revision 的自动认证进度（观察起止、身份/参考来源、成功率、门槛与阻断）；不得投影来源 target/fingerprint、approval hash 或内部输入。该能力由离线 migration `apify_actor_pool_staging_v18`（global version 20）安装：要求 global version 19 已通过、API/Worker 停止且无活跃 Job，先做 `0600` backup，再检查 integrity/foreign keys 与 marker；任何失败恢复备份，普通 initialize 不得静默安装。
