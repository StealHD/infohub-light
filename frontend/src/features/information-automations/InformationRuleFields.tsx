import { useState } from 'react'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import type { NotificationService, Subscription } from '../../api/types'
import { Button, FormSelect, Icons, Input, Label, TextArea, TextField } from '../../design-system'
import { InformationTriggerFields } from './InformationTriggerFields'
import { InformationModelFields } from './InformationModelFields'
import { InformationSourcePicker } from './InformationSourcePicker'
import { triggerLabel } from './informationRuleModel'

export function InformationRuleFields({ value, onChange, sources, targets, disabled }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void
  sources: (Subscription & { source_platform?: string })[]; targets: NotificationService[]; disabled: boolean
}) {
  const [open, setOpen] = useState<'trigger' | null>(null)
  const toggleTrigger = () => setOpen((current) => current === 'trigger' ? null : 'trigger')
  return <div className="grid gap-4">
    <TextField isDisabled={disabled}><Label>任务名称</Label><Input value={value.name} maxLength={100}
      onChange={(event) => onChange({ ...value, name: event.target.value })} /></TextField>
    <TextField isDisabled={disabled}><Label>完整任务描述</Label><TextArea value={value.requirement} maxLength={24000}
      placeholder="说明关注什么、关键词及排除要求，以及符合要求时希望收到的总结。"
      onChange={(event) => onChange({ ...value, requirement: event.target.value })} /></TextField>
    <InformationSourcePicker value={value.source_ids} sources={sources} disabled={disabled}
      onChange={(source_ids) => onChange({ ...value, source_ids })} />
    <section className="border-t border-separator pt-3"><InformationModelFields value={value} onChange={onChange} disabled={disabled} compactHeading /></section>
    <section className="border-t border-separator pt-3"><Button variant="ghost" className="w-full justify-between" aria-expanded={open === 'trigger'} onPress={toggleTrigger}>
      <span className="min-w-0 text-left"><span className="type-control block">触发与通知</span><span className="type-meta block truncate text-muted">{triggerLabel(value.trigger)} · {targets.find((target) => target.id === value.target_id)?.name || '未选通知目标'}</span></span><Icons.ChevronDown size={15} aria-hidden="true" />
    </Button>{open === 'trigger' && <div className="mt-3 grid gap-4"><InformationTriggerFields value={value.trigger} disabled={disabled} onChange={(trigger) => onChange({ ...value, trigger })} />
      <FormSelect label="通知目标" value={value.target_id || ''} isDisabled={disabled} options={targets.map((target) => ({ id: target.id, label: target.name, description: target.available ? '可用' : '请先在通知设置中修复' }))}
        onChange={(target_id) => onChange({ ...value, target_id })} /></div>}</section>
  </div>
}
