import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import type { InformationRule } from '../../api/informationAutomationService'
import { Button, Card, FormSelect, Label, StableAsyncButton, StatusIndicator, Switch, TextArea, TextField } from '../../design-system'
import { InformationArticlePicker } from './InformationArticlePicker'
import { judgmentLabels } from './informationRuleModel'
import { previewStatus } from './previewStatus'
import { useInformationContext } from './useInformationContext'
import { informationTestStatusLabel, type InformationTestSession, type TestArticleSelection } from './useInformationTests'

export function InformationTestPanel({ rule, dirty, canMutate, session, onSelect, onTextChange, onConfigureNotification, onStart }: {
  rule: InformationRule; dirty: boolean; canMutate: boolean; session: InformationTestSession
  onSelect: (value: TestArticleSelection[]) => void; onTextChange: (value: string) => void
  onConfigureNotification: (send: boolean, target: string | null) => void; onStart: () => Promise<void>
}) {
  const { api, userId } = useInformationContext()
  const [picker, setPicker] = useState(false)
  const [showReason, setShowReason] = useState(false)
  const [showItems, setShowItems] = useState(false)
  const feed = useQuery({ queryKey: ['information-test-feed', userId], queryFn: ({ signal }) => api.latestFeed(signal) })
  const services = useQuery({ queryKey: ['information-test-notification-services', userId],
    queryFn: ({ signal }) => api.notificationServices(signal) })
  const targets = services.data?.services.filter((item) => item.available) || []
  const selectedTarget = session.notificationTargetId || rule.config.target_id || ''
  const articles = (feed.data?.items || []).filter((item) => [item.source_id, ...(item.source_ids || [])]
    .some((id) => id && rule.config.source_ids.includes(id)))
  const pending = ['submitting', 'pending', 'judging', 'quota_wait'].includes(session.phase) && !session.data?.requires_review
  const result = session.data
  const usesCustomText = Boolean(session.customText.trim())
  return <div className="grid gap-4">
    <p className="type-meta text-muted">测试规则版本 {rule.version}。默认不通知；仅勾选且分析命中时发送测试通知，不推进正式处理水位。</p>
    <Card variant="secondary" className="grid gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><span className="type-body">{usesCustomText ? '使用自定义文本测试' : `已选 ${session.selection.length} 篇文章`}</span>
        <Button size="sm" variant="secondary" isDisabled={pending || feed.isPending} onPress={() => setPicker(true)}>选择文章</Button></div>
      {feed.isError && <p role="alert" className="type-meta">最新信息流读取失败，请刷新后再选择文章。</p>}
      {!usesCustomText && session.selection.length > 0 && <p className="type-meta line-clamp-2 text-muted">{session.selection.slice(0, 2).map((item) => item.title).join('、')}{session.selection.length > 2 ? `，另有 ${session.selection.length - 2} 篇` : ''}</p>}
      <TextField isDisabled={pending || !canMutate}><Label>自定义测试文本</Label><TextArea aria-label="自定义测试文本" value={session.customText} maxLength={24000}
        placeholder="粘贴想验证的标题、正文或任意示例内容。填写后，本次测试不会使用已选文章。"
        onChange={(event) => onTextChange(event.target.value)} /></TextField>
      {usesCustomText && <p className="type-meta text-muted">本次仅使用自定义文本，不读取或改写文章、正式水位和任务配置。</p>}
      {dirty && <p role="alert" className="type-meta text-warning">当前有未保存修改；请先保存，再测试对应版本。</p>}
      <Switch isSelected={session.sendNotification} isDisabled={pending || !canMutate}
        onChange={(send) => onConfigureNotification(send, send ? selectedTarget || null : null)}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>命中后发送测试通知</Switch.Content>
      </Switch>
      {session.sendNotification && <FormSelect label="本次测试通知服务" value={selectedTarget}
        isDisabled={pending || !canMutate} options={targets.map((item) => ({ id: item.id, label: item.name }))}
        onChange={(target) => onConfigureNotification(true, target)} />}
      {session.sendNotification && !selectedTarget && <p role="alert" className="type-meta text-warning">请选择已验证的通知服务。</p>}
      <StableAsyncButton pending={session.phase === 'submitting'} pendingContent="正在提交…"
        isDisabled={!canMutate || rule.state === 'archived' || dirty || (!session.selection.length && !usesCustomText) || pending || (session.sendNotification && !selectedTarget) || session.data?.reason === "completion_unknown"} onPress={onStart}>
        {session.data?.reason === 'preview_confirmation_required' ? '确认重新测试' : session.phase === 'submission_unknown' || session.phase === 'failed' ? '手动重新测试' : '开始测试'}
      </StableAsyncButton>
    </Card>
    {session.phase !== 'idle' && <div role="status" className="grid gap-3">
      <StatusIndicator tone={session.phase === 'failed' || session.phase === 'submission_unknown' ? 'danger' : session.phase === 'completed' ? 'success' : 'accent'} label={informationTestStatusLabel(session.phase)} />
      {session.error && <p className="type-body">{session.error}</p>}
      {result && previewStatus(result) && <p className="type-body">{previewStatus(result)}</p>}
      {result?.reason === 'offline' && <Link to="/agents" className="type-meta underline">连接 OpenClaw</Link>}
      {(session.phase === "submission_unknown" || result?.requires_review || result?.reason === "completion_unknown") && <a href="/agents" className="type-meta underline">核对分析服务与执行记录（测试编号：{result?.preview_id || "提交结果未知"}）</a>}
      {result?.progress && <p className="type-meta">分析进度：{result.progress.completed} / {result.progress.total}</p>}
      {result?.sends_notification && <p className="type-meta">测试通知：{({ waiting_analysis: '等待分析', pending: '等待发送', quota_wait: '等待每日额度', sending: '发送中', sent: '已发送', failed: '发送失败', unknown: '结果未知，请核对接收端', cancelled: '已取消', not_required: '未命中，无需发送' } as Record<string, string>)[result.notification_status || ''] || '等待处理'}</p>}
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
