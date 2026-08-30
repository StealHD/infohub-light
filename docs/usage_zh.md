# Inteliscope 使用说明

这份说明面向日常使用和小范围分享。当前部署入口为 `https://rb.jiefs.top/`，本地默认入口为 `http://127.0.0.1:8080/`。

## 1. 登录与角色

Service API 始终要求应用账号登录。角色分为 `owner/admin/member/viewer`：

- Owner/Admin 管理成员、工作区来源、AI/Apify Key、通知服务、ActorOps 与存储治理。
- Member 管理自己的 private 来源、订阅、Feed 状态和允许的 Agent 连接。
- Viewer 可阅读自己的 Feed、历史、来源和运行记录，但不能执行写操作。

Nginx Basic Auth 只能作为可选外层门禁，不能替代应用登录和角色权限。

## 2. Feed、收藏与历史

主要页面为：

- `/feed`：当前用户时间窗口内的 Feed，支持时间流和来源概览。
- `/saved`：收藏与稍后读集合；历史 `/later` 会重定向到这里。
- `/history`：当前 Feed 窗口之前的稳定内容。
- `/subscriptions`：我的订阅、来源库和运行记录。
- `/agents`：Remote MCP delegation 与浏览器 OpenClaw 连接。
- `/settings/*`：通知、AI、获取、忽略、密钥、ActorOps 和存储治理。

选中或打开条目不会自动标记已读。收藏、稍后读、忽略和已读/未读只修改当前用户的 item state。Feed 搜索覆盖当前窗口、在线历史和现役冷归档元数据，但不会把旧内容移回 Feed。

右上角“重新载入”只读取最新投影；“获取新内容”创建或复用 `user_feed_refresh` Job。任务完成后页面重新读取 Feed，同一账号重复提交不会创建并发刷新。

## 3. 来源与计划

来源可见范围为 public、workspace 或 private。创建来源后可订阅；订阅 shared 来源不会改变其他用户，最后一个 private owner 取消订阅时会软停用无人引用来源。

自动计划全部由现有 Worker 执行：

- 每用户 Feed 周期：1/3/6/12/24 小时，默认关闭。
- 每订阅单源周期：30 分钟或 1/3/6/12/24 小时，默认跟随全局。

它们创建普通 `user_feed_refresh` 或 `source_fetch` Job，共用去重、配额、Source Health、Feed finalization 和通知规则。没有 scheduler 服务或 profile。

## 4. 通知服务

`/settings/notifications` 使用统一“通知服务”界面：

- Owner/Admin 创建和维护 workspace Email、Webhook、Telegram 服务。
- 目的地和凭据只在写请求中出现，提交后不回显。
- `保存并测试` 只发送一次明确的模拟消息；成功后启用该 service generation。
- 用户在“个人新内容通知”中选择服务，并在订阅卡片上逐源 opt-in。

首份 snapshot、历史复用内容、通知关闭期间发现的内容都不补发。通知失败不会改变 Feed 或重跑来源获取。

## 5. 设置与密钥

Owner/Admin 可在原生设置页管理：

- AI Key、Provider/Model 和安全输入输出上限。
- RSSHub Base URL、获取窗口与主题库。
- Apify Key Pool、ActorOps、发现与付费 Canary 审批。
- 存储概览、标准清理、冷归档与恢复。

真实 Key、Token、Webhook URL、SMTP 密码和 Chat ID 只写入 `data/secrets.env`，权限为 `0600`；页面、API、日志、Job 和数据库只保存安全引用/摘要。

### ActorOps 稳定维护

ActorOps 现在按三阶段处理候选：先从商城按 Route 相关性和公开质量选取少量候选，再结合 exact Build/Schema 与真实 Dataset 判断是否“系统可用”，最后才进入费用对账、主备应用和正式抓取。静态字段匹配只表示分析完成，不代表已经可替换；真实 Dataset 的身份、URL、时间和内容验证通过且费用已结算后才成为可用证明。

Dataset 可以是平铺、嵌套或混合记录。系统会在一次已授权实测中有界展开发布子项，并继承父级作者/频道身份。若首次实测只因字段映射失败，费用结算后会自动复用同一已付费 Dataset 做最多两轮重映射和零费用重验，不再次启动 Actor、也不再次询问实测授权；界面会显示当前处于费用对账、Dataset 读取、自动适配或零费用重验。两轮仍无法证明时保留 Actor 并报告具体缺口，不直接判定 Actor 故障。最终把 Candidate 应用到主用或备用仍需管理员确认。

`/settings/actorops` 的健康状态按每条已就绪来源 Binding 实际能使用的 Actor 路径计算，不再只看主用/备用槽位是否有值。黄色“最近失败”仍允许退避后的受控探测，红色“已确认故障”会停止继续调度该 Actor；成功恢复后标签自动清除。卡片同时显示稳定路径、冷却数量、风险来源和原生降级，展开详情可查看脱敏 Repair、Discovery、费用与维护状态。

新建数据库和未曾改动过的 workspace/Route 维护策略默认按既有安全预算开启；管理员显式关闭会一直保留。没有 enabled Owner/Admin 时维护只显示等待授权，不创建无人负责的任务。默认维护可免费搜索候选、在预算内串行 Probe 和补充备用；只有候选已对当前来源取得最终业务有效证明，且旧 Actor 是已确认故障的非最后一路时才会自动替换。YouTube 还必须明确支持包含 Shorts 的全部内容与最新排序；能力不明、证据不足和最后一路继续由管理员处理。卡片固定显示备用 1/2；空槽可直接“补充备用”，已占用槽位可替换，均可继续使用人工确认流程。取消不会抹除已经发起或待对账的费用事实。

Route 卡的“管理 Actor”会把搜索、选择主用/备用槽位、候选比较、免费预检、实测和应用放在同一个 Drawer 内；已有任务时卡片直接显示“继续搜索/继续实测/等待应用”，关闭或刷新页面后仍会恢复进度。系统按公开质量和当前可用证据自动推荐一个候选，管理员仍可改选。Drawer 会保留已确认故障或字段映射未完成候选的公开资料和安全原因，但禁止继续选择。免费 Discovery 会合并平台 Adapter 的多个能力搜索词，按 Actor 去重后依据公开用户量、评分、评价数和收藏数排序，再读取最多 12 个高质量 exact Actor/Build；不会因第一个窄查询先返回低使用量结果而漏掉通用高质量 Actor。系统随后按每个 exact Build 的公开 Schema 生成独立字段映射；确定性规则先匹配输入、帖子字段和身份，确定性 proposal 未通过严格证明时也会进入 AI fallback，不会直接卡在 `mapping_pending`。YouTube 频道来源兼容原生 RSS 的 `url` 与社交来源的 `target`，并识别常见 `channelId/channelUrls/channelUrl`、`maxResults` 和视频 `id/url/date/title/channelId` 字段。X 帖子没有独立作者字段时，可复用同一帖子 URL并在真实输出中提取 handle 核验；头像或其他 URL 不能冒充用户名。若高质量 Actor 只提供高级搜索，系统仅在公开 Schema 明确包含 `Advanced Search`、`Latest`、作者用户名和数字帖子 ID 时，把订阅账号安全编译为 `from:<账号>`，并可由作者用户名和帖子 ID 生成标准 X 帖子 URL；AI 不能自己拼模板或 URL。缺少头像、作者显示名等展示增强字段不会丢弃正文，作者用户名仍用于身份核验、作者链接和去重。通过的 exact Build/Schema 映射写入数据库缓存，后续直接复用。不能证明时会具体显示“缺少帖子作者用户名字段”“输出不是帖子列表”“缺少订阅账号输入”或缺少帖子 ID/URL/时间/正文，不再只显示“合同不兼容”。此流程只调用已配置 AI，不启动 Apify Actor，不产生 Actor 实测费用。点击“免费检查并准备实测”时，系统先免费检查当前来源输入合同、target fingerprint、冻结 Build、Actor/Build 身份、Schema 与价格；失败会说明是缺少原生目标 ID、handle、主页 URL、Manifest 无效、输入模板不可渲染或固定 Build/Schema 变化，并明确尚未创建 Attempt、Apify Run，费用为 `$0`。例如仅保存 X handle 的来源遇到要求 `target.native_id` 的 Actor，会提示“需要原生用户 ID，请改选支持 handle 的 Actor”。免费检查通过后，按钮会直接标明本计划最高费用；点击即可授权实测，无需再输入确认短语。授权后的启动前仍会再次免费复核，防止两次操作之间状态变化。全部来源证明和费用终结后，点击“应用到主用/备用”才会真正改变槽位。

Owner/Admin 可通过 Recovery Probe API 对仍占用主用或备用槽位的“已确认故障” Actor 做一次原位恢复实测。请求必须输入固定确认词 `确认实测恢复 Actor`，并携带页面最新的 Route、Candidate、Binding generation 与失败时间；系统在 validation 费用域中最多启动一次、只请求一个计费结果且单次上限 `$0.05`。为识别忽略条数限制的 Actor，系统会有界检查 Dataset 实际返回的前四行，任一外部账号或合同漂移都会使实测失败。成功只恢复当前 Actor 的调度资格，不替换槽位、不发布 Feed；费用未结、请求期间出现新故障或任一版本变化都会保持待对账并要求刷新。当前页面仍以人工替换作为可见故障操作，Recovery Probe 是管理员 API 能力。

Actor 商城详情只显示头像映射“已就绪 / 待发现 / 待刷新”。系统只在内容合同已经验证成功后，从当前 exact Build/Schema 的 Manifest、Schema 或实际输出中寻找并验证 HTTP(S) 头像；大对象只遍历再次通过目标身份校验的有界 Mapping。Instagram 协作帖只有在协作者列表 exact 命中目标账号时才允许用内存副本完成身份校验：direct 目标头像优先，没有 direct 头像时才采用 exact matched coauthor 自身头像，其他发布者头像不会映射给来源。URL 不进入 ActorOps 管理响应、日志、映射表、Feed 或公开 Job diagnostics；正常抓取只可在私有 acquisition cache 的 freshness 窗口内保留 proof-bound URL，以便首次媒体下载失败后由缓存命中重试。已结算且身份/合同仍有效的历史 Dataset 可只读重放映射和头像落盘，不会启动新的 Apify Run；头像媒体仍经过公共网络地址固定、类型与 2 MiB 上限校验，并只以登录保护的 `/api/media/*` 暴露。缺少头像不会让有效内容抓取失败。

## 6. OpenClaw 与 Remote MCP

`/agents` 可创建当前用户自己的 delegation。Read 连接只访问该用户的安全 Feed、来源、健康、Job 和脱敏诊断；受控订阅写入需要单独选择权限、服务端开关和实时角色校验。

浏览器 OpenClaw 对话是另一条 opt-in 连接，浏览器直接连接用户自己的 Gateway；Inteliscope 不代理 Gateway，也不保存 bootstrap token。Remote MCP 的唯一服务端入口是 `/mcp`，仓库不再提供本地 stdio MCP。

## 7. 数据边界

当前 latest/history/search 真源是 `data/service.db`。Service DB 继续双读既有完整 snapshot 与 compact snapshot；现役冷归档位于 `data/archives/**`，由 `/api/admin/storage/*` 管理。

以下历史数据已经停止读写，但本次退役不会物理删除：

- `data/site/**`
- `data/horizon.db`
- 旧 summaries
- 旧本地 MCP run
- 既有 feedback 表和行

Fresh DB 不再创建 feedback 表。旧 `/api/archive/{graph,items,trends,facets,source-quality}` 与 feedback POST 已删除，访问时返回统一 404，OpenAPI 不再列出。

`data/config.json` 中历史 `email/webhook/premium_analysis/article_graph` 块会原样保留在磁盘，但 API 不返回、现役代码不执行、配置 action 不改写。

## 8. 管理员运维

查看服务与日志：

```bash
ssh vps-tokyo
cd /opt/inteliscope/current
docker compose ps
docker compose logs -f horizon-api horizon-worker
```

正常发布从本地、干净且与 `origin/main` 一致的 `main` 执行：

```bash
./scripts/release_vps.sh preflight vX.Y.Z
./scripts/release_vps.sh release vX.Y.Z
./scripts/release_vps.sh status
./scripts/release_vps.sh rollback [release-id]
```

镜像必须在本地构建并验证 `linux/amd64`，VPS 只执行 `docker load`。切换前脚本检查活跃 Job，并在发现残留历史 scheduler 容器时阻断。普通发布失败回滚到上一不可变 API/Worker release；包含数据库迁移的版本必须走独立 runbook。

ActorOps global 33 是当前独立停机迁移，并要求有效 global 32。停止 API/Worker 后先只读检查，再显式应用；它只安装本地 circuit、维护来源标记与头像映射 sidecar，不会调用 Actor、AI 或真实来源，也不会创建、结算或删除费用事实。

```bash
.venv/bin/python scripts/migrate_actorops_v2_stability.py --data-dir data
.venv/bin/python scripts/migrate_actorops_v2_stability.py --data-dir data --backup-dir data/backups --apply
```

应用会创建 `0600` 备份并验证 marker/shape、完整性和外键；partial schema 或 version 33 被占用会拒绝继续，失败恢复备份。未改动的策略切为 `system_default` 开启，管理员已经显式关闭的策略保持关闭，Route 自动替换统一关闭。迁移完成前，只有 ActorOps 来源和管理链路提示需要迁移；普通 RSS/GitHub 不受影响。

随后安装 global 34。它只收紧“历史 Dataset 重验后恢复 Candidate”的数据库边界，不启动 Actor、AI 或来源请求：

```bash
.venv/bin/python scripts/migrate_actorops_v2_revalidation.py --data-dir data
.venv/bin/python scripts/migrate_actorops_v2_revalidation.py --data-dir data --backup-dir data/backups --apply
```

随后依次安装 global 35 私有 InputPlan 与 global 36 已验证自动替换门。两步都要求 API/Worker 已停止，先 preview 再显式 apply；不会联网或启动 Actor：

```bash
.venv/bin/python scripts/migrate_actorops_v2_sampling.py --data-dir data
.venv/bin/python scripts/migrate_actorops_v2_sampling.py --data-dir data --backup-dir data/backups --apply
.venv/bin/python scripts/migrate_actorops_v2_verified_replacement.py --data-dir data
.venv/bin/python scripts/migrate_actorops_v2_verified_replacement.py --data-dir data --backup-dir data/backups --apply
```

替换若因发布时间、作者身份、帖子 URL、时间窗口或通用输出映射错误失败，且原费用与 Dataset 已结算，Drawer 会提供“重新验证已有结果（$0 Actor 费）”。系统免费复核固定 Build，并用当前映射规则只读原 Dataset；有效内容会保留原失败 Attempt 和原费用，另建一条 `$0` proof 与新替换计划。若合同已兼容但该批内容按订阅规则全部被过滤（例如 X 全部为回复），系统只解除错误的合同故障并把 Candidate 恢复为 static_valid，不把空结果算作替换成功；新计划仍需重新实测。仍缺其他来源证明时只继续缺少的 Probe，不重复启动已经证明过的 Actor，也不会自动应用替换。

首次空数据库只使用 `scripts/release_rc1.sh`。失败时停止新 API/Worker 并保留诊断数据，不恢复旧 Web。

## 9. 本地启动与验证

```bash
cp .env.example .env
./scripts/up-latest.sh
curl http://127.0.0.1:8080/api/health/live
curl http://127.0.0.1:8080/api/health/ready
```

必须从准备验证的 Worktree 运行 `up-latest.sh`。脚本通过 Git common directory 使用主 checkout 的 `.env`、`data` 和 `logs`，按当前 HEAD、tracked diff 与 untracked 文件计算 source digest；dirty 构建的 revision 会包含该摘要，构建期间源码改变则拒绝启动。启动后还会核对 API/Worker revision、两个容器的 source-digest label、Docker health 和实际 React 资源，避免把旧容器误认为当前代码。

若新镜像需要显式迁移，脚本只会在确认 migration-required 来自目标 revision 后停止 API/Worker、打印精确迁移命令并退出，不会替用户自动迁移。检查备份影响、执行上面的 preview/apply 后，再从同一 Worktree 重跑 `./scripts/up-latest.sh`；不要用临时 Compose override、运行目录软链接或主 checkout 的旧代码替代这条流程。

全量验证：

```bash
python scripts/test_gate.py run --mode full
python scripts/test_gate.py run --mode release
git diff --check
```

门禁不会运行真实来源、AI、付费 Actor、通知发送或 scheduler。
