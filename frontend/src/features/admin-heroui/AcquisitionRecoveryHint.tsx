import { Link } from 'react-router-dom'
import type { CatalogSource } from '../../api/types'
import { sourceAcquisitionIssue } from './subscriptionAcquisitionState'

export function AcquisitionRecoveryHint({ source, canManageActors }: { source: CatalogSource; canManageActors: boolean }) {
  if (!sourceAcquisitionIssue(source)) return null
  return canManageActors
    ? <Link to="/settings/actorops" aria-label="配置 Bilibili 主备" className="type-meta rounded text-accent underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-focus">配置主备</Link>
    : <span className="type-meta">请联系管理员配置主备</span>
}
