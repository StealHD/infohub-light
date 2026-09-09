import { queryKeys } from '../../api/queryKeys'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'
import { Button, Modal, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { InformationRuleFields } from './InformationRuleFields'
import { completeRule, triggerLabel } from './informationRuleModel'
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
  const [confirming, setConfirming] = useState(false)
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
  async function enable() {
    const saved = await api.transitionInformationRule(rule.id, draft.version, 'enable')
    draft.accept(saved); setConfirming(false); await onSaved(saved)
  }
  return <div className="grid gap-4">
    <div className="sticky top-0 z-10 -mx-4 flex flex-wrap gap-2 border-b border-separator bg-surface px-4 py-3">
      {onExit && <Button variant="ghost" isDisabled={Boolean(busy)} onPress={onExit}>返回概览</Button>}
      <StableAsyncButton pending={busy === 'save'} pendingContent="正在保存…" isDisabled={!editable || Boolean(busy) || !draft.dirty}
        onPress={() => perform('save', async () => {
          const saved = await api.updateInformationRule(rule.id, draft.version, draft.config)
          draft.accept(saved); await onSaved(saved)
        })}>保存草稿</StableAsyncButton>
      <Button isDisabled={!editable || Boolean(busy) || draft.dirty || !completeRule(draft.config) || rule.state === 'active'}
        onPress={() => setConfirming(true)}>确认启用</Button>
    </div>
    <InformationRuleFields value={draft.config} onChange={draft.setConfig}
      sources={sources.data?.subscriptions || []} targets={targets.data?.services || []} disabled={!editable || Boolean(busy)} />
    {(sources.isError || targets.isError) && <p role="alert">来源或通知目标读取失败，请刷新后重试。</p>}
    <p className="type-meta text-muted">修改描述、来源、模型、触发方式或通知目标后会暂停任务，需要重新确认。首次采集建立基线，不补发历史内容。</p>
    {error && <p role="alert">{error}</p>}
    <Modal isOpen={confirming} onOpenChange={(open) => { if (!lock.current) setConfirming(open) }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开启用确认</Modal.Trigger>
      <Modal.Backdrop><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>确认启用“{rule.config.name}”</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body whitespace-pre-wrap">{rule.config.requirement}</p><p className="type-meta">{rule.config.model?.id} · {triggerLabel(rule.config.trigger)} · {sources.data?.subscriptions.filter((source) => rule.config.source_ids.includes(source.source_id)).map((source) => source.source_display_name || source.source_id).join('、') || `${rule.config.source_ids.length} 个订阅源`}</p><p className="type-body">启用后，将按当前保存的完整要求、来源、模型与触发方式持续自动发送到“{targets.data?.services.find((target) => target.id === rule.config.target_id)?.name || '所选通知目标'}”。只处理新增内容，可随时暂停。</p>{error && <p role="alert">{error}</p>}</Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={Boolean(busy)} onPress={() => setConfirming(false)}>取消</Button>
          <StableAsyncButton pending={busy === 'enable'} pendingContent="正在启用…" onPress={() => perform('enable', enable)}>确认并启用</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </div>
}
