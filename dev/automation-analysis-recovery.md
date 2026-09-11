# 自动化分析恢复操作

本次代码交付只完成本地修复与受控验证，不代表 VPS 已升级；VPS 的三次旧排队测试必须保留，不能自动执行。接口字段和状态以[信息自动化合同](../contracts/api/information-automations.md)为准。

## 后续获准部署时

1. 按正式发布流程部署同一已验证版本的 Service、独立 runner 或托管 adapter。停止 API/Worker，先运行 `python scripts/migrate_information_recovery_v45.py --data-dir ABS` 检查，再加 `--apply` 显式备份迁移；前置 global 44 必须已完成。此次不要对线上运行这些命令。
2. 托管 supervisor 新安装的记录使用 `execution_mode=previews_only`。旧记录继续遵循原目录模式；恢复时管理员明确设置服务环境 `INTELISCOPE_ANALYSIS_EXECUTION_MODE=previews_only`，并移除原 `INTELISCOPE_ANALYSIS_CATALOG_ONLY=true`（该旧安全开关仍优先禁止执行）。按现有服务管理方式重启 supervisor。独立 runner 显式传 `--execution-mode previews_only`；只有获准开放正式自动化时才改为 `full`。
3. 核对模型目录新鲜、preview_executable=true、execution_mode=previews_only。旧执行器显示需要升级时不能把 ready 目录当成执行成功。旧 pending 行保留，不直接修改状态或删除；用户重新选择相同文章并点击“确认重新测试”，才会原子替代未领取旧预览。已领取且结果未知时核对测试编号、主机私有结果 journal 和 Gateway 执行记录，不删除 inference-state.json 来强行恢复。
4. 新增模型后点击“刷新模型目录”，核对对应请求的 completed_at，而不是只看请求 HTTP 200。刷新失败、离线或 120 秒超时先检查 supervisor 状态与配置，之后手动重试。刷新本身不调用模型、不自动选择新模型。
5. `inteliscope-analysis-policy.json` 只记录系统创建白名单的归属及最后管理值。管理员显式改动会转为 administrator 并停止自动扩展。旧列表缺少归属记录时提示 allowlist_ownership_unknown；管理员先审查原限制，再明确采用系统管理或继续管理员管理，不能凭列表相似自动认领。不要把凭据写进此记录。
6. VPS 验收另行确认：新提交的一次预览贯通到页面完成；旧三条记录无新增领取；正式任务和通知保持关闭；新增模型真实发现与回执；两到三个 admin 浏览器会话重复提交不产生重复推理。本地受控 Gateway 的通过不能替代这些线上证据。
