import { useState } from 'react'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import type { NotificationService, Subscription } from '../../api/types'
import { Checkbox, FormSelect, Input, Label, TextArea, TextField } from '../../design-system'
import { linesToTerms } from './informationRuleModel'

export function InformationRuleFields({ value, onChange, sources, targets, disabled }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void
  sources: Subscription[]; targets: NotificationService[]; disabled: boolean
}) {
  return <div className="grid gap-4">
    <TextField isDisabled={disabled}><Label>提醒名称</Label><Input value={value.name} maxLength={100}
      onChange={(event) => onChange({ ...value, name: event.target.value })} /></TextField>
    <FormSelect label="判断方式" value={value.mode} isDisabled={disabled}
      options={[{ id: 'keyword', label: '关键词' }, { id: 'semantic', label: '语义判断' }]}
      onChange={(mode) => onChange({ ...value, mode: mode as InformationRuleConfig['mode'] })} />
    <fieldset className="grid gap-2"><legend className="type-control">订阅来源</legend>
      {sources.filter((source) => source.enabled).map((source) => <Checkbox key={source.source_id}
        isDisabled={disabled} isSelected={value.source_ids.includes(source.source_id)}
        onChange={(checked) => onChange({ ...value, source_ids: checked
          ? [...value.source_ids, source.source_id] : value.source_ids.filter((id) => id !== source.source_id) })}>
        <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><Checkbox.Content>
          <Label>{source.source_display_name || source.source_type || '订阅来源'}</Label>
        </Checkbox.Content>
      </Checkbox>)}
      {!sources.some((source) => source.enabled) && <a href="/subscriptions" className="type-body underline">先添加或启用订阅</a>}
    </fieldset>
    {value.mode === 'keyword' ? (['all', 'any', 'exclude'] as const).map((kind) => <TextField key={kind} isDisabled={disabled}>
      <Label>{{ all: '包含全部（每行一个）', any: '包含任意（每行一个）', exclude: '排除（每行一个）' }[kind]}</Label>
      <TermInput values={value.conditions[kind]} onChange={(terms) => onChange({ ...value,
        conditions: { ...value.conditions, [kind]: terms } })} />
    </TextField>) : <TextField isDisabled={disabled}><Label>完整判断要求</Label><TextArea value={value.requirement} maxLength={16000}
      onChange={(event) => onChange({ ...value, requirement: event.target.value })} /></TextField>}
    <FormSelect label="通知目标" value={value.target_id || ''} isDisabled={disabled}
      options={targets.map((target) => ({ id: target.id, label: target.name,
        description: target.available ? '可用' : '尚未就绪，启用前需在通知设置中修复' }))}
      onChange={(target_id) => onChange({ ...value, target_id })} />
  </div>
}

function TermInput({ values, onChange }: { values: string[]; onChange: (terms: string[]) => void }) {
  const [text, setText] = useState(values.join('\n'))
  const canonical = values.join('\n')
  const displayed = linesToTerms(text).join('\n') === canonical ? text : canonical
  return <TextArea value={displayed} onChange={(event) => { setText(event.target.value); onChange(linesToTerms(event.target.value)) }} />
}
