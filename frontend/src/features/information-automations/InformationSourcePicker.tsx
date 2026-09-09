import { useState } from 'react'
import type { Subscription } from '../../api/types'
import { Button, Checkbox, Icons, Modal, SearchField } from '../../design-system'
import { informationSourceLabel } from './informationSourceLabel'

const pageSize = 10

export function InformationSourcePicker({ value, sources, disabled, onChange }: {
  value: string[]; sources: (Subscription & { source_platform?: string })[]; disabled: boolean; onChange: (value: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string[]>(value)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const enabled = sources.filter((source) => source.enabled)
  const filtered = enabled.filter((source) => informationSourceLabel(source).toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const rows = filtered.slice(page * pageSize, (page + 1) * pageSize)
  const selected = value.map((id) => enabled.find((source) => source.source_id === id)).filter(Boolean) as typeof enabled
  const summary = selected.length ? `${informationSourceLabel(selected[0])}${selected.length > 1 ? ` 等 ${selected.length} 个` : ''}` : '尚未选择订阅源'
  const begin = () => { setDraft(value); setSearch(''); setPage(0); setOpen(true) }
  return <>
    <div className="grid gap-2"><p className="type-control">订阅源</p><p className="type-meta break-words text-muted">{summary}</p>
      <Button variant="secondary" isDisabled={disabled || !enabled.length} onPress={begin}><Icons.ListChecks size={15} />选择订阅源</Button>
      {!enabled.length && <a href="/subscriptions" className="type-body underline">先添加或启用订阅</a>}
      {selected.some((source) => source.notify_on_new_items) && <p className="type-meta text-muted">部分来源已开启全部新内容通知，将独立发送。</p>}
    </div>
    <Modal isOpen={open} onOpenChange={(next) => { if (!next) setOpen(false) }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开订阅源选择</Modal.Trigger><Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>选择订阅源</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid gap-3">
        <SearchField aria-label="搜索可用订阅源" value={search} onChange={(next) => { setSearch(next); setPage(0) }} fullWidth>
          <SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon><SearchField.Input placeholder="搜索平台或名称" /><SearchField.ClearButton /></SearchField.Group>
        </SearchField>
        <p className="type-meta text-muted">已选 {draft.length} / 50</p>
        {rows.map((source) => <Checkbox key={source.source_id} isSelected={draft.includes(source.source_id)}
          isDisabled={!draft.includes(source.source_id) && draft.length >= 50} onChange={(checked) => setDraft((current) => checked ? [...current, source.source_id] : current.filter((id) => id !== source.source_id))}>
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{informationSourceLabel(source)}</Checkbox.Content>
        </Checkbox>)}
        {!rows.length && <p className="type-body text-muted">没有匹配的可用订阅源。</p>}
        {filtered.length > pageSize && <div className="flex items-center justify-between gap-2"><Button size="sm" variant="ghost" isDisabled={page === 0} onPress={() => setPage((value) => value - 1)}>上一页</Button>
          <span className="type-meta">{page + 1} / {Math.ceil(filtered.length / pageSize)}</span><Button size="sm" variant="ghost" isDisabled={(page + 1) * pageSize >= filtered.length} onPress={() => setPage((value) => value + 1)}>下一页</Button></div>}
      </div></Modal.Body>
      <Modal.Footer><Button variant="ghost" onPress={() => setOpen(false)}>取消</Button><Button onPress={() => { onChange(draft); setOpen(false) }}>确认选择</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
  </>
}
