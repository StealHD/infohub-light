import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2AdminChangelogEntries: ChangelogEntry[] = [
  {
    date: '2026-08-22',
    title: 'ActorOps 管理视图切换到 v2',
    summary: 'Route、候选、Binding、费用与维护信息现在从 v2 事实直接投影，旧诊断记录不再混入当前控制面。',
    items: [
      { title: 'Route 状态来自当前 v2 数据', description: '管理列表和详情统一显示 v2 Route、主用/备用/最近成功候选、Binding 准备状态、Discovery、维护预算与替换计划；不会显示目标、Manifest、密钥或远端 Run/Dataset 标识。' },
      { title: '不可用状态更明确', description: '缺少所需 v2 数据库迁移会明确提示先完成迁移；其他暂时不可用也会以独立状态显示。普通 RSS、GitHub 与既有信息流不受影响。' },
      { title: '操作记录只保留安全动作', description: 'ActorOps 时间线只展示脱敏的 v2 管理动作，不再读取旧 Canary、Pool 或诊断事件。' },
    ],
  },
  {
    date: '2026-08-22',
    title: 'ActorOps 控制面不再回退旧版',
    summary: '设置页现在只调用 v2 Route、详情、替换、告警和脱敏操作记录；旧 Pool、Canary、Freshness 控制不再出现在浏览器。',
    items: [
      { title: '路线状态只有启用或停用', description: '界面只显示 active 或 disabled；遗留 shadow 值会安全显示为停用和迁移提示，不会触发旧路线或远端调用。' },
      { title: '详情按需读取且保持脱敏', description: '展开某条 Route 才读取 Candidate、Binding、Attempt、Discovery、维护与 Replacement；目标、Manifest、密钥和远端 Run/Dataset 始终不显示。' },
      { title: '迁移和退役错误可安全处理', description: '缺少 v2 migration、暂时不可用或旧接口 410 都会显示独立状态，不会造成整页崩溃，也不会影响普通 RSS 或 GitHub。' },
    ],
  },
]
