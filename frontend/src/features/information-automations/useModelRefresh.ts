import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useInformationContext } from './useInformationContext'

export function useModelRefresh() {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const [ticket, setTicket] = useState<{ id: string; deadline: number } | null>(null)
  const [timedOut, setTimedOut] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false)
  const models = useQuery({ queryKey: ['information-models', userId], queryFn: ({ signal }) => api.informationModels(signal),
    refetchInterval: (query) => query.state.data?.refresh?.status === 'pending' && query.state.data.refresh.id !== timedOut ? 1500 : 15000 })
  const receipt = models.data?.refresh
  const deadline = ticket?.deadline ?? (receipt?.status === 'pending' ? Date.parse(receipt.requested_at) + 120000 : null)
  const id = ticket?.id ?? (receipt?.status === 'pending' ? receipt.id : null)
  const matched = Boolean(id && receipt?.id === id)
  const expired = Boolean(id && timedOut === id)
  const waiting = Boolean(id && !expired && (!matched || receipt?.status === 'pending'))
  useEffect(() => {
    if (!waiting || !id || deadline === null || !Number.isFinite(deadline)) return
    const timer = window.setTimeout(() => setTimedOut(id), Math.max(0, deadline - Date.now()))
    return () => window.clearTimeout(timer)
  }, [waiting, id, deadline])
  const message = submitting ? '正在请求模型同步…' : expired ? '' : waiting ? '正在等待执行器同步模型目录…'
    : matched && receipt?.status === 'completed' ? receipt.changed ? '模型目录已刷新。' : '已刷新，无变化。' : ''
  const error = submitError || (expired
    ? `模型刷新超时：${models.data?.execution_reason === 'connector_upgrade_required' ? '执行器需要升级' : models.data?.reason === 'offline' ? '分析服务离线' : '执行器未在 120 秒内回传同步结果'}。请检查服务后手动重试。`
    : matched && receipt?.status === 'failed' ? '模型同步失败，请检查分析服务后手动重试。' : '')
  const refresh = async () => {
    if (busy.current || waiting) return
    busy.current = true; setSubmitting(true); setSubmitError(''); setTimedOut(null)
    const abort = new AbortController()
    const timer = window.setTimeout(() => abort.abort(), 120000)
    try {
      const result = await api.refreshInformationModels(abort.signal)
      if (!result.requested || !result.refresh) throw new Error('执行器尚未支持刷新确认，请升级服务。')
      cache.setQueryData(['information-models', userId], result)
      setTicket({ id: result.refresh.id, deadline: Date.now() + 120000 })
    } catch (cause) {
      setSubmitError(abort.signal.aborted ? '模型刷新请求超时，请核对服务状态后手动重试。' : cause instanceof Error ? cause.message : '模型刷新请求失败。')
    } finally { window.clearTimeout(timer); busy.current = false; setSubmitting(false) }
  }
  return { models, refresh, refreshing: submitting || waiting, message, error }
}
