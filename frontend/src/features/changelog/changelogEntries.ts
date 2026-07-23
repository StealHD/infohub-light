export type ChangelogItem = {
  title: string
  description: string
}

export type ChangelogEntry = {
  date: string
  title: string
  summary: string
  items: ChangelogItem[]
}

export type ChangelogMonth = {
  id: `month-${number}-${string}`
  label: string
  entries: ChangelogEntry[]
}

export const changelogMonths: ChangelogMonth[] = [
  {
    id: 'month-2026-07',
    label: '2026 年 7 月',
    entries: [
      {
        date: '2026-07-23',
        title: '操作结果不再挤压页面',
        summary: '保存、更新与任务结果统一从页面顶部短暂出现，正文和列表保持原位。',
        items: [
          { title: '顶部操作反馈', description: '设置、订阅、Agent、成员和 Feed 的操作结果会以可关闭提示短暂出现，不再推动页面内容。' },
          { title: '失败可直接重试', description: '刷新或来源任务失败且允许重试时，可直接在提示中重试；重复点击不会创建并行操作。' },
          { title: '表单仍在原位修正', description: '字段校验、弹窗内错误与排队或运行状态继续显示在对应控件附近，方便就地处理。' },
        ],
      },
      {
        date: '2026-07-22',
        title: '更清晰的交互反馈',
        summary: '让常用操作更靠近触发位置，状态变化更明确，工作区切换也更平稳。',
        items: [
          { title: '近邻提示', description: '鼠标与键盘触发的说明现在优先显示在控件右侧；空间不足时会自动换向或移动，异常详情也不再跑到页面角落。' },
          { title: '上下文选中态', description: '加入 Agent 上下文的按钮默认保持中性，仅在选中后显示紫色强调，并通过按压状态向辅助技术确认结果。' },
          { title: '柔和的工作区变化', description: '左右侧栏使用一致的短过渡；关闭 Agent 面板时先停止交互，再在动画结束后卸载内容。' },
          { title: '稳定的发送位置', description: 'OpenClaw 发送按钮切换为停止状态时保持在同一位置，连续操作不再引起工具栏跳动。' },
          { title: '可预期的信息流', description: '切换发布时间、入库时间或排序方向后，信息流会回到当前排序的新鲜边缘；筛选与刷新仍保留阅读位置。' },
          { title: '跟随系统外观', description: '浅色与深色外观现在跟随操作系统，并在应用加载前确定主题，减少启动时的颜色闪动。' },
        ],
      },
      {
        date: '2026-07-22',
        title: '更新日志上线',
        summary: '产品内可以直接查看 Inteliscope 的重要体验变化。',
        items: [
          { title: '本地版本记录', description: '更新内容与代码一同维护，按月份组织；桌面端提供右侧时间线，窄屏使用横向月份选择器。' },
        ],
      },
    ],
  },
]

export const defaultChangelogMonthId = changelogMonths[0].id

export function isChangelogMonthId(value: string): value is ChangelogMonth['id'] {
  return changelogMonths.some((month) => month.id === value)
}
