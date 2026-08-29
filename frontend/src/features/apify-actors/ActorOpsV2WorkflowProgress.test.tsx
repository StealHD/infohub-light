import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ActorOpsV2Candidate } from '../../api/actorOpsV2Types'
import { ActorOpsV2RouteWorkflowSummary } from './ActorOpsV2WorkflowProgress'

const candidate: ActorOpsV2Candidate = {
  candidate_id: 'candidate-1', build_number: '1', lifecycle: 'static_valid', assignment: 'inactive', priority: null, generation: 1,
  operational_status: 'normal', issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready',
  store_metadata: null, evidence_progress: { verified_bindings: 0, required_bindings: 2 },
}

describe('ActorOpsV2RouteWorkflowSummary', () => {
  it('shows durable replacement phase, source progress, and pending cost', () => {
    render(<ActorOpsV2RouteWorkflowSummary workflow={{
      discovery: null,
      replacement: {
        plan_id: 'plan-1', target_assignment: 'active', target_priority: 0, status: 'running', generation: 2,
        binding_count: 2, per_probe_cap_usd: 0.05, total_cap_usd: 0.10, error_code: null,
        phase: 'dataset_read', progress: { verified_bindings: 1, required_bindings: 2, completed_attempts: 1, attempt_count: 2, pending_attempts: 1 },
        cost_summary: { finalized_usd: 0.02, pending: true }, candidate,
      },
    }} />)

    expect(screen.getByText('处理中')).toBeInTheDocument()
    expect(screen.getByText('读取本次 Dataset · 1/2 个来源 · 费用待对账')).toBeInTheDocument()
  })

  it('shows the exact active discovery stage', () => {
    render(<ActorOpsV2RouteWorkflowSummary workflow={{
      replacement: null,
      discovery: {
        discovery_id: 'discovery-1', trigger_reason: 'operator', status: 'running', stage: 'mapping', stage_attempt: 1,
        candidate_count: 3, rejection_count: 1, error_code: null, created_at: '2026-08-29T00:00:00Z', terminal_at: null, updated_at: '2026-08-29T00:01:00Z',
      },
    }} />)

    expect(screen.getByText('搜索中')).toBeInTheDocument()
    expect(screen.getByText('分析字段合同')).toBeInTheDocument()
  })
})
