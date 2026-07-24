import { useOutletContext } from 'react-router-dom'

import type { ServiceApi } from '../api/service'
import type { FeedSnapshot, User } from '../api/types'
import type { FeedActivity } from '../features/jobs/jobModel'
import type { ActionToken } from './actionGeneration'

export type AppOutletContext = {
  api: ServiceApi
  user: User
  query: string
  setQuery: (value: string) => void
  activity: FeedActivity
  refresh: () => void
  reloadFeed: () => Promise<FeedSnapshot>
  beginAction: () => ActionToken
  isActionCurrent: (token: ActionToken) => boolean
}

export const useAppContext = () => useOutletContext<AppOutletContext>()
