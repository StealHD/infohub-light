import type { ChangelogEntry } from './changelogTypes'

export const agentWorkspaceChangelogEntry: ChangelogEntry = {
  date: '2026-09-05',
  title: 'OpenClaw 成为与 Inscope 平级的工作区',
  summary: '左上角可在阅读工作区与执行工作区之间切换；完整对话、Worktree 任务、产物、私有 Skill 和 Automation 继续直接使用用户自己的 Gateway。',
  items: [
    { title: '首次连接提示更准确', description: '新地址或浏览器没有设备凭据时，明确提示首次配对，不再误报 Gateway token 已失效；本地校验需同时配置对应前后端端口与 Gateway 允许来源。' },
    { title: '斜杠命令在对话中输出', description: '/skills、/status、/help 直接显示列表、状态与帮助；模型、推理档位、新对话和 Worktree 使用对话内选项或确认。执行后回到普通输入，再输入 / 始终显示命令；不再进入 Skills 子菜单或弹出设置窗口。' },
    { title: '输入 @ 与 / 快捷选择', description: '信息流 Agent 与完整工作台共用快捷候选：@ 引用已有材料或选择 Skill，/ 打开少量项目操作。选择不发送，Skill 发送前再次核验；新对话与 Worktree 仍需确认，不引入 Shell、文件搜索或自动执行。' },
    { title: '顶部与信息流统一，Skills 可以直接查看', description: 'OpenClaw 复用信息流玻璃页头，隐藏自动会话标题中的地址与随机标识。兼容 Gateway 的 Skill 状态字段，增加无需授权的详情、缺失条件和刷新重试；顶部“使用示例”说明每项功能的操作与预期结果。' },
    { title: '两个产品工作区清楚切换', description: 'Inscope 保留订阅、阅读与追踪；OpenClaw 集中对话、执行与自动化。每个用户只保存各工作区最近路由，切换不重连、不自动发消息或打断任务。' },
    { title: '对话成为主场', description: '移除旧五标签、嵌套三栏与连续卡片。桌面固定会话侧栏，Context、Tasks 和 Artifacts 按需打开；手机改用底部 Sheet，信息流紧凑 Agent 面板保持原样。' },
    { title: '新 Worktree 任务有可信范围', description: '只能选择 Gateway 注册项目和服务器返回的基础分支；父对话继续运行。若 Worktree 已建但任务未启动，可在原 Session 内重试，不会重复创建。' },
    { title: '任务与产物独立恢复', description: 'Tasks 支持筛选、详情和确认取消；Artifacts 只按明确来源读取，安全图片与文本可小体积预览，HTML、SVG 和未知文件只下载，内容不经过 Inscope 服务。' },
    { title: '私有 Skill 分块上传', description: '用户 ZIP 在浏览器计算 SHA-256 后顺序上传，大小取 Gateway 限制与 20 MiB 的较小值；覆盖、安装和启停都需要明确确认，页面不读取环境变量值。' },
    { title: 'Automation 关闭页面仍继续', description: '一次、间隔和带时区 Cron 由 Gateway 保存执行；编辑一次执行时间时按浏览器本地时区回填，避免 UTC 偏移。新建默认停用且只运行 isolated agentTurn；不提供 Webhook、Shell、秘密字段或外部投递。' },
    { title: '管理授权按需出现', description: '写操作才弹出单独的临时 operator.admin 授权；成功后只解锁动作，不自动重放写入。连接不持久化、不自动重连，并在页面关闭或空闲后销毁。' },
    { title: '连接与资源不再串线', description: '快速切换连接或会话时只接受最新操作；Tasks、Artifacts 和会话树按可信根来源校验。Worktree 重试复用幂等标识，临时管理连接断开或过期会立即重新锁定。' },
    { title: '本地连接不影响生产页面', description: '本地与生产站点按浏览器 Origin 隔离配对信息；保存的 Session 已被 Gateway 删除时，只更新本地 Session 绑定，不删除或覆盖生产页面的设备连接。' },
  ],
}
