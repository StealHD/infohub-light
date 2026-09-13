import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useInformationContext } from './useInformationContext'

export function useModelRefresh() {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const [submitError, setSubmitError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false)
  const models = useQuery({ queryKey: ['information-models', userId], queryFn: ({ signal }) => api.informationModels(signal), refetchInterval: 15000 })
  const refresh = async () => {
    if (busy.current) return
    busy.current = true; setSubmitting(true); setSubmitError('')
    const abort = new AbortController()
    const timer = window.setTimeout(() => abort.abort(), 35000)
    try {
      const result = await api.refreshInformationModels(abort.signal)
      cache.setQueryData(['information-models', userId], result)
    } catch (cause) {
      setSubmitError(abort.signal.aborted ? '读取 OpenClaw 模型目录超时，请检查 Gateway 后重试。' : cause instanceof Error ? cause.message : '读取 OpenClaw 模型目录失败。')
    } finally { window.clearTimeout(timer); busy.current = false; setSubmitting(false) }
  }
  return { models, refresh, refreshing: submitting, message: submitting ? '正在读取 OpenClaw 模型目录…' : '', error: submitError }
}
