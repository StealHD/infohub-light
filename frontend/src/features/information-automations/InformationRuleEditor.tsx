import { queryKeys } from '../../api/queryKeys'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'
import { Button, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { InformationRuleFields } from './InformationRuleFields'
import { useInformationDraft } from './useInformationDraft'

export function InformationRuleEditor({ rule, canMutate, onSaved, onBusyChange, onDraftChange, onExit }: {
  rule: InformationRule; canMutate: boolean; onSaved: (rule: InformationRule) => Promise<unknown>; onBusyChange?: (busy: boolean) => void
  onDraftChange?: (config: InformationRuleConfig, dirty: boolean) => void; onExit?: () => void
}) {
  const { api, userId } = useInformationContext()
  const draft = useInformationDraft(userId, rule)
  const [busy, setBusy] = useState('')
  const lock = useRef(false)
  const [error, setError] = useState('')
  const sources = useQuery({ queryKey: queryKeys.subscriptions(userId), queryFn: ({ signal }) => api.subscriptions(signal) })
  const targets = useQuery({ queryKey: queryKeys.notificationServices(userId), queryFn: ({ signal }) => api.notificationServices(signal) })
  const editable = canMutate && rule.state !== 'archived'
  useEffect(() => { onDraftChange?.(draft.config, draft.dirty) }, [draft.config, draft.dirty, onDraftChange])
  async function perform(action: string, operation: () => Promise<void>) {
    if (lock.current) return
    lock.current = true; onBusyChange?.(true); setBusy(action); setError('')
    try { await operation() } catch (failure) {
      if (draft.active.current) setError(failure instanceof Error ? failure.message : '操作失败，请重试。')
    } finally { lock.current = false; onBusyChange?.(false); if (draft.active.current) setBusy('') }
  }
  return <div className="grid gap-4">
    <div className="sticky top-0 z-10 -mx-4 flex flex-wrap justify-end gap-2 border-b border-separator bg-surface px-4 py-3">
      {onExit && <Button variant="ghost" isDisabled={Boolean(busy)} onPress={onExit}>返回概览</Button>}
      <StableAsyncButton pending={busy === 'save'} pendingContent="正在保存…" isDisabled={!editable || Boolean(busy) || !draft.dirty}
        onPress={() => perform('save', async () => {
          const saved = await api.updateInformationRule(rule.id, draft.version, draft.config)
          draft.accept(saved); await onSaved(saved)
        })}>保存草稿</StableAsyncButton>
    </div>
    <InformationRuleFields value={draft.config} onChange={draft.setConfig}
      sources={sources.data?.subscriptions || []} targets={targets.data?.services || []} disabled={!editable || Boolean(busy)} />
    {(sources.isError || targets.isError) && <p role="alert">来源或通知目标读取失败，请刷新后重试。</p>}
    <p className="type-meta text-muted">修改描述、来源、模型、触发方式或通知目标后会暂停任务；保存后可再次启动。首次采集建立基线，不补发历史内容。</p>
    {error && <p role="alert">{error}</p>}
  </div>
}
