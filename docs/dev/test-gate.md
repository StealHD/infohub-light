# 测试与控制面验证

本文件是测试选择、任务审查顺序、PR/main 与发布 Gate 的流程真源。`scripts/test_gate.py` 统一选择和执行测试；选择器的唯一映射是 `tests/test_impact_map.json`，不是控制面 `watch`。运行时构建、迁移、健康和回滚遵循[架构合同](../contracts/architecture/jobs-notifications-runtime-migrations.md#310-runtime--migration-boundary)。

## 任务验证流程

1. 改动前创建任务独享 snapshot（示例路径可替换）。snapshot schema 2 保存 `base_sha`，冻结单体按任务开始的版本比较；新文件/函数及既有例外的硬限制只由 `tests/code_size_policy.json` 定义，缩小冻结文件不修改策略。
2. 按逻辑切片运行直接受影响的 Pytest、Vitest 或 Playwright spec，先定位首个失败；不以全量抓取、AI 或真实推送代替测试。
3. 提交、最终 main 验证或部署前主动审查任务范围 diff，修复所有已知或高置信缺陷，并复验直接受影响的 spec。不得把已知缺陷留给 CI、Docker 或 VPS 发现。
4. 运行一次 impacted `preflight`。完整 Gate 失败后先修复并复验失败 spec；同一任务的完整 Gate 最多重跑 5 次（不含首次执行），每次重跑前都必须修复已知问题并通过直接相关测试。

```bash
python scripts/test_gate.py snapshot --output /tmp/infohub-task-impact.json
python scripts/test_gate.py plan --snapshot /tmp/infohub-task-impact.json --json
python scripts/test_gate.py run --snapshot /tmp/infohub-task-impact.json --mode targeted
python scripts/test_gate.py preflight --snapshot /tmp/infohub-task-impact.json
```

`preflight --staged` 比较 HEAD，`preflight --base BASE --head HEAD` 验证提交范围。未知可执行代码、全局依赖和构建配置 fail closed 到无 Docker/Playwright 的完整代码域检查；`project-controls.json` 当前也在 full 映射中。不要为缩短本次任务而降低选择器覆盖。目标行数、复杂度和嵌套指标只报告，硬限制以上述代码策略为准。

控制文档字节上限由 `scripts/check_markdown_controls.py` 统一维护；不在 init-pro policy 复制预算或增加另一组限制。其静态检查继续通过既有 control Gate 执行。

## PR、main 与正式发布

- PR/main 对受影响的后端、前端代码域运行完整检查；全局依赖/构建改动覆盖两域。文档-only revision 仅运行 control。
- PR Linux UI 运行映射的 E2E spec；ActorOps、Workbench、Agent Workspace 和视觉快照等按现有映射选择。App Shell、设计系统、全局路由和未知 UI fail closed 到全部 E2E。开始 Playwright 前的静态 E2E 合同拒绝硬编码 preview 端口、瞬态 inert 前计数断言和不确定视觉准备。
- 有 UI 影响的 main push 为最终 SHA 运行一次权威完整 Playwright Gate。正式 VPS 发布复用精确 main SHA 的成功 Gate，绿灯后才创建并推送版本 Tag；Tag workflow 核验同一 main 结果，仅追加隔离 API Docker smoke。
- 标准 `scripts/release_vps.sh` 先做有界 impacted preflight，再复用 main 证据；本地流程不得重复 release Docker smoke 或完整 Playwright。release smoke 不得调用真实来源、付费 provider、AI、Worker、通知或退役 scheduler。

## 输出与失败定位

退出码：`0` 通过，`1` 测试失败，`2` 快照、映射或环境配置错误。完整日志和 `result.json` 写入忽略的 `.test-results/<run-id>/`，日志权限为 `0600`。stdout 成功摘要最多 2 KiB，失败摘要最多 8 KiB，并只提供首个失败和最多 80 行输出；摘要不足时只读取对应日志的必要区段。

## init-pro 0.4 控制面维护

使用已安装的 `init-pro 0.4.0` 增量维护 schema 3。`project-controls.json` 管主题归属与变更候选，显式 `project-controls-policy.json` 管扫描排除和索引检查；policy 不自动发现、不覆盖主题所有权，也不强制读取 PLAN。工具输出候选仍须遵守 [AGENTS 的读取路由](../../AGENTS.md#4-agent-默认读取范围与任务读取路由)。

```bash
INIT_PRO_HOME="${CODEX_HOME:-$HOME/.codex}/skills/init-pro"
python3 "$INIT_PRO_HOME/scripts/controlctl.py" --version
python3 "$INIT_PRO_HOME/scripts/controlctl.py" audit --project-root . --policy project-controls-policy.json --format markdown
python3 "$INIT_PRO_HOME/scripts/controlctl.py" context --project-root . --policy project-controls-policy.json --format markdown
python3 "$INIT_PRO_HOME/scripts/controlctl.py" context --project-root . --policy project-controls-policy.json --topic interface --format markdown
python3 "$INIT_PRO_HOME/scripts/controlctl.py" check --project-root . --policy project-controls-policy.json --format markdown
```

按改动选取候选时，给 `context` 或 `check` 增加 `--base BASE`，它覆盖 staged、unstaged 与非忽略新文件；增加 `--head HEAD` 则选择精确提交范围。结构校验始终针对当前工作区，不能将其描述为另一个 checkout 已通过。API/架构/UI 等目录候选只展开到索引；阶段、能力和决策仅在任务相关时读取。

`STRUCTURAL_PASS` 只表示确定性检查通过。Agent 仍须审查阶段、能力默认值、合同含义和验证/部署证据；文档有 diff 不等于完成语义审查。`watch` 命中不强制文档修改或新增决策。当前流程不启用 `--require-review`，不生成持久审查回执、不新增 CI 分发或 LLM 门禁。无 `--include-history` 时不展开历史正文；compact WORKLOG 的结构验证仍按技能检查其归档。

控制面修改完成后，除上述 policy check，还运行兼容结构检查、WORKLOG 和 JSON 校验：

```bash
python scripts/check_markdown_controls.py
python3 "$INIT_PRO_HOME/scripts/validate_project_controls.py" --project-root . --format markdown
python3 "$INIT_PRO_HOME/scripts/worklogctl.py" validate --project-root .
python3 -m json.tool project-controls.json
python3 -m json.tool project-controls-policy.json
python3 -m json.tool project-defaults.yaml
git diff --check
```

保持输出在 stdout，除非用户要求持久报告。WORKLOG 的一任务一记录、partial/finalize 与证据更新规则由 [AGENTS](../../AGENTS.md#6-worklog-rule) 维护。
