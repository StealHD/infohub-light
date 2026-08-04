import { useMemo, useState } from 'react'

import { Button, Input, Label, RemovableTag, TextField } from '../../design-system'
import { normalizeTopics } from './settingsFetchingModel'

export function SettingsTopicLibrary({ topics, draft, pending, onDraftChange, onSave }: {
  topics: string[]
  draft: string[]
  pending: boolean
  onDraftChange: (topics: string[]) => void
  onSave: (topics: string[]) => void
}) {
  const source = useMemo(() => normalizeTopics(topics), [topics])
  const normalizedDraft = useMemo(() => normalizeTopics(draft), [draft])
  const [newTopic, setNewTopic] = useState('')
  const [search, setSearch] = useState('')
  const dirty = JSON.stringify(normalizedDraft) !== JSON.stringify(source)
  const visible = normalizedDraft.filter((topic) => topic.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))

  function add() {
    const next = normalizeTopics([...normalizedDraft, newTopic])
    if (next.length === normalizedDraft.length) return
    onDraftChange(next)
    setNewTopic('')
  }

  return <div className="grid gap-4">
    <div className="grid gap-3 min-[720px]:grid-cols-[1fr_auto_1fr]">
      <TextField fullWidth value={newTopic} onChange={setNewTopic}><Label>新增主题</Label><Input maxLength={40} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); add() } }} /></TextField>
      <Button className="self-end" isDisabled={!newTopic.trim() || pending} onPress={add}>添加主题</Button>
      <TextField fullWidth value={search} onChange={setSearch}><Label>搜索主题</Label><Input /></TextField>
    </div>
    <div className="flex min-h-10 flex-wrap gap-2">
      {visible.map((topic) => <RemovableTag key={topic} label={topic} disabled={pending} onRemove={() => onDraftChange(normalizedDraft.filter((item) => item !== topic))} />)}
      {!visible.length && <span className="type-body text-muted">没有匹配的主题。</span>}
    </div>
    <div className="flex flex-wrap gap-2"><Button size="sm" isDisabled={!dirty || pending} onPress={() => onSave(normalizedDraft)}>{pending ? '保存中…' : '保存更改'}</Button><Button size="sm" variant="ghost" isDisabled={!dirty || pending} onPress={() => onDraftChange(source)}>撤销更改</Button></div>
  </div>
}
