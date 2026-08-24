import type { ApiClient } from './client'

export type RsshubAccessKeyStatus = {
  configured: boolean
  management_source: 'secret_store' | 'environment' | 'none'
}

export function rsshubAccessKeyApi(client: ApiClient) {
  return {
    rsshubAccessKey: (signal?: AbortSignal) => client.get<RsshubAccessKeyStatus>('/api/admin/rsshub-access-key', signal),
    saveRsshubAccessKey: (value: string) => client.put<RsshubAccessKeyStatus>('/api/admin/rsshub-access-key', { value }),
    deleteRsshubAccessKey: () => client.delete<RsshubAccessKeyStatus>('/api/admin/rsshub-access-key'),
  }
}
