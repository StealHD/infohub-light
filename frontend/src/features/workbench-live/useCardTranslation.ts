import { useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { AppOutletContext } from '../../app/AppContext'
import { ApiError } from '../../api/client'
import type { FeedTranslation } from '../../api/feedTranslationService'

type ReadingState = { open: boolean; submitting?: boolean; requestId?: string; error?: string; code?: string }

export function useCardTranslation(context: AppOutletContext, id: string, onExpand: () => void) {
  const { api, user, beginAction, isActionCurrent } = context
  const client = useQueryClient()
  const lock = useRef(false)
  const stateKey = ['user', user.id, 'translation-reading', id] as const
  const queryKey = ['user', user.id, 'translation', id] as const
  const reading = useQuery<ReadingState>({ queryKey: stateKey, queryFn: () => ({ open: false }), enabled: false })
  const state = reading.data ?? { open: false }
  const result = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.feedTranslation(id, signal),
    enabled: state.open && !state.submitting,
    retry: false,
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.status ?? '') ? 1000 : false,
    staleTime: 0,
  })
  const pending = Boolean(state.submitting) || ['queued', 'running'].includes(result.data?.status ?? '')

  async function activate(retry = false) {
    if (lock.current || pending) return
    if (!retry && state.open && result.data?.status === 'succeeded') {
      client.setQueryData(stateKey, { ...state, open: false })
      return
    }
    lock.current = true
    const token = beginAction()
    // A retry after an unknown HTTP outcome keeps the same idempotency key.
    const requestId = result.data?.status === 'failed' || !state.requestId ? crypto.randomUUID() : state.requestId
    client.setQueryData(stateKey, { open: true, submitting: true, requestId })
    onExpand()
    try {
      await client.cancelQueries({ queryKey })
      const existing = await api.feedTranslation(id)
      if (!isActionCurrent(token)) return
      const data = ['succeeded', 'queued', 'running'].includes(existing.status)
        ? existing : await api.translateFeedItem(id, requestId)
      if (!isActionCurrent(token)) return
      client.setQueryData<FeedTranslation>(queryKey, data)
      client.setQueryData(stateKey, { open: true })
    } catch (error) {
      if (!isActionCurrent(token)) return
      client.setQueryData(stateKey, {
        open: true, requestId: error instanceof ApiError && error.code === 'translation_request_conflict' ? undefined : requestId,
        error: error instanceof ApiError ? error.message : '暂时无法确认翻译状态，请重试。',
        code: error instanceof ApiError ? error.code : 'translation_connection_failed',
      })
    } finally {
      lock.current = false
    }
  }

  const queryError = result.error instanceof ApiError ? result.error : null
  const recovered = result.isSuccess && ['queued', 'running', 'succeeded'].includes(result.data?.status ?? '')
  return {
    open: state.open, pending, data: result.data,
    message: (!recovered && state.error) || queryError?.message || (result.isError ? '无法读取翻译状态，请重试。' : result.data?.error?.message),
    code: (!recovered && state.code) || queryError?.code || result.data?.error?.code,
    activate,
  }
}
