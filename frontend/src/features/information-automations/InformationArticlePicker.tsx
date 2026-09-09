import { useState } from 'react'
import type { FeedItem } from '../../api/types'
import { Button, Checkbox, Icons, Modal, SearchField } from '../../design-system'
import type { TestArticleSelection } from './useInformationTests'

const pageSize = 10

export function InformationArticlePicker({ open, articles, value, onClose, onConfirm }: {
  open: boolean; articles: FeedItem[]; value: TestArticleSelection[]; onClose: () => void; onConfirm: (value: TestArticleSelection[]) => void
}) {
  const [draft, setDraft] = useState(value)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const filtered = articles.filter((item) => item.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const rows = filtered.slice(page * pageSize, (page + 1) * pageSize)
  const reset = () => { setDraft(value); setSearch(''); setPage(0) }
  return <Modal isOpen={open} onOpenChange={(next) => { if (!next) onClose() }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开测试文章选择</Modal.Trigger><Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
    <Modal.Header><Modal.Heading>选择测试文章</Modal.Heading></Modal.Header>
    <Modal.Body><div className="grid gap-3">
      <SearchField aria-label="搜索测试文章" value={search} onChange={(next) => { setSearch(next); setPage(0) }} fullWidth>
        <SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon><SearchField.Input placeholder="搜索文章标题" /><SearchField.ClearButton /></SearchField.Group>
      </SearchField>
      <p className="type-meta text-muted">已选 {draft.length} 篇；仅显示当前最新信息流中符合任务来源的文章。</p>
      {rows.map((item) => <Checkbox key={item.id} isSelected={draft.some((selected) => selected.id === item.id)}
        isDisabled={!draft.some((selected) => selected.id === item.id) && draft.length >= 1000}
        onChange={(checked) => setDraft((current) => checked ? [...current, { id: item.id, title: item.title }] : current.filter((selected) => selected.id !== item.id))}>
        <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{item.title}</Checkbox.Content>
      </Checkbox>)}
      {!rows.length && <p className="type-body text-muted">没有匹配的可测试文章。</p>}
      {filtered.length > pageSize && <div className="flex items-center justify-between gap-2"><Button size="sm" variant="ghost" isDisabled={page === 0} onPress={() => setPage((value) => value - 1)}>上一页</Button>
        <span className="type-meta">{page + 1} / {Math.ceil(filtered.length / pageSize)}</span><Button size="sm" variant="ghost" isDisabled={(page + 1) * pageSize >= filtered.length} onPress={() => setPage((value) => value + 1)}>下一页</Button></div>}
    </div></Modal.Body>
    <Modal.Footer><Button variant="ghost" onPress={() => { reset(); onClose() }}>取消</Button><Button onPress={() => onConfirm(draft)}>确认选择</Button></Modal.Footer>
  </Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
}
