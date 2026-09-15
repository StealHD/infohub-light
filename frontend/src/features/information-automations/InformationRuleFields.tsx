import type { InformationRuleConfig } from '../../api/informationAutomationService'
import type { NotificationService, Subscription } from '../../api/types'
import { FormSelect, Input, Label, Switch, TextArea, TextField } from '../../design-system'
import { InformationTriggerFields } from './InformationTriggerFields'
import { InformationModelFields } from './InformationModelFields'
import { InformationSourcePicker } from './InformationSourcePicker'

export function InformationRuleFields({ value, onChange, sources, targets, disabled }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void
  sources: (Subscription & { source_platform?: string })[]; targets: NotificationService[]; disabled: boolean
}) {
  return <div className="grid gap-4">
    <TextField isDisabled={disabled}><Label>任务名称</Label><Input value={value.name} maxLength={100}
      onChange={(event) => onChange({ ...value, name: event.target.value })} /></TextField>
    <TextField isDisabled={disabled}><Label>完整任务描述</Label><TextArea value={value.requirement} maxLength={24000}
      placeholder="说明关注什么、关键词及排除要求，以及符合要求时希望收到的总结。"
      onChange={(event) => onChange({ ...value, requirement: event.target.value })} /></TextField>
    <InformationSourcePicker value={value.source_ids} sources={sources} disabled={disabled}
      onChange={(source_ids) => onChange({ ...value, source_ids })} />
    <section className="border-t border-separator pt-3"><InformationModelFields value={value} onChange={onChange} disabled={disabled} compactHeading /></section>
    <section className="grid gap-4 border-t border-separator pt-3"><h3 className="type-control">触发与通知</h3>
      <InformationTriggerFields value={value.trigger} disabled={disabled} onChange={(trigger) => onChange({ ...value, trigger })} />
      <Switch isSelected={value.notification_enabled !== false} isDisabled={disabled} onChange={(notification_enabled) => onChange({ ...value, notification_enabled })}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>命中时发送通知</Switch.Content>
      </Switch>
      {value.notification_enabled !== false && <FormSelect label="通知目标" value={value.target_id || ''} isDisabled={disabled} options={targets.map((target) => ({ id: target.id, label: target.name, description: target.available ? '可用' : '请先在通知设置中修复' }))}
        onChange={(target_id) => onChange({ ...value, target_id })} />}</section>
  </div>
}
