# Inteliscope HeroUI 全站 Web UI 实施计划

## Global Constraints

- 生产 Web UI 最终只使用 `@heroui/react@3.2.2`、`@heroui/styles@3.2.2`、Tailwind CSS 4.3.3、Lucide 和本地 Noto Sans SC；业务页面不得直接导入 `@heroui/*`，只能从 `frontend/src/design-system/**` 使用组件。
- 全站只提供石墨紫暗色主题；圆角仅使用 16/14/10/8px，动效 120–220ms，并支持 Reduced Motion。颜色、阴影、圆角及动效常量集中在设计系统主题入口。
- 不修改后端 API、数据库、权限、TanStack Query Key、Remote MCP 协议或历史数据。继续复用 `ServiceApi`、查询缓存隔离、`ActionGeneration` 与乐观更新回滚。
- 信息流生产语义固定为“全部”；删除精选、日报、稍后读入口与模式偏好，但服务端兼容字段保留。`/later` 重定向 `/saved`，旧 `mode` 参数通过 replace 清除并保留 `item`。
- 全部正式页面完成并验证后一次性切换；删除 MUI、Emotion、MUI 图标、旧 `src/ui`、MUI 对照原型和页面级视觉 CSS Modules。开发专用固定数据 HeroUI 原型可以保留。
- 最终构建不得包含 MUI/Emotion 模块、`Mui` 类名或旧 MUI 原型文案。故障回滚依赖上一 Docker 镜像，不在源码保留生产切换开关。
- 实现必须先写失败测试，再写生产代码；保持键盘操作、焦点管理、Reduced Motion 与 Axe serious/critical 零问题。

## Task 1: HeroUI 设计系统与应用边界

- 新建 `frontend/src/design-system/**`，集中导出 HeroUI Card、Button、SearchField、Chip、Tabs、Modal、Drawer、Select、ComboBox、Table、Skeleton、Toast、Tooltip、ScrollShadow、TextArea、表单能力与 Lucide 图标。
- 固化石墨画布、三层中性表面、低饱和紫色强调、16/14/10/8px 圆角、120–220ms 动效和 Reduced Motion；使用本地 Noto Sans SC，不请求外部字体。
- 增加 HeroUI `RouterProvider` 与 React Router 的 SPA 导航桥接，保留 QueryClient、认证和 `ServiceApi` 应用边界。
- 在这一任务中只建立可测试的正式设计系统和 bootstrap 接口，不迁移具体业务页面，也不删除 MUI。
- 更新静态 UI 契约检查：正式业务代码只能通过 `design-system` 使用 HeroUI；固定数据 HeroUI 原型是唯一允许直接导入 `@heroui/*` 的业务外例外。此阶段现有 MUI 生产树仍允许存在。
- 测试至少覆盖：主题根属性、RouterProvider SPA 导航、业务层直接 HeroUI 导入被静态契约拒绝、原型例外仍被允许。

## Task 2: HeroUI 核心工作台、信息流与 Agent

- 建立正式 HeroUI Shell。断点严格为：`>=1360px` 使用 `232px + minmax(640px, 1fr) + 360px`；`1200–1359px` 使用 72px 导航并保留三栏；`768–1199px` 使用 72px 导航与覆盖式 Agent Drawer；`<=767px` 使用单栏、底部导航和 Agent Bottom Sheet。
- 导航固定为信息流、收藏、历史、订阅、助手连接、设置；没有稍后读。导航、内容和 Agent 独立滚动，开关面板不改变信息流位置。
- Feed 固定读取 `snapshot.items`，统一 Feed/收藏/历史的 `WorkbenchCardModel`，按有效发布时间旧上新下稳定排序；无效时间保持 API 原始相对顺序。
- 安装并使用 `@tanstack/react-virtual@3.14.6`，动态测量展开卡片、overscan=5；200 条数据时 Feed 卡片 DOM 不超过 40；首次进入定位底部，深链优先定位对应条目。
- 点击卡片原位展开正文并写入 `?item=<id>`；再次点击收起并移除参数；展开不自动标记已读。深链不在列表时调用现有 `feedItem`，成功则按时间临时插入并定位，404 则移除失效参数并显示可关闭提示，Feed 本身继续可用。
- 卡片直接操作仅为打开原文、收藏、加入 Agent 上下文；标记已读、复制摘要、忽略进入更多菜单；Viewer 只能查看和复制。
- 距底部 `<=96px` 自动跟随新内容；离开底部保持锚点并显示“有 N 条新内容”，点击后到底部并清零。
- 112px 短刻度最多 12 个采样点，当前可见卡片映射最近刻度，点击使用虚拟列表 `scrollToIndex`。
- 保留搜索、未读、来源、频道、主题、最低分筛选，收进 HeroUI 紧凑工具栏与 Popover。
- “更新信息流”复用 Worker 预检与任务轮询；排队/运行在按钮和运行状态展示；成功提示 4 秒，失败/部分成功/Worker 不可用提示 8 秒且可关闭。
- Agent 只在 Feed/收藏/历史出现。查询现有 delegation，只显示已配置、未配置、检查失败。`AgentContextDraftV1={userId,question,itemIds}`；最多 8 个有序 ID、问题最多 1200 字；以 `inteliscope.agent-context.v1:<user_id>` 存入 sessionStorage，退出清理；生成要求 OpenClaw 调用 `get_item` 的确定性交接提示词，不实现站内聊天、流式回答或在线状态。
- Feed 偏好使用 `inteliscope.ui.feed.v2:<user_id>`，仅保存 unreadFirst/source/channel/topic/minScore；首次读取 v1 只迁移 unreadFirst。侧栏仍使用 `inteliscope.ui.sidebar.v1:<user_id>`。
- 测试覆盖 URL/重定向/偏好迁移、稳定排序、虚拟列表、滚动与深链降级、权限与乐观回滚、12 刻度、Agent 上下文和三种响应布局。

## Task 3: HeroUI 订阅、助手连接、设置与登录

- 迁移订阅页，保留“我的订阅 / 来源库 / 运行记录”三标签、按有效频道分组、搜索及类型/健康/范围筛选。
- 来源与订阅表单使用 HeroUI Modal、Select、ComboBox、Chip；权限继续使用现有纯函数：公共/团队来源仅管理员编辑，私有来源仅创建者编辑，Viewer 全部只读。
- 保留“立即获取”、Worker 预检、任务去重、中文任务映射、技术详情和自动更新语义。
- 迁移助手连接页的创建、重命名、吊销、复制。一次性令牌 Modal 禁止背景点击和 Escape 关闭；确认“我已保存”后立即清除 React 状态。
- 设置页按“助手与 AI / 获取与主题 / 密钥 / 成员”组织。Member 只显示可读说明和助手入口；Owner/Admin 保留 AI、主题、密钥、成员；隐藏精选阈值、日报阈值、日报条数；Secret 不回显，保存失败保留必要字段但清空密钥。
- 登录页使用 HeroUI Card、Form、Input、Button；认证、错误和跳转不变。
- 这些非工作台页面不显示 Agent，内容使用完整可用宽度。
- 测试覆盖角色权限、分组筛选、单源任务状态、主题/表单校验、令牌不可意外关闭、密钥清除和登录语义。

## Task 4: 最终切换、清理与全量门禁

- HeroUI AppBootstrap 成为唯一生产入口；保留开发专用固定数据 HeroUI 原型，删除真实数据验收入口与 MUI 对照入口。
- 删除所有 MUI/Emotion/MUI Icons 依赖、MUI 生产代码、`frontend/src/ui/**`、MUI 原型和旧页面视觉 CSS Modules；业务页面全部通过 `frontend/src/design-system/**`。
- 静态 UI 契约阻止 `@mui/*`、Emotion、业务层直接 `@heroui/*`、原始颜色与页面级视觉常量重新进入。
- 更新 `UI_CONTRACT.md`、`PLAN.md`、`DECISION_LOG.md` 与测试影响映射；不复制相同规则到多处，明确真源引用关系。
- 构建产物检查不得出现 MUI/Emotion 模块、`Mui` 类名或旧原型文案。
- 完整门禁顺序：UI 契约、ESLint、TypeScript、Vitest、Vite build、三视口 Playwright/Axe、Python API 回归、Compose 校验、`git diff --check`。
- 1440x900 验证完整三栏和 4–5 张卡片；1024x768 验证覆盖 Agent；390x844 验证 Bottom Sheet 与底部导航。验证无横向溢出、独立滚动、焦点归还、Reduced Motion 与 Axe serious/critical 零问题。
