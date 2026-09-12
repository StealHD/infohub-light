# OpenClaw 全来源订阅分流修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 计划创建时仅新建分支；用户随后已授权在本 Worktree 实施，生产操作不在本轮范围内。

**Goal:** 让 OpenClaw 对全部已支持的来源走正确订阅路径；误调用通用解析器时能够恢复，不再把“没有解析适配器”报告成“管理员必须接通 Web”。

**Architecture:** 保留现有 registry 配置校验、来源复用、proposal 和 apply 事务。以小型能力模块明确通用解析支持范围，分开表达“直接配置可创建”“需要身份解析”“只能订阅预配置来源”；同步 MCP 工具描述、Skill 和 HTTP 回归，不新增平台解析器。

**Tech Stack:** Python / FastAPI / FastMCP / Pytest，OpenClaw Markdown Skill，React 产品手册与更新记录。

**Spec:** 本计划的“范围与验收矩阵”定义本次缺陷修复需求；现行约束来自 [Remote MCP 合同](../../contracts/api/remote-mcp.md)、[模块边界](../../contracts/architecture/openclaw-module-boundaries.md) 和 [验证流程](../../dev/test-gate.md)。实现时只修改这些合同中受本次行为变更影响的内容。

**接续修正（用户补充手动添加截图）：** 本计划是修复 A（Agent 分流）；还必须完成 [修复 B：多用户来源身份隔离](2026-09-12-source-identity-isolation.md)。生产同一仓库已有另一账号的 private 来源，当前工作区唯一键会使 Web 和 MCP 正确创建路径继续失败。A 独立通过不能声称原始订阅问题已解决；建议顺序为 B 的身份/迁移设计与实现 → A → 两组整体验证，最后再安排明确授权的生产迁移和发布。

## Global Constraints

- 起点：本地 `main` 的 `2df85c1a56fcee98b85efc9197353d5b760eb132`；分支 `codex/openclaw-subscription-routing`。
- Worktree：`/Users/stealmac/Documents/Inteliscope/infohub-light/.worktrees/openclaw-subscription-routing`。不带入主工作区其他任务的修改。
- snapshot：`/tmp/openclaw-subscription-routing-impact.json`；实施前若已有新的代码修改或 snapshot 丢失，重新建立明确的任务基线并记录差异。
- 现有四组定向测试在该分支起点通过：61 passed；这仅是旧实现基线，不是本修复验收。
- `prepare → preview → exact confirmation → apply` 不变；prepare 可写密封 proposal，不得写业务订阅。不能把“prepare 不改订阅”写成“prepare 不写任何数据”。
- 不扩展 delegation scope、工具 allowlist、租户可见性、URL 网络权限、来源启用策略或付费权限。
- 不进行生产订阅写入、真实平台抓取、模型调用、Actor Run、通知、迁移或部署。上线和真实会话验收是后续独立步骤。
- `src/services/source_type_registry.py`、`src/services/subscription_mutation.py` 等冻结文件相对任务基线不得增长；新增逻辑放小模块，不放宽 `tests/code_size_policy.json`。
- 每个切片先失败测试、再实现、再定向验证；收尾先审查 diff，再一次 impacted preflight。若完整 gate 失败，先复验失败 spec；遵循本会话更严格的完整 gate 最多再跑一次限制。

## 已验证根因与范围

生产 `a8651e6bb2ab` 和本地 main 的 `SourceResolutionService` 默认只注册 `youtube`。对其他已知类型，`adapter is None` 直接返回 `web_setup_required`，此时没有发起上游请求。与此同时，11 类非 YouTube 的 guide 明确返回 `self_service=true`、`requires_web_setup=false`。这种互相矛盾的返回足以让 Agent 错误停止。

在临时数据库内，12 类自助来源的 private prepare/apply 全部通过；通用 Apify 被正确拒绝新建。生产仅复现解析状态，不能据此声称每类真实平台抓取或 OpenClaw 会话已成功。

### 范围与验收矩阵

| 类型 | 主路径 / 必要公开参数 | 误调用通用解析器后的预期 |
| --- | --- | --- |
| `rss`, `website` | 已知公开 RSS/Atom `url` → private prepare；网站首页不等于 Feed | `configuration_required` → guide → 使用已提供字段，缺少时只问缺项 |
| `github` | `repository=owner/repo` → private prepare | 同上；必须覆盖 `openclaw/openclaw` 原始案例 |
| `github_user` | `username` → private prepare | 同上 |
| `reddit` | `subreddit` → private prepare | 同上 |
| `reddit_user` | `username` → private prepare | 同上 |
| `telegram` | `channel` → private prepare | 同上 |
| `hackernews` | 默认 `config={}` → private prepare | 同上；不得索要不存在的必要字段 |
| `bilibili` | 显式主页 UID 或 `search_bilibili_users` 唯一命中 → 受控 config → prepare | 同上；按 B 站专用流程，不使用通用解析器 |
| `twitter`, `instagram` | 明确平台及 `handle` → private prepare | 同上；按实际 preview/apply 结果说明启用或待核验，不启动 Actor |
| `youtube` | 官方 locator / 有界候选 → `resolve_source` → `resolution_ref` → prepare | 保留既有解析语义；上游失败不能降级成未经验证的 private 输入 |
| `apify` | `list_available_sources` 返回的可见 source ID → existing prepare | 保留 `web_setup_required`，没有来源时才引导 Web 配置 |

所有类型先检查当前订阅和可复用来源；列表为空只表示没有可复用对象，不证明类型不支持。保留不安全 catalog `public_target="web_setup_required"` 的脱敏占位，它与 resolve 顶层 status 不同，不得批量替换。A 实施期间保留旧身份规则；合并 B 后，隐藏的他人 private 来源不再占用调用者的创建身份，也不能被引用或披露。

## Task 1: 分离解析能力与订阅配置状态

**Files:**
- Create: `src/services/source_resolution_capabilities.py`，无 I/O、无 registry 反向依赖的能力投影。
- Modify: `src/services/source_type_registry.py` 的 `AgentSourceTypeDefinition.guide_summary/guide_detail`，抽走现有 YouTube 能力块以满足冻结限制。
- Modify: `src/services/source_resolution.py` 的无 adapter 分支。
- Create: `tests/test_source_resolution_routing.py`。
- Test: `tests/test_source_setup_guidance.py`、`tests/test_source_resolution.py`。

**Interfaces:**
- Consumes: registry 校验后的 canonical `source_type`、guide 的 `self_service` 与 `resolution.supported`。
- Produces: `source_resolution_capability(source_type: str) -> dict[str, Any]`。YouTube 保留现有 `supported/strategy/official_hosts/locator_kinds/max_candidates`；其他已知类型显式返回 `{"supported": False}`。guide 列表和详情都暴露该能力。
- Produces: 新增 resolve 顶层状态 `configuration_required`；保留所有旧字段及旧状态含义。唯一语义修正是这 11 类不再返回 `web_setup_required`。

- [x] **1. 先添加覆盖全部 11 类的失败测试。** 使用现有 Python 风格补齐 imports，测试的完整主体如下；`None` store 与 socket guard 证明该分支不依赖数据库或网络。

```python
import asyncio
import socket

import pytest

from src.services.source_resolution import SourceResolutionService
from src.services.source_type_registry import get_source_setup_guide

DIRECT_TYPES = (
    "rss", "website", "github", "github_user", "reddit", "reddit_user",
    "telegram", "hackernews", "bilibili", "twitter", "instagram",
)

@pytest.mark.parametrize("source_type", DIRECT_TYPES)
def test_wrong_resolver_routes_back_to_configuration(source_type, monkeypatch):
    def deny_connect(*args, **kwargs):
        pytest.fail("unsupported resolver must not connect")
    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    result = asyncio.run(SourceResolutionService(None).resolve(
        actor=None, source_type=source_type, input_value="openclaw/openclaw",
    ))
    assert result["status"] == "configuration_required"
    assert result["reason_code"] == "resolver_not_supported"
    assert result["next_step"] == {
        "tool": "get_source_setup_guide",
        "arguments": {"source_type": source_type},
    }
    assert result["candidates"] == [] and result["returned"] == 0
    assert "resolution_ref" not in result

@pytest.mark.parametrize("source_type", DIRECT_TYPES)
def test_direct_guide_has_explicit_resolution_capability(source_type):
    detail = get_source_setup_guide(source_type)["source_type"]
    summary = next(x for x in get_source_setup_guide()["source_types"]
                   if x["type"] == source_type)
    assert detail["resolution"] == summary["resolution"] == {"supported": False}
    assert detail["self_service"] and not detail["requires_web_setup"]
```

- [x] **2. 确认失败原因正确。** 运行 `python -m pytest -q tests/test_source_resolution_routing.py`，预期旧状态与缺少 `resolution` 导致断言失败，而非 import/环境错误。
- [x] **3. 实现能力投影及最小分支修复。** 新模块将原有 YouTube 字典移动为私有常量，函数使用 `deepcopy` 返回独立对象，其他类型返回 `{"supported": False}`。由 registry 原有 canonical 校验拒绝未知类型，不让 helper 独立承担类型合法性校验。删除 registry 的原有 YouTube if 块，在 guide_summary 添加能力字段，guide_detail 沿用 summary。resolver 无 adapter 分支使用：

```python
guide = get_source_setup_guide(public_type)["source_type"]
if guide["resolution"]["supported"]:
    return self._result("unavailable", public_type)
if guide["self_service"]:
    return self._result("configuration_required", public_type) | {
        "reason_code": "resolver_not_supported",
        "next_step": {
            "tool": "get_source_setup_guide",
            "arguments": {"source_type": public_type},
        },
        "message": (
            "This type supports direct subscription configuration. "
            "Use the setup guide and the user's supplied fields to prepare "
            "the subscription; no Web setup is required for supported public inputs."
        ),
    }
return self._result("web_setup_required", public_type)
```

- [x] **4. 补齐边界测试并通过。** 同文件测试：`apify` 仍返回 Web；`github_release` 等已有 alias 归一后走正确状态；未知类型仍 invalid；YouTube 名称仍 discovery_required；移除已宣告支持的 adapter 后为 unavailable；危险 input 不反射到结果、不触网、不创建 ref；返回 guide 被调用方修改后不影响下次结果。保留并运行现有 YouTube 的 resolved/ambiguous/not_found/unavailable、SSRF 和引用绑定测试。
- [x] **5. 定向验证和审查。** 运行 `python -m pytest -q tests/test_source_resolution_routing.py tests/test_source_setup_guidance.py tests/test_source_resolution.py`，检查默认注册 adapter 类型集合与 guide 宣告支持集合一致。记录 `_result` 旧字段不变和 registry 净行数不增长的证据。

## Task 2: MCP 与 Skill 提供一致的下一步

**Files:**
- Modify: `src/mcp/remote_read_tools.py`（resolve、guide、list 的工具描述），`src/mcp/remote_subscription_tools.py`（prepare 描述）。
- Modify: `integrations/openclaw/inteliscope/SKILL.md`、`references/workflows.md`、`references/tool-contract.md`、`README.md`。
- Test: `tests/test_openclaw_skill.py`、`tests/test_remote_mcp_subscription_http.py`；新增参数化流程测试留在 Task 3 的独立文件，避免冻结测试文件增长。

**Interfaces:**
- Consumes: Task 1 的 `resolution.supported`、`configuration_required` 与 `next_step`。
- Produces: 不依赖用户换一种说法的明确分流；工具名、source union、权限和确认流程不变。

- [x] **1. 在 Task 3 新 HTTP 测试文件中先断言 `tools/list` 的真实工具描述包含 `configuration_required` 与 `get_source_setup_guide`，并明确只有已声明支持的类型调用 resolver。运行该单测看到失败；不能只检查源码文本。**
- [x] **2. 修改工具描述，直接使用以下含义的文案。**

```text
resolve_source: Resolve identities only when get_source_setup_guide reports
resolution.supported=true (currently YouTube). configuration_required means
direct subscription setup is supported: follow next_step and prepare with
the user's supplied public fields. It does not mean a service outage.

prepare_create_subscription: Known public inputs for self-service types can
use mode=private directly after consulting the setup guide. A resolution_ref
is required only when using mode=resolved; it is not a universal prerequisite.

list_available_sources: Empty results mean no matching reusable visible
enabled sources. They do not prohibit creating a self-service private source.
```

- [x] **3. 重写 Skill 的订阅总流程及所有引用文档。** 第一层按 guide 分流：YouTube 解析；B 站专用搜索；其余 self-service 根据 required_fields 准备 private；Apify 只能 existing。`configuration_required` 后不反复重试 resolver，也不重复索取已知字段。对旧服务器误返 Web，先以 guide 识别“通用 resolver 缺失”，只在明确 public/self-service 输入时走已有 prepare；不能将 prepare 真正返回的 `source_requires_web_setup` 当作可忽略错误。
- [x] **4. 增加可直接使用的 GitHub 与 HN 请求示例。**

```json
{"source":{"mode":"private","type":"github","display_name":"OpenClaw Releases","config":{"repository":"openclaw/openclaw"}}}
```

```json
{"source":{"mode":"private","type":"hackernews","display_name":"Hacker News","config":{}}}
```

- [x] **5. 收口相邻文案矛盾。** 网站仅指公开 Feed，不承诺发现任意网站 RSS；B 站不要求用户提供内部 RSSHub 地址。X/Instagram 按现行 ActorOps preview/apply 输出描述已启用或 pending，保留当前自动本地证据检查，不能把本修复扩展成 ActorOps 策略变更。明确 prepare 写 proposal、apply 才写业务对象。
- [x] **6. 验证 Skill 和运行时描述。** 运行 `python -m pytest -q tests/test_openclaw_skill.py tests/test_remote_mcp_subscription_routing_http.py`。静态文案通过不等于真实 Agent 行为通过，实际会话证据另见 Task 4。

## Task 3: 全来源复现、恢复及权限回归

**Files:**
- Create: `tests/remote_mcp_subscription_routing_cases.py`（唯一测试参数矩阵）。
- Create: `tests/test_remote_mcp_subscription_routing.py`（临时数据库 prepare/apply）。
- Create: `tests/test_remote_mcp_subscription_routing_http.py`（真实 MCP 协议测试客户端）。
- Reuse: `tests/remote_mcp_subscription_service_test_support.py`、`tests/remote_mcp_subscription_http_test_support.py`。
- Modify: `tests/test_impact_map.json`，将新源文件与新测试映射至已有 source/MCP 后端域，保留未知文件 fail-closed。

**Interfaces:**
- Consumes: 现有 `context` fixture、`_actor(context, "member")`、HTTP helper `_app` 与客户端约定，Task 1/2 协议。
- Produces: 13 类及已存在 alias 的行为矩阵；错路由和正常路径都可验证；不靠模型或生产写入执行测试。

- [x] **1. 建立测试参数矩阵。** `CREATE_CASES` 使用以下完整公开配置，按类型独立 fixture 避免配额与重复来源互相干扰。

```python
CREATE_CASES = {
    "rss": {"url": "https://example.com/feed.xml"},
    "website": {"url": "https://example.com/feed.xml"},
    "github": {"repository": "openclaw/openclaw"},
    "github_user": {"username": "openai"},
    "reddit": {"subreddit": "LocalLLaMA"},
    "reddit_user": {"username": "spez"},
    "telegram": {"channel": "durov"},
    "hackernews": {},
    "bilibili": {"site": "bilibili", "route_key": "user_video",
                 "params": {"uid": "39627524"}},
    "twitter": {"handle": "openai"},
    "instagram": {"handle": "instagram"},
    "youtube": {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"},
}
```

- [x] **2. 先写再运行错误分流后的恢复测试。** 核心测试主体如下，module 从已有 support 引入 `context` fixture 和 `_actor`。测试是确定性编排合同验证，不冒充 LLM 自主选择工具。

```python
@pytest.mark.parametrize("source_type", [t for t in CREATE_CASES if t != "youtube"])
def test_resolver_fallback_can_prepare_and_apply(context, source_type):
    service = context["service"]
    actor = _actor(context, "member")
    response = asyncio.run(service.resolve_source(
        actor=actor, source_type=source_type, input_value="audit public target",
    ))
    assert response["status"] == "configuration_required"
    prepared = service.prepare_create_subscription(
        actor=actor,
        source={"mode": "private", "type": source_type,
                "display_name": "Audit " + source_type,
                "config": CREATE_CASES[source_type]},
        subscription={}, schedule=None,
    )
    assert context["store"].list_user_subscriptions(actor.user_id) == []
    applied = service.apply_subscription_change(
        actor=actor, proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    assert applied["result"]["subscription_id"]
    assert len(context["store"].list_user_subscriptions(actor.user_id)) == 1
    assert context["store"].connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == 0
```

- [x] **3. 扩展端到端断言。** 对 12 类均测正常 private prepare/apply；YouTube 另复用 fake verified adapter 覆盖 resolved ref → prepare/apply，确保 Skill 的正常路径已验证。Apify 先创建可见测试 catalog 再 existing apply，private create 必须 source_requires_web_setup。B 站名称无唯一命中不得准备；X/Instagram 裸 handle 无平台仍需澄清，无证明 fixture 保持 pending、不新增 Attempt。补测已有订阅避免重复、可见未订阅来源 existing 复用、隐藏/禁用来源不能被选择；不改变既有列表过滤合同。
- [x] **4. 通过 HTTP 工具入口复现。** 使用现有 MCP `ClientSession` 测试支架，参数化验证 guide → 错误 resolver → configuration_required → prepare → 未确认零订阅 → exact-confirmed apply；执行环境为临时 app/store。读取 `tools/list` 真正返回的描述，不模拟 server 的核心返回。所有网络仅连接测试 ASGI app，上游使用显式 fake/deny。
- [x] **5. 保护权限与负向路径。** reads-only delegation、写开关关闭、吊销身份仍在 prepare/apply 阻断；说明具体权限状态，不能将它们映射为 Web setup 缺失。confirmation_mismatch、过期/ref 跨 actor 不写业务，不额外创建或消费 proposal。响应和新增日志不含原始 input、config、URL、令牌或确认短语。
- [x] **6. 定向验证。** 运行新路由 service/HTTP 两文件以及 `tests/test_remote_mcp_subscription_http.py`、`tests/test_openclaw_all_source_subscriptions.py`、`tests/test_source_resolution.py`。若修改超出分流所需，先缩小 diff，不能顺手改 scraper 或 ActorOps 激活策略。

## Task 4: 合同、验收证据和上线接续

**Files:**
- Modify: `docs/contracts/api/remote-mcp.md`，记录新增状态及 guide 能力字段，保留安全 public_target 占位含义。
- Modify: `docs/decisions/README.md` 与索引指向的当前记录桶；按实际下一编号记录状态语义修正及兼容理由，不在本计划预占决策编号。
- Modify: `frontend/src/features/manual/manualContent.ts`、`frontend/src/features/changelog/changelogEntries.ts`，只更新受影响操作说明与用户可见修复记录。
- Update through tool: `WORKLOG.md`；执行修复时用该实施任务自身的一条记录，不能把本轮计划记录改写为代码已完成。
- Inspect only: `scripts/openclaw_setup_skill.py`、`scripts/openclaw_setup_workflow.py`，确认既有安装核对方法。

**Interfaces:**
- Consumes: Task 1–3 实现及测试证据。
- Produces: 可审查修复分支、明确的本地验收结论与尚待上线/真实会话验收项。

- [ ] **1. 同步用户可见合同。** 描述 configuration_required 表示“进入公开配置流程”，不代表已验证目标存在；模型不能把 hint 当成目标 ref 或用户授权。写明这次修复覆盖 11 类误路由，不宣称平台采集全可用。`project-defaults.yaml` 当前只声明解析开关/上限；无配置变化则不修改它，也不改根 PLAN 的全局阶段。
- [ ] **2. 审查最终任务 diff 并验证映射。** 运行 `git diff --check` 和 `python scripts/test_gate.py plan --snapshot /tmp/openclaw-subscription-routing-impact.json --json`；检查新文件已被纳入，冻结文件未增长，没有来源配置、订阅数据或秘密误入 diff。文档内状态清单和 HTTP 返回一致。
- [ ] **3. 运行一次 impacted preflight 与控制检查。** 使用 Worktree 的已配置 Python 环境执行 `python scripts/test_gate.py preflight --snapshot /tmp/openclaw-subscription-routing-impact.json`。API/决策合同变更按 `docs/dev/test-gate.md` 运行 Markdown、init-pro policy/结构、worklog、JSON 检查；仅失败项先定向修复，不以 Docker 或 VPS 代替本地检查。
- [ ] **4. 明确当前连接能力。** 后续上线前只读核对目标 OpenClaw 实际启用的 Skill 内容、`tools/list` 描述和 prepare/apply 可见性，以及 delegation 写权限。个人托管 Agent 合同默认仅 13 个只读工具，不能凭后端支持就承诺该连接可写，也不能自动提权。本轮未检查用户截图对应具体会话的安装路径或写工具权限。
- [ ] **5. 记录升级与运行验收清单。** 后续获授权发布时，同时同步服务端版本和目标 Gateway 的 bundled Skill；已有 `skill_tree_matches` 可校验安装内容，先按目标拓扑核对再使用部署/安装入口，不能盲跑本地 setup 脚本重启生产 Gateway。重新连接会话并核对工具描述已刷新；授权的真实会话使用“订阅 OpenClaw 的 GitHub Release”验收至 preview，覆盖一个 RSS、HN 默认配置和 B 站分流。真实模型调用及最终 apply 分别遵循当次授权/确认；未经这些验收，只能报告“本地合同与受控流程通过”。
- [ ] **6. 交付修复证据。** 输出实际通过的用例、13 类结果矩阵、未验证的运行环节和关键文件。本轮交付本地实现与验证，不自动提交、合并、打 tag 或部署。

## 计划自审

- 覆盖 13 类来源与 11 类共同误路由；不以新增 11 个解析器掩盖原有配置能力。
- 新状态、能力字段、下一步结构、修改位置、参数矩阵和测试命令已明确；YouTube 和 Apify 的不同限制保留。
- 安全占位 `public_target`、业务确认、写权限、网络边界、ActorOps 当前行为都有独立验收点。
- 运行 Skill/工具描述可能不同步、连接可能只读，纳入运行验收，不当作已查明的生产事实。
- 分支准备与旧测试通过不是修复完成；实施、上线、真实会话三个阶段分别保留证据。


执行状态（2026-09-12）：用户已授权本地实施，取代此前“仅计划”的当轮范围。实现见当前分支 diff；迁移与 Web 边界经独立审查后补充了事务回滚、同身份只创建不覆盖、disabled 无引用以及 POST can_subscribe 能力。最终代码域 Gate 证据将在完成后记录；生产迁移、发布、Gateway Skill 刷新和真实会话验收仍未执行。

本地实施验收（2026-09-12）已完成。所有已知失败已修复并定向复验；遵循用户减少重复测试要求，两次 preflight 中断后续跑未执行部分，保留原 failed 记录，不重跑已通过测试。后端分段覆盖完成；前端 924 项、三视口 6 项浏览器用例与构建通过。详细证据和未执行的生产环节见 WORKLOG 的 openclaw-subscription-routing-implementation-20260912。
