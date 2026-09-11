import type { ChangelogEntry } from './changelogTypes'
const openclawServerEntry: ChangelogEntry = {
  date: '2026-09-07', title: 'OpenClaw 服务端连接',
  summary: '管理员可通过 Inscope 服务端连接线上 OpenClaw，无需在浏览器填写 Gateway Token。',
  items: [
    {title: '连接页遮挡与自动连接', description: '个人接入页沿用工作区顶部避让，首次手动连接成功后按账号记住自动连接；修复开发模式自动连接被取消后不重试的问题；本机开发代理支持 WebSocket，连接保持当前路由。'},
    {title: '登录和会话保护', description: '连接使用当前 Inscope 登录身份，服务端保管凭据并按账号检查会话归属。'},
    {title: '连接后正常加载历史', description: '修复聊天历史的长度限制参数被服务端误拒绝，导致认证成功后仍提示无法连接的问题。'},
  ],
}

export const openclawServerEntries: ChangelogEntry[] = [{
  date: '2026-09-11', title: '多页面 Agent 连接更稳定',
  summary: '提高同账号连接容量，关闭页面主动释放连接，取消一小时强制断线。',
  items: [{ title: '退出释放与运行保护', description: '默认支持 12 个页面同时连接，部署时可调整。关闭页面停止重连，浏览器后退恢复时恢复连接；切到后台不主动断开，退出页面不发送任务取消。' }],
}, {
  date: '2026-09-10', title: '托管接入配置兼容修复',
  summary: '修复个人与独立分析 Agent 的记忆配置字段，兼容 OpenClaw 2026.9.2 与 2026.9.3 的原生配置校验。',
  items: [{ title: '保留原接入并核验真实协议', description: '缺失记忆策略的旧配置可原位补齐，显式策略冲突仍停止处理；不重建身份或替换正常凭据。原生 MCP 验证同时支持旧版合并模块和新版拆分模块，不能用旧连接可用代替新接入验收。' }],
}, {
  date: '2026-09-10', title: 'OpenClaw 聊天与自动化接入修复',
  summary: '修复个人工具协议与模型切换期间的发送冲突，独立分析纳入同一托管接入。',
  items: [{ title: '参数与失败恢复', description: '发送和重试重新核验会话模型与推理档位；不兼容时保留内容，不自动更换模型或重复调用。失败显示安全原因和恢复方向。' },
    { title: '分析服务与目录状态', description: '管理员可修复现有接入，补齐独立分析配置与模型目录；目录缺失、离线和过期分别提示，刷新不冒充配置成功。撤销同步关闭分析授权并清理专属配置，未知运行状态保留待清理。' }],
}, {
  date: '2026-09-10', title: '远端 OpenClaw 自动接入',
  summary: '支持项目与 OpenClaw 分处不同服务器，成员仍在同一入口申请和连接。',
  items: [{ title: '受限配置与同步清理', description: '服务端通过专用受限连接配置个人 Agent，验证真实加载和本人数据访问后才开放聊天；撤销同步清理远端专属授权，旧身份不能重新安装。无需用户下载文件或创建令牌。' }],
}, {
  date: '2026-09-10', title: '撤销成员接入与清理状态',
  summary: '管理员可撤销成员接入，本站立即失效，OpenClaw 清理单独核验。',
  items: [{ title: '安全撤销', description: '请求停止专属运行、停用任务并卸载专属配置，保留历史；系统派生审查任务备份后由 Gateway 随 Agent 卸载回收。清理失败可重试，不恢复权限，完成前不能重新申请。' }],
}, {
  date: '2026-09-10', title: '成员申请与管理员审批',
  summary: '成员在 Agent 接入页申请，管理员在同页允许或拒绝；结果跨浏览器保存。',
  items: [{ title: '批准后自动配置', description: '审批通过后配置成员个人 Agent，实际验证完成才能聊天；失败保留绑定供管理员重试。拒绝需填写原因，成员可重新申请。本轮不发送通知。' }],
}, {
  date: '2026-09-10', title: '本机 Agent 统一接入',
  summary: '接入、自动配置和验证收敛为一个入口，不再要求下载配置或手动创建令牌。',
  items: [{ title: '兼容旧 Agent 归属配置', description: '修复重新接入时旧默认标记在 Gateway 校验中丢失导致的配置拒绝；托管安装显式声明 Agent 归属，保留已有 Agent 和模型设置。' },
    { title: '主动解除与重新接入', description: '接入卡支持确认解除当前账号授权，再主动重新接入以验证配置流程；旧 Agent 和历史保留，新接入不迁移旧会话。' },
    { title: '账号绑定与安全恢复', description: '同账号跨浏览器复用个人 Agent；失败先检查原状态再续接，既有授权和会话保留，不自动调用模型或发送通知。' }],
}, {
  date: '2026-09-09', title: '个人 Agent 网页接入入口',
  summary: '修复未绑定账号只有说明和刷新、无法开始配置的问题。',
  items: [{ title: '配置与继续接入', description: 'Owner/Admin 可为本人准备独立绑定、下载私密配置并提交主机验证回执；保留已有数据连接，模型和通知不自动执行。' }],
}, {
  date: '2026-09-09', title: 'Skills 管理员开放范围',
  summary: '共享 OpenClaw 由管理员统一开放 Skills，成员只看到获准且满足使用条件的项目。',
  items: [
    { title: '默认关闭与统一清单', description: '首次和新发现 Skill 默认不开放；Owner/Admin 搜索、筛选、勾选并确认后统一生效，普通用户无法读取完整目录。' },
    { title: '同步失败安全恢复', description: '保存会校验版本并核对每个个人 Agent；失败保留待重试状态并暂停新聊天，已开始的对话和历史读取继续有效。' },
  ],
}, {
  date: '2026-09-08', title: '高级 Cron 兼容修复',
  summary: '完整保留长提示词，支持计划和运行记录分页，显式保留执行 Agent。',
  items: [{ title: '旧计划边界', description: '未绑定 Agent 的旧计划仍可查看、停用或删除；共享接入不开放 Gateway 管理授权。' }],
}, {
  date: '2026-09-08', title: '独立语义判断',
  summary: '语义提醒使用无工具独立推理，支持测试预览、判断额度与领取恢复。',
  items: [{ title: '有依据才通知', description: '文章引用、版本与授权在服务端校验；个人只读分析模式内容不进入模型。' },
    { title: '可恢复执行', description: '空队列不调用模型，结果提交中断后重交同一结果；真实通知回执待验收。' }],
}, {
  date: '2026-09-08', title: '聊天提醒草稿与管理',
  summary: '个人提醒支持编辑、测试预览、确认启用和运行记录；聊天仅准备草稿。',
  items: [{ title: '独立授权', description: '提醒 MCP 授权单独配置，原有连接不会自动扩权。' },
    { title: '先确认再启用', description: '确认卡读取服务端规则；示例不自动发送，旧 Cron 保留为高级入口。真实通知回执待验收。' }],
}, {
  date: '2026-09-08', title: '个人关键词提醒后端',
  summary: '新增个人规则草稿、测试和确认启用接口；只判断启用后采集的新增内容。',
  items: [
    { title: '确认后启用', description: '规则修改后暂停并重新确认；测试不发送通知，也不推进正式水位。' },
    { title: '可追踪的投递', description: '判断和通知状态分别记录，未知发送结果不会自动重发。聊天管理界面和真实通知回执仍待验收。' },
  ],
}, {
  date: '2026-09-08', title: '个人接入状态与会话目录',
  summary: '个人接入页区分绑定验证、聊天连接和通知状态；会话目录按本人 Agent 分页读取。',
  items: [
    { title: '按账号恢复', description: '切换账号后不采用旧账号的状态响应；个人目录保留历史读取边界。' },
    { title: '查看 Skills', description: '只读展示当前 Agent 的 Skills，共享接入不开放安装和修改。' },
  ],
}, {
  date: '2026-09-08', title: '个人 Agent 身份与授权',
  summary: '服务端连接按当前账号选择独立 Agent 和 MCP 授权，绑定无效时停止连接。',
  items: [
    { title: '账号分别接入', description: 'Owner、Admin 和 Member 完成个人部署绑定后可聊天；Viewer 保持只读。个人工具只读取本人内容，旧授权不会自动扩权。' },
    { title: '保留已有历史', description: '既有 main 会话继续按原账号归属只读，不自动迁移；吊销绑定、停用账号或授权过期后阻止继续访问。' },
  ],
}, openclawServerEntry]
