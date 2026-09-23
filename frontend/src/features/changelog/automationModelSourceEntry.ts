import type { ChangelogEntry } from './changelogTypes'

export const automationModelSourceEntry: ChangelogEntry = {
  date: '2026-09-23',
  title: '自动化模型显示来源',
  summary: '自动化复用对话中的模型与推理选择样式，模型列表和已选模型显示来源。',
  items: [
    { title: '模型来源可见', description: '自动化新建和编辑表单使用同款模型弹层与推理滑杆；模型列表显示来源，选中后显示来源与名称。保存时仍使用原有完整模型 ID。' },
  ],
}
