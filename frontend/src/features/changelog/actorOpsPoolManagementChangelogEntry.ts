import type { ChangelogEntry } from './changelogTypes'

export const actorOpsPoolManagementChangelogEntry: ChangelogEntry = {
  date: '2026-08-13',
  title: 'ActorOps 主备池可安全管理',
  summary: '固定三槽现在可由管理员按槽位新增、替换、移出或切换主用；验证、来源证据和费用边界保持不变。',
  items: [
    { title: '槽位操作由服务端判定', description: '空槽只允许填入第一个空位，已占用槽才允许替换或移出。页面会显示安全阻断原因，避免浏览器根据状态自行推断可操作性。' },
    { title: '失败重规划不再错称旧 Actor 升级', description: '持久化的新增或替换流程会显示真实操作和安全槽位；候选列表只读取该槽，不会把“替换主用”伪装成“升级当前 Actor”。' },
    { title: '替换继续两次确认', description: '新增和替换先免费检查并手选候选，再进行一次付费验证；所有已启用来源通过后，第二次确认才原子切换单槽。旧主备在整个验证期间持续运行。' },
    { title: '超出批准上限会终态拒绝', description: '上游最终费用若高于本次批准上限，验证、尝试与批次会以同一安全原因终结并保留实际账目；不会卡在运行中、不会激活候选，也不会自动重试。' },
    { title: '失败不会再伪装成已就绪', description: '候选启动被上游拒绝、返回错误内容或无法核对费用时会保留安全失败原因并立即停止该流程；不会把未完成的验证写成“可以生效”。' },
    { title: '绑定的主备池会进入真实抓取', description: '已有 X、Instagram 或 YouTube 来源绑定 ActorOps Route 后，单来源获取和信息流刷新都会使用该 Route 的当前主备顺序；YouTube 的来源 Canary 未完成时仍使用免费 Feed，认证后才以 Actor 为主，不会再因旧配置形状静默回退或直接失败。' },
    { title: '单个来源的健康主用不会被暂停备用连带阻断', description: '来源已完成主备实测后，某一 Actor 只对该目标临时暂停时，Worker 会继续用其余已验证健康槽获取最新内容；不会把这条来源误报为“缺少两个 Actor”，也不会临时启动未经验证的替代者。' },
    { title: '移出不收费且保留历史', description: '移出主备池会展示压紧后的顺序，要求固定确认词，不启动 Actor，也不会删除 Revision、Canary 或费用证据。未知启动、运行中验证和门槛不足会安全阻止操作。' },
    { title: '已验证备用可直接设为主用', description: '备用槽可通过精确确认词直接成为当前主用；该操作只交换已认证槽位顺序，不启动 Actor、不重新验证，也不产生费用。' },
    { title: '候选质量可见且不放宽安全门槛', description: '已通过免费可执行性检查的候选会显示 Apify Store 的评分、评分人数和使用人数，并据此稳定排序。公开质量数据只帮助选择，不能让未通过 Build、输入、内容或价格检查的 Actor 变得可配置。' },
    { title: '后续单次费用上限可直接调整', description: '主备配置页可将后续、仍需人工确认的单次 Actor Run 上限调至最高 $0.10；保存不替换当前池，也不会自动启动或扣费。' },
    { title: '页面更平整', description: 'ActorOps 页签和主备表面移除多余阴影与模糊效果，保留细边框和适度圆角；手机单列不会横向溢出。' },
  ],
}
