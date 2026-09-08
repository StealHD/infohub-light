import { useState } from 'react'
import type { InformationTrigger } from '../../api/informationAutomationService'
import { Checkbox, FormSelect, Input, Label, TextField } from '../../design-system'

export function InformationTriggerFields({ value, onChange, disabled }: {
  value: InformationTrigger; onChange: (value: InformationTrigger) => void; disabled: boolean
}) {
  const [unit, setUnit] = useState<'minute' | 'hour' | 'day'>(() => value.interval_seconds % 86400 === 0 ? 'day' : value.interval_seconds % 3600 === 0 ? 'hour' : 'minute')
  const scale = { minute: 60, hour: 3600, day: 86400 }[unit]
  return <div className="grid gap-3">
    <FormSelect label="触发方式" value={value.kind} isDisabled={disabled}
      options={[{ id: 'each', label: '每条到达' }, { id: 'count', label: '累计条数' },
        { id: 'interval', label: '固定间隔' }, { id: 'calendar', label: '固定时间' }]}
      onChange={(kind) => onChange({ ...value, kind: kind as InformationTrigger['kind'] })} />
    {value.kind === 'count' && <>
      <TextField isDisabled={disabled}><Label>累计多少条后分析</Label><Input type="number" min={2} max={10000} value={String(value.count)}
        onChange={(event) => onChange({ ...value, count: Number(event.target.value) })} /></TextField>
      <Checkbox isDisabled={disabled} isSelected={value.max_wait_seconds !== null}
        onChange={(checked) => onChange({ ...value, max_wait_seconds: checked ? 3600 : null })}>
        <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>设置最长等待时间</Checkbox.Content>
      </Checkbox>
      {value.max_wait_seconds !== null && <TextField isDisabled={disabled}><Label>最长等待（分钟）</Label>
        <Input type="number" min={1} max={10080} value={String(value.max_wait_seconds / 60)}
          onChange={(event) => onChange({ ...value, max_wait_seconds: Number(event.target.value) * 60 })} /></TextField>}
    </>}
    {value.kind === 'interval' && <>
      <TextField isDisabled={disabled}><Label>处理间隔</Label>
        <Input type="number" min={1} max={604800 / scale} value={String(value.interval_seconds / scale)}
          onChange={(event) => onChange({ ...value, interval_seconds: Number(event.target.value) * scale })} /></TextField>
      <FormSelect label="间隔单位" value={unit} isDisabled={disabled}
        options={[{ id: 'minute', label: '分钟' }, { id: 'hour', label: '小时' }, { id: 'day', label: '天' }]}
        onChange={(id) => {
          const next = id as typeof unit
          setUnit(next); onChange({ ...value, interval_seconds: Math.min(604800, value.interval_seconds / scale * { minute: 60, hour: 3600, day: 86400 }[next]) })
        }} />
    </>}
    {value.kind === 'calendar' && <>
      <FormSelect label="重复" isDisabled={disabled} value={value.weekdays.length ? 'weekly' : 'daily'}
        options={[{ id: 'daily', label: '每天' }, { id: 'weekly', label: '每周' }]}
        onChange={(repeat) => onChange({ ...value, weekdays: repeat === 'weekly' ? [0] : [] })} />
      {!!value.weekdays.length && <div className="flex flex-wrap gap-3">{['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((label, day) =>
        <Checkbox key={day} isDisabled={disabled || (value.weekdays.length === 1 && value.weekdays.includes(day))}
          isSelected={value.weekdays.includes(day)} onChange={(checked) => onChange({ ...value,
            weekdays: checked ? [...value.weekdays, day].sort() : value.weekdays.filter((entry) => entry !== day) })}>
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{label}</Checkbox.Content>
        </Checkbox>)}</div>}
      <TextField isDisabled={disabled}><Label>时间</Label><Input type="time" value={value.time}
        onChange={(event) => onChange({ ...value, time: event.target.value })} /></TextField>
      <TextField isDisabled={disabled}><Label>时区</Label><Input value={value.timezone}
        onChange={(event) => onChange({ ...value, timezone: event.target.value })} /></TextField>
    </>}
    <p className="type-meta text-muted">只处理新增内容；没有新内容时不调用模型。到达时间取决于订阅的获取周期。</p>
  </div>
}
