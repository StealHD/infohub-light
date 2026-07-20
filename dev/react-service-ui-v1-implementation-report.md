# React 三栏 Service UI v1 实施报告

## 结果

默认 Service UI 已迁移到 `frontend/` 工程，保留现有 FastAPI、SQLite、Feed v2、任务、来源健康和权限接口。Vite 产物由 FastAPI 托管；`/assets/*` 使用 immutable cache，BrowserRouter 深链接返回 no-cache index。旧原生 UI 在一个发布周期内可用 `HORIZON_SERVICE_UI_VARIANT=legacy` 回滚。

## 能力矩阵

| 旧 Service 能力 | React 页面 | 状态 |
|---|---|---|
| 登录、Session 失效、退出 | `/login`、账户菜单 | 已迁移 |
| 精选、全部、日报 | `/feed?mode=` | 已迁移为模式筛选 |
| 稍后读 | `/later` | 已迁移 |
| Feed 历史留存 | `/history` | 已迁移 |
| 搜索、来源、频道、主题、最低分、未读优先 | 顶栏与列表工具栏 | 已迁移，移动端更多筛选为贴底面板 |
| 打开原文、已读、收藏、稍后读、忽略 | 阅读详情 | 已迁移，mutation 乐观更新并回滚 |
| `user_feed_refresh` 状态与恢复 | 全局获取横幅 | 已迁移，2 秒轮询，terminal 刷新 Feed/历史/健康 |
| 来源健康、订阅编辑、来源市场 | `/subscriptions` | 已迁移 |
| 8 类 registry 来源动态表单 | `/subscriptions` | 已迁移，不复制 Python 校验规则 |
| 来源测试样例、单源重抓 | `/subscriptions` 最近任务 | 已迁移 |
| 用户 Feed 自动周期 | `/subscriptions` | 已迁移 |
| 全局 AI/过滤/主题库配置 | `/settings` | 已迁移，owner/admin 可写 |
| 成员管理 | `/settings` | 已迁移 |
| write-only AI/Apify Key | `/settings` | 已迁移，值不回显 |
| Graph、Archive analytics、偏好反馈、站内预览 | 无 | 按产品边界继续不提供 |

## 安全与隔离

- 所有用户 Query key 都包含 `user_id`。
- logout、401 和身份切换取消旧请求并删除旧用户缓存。
- Feed 刷新、重试和订阅保存后的测试/重抓均绑定 `user_id + action_generation`；旧身份响应不能创建后续任务或写入新身份缓存。
- viewer 的 Feed 获取、重试、阅读状态和订阅写操作在 UI 中直接禁用；不依赖后端 403 作为交互反馈。
- item state 乐观更新失败时恢复所有 Feed/history 副本。
- 管理员列表 Key 只渲染名称、provider、状态和引用数；真实值仅存在于 write-only 请求输入期间，提交后立即清空表单。
- 外链仅允许无认证信息的 HTTP(S) URL。

## 工程与运行

- React 19.2、TypeScript strict、Vite 8.1、TanStack Query v5、React Router、CSS Modules、Lucide。
- Vitest + React Testing Library + MSW 覆盖 API client、缓存隔离、Feed 模型、任务状态、权限和组件。
- Playwright 覆盖 1440×900、1024×768、390×844 的截图基线、移动端列表/详情往返，以及桌面端登录到获取、留存、历史、订阅和设置的完整闭环。
- 活跃 Feed 任务每 2 秒轮询，达到 180 秒后停止网络轮询并提示用户稍后刷新查看后台结果。
- Docker 使用 Node 22 多阶段构建，最终 Python 镜像只复制 `src/ui/service_static`，不保留 Node 构建环境。

## 保留项

公网与 VPS 发布仍冻结。本报告只表达本地实现和自动化验证，不表示 `rb.jiefs.top` 已切换。旧 62 项原生 UI 行为测试保留作为 legacy compatibility 回归；React 等价能力由新的 Vitest/Playwright 测试追踪。
