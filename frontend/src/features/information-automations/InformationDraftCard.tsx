import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, RefreshButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { InformationRuleEditor } from './InformationRuleEditor'

export default function InformationDraftCard({ ruleId }: { ruleId: string }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const key = ['information-rule', userId, ruleId]
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => api.informationRule(ruleId, signal), retry: false })
  const access = useQuery({ queryKey: ['agent-connection', userId], queryFn: ({ signal }) => api.agentConnection(signal) })
  return <Card variant="secondary" className="my-4 p-4" aria-label="服务端提醒确认卡">
    <Card.Title>{query.data?.config.name || '提醒草稿'}</Card.Title>
    <Card.Description>规则内容从当前账号的服务端读取。聊天文本不会直接启用提醒。</Card.Description>
    <RefreshButton pending={query.isFetching} aria-label="刷新确认卡" onPress={() => query.refetch()} />
    {query.isPending && <p role="status">正在读取可信规则…</p>}
    {query.isError && <p role="alert">当前账号无法读取此草稿，请从个人提醒列表检查。</p>}
    {query.data && <InformationRuleEditor key={`${userId}:${ruleId}`} rule={query.data} canMutate={Boolean(access.data?.can_chat) && !query.isError}
      onSaved={async (saved) => { cache.setQueryData(key, saved); await cache.invalidateQueries({ queryKey: ['information-rules', userId] }) }} />}
  </Card>
}
