import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule, InformationTest } from '../../api/informationAutomationService'
import { Button, Checkbox, Modal, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { InformationRuleFields } from './InformationRuleFields'
import { InformationRuleRuns } from './InformationRuleRuns'
import { completeRule, judgmentLabels, ruleStateLabels } from './informationRuleModel'
import { useInformationDraft } from './useInformationDraft'

export function InformationRuleEditor({ rule, canMutate, onSaved }: {
  rule: InformationRule; canMutate: boolean; onSaved: (rule: InformationRule) => Promise<unknown>
}) {
  const { api, userId } = useInformationContext()
  const draft = useInformationDraft(userId, rule)
  const [busy, setBusy] = useState('')
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<InformationTest | null>(null)
  const [showRuns, setShowRuns] = useState(false)
  const sources = useQuery({ queryKey: ['information-sources', userId], queryFn: ({ signal }) => api.subscriptions(signal) })
  const targets = useQuery({ queryKey: ['information-targets', userId], queryFn: ({ signal }) => api.notificationServices(signal) })
  const feed = useQuery({ queryKey: ['information-test-feed', userId], queryFn: ({ signal }) => api.latestFeed(signal) })
  const previewQuery = useQuery({ queryKey: ['information-preview', userId, rule.id, preview?.preview_id],
    queryFn: ({ signal }) => api.informationTestPreview(rule.id, preview!.preview_id!, signal), enabled: Boolean(preview?.preview_id),
    refetchInterval: (query) => ['completed', 'failed'].includes(query.state.data?.status || '') ? false : 1500 })
  const result = previewQuery.data || preview
  const editable = canMutate && rule.state !== 'archived'
  async function perform(action: string, operation: () => Promise<void>) {
    if (lock.current) return
    lock.current = true; setBusy(action); setError('')
    try { await operation() } catch (failure) {
      if (draft.active.current) setError(failure instanceof Error ? failure.message : '操作失败，请重试。')
    } finally { lock.current = false; if (draft.active.current) setBusy('') }
  }
  async function transition(action: 'enable' | 'pause' | 'archive') {
    const saved = await api.transitionInformationRule(rule.id, draft.version, action)
    draft.accept(saved); setConfirming(false); await onSaved(saved)
  }
  const articles = (feed.data?.items || []).filter((item) =>
    [item.source_id, ...(item.source_ids || [])].some((id) => id && draft.config.source_ids.includes(id)))
  return <div className="grid gap-4">
    <p className="type-body">{ruleStateLabels[rule.state]} · 版本 {draft.version}</p>
    <InformationRuleFields value={draft.config} onChange={(value) => { draft.setConfig(value); setPreview(null) }}
      sources={sources.data?.subscriptions || []} targets={targets.data?.services || []} disabled={!editable || Boolean(busy)} />
    {(sources.isError || targets.isError) && <p role="alert">来源或通知目标读取失败，请刷新后重试。</p>}
    <p className="type-meta text-muted">修改来源、条件或通知目标后会暂停提醒，需要重新确认。首次采集建立基线，不补发历史内容。</p>
    {error && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <StableAsyncButton pending={busy === 'save'} pendingContent="正在保存…" isDisabled={!editable || Boolean(busy) || !draft.dirty}
        onPress={() => perform('save', async () => {
          const saved = await api.updateInformationRule(rule.id, draft.version, draft.config)
          draft.accept(saved); setPreview(null); await onSaved(saved)
        })}>保存草稿</StableAsyncButton>
      <Button isDisabled={!editable || Boolean(busy) || draft.dirty || !completeRule(draft.config) || rule.state === 'active'}
        onPress={() => setConfirming(true)}>确认启用</Button>
      <StableAsyncButton variant="secondary" pending={busy === 'pause'} pendingContent="正在暂停…"
        isDisabled={!editable || Boolean(busy) || rule.state !== 'active'} onPress={() => perform('pause', () => transition('pause'))}>暂停</StableAsyncButton>
      <StableAsyncButton variant="ghost" pending={busy === 'archive'} pendingContent="正在归档…"
        isDisabled={!editable || Boolean(busy)} onPress={() => perform('archive', () => transition('archive'))}>归档</StableAsyncButton>
    </div>
    <fieldset className="grid gap-2"><legend className="type-section-title">测试预览</legend>
      <p className="type-meta text-muted">选择最多 20 篇已收录文章。测试不发送通知，不推进正式处理水位。</p>
      {articles.slice(0, 50).map((item) => <Checkbox key={item.id} isSelected={selected.includes(item.id)}
        isDisabled={Boolean(busy) || (!selected.includes(item.id) && selected.length >= 20)}
        onChange={(checked) => setSelected((current) => checked ? [...current, item.id] : current.filter((id) => id !== item.id))}>
        <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{item.title}</Checkbox.Content>
      </Checkbox>)}
      {articles.length === 0 && <p className="type-body">当前所选来源没有可测试文章。</p>}
      <StableAsyncButton pending={busy === 'test'} pendingContent="正在测试…"
        isDisabled={Boolean(busy) || draft.dirty || !selected.length} onPress={() => perform('test', async () => {
          const result = await api.testInformationRule(rule.id, draft.version, selected)
          if (draft.active.current) setPreview(result)
        })}>测试已保存规则</StableAsyncButton>
      {result && <div role="status" className="grid gap-2"><p>版本 {result.version} 测试结果 · 未发送通知</p>
        {result.status && !['completed', 'failed'].includes(result.status) && <p>{result.status === 'quota_wait' ? '今日判断额度已用完，测试仍在队列中。' : '正在等待独立语义判断…'}</p>}
        {result.status === 'failed' && <p>测试未完成，请检查判断服务后重试。</p>}
        {previewQuery.isError && <p>测试进度读取失败，请稍后重试。</p>}
        {result.results.map((item) => <p key={item.article_id}>{articles.find((article) => article.id === item.article_id)?.title || '订阅文章'}：{judgmentLabels[item.status]}</p>)}
      </div>}
    </fieldset>
    <Button variant="ghost" onPress={() => setShowRuns((value) => !value)}>{showRuns ? '收起运行记录' : '查看运行记录'}</Button>
    {showRuns && <InformationRuleRuns ruleId={rule.id} />}
    <Modal isOpen={confirming} onOpenChange={(open) => { if (!lock.current) setConfirming(open) }}>
      <Modal.Backdrop><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>确认启用“{rule.config.name}”</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body">启用后，将按当前保存的来源和条件持续自动发送到“{targets.data?.services.find((target) => target.id === rule.config.target_id)?.name || '所选通知目标'}”。只处理新增内容，可随时暂停。</p>{error && <p role="alert">{error}</p>}</Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={Boolean(busy)} onPress={() => setConfirming(false)}>取消</Button>
          <StableAsyncButton pending={busy === 'enable'} pendingContent="正在启用…" onPress={() => perform('enable', () => transition('enable'))}>确认并启用</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </div>
}
