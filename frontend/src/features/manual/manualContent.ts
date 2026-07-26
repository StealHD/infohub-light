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
  reviewedAt: '2026-07-26',
  change: 'v1.7.7：状态图标化、渐进危险操作、设置悬浮目录与 OpenClaw 输入法修复',
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
        description: '订阅列表的“立即获取”会创建后台任务；任务结束后会先加载最新信息流，再显示去重合并后实际新增了多少条。任务状态和详情仍可在同页“运行记录”中查看，不需要反复点击。',
      },
      {
        title: '开始阅读',
        description: '回到信息流后，可用“重新载入”读取服务器上的最新快照，也可用“获取新内容”启动后台来源抓取。“重新载入”进行中按钮保持原位，只旋转图标并阻止重复点击。还可按发布时间或入库时间排序，并使用当天、公共订阅、私人订阅等常用视图缩小范围。',
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
        description: '筛选、重新载入、获取新内容和常用视图会尽量保留当前卡片位置；离开新鲜边缘时，新到内容会通过“N 条新内容”提示等待查看。切换排序方向或时间口径会明确回到列表顶部。“信息概览”还可查看我的订阅、来源库与最近加载的最多 100 条运行记录，读取失败会显示“—”而不会误报为 0，点击可直达对应订阅页签。',
      },
      {
        title: '查看与保存',
        description: '卡片可以从标签或空白区域展开，也可用展开/折叠线框按钮控制；鼠标或键盘停留在底部操作上时，说明会优先显示在按钮上方。图片会完整显示在缩略格中，点击后可用缩略图、左右按钮、方向键或触摸滑动切换，单张加载失败可就地重试。也可以打开原文、收藏或“问 Agent”；取消收藏或忽略后有 8 秒撤销入口，超时后仍可从设置页恢复忽略内容。',
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
        description: '“我的订阅”固定提供“全部”和“异常”，默认显示全部；异常只收纳需关注与连续失败，不包含尚未抓取。“来源库”仍只按真实频道分类。顶部“我的订阅 / 来源库 / 运行记录”不再长期显示数量，数量集中在信息概览；页面链接会用 tab 参数保留当前页签。搜索覆盖全部来源，类型、健康状态和可见范围通过“筛选”下拉菜单设置；当前订阅分组无结果时会回到“全部”，移动端选择器使用相同规则。',
      },
      {
        title: '公共与私人',
        description: '公共订阅可被工作区成员发现，私人订阅只对创建者可见。旧的 workspace 来源会作为公共订阅显示。订阅共享来源时，只复用能够确认来源原始标题的历史内容，并按当前账户的频道、主题、个人标签和分析模式重新生成；缺少可信原始标题的旧内容不会预填，也不会继承其他成员的 AI 翻译标题、偏好、分析结果、阅读状态或内容图片。',
      },
      {
        title: '全部订阅自动更新',
        description: '卡片右上角的开关直接开启或关闭全部订阅自动更新，右下角的“更新周期”单独选择周期；手机端也无需先展开管理区。它始终作用于全部已启用订阅，不是频道级设置。',
      },
      {
        title: '只通知之后的新内容',
        description: '先在设置页保存收件邮箱或 Webhook 并启用消息通知，再直接使用订阅卡片上的 Bell/BellRing 图标开关；鼠标停留或键盘聚焦会在上方说明当前状态，订阅设置弹窗不再重复该选项。邮箱还要求管理员已启用工作区发件服务；服务暂停时保留你的选择，但不入队也不补发。首次快照、历史或复用内容、停用期间发现的内容都不会补推；personal_only 来源不参与通知。',
        href: '/settings',
        linkLabel: '配置消息通知',
      },
      {
        title: '直接操作与稳定获取状态',
        description: '允许编辑的来源直接显示 Pencil 图标，Settings 图标打开订阅设置；只有允许分享私人来源时才显示“更多”，且其中只保留分享。健康状态也只显示明确图标，鼠标停留或键盘聚焦会在上方说明，失败图标仍可打开安全详情。“立即获取”在提交、排队和运行期间保持同一宽度与文字，只旋转图标并阻止重复点击；可在运行记录查看后续结果。',
      },
      {
        title: '排查失败',
        description: '来源状态为降级或失败时，先打开状态详情查看安全摘要和恢复建议；页面不会展示凭据或原始上游错误。',
      },
      {
        title: '复用运行记录',
        description: '运行记录优先显示任务、状态、来源或结果以及创建和完成时间；Feed 获取结果显示去重后的实际新增数量，不把抓取量或整份信息流总量冒充新增。技术详情与响应结构默认折叠，可通过带箭头的独立按钮柔和展开。记录也可直接加入 Agent 上下文，OpenClaw 会通过只读任务诊断取得安全的原因、证据和建议，不会自动重试或修改任务；内部任务 ID 不会成为页面文案。',
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
        description: '在“助手连接”创建只读或订阅管理连接。令牌只显示一次；订阅管理仍需 prepare、确认和 apply，不能直接改写数据。现有连接的复制、重命名、吊销或删除集中在中性“更多”菜单；吊销只出现在有效连接，删除只出现在已吊销记录，红色实心动作只会出现在最后一步确认。',
        href: '/agents',
        linkLabel: '打开助手连接',
      },
      {
        title: '按名称订阅 B 站 UP 主',
        description: '在浏览器 Agent 面板不附带文章或任务，直接告诉 OpenClaw 公开账号名称并要求订阅；它会通过 Inteliscope MCP 的固定 Bilibili 官方查询取得最多 5 个名称、UID 和主页候选，不需要启用 Chrome、浏览器远程调试或手工搜索。唯一精确同名会进入订阅预览，同名或模糊结果必须先由你选择。核对预览后，另发一条与服务端返回内容完全一致的准确确认短语才会应用；浏览器和 OpenClaw 都不能代你生成或改写确认。附带文章或任务的交接始终只读。',
      },
      {
        title: '连接本地 Gateway',
        description: '浏览器直接连接用户自己的 OpenClaw Gateway。Inteliscope 不托管模型密钥，也不会把文章正文预先发送给模型。',
      },
      {
        title: '查看运行反馈',
        description: '发送后会立即显示正在处理，并以可折叠轨迹说明正在读取内容、比较或使用安全工具；页面只显示固定中文动作，不展示模型原始思维、工具参数、结果、地址、令牌或确认短语。顶栏状态只保留图标，鼠标停留或键盘聚焦可查看说明；运行轨迹、重连和错误仍显示文字。向上查看旧消息时，新回复会用“有新回复”提示，不会强行把页面拉回底部。',
      },
      {
        title: '使用中文输入法',
        description: '输入法仍在组合候选时，Enter 只确认候选，不会提前发送；完成输入后普通 Enter 才会发送一次，Shift+Enter 保持换行。',
      },
      {
        title: '加入上下文',
        description: '信息卡片或运行记录最多可加入 8 条上下文；发送时只传问题和内部条目 ID。文章由 OpenClaw 读取授权内容，运行记录走只读诊断；页面摘要和错误原文不会预先发送给模型，窄屏条目也不会造成横向溢出。',
      },
      {
        title: '查询安全诊断事件',
        description: '明确要求排障时，OpenClaw 可以按最近时间或任务、来源、订阅、请求关联读取当前账户的脱敏操作事件。即使是管理员连接也只能读取与自己相关的事件；原始日志、路径、身份、文章内容、URL、凭据和堆栈不会进入页面或 Agent 上下文。',
      },
      {
        title: '断开与移除',
        description: '普通断开保留当前会话；存在浏览器配对时会显示中性的 Unplug 图标，停留或聚焦可看到“忘记此浏览器”。点击后仍需二次确认，只有 Gateway 确认移除设备后，才清理本地凭据和对话记录。',
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
        description: '侧栏底部头像会向上打开账户菜单，可进入账户与成员、设置、操作手册和更新日志，或显式退出登录；手机端从底部导航的“更多与账户”打开同一组入口，并适配系统安全区。',
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
        description: '设置页集中管理主题、消息通知、恢复已忽略内容以及管理员可见的 AI、Key 与 RSSHub Base URL。电脑端正文保持单列，把鼠标移到左侧“设置”约 150 毫秒或用键盘聚焦会打开分区目录；手机和触摸设备继续使用页内“设置区域”选择器，分区链接可直接定位。Bilibili 等受控来源只保存站点、路由和 UID，运行时使用这里配置的自建、反向代理前缀或第三方 RSSHub；自建公网实例可把 RSSHUB_ACCESS_KEY 写入 SecretStore，来源测试与 Worker 抓取只发送路由级 code，OpenClaw 不会看到或提交服务地址与密钥。可将“RSS 首次抓取窗口”设为 7 天或 30 天；新 RSS/RSSHub 订阅首次成功（即使零条）后会恢复“日常抓取窗口”，且不会扩大信息流留存。更新项目后重新运行本地 OpenClaw 初始化会自动刷新旧 Skill 并重启 Gateway；请新建对话，使“按账号名称自行解析 UID”的规则生效。收件邮箱或 Webhook 保存后只显示是否已配置，测试通知使用模拟内容，不抓取来源也不改变新内容起点；真实 Key 同样不会回显。',
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
        description: 'Agent 标题栏只显示一个 OpenClaw 状态图标，鼠标停留或键盘聚焦可查看连接、处理、重连或异常说明；重连与错误在对话区继续显示文字。工具可用性仍单独校验，未发现 Inteliscope 工具时会在对话区给出数据连接、授权范围和 Gateway 配置指引。',
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
