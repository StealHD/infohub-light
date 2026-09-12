import { useEffect, useState } from 'react'
import { Button, Checkbox, EmptyState, Input, Label, LoadingState, Modal, RefreshButton, StatusNotice, TextField } from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import { AgentSessionRow } from './AgentSessionRow'
import { useAgentSessionDirectory } from './useAgentSessionDirectory'

export function AgentSessionHistory({ open, onOpenChange, chat, userId, onOpen }: {
  open: boolean; onOpenChange: (open: boolean) => void; chat: OpenClawChatController; userId: string; onOpen: (session: OpenClawWorkspaceSession) => Promise<boolean>
}) {
  const [search, setSearch] = useState('')
  const [archived, setArchived] = useState(false)
  const [offsets, setOffsets] = useState([0])
  const directory = useAgentSessionDirectory(chat, userId, open, search, archived, offsets.at(-1))
  useEffect(() => chat.workspace.subscribe((event) => { if (event === 'sessions.changed') setOffsets([0]) }), [chat.workspace])
  return <Modal isOpen={open} onOpenChange={onOpenChange}>
    <Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>全部会话</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid min-w-0 gap-3">
        <TextField value={search} onChange={(value) => { setSearch(value); setOffsets([0]) }}><Label>搜索会话</Label><Input placeholder="搜索标题或会话" /></TextField>
        <Checkbox isSelected={archived} onChange={(value) => { setArchived(value); setOffsets([0]) }}><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><Checkbox.Content><Label>查看已归档会话</Label></Checkbox.Content></Checkbox>
        {directory.error && <StatusNotice title="会话暂不可用" status="warning">{directory.error}<RefreshButton onPress={directory.refresh} pending={directory.loading} label="重试" /></StatusNotice>}
        {!directory.available && <StatusNotice title="会话目录不可用" status="warning">连接支持会话目录的 Gateway 后重试。</StatusNotice>}
        {directory.loading && !directory.page ? <LoadingState label="正在读取历史会话" rows={3} /> : <div aria-busy={directory.loading} className="quiet-scroll-region grid max-h-[50dvh] min-w-0 gap-1 overflow-y-auto">
          {directory.page?.sessions.map((session) => <AgentSessionRow workspace={chat.workspace} key={session.key} session={session} current={session.key === chat.sessionKey} disabled={session.key !== chat.sessionKey && (chat.isRunning || chat.runtimeUpdating)} onOpen={(target) => { void onOpen(target).then((success) => { if (success) onOpenChange(false) }) }} />)}
          {directory.page?.sessions.length === 0 && <EmptyState title="没有匹配的会话" description="尝试其他关键词或切换归档筛选。" />}
        </div>}
      </div></Modal.Body>
      <Modal.Footer>
        <Button variant="ghost" isDisabled={offsets.length === 1 || directory.loading} onPress={() => setOffsets((values) => values.slice(0, -1))}>上一页</Button>
        <Button variant="secondary" isDisabled={!directory.page?.hasMore || directory.loading} onPress={() => { const next = directory.page?.nextOffset; if (next !== undefined) setOffsets((values) => [...values, next]) }}>下一页</Button>
        <Button variant="ghost" onPress={() => onOpenChange(false)}>关闭</Button>
      </Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}
