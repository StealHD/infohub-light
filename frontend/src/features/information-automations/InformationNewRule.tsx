import { queryKeys } from '../../api/queryKeys'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule } from '../../api/informationAutomationService'
import { Button, Card, StableAsyncButton } from '../../design-system'
import { InformationRuleFields } from './InformationRuleFields'
import { emptyInformationRule } from './informationRuleModel'
import { useInformationContext } from './useInformationContext'

export function InformationNewRule({ onSaved, onCancel }: { onSaved: (rule: InformationRule) => Promise<void>; onCancel: () => void }) {
  const { api, userId } = useInformationContext()
  const draftKey = `information-new-draft:${userId}`
  const [value, setValue] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey) || 'null')
      if (saved?.schema_version === 2 && saved.trigger && Array.isArray(saved.source_ids)) return saved as ReturnType<typeof emptyInformationRule>
    } catch { /* Storage is optional. */ }
    return emptyInformationRule()
  })
  useEffect(() => {
    try { sessionStorage.setItem(draftKey, JSON.stringify(value)) } catch { /* Keep the in-memory draft. */ }
  }, [draftKey, value])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const lock = useRef(false)
  const sources = useQuery({ queryKey: queryKeys.subscriptions(userId), queryFn: ({ signal }) => api.subscriptions(signal) })
  const targets = useQuery({ queryKey: queryKeys.notificationServices(userId), queryFn: ({ signal }) => api.notificationServices(signal) })
  return <Card variant="secondary" className="grid gap-4 p-4">
    <Card.Title>新建自动化</Card.Title>
    <InformationRuleFields value={value} onChange={setValue} sources={sources.data?.subscriptions || []}
      targets={targets.data?.services || []} disabled={busy} />
    {(sources.isError || targets.isError) && <p role="alert">来源或通知目标读取失败，请重新打开后重试。</p>}
    {error && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <Button variant="ghost" isDisabled={busy} onPress={onCancel}>取消</Button>
      <StableAsyncButton pending={busy} pendingContent="正在保存…" isDisabled={!value.name.trim()} onPress={async () => {
        if (lock.current) return
        lock.current = true; setBusy(true); setError('')
        try {
          const saved = await api.createInformationRule(value)
          try { sessionStorage.removeItem(draftKey) } catch { /* Storage is optional. */ }
          await onSaved(saved)
        }
        catch (failure) { setError(failure instanceof Error ? failure.message : '保存失败，请重试。') }
        finally { lock.current = false; setBusy(false) }
      }}>保存草稿</StableAsyncButton>
    </div>
  </Card>
}
