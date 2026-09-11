import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule } from '../../api/informationAutomationService'
import { Button, Card, StableAsyncButton, StatusIndicator } from '../../design-system'
import { InformationArticlePicker } from './InformationArticlePicker'
import { judgmentLabels } from './informationRuleModel'
import { previewStatus } from './previewStatus'
import { useInformationContext } from './useInformationContext'
import { informationTestStatusLabel, type InformationTestSession, type TestArticleSelection } from './useInformationTests'

export function InformationTestPanel({ rule, dirty, canMutate, session, onSelect, onStart }: {
  rule: InformationRule; dirty: boolean; canMutate: boolean; session: InformationTestSession
  onSelect: (value: TestArticleSelection[]) => void; onStart: () => Promise<void>
}) {
  const { api, userId } = useInformationContext()
  const [picker, setPicker] = useState(false)
  const [showReason, setShowReason] = useState(false)
  const [showItems, setShowItems] = useState(false)
  const feed = useQuery({ queryKey: ['information-test-feed', userId], queryFn: ({ signal }) => api.latestFeed(signal) })
  const articles = (feed.data?.items || []).filter((item) => [item.source_id, ...(item.source_ids || [])]
    .some((id) => id && rule.config.source_ids.includes(id)))
  const pending = ['submitting', 'pending', 'judging', 'quota_wait'].includes(session.phase) && !session.data?.requires_review
  const result = session.data
  return <div className="grid gap-4">
    <p className="type-meta text-muted">测试规则版本 {rule.version}，不会发送通知，也不会推进正式处理水位。</p>
    <Card variant="secondary" className="grid gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><span className="type-body">已选 {session.selection.length} 篇文章</span>
        <Button size="sm" variant="secondary" isDisabled={pending || feed.isPending} onPress={() => setPicker(true)}>选择文章</Button></div>
      {feed.isError && <p role="alert" className="type-meta">最新信息流读取失败，请刷新后再选择文章。</p>}
      {session.selection.length > 0 && <p className="type-meta line-clamp-2 text-muted">{session.selection.slice(0, 2).map((item) => item.title).join('、')}{session.selection.length > 2 ? `，另有 ${session.selection.length - 2} 篇` : ''}</p>}
      {dirty && <p role="alert" className="type-meta text-warning">当前有未保存修改；请先保存，再测试对应版本。</p>}
      <StableAsyncButton pending={session.phase === 'submitting'} pendingContent="正在提交…"
        isDisabled={!canMutate || rule.state === 'archived' || dirty || !session.selection.length || pending || session.data?.reason === "completion_unknown"} onPress={onStart}>
        {session.data?.reason === 'preview_confirmation_required' ? '确认重新测试' : session.phase === 'submission_unknown' || session.phase === 'failed' ? '手动重新测试' : '开始测试'}
      </StableAsyncButton>
    </Card>
    {session.phase !== 'idle' && <div role="status" className="grid gap-3">
      <StatusIndicator tone={session.phase === 'failed' || session.phase === 'submission_unknown' ? 'danger' : session.phase === 'completed' ? 'success' : 'accent'} label={informationTestStatusLabel(session.phase)} />
      {session.error && <p className="type-body">{session.error}</p>}
      {result && previewStatus(result) && <p className="type-body">{previewStatus(result)}</p>}
      {(session.phase === "submission_unknown" || result?.requires_review || result?.reason === "completion_unknown") && <a href="/agents" className="type-meta underline">核对分析服务与执行记录（测试编号：{result?.preview_id || "提交结果未知"}）</a>}
      {result?.progress && <p className="type-meta">分析进度：{result.progress.completed} / {result.progress.total}</p>}
      {result?.result && <Card variant="secondary" className="grid gap-2 p-4"><p className="type-page-title">{judgmentLabels[result.result.status]}</p><p className="type-body">{result.result.summary}</p>
        {(result.result.reason || result.result.evidence.length > 0) && <Button size="sm" variant="ghost" aria-expanded={showReason} onPress={() => setShowReason((value) => !value)}>{showReason ? '收起判断依据' : '查看判断原因与原文依据'}</Button>}
        {showReason && <div className="grid gap-2"><p className="type-body">{result.result.reason}</p>{result.result.evidence.map((item, index) => <blockquote key={`${item.article_id}:${index}`} className="type-body border-l border-separator pl-3">{item.quote} — {item.note}{item.url && <a className="block underline" href={item.url} target="_blank" rel="noopener noreferrer">{item.title || '查看原文'}</a>}</blockquote>)}</div>}
      </Card>}
      {!!result?.results.length && <div className="grid gap-2"><Button variant="ghost" aria-expanded={showItems} onPress={() => setShowItems((value) => !value)}>{showItems ? '收起逐篇结果' : `查看逐篇结果（${result.results.length}）`}</Button>
        {showItems && result.results.map((item) => <p key={item.article_id} className="type-body">{session.selection.find((article) => article.id === item.article_id)?.title || '订阅文章'}：{judgmentLabels[item.status]}</p>)}</div>}
    </div>}
    {picker && <InformationArticlePicker open articles={articles} value={session.selection} onClose={() => setPicker(false)} onConfirm={(value) => { onSelect(value); setPicker(false) }} />}
  </div>
}
