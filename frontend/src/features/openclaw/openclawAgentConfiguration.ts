import type { AgentDelegationAccess } from '../../api/types'

const TOKEN_REFERENCE = '${INTELISCOPE_MCP_TOKEN}'

export const READ_TOOL_FILTER = [
  'get_my_feed',
  'get_item',
  'list_subscriptions',
  'source_health',
  'list_jobs',
  'get_job',
  'get_source_setup_guide',
  'search_bilibili_users',
  'resolve_source',
  'list_available_sources',
  'diagnose_source',
  'diagnose_job',
  'query_operation_logs',
] as const

export const SUBSCRIPTION_WRITE_TOOL_FILTER = [
  ...READ_TOOL_FILTER,
  'prepare_create_subscription',
  'prepare_update_subscription',
  'prepare_delete_subscription',
  'apply_subscription_change',
] as const

export const SYSTEM_SETTINGS_TOOL_FILTER = [
  ...READ_TOOL_FILTER,
  'list_system_settings',
  'prepare_update_system_settings',
  'apply_system_settings_change',
] as const

export function agentConfiguration(mcpUrl: string, access: AgentDelegationAccess = 'read'): string {
  const config = JSON.stringify({
    url: mcpUrl,
    transport: 'streamable-http',
    connectTimeout: 10,
    timeout: 30,
    supportsParallelToolCalls: true,
    headers: { Authorization: `Bearer ${TOKEN_REFERENCE}` },
    toolFilter: { include: access === 'subscriptions_write' ? SUBSCRIPTION_WRITE_TOOL_FILTER : access === 'system_settings_write' ? SYSTEM_SETTINGS_TOOL_FILTER : READ_TOOL_FILTER },
  })
  return [`openclaw mcp set inteliscope '${config}'`, 'openclaw mcp doctor inteliscope --probe', 'openclaw mcp status --verbose', 'openclaw dashboard'].join('\n')
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\"'\"'")}'`
}

export function oneTimeTokenWriteCommand(token: string): string {
  const tokenLine = shellQuote(`INTELISCOPE_MCP_TOKEN=${token}`)
  return [
    'mkdir -p ~/.openclaw',
    'chmod 700 ~/.openclaw',
    `(umask 077; { test -f ~/.openclaw/.env && grep -v '^INTELISCOPE_MCP_TOKEN=' ~/.openclaw/.env || true; printf '%s\\n' ${tokenLine}; } > ~/.openclaw/.env.tmp && mv ~/.openclaw/.env.tmp ~/.openclaw/.env)`,
    'chmod 600 ~/.openclaw/.env',
  ].join(' && ')
}
