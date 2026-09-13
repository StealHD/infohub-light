import type { ApiClient } from './client'
import type { NotificationService, NotificationTestResult, OpenClawChannelAccount, OpenClawServiceCreate, OpenClawServicePatch } from './types'

const base = '/api/admin/openclaw-notification-services'
const path = (id: string) => `${base}/${encodeURIComponent(id)}`

export const openClawNotificationApi = (client: ApiClient) => ({
  openClawNotificationChannels: (signal?: AbortSignal) => client.get<{ channels: OpenClawChannelAccount[] }>(`${base}/channels`, signal),
  createOpenClawNotificationService: (payload: OpenClawServiceCreate) => client.post<NotificationService>(base, payload),
  updateOpenClawNotificationService: (serviceId: string, patch: OpenClawServicePatch) => client.patch<NotificationService>(path(serviceId), patch),
  testAndEnableOpenClawNotificationService: (serviceId: string) => client.post<NotificationTestResult>(`${path(serviceId)}/test-and-enable`),
  archiveOpenClawNotificationService: (serviceId: string) => client.delete<{ service_id: string; archived: boolean }>(path(serviceId)),
})
