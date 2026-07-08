# Inteliscope InfoHub Light 实施计划

## 1. 计划目的
本文件定义当前阶段、实施顺序和默认验证策略。后续 agent 应以本文件作为开发入口之一，但不得用它覆盖更细的 API、架构、上下文和决策合同。

## 2. 当前阶段状态
结论：当前阶段是私人信息 Hub 的阅读筛选稳定化与长期归档分析准备。

已完成：

1. Light runtime 方向：默认只启动 Web，避免误启 scheduler。
2. No-AI / personal-only 成本护栏。
3. Hub taxonomy 基础：`channel/topics/signal_strength/signal_type/entities`，并保留 `category/tags` 兼容。
4. 静态阅读 UI 的频道优先筛选。
5. `ArticleStore` 对 Hub taxonomy 字段的归档落库。
6. init-pro 控制面初始化。

当前仍需推进：

1. 用真实来源验证频道、主题和信号字段的分类质量。
2. 建立分类质量巡检：`其他` 占比、空 topics、弱信号占比、实体缺失率。
3. 建立归档分析第一版：按 channel/topic/entity 聚合趋势。
4. 收敛配置页面中来源、主题、个人标签和成本功能的交互边界。
5. 清理或归档过期计划，保持唯一真源。

## 3. Agent 开工前默认读取
默认先读：

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. 当前任务直接相关代码
5. 当前任务直接相关测试

按需再读：

1. 架构任务：`ARCHITECTURE_CONTRACT.md`
2. 决策核对：`DECISION_LOG.md`
3. 上下文策略任务：`CONTEXT_READ_RULES.md`
4. 真实数据验证：`docs/dev/hub-taxonomy-real-run.md`

默认不读：

1. `data/site/history-data.json`
2. `data/site/history/**`
3. `data/horizon.db`
4. `logs/**`
5. `.env*`
6. `.venv/**`
7. 不相关 Markdown

## 4. 当前实施范围
本阶段继续做：

1. 私人阅读筛选体验。
2. Hub taxonomy 与 legacy alias 的兼容迁移。
3. 来源配置、抓取、AI 分析、静态 UI、SQLite 归档之间的稳定字段合同。
4. 低成本验证路径和明确的 capability / degrade 表达。
5. 面向长期归档分析的最小可查询字段。

本阶段不做：

1. 第三方 AIHub/AIHOT API 逆向或依赖。
2. 私密群组、好友流、cookie、session、账号密码采集。
3. 未确认的生产推送、邮件群发或 scheduler 启动。
4. 大规模 embedding、实时模型图谱、复杂可视化，除非单独立项。
5. 与当前闭环无关的大型重构。

## 5. API / 模块实现优先级
当前优先级：

1. 稳定 `ContentItem` 标准模型和来源 metadata 边界。
2. 稳定静态 JSON 输出合同。
3. 稳定配置 API action 的请求/响应和错误语义。
4. 稳定 `ArticleStore` 归档字段与旧库迁移。
5. 增加分类质量和归档分析的最小查询能力。
6. 用目标测试覆盖每个兼容边界。

## 6. 当前实现强约束
1. 不得把外部系统原始字段扩散到业务层。
2. 不得把 taxonomy、阈值、成本开关写死在入口层。
3. 不得让输出层直接访问运行时来源。
4. 不得静默跳过能力缺口，必须显式表达 capability / degrade、unsupported 或 unknown。
5. 不得读取大历史数据或启动 scheduler，除非任务明确要求。
6. `personal_tags` 不进入 AI prompt。
7. `category/tags` 只作为兼容 alias；新实现应优先读写 `channel/topics`。

## 7. 建议测试顺序
1. 运行当前任务相关单测。
2. 运行 Python 或 JavaScript 语法检查。
3. 运行受影响范围的回归测试。
4. 如涉及静态 UI，验证 `data/site/radar-data.json` 字段兼容。
5. 如涉及归档，验证 `articles_light` schema 和旧库迁移。
6. 如涉及控制面，运行 init-pro validator。

## 8. 执行后可视化校验
完成控制面、阶段计划、接口合同或架构合同修改后，生成一次控制面校验报告：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" \
  --project-root . \
  --primary-config project-defaults.yaml \
  --output INIT_PRO_VALIDATION.md
```

报告会输出：

1. 控制文件覆盖检查
2. 默认读取范围检查
3. API 错误 / 兼容 / 幂等 / 后台任务合同检查
4. `WORKLOG.md` 和主 YAML 记录检查
5. Mermaid 约束图与业务变更影响图
