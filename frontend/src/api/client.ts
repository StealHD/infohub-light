export type ApiErrorBody = {
  code: string
  message: string
  retryable?: boolean
  action?: string
}

export type ApiEnvelope<T> = {
  ok: boolean
  data?: T
  error?: ApiErrorBody
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean
  readonly action?: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code || 'request_failed'
    this.retryable = Boolean(body.retryable)
    this.action = body.action
  }
}

type ApiClientOptions = {
  fetcher?: typeof fetch
  onUnauthorized?: () => void
}

export type ApiClient = ReturnType<typeof createApiClient>

export function createApiClient(options: ApiClientOptions = {}) {
  const fetcher = options.fetcher ?? fetch

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const response = await fetcher(path, {
      ...init,
      credentials: 'same-origin',
      headers,
    })
    let envelope: ApiEnvelope<T>
    try {
      envelope = await response.json() as ApiEnvelope<T>
    } catch {
      throw new ApiError(response.status, {
        code: 'invalid_response',
        message: '服务返回了无法解析的响应。',
        retryable: response.status >= 500,
      })
    }
    if (!response.ok || envelope.ok === false || envelope.error) {
      const error = new ApiError(response.status, envelope.error ?? {
        code: 'request_failed',
        message: `HTTP ${response.status}`,
        retryable: response.status >= 500,
      })
      if (response.status === 401) options.onUnauthorized?.()
      throw error
    }
    return envelope.data as T
  }

  return {
    get<T>(path: string, signal?: AbortSignal) {
      return request<T>(path, { method: 'GET', signal })
    },
    post<T>(path: string, body?: unknown, signal?: AbortSignal) {
      return request<T>(path, {
        method: 'POST',
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      })
    },
    patch<T>(path: string, body: unknown, signal?: AbortSignal) {
      return request<T>(path, { method: 'PATCH', body: JSON.stringify(body), signal })
    },
    put<T>(path: string, body: unknown, signal?: AbortSignal) {
      return request<T>(path, { method: 'PUT', body: JSON.stringify(body), signal })
    },
    delete<T>(path: string, signal?: AbortSignal) {
      return request<T>(path, { method: 'DELETE', signal })
    },
  }
}
