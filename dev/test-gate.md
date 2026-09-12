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

## PR、main 与正式发布

下列 main/Tag 规则默认用于标准发布；显式快速模式见下一节。新 push 不自动取消已启动的 Gate，避免快速提交中断标准验证。

- PR 对受影响后端运行映射 Pytest，前端运行关联 Vitest 与必要静态检查；main 对受影响代码域运行完整检查。公共基础模块、真实依赖/构建改动及未知可执行路径保留保守扩大范围，文档-only revision 仅运行 control。
- 公共 control 在 CI 的 impact job 执行一次，后端、前端、E2E 和手动 smoke 依赖该 job 成功，再用 `run --skip-control` 执行自己的 scope。独立调用默认仍包含 control；`--skip-control` 不接受 all/control scope。命令已包含生产 build 时不再独立执行 TypeScript，因为 `npm run build` 包含 `tsc`；无 build 的选测保留类型检查。
- PR Linux UI 运行映射的 E2E spec；ActorOps、Workbench、Agent Workspace 和视觉快照等按现有映射选择。App Shell、设计系统、全局路由和未知 UI fail closed 到全部 E2E。只改 E2E spec/截图不触发完整 Vitest，仍检查 E2E 合同并验证浏览器场景。开始 Playwright 前的静态 E2E 合同拒绝硬编码 preview 端口、瞬态 inert 前计数断言和不确定视觉准备。
- 有 UI 影响的 main push 为最终 SHA 运行一次权威完整 Playwright Gate。main 的影响范围从最近已成功的、严格早于当前 HEAD 的第一父链 main Gate 起算，包含此前失败或取消后尚未验证的改动；GitHub 查询不可用或无可信基线时执行完整代码与 E2E 验证。CI planner 最多查询 100 个成功的 main push Gate，不新增持久验证缓存。
- 仅 main 且整个原始 Git diff 只改变 `pyproject.toml` 的项目版本及 `uv.lock` 中本项目 `horizon` 的版本、前后版本分别一致、TOML 其余内容及文件模式不变时，复用已成功基线的代码证据并只执行 control 与版本一致性验证。依赖、哈希、构建配置、其他文件或无可信证据均不走版本轻量路径；本地和 PR 仍按依赖文件映射保守验证。新的 main SHA 仍须完成自己的 CI，之后才能创建 Tag。
- 标准 `scripts/release_vps.sh release` 只执行发布身份、迁移、容量等条件检查，不自动运行本地代码 preflight；复用精确 main SHA 的成功 Gate，绿灯后才创建并推送版本 Tag。显式 `preflight` 是可选诊断，继续执行本地 impacted preflight。Tag workflow 核验同一 main 结果后跳过重复 control，仅追加隔离 API Docker smoke。release smoke 不得调用真实来源、付费 provider、AI、Worker、通知或退役 scheduler。

## 显式快速发布

标准 `release` 保持完整门禁和 Tag smoke。最终 main 提交末尾只有一个 `Release-Mode: fast` trailer 时，main 仅运行公共 control、版本一致性和改动脚本语法检查；缺省或 `standard` 走标准路径，重复、位置错误或未知值报错。PR 保持选测，手动 workflow dispatch 执行完整代码与 E2E；自动轻量绿灯不能充当完整验证基线，后续标准 Gate 累计期间全部 fast 改动。标准、快速入口均核验模式，不自动切换或改写已推送历史。

先确定版本与最终代码，在本地 Gate 中取得通过结果，再从干净本地 main 运行 `prepare-fast vX.Y.Z --gate-result PATH [--e2e-result PATH]`。允许准备时尚未推送。Gate 结果包含版本化输入指纹、命令范围和 Python/Node/系统环境；准备阶段按实际运行的 API/Worker 一致 revision 计算完整待发布差异，逐项核对覆盖。局部分支结果、失败、输入变化、环境变化、旧格式和缺少必要 E2E 均拒绝；未知生产基线要求完整代码及完整 E2E。普通 UI 按映射选测，全局/未知影响扩大，不增加 ARM/AMD64 双平台全套测试。只有非可执行的普通 Markdown 变化可复用业务结果，准备阶段重新执行轻量校验；版本及锁文件变化仍须最终代码验证。

准备只读取生产 revision，不上传或切换：本地构建一次正式 `linux/amd64` 镜像，保留原有 API/Worker 入口检查，并对同一个不可变 image ID 做隔离 API smoke。测试网络禁止外部访问，数据/日志/凭据和容器独立，不启动 Worker 或真实来源/AI/通知。准备清单、测试引用、源码/镜像包和校验和存于私有 `.test-results/fast-release/<SHA>/`。通过产物保留供复用，过期产物在显式重新准备时移到同级 previous 目录；准备失败清理本次临时产物和容器。

推送该 main 提交后执行 `release-fast vX.Y.Z`。此阶段不构建、不补测：校验清单、源码/版本、镜像、归档、目标与运行基线，上传后复核，等精确 main 轻量绿灯，再创建同样带 `Release-Mode: fast` 的附注 Tag。Tag 核验版本、main 归属和模式一致，快速 Tag 不运行 Docker smoke。后续共用标准容量、迁移阻断、备份、健康与回滚。任何证据不足均输出需补跑的本地命令并退出，不以快速模式绕过已知缺陷。构建与 smoke 前移只缩短 release 阶段；评估总收益须合计本地准备、发布和 GitHub 任务耗时。

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
