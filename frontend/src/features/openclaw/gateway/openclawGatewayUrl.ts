function isLoopback(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '')
  return host === 'localhost' || host === '127.0.0.1'
}

function canonicalSocketUrl(parsed: URL): string {
  const path = parsed.pathname === '/' ? '' : parsed.pathname
  return `${parsed.protocol}//${parsed.host}${path}`
}

export function validateGatewayUrl(value: string): string {
  const input = value.trim()
  let parsed: URL
  try {
    parsed = new URL(input)
  } catch {
    throw new Error('请输入有效的 OpenClaw Gateway URL。')
  }
  if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') {
    throw new Error('Gateway URL 必须使用 ws:// 或 wss://。')
  }
  if (parsed.username || parsed.password) {
    throw new Error('Gateway URL 不能包含用户名、密码或其他凭证。')
  }
  if (parsed.search) throw new Error('Gateway URL 不能包含查询参数。')
  if (parsed.hash) throw new Error('Gateway URL 不能包含 fragment。')
  if (parsed.protocol === 'ws:' && !isLoopback(parsed.hostname)) {
    throw new Error('非本机 OpenClaw Gateway 必须使用 WSS。')
  }
  return canonicalSocketUrl(parsed)
}

export function parseOpenClawConnectionInput(gatewayUrl: string, authInput: string): {
  gatewayUrl: string
  bootstrapToken: string
} {
  const input = authInput.trim()
  if (!input) throw new Error('请输入 OpenClaw Gateway token。')
  if (/^https?:\/\//i.test(input)) {
    const dashboard = new URL(input)
    if (dashboard.search) throw new Error('Dashboard 地址不能包含查询参数。')
    const fragment = new URLSearchParams(dashboard.hash.replace(/^#/, ''))
    const bootstrapToken = fragment.get('token')?.trim() || ''
    if (!bootstrapToken) throw new Error('Dashboard 地址中没有找到 token。')
    dashboard.protocol = dashboard.protocol === 'https:' ? 'wss:' : 'ws:'
    dashboard.hash = ''
    return { gatewayUrl: validateGatewayUrl(dashboard.toString()), bootstrapToken }
  }
  return { gatewayUrl: validateGatewayUrl(gatewayUrl), bootstrapToken: input }
}
