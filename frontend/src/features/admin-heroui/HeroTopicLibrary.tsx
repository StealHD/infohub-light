import { useMemo, useState } from 'react'

import { Button, Chip, Icons, Input, Label, TextField } from '../../design-system'

function normalizeTopics(values: string[]) {
  const seen = new Set<string>()
  return values.map((value) => value.trim().replace(/^#+/, '').trim()).filter((value) => {
    const key = value.toLocaleLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function HeroTopicLibrary({ topics, pending, onSave }: { topics: string[]; pending: boolean; onSave: (topics: string[]) => void }) {
  const source = useMemo(() => normalizeTopics(topics), [topics])
  const [draft, setDraft] = useState(source)
  const [newTopic, setNewTopic] = useState('')
  const [search, setSearch] = useState('')
  const dirty = JSON.stringify(draft) !== JSON.stringify(source)
  const visible = draft.filter((topic) => topic.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))

  function add() {
    const next = normalizeTopics([...draft, newTopic])
    if (next.length === draft.length) return
    setDraft(next)
    setNewTopic('')
  }

  return <div className="grid gap-4">
    <p className="type-body text-muted">新增或删除只影响未来候选和 AI 分类；已有订阅与历史内容不会被改写。</p>
    <div className="grid gap-3 min-[720px]:grid-cols-[1fr_auto_1fr]">
      <TextField fullWidth value={newTopic} onChange={setNewTopic}><Label>新增主题</Label><Input maxLength={40} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); add() } }} /></TextField>
      <Button className="self-end" isDisabled={!newTopic.trim() || pending} onPress={add}>添加主题</Button>
      <TextField fullWidth value={search} onChange={setSearch}><Label>搜索主题</Label><Input /></TextField>
    </div>
    <div className="flex min-h-10 flex-wrap gap-2">
      {visible.map((topic) => <Chip key={topic} variant="soft"><Chip.Label>{topic}</Chip.Label><button type="button" aria-label={`删除 ${topic}`} disabled={pending} onClick={() => setDraft((current) => current.filter((item) => item !== topic))}><Icons.X size={13} /></button></Chip>)}
      {!visible.length && <span className="type-body text-muted">没有匹配的主题。</span>}
    </div>
    <div className="flex gap-2"><Button size="sm" isDisabled={!dirty || pending} onPress={() => onSave(draft)}>{pending ? '保存中…' : '保存更改'}</Button><Button size="sm" variant="ghost" isDisabled={!dirty || pending} onPress={() => setDraft(source)}>撤销更改</Button></div>
  </div>
}
