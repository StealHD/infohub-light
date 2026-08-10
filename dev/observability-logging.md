# 诊断日志开发手册

本文件是 Inteliscope 运行日志、结构化操作事件与 OpenClaw 安全查询的开发真源。它只描述本地文件可观测性；Remote MCP 的公开工具输入输出继续以 `docs/contracts/api/remote-mcp.md` 为准。

## 1. 文件与保留策略

API、Worker、legacy Scheduler 和 CLI 统一调用 `src/logging_utils.py::configure_logging()`。默认目录是项目根目录下的 `logs/`：

- `runtime-<service>.jsonl`：运行消息和已脱敏异常，`service` 为 `api|worker|scheduler|cli`。
- `operations-<service>.jsonl`：schema v1 结构化关键操作事件。
- UTC 每日轮转，目录权限固定 `0700`，文件权限固定 `0600`。
- `HORIZON_LOG_LEVEL=INFO` 统一控制各进程的 runtime/console 级别；关键 operation event 仍按自身 `info|warning|error` 级别完整落盘，不能因提高 runtime 门槛而丢失成功状态变化。
- `HORIZON_LOG_RETENTION_DAYS=30` 控制轮转文件保留期，合法范围为 `1..365`；非法值必须在服务启动时失败。
- 启动和轮转只清理符合 `runtime|operations`、已知服务名和日期后缀的系统文件。Smoke 报告及未知历史文件不得删除。
- Uvicorn 必须由该配置接管，入口固定使用 `log_config=None` 和 `access_log=False`；生产路径不得自行 `print`、调用 `basicConfig()` 或增加文件 handler。

生产镜像不包含日志；部署必须把独立的 `logs/` 目录挂载到 `/app/logs`。不要让不同服务共用同一活动文件名。

## 2. 结构化事件合同

`src/services/operation_log.py::emit_operation_event()` 是唯一事件构造入口。每行包含：

- 必需：`schema_version=1`、UTC `timestamp`、`event_id`、`service`、`level`、`category`、`action`、`outcome`。
- 可选关联：`request_id`、`job_id`、`source_id`、`subscription_id`、`stage`、安全 `error_code`、稳定 `error_fingerprint`、`duration_ms`、`changed_fields`、整数 `counts`。
- 仅文件内隔离字段：workspace、actor 和 subject。它们永远不进入 MCP 返回。
- API 请求 ID 由服务端生成，格式为 `req_<uuid>`；不得信任客户端传入的 ID。API 与 MCP HTTP 响应通过 `X-Request-ID` 返回 API 请求 ID。

`src/observability_context.py` 是 API、MCP 和 Worker 共用的关联上下文边界。入口只写上述安全标识与阶段，内部调用通过 `ContextVar` 自动继承；退出时必须 reset，防止并发请求或 Job 串线。异常指纹只能由 revision、异常类型和安全 frame 位置生成，不得包含异常消息。

事件只接受有界枚举、标识符、字段名和计数，不接受自由文本。每次文件写入必须实际 flush 并回报成功或失败；业务调用使用 `safe_emit_operation_event()`，日志失败不得回滚已经提交的业务事务，也不得把成功响应改成失败。API readiness 通过 `logging_status=ready|degraded` 单独披露 sink 健康，日志降级本身不把 readiness HTTP 200 改为 503。

## 3. 敏感数据边界

任何日志都不得接收或拼接以下值：

- 密码、Token（含 Telegram Bot Token）、Authorization、API Key、Secret、确认短语或其他凭据。
- 通知目标中的 Webhook/邮箱/Telegram Chat ID 目的地、URL、Secret 引用/摘要、source config、请求 payload、环境变量名。
- 个人标签、展示名、文章 ID、标题、正文、摘要或媒体内容。
- 上游请求/响应正文、原始错误消息、远端账号资料或堆栈投影。

运行日志 formatter 会在最终渲染后再次统一移除常见凭据、邮箱、URL、环境变量名和敏感赋值；异常只保留类型及不含源码/异常文本的有界 frame 位置。这只是最后一道防线，不能替代调用点的值最小化。操作事件文件只写经过 schema 校验的对象，不写 `message` 或 `stack`。

路由日志只使用 FastAPI 模板路径，例如 `/api/jobs/{job_id}`，不得读取 query 或 body。错误只记录稳定代码；异常原文仅可进入经过统一脱敏的 runtime 文件。

## 4. 何时记录

成功事件必须在对应数据库事务提交后写入；事务回滚或泄漏只能产生安全失败事件。统一 API/MCP/Worker 边界负责失败事件，局部代码不要重复记录同一失败。

必须记录：

- 登录成功/失败、退出、个人改密及成员创建、角色/状态/密码变更。
- 来源、订阅、共享范围、Feed/单来源计划的创建、更新、启停和删除。
- Secret 引用创建/轮换/删除、Apify 池排序/排空、通知目标创建/更新/测试/启停/归档、业务目标绑定和邮件/Telegram transport 配置/测试。
- Agent delegation 创建、重命名、吊销、删除及每次 MCP 调用结果。
- Job 排队/去重、计划排队、领取、资格检查、执行、持久化终态、重试、取消、失效取消、stale lease 恢复和终态；claim 前边界失败也必须留下安全事件。
- 每个 Job 类型必须在 Worker trace policy 中显式声明；每个来源获取结果、来源头像缓存和通知投递都要带可关联的 Job/source/subscription 与 stage。
- 存储治理计划的预演与 apply 结果使用 `category=storage`，只记录 operation、结果、稳定错误码和有界候选/处理计数；不得记录归档路径、确认短语、候选 ID、正文或 manifest。

默认不记录普通 GET、Feed 浏览、Worker 空轮询和 heartbeat。item-state 与兼容 feedback 属于写接口，成功或失败都由统一 API mutation 边界记录；普通 GET 未处理异常使用 `category=request/action=unhandled_error`。同一异常只允许最外层边界生成一个 operation failure，局部实现只写安全 runtime 诊断。

## 5. OpenClaw 查询边界

OpenClaw 只能调用只读 `query_operation_logs`，不能读取日志文件或路径。查询固定为：

- `scope=self` 为缺省，只返回 actor 或 subject 为当前 delegation 用户的事件。
- `scope=workspace` 只允许创建连接时由当前 `owner/admin` 显式授予；现有连接保持 `self`，不能 PATCH 提权，实时角色降级后立即拒绝。
- workspace 查询必须带 Job/source/subscription/request ID 之一，或将 `minimum_level` 设为 `warning|error`；无标识的全量 info 查询返回 `diagnostics_filter_required`。
- 默认回看 24 小时，范围 `1..720` 小时。
- 可按 category、outcome、最低级别及 Job/source/subscription/request ID 过滤。
- 默认返回 50 条，最大 100 条，最新优先。
- 每次最多扫描 20,000 行；达到扫描或返回上限时 `truncated=true`。
- 损坏、未写完、非 schema v1 或被篡改的行跳过；目录缺失为 `empty`，不可安全读取为 `unavailable`。

所有查询都必须匹配 delegation 的 workspace。self 查询继续要求当前调用者是事件 actor 或 subject；workspace 查询只越过该 actor/subject 条件，不取得业务对象、身份字段或原始日志，并额外生成一条安全 MCP 审计事件。返回白名单字段、查询 `scope`、窗口、`availability`、`returned` 和 `truncated`，不返回身份、文件信息、原始消息、内容、URL、凭据或堆栈。

前端只在“助手连接”生成的 OpenClaw `toolFilter` 中包含该工具。不得新增日志 REST API、日志列表、日志正文组件或前端查询缓存。

## 6. 开发与排障

常用关联顺序：

1. 从 API 响应的 `X-Request-ID` 定位请求事件。
2. 对异步操作从排队事件取得 `job_id`，再串联 Worker claim、acquisition、notification 和终态。
3. 未知 API 异常只向调用方返回 `internal_error` 和 `X-Request-ID`；用该 ID 匹配 `request/unhandled_error` 与相同 `error_fingerprint`，不要向用户索要异常原文。
4. 优先使用 MCP 的 `self`、最窄 ID 与最短窗口；确需工作区排查时，由 Owner/Admin 新建显式授权连接。服务器维护者确需读原始 runtime 文件时，只读取相关服务和时间段，不复制完整日志。
5. readiness 的 `logging_status=degraded` 表示 runtime 或 operation sink 最近写入失败；检查挂载、所有者、空间、`0700/0600` 权限及符号链接，不要降低权限或改为前端展示。
6. `availability=unavailable` 只表示查询端无法安全读取；它与 sink 健康是两个信号，不能互相推断。

定向验证：

```bash
python scripts/check_observability_contract.py
python -m pytest -q \
  tests/test_logging_utils.py \
  tests/test_operation_log.py \
  tests/test_api_operation_logging.py \
  tests/test_remote_mcp_http.py \
  tests/test_worker.py
python scripts/test_gate.py run --mode full
python3 -m json.tool project-defaults.yaml >/dev/null
git diff --check
```

`check_observability_contract.py` 会在 targeted、full 和 release 的所有 scope 前执行，并阻止未映射写路由、未声明 Job 类型、生产 `print`、独立日志配置、未收口 Uvicorn 或缺少关键 Worker 生命周期事件。Test Gate 只持久化经过运行时同源脱敏器处理的 `0600` 日志，不保留具名 raw 临时文件。

不要用真实来源、AI、付费 Provider、Worker 或完整 Scheduler 验证日志。
