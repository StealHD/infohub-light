# Task 10 Fix R1 Report

状态：DONE

基线：`d6e2ee4`

## 根因与修复

- README 之前为所有连接提供同一个 14-tool `toolFilter`，因此 viewer/read-only 连接也会安装无权使用的 subscription-management 工具。
- README 现在给出两个明确的 `openclaw mcp set` 配置：viewer/read-only 连接精确六个核心读工具；仅 Inteliscope Web 创建的 subscription-management 连接精确全部 14 个工具。
- 两个命令都只引用 `${INTELISCOPE_MCP_TOKEN}` 环境变量占位符；未记录或新增任何真实令牌。
- `tests/test_openclaw_skill.py` 解码两个配置并断言其精确工具数量和集合（6/read 与 14/all），防止权限特定的本地过滤器再次混用。

## 验证

- `.venv/bin/pytest tests/test_openclaw_skill.py -q`：7 项通过。
- `git diff --check`：通过。

## 文件与范围

- `integrations/openclaw/inteliscope/README.md`
- `tests/test_openclaw_skill.py`
- `.superpowers/sdd/task-10-fix-r1-report.md`
- `WORKLOG.md`

未运行其他测试、审查或完整 gate；未修改服务端、前端、生产配置或真实 OpenClaw canary。
