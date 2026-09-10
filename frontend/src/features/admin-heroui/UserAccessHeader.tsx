import { Link } from 'react-router-dom'
import { useAppContext } from '../../app/AppContext'
import { AdminPageHeader } from './HeroAdminControls'
import { canAdministerWorkspace } from '../settings/settingsModel'

export function UserAccessHeader({ description }: { description: string }) {
  const { user } = useAppContext()
  return <div className="grid gap-3">
    <AdminPageHeader description={description} />
    {canAdministerWorkspace(user) && <Link className="type-control underline w-fit" to="/agents?tab=requests">处理 Agent 接入申请</Link>}
  </div>
}
