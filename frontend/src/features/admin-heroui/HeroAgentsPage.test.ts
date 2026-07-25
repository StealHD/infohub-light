import { describe, expect, it } from 'vitest'

import {
  READ_TOOL_FILTER,
  SUBSCRIPTION_WRITE_TOOL_FILTER,
  agentConfiguration,
} from './HeroAgentsPage'

describe('Hero Agents OpenClaw configuration', () => {
  it('keeps read and subscription-management tool filters exact', () => {
    expect(READ_TOOL_FILTER).toEqual([
      'get_my_feed',
      'get_item',
      'list_subscriptions',
      'source_health',
      'list_jobs',
      'get_job',
      'get_source_setup_guide',
      'search_bilibili_users',
      'list_available_sources',
      'diagnose_source',
      'diagnose_job',
      'query_operation_logs',
    ])
    expect(SUBSCRIPTION_WRITE_TOOL_FILTER).toEqual([
      ...READ_TOOL_FILTER,
      'prepare_create_subscription',
      'prepare_update_subscription',
      'prepare_delete_subscription',
      'apply_subscription_change',
    ])
  })

  it('renders only an environment placeholder and never an MCP token value', () => {
    const read = agentConfiguration('https://rb.jiefs.top/mcp', 'read')
    const write = agentConfiguration('https://rb.jiefs.top/mcp', 'subscriptions_write')
    expect(read).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(read).not.toContain('prepare_create_subscription')
    expect(write).toContain('prepare_create_subscription')
    expect(write).toContain('apply_subscription_change')
  })
})
