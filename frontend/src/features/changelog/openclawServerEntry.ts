import type { ChangelogEntry } from './changelogTypes'
const openclawServerEntry: ChangelogEntry = {
  date: '2026-09-07', title: 'OpenClaw 服务端连接',
  summary: '管理员可通过 Inscope 服务端连接线上 OpenClaw，无需在浏览器填写 Gateway Token。',
  items: [
    {title: '登录和会话保护', description: '连接使用当前 Inscope 登录身份，服务端保管凭据并按账号检查会话归属。'},
    {title: '连接后正常加载历史', description: '修复聊天历史的长度限制参数被服务端误拒绝，导致认证成功后仍提示无法连接的问题。'},
  ],
}

export const openclawServerEntries: ChangelogEntry[] = [{
  date: '2026-09-08', title: '个人 Agent 身份与授权',
  summary: '服务端连接按当前账号选择独立 Agent 和 MCP 授权，绑定无效时停止连接。',
  items: [
    { title: '账号分别接入', description: 'Owner、Admin 和 Member 完成个人部署绑定后可聊天；Viewer 保持只读。个人工具只读取本人内容，旧授权不会自动扩权。' },
    { title: '保留已有历史', description: '既有 main 会话继续按原账号归属只读，不自动迁移；吊销绑定、停用账号或授权过期后阻止继续访问。' },
  ],
}, openclawServerEntry]
