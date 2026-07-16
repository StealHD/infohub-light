import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { createApiClient } from './client'

const server = setupServer(
  http.get('http://localhost/api/feed/latest', () => HttpResponse.json({
    ok: true,
    data: { schema_version: 2, items: [{ id: 'article-1', title: 'MSW Feed' }] },
  })),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('api client with MSW', () => {
  it('uses the browser-shaped fetch boundary and unwraps a mocked Feed response', async () => {
    const client = createApiClient({
      fetcher: (input, init) => fetch(new URL(String(input), 'http://localhost'), init),
    })

    await expect(client.get<{ schema_version: number; items: Array<{ id: string }> }>('/api/feed/latest')).resolves.toMatchObject({
      schema_version: 2,
      items: [{ id: 'article-1' }],
    })
  })
})
