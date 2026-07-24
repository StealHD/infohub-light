export type ManualStep = {
  title: string
  description: string
  href?: string
  linkLabel?: string
}

export type ManualSection = {
  id: `manual-${string}`
  label: string
  summary: string
  steps: ManualStep[]
}

export const manualReview = {
  reviewedAt: '2026-07-24',
  change: '订阅交互、偏好通知与工作区邮件发送服务',
} as const

export const manualSections: ManualSection[] = [
  {
    id: 'manual-start',
    label: '快速开始',
    summary: '从订阅来源到阅读第一批内容的最短路径。',
    steps: [
      {
        title: '选择来源',
        description: '进入“订阅与来源”，可以从来源库订阅公共来源，也可以新增只对自己可见的私人来源。',
        href: '/subscriptions',
        linkLabel: '打开订阅与来源',
      },
      {
        title: '获取内容',
        description: '订阅列表的“立即获取”会创建后台任务；任务状态和结果在同页“运行记录”中查看，不需要反复点击。',
      },
      {
        title: '开始阅读',
        description: '回到信息流后，可按发布时间或入库时间排序，并使用当天、公共订阅、私人订阅等常用视图缩小范围。',
        href: '/feed',
        linkLabel: '打开信息流',
      },
    ],
  },
  {
    id: 'manual-reading',
    label: '阅读与收藏',
    summary: '在不丢失阅读位置的前提下筛选、展开和保存内容。',
    steps: [
      {
        title: '筛选与排序',
        description: '筛选、刷新和常用视图会尽量保留当前卡片位置；切换排序方向或时间口径会明确回到列表顶部。',
      },
      {
        title: '查看与保存',
        description: '卡片可以从标签或空白区域展开；图片会完整显示在缩略格中，点击后可查看全图并用左右按钮或方向键切换。也可以打开原文、收藏或加入 Agent 上下文，忽略的内容只能从设置页恢复。',
      },
      {
        title: '管理收藏',
        description: '“收藏”和“历史”复用相同的卡片、筛选和排序方式；收藏只属于当前账户。',
        href: '/saved',
        linkLabel: '打开收藏',
      },
    ],
  },
  {
    id: 'manual-subscriptions',
    label: '订阅与运行记录',
    summary: '管理来源范围、自动更新、健康状态和后台任务。',
    steps: [
      {
        title: '按频道管理',
        description: '“我的订阅”和“来源库”会分别记住当前频道。搜索覆盖全部来源，类型、健康状态和可见范围通过“筛选”下拉菜单设置；当前频道无结果时会自动显示首个有内容的频道，桌面频道标识在选中状态下仍保持清晰对比。',
      },
      {
        title: '公共与私人',
        description: '公共订阅可被工作区成员发现，私人订阅只对创建者可见。旧的 workspace 来源会作为公共订阅显示。',
      },
      {
        title: '全部订阅自动更新',
        description: '卡片右上角的开关直接开启或关闭全部订阅自动更新，右下角的“更新周期”单独选择周期；手机端也无需先展开管理区。它始终作用于全部已启用订阅，不是频道级设置。',
      },
      {
        title: '只通知之后的新内容',
        description: '先在设置页保存收件邮箱或 Webhook 并启用消息通知，再在订阅设置中开启“从现在开始接收新内容通知”。邮箱还要求管理员已启用工作区发件服务；服务暂停时保留你的选择，但不入队也不补发。首次快照、历史或复用内容、停用期间发现的内容都不会补推；personal_only 来源不参与通知。',
        href: '/settings',
        linkLabel: '配置消息通知',
      },
      {
        title: '排查失败',
        description: '来源状态为降级或失败时，先打开状态详情查看安全摘要和恢复建议；页面不会展示凭据或原始上游错误。',
      },
      {
        title: '复用运行记录',
        description: '运行记录优先显示任务、状态、来源或结果以及创建和完成时间；技术详情与响应结构默认折叠，可通过带箭头的独立按钮柔和展开。记录也可直接加入 Agent 上下文，OpenClaw 会通过只读任务诊断取得安全的原因、证据和建议，不会自动重试或修改任务；内部任务 ID 不会成为页面文案。',
      },
    ],
  },
  {
    id: 'manual-agent',
    label: 'Agent 与 OpenClaw',
    summary: '让用户自己的 OpenClaw 在明确授权下读取 Inteliscope 数据。',
    steps: [
      {
        title: '创建数据连接',
        description: '在“助手连接”创建只读或订阅管理连接。令牌只显示一次；订阅管理仍需 prepare、确认和 apply，不能直接改写数据。',
        href: '/agents',
        linkLabel: '打开助手连接',
      },
      {
        title: '连接本地 Gateway',
        description: '浏览器直接连接用户自己的 OpenClaw Gateway。Inteliscope 不托管模型密钥，也不会把文章正文预先发送给模型。',
      },
      {
        title: '加入上下文',
        description: '信息卡片或运行记录最多可加入 8 条上下文；发送时只传问题和内部条目 ID。文章由 OpenClaw 读取授权内容，运行记录走只读诊断；页面摘要和错误原文不会预先发送给模型，窄屏条目也不会造成横向溢出。',
      },
      {
        title: '断开与移除',
        description: '普通断开保留当前会话；“忘记此浏览器”只有在 Gateway 确认移除设备后，才清理本地凭据和对话记录。',
      },
    ],
  },
  {
    id: 'manual-account',
    label: '账户与设置',
    summary: '管理密码、成员、Key、外观以及产品文档入口。',
    steps: [
      {
        title: '账户菜单',
        description: '侧栏底部头像会向上打开账户菜单，可进入账户与成员、设置、操作手册和更新日志，或显式退出登录。',
      },
      {
        title: '文档与发布',
        description: '展开侧栏后，账户右侧的独立入口会向上打开“文档与发布”菜单，可选择操作手册、更新日志或 GitHub Release 发布页。',
      },
      {
        title: '账户安全',
        description: '每位登录用户都可以修改自己的密码；Owner/Admin 还可以管理非 Owner 成员，服务端权限始终是最终边界。',
        href: '/users',
        linkLabel: '打开账户与成员',
      },
      {
        title: '工作区设置',
        description: '设置页集中管理主题、消息通知、恢复已忽略内容以及管理员可见的 AI 与 Key 配置。收件邮箱或 Webhook 保存后只显示是否已配置，测试通知使用模拟内容，不抓取来源也不改变新内容起点；真实 Key 同样不会回显。',
        href: '/settings',
        linkLabel: '打开设置',
      },
      {
        title: '管理员配置发件服务',
        description: 'Owner/Admin 在“邮件发送服务”选择 QQ、网易、Gmail、Resend 或 Amazon SES，按页面填写完整发件邮箱及对应的授权码、App Password、API Key 或 SES SMTP Password，再依次“保存配置 → 发送测试邮件 → 启用”。凭据和测试收件人提交后立即清空且不会回显；修改账号或凭据后必须重新测试。普通成员只填写自己的收件邮箱。',
        href: '/settings',
        linkLabel: '配置邮件发送服务',
      },
    ],
  },
  {
    id: 'manual-troubleshooting',
    label: '状态与排查',
    summary: '先确认状态事实，再决定是否重试或联系管理员。',
    steps: [
      {
        title: '查看操作结果',
        description: '保存、更新或任务完成后，页面顶部会短暂显示可关闭的结果提示；允许重试的失败可直接从提示中重试，表单校验和运行中状态仍保留在原控件附近。',
      },
      {
        title: '后台不可用',
        description: 'Worker 显示缺失或过期时，不要连续提交获取任务；先等待后台恢复或联系管理员，再从运行记录重试。',
      },
      {
        title: '工具未发现',
        description: 'OpenClaw 已连接与 Inteliscope 工具可用是两种独立状态。工具未发现时检查数据连接、授权范围和 Gateway 工具配置。',
      },
      {
        title: '保护秘密',
        description: '不要把 API Key、Gateway Token 或 MCP Token 粘贴到对话、问题、来源说明或运行记录中；只通过对应的安全表单写入。',
      },
    ],
  },
]

export const defaultManualSectionId = manualSections[0].id

export function isManualSectionId(value: string): value is ManualSection['id'] {
  return manualSections.some((section) => section.id === value)
}
