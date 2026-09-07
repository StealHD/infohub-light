import type { ChangelogEntry } from './changelogTypes'
export const openclawServerEntry: ChangelogEntry = {
  date: '2026-09-07', title: 'OpenClaw 服务端连接',
  summary: '管理员可通过 Inscope 服务端连接线上 OpenClaw，无需在浏览器填写 Gateway Token。',
  items: [
    {title: '登录和会话保护', description: '连接使用当前 Inscope 登录身份，服务端保管凭据并按账号检查会话归属。'},
    {title: '连接后正常加载历史', description: '修复聊天历史的长度限制参数被服务端误拒绝，导致认证成功后仍提示无法连接的问题。'},
  ],
}
