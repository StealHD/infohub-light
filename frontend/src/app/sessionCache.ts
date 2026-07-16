import type { QueryClient } from '@tanstack/react-query'

export async function clearUserCache(queryClient: QueryClient, userId: string): Promise<void> {
  const queryKey = ['user', userId] as const
  await queryClient.cancelQueries({ queryKey })
  queryClient.removeQueries({ queryKey })
}
