import type { ChangelogEntry } from './changelogTypes'

export const automationsUnifiedEntry: ChangelogEntry = {
  date: '2026-09-08', title: 'Automations 统一分析与灵活触发',
  summary: '用一段完整描述表达关键词、语义和排除要求，选择 OpenClaw 模型，按新增内容、条数或时间执行综合分析。',
  items: [
    { title: '一个任务描述', description: '新建自动化统一填写完整要求、订阅来源、模型和通知目标，不再选择关键词或语义模式。保存后测试并确认启用。' },
    { title: '四种触发方式', description: '支持每条到达、累计条数、固定间隔以及每天或每周固定时间；累计条数可设置最长等待，空周期不调用模型。' },
    { title: '综合判断与可信通知', description: '大批量分段分析后统一结论，一批最多发送一条含原文依据的通知。页面显示待处理数量、下次处理时间和分析进度；测试明确区分排队、分析、模型不可用及格式校验失败。' },
    { title: '自动读取模型目录', description: '读取 OpenClaw 已配置且允许独立分析的模型与推理选项；区分加载中、未接入、过期和无授权状态，接入后自动更新选择器。模型失效时保留待处理内容，刷新或更换模型后恢复。旧规则通过 global 40 显式升级并重新确认。' },
  ],
}
