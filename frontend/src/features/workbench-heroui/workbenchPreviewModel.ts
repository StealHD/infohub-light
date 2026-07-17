export type WorkbenchPreviewStory = {
  id: string
  source: string
  age: string
  title: string
  summary: string
  body: string
  channel: string
  topics: string[]
}
export type WorkbenchPreviewNavigationItem = {
  id: 'feed' | 'saved' | 'history' | 'subscriptions' | 'agents' | 'settings'
  label: string
  href: string
}

export const workbenchPreviewStories: WorkbenchPreviewStory[] = [
  {
    id: 'signal-01',
    source: 'OpenAI News',
    age: '昨天 18:21',
    title: '面向长任务的 Agent 状态管理开始形成稳定范式',
    summary: '可靠的阶段反馈、可恢复上下文和显式用户控制，正在成为长任务产品的基础能力。',
    body: '这类产品不再只展示一个加载动画，而是把准备、执行、等待外部依赖和交付结果拆成用户可以理解的阶段。好的状态设计让用户知道系统正在做什么，以及什么时候需要自己介入。',
    channel: 'AI',
    topics: ['Agent', '交互设计'],
  },
  {
    id: 'signal-02',
    source: '产品沉思录',
    age: '5 小时前',
    title: '从任务到结果：AI 原生产品的交互范式演进',
    summary: '当模型能力成为基础设施，产品竞争焦点正在从功能堆叠转向结果交付和信任建立。',
    body: '产品设计的重点正在从功能堆叠转向结果交付。用户不需要理解模型的每一步推理，但需要清楚地看到输入如何被采用、任务处于什么状态、结果基于哪些上下文，以及失败后如何恢复。',
    channel: '产品',
    topics: ['AI 原生', '用户体验', '产品设计'],
  },
  {
    id: 'signal-03',
    source: 'TechNode',
    age: '4 小时前',
    title: 'AI 编程工具市场格局变化：新玩家入场与估值分化加剧',
    summary: '头部产品持续迭代，竞争逐渐从模型能力转向工作流整合、上下文管理和团队协作。',
    body: '开发工具的新一轮竞争，不只发生在模型质量上。能否稳定地理解项目、保留任务上下文、解释执行过程并接入团队已有系统，开始决定产品的长期留存。',
    channel: 'AI',
    topics: ['AI 编程', '市场动态'],
  },
  {
    id: 'signal-04',
    source: '36Kr',
    age: '今天 09:12',
    title: '大模型企业应用落地观察：从试点到规模化的关键变量',
    summary: '企业开始把注意力从单点演示转向权限、可观测性、成本和结果一致性。',
    body: '真正进入生产环境后，企业需要回答谁能调用、使用了哪些数据、结果能否复查、失败如何恢复，以及每次任务的真实成本。',
    channel: '商业',
    topics: ['企业服务', '大模型'],
  },
  {
    id: 'signal-05',
    source: 'Claude Code Releases',
    age: '今天 10:08',
    title: 'Claude Code 更新任务恢复与工具调用可见性',
    summary: '新版集中改进长时间运行任务的状态恢复、工具反馈和错误定位。',
    body: '更新重点是降低长任务中断后的恢复成本，并让工具调用结果更容易被用户理解和复查。',
    channel: '工具',
    topics: ['Claude Code', '开发工具'],
  },
  {
    id: 'signal-06',
    source: 'Apple Developer',
    age: '今天 10:42',
    title: '面向浏览器应用的响应式侧栏与焦点管理实践',
    summary: '多栏工作台需要独立滚动、稳定焦点和清晰的窄屏降级策略。',
    body: '桌面宽屏可以同时保留导航、工作区和上下文面板；平板应改为覆盖式面板，手机则需要单列和明确的返回路径。',
    channel: '设计',
    topics: ['Web UI', '无障碍'],
  },
  {
    id: 'signal-07',
    source: 'Open Source Weekly',
    age: '今天 11:06',
    title: '虚拟列表不只是性能优化，也是一项滚动体验工程',
    summary: '动态高度、锚点保持和新内容插入决定了长列表是否真正可用。',
    body: '列表只减少 DOM 数量并不够。卡片展开、图片加载和新条目进入时，用户正在阅读的位置都不应该突然跳动。',
    channel: '工程',
    topics: ['前端', '性能'],
  },
  {
    id: 'signal-08',
    source: 'Design Systems',
    age: '今天 11:28',
    title: '暗色界面的高级感来自层级控制，而不是纯黑背景',
    summary: '相邻表面的轻微明度差、克制边框和稳定排版，比大量发光效果更耐看。',
    body: '暗色系统需要减少无意义的边界，同时让交互区域仍然可辨认。强调色只用于当前状态、关键动作和反馈。',
    channel: '设计',
    topics: ['视觉系统', '暗色主题'],
  },
  {
    id: 'signal-09',
    source: 'OpenClaw Notes',
    age: '今天 11:43',
    title: 'Remote MCP 让本地 Agent 安全读取远程个人数据',
    summary: '模型与会话留在本机，服务端只暴露有界的用户隔离只读工具。',
    body: '这种方式避免服务器承担 Agent 运行和对话状态，同时让用户继续使用自己已经配置好的本地模型。',
    channel: 'Agent',
    topics: ['OpenClaw', 'MCP'],
  },
  {
    id: 'signal-10',
    source: 'Inteliscope',
    age: '刚刚',
    title: '信息工作台新增两条高相关产品信号',
    summary: '新内容已完成去重与整理，等待你回到信息流底部查看。',
    body: '当用户正在阅读旧内容时，新条目不会抢走滚动位置，而是通过独立按钮提醒。',
    channel: '系统',
    topics: ['新内容', '状态反馈'],
  },
]

export const workbenchPreviewNavigation: WorkbenchPreviewNavigationItem[] = [
  { id: 'feed', label: '信息流', href: '/feed' },
  { id: 'saved', label: '收藏', href: '/saved' },
  { id: 'history', label: '历史', href: '/history' },
  { id: 'subscriptions', label: '订阅', href: '/subscriptions' },
  { id: 'agents', label: '助手连接', href: '/agents' },
  { id: 'settings', label: '设置', href: '/settings' },
]

export function buildWorkbenchHandoffPrompt(question: string, context: WorkbenchPreviewStory[]) {
  const request = question.trim() || '请基于这些信息提炼关键变化、机会和风险。'
  const references = context.map((item, index) => `${index + 1}. ${item.title}（item_id: ${item.id}）`).join('\n')
  return [
    '请使用 Inteliscope Remote MCP 处理以下任务。',
    `问题：${request}`,
    '先调用 get_item 读取每个 item_id 的完整安全投影；不要把标题当作完整正文。',
    '上下文条目：',
    references,
  ].join('\n')
}
