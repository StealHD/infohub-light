import type { AgentConnection } from '../../api/agentConnectionService'

const analysisLabels: Record<string, string> = {
  not_configured: '尚未配置，请管理员修复接入', preparing: '正在准备', configuring: '正在配置',
  catalog_ready: '目录已安装，等待分析服务上线', catalog_only: '目录同步正常，任务领取暂未启用',
  ready: '分析服务已就绪', no_authorized_models: '没有获准模型', failed: '配置失败，请管理员修复接入',
  revoking: '正在撤销', removed: '已撤销', offline: '服务离线，请管理员检查',
}

export function AgentCapabilityStatus({ state, connected }: { state: AgentConnection; connected: boolean }) {
  if (!state.can_connect) return null
  return <dl className="grid gap-1 mt-3 type-meta text-muted" aria-label="Agent 能力状态">
    <div><dt className="inline">聊天连接：</dt><dd className="inline">{connected ? '已连接' : '等待连接'}</dd></div>
    <div><dt className="inline">个人数据授权：</dt><dd className="inline">{state.verification.own_content ? '已验证；工具调用需在聊天中核验' : '待验证'}</dd></div>
    <div><dt className="inline">自动化分析：</dt><dd className="inline">{analysisLabels[state.analysis?.phase || 'not_configured'] || '等待核验'}</dd></div>
  </dl>
}
