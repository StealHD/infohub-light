import type { ChangelogEntry } from './changelogTypes'

export const actorOpsPoolManagementChangelogEntry: ChangelogEntry = {
  date: '2026-08-13',
  title: 'ActorOps 主备池可安全增删替换',
  summary: '固定三槽现在可由管理员按槽位新增、替换或移出；验证、来源证据和费用边界保持不变。',
  items: [
    { title: '槽位操作由服务端判定', description: '空槽只允许填入第一个空位，已占用槽才允许替换或移出。页面会显示安全阻断原因，避免浏览器根据状态自行推断可操作性。' },
    { title: '替换继续两次确认', description: '新增和替换先免费检查并手选候选，再进行一次付费验证；所有已启用来源通过后，第二次确认才原子切换单槽。旧主备在整个验证期间持续运行。' },
    { title: '移出不收费且保留历史', description: '移出主备池会展示压紧后的顺序，要求固定确认词，不启动 Actor，也不会删除 Revision、Canary 或费用证据。未知启动、运行中验证和门槛不足会安全阻止操作。' },
    { title: '页面更平整', description: 'ActorOps 页签和主备表面移除多余阴影与模糊效果，保留细边框和适度圆角；手机单列不会横向溢出。' },
  ],
}
