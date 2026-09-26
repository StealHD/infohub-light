import type { ChangelogEntry } from './changelogTypes'

export const skillExecutionEntry: ChangelogEntry = {
  date: '2026-09-26', title: '补齐已开放 Skill 的执行能力',
  summary: 'Skill 可读取说明与参考文件，book-skill 可使用浏览器；同步会核验已有会话的实际工具是否就绪。',
  items: [
    { title: '受限读取与浏览器', description: '开放 Skill 后补齐工作区及已解析 Skill 目录的只读能力，book-skill 同时取得浏览器能力；保留主机文件、Shell 和文件修改限制。' },
    { title: '已有连接可同步或收回', description: '部署更新后，管理员在管理开放范围点击“同步执行能力”即可修复；已有会话的实际工具未就绪时显示同步失败并允许重试。收回 Skill 时撤回对应受管能力。' },
  ],
}
