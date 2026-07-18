import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
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

export function useOptimisticItemState(options: ItemStateMutationOptions) {
  const queryClient = useQueryClient()
  const feedback = useActionFeedback()
  const mutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<UserItemState>; token: ActionToken }) => options.api.updateItemState(id, patch),
    onMutate: async ({ id, patch, token }) => {
      const action = String(Object.keys(patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.begin(`item-${action}`, id)
      const prefix = ['user', options.user.id] as const
      await queryClient.cancelQueries({ queryKey: prefix })
      const previous = queryClient.getQueriesData({ queryKey: prefix })
      queryClient.setQueriesData({ queryKey: prefix }, (data) => patchItemStateInData(data, id, patch))
      return { previous, token }
    },
    onError: (caught, variables, context) => {
      if (context && options.isActionCurrent(context.token)) context.previous.forEach(([key, data]) => queryClient.setQueryData(key, data))
      const action = String(Object.keys(variables.patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.fail(`item-${action}`, variables.id, caught instanceof ApiError ? `${caught.message}，状态已恢复。` : '阅读状态保存失败，状态已恢复。')
    },
    onSuccess: (result, variables, context) => {
      if (!context || !options.isActionCurrent(context.token)) return
      queryClient.setQueriesData({ queryKey: ['user', options.user.id] }, (data) => patchItemStateInData(data, variables.id, result))
      const action = String(Object.keys(variables.patch)[0] ?? 'state')
      if (options.publishFeedback !== false) feedback.succeed(`item-${action}`, variables.id)
    },
  })

  return {
    ...mutation,
    mutateItem: (id: string, patch: Partial<UserItemState>) => mutation.mutate({ id, patch, token: options.beginAction() }),
    isItemActionPending: (action: keyof UserItemState, id: string) => options.publishFeedback === false
      ? mutation.isPending && mutation.variables?.id === id && action in mutation.variables.patch
      : feedback.isPending(`item-${String(action)}`, id),
  }
}
