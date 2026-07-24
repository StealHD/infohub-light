# 诊断日志开发手册

本文件是 Inteliscope 运行日志、结构化操作事件与 OpenClaw 安全查询的开发真源。它只描述本地文件可观测性；Remote MCP 的公开工具输入输出继续以 `API_CONTRACT.md` 为准。

## 1. 文件与保留策略

API、Worker、legacy Scheduler 和 CLI 统一调用 `src/logging_utils.py::configure_logging()`。默认目录是项目根目录下的 `logs/`：

- `runtime-<service>.jsonl`：运行消息和已脱敏异常，`service` 为 `api|worker|scheduler|cli`。
- `operations-<service>.jsonl`：schema v1 结构化关键操作事件。
- UTC 每日轮转，目录权限固定 `0700`，文件权限固定 `0600`。
- `HORIZON_LOG_LEVEL=INFO` 统一控制各进程的 runtime/console 级别；关键 operation event 仍按自身 `info|warning|error` 级别完整落盘，不能因提高 runtime 门槛而丢失成功状态变化。
- `HORIZON_LOG_RETENTION_DAYS=30` 控制轮转文件保留期，合法范围为 `1..365`；非法值必须在服务启动时失败。
- 启动和轮转只清理符合 `runtime|operations`、已知服务名和日期后缀的系统文件。Smoke 报告及未知历史文件不得删除。

生产镜像不包含日志；部署必须把独立的 `logs/` 目录挂载到 `/app/logs`。不要让不同服务共用同一活动文件名。

## 2. 结构化事件合同

`src/services/operation_log.py::emit_operation_event()` 是唯一事件构造入口。每行包含：

- 必需：`schema_version=1`、UTC `timestamp`、`event_id`、`service`、`level`、`category`、`action`、`outcome`。
- 可选关联：`request_id`、`job_id`、`source_id`、`subscription_id`、安全 `error_code`、`duration_ms`、`changed_fields`、整数 `counts`。
- 仅文件内隔离字段：workspace、actor 和 subject。它们永远不进入 MCP 返回。
- API 请求 ID 由服务端生成，格式为 `req_<uuid>`；不得信任客户端传入的 ID。API 与 MCP HTTP 响应通过 `X-Request-ID` 返回 API 请求 ID。

事件只接受有界枚举、标识符、字段名和计数，不接受自由文本。日志失败不得改变业务结果，业务调用使用 `safe_emit_operation_event()`。

## 3. 敏感数据边界

任何日志都不得接收或拼接以下值：

- 密码、Token、Authorization、API Key、Secret、确认短语或其他凭据。
- Webhook/邮箱目的地、URL、source config、请求 payload、环境变量名。
- 个人标签、展示名、文章 ID、标题、正文、摘要或媒体内容。
- 上游请求/响应正文、原始错误消息、远端账号资料或堆栈投影。

运行日志 formatter 会在最终渲染后再次统一移除常见凭据、邮箱、URL、环境变量名和敏感赋值；异常只保留类型及不含源码/异常文本的有界 frame 位置。这只是最后一道防线，不能替代调用点的值最小化。操作事件文件只写经过 schema 校验的对象，不写 `message` 或 `stack`。

路由日志只使用 FastAPI 模板路径，例如 `/api/jobs/{job_id}`，不得读取 query 或 body。错误只记录稳定代码；异常原文仅可进入经过统一脱敏的 runtime 文件。

## 4. 何时记录

成功事件必须在对应数据库事务提交后写入；事务回滚或泄漏只能产生安全失败事件。统一 API/MCP/Worker 边界负责失败事件，局部代码不要重复记录同一失败。

必须记录：

- 登录成功/失败、退出、个人改密及成员创建、角色/状态/密码变更。
- 来源、订阅、共享范围、Feed/单来源计划的创建、更新、启停和删除。
- Secret 引用创建/轮换/删除、Apify 池排序/排空、通知设置和邮件 transport 配置/测试。
- Agent delegation 创建、重命名、吊销、删除及每次 MCP 调用结果。
- Job 排队/去重、计划排队、领取、重试、取消和终态；来源获取与通知投递结果。

默认不记录普通 GET、Feed 浏览、已读/收藏/忽略等高频成功交互、Worker 空轮询和 heartbeat。它们只在未处理的服务端错误时进入 runtime 日志，不生成 operation event。

## 5. OpenClaw 查询边界

OpenClaw 只能调用只读 `query_operation_logs`，不能读取日志文件或路径。查询固定为：

- 默认回看 24 小时，范围 `1..720` 小时。
- 可按 category、outcome、最低级别及 Job/source/subscription/request ID 过滤。
- 默认返回 50 条，最大 100 条，最新优先。
- 每次最多扫描 20,000 行；达到扫描或返回上限时 `truncated=true`。
- 损坏、未写完、非 schema v1 或被篡改的行跳过；目录缺失为 `empty`，不可安全读取为 `unavailable`。

查询必须同时匹配 delegation 的 workspace，并要求当前调用者是事件 actor 或 subject。Owner/Admin 没有跨用户例外；跨用户对象 ID 过滤返回空集合。返回白名单字段、查询窗口、`availability`、`returned` 和 `truncated`，不返回身份、文件信息、原始消息、内容、URL、凭据或堆栈。

前端只在“助手连接”生成的 OpenClaw `toolFilter` 中包含该工具。不得新增日志 REST API、日志列表、日志正文组件或前端查询缓存。

## 6. 开发与排障

常用关联顺序：

1. 从 API 响应的 `X-Request-ID` 定位请求事件。
2. 对异步操作从排队事件取得 `job_id`，再串联 Worker claim、acquisition、notification 和终态。
3. 优先使用 MCP 的最窄 ID 与最短窗口；服务器维护者确需读原始 runtime 文件时，只读取相关服务和时间段，不复制完整日志。
4. `availability=unavailable` 时检查挂载、所有者、`0700/0600` 权限及符号链接；不要降低权限或改为前端展示。

定向验证：

```bash
python -m pytest -q \
  tests/test_logging_utils.py \
  tests/test_operation_log.py \
  tests/test_api_operation_logging.py \
  tests/test_remote_mcp_http.py \
  tests/test_worker.py
python3 -m json.tool project-defaults.yaml >/dev/null
git diff --check
```

不要用真实来源、AI、付费 Provider 或完整 Scheduler 验证日志。
