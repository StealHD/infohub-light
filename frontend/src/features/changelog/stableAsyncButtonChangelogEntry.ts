import type { ChangelogEntry } from './changelogTypes'

export const stableAsyncButtonChangelogEntry: ChangelogEntry = {
  date: '2026-09-02',
  title: '操作按钮在处理中不再跳动',
  summary: '保存、提交、测试、刷新和删除等操作进入处理中时会保持原有尺寸与位置，减少页面抖动和误触疑虑。',
  items: [
    { title: '按钮尺寸保持稳定', description: '按钮会同时为正常文案和处理中提示预留空间，只切换可见内容，不再因“保存中”等文字长短改变宽度或挤动相邻操作。' },
    { title: '通知设置不再整体闪动', description: '保存个人新内容通知后继续保留同一张表单和按钮实例，避免成功响应导致操作区重新挂载、焦点和视觉位置突变。' },
    { title: '同类操作统一约束', description: '系统设置、成员、订阅、通知、助手连接和 ActorOps 等异步文字按钮统一使用稳定状态组件，并由 UI 合同检查阻止旧写法回流。' },
    { title: '刷新反馈清晰可见', description: '刷新或重试后图标会立即旋转，请求很快时也会保留可感知的短暂反馈；按钮文案、尺寸和位置不会跳变。' },
  ],
}
