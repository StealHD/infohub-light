# 多用户来源身份隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本文为拟实施设计，未修改代码或生产数据库。

**Goal:** 同一公开仓库、Feed 或账号被某用户保存为 private 来源后，不阻止其他用户建立自己的订阅；不暴露、接管或自动分享既有 private 来源。

**Architecture:** `source_key` 继续表示规范化采集目标，但唯一性按来源可见范围区分：private 在同一 workspace + owner 内唯一；public/workspace 在同一 workspace 的共享范围内唯一。所有身份查询显式携带目标 scope/owner，用户发现只返回其可见记录；来源 ID、配置、订阅和历史关联保持不变。

**Tech Stack:** SQLite migration、Python ServiceStore / SubscriptionMutationService、FastAPI / MCP、React 来源对话框与 Pytest/Vitest/Playwright。

**Spec:** 本文设计变更以用户手动创建失败为触发；修改 [Service catalog 合同](../../contracts/api/service-core.md) 中目前明确禁止跨用户 private key 碰撞的旧规则，并与 [分流修复 A](2026-09-12-openclaw-subscription-routing.md) 一起验收。API/存储契约变化必须有决策记录。

## Global Constraints

- 复用修复 A 的 Worktree、分支、base SHA 和 snapshot。本轮只做计划和本地复现。
- 生产只读证据：`github_release:openclaw/openclaw` 已有 private、enabled 来源，2026-08-11 创建，有一条有效订阅；2026-09-12 05:02:35 UTC 的 source/create conflict 操作者不是来源所有者。诊断不保存或展示两者账号标识。
- 当前唯一索引为 `idx_source_catalog_workspace_source_key(workspace_id, source_key)`；MCP private prepare 同样全 workspace 查 key，Web upsert 还要求 scope/type/owner 兼容。改 Agent 指引不足以解决本问题。
- 不修改历史来源 scope、owner、config、secret、ID，不移动订阅，不合并历史/健康/ActorOps Binding，不通过删除索引而放弃去重，不用随机后缀伪造 source_key。
- 迁移必须显式 preview、停 API/Worker、0600 备份、apply、完整性验证；本计划不授权这些生产动作。
- 新的身份查询和 schema 放独立模块；`service_store.py`、`subscription_mutation.py`、`server.py` 等冻结文件只替换/抽取，不能净增长。
- 上游限额与 ActorOps 授权不变；private 采集仍按用户隔离，共享采集不能读其他人的 private 数据。

## 行为决策

| 已有记录 | 当前用户请求 | 预期 |
| --- | --- | --- |
| 同一用户同一 private 目标 | 重复创建同一 private | 返回同一 ID；订阅幂等；不同配置的修改不能被“复用”静默覆盖 |
| 另一用户 private 目标 | 新建自己的 private 或管理员新建 shared | 创建独立 ID，原记录不变，不披露隐藏来源 |
| 可见 shared 目标 | 订阅现有目标 | 使用明确返回的 existing ID，仅写调用者订阅，不覆盖共享配置 |
| 同一共享身份重复 POST | 相同 scope/type 的管理员 upsert | 保留原有幂等；scope 转换必须走显式操作 |
| 本人 private 与 shared 同目标并存 | 解析/列举 | 均按可见规则处理；优先已订阅的精确来源，再本人 private，再 shared；不重复创建订阅 |
| 禁用来源 | 请求订阅 | 提示现有状态及有权限的启用路径；不因重试创建绕开禁用 |
| private 分享为 shared，已有 shared 同目标 | 分享请求 | 原子拒绝冲突，提示使用已有可见来源；不自动合并、转移历史或分享他人来源 |
| PATCH 改到本作用域内已占用目标 | 修改请求 | 继续 409 source_key_conflict，全部原记录不变 |

同一用户选择 private 与 shared 是不同来源身份；新建 shared 不自动发布其 private 行。原有管理员默认 public 行为保留，但 UI 必须如实呈现其作用域。Web 的“创建并订阅”不能先覆盖某个已有来源配置再悄悄称为复用。

## Task B1: 先补全失败复现与存储身份合同

**Files:** Create `tests/test_source_identity_isolation.py`、`tests/test_catalog_source_identity_api.py`；reuse `tests/api_service_test_support.py`；review `tests/test_service_store.py` 的并发/跨用户测试。

**Interfaces:** 输入实际 `source_key`、scope、actor；输出来源 ID、事务结果、可见性和原行保持不变的断言。

- [x] **1. 固化与截图一致的 REST 失败测试。** 临时 store 中用另一个 admin 创建 private `github_release:openclaw/openclaw`，以 owner 登录 POST `/api/catalog/sources`。请求如下；旧实现预期 409，修复后预期成功且为新的 source ID。

```python
payload = {
    "type": "github_release", "display_name": "OpenClaw Releases",
    "config": {"owner": "openclaw", "repo": "openclaw", "fetch_limit": 1},
    "enabled": True,
}
response = client.post("/api/catalog/sources", json=payload)
assert response.status_code == 200
created = response.json()["data"]
assert created["id"] != other_private_source_id
assert store.get_source(other_private_source_id) == original_source
```

- [x] **2. 参数化所有可创建 catalog 类型。** 使用 A 的规范化配置矩阵，覆盖两个 member 分别 private、admin/owner shared 与他人 private 并存；相同用户同 scope 并发只产生一行。保存来源、订阅、健康、ActorOps 和任务行的前后差异，只允许本次目标新增；不读真实数据。
- [x] **3. 运行 `python -m pytest -q tests/test_source_identity_isolation.py tests/test_catalog_source_identity_api.py`，先确认旧实现因全 workspace key 冲突失败。** 不把预期 409 的旧契约测试直接删除；实施后改为断言“创建独立身份且原 private 未被接管”，并保留本作用域碰撞测试。

## Task B2: 显式唯一索引迁移及查询入口

**Files:** Create `src/storage/source_identity_schema.py`、`src/storage/source_identity_store.py`、`scripts/migrate_source_identity_v46.py`、`tests/test_migrate_source_identity_v46.py`；modify `src/storage/service_store.py` 初始化和来源相关方法。

**Interfaces:** 当前 main 已有 global 45；该基线采用 global 46 `source_identity`。合入前若版本已占用，整组调整到下一可用编号，不能覆盖既有 migration。

- [x] **1. 编写 preview/apply 的幂等、半迁移、损坏 marker、并发和回滚测试。** 有效旧库 → preview 不修改字节；apply 后 source/subscription 等业务表数据不变；重复 apply 不重复写 marker；只删除已知旧唯一索引；未知索引/重复身份/缺失 private owner 阻断并提供安全计数，不修复数据。
- [x] **2. 新身份约束使用以下两个索引。** 新模块提供 `ready(conn) -> bool`、`apply_migration(conn) -> None` 和只读预检；校验 marker、精确索引列/谓词以及 private owner 非空约束。fresh store 直接建立正确形状；已有库不得由 initialize 自动删旧索引或应用迁移。

```sql
CREATE UNIQUE INDEX idx_source_catalog_private_identity
ON source_catalog(workspace_id, owner_user_id, source_key)
WHERE scope = 'private' AND source_key IS NOT NULL AND source_key != '';

CREATE UNIQUE INDEX idx_source_catalog_shared_identity
ON source_catalog(workspace_id, source_key)
WHERE scope IN ('public', 'workspace') AND source_key IS NOT NULL AND source_key != '';
```

- [x] **3. private owner 约束在 INSERT/UPDATE 触发器和 Service 校验中拒绝 NULL/空值。** 迁移前先检查历史不合格行；旧数据不自动归属任何用户。scope 合法性沿用现有约束。
- [x] **4. `ServiceStore.get_source_by_key` 改为显式身份 API，并由小模块实现 SQL。**

```python
def get_source_by_key(
    self, *, workspace_id: str, source_key: str,
    scope: str, owner_user_id: str | None = None,
) -> dict[str, Any] | None:
    if scope == "private":
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("private source owner is required")
        row = self.connect().execute(
            "SELECT * FROM source_catalog WHERE workspace_id=? "
            "AND source_key=? AND scope='private' AND owner_user_id=?",
            (workspace_id, source_key, owner_user_id),
        ).fetchone()
    elif scope in {"public", "workspace"}:
        row = self.connect().execute(
            "SELECT * FROM source_catalog WHERE workspace_id=? "
            "AND source_key=? AND scope IN ('public','workspace')",
            (workspace_id, source_key),
        ).fetchone()
    else:
        raise ValueError("source scope is invalid")
    return self._source(row)
```

不保留一个会随机返回不同 owner 行的缺省查询。独立 `get_visible_sources_by_key(user, source_key)` 只返回本人 private 与 shared（含 enabled 状态），供 discovery 选择；不要先读取他人行再投影。所有 SQL 参数化，不拼接身份值。
- [x] **5. 修正 create/upsert/update 和 fresh/existing 初始化。** 同身份幂等与 BEGIN IMMEDIATE 保留；PATCH/scope sharing 由新索引提供原子冲突保护。未迁移旧库对需要新身份规则的来源 mutation/prepare 返回稳定 `source_identity_migration_required`，不在冲突时降级旧全 workspace 查询；既有 Feed 读取继续工作。健康检查与发布预检必须能报告明确迁移状态。
- [x] **6. 迁移脚本沿用停服检测/备份约定，`integrity_check` 与 `foreign_key_check` 必须通过。** 部署旧镜像前先检查是否已存在跨身份重复 key；出现新身份数据后不可直接恢复旧索引，回滚必须恢复已校验的迁移前 backup 并通过旧 API/Worker 健康检查。测试不能只回滚空库。

## Task B3: REST / MCP / 解析与分享采用同一身份规则

**Files:** Modify `src/services/subscription_mutation.py`、`src/services/source_resolution.py`、`src/api/server.py`；focused new tests `tests/test_catalog_source_identity_api.py`、`tests/test_remote_mcp_subscription_identity.py`；update `tests/test_impact_map.json`。

**Interfaces:** consumes B2 的显式身份 API；existing 引用仍为 source ID，private plan 仍由 actor 自身决定 owner，不能接受用户传入 owner ID。

- [x] **1. 更新当前六个 `get_source_by_key` 调用点。** resolution `_candidate` 按可见目标选择；MCP private prepare 与 apply stale-check 只查当前 actor 的 private 身份；REST upsert 传入请求 scope/owner；API legacy import 明确 shared；API catalog create 的 managed-source precheck 使用与 upsert 完全相同身份。用 `rg -n 'get_source_by_key\(' src` 确认无旧签名残留。
- [x] **2. 审计绕过 helper 的全部 SQL。** `rg -n 'source_key' src/storage src/services src/api`，检查每个 `SELECT/UPDATE` 是否原先假设 workspace 内 key 唯一；不能只修改六个 Python 调用。来源健康、Schedule、Job、Binding、内容关系以 source ID 保留；任何按 canonical key 合并 private 内容的查询必须带原有用户隔离条件。
- [x] **3. 保留私有计划的确认/CAS。** 他人的同 key private 在 prepare/apply 之间新增不令本人的 proposal stale；本人同身份在中间新增仍返回冲突/stale，不静默消费为另一来源。existing plan 继续检查可见性和指纹，来源撤销/禁用/分享变化都复验。
- [x] **4. 分享碰撞以明确 409 原子返回。** 不自动订阅其他来源，不转移私人配置/secret/history，不删除来源。已有 shared 可见时 UI 可引导用户选择，但不能把隐藏 ID 放入错误响应。
- [x] **5. 验证跨用户正反例及全来源。** 对两人相同目标 prepare/apply、REST 双用户/双 scope、相同用户并发、disabled、share/PATCH 冲突、跨 actor resolution_ref、配额和无副作用全部断言。运行新 identity 测试和 A 的 routing 测试；在同一临时库先放入他人 private OpenClaw，再完成 Web 与 MCP 原始案例。

## Task B4: Web 恢复流程、文档与组合验收

**Files:** Modify `frontend/src/features/admin-heroui/HeroSubscriptionsPage.tsx`、`HeroSubscriptionDialogs.tsx`；new focused helper `frontend/src/features/admin-heroui/sourceCreationRecovery.ts` 与对应 Vitest；extend `frontend/e2e/production-admin.spec.ts` 的既有订阅覆盖；API/存储/架构合同、决策、manual、changelog、impact map 按本变更更新。

- [ ] **1. 实施 UI 前加载仓库 inteliscope-ui 技能及相关 UI 合同。** 沿用既有来源选择、notice、dialog 和按钮角色，不引入新视觉样式。冻结页面如无法保持大小则抽取受影响 helper/组件。
- [ ] **2. 增加重试与已有可见来源测试。** 服务端 source_key_conflict 不直接展示内部英语异常；`sourceCreationRecovery(error)` 只按安全错误码返回中文说明与可执行下一步。保留表单输入；可见共享来源引导 existing 订阅，本人已订阅提示状态；schema 未迁移提示管理员迁移；不安全/隐藏状态不能列出其他用户身份。
- [ ] **3. “创建并订阅”仅在两个步骤都成功后报成功。** 不将新建成功但订阅失败混为完成；沿用现有显式部分失败反馈，重试能选择已创建的本人来源，不再次覆盖配置。测试观察调用顺序和持久状态，不能只检查按钮文本。
- [ ] **4. 同步契约。** 明确将旧“跨用户 private key 碰撞必须 409”改为“按 owner 隔离创建，绝不接管”，记录决策与迁移依赖；分享到已有 shared 的碰撞仍受保护。无须声称公开 GitHub 仓库变成私人仓库，private 是本系统来源记录的权限范围。
- [ ] **5. 组合验收。** 在干净临时库及带他人 private 来源的迁移库分别跑 A+B 全来源矩阵；定向 Vitest/Playwright 验证截图表单流程；审查 diff、直接受影响测试通过后一次 impacted preflight。scope/storage 属于公共合同变更，按验证真源完成控制检查和 WORKLOG。
- [ ] **6. 交付分阶段证据。** 本地实现、显式迁移、服务端发布、目标 Gateway Skill 刷新、真实会话 prepare 和用户确认 apply 分别记录；当前本地实施任务不执行后五项，也不更改已有 private 来源来临时绕过缺陷。

## 计划审查结论

该问题由明确旧契约和唯一索引导致，属于数据身份规则修正；既有保护测试不是偶然失败。修复以保持隔离为前提允许独立身份，不能仅删除冲突校验。A 解决错误分流，B 解决实际数据冲突；只有组合验证通过，才能认为原始案例在代码层已修复。


执行状态（2026-09-12）：用户已授权本地实施，取代此前“仅计划”的当轮范围。实现见当前分支 diff；迁移与 Web 边界经独立审查后补充了事务回滚、同身份只创建不覆盖、disabled 无引用以及 POST can_subscribe 能力。最终代码域 Gate 证据将在完成后记录；生产迁移、发布、Gateway Skill 刷新和真实会话验收仍未执行。

本地实施验收（2026-09-12）已完成。所有已知失败已修复并定向复验；遵循用户减少重复测试要求，两次 preflight 中断后续跑未执行部分，保留原 failed 记录，不重跑已通过测试。后端分段覆盖完成；前端 924 项、三视口 6 项浏览器用例与构建通过。详细证据和未执行的生产环节见 WORKLOG 的 openclaw-subscription-routing-implementation-20260912。
