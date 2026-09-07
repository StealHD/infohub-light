import type { ChangelogEntry } from './changelogTypes'
export const openclawServerEntry: ChangelogEntry = {
  date: '2026-09-07', title: 'OpenClaw 服务端连接',
  summary: '管理员可通过 Inscope 服务端连接线上 OpenClaw，无需在浏览器填写 Gateway Token。',
  items: [{title: '登录和会话保护', description: '连接使用当前 Inscope 登录身份，服务端保管凭据并按账号检查会话归属。'}],
}
