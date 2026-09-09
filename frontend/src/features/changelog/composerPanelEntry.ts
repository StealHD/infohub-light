import type { ChangelogEntry } from './changelogTypes'

export const composerPanelEntry: ChangelogEntry = {
  date: '2026-09-09', title: '快捷列表更紧凑，动效区分 Ultra 与 Fast',
  summary: '/ 与 @ 去掉重复标题与大块留白，Ultra 轻盈漂浮、Fast 快速流动。',
  items: [
    { title: '紧凑的候选列表', description: '移除顶部标题和底部提示占位，列表限高滚动，窄栏自动分行；技能与材料混合时显示轻量分组，禁用原因仍完整可读。' },
    { title: '紧凑模型列表', description: '模型选择页把整行返回标题收敛为图标，并隐藏视觉滚动条；滚轮、触控和键盘滚动保持可用。' },
    { title: '两种粒子状态', description: '拖到 Ultra 即淡入微浮粒子，移离即淡回刻度，松手才提交；Fast 的短尾迹从右向左快速运动，大小与明暗轻微错开；白球以圆心放大，Ultra 左端圆角与渐变同步过渡；同时开启时以 Fast 为主，减少动态效果时保持静态。' },
    { title: '直观的操作名称', description: '快捷菜单与面板显示选择技能、新建对话、选择模型、推理强度和查看状态，仅帮助保留 /help 提示。' },
    { title: '聚焦聊天与技能', description: '移除 Worktree 任务入口与创建、重试能力，既有会话和聊天草稿继续保留。' },
    { title: '保持输入连续', description: '保留问题和附件，点击面板外直接收起且不抢走新目标焦点，Esc 或关闭按钮返回输入框；键盘候选选择、手机和窄 Agent 侧栏继续可用。' },
  ],
}
