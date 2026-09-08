import { useState } from 'react'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import type { NotificationService, Subscription } from '../../api/types'
import { Checkbox, FormSelect, Input, Label, TextArea, TextField } from '../../design-system'
import { InformationTriggerFields } from './InformationTriggerFields'
import { InformationModelFields } from './InformationModelFields'

export function InformationRuleFields({ value, onChange, sources, targets, disabled }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void
  sources: (Subscription & { source_platform?: string })[]; targets: NotificationService[]; disabled: boolean
}) {
  const [search, setSearch] = useState('')
  return <div className="grid gap-4">
    <TextField isDisabled={disabled}><Label>任务名称</Label><Input value={value.name} maxLength={100}
      onChange={(event) => onChange({ ...value, name: event.target.value })} /></TextField>
    <TextField isDisabled={disabled}><Label>完整任务描述</Label><TextArea value={value.requirement} maxLength={24000}
      placeholder="说明关注什么、关键词及排除要求，以及符合要求时希望收到的总结。"
      onChange={(event) => onChange({ ...value, requirement: event.target.value })} /></TextField>
    <fieldset className="grid gap-3"><legend className="type-section-title">订阅源</legend>
      <TextField><Label>搜索订阅</Label><Input value={search} onChange={(event) => setSearch(event.target.value)} /></TextField>
      {sources.filter((source) => source.enabled && `${source.source_platform || source.source_type} ${source.source_display_name}`.toLowerCase().includes(search.toLowerCase())).map((source) =>
        <Checkbox key={source.source_id} isDisabled={disabled} isSelected={value.source_ids.includes(source.source_id)}
          onChange={(checked) => onChange({ ...value, source_ids: checked ? [...value.source_ids, source.source_id] : value.source_ids.filter((id) => id !== source.source_id) })}>
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
            <Label>{(source.source_platform || source.source_type || '').replace(/^(x|twitter)$/, 'X')} · {source.source_display_name || '订阅来源'}</Label>
          </Checkbox.Content>
        </Checkbox>)}
      {!sources.some((source) => source.enabled) && <a href="/subscriptions" className="type-body underline">先添加或启用订阅</a>}
      {sources.some((source) => value.source_ids.includes(source.source_id) && source.notify_on_new_items) && <p className="type-meta text-muted">所选来源已开启全部新内容通知，它会独立发送；可在订阅设置关闭。</p>}
      <p className="type-meta text-muted">仅收录内容不会进入模型。</p>
    </fieldset>
    <InformationModelFields value={value} onChange={onChange} disabled={disabled} />
    <fieldset className="grid gap-3"><legend className="type-section-title">触发</legend>
      <InformationTriggerFields value={value.trigger} disabled={disabled} onChange={(trigger) => onChange({ ...value, trigger })} />
    </fieldset>
    <FormSelect label="通知目标" value={value.target_id || ''} isDisabled={disabled}
      options={targets.map((target) => ({ id: target.id, label: target.name, description: target.available ? '可用' : '请先在通知设置中修复' }))}
      onChange={(target_id) => onChange({ ...value, target_id })} />
  </div>
}
