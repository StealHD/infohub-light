# Bilibili Apify 采集

Bilibili 的现役适配器为 `bilibili/profile/items`，仅接受一个公开 UP UID/空间主页并验证输出 UID、视频链接和时间。输入/输出字段、Actor 多模式选择和确定性 RSS 视频 ID 兼容归 `adapters/bilibili/`；`bilibili_source_identity.py` 识别受控及旧 RSSHub URL 身份，`bilibili_actor_source.py` 只作运行时投影。旧目录仍为 RSS，ready Binding 才注入路线，pending/missing 永不落回 RSSHub；原生 fallback 返回 unsupported。主备发现、费用、未知启动、熔断、恢复和 publication 复用通用 v2。`migrate_bilibili_actor_sources.py` 是显式数据切换入口：默认只读预览，应用要求 API/Worker 停止、队列和远端 Run 空闲、私有备份及事务后检；补齐 disabled Route 和 pending/disabled Binding，主动停用及已有 Binding 保留，不触发抓取、AI 或通知。新库随 Registry 初始化注册路线。

目录和订阅继续使用兼容 RSS 身份；公开视频投稿是唯一内容范围，名称搜索保留现有服务。BV/AV 原文链接按 RSSHub 的发布时间分界规范化后生成原 RSS 内容 ID，原始 URL 来源保留旧 feed 身份；不改写已读、收藏或通知账本。付费实测和主备启用遵守 [ActorOps](agent-observability-actorops.md) 预算和授权合同，切换工具本身不授权任何付费动作。

运行操作与恢复遵守 [运行时与迁移](jobs-notifications-runtime-migrations.md) 的 Bilibili 切换入口。

生产发布使用原库执行 `migrate_bilibili_actor_sources.py --data-dir /opt/inteliscope/data --apply --services-stopped --release-revision FULL_SHA --release-receipt /opt/inteliscope/data/backups/bilibili-FULL_SHA.json`。先在本机构建新版本镜像并传到 VPS，再停止 API/Worker、跨 heartbeat 安全窗并确认队列和 Actor Run 空闲；在新镜像内原位迁移，挂载生产运行根目录以保持回执路径一致。回执绑定完整发布 SHA、私有迁移前备份和 Bilibili 绑定指纹；标准 `release_vps.sh release vX.Y.Z --migration-receipt ABSOLUTE_PATH` 必须复核后才允许切换和发布 Tag。迁移只补齐路线及绑定，不启用 Actor 或发起采集；固定 Build 的主备须在生产环境独立验证、结算后应用和受控启用。失败切换恢复旧程序并保留当前业务数据库，迁移前备份留作人工恢复，禁止用预览数据库或 SecretStore 覆盖生产。

多模式候选只选择用户公开视频列表操作，兼容 camelCase/snake_case 字段；同时存在总行数和每位 UP 视频限制时，优先绑定后者，避免 UP 资料占用视频配额。可空字段按 Schema 证明的指针顺序回退，资料行可识别但不能当作视频证据；归属优先读取实际 uploader/author UID，不以请求 UID 或资料行替代；联合投稿缺少目标 UP 参与证据时仍阻断。发现时重新规范旧的无结构映射，保留已有结构提取和参与者声明。

UP 列表可能包含其他首位作者的联合投稿；批次同时证明目标 UP 的真实视频时，过滤归属其他 UP 的条目。没有任何目标 UP 视频时保留失败语义，不以资料行或联合投稿标记替代归属证明；时间、视频链接和输出数量校验仍逐项执行。

首次配置允许 disabled Bilibili Route 的显式主用实测计划冻结 pending Binding，排除 disabled Binding；预检、授权、单来源费用上限、计划总额及未知启动锁保持不变。每个冻结目标均须真实返回公开视频并结清费用，才允许应用首个主 Actor；应用本身不启用路线，仍须停 API/Worker 后经 `actorops_v2_cutover.py --platform bilibili` 执行受控切换。已存在主 Actor 的路线沿用 ready Binding 的替换流程。旧 RSS 配置只在 Actor 输入和目标指纹边界投影为公开空间身份；nullable 标量 Schema 不应使候选发现崩溃。
