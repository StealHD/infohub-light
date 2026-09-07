# Token 与上下文参考入口

本页仅提供索引，不定义独立的读取范围、测试流程或运行配置。

- 开发上下文与按需读取：[AGENTS](../../AGENTS.md#4-agent-默认读取范围与任务读取路由)。
- 定向测试、impacted preflight 与限长日志：[验证流程](test-gate.md)。
- AI 输入边界、用户隔离缓存与缓存版本：[架构合同](../contracts/architecture/README.md#33-ai-boundary)；当前 Service 缓存实现为 `src/services/user_analysis_cache.py`。
- 能力与参数词汇：[project-defaults.yaml](../../project-defaults.yaml)；目标环境的实际配置仍需从相关 Service 配置/设置实现核对。

旧笔记中的文件型分析缓存、二阶段 enrichment 和每日任务说明不再作为当前 Service 的运行依据；需要解释旧行为时使用本文件的 Git 历史。
