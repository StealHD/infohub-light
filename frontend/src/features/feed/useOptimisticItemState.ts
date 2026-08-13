import { useMutation, useQueryClient, type QueryFilters, type QueryKey } from '@tanstack/react-query'
import { useRef } from 'react'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { ServiceApi } from '../../api/service'
import type { User, UserItemState } from '../../api/types'
import type { ActionToken } from '../../app/actionGeneration'
import { useActionFeedback } from '../../app/ActionFeedback'
import { patchItemStateInData } from './feedCache'

type ItemStateMutationOptions = {
  api: ServiceApi
  user: User
  beginAction: () => ActionToken
  isActionCurrent: (token: ActionToken) => boolean
  publishFeedback?: boolean
}

type ItemStateMutationVariables = {
  id: string
  patch: Partial<UserItemState>
  token: ActionToken
  sequence: number
}

type ItemStateMutationChain = {
  baseStates: Map<string, { queryKey: QueryKey; state: UserItemState }>
  confirmedSequences: Map<keyof UserItemState, number>
  managedFields: Set<keyof UserItemState>
  operations: Map<number, Partial<UserItemState>>
}

const itemStateQueryFamilies = new Set(['feed', 'feed-item', 'history', 'search', 'saved', 'ignored'])
const defaultItemState: UserItemState = {
  is_read: false,
  is_saved: false,
  is_later: false,
  dismissed: false,
}
const itemStateTimestampFields: Partial<Record<keyof UserItemState, keyof UserItemState>> = {
  is_read: 'read_at',
  is_saved: 'saved_at',
  is_later: 'later_at',
  dismissed: 'dismissed_at',
}

export function isItemStateQueryKey(queryKey: readonly unknown[], userId: string): boolean {
  return (
    queryKey[0] === 'user'
    && queryKey[1] === userId
    && typeof queryKey[2] === 'string'
    && itemStateQueryFamilies.has(queryKey[2])
  )
}

function itemStateQueryFilters(userId: string): QueryFilters {
  return {
    predicate: (query) => isItemStateQueryKey(query.queryKey, userId),
  }
}

function itemStateFromData(data: unknown, articleId: string): UserItemState | undefined {
  if (!data || typeof data !== 'object') return undefined
  const record = data as Record<string, unknown>
  if (record.id === articleId && record.user_state && typeof record.user_state === 'object') {
    return { ...defaultItemState, ...(record.user_state as Partial<UserItemState>) }
  }
  for (const key of ['items', 'today_items', 'featured_items', 'daily_push_items'] as const) {
    const collection = record[key]
    if (!Array.isArray(collection)) continue
    for (const entry of collection) {
      const state = itemStateFromData(entry, articleId)
      if (state) return state
    }
  }
  if (Array.isArray(record.pages)) {
    for (const page of record.pages) {
      const state = itemStateFromData(page, articleId)
      if (state) return state
    }
  }
  return undefined
}

function effectiveItemStatePatch(
  chain: ItemStateMutationChain,
  baseState: UserItemState,
): Partial<UserItemState> {
  const statePatch: Partial<UserItemState> = {}
  for (const field of chain.managedFields) Object.assign(statePatch, { [field]: baseState[field] })
  for (const [sequence, operationPatch] of [...chain.operations.entries()].sort(([left], [right]) => left - right)) {
    for (const [field, value] of Object.entries(operationPatch) as Array<[keyof UserItemState, UserItemState[keyof UserItemState]]>) {
      if (sequence > (chain.confirmedSequences.get(field) ?? -1)) Object.assign(statePatch, { [field]: value })
    }
  }
  return statePatch
}

function confirmItemStateOperation(
  chain: ItemStateMutationChain,
  sequence: number,
  patch: Partial<UserItemState>,
  result: UserItemState,
) {
  const explicitlyPendingFields = new Set<keyof UserItemState>()
  for (const pendingPatch of chain.operations.values()) {
    for (const field of Object.keys(pendingPatch) as Array<keyof UserItemState>) explicitlyPendingFields.add(field)
  }
  const operationFields = new Set(Object.keys(patch) as Array<keyof UserItemState>)
  for (const [field, value] of Object.entries(result) as Array<[keyof UserItemState, UserItemState[keyof UserItemState]]>) {
    if (
      operationFields.has(field)
      || explicitlyPendingFields.has(field)
      || chain.confirmedSequences.has(field)
    ) {
      continue
    }
    chain.managedFields.add(field)
    for (const base of chain.baseStates.values()) Object.assign(base.state, { [field]: value })
  }
  for (const field of operationFields) {
    if (sequence < (chain.confirmedSequences.get(field) ?? -1)) continue
    chain.managedFields.add(field)
    for (const base of chain.baseStates.values()) {
      Object.assign(base.state, { [field]: result[field] ?? patch[field] })
    }
    chain.confirmedSequences.set(field, sequence)
    const timestampField = itemStateTimestampFields[field]
    if (timestampField && timestampField in result) {
      chain.managedFields.add(timestampField)
      for (const base of chain.baseStates.values()) {
        Object.assign(base.state, { [timestampField]: result[timestampField] })
      }
      chain.confirmedSequences.set(timestampField, sequence)
    }
  }
}

export function useOptimisticItemState(options: ItemStateMutationOptions) {
  const queryClient = useQueryClient()
  const feedback = useActionFeedback()
  const nextSequence = useRef(0)
  const chains = useRef(new Map<string, ItemStateMutationChain>())

  const captureChainQueries = (
    userId: string,
    articleId: string,
    chain: ItemStateMutationChain,
  ) => {
    for (const query of queryClient.getQueryCache().findAll(itemStateQueryFilters(userId))) {
      if (chain.baseStates.has(query.queryHash)) continue
      const state = itemStateFromData(query.state.data, articleId)
      if (!state) continue
      chain.baseStates.set(query.queryHash, {
        queryKey: query.queryKey,
        state,
      })
    }
  }

  const applyChain = (userId: string, articleId: string, chain: ItemStateMutationChain) => {
    captureChainQueries(userId, articleId, chain)
    for (const base of chain.baseStates.values()) {
      queryClient.setQueryData(
        base.queryKey,
        (data) => patchItemStateInData(data, articleId, effectiveItemStatePatch(chain, base.state)),
      )
    }
  }

  const mutation = useMutation({
    mutationFn: ({ id, patch }: ItemStateMutationVariables) => options.api.updateItemState(id, patch),
    onMutate: async ({ id, patch, token, sequence }: ItemStateMutationVariables) => {
      const action = String(Object.keys(patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.begin(`item-${action}`, id)
      const userId = token.userId
      const filters = itemStateQueryFilters(userId)
      const chainKey = `${userId}\u0000${id}`
      let chain = chains.current.get(chainKey)
      if (!chain) {
        chain = {
          baseStates: new Map(),
          confirmedSequences: new Map(),
          managedFields: new Set(),
          operations: new Map(),
        }
        chains.current.set(chainKey, chain)
      }
      captureChainQueries(userId, id, chain)
      for (const field of Object.keys(patch) as Array<keyof UserItemState>) chain.managedFields.add(field)
      chain.operations.set(sequence, patch)
      await queryClient.cancelQueries(filters)
      applyChain(userId, id, chain)
      return { chainKey, sequence, token }
    },
    onError: (caught, variables, context) => {
      const chain = context ? chains.current.get(context.chainKey) : undefined
      if (chain && context) {
        captureChainQueries(context.token.userId, variables.id, chain)
        chain.operations.delete(context.sequence)
        if (options.isActionCurrent(context.token)) applyChain(context.token.userId, variables.id, chain)
        if (chain.operations.size === 0) chains.current.delete(context.chainKey)
      }
      const action = String(Object.keys(variables.patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.fail(`item-${action}`, variables.id, caught instanceof ApiError ? `${caught.message}，状态已恢复。` : '阅读状态保存失败，状态已恢复。')
    },
    onSuccess: (result, variables, context) => {
      if (!context) return
      const chain = chains.current.get(context.chainKey)
      let chainSettled = false
      if (chain) {
        captureChainQueries(context.token.userId, variables.id, chain)
        chain.operations.delete(context.sequence)
        confirmItemStateOperation(chain, context.sequence, variables.patch, result)
        if (options.isActionCurrent(context.token)) applyChain(context.token.userId, variables.id, chain)
        chainSettled = chain.operations.size === 0
        if (chainSettled) chains.current.delete(context.chainKey)
      }
      if (options.isActionCurrent(context.token) && (!chain || chainSettled)) {
        // The response is authoritative once this item's mutation chain has
        // settled. Reconcile every cached feed family as well as the
        // optimistic snapshot, so a concurrent observer cannot leave the
        // visible card showing the pre-save star until a full reload.
        queryClient.setQueriesData(
          itemStateQueryFilters(context.token.userId),
          (data) => patchItemStateInData(data, variables.id, result),
        )
      }
      // A saved collection may already be cached as an empty page. Patching
      // item state cannot add this newly saved item to that response, so make
      // the collection stale after the server accepts the save.
      if (variables.patch.is_saved === true) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.saved(context.token.userId) })
      }
      if (!options.isActionCurrent(context.token)) return
      const action = String(Object.keys(variables.patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.succeed(`item-${action}`, variables.id)
    },
  })

  return {
    ...mutation,
    mutateItem: (id: string, patch: Partial<UserItemState>) => mutation.mutate({
      id,
      patch,
      token: options.beginAction(),
      sequence: ++nextSequence.current,
    }),
    isItemActionPending: (action: keyof UserItemState, id: string) => options.publishFeedback === false
      ? mutation.isPending && mutation.variables?.id === id && action in mutation.variables.patch
      : feedback.isPending(`item-${String(action)}`, id),
  }
}
