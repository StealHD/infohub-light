import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Button,
  Card,
  Chip,
  Icons,
  Input,
  Label,
  LoadingState,
  PageFrame,
  TextField,
  toast,
} from '../../design-system'
import { canAdministerWorkspace } from '../settings/settingsModel'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'

const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
const messageOf = (caught: unknown, fallback: string) => caught instanceof ApiError || caught instanceof Error ? caught.message : fallback

function AccountPasswordSection() {
  const { api } = useAppContext()
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) => api.changePassword(currentPassword, newPassword),
  })

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const currentPassword = String(data.get('current_password') ?? '')
    const newPassword = String(data.get('new_password') ?? '')
    const confirmation = String(data.get('confirmation') ?? '')
    if (newPassword !== confirmation) {
      setError('两次输入的新密码不一致。')
      return
    }
    setError('')
    try {
      await mutation.mutateAsync({ currentPassword, newPassword })
      form.reset()
      toast.success('密码已更新', { description: '下次登录请使用新密码。', timeout: 4000 })
    } catch (caught) {
      const message = messageOf(caught, '密码修改失败。')
      setError(message)
      toast.danger('密码修改失败', { description: message, timeout: 8000 })
    }
  }

  return <AdminSection title="账户安全" description="修改当前登录账户的密码；密码不会在页面中回显。">
    <form className="grid gap-3 min-[760px]:grid-cols-3" onSubmit={submit}>
      <TextField fullWidth name="current_password" isRequired><Label>当前密码</Label><Input type="password" autoComplete="current-password" /></TextField>
      <TextField fullWidth name="new_password" isRequired><Label>新密码</Label><Input type="password" autoComplete="new-password" minLength={8} /></TextField>
      <TextField fullWidth name="confirmation" isRequired><Label>确认新密码</Label><Input type="password" autoComplete="new-password" minLength={8} /></TextField>
      <Button className="w-fit" type="submit" isDisabled={mutation.isPending}><Icons.KeyRound size={15} />{mutation.isPending ? '更新中…' : '更新密码'}</Button>
    </form>
    {error && <div className="mt-3"><HeroNotice title={error} /></div>}
  </AdminSection>
}

export function HeroUsersPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const admin = canAdministerWorkspace(user)
  const users = useQuery({ queryKey: queryKeys.users(user.id), queryFn: ({ signal }) => api.users(signal), enabled: admin })
  const [newUserRole, setNewUserRole] = useState('member')
  const [error, setError] = useState('')

  const memberMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) => api.updateUser(id, patch),
    onMutate: ({ id }) => feedback.begin('member-update', id),
    onSuccess: async (_result, { id }) => {
      feedback.succeed('member-update', id)
      await queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) })
      toast.success('成员设置已保存', { timeout: 4000 })
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '成员更新失败。')
      setError(message)
      feedback.fail('member-update', id, message)
      toast.danger('成员更新失败', { description: message, timeout: 8000 })
    },
  })

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    feedback.begin('member-create', 'new')
    try {
      await api.createUser({
        username: inputValue(data, 'username'),
        password: String(data.get('password') ?? ''),
        display_name: inputValue(data, 'display_name') || null,
        role: newUserRole,
        enabled: true,
      })
      form.reset()
      feedback.succeed('member-create', 'new')
      await queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) })
      toast.success('成员已创建', { timeout: 4000 })
    } catch (caught) {
      const message = messageOf(caught, '成员创建失败。')
      setError(message)
      feedback.fail('member-create', 'new', message)
      toast.danger('成员创建失败', { description: message, timeout: 8000 })
    }
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username}`} />
    {error && <HeroNotice title={error} />}
    <AccountPasswordSection />
    {admin && <AdminSection title="成员管理" description="创建成员，并管理角色与账户可用状态。">
      <form className="grid gap-3 min-[760px]:grid-cols-5" onSubmit={createUser}>
        <TextField fullWidth name="username" isRequired><Label>用户名</Label><Input /></TextField>
        <TextField fullWidth name="display_name"><Label>显示名</Label><Input /></TextField>
        <TextField fullWidth name="password" isRequired><Label>初始密码</Label><Input type="password" autoComplete="new-password" /></TextField>
        <HeroSelect label="角色" value={newUserRole} onChange={setNewUserRole} options={[{ id: 'admin', label: '管理员' }, { id: 'member', label: '成员' }, { id: 'viewer', label: '只读成员' }]} />
        <Button className="self-end" type="submit" isDisabled={feedback.isPending('member-create', 'new')}><Icons.UserPlus size={15} />{feedback.isPending('member-create', 'new') ? '创建中…' : '新增成员'}</Button>
      </form>
      {users.isLoading && <LoadingState label="正在读取成员" rows={2} />}
      {users.isError && <div className="mt-4"><HeroNotice title="成员列表读取失败" /></div>}
      <div className="mt-5 grid gap-2">{(users.data?.users ?? []).map((member) => {
        const pending = feedback.isPending('member-update', member.id)
        return <Card key={member.id} variant="transparent" className="flex-row flex-wrap items-center gap-3 p-3">
          <div className="min-w-0 flex-1"><Card.Title>{member.display_name || member.username}</Card.Title><Card.Description>{member.username}</Card.Description></div>
          {member.role === 'owner'
            ? <Chip size="sm" variant="soft"><Chip.Label>所有者 · 受保护</Chip.Label></Chip>
            : <HeroSelect label={`角色 ${member.username}`} value={member.role} onChange={(role) => memberMutation.mutate({ id: member.id, patch: { role } })} isDisabled={pending} options={[{ id: 'admin', label: '管理员' }, { id: 'member', label: '成员' }, { id: 'viewer', label: '只读成员' }]} />}
          <Button size="sm" variant="ghost" aria-label={`切换 ${member.username} 状态`} isDisabled={member.role === 'owner' || pending} onPress={() => memberMutation.mutate({ id: member.id, patch: { enabled: !member.enabled } })}>{pending ? '保存中…' : member.enabled ? '停用' : '启用'}</Button>
        </Card>
      })}</div>
    </AdminSection>}
  </PageFrame></div>
}
