import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Button, Tabs, TextField, Input, Label, RefreshButton, FormSelect } from '../../design-system'
import { queryKeys } from '../../api/queryKeys'
import { useAgentConnectionContext } from './AgentConnectionContext'
import { PersonalAgentConnection } from './PersonalAgentConnection'
import { AccessRequestRow } from './AccessRequestRow'

function Requests() {
  const { api, userId } = useAgentConnectionContext()
  const [group, setGroup] = useState('pending')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['agent-access', userId, group, search, page],
    queryFn: async ({ signal }) => {
      const result = await api.agentAccessRequests(group, search, page, signal)
      return result
    }, refetchInterval: 5000 })
  return <div className="grid gap-3 pt-4 text-foreground">
    <div className="flex flex-wrap items-end gap-3">
      <FormSelect label="申请状态" value={group} onChange={(value) => { setGroup(value); setPage(1) }} options={[
        { id: 'pending', label: '待审核' }, { id: 'processing', label: '处理中' }, { id: 'processed', label: '已处理' }]} />
      <TextField value={search} onChange={(value) => { setSearch(value); setPage(1) }}><Label>搜索申请人</Label><Input placeholder="姓名或用户名" /></TextField>
      <RefreshButton pending={query.isFetching} onPress={() => query.refetch()} />
    </div>
    {query.isError && <p role="alert" className="type-body">读取申请失败，请刷新重试；若尚未升级，请先完成接入申请数据库迁移。</p>}
    {query.isPending && <p role="status" className="type-body">正在读取申请…</p>}
    {query.data?.items.map(row => <AccessRequestRow key={row.id} row={row} refresh={() => query.refetch()} />)}
    {query.data?.total === 0 && <p className="type-body text-muted">暂无相关申请</p>}
    <div className="flex items-center gap-2">
      <Button variant="ghost" isDisabled={page === 1 || query.isFetching} onPress={() => setPage(page-1)}>上一页</Button>
      <span className="type-meta">第 {page} 页 · 共 {query.data?.total ?? 0} 条</span>
      <Button variant="ghost" isDisabled={!query.data || page*20 >= query.data.total || query.isFetching} onPress={() => setPage(page+1)}>下一页</Button>
    </div>
  </div>
}

export function AgentAccessPanel() {
  const { api, userId } = useAgentConnectionContext()
  const query = useQuery({ queryKey: queryKeys.agentConnection(userId), queryFn: ({ signal }) => api.agentConnection(signal) })
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'requests' ? 'requests' : 'personal'
  const count = useQuery({ queryKey: ['agent-access-count', userId], enabled: Boolean(query.data?.can_manage_setup),
    queryFn: ({ signal }) => api.agentAccessRequests('pending', '', 1, signal), refetchInterval: 10000 })
  if (query.isPending) return <p role="status" className="type-body">正在读取接入状态…</p>
  if (!query.data?.can_manage_setup) return <PersonalAgentConnection />
  return <Tabs selectedKey={tab} onSelectionChange={(key) => setParams(key === 'requests' ? { tab: 'requests' } : {})}>
    <Tabs.List aria-label="Agent 接入管理">
      <Tabs.Tab id="personal">我的 Agent<Tabs.Indicator /></Tabs.Tab>
      <Tabs.Tab id="requests">接入申请{count.data?.pending_count ? ` (${count.data.pending_count})` : ''}<Tabs.Indicator /></Tabs.Tab>
    </Tabs.List>
    <Tabs.Panel id="personal" className="pt-4"><PersonalAgentConnection /></Tabs.Panel>
    <Tabs.Panel id="requests"><Requests /></Tabs.Panel>
  </Tabs>
}
