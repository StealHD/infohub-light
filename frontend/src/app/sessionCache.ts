import type { QueryClient } from '@tanstack/react-query'
import { clearAgentContextDraft } from '../features/workbench-live/agentContext'
import { clearFeedEndMessageSession } from '../features/workbench-live/feedEndMessageSession'
import { clearSourceSummaryCache } from '../features/workbench-live/sourceSummaryCache'

export async function clearUserCache(queryClient: QueryClient, userId: string): Promise<void> {
  const queryKey = ['user', userId] as const
  await queryClient.cancelQueries({ queryKey })
  queryClient.removeQueries({ queryKey })
  clearAgentContextDraft(userId)
  clearFeedEndMessageSession(userId)
  clearSourceSummaryCache(userId)
}
