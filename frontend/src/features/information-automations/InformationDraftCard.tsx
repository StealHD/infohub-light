import { useEffect } from 'react'
import { lazy, Suspense, useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, RefreshButton } from '../../design-system'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { useInformationContext } from './useInformationContext'
import { InformationTestPanel } from './InformationTestPanel'
import { useInformationTests } from './useInformationTests'
const InformationRuleEditor = lazy(() => import('./InformationRuleEditor').then((module) => ({ default: module.InformationRuleEditor })))

export default function InformationDraftCard({ ruleId }: { ruleId: string }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const tests = useInformationTests()
  const restore = tests.restore
  const [dirty, setDirty] = useState(false)
  const [showTest, setShowTest] = useState(false)
  const handleDraftChange = useCallback((_config: InformationRuleConfig, changed: boolean) => setDirty(changed), [])
  const key = ['information-rule', userId, ruleId]
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => api.informationRule(ruleId, signal), retry: false })
  const access = useQuery({ queryKey: ['agent-connection', userId], queryFn: ({ signal }) => api.agentConnection(signal) })
  useEffect(() => { if (query.data) void restore(query.data.id, query.data.version) }, [restore, query.data])
  return <Card variant="secondary" className="my-4 p-4" aria-label="服务端提醒确认卡">
    <Card.Title>{query.data?.config.name || '提醒草稿'}</Card.Title>
    <Card.Description>规则内容从当前账号的服务端读取。聊天文本不会直接启用提醒。</Card.Description>
    <RefreshButton pending={query.isFetching} aria-label="刷新确认卡" onPress={() => query.refetch()} />
    {query.isPending && <p role="status">正在读取可信规则…</p>}
    {query.isError && <p role="alert">当前账号无法读取此草稿，请从个人提醒列表检查。</p>}
    {query.data && <><Suspense fallback={<p role="status">正在加载任务详情…</p>}><InformationRuleEditor key={`${userId}:${ruleId}`} rule={query.data} canMutate={Boolean(access.data?.can_chat) && !query.isError}
      onDraftChange={handleDraftChange}
      onSaved={async (saved) => { cache.setQueryData(key, saved); await cache.invalidateQueries({ queryKey: ['information-rules', userId] }) }} /></Suspense>
      <Button className="mt-3" variant="secondary" aria-expanded={showTest} onPress={() => setShowTest((value) => !value)}>{showTest ? '收起测试' : '测试已保存规则'}</Button>
      {showTest && <div className="mt-4 border-t border-separator pt-4"><InformationTestPanel rule={query.data} dirty={dirty} canMutate={Boolean(access.data?.can_chat) && !query.isError}
        session={tests.session(ruleId, query.data.version)} onSelect={(value) => tests.select(ruleId, query.data!.version, value)} onStart={() => tests.start(ruleId, query.data!.version)} /></div>}
    </>}
  </Card>
}
