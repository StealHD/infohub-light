---
name: inteliscope-ui
description: Implement or review Inteliscope production Web UI under its UI Contract. When explicitly supplied or copied to another Web project, adapt to that project's stack and conventions, including new pages and projects. Covers interaction, responsive behavior, accessibility and component reuse; excludes backend-only work and Inteliscope's fixed-data HeroUI preview unless production UI rules are also affected.
---

# Inteliscope UI

## 确认项目与任务

- 先根据用户指定的目标工作区、适用的 `AGENTS.md`、项目清单与组件入口确认项目；不要根据此 skill 的名称或存放位置推断目标项目。
- **Inteliscope**：确认目标仓库的 UI Contract 与设计系统后，使用下文项目入口；现有合同是生产 UI 权威。
- **其他 Web 项目**：发现并遵循该项目已有规范、技术栈、组件库、样式参数和测试工具。不要套用下文 Inteliscope 的路径、HeroUI、视觉参数或命令；不能因缺少 Inteliscope 文件而判断项目不可用。
- **新项目或缺少规范**：保留用户指定的技术栈与视觉方向。未指定时按交互复杂度选择最小方案，简单静态页面不默认引入框架；只建立当前任务所需的组件、语义参数和状态，不强制生成完整设计系统或规范文件。
- 后端任务不启用 UI 工作流。Inteliscope 固定数据 HeroUI 预览仅在同时涉及生产 UI 规则时进入本项目工作流。

按用户意图区分工作方式：

- **评审或分析**：只读检查，给出问题位置、用户影响、依据与未验证项；不自动修复代码、更新快照或改写规范。
- **修改现有界面**：定位最近的同类组件及其调用与测试，优先复用角色；仅改变完成请求所需的区域。
- **新增页面**：先明确用户任务、首要信息、主操作及加载、空、失败等必要状态，再组合已有角色。局部换色或样式调整默认只作用于用户指定界面。

## 按需读取

遵守目标项目的必读入口与顺序。已有上下文仍然适用时不重复读取；长文件先定位目录、章节、规则标识或关键词，补齐相关上下文，避免默认扫描全部组件或无关路由。下文项目文件路径均相对于目标项目根目录。

**仅 Inteliscope 使用以下入口，按顺序读取：**

1. 适用的 `AGENTS.md`；按其读取要求和任务范围决定是否展开 `PLAN.md`。
2. `docs/contracts/ui/README.md`：权威关系与路由索引。
3. `docs/contracts/ui/interaction-constitution.md`：跨页面交互。
4. `docs/contracts/ui/component-parameters.md`：组件角色和数值归属。
5. 索引链接的目标路由合同，仅展开受影响界面的条款及适用例外。
6. `docs/contracts/ui/acceptance.md`：选择测试或宣告完成之前核对。

在 Inteliscope 中，随后检查最近的生产组件、对应测试、`frontend/src/design-system/index.ts` 及其相关实现、`frontend/scripts/check-ui-contract.mjs`。业务 UI 基础组件从设计系统边界导入，先选择现有角色再考虑新增模式。

## 实施与规则冲突

- 规则、组件实现和历史记录分别核对：代码现状是证据，不自动成为规范；明确已取代的记录不作为现役验收要求。
- 按目标项目已有的权威与取代关系消解冲突。若仍不能确定，说明当前规则的位置、实际行为、用户影响与建议；继续不依赖该决定的工作，仅对阻塞任务且无法推断的决定询问用户。
- 不静默改写规则或用更新快照掩盖冲突。已有明确授权与范围持续有效，无需重复确认；规则变更未获授权时不自行扩大任务。范围外问题仅报告。
- Inteliscope 可复用行为归 `frontend/src/design-system/**`；跨路由交互、组件数值、路由例外、验收和静态检查分别回到现有权威文件。静态规则须有正反例，不能用宽泛正则代替行为验证。引用规则标识或权威章节，不把合同复制到此 skill。
- 其他项目沿用自身的组件与规则归属；缺少共享模式时仅提取当前确有复用需求的部分，不顺带更换组件库或重构全站。

## 交互检查与验证

Inteliscope 以交互宪章的规则标识及 acceptance 为准，不在此重定义阈值。其他项目按实际任务检查以下行为，具体尺寸、时长、视口、样式及组件选择由目标项目决定：

- **异步操作**：即时反馈并防止同一操作重复提交；覆盖 idle、pending、成功和失败，避免非预期尺寸跳动。刷新已有内容时保留可读内容；取消或停止是独立动作，不被笼统的 pending 锁误禁用。
- **恢复与上下文**：失败保留可恢复输入，提供明确下一步；结果不明且可能重复产生副作用时先核对状态。局部更新保留逻辑节点、焦点、选区、滚动和展开意图，除非用户接受的操作必然移除对象或导航。
- **内容与输入方式**：长标题、URL、错误和标签在窄屏及放大时可读可操作；键盘、触屏、可访问名称与焦点回归符合组件语义。Reduced Motion 保留状态含义，业务正确性不只依赖动画结束事件。

根据变更选择已有验证工具：静态检查验证可机械判断的边界；组件测试验证状态与请求行为；浏览器验证真实几何、焦点、滚动、响应式和视觉结果。快照通过不证明可用性，静态检查通过不证明完整交互合规。

- **Inteliscope 生产 UI 实施**：遵循 acceptance 的顺序，运行最小相关 Vitest 或 Playwright spec，并在 `frontend` 目录运行 `npm run check:ui` 和 `npm run typecheck`。实施前建立任务 snapshot，审查任务差异后按仓库策略运行一次 impacted preflight；不重复执行已由门禁提供的相同检查。UI 合同变更还须遵循 `AGENTS.md` 的控制面验证要求。
- **其他项目**：从项目清单和测试配置选择适用命令，不预设 npm、Vitest 或 Playwright。工具缺失时完成仍可执行的检查并说明证据缺口，不擅自安装新测试框架。
- **评审交付**：分别标明已确认问题、待验证推断、已执行检查及未覆盖场景，不将只读抽查写成全量合规结论。
- **此 skill 的维护**：使用可用的 `skill-creator/scripts/quick_validate.py` 验证格式，并通过代表任务检查项目路由、只读边界和验证选择；格式校验不替代行为评估。仓库内修改仍遵循任务 snapshot、差异审查、impacted preflight 和工作记录要求。

## 外部参考与可移植边界

外部设计资料只作为证据，不能自动覆盖项目规范或用户指定方向。Inteliscope 的可选上游教材固定为 [UI UX Pro Max Skill，commit `40d8b6f`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/commit/40d8b6facf46677f86e8c0e5d4c6f77c137c9888)：仅在用户要求 UI 研究或合同存在实际缺口时查阅。不得将其目录、token、模板、断点、依赖或样式预设直接复制到 Inteliscope；上游更新仍需新的明确评审和决定。其他项目不强制使用该参考。

此 skill 保留在原项目目录。其他项目需显式提供或自行复制后使用；本工作流不安装全局 skill，也不以另一个 skill 已安装为日常 UI 工作的前提。
