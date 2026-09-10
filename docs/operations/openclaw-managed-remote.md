# 远端 OpenClaw 托管接入

项目与 Gateway 可分处两台服务器。用户仍使用 `/agents`；部署者只配置一次受限主机通道，不让用户下载配置或创建令牌。普通聊天仍走原 WSS，不授予普通 relay 管理权限。

## 部署

1. 使用通过测试的同一源码提交，在 Gateway 主机建立独立私有部署目录和 Python 环境，提供源码 `src/` 与 `scripts/configure_managed_host.py`；依赖至少包含 websockets、cryptography、python-dotenv、mcp。不要改变 OpenClaw 的安装、已有工作目录或模型配置。
2. 在 Service 的私有持久数据目录生成单独 ed25519 密钥，私钥 0600。不复制操作者的通用 SSH 私钥。通过已有可信管理连接核对 Gateway 主机公钥，保存独立 0600 known_hosts；不得关闭主机校验或自动信任扫描结果。
3. 在 Gateway 主机使用操作者权限执行 `python -m scripts.configure_managed_host --root /absolute/openclaw --deployment /absolute/adapter --source-ip SERVICE_EGRESS_IP --mcp-url https://service.example/mcp --openclaw-package /absolute/installed/openclaw`，stdin 仅传上述专用公钥。安装器保留 authorized_keys 备份，添加带固定程序、来源 IP 和 restrict 的条目；不覆盖已有密钥。部署路径须为真实非符号链接目录，程序读取固定受保护 host.env，不接受 SSH 调用者提交配置目录。
4. 固定程序只接受 `inteliscope-managed-v1` 命令，stdin 为严格 JSON install/remove/check。显式 check 建立独立管理设备，操作者只批准其精确设备 ID 的 operator.admin；不批准未知设备，不给聊天设备扩权。核验 check 返回 ready；这只证明配置接口和目标目录，不证明模型或通知。
5. Service `.env` 设置 `HORIZON_OPENCLAW_MANAGED_TRANSPORT=ssh` 及 `HORIZON_OPENCLAW_MANAGED_SSH_HOST/USER/PORT/KEY/KNOWN_HOSTS`。容器路径使用现有 `/app/data` 私有卷；不挂载 Gateway 主机根目录或 Docker socket。API 镜像包含 SSH 客户端；本地 A 模式保持 transport=local。
6. 通过同一页面完成申请、审批、实际配置加载、本人 MCP 读取和聊天握手，再验证撤销与重新接入。测试不自动发消息、调用模型或通知。生产完成证据需同时记录项目 revision、适配器 revision 和真实验证结果。

## 分析服务升级（global 44）

1. 本次升级包含显式数据库迁移，不能走无迁移的普通 cutover。停止目标 API/Worker，验证备份后执行新版本 `python scripts/migrate_agent_analysis_v44.py --data-dir /absolute/data --apply`；原绑定不回填安装记录、不自动批准。保留迁移前备份用于既有发布回滚流程。
2. 在原主机适配器目录同步同一发布提交的源码，保留私有 host.env、state、.venv 及旧版本。在受保护 host.env 增加 `INTELISCOPE_OPENCLAW_PACKAGE`（实际安装包绝对目录，包含 openclaw.mjs）和 `INTELISCOPE_ANALYSIS_CATALOG_ONLY=true`。包路径仅部署者设置；不得从网页、SSH 请求载荷或浏览器读取。安装版本不兼容时原生验证失败关闭，不跳过检查。
3. 运行 `python -m scripts.install_analysis_supervisor --deployment /absolute/adapter` 安装用户级 `inteliscope-analysis.service`，此命令不启动服务。确认 host.env 权限 0600，再 `systemctl --user enable --now inteliscope-analysis.service`。与已有 Gateway 同用户，单服务最多 4 个绑定执行槽，每个绑定串行，空队列不调用模型；不重启共享 Gateway。
4. 在项目 `/agents` 显式修复既有绑定；后续新增接入自动安装个人和分析配置。能力上报心跳必须真实收到。先检查 Service 中未完成分析/预览和待投递积压，保持 catalog-only，不提交旧回执。若存在旧任务先明确逐项处置，不通过启动服务批量补跑。确认没有非本次授权任务后，部署者才可将 catalog-only 改为 false 并重启该分析服务。
5. 真实验收使用项目个人 Agent，核对其 MCP 工具目录与本人读取，再逐项执行获准的 Flash、Pro 和单篇分析。单项失败停止后续调用，不发送通知。原生传输探测只证明安装版本解析/只读调用，不能替代 Gateway 会话验收；config hash、目录心跳也不等于模型完成。
6. 分析 HTTP 结束未知时，私有运行目录保留 inference-state.json 并停止新领取。撤销先失效本站和机器令牌、请求精确身份停止，再清理；无法证明该调用已结束时保持待清理。不得删除标记来绕过检查或重启共享 Gateway 冒充安全回收，需核对真实运行证据后另行受控恢复。

## 恢复与留存

SSH 超时或未知结果不自动重试；绑定保持待验证，由管理员重试原申请。远端复用锁、配置冲突检查和验证，清理先写撤销墓碑，失败不复活旧身份。Service 的权限即时撤销不依赖远端在线。

撤销墓碑、历史会话、工作目录、配置/环境备份以及安装时的 authorized_keys 备份属于留存资料，均不算活动授权。回滚时保留这些数据；不能删除墓碑来恢复旧绑定。要停用通道，删除对应专用公钥条目并关闭 transport 配置，不删除其他管理密钥。更新适配器须在没有托管操作时切换源码，保留 host.env、state 和旧版本以便核验；不得盲目重新执行初次安装器覆盖设置。
