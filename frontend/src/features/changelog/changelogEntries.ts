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
        date: '2026-07-24',
        title: '订阅与运行记录更清爽',
        summary: '用更清楚的来源卡、筛选下拉和自动更新开关减少订阅页的信息拥挤。',
        items: [
          { title: '频道聚焦', description: '“我的订阅”和“来源库”分别记住当前频道；搜索或筛选使频道暂时无结果时，会自动回到首个有内容的频道，桌面选中标识也保持清晰对比。' },
          { title: '来源卡片', description: '来源卡只保留名称、类型、范围、HeroUI 健康状态标签、更新摘要和主操作；低频“查看引用”入口已移除，分享与编辑继续按权限放在明确的“更多”菜单。' },
          { title: '筛选与自动更新', description: '来源筛选改为原位下拉面板；全部订阅自动更新的纯开关固定在右上角，更新周期单独位于右下角，手机端也能直接操作。' },
          { title: '紧凑运行记录', description: '任务结果与创建、完成时间集中在一行展示；技术详情和响应结构通过带箭头、明确展开反馈的独立按钮按需显示。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '主流邮件服务统一发件配置',
        summary: '由工作区管理员统一配置发件服务，成员只需填写自己的收件邮箱。',
        items: [
          { title: '五种服务商预设', description: '支持 QQ、网易、Gmail、Resend 与 Amazon SES；服务器、端口和 SSL 方式由系统固定派生，不开放任意 SMTP 地址。' },
          { title: '保存、测试、启用', description: '配置或凭据变化会自动停用；只有当前配置成功发送测试邮件后才能启用，凭据与测试收件人提交后立即清空且不回显。' },
          { title: '暂停不补发', description: '邮件服务未就绪时保留用户原有邮箱通知选择，但不会产生邮件队列；恢复后只通知之后真正新增的内容，Webhook 不受影响。' },
          { title: '凭据隔离', description: '授权码、App Password、API Key 与 SES SMTP Password 只写入 SecretStore；设置页和接口只显示安全配置状态。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '偏好来源新内容通知',
        summary: '为明确选择的来源增加邮箱或 Webhook 主动通知，同时把历史数据留在信息流而不补推。',
        items: [
          { title: '账户接收方式', description: '每个账户可在设置页选择邮箱或 Webhook，保存后只显示是否已配置，并可发送一条不抓取来源的模拟测试通知。' },
          { title: '按来源开启', description: '订阅设置新增“从现在开始接收新内容通知”；开启后的来源卡片会显示通知状态。' },
          { title: '旧数据保护', description: '首次快照、历史或复用内容、停用期间的内容以及 personal_only 来源不会补推，只投递启用后确认的新条目。' },
          { title: '投递与获取隔离', description: '通知在信息流结果提交后独立发送；接收端失败不会让已经成功的来源获取被重复执行。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '运行诊断与阅读细节完善',
        summary: 'OpenClaw 能取得更充分的安全任务证据，图片、概览和常用控件在窄空间下也更容易操作。',
        items: [
          { title: '运行记录直接诊断', description: '从运行记录加入 OpenClaw 后会读取安全的原因、证据和恢复建议，不再只停留在任务状态摘要，也不会自动重试或修改任务。' },
          { title: '图片全图预览', description: '多图缩略格不再裁掉竖图；点击可查看完整图片，并通过左右按钮或方向键循环切换。' },
          { title: '更大的展开区域', description: '卡片使用图标式展开提示，标签和 Footer 空白也能展开；收藏、原文、Agent 与更多操作仍保持独立。' },
          { title: '概览先利用空白', description: '手动打开信息概览时，阅读列会先使用左侧空余空间让位，到达安全边界后才覆盖卡片。' },
          { title: '管理操作反馈', description: 'Apify 额度刷新会显示忙碌状态；OpenClaw 连接按钮保持同行，MCP 配置代码块也会对齐并安全换行。' },
        ],
      },
      {
        date: '2026-07-23',
        title: '操作手册与发布入口',
        summary: '把使用说明、产品更新和正式 Release 放到随时可达的账户区域，并建立合并文档门禁。',
        items: [
          { title: '操作手册', description: '新增源码受控的操作手册，覆盖订阅、阅读、运行记录、Agent、账户设置和常见状态排查。' },
          { title: '向上账户菜单', description: '侧栏底部头像菜单改为垂直向上展开；折叠导航也能直接进入操作手册、更新日志和 Release 发布页。' },
          { title: '文档与发布菜单', description: '展开侧栏后，账户右侧提供独立的向上菜单，可在操作手册、更新日志和 GitHub Release 页面之间选择。' },
          { title: '合并自动检查', description: '每次产品代码合并都由 Test Gate 验证操作手册与更新日志已同步复核，缺少任一项时检查失败。' },
        ],
      },
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
          { title: '明确的明暗外观', description: '页头可以显式选择白天或黑夜模式；选择会在应用加载前恢复，不再被后续系统外观变化覆盖。' },
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
