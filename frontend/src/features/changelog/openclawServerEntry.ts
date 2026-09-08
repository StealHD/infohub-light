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
