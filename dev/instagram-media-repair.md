# Instagram 指定帖子补图

适用于已存在、未归档且归属明确的 Instagram 文章。它不是免费来源批量 `content_repair`，不会启动 Actor、创建费用预留、调用 AI、通知、创建文章或 Feed 快照、推进来源水位。图片仍通过当前用户权限隔离的 `/api/media/…` 展示。

## 先预览，再明确执行

在当前 checkout 使用其 Python 环境；数据目录必须包含既有 `service.db`，不会初始化或迁移数据库。每次只指定一个 workspace、user、source、article，不支持通配或全量补图。

```sh
.venv/bin/python scripts/repair_instagram_media.py \
  --data-dir /absolute/path/to/data \
  --workspace-id WORKSPACE_ID --user-id USER_ID \
  --source-id SOURCE_ID --article-id ARTICLE_ID
```

预览返回安全原因、可用图片数量、已知总数和 `preview` 摘要，不下载图片、不写文章，也不输出远程地址或原始 Dataset 行。确认预览中的具体文章后，再执行同一命令并增加：

```sh
--apply --expected-preview PREVIEW_DIGEST
```

执行会重新生成预览并验证摘要；原始图片地址、来源绑定、文章版本或候选证据改变时拒绝覆盖。此时重新预览，不复用旧摘要。成功返回 `succeeded`，部分下载失败返回 `partial`，没有可确认媒体返回 `skipped`。部分失败可再次预览并重试；正文、分析和用户状态保持不变，历史快照不可变。SQLite 事务失败时删除本次新增孤立文件。

## 数据来源和边界

优先使用该用户文章已保存的远程图片地址（包括其私有媒体资产记录），否则检查同来源、同绑定版本和目标指纹的最近 5 个成功、已验证且费用最终结算的 Fetch Attempt。只读取与原 Run 和原凭据版本精确关联的既有 Dataset；每次 GET 最多 100 行、8 MiB，不追随重定向。帖子必须再次通过冻结 Manifest 的身份、URL、时间和正文校验，且与指定文章唯一匹配。不得自动重新付费抓取。

单图、图集与视频封面共用缓存；最多 6 张，视频本体不下载。受限媒体扫描最多检查 100 个子项/尺寸候选，越界尾部不虚构数量。图集优先子项，父封面不重复插入；不扫描头像、评论或推荐内容。保存地址失效时显示未缓存数量；没有地址且 Dataset 不可用时，无法凭空恢复图片。

常见安全原因：`instagram_dataset_unavailable`（既有 Dataset 请求失败）、`instagram_dataset_credential_missing`（原凭据不可用）、`instagram_dataset_identity_unproven`（Run/来源/帖子归属无法确认）、`instagram_dataset_request_changed`（冻结请求不匹配）、`instagram_media_missing`（无支持的图片）、`instagram_media_preview_changed`（预览过期）。

历史 Dataset 可能已经过期；请求不可用时不能确认其真实结构。固定样例用于验证已列出的别名，不宣称所有历史 Dataset 必含图片。旧 Manifest 仍走原兼容解析；新字段通过 Schema 或脱敏样本证明的声明映射适配。Instagram 抓取启动失败是独立问题。


## 多 Actor 适配与质量证据

新抓取按媒体结构识别不同 Actor：子项列表、Instagram 原生轮播、GraphQL 子节点和下载链接数组共用解析；尺寸变体只择优一张。公开 Schema 的 Dataset 展示列不保证包含全部字段，真实未识别的媒体对象记为 `mapping_gap`；明确图集却只返回封面记为 `upstream_incomplete`。正文仍保留，媒体缺失不会在同一任务追加收费。

若内容获取成功但仍反复选中仅封面的 Actor，先检查下面的迁移预览是否为 `ready`；应用代码已更新不代表证据表已安装。迁移后需要真实结果形成同来源证据，不应清空费用账本或将媒体缺失当作整体抓取失败。候选只有空 `structures` 或共同作者声明时，媒体继续复用兼容识别；只有明确声明媒体映射才替代兼容媒体解析。

媒体证据需要 global 48。已有库不会由启动过程自动迁移；先停止 API、Worker，再预览和备份迁移：

```sh
.venv/bin/python scripts/migrate_actor_media_evidence_v48.py --data-dir /absolute/path/to/data
.venv/bin/python scripts/migrate_actor_media_evidence_v48.py --data-dir /absolute/path/to/data --apply --backup-dir /absolute/path/to/backups
```

迁移只创建私有证据表，不修改历史内容或 Attempt；DDL 失败回滚，保留 0600 备份。新建空库直接安装。未迁移时解析仍有效，但不保存质量证据或据此调整排序。管理员 Route detail 可读取 Binding 的 `media_capabilities` 和 Candidate 的 `output_schema_origin`；不要将静态支持当成真实多图验证。迁移后由正常、已授权抓取积累证据，当前任务优先恢复原 Attempt，后续任务才按媒体质量选择合格来源。

本次多 Actor 样例明确区分真实结果与文档/构造结构。futurizerush 的 `mediaDownloadUrl` 数组内部仅解析已知媒体字段；未知对象不猜测，仍需后续真实样本确认。既有只有封面的帖子不会自动补齐，单帖补图继续沿用上文流程。

## 通用映射升级与恢复排查

新映射由 AI 根据 exact Build 的 Schema 或已授权 Probe 的样本结构生成 `structures`，支持陌生字段名、嵌套数组、尺寸候选和共同作者。旧候选与冻结请求保持不变；重新发现候选后，仍按现有实测、Dataset 零新增 Run 重验和应用流程启用后继。升级解析器不会自动更新已缓存 Manifest 或修复线上候选。静态成功不代表真实来源已验证；原结果没有提供的图片无法还原。

原 Dataset 恢复只使用原 Run 的凭据版本。出现 `actorops_dataset_access_denied` 时检查原凭据权限，不通过切换当前池 Key 重试；`actorops_dataset_missing` 表示原 Dataset 不可读，`actorops_dataset_identity_unproven` 表示关联证据不足，`actorops_dataset_credential_unavailable` 表示原凭据版本不可用。不要编辑历史 Run/Attempt 归属来绕过校验。瞬态读取失败遵守原任务退避及剩余次数；`actorops_result_recovery_exhausted` 后停止自动恢复，保留历史次数与费用证据。任何新的收费实测或重抓仍走原授权流程。

旧 Instagram 映射的 `coauthor_producers` 兼容结构经样本 Schema 证明后，可接入通用 contributors 校验；作者字段路径仍由原 Manifest 指定，保留真实作者、目标共同作者头像与图集。此投影仅用于当前校验，不更新持久 Manifest/hash；显式 structures 优先，陌生共同作者字段仍须走 AI 映射，邀请和标签不能证明归属。

费用已结算但仍显示等待时，分别检查 Job 的历史终态、Attempt 的 `cost_final/result_state` 和当前 Repair。Repair 兼容 `actorops_cost_settlement_required`、`actorops_repair_cost_settlement_required`、`actorops_result_recovery_required` 与 `apify_start_outcome_unknown`；结算只唤醒同 workspace/route 的相关 Repair，下次执行或复用时重验权限、预算和全部未完成 Attempt，再清除过时原因。终态 Job/Attempt 不重写，已失败候选的冷却也不会因解析代码升级自动清除。

若原来源 Job 已成功（例如免费 RSS 回退成功），但旧 Actor Attempt 仍为已结算的 observed 结果，Worker 正常对账会自动将该未使用 Attempt 收尾为 `actorops_result_recovery_superseded`，无需清库、重跑成功任务或新增付费 Run。免费回退本身失败也会同步 Repair，不能因 HTTP 异常跳过维护。

`certified + inactive` 不等于需要再次收费探测。Repair 会复用当前 Binding 证明尝试接管；`actorops_repair_assignment_unavailable` 表示槽位已满且不符合自动替换条件，保留现有候选并退避重试。只有来源冷却不能授权全局隔离 Actor；可等待自然冷却/健康变化，或由管理员按既有替换流程处理。自动接管关闭或平台能力未证明会返回对应安全原因。证明因 Binding 更新失效时，只在正常预算内补缺少的证明。接管成功仍需两条稳定路径才结束修复。

## Apify 中断与自动恢复

路线没有可用备用时，Repair 会检查同路线的其他合格备用：若已有更多当前来源验证成功的候选，自动转向它，正常维护优先补齐其缺少的来源证明，避免长期盯住无进展的旧候选。探测仍遵守原时间槽、预算和费用未决保护；修复任务执行成功或显示等待探测，不代表来源已经恢复。主候选的来源冷却不会被手动清除，完成验证后才允许备用接管。

本地使用系统代理时，Apify 抓取、Catalog、探测和对账均遵循系统/环境代理；修改代理后重启 API/Worker。`apify_request_not_started` 表示原启动经对账确认没有发生，原任务不会再次付费启动；下一次正常来源调度会重新尝试。此错误及内部网络失败不触发换 Actor。`apify_start_outcome_unknown` 尚不能证明未启动，仍需先对账，不能手工清空账本或反复新建任务。

若 Run 已是最终零费用的 `start_rejected`，Key 池仍显示未知启动阻塞，正常维护会检查该凭据的结算证据及全部未终态采集 Run，再自动释放过时阻塞。无需改 Key、删账本或手动解除；其他凭据、新阻塞及未决 Run 不满足释放条件。

`apify_pool_reconcile_deadline` 表示本轮该 workspace 的核账超过 20 秒，Worker 留待下轮继续并进入后续任务处理。此提示不是 Actor 故障，也不会清除尚未确认的费用。持续出现时检查本地代理/网络和原凭据可用性。

Instagram 同批混入无法证明归属的帖子时，保留其他已验证帖子，执行轨迹记录 `actorops_partial_identity` 和 `rejected_identity_rows`。例如两条目标作者帖子加一条未提供共同作者证据的品牌帖子，保留两条，隔离品牌帖子；不会把 `username_scrape` 等抓取目标回显当作作者证据。整批都不匹配仍失败。旧失败任务与其冷却记录保持原样，代码升级不自动补写历史内容。

探测在领取凭据前失败时，系统自动收尾未启动 Attempt；没有远端 Run 预留才释放预算。Worker 中断后，下一轮对账按终态任务关联恢复。已有远端预留或启动结果不确定的记录继续核账，不手动清零，不追加启动。既有 GET 有界重试保持不变，网络错误不作为 Actor 身份或内容合同故障。

修复受阻时查看 Job 的具体错误码和 `next_attempt_at`。`actorops_repair_assignment_unavailable` 表示当前接管条件不满足；槽位释放或已确认故障满足原替换政策后，维护循环会提前唤醒修复。仅某来源失败仍不能把全局候选强制下线。`apify_transport_unavailable` 表示启动前传输失败；`apify_run_reconcile_required` 表示保留未决执行等待对账。历史 Job 结果不重写，新的失败任务和完成日志携带同一个安全错误码。
