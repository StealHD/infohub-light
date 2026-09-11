import type { OpenClawFailureDiagnostic } from '../chat/openclawFailureDiagnostic'
import { openClawSafeError } from '../chat/openclawSafeError'

export function OpenClawFailureNotice({ diagnostic, text }: { diagnostic: OpenClawFailureDiagnostic; text: string }) {
  const reason = openClawSafeError(diagnostic.code)
  return <div className="type-label mt-1.5 min-w-0 break-words text-muted" role="status">
    {reason !== text && <div>{reason}</div>}
    <div>本次实际模型：{diagnostic.actualModelId ?? '未知'}</div>
    {diagnostic.runId && <div>运行编号：{diagnostic.runId}</div>}
  </div>
}
