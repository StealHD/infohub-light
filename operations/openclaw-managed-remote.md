# 远端 OpenClaw 托管接入

项目与 Gateway 可分处两台服务器。用户仍使用 `/agents`；部署者只配置一次受限主机通道，不让用户下载配置或创建令牌。普通聊天仍走原 WSS，不授予普通 relay 管理权限。

## 部署

1. 使用通过测试的同一源码提交，在 Gateway 主机建立独立私有部署目录和 Python 环境，提供源码 `src/` 与 `scripts/configure_managed_host.py`；依赖至少包含 websockets、cryptography、python-dotenv、mcp。不要改变 OpenClaw 的安装、已有工作目录或模型配置。
2. 在 Service 的私有持久数据目录生成单独 ed25519 密钥，私钥 0600。不复制操作者的通用 SSH 私钥。通过已有可信管理连接核对 Gateway 主机公钥，保存独立 0600 known_hosts；不得关闭主机校验或自动信任扫描结果。
3. 在 Gateway 主机使用操作者权限执行 `python -m scripts.configure_managed_host --root /absolute/openclaw --deployment /absolute/adapter --source-ip SERVICE_EGRESS_IP --mcp-url https://service.example/mcp`，stdin 仅传上述专用公钥。安装器保留 authorized_keys 备份，添加带固定程序、来源 IP 和 restrict 的条目；不覆盖已有密钥。部署路径须为真实非符号链接目录，程序读取固定受保护 host.env，不接受 SSH 调用者提交配置目录。
4. 固定程序只接受 `inteliscope-managed-v1` 命令，stdin 为严格 JSON install/remove/check。显式 check 建立独立管理设备，操作者只批准其精确设备 ID 的 operator.admin；不批准未知设备，不给聊天设备扩权。核验 check 返回 ready；这只证明配置接口和目标目录，不证明模型或通知。
5. Service `.env` 设置 `HORIZON_OPENCLAW_MANAGED_TRANSPORT=ssh` 及 `HORIZON_OPENCLAW_MANAGED_SSH_HOST/USER/PORT/KEY/KNOWN_HOSTS`。容器路径使用现有 `/app/data` 私有卷；不挂载 Gateway 主机根目录或 Docker socket。API 镜像包含 SSH 客户端；本地 A 模式保持 transport=local。
6. 通过同一页面完成申请、审批、实际配置加载、本人 MCP 读取和聊天握手，再验证撤销与重新接入。测试不自动发消息、调用模型或通知。生产完成证据需同时记录项目 revision、适配器 revision 和真实验证结果。

## 恢复与留存

SSH 超时或未知结果不自动重试；绑定保持待验证，由管理员重试原申请。远端复用锁、配置冲突检查和验证，清理先写撤销墓碑，失败不复活旧身份。Service 的权限即时撤销不依赖远端在线。

撤销墓碑、历史会话、工作目录、配置/环境备份以及安装时的 authorized_keys 备份属于留存资料，均不算活动授权。回滚时保留这些数据；不能删除墓碑来恢复旧绑定。要停用通道，删除对应专用公钥条目并关闭 transport 配置，不删除其他管理密钥。更新适配器须在没有托管操作时切换源码，保留 host.env、state 和旧版本以便核验；不得盲目重新执行初次安装器覆盖设置。
