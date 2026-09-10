# OpenClaw 托管配置兼容核验

个人与独立分析 Agent 使用 `memory.search.enabled: false`；`memorySearch` 不是 OpenClaw 2026.9.2/2026.9.3 的有效 Agent 字段。旧配置缺少策略时可经原接入修复流程补齐，显式启用或其他策略冲突仍拒绝覆盖。升级适配器后重试原接入，不需要解除绑定、重建身份或轮换正常凭据。

## 不调用模型的原生验证

指定目标主机已安装的 OpenClaw 包目录，再运行：

```sh
INTELISCOPE_OPENCLAW_PACKAGE=/absolute/path/to/openclaw .venv/bin/python -m pytest -q tests/test_agent_native_config.py tests/test_native_mcp_installed.py
```

前者将编译出的完整配置交给实际安装包的 Schema，分别检查新配置、旧配置补齐与错误字段拒绝。后者使用实际安装包的 MCP 传输与生命周期函数访问临时本地 MCP 服务，验证初始化、目录和只读工具调用，并在结束时关闭服务和线程；不访问用户数据、不启动真实 Agent、不调用模型或发送通知。

未指定安装包时这些用例会明确跳过，**跳过不算原生验收**。受控模块布局测试另覆盖 `.js`、`.mjs` 和拆分的 `mcp-client-lifecycle` 模块。

跨版本发布前须在目标版本重复原生核验。现有 Gateway 握手成功、Python 客户端直接访问 MCP、字典结构测试通过，都不能替代新配置被目标 Gateway 接受和实际工具可用的项目端验收。离线 Schema 校验仍不等于生产接入或模型验收。
