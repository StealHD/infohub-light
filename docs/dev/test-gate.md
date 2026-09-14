# 测试与控制面验证

本文件是测试选择、任务审查顺序、PR/main 与发布 Gate 的流程真源。`scripts/test_gate.py` 统一选择和执行测试；选择器的唯一映射是 `tests/test_impact_map.json`，不是控制面 `watch`。运行时构建、迁移、健康和回滚遵循[架构合同](../contracts/architecture/jobs-notifications-runtime-migrations.md#310-runtime--migration-boundary)。

## 任务验证流程

1. 改动前创建任务独享 snapshot（示例路径可替换）。snapshot schema 2 保存 `base_sha`，冻结单体按任务开始的版本比较；新文件/函数及既有例外的硬限制只由 `tests/code_size_policy.json` 定义，缩小冻结文件不修改策略。
2. 按逻辑切片运行直接受影响的 Pytest、Vitest 或 Playwright spec，先定位首个失败；不以全量抓取、AI 或真实推送代替测试。
3. 提交或最终 main 验证前主动审查任务范围 diff，修复所有已知或高置信缺陷，并复验直接受影响的 spec。不得把已知缺陷留给 CI、Docker 或 VPS 发现。
4. 运行一次 impacted `preflight`。完整 Gate 失败后先修复并复验失败 spec；同一任务的完整 Gate 最多重跑 5 次（不含首次执行），每次重跑前都必须修复已知问题并通过直接相关测试。

```bash
python scripts/test_gate.py snapshot --output /tmp/infohub-task-impact.json
python scripts/test_gate.py plan --snapshot /tmp/infohub-task-impact.json --json
python scripts/test_gate.py run --snapshot /tmp/infohub-task-impact.json --mode targeted
python scripts/test_gate.py preflight --snapshot /tmp/infohub-task-impact.json
```

`preflight --staged` 比较 HEAD，`preflight --base BASE --head HEAD` 验证提交范围。未知可执行代码、全局依赖和构建配置 fail closed 到无 Docker/Playwright 的完整代码域检查；`project-controls.json` 当前也在 full 映射中。不要为缩短本次任务而降低选择器覆盖。目标行数、复杂度和嵌套指标只报告，硬限制以上述代码策略为准。

控制文档字节上限由 `scripts/check_markdown_controls.py` 统一维护；不在 init-pro policy 复制预算或增加另一组限制。其静态检查继续通过既有 control Gate 执行。

## PR/main 开发检查

现有开发 CI 保持原状，发布不等待这些任务。新 push 不自动取消已启动的 Gate。

- PR 对受影响后端运行映射 Pytest，前端运行关联 Vitest 与必要静态检查；main 对受影响代码域运行完整检查。公共基础模块、真实依赖/构建改动及未知可执行路径保留保守扩大范围，文档-only revision 仅运行 control。
- 公共 control 在 CI 的 impact job 执行一次，后端、前端、E2E 和手动 smoke 依赖该 job 成功，再用 `run --skip-control` 执行自己的 scope。独立调用默认仍包含 control；`--skip-control` 不接受 all/control scope。命令已包含生产 build 时不再独立执行 TypeScript，因为 `npm run build` 包含 `tsc`；无 build 的选测保留类型检查。
- PR Linux UI 运行映射的 E2E spec；ActorOps、Workbench、Agent Workspace 和视觉快照等按现有映射选择。App Shell、设计系统、全局路由和未知 UI fail closed 到全部 E2E。只改 E2E spec/截图不触发完整 Vitest，仍检查 E2E 合同并验证浏览器场景。开始 Playwright 前的静态 E2E 合同拒绝硬编码 preview 端口、瞬态 inert 前计数断言和不确定视觉准备。
- 有 UI 影响的 main push 为最终 SHA 运行一次权威完整 Playwright Gate。main 的影响范围从最近已成功的、严格早于当前 HEAD 的第一父链 main Gate 起算，包含此前失败或取消后尚未验证的改动；GitHub 查询不可用或无可信基线时执行完整代码与 E2E 验证。CI planner 最多查询 100 个成功的 main push Gate，不新增持久验证缓存。
- 仅 main 且整个原始 Git diff 只改变 `pyproject.toml` 的项目版本及 `uv.lock` 中本项目 `horizon` 的版本、前后版本分别一致、TOML 其余内容及文件模式不变时，复用已成功基线的代码证据并只执行 control 与版本一致性验证。依赖、哈希、构建配置、其他文件或无可信证据均不走版本轻量路径；本地和 PR 仍按依赖文件映射保守验证。新的 main SHA 仍执行自己的 CI，作为开发集成反馈。

已有 `Release-Mode: fast` 的轻量 CI 兼容行为保留；它不是发布命令的要求，不需要为发布改写提交 trailer。UI skill 指导设计和编码，检查仍由开发流程负责。

## 发布

当前项目处于快速迭代阶段。普通 `release` 与 `release-fast` 共用一个发布入口：

```bash
./scripts/release_vps.sh release vX.Y.Z
```

发布只执行：核对干净的本地 main、origin/main 和版本 → 复用同 SHA 镜像或本地构建一次 linux/amd64 镜像 → 核对 API/Worker 入口与产物身份 → 上传 → 停 API/Worker、检查活跃任务并备份现有生产库 → 切换 → 版本/健康/React 静态资源检查 → 创建并推送 Tag。失败切换仍自动恢复旧程序。VPS 不编译项目；原有生产数据、运行配置和显式迁移边界沿用运行合同。

发布及准备阶段不运行 UI 合同检查、视觉快照、Axe、Playwright、Vitest、完整 Pytest、本地 preflight 或隔离 Docker smoke；不收集/核对测试回执，不等待 main CI 或 Tag CI。Tag workflow 只异步核对版本与 main 归属。用户要求发布已有代码时，直接走上述路径，不因 UI 审查补改产品界面。开发阶段已知问题按当前授权范围处理，不以发布任务为由扩大 UI 修改。

普通代码发布不做全库 integrity/FK 扫描，只在停服务后检查任务和备份；完整数据校验留给显式迁移或数据库恢复。磁盘按本次归档、镜像和原库备份加 512 MiB 余量检查，不再要求固定 8 GiB 或 85% 使用率。global 47 等结构迁移仍显式进行，禁止将测试库复制到生产。

## 显式快速发布

`release-fast vX.Y.Z` 是同一简化发布流程的兼容名称，不要求 `Release-Mode` trailer，也不要求先执行准备命令。可选的 `prepare-fast vX.Y.Z` 只提前构建、检查并缓存本地镜像归档，不联网查询生产或执行测试；没有 Gate/E2E 参数。发布自动复用匹配 SHA、版本、目标及校验和的缓存，否则重新构建。生产容器重启不使相同源码镜像失效。

`preflight` 和测试工具继续作为用户明确请求的开发/诊断入口保留，发布脚本不自动调用。发布代码本身修改时，用相关脚本测试验证命令顺序、失败中止、缓存与数据保护即可，不为流程修改启动 UI 用例或整项目验收。

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
