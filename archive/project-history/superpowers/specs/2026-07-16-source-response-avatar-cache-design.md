# X CDN 头像缓存与来源响应结构设计

## 1. 目标

本设计解决三个相互关联的问题：

1. Xquik 已返回 X 头像，但 `pbs.twimg.com` 在本地合成 DNS 环境下被公共网络策略拒绝，导致头像无法进入受保护的本地媒体缓存。
2. 来源头像一旦缓存便永久复用，不能在上游头像发生变化时安全更新。
3. 来源运行记录只能看到任务状态，不能比较上游实际返回结构和系统标准化后的结构。

本阶段不保存或展示任何上游字段值，不新增付费抓取，不扩大 scheduler、Worker 或 VPS 权限，不改变 Feed 内容、AI 分析或来源计费语义。

## 2. 已确认方案

采用方案 A：把有界响应结构摘要写入现有 terminal Job 的 `result_json`。结构摘要沿用 Job 的用户隔离、权限、保留和清理策略，不新增独立历史表。

运行记录同时展示：

- 上游原始结构：适配器在原始响应转换为 `ContentItem` 前看到的记录结构。
- 系统标准化结构：该次运行实际生成的 `ContentItem` 结构。

两层只包含字段路径、字段类型和截断状态。

## 3. X CDN 安全边界

`src/services/network_policy.py` 继续执行现有逐跳策略：

- 仅允许 HTTP/HTTPS 且禁止 URL userinfo。
- 初始请求与每次重定向都重新解析并审核全部地址。
- 连接固定到审核通过的地址并保留原 Host/SNI。
- 隔离代理环境，拒绝压缩响应并执行流式大小限制。
- 非公开地址默认拒绝。

媒体缓存新增独立 X 媒体后缀集合，第一阶段只包含精确后缀 `pbs.twimg.com`。仅当主机匹配该后缀，且全部非公开解析地址都位于既有 `198.18.0.0/15` 合成 DNS 网络时，才允许继续连接。`pbs.twimg.com.example.com`、其他 `twimg.com` 主机、私网地址、回环地址和不匹配的合成 DNS 地址继续拒绝。

允许合成 DNS 不绕过后续防护。响应仍必须不超过 8 MiB，并通过 PNG、JPEG、GIF 或 WebP 文件魔数检测后才能落盘。

## 4. 头像版本更新

### 4.1 头像身份

远端头像身份由规范化 URL 计算：

- scheme 和 host 转为小写；
- 保留显式端口和 path；
- 删除 query 与 fragment。

忽略 query 可避免 Instagram 等签名 URL 每次刷新都被误判为新头像。常见 X/Instagram 头像更新会改变 path；path 变化视为新版本。

### 4.2 更新规则

每次抓取项目携带远端头像地址时：

1. 当前来源没有 ready 头像：下载并创建首个版本。
2. 远端身份与现有头像不同：立即下载候选版本。
3. 身份相同且现有头像在 24 小时内复验过：直接复用，不发起头像请求。
4. 身份相同但超过 24 小时：下载候选内容并比较 SHA-256。
5. checksum 相同：复用现有文件，只更新当前远端 URL 和 `updated_at`。
6. checksum 不同：原子写入新文件和新 ready 记录，然后删除该来源的旧头像记录与文件。

`created_at` 表示头像版本创建时间，`updated_at` 表示最近一次成功复验时间，因此不需要新增数据库列或显式迁移。

### 4.3 失败语义

候选头像下载、网络审核、大小校验、类型校验或落盘失败时：

- 已有头像继续保持 ready 并供 UI 使用；
- 不删除旧文件和旧记录；
- 不把失败候选写入 Feed、详情或 DOM；
- 头像失败保持 best-effort，不把成功的来源抓取改成失败。

来源身份配置变化时，现有显式 `invalidate_source_avatar` 行为继续保留。

## 5. 响应结构摘要

### 5.1 数据结构

Job `result_json` 新增可选字段：

```json
{
  "response_schemas": [
    {
      "source_id": "src_example",
      "catalog_type": "apify_social",
      "capture_status": "captured",
      "upstream": {
        "root_type": "array",
        "fields": [
          {"path": "author.profilePicture", "type": "string"}
        ],
        "truncated": false
      },
      "normalized": {
        "root_type": "array",
        "fields": [
          {"path": "metadata.author_avatar_url", "type": "string"}
        ],
        "truncated": false
      }
    }
  ]
}
```

`capture_status` 固定使用：

- `captured`：本次直接观察到上游结构。
- `empty`：上游成功但没有可供推断字段的记录。
- `cached`：本次使用共享内容缓存，没有重新观察上游结构。
- `unavailable`：失败发生在结构可捕获之前，或适配器不支持结构捕获。

### 5.2 字段提取

新增纯函数结构提取器，输入任意 JSON-like 值，输出排序稳定的字段列表。类型仅允许：

- `object`
- `array`
- `string`
- `integer`
- `number`
- `boolean`
- `null`
- `mixed`

数组中多个记录的同一路径会合并；类型冲突输出 `mixed`。不输出数组长度、样本数量或任何字段值。对象 key 必须是最多 80 字符的普通字段标识；控制字符、疑似动态内容或超长 key 统一显示为 `[dynamic-key]`，避免把上游内容误当字段名保存。

每个来源的每一层结构最多：

- 6 层；
- 256 个字段路径；
- 序列化后 8 KiB。

单个 Job 的全部结构摘要最多 64 KiB。达到任一限制时保留已经稳定排序的前缀并写入 `truncated=true`，不得因结构过大让抓取任务失败。

### 5.3 数据流

适配器只在内存中短暂持有原始响应：

1. 解析 JSON、XML 或 HTML 为适配器记录。
2. 立即调用结构提取器并保存纯结构摘要。
3. 按现有逻辑生成 `ContentItem`。
4. Orchestrator 从适配器读取本次上游摘要，并从实际 `ContentItem.model_dump(mode="json")` 生成标准化摘要。
5. `SourceOutcome` 携带可选的安全摘要；`safe_run_diagnostics` 在统一大小限制后写入 Job `result_json`。
6. Feed snapshot、`user_content_items`、AI prompt 和媒体元数据都不保存结构摘要。

共享获取命中时不得把旧结构冒充本次观察结果，状态写为 `cached`。失败发生在响应解析前时写为 `unavailable`。成功的空数组写为 `empty`。

## 6. API 与权限

不新增 API endpoint。现有 `GET /api/jobs` 和 `GET /api/jobs/{id}` 在终态 Job 的 `result/result_json` 中返回可选 `response_schemas`。

权限继续沿用 Job 边界：普通用户只能读取自己的 Job；管理员现有排查能力不扩大。结构摘要不包含 source config、Actor 输入、请求 URL、正文、用户名、字段值、密钥、Token、Cookie、Header、错误堆栈或带 query 的地址。

旧 Job 没有 `response_schemas` 时保持兼容，UI 显示“本次运行未记录响应结构”。

## 7. 运行记录 UI

React 运行记录卡片保留现有摘要和“技术详情”。对包含 `response_schemas` 的 Job 新增默认折叠的“响应结构”：

- 先按来源名称分组；找不到名称时显示 `catalog_type`。
- 每个来源依次显示“上游响应”和“标准化结果”。
- 字段使用两列结构表：字段路径、类型。
- `empty/cached/unavailable` 和 `truncated` 使用明确中文说明。
- 折叠区域不自动加载其他接口，不把任何结构字段写入全局通知。
- 390px 视口下字段路径允许断行，页面不得水平溢出；折叠控件保留键盘与屏幕阅读器语义。

## 8. 测试与验收

实施必须按 TDD 依次覆盖：

1. 网络策略：`pbs.twimg.com` 合成 DNS 可用；相似域名、其他后缀、私网和非法重定向仍拒绝。
2. 头像缓存：首次创建、24 小时内复用、query 轮换复用、身份变化更新、到期同 checksum 复验、到期不同 checksum 替换、失败保留旧头像、旧文件清理和用户媒体授权。
3. 结构提取：嵌套对象、数组合并、混合类型、空响应、动态 key、深度/字段/字节截断、排序稳定及注入 secret/正文/URL 后零值泄漏。
4. 集成：单源 fetch、完整 refresh、失败、空响应和共享缓存命中均生成正确状态；Feed、AI 与内容索引不携带结构摘要。
5. API：Job 用户隔离不变，旧 Job 兼容，公开 JSON 不含测试注入值。
6. React：双层结构显示、默认折叠、缺失/截断状态、键盘访问和 390px 不溢出。

自动测试不得调用真实来源、Apify、AI、Worker 或 scheduler。完成前先跑定向测试，再运行 `python scripts/test_gate.py run --mode full`，最后重建本地 API + Worker，并通过桌面与 390px Playwright 验收。真实头像补齐只允许由用户下一次正常来源抓取触发，本实施不额外创建付费 Job。

## 9. 控制面影响

本实现会扩展 terminal Job 的公开结果结构并新增运行记录展示，因此实施时更新：

- `API_CONTRACT.md`：`response_schemas` 精确字段、上限和脱敏要求。
- `ARCHITECTURE_CONTRACT.md`：适配器结构摘要、Job 边界和媒体缓存更新所有权。
- `UI_CONTRACT.md`：运行记录双层结构视图与窄屏行为。
- `DECISION_LOG.md`：选择 Job 内有界摘要而非原始响应存储或独立历史表的理由。

不改变数据库 schema、部署拓扑、来源成本策略、AI 合同或 VPS Worker 状态。
