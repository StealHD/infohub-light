import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { User } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  AvatarFallback,
  AvatarRoot,
  Button,
  Chip,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  Table,
  TextField,
  toast,
  type SortDescriptor,
} from '../../design-system'
import { canAdministerWorkspace } from '../settings/settingsModel'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'

const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
const messageOf = (caught: unknown, fallback: string) => caught instanceof ApiError || caught instanceof Error ? caught.message : fallback

const memberColumns = [
  { key: 'identity', label: '成员', isRowHeader: true, allowsSorting: true, className: 'min-w-[300px] w-[38%]' },
  { key: 'role', label: '角色', allowsSorting: true, className: 'min-w-[220px] w-[28%]' },
  { key: 'status', label: '账户状态', allowsSorting: true, className: 'min-w-[130px] w-[15%]' },
  { key: 'actions', label: '操作', allowsSorting: false, className: 'min-w-[140px] w-[19%] text-end' },
] as const

type MemberColumnKey = typeof memberColumns[number]['key']

const avatarTones = [
  'from-violet-300 via-fuchsia-300 to-rose-400',
  'from-emerald-300 via-teal-300 to-blue-500',
  'from-amber-200 via-orange-300 to-rose-500',
  'from-sky-200 via-cyan-300 to-violet-500',
] as const

const roleOrder: Record<User['role'], number> = {
  owner: 0,
  admin: 1,
  member: 2,
  viewer: 3,
}

const memberCollator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

function avatarTone(username: string) {
  let hash = 0
  for (const character of username) hash = ((hash << 5) - hash + character.codePointAt(0)!) | 0
  return avatarTones[Math.abs(hash) % avatarTones.length]
}

function memberInitial(member: User) {
  return (member.display_name || member.username).trim().slice(0, 1).toUpperCase()
}

function compareMembers(a: User, b: User, column: MemberColumnKey) {
  switch (column) {
    case 'identity':
      return memberCollator.compare(a.display_name || a.username, b.display_name || b.username)
        || memberCollator.compare(a.username, b.username)
    case 'role':
      return roleOrder[a.role] - roleOrder[b.role]
    case 'status':
      return Number(b.enabled) - Number(a.enabled)
    case 'actions':
      return 0
  }
}

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
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetError, setResetError] = useState('')
  const [sortDescriptor, setSortDescriptor] = useState<SortDescriptor>({
    column: 'identity',
    direction: 'ascending',
  })

  const sortedMembers = useMemo(() => {
    const source = users.data?.users ?? []
    const column = sortDescriptor.column as MemberColumnKey
    const direction = sortDescriptor.direction === 'descending' ? -1 : 1
    return source
      .map((member, index) => ({ member, index }))
      .sort((left, right) => direction * compareMembers(left.member, right.member, column) || left.index - right.index)
      .map(({ member }) => member)
  }, [sortDescriptor, users.data?.users])

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

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.updateUser(id, { password }),
    onMutate: ({ id }) => feedback.begin('member-password-reset', id),
    onSuccess: async (_result, { id }) => {
      feedback.succeed('member-password-reset', id)
      setResetTarget(null)
      setResetError('')
      await queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) })
      toast.success('成员密码已重置', { description: '新密码已生效。', timeout: 4000 })
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '密码重置失败。')
      setResetError(message)
      feedback.fail('member-password-reset', id, message)
      toast.danger('密码重置失败', { description: message, timeout: 8000 })
    },
  })

  async function resetMemberPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!resetTarget) return
    const data = new FormData(event.currentTarget)
    const password = String(data.get('password') ?? '')
    const confirmation = String(data.get('confirmation') ?? '')
    if (password.length < 8) {
      setResetError('新密码至少需要 8 个字符。')
      return
    }
    if (password !== confirmation) {
      setResetError('两次输入的新密码不一致。')
      return
    }
    setResetError('')
    try {
      await resetPasswordMutation.mutateAsync({ id: resetTarget.id, password })
    } catch {
      // Mutation feedback is rendered in the dialog so the user can correct and retry.
    }
  }

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

  function renderMemberCell(member: User, columnKey: MemberColumnKey) {
    const pending = feedback.isPending('member-update', member.id)
      || feedback.isPending('member-password-reset', member.id)

    switch (columnKey) {
      case 'identity':
        return <div className="flex min-w-0 items-center gap-3">
          <AvatarRoot
            aria-hidden="true"
            className={`size-10 shrink-0 bg-gradient-to-br ${avatarTone(member.username)} shadow-sm ring-1 ring-white/10`}
          >
            <AvatarFallback className="type-control bg-transparent text-black/70">{memberInitial(member)}</AvatarFallback>
          </AvatarRoot>
          <div className="min-w-0">
            <strong className="type-body block truncate">{member.display_name || member.username}</strong>
            <span className="type-meta block truncate text-muted">@{member.username}</span>
          </div>
        </div>
      case 'role':
        return member.role === 'owner'
          ? <Chip size="sm" variant="soft">
            <Icons.ShieldCheck size={13} aria-hidden="true" />
            <Chip.Label>所有者 · 受保护</Chip.Label>
          </Chip>
          : <div className="min-w-44">
            <HeroSelect
              label={`角色 ${member.username}`}
              value={member.role}
              onChange={(role) => memberMutation.mutate({ id: member.id, patch: { role } })}
              isDisabled={pending}
              options={[
                { id: 'admin', label: '管理员' },
                { id: 'member', label: '成员' },
                { id: 'viewer', label: '只读成员' },
              ]}
              hideLabel
              className="min-w-0"
              triggerClassName="border-transparent bg-transparent shadow-none hover:bg-default/70"
            />
          </div>
      case 'status':
        return <Chip size="sm" color={member.enabled ? 'success' : 'danger'} variant="soft">
          <Chip.Label>{member.enabled ? '已启用' : '已停用'}</Chip.Label>
        </Chip>
      case 'actions':
        return <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant={member.enabled && member.role !== 'owner' ? 'danger-soft' : 'tertiary'}
            isIconOnly
            className="size-9 rounded-full"
            aria-label={`切换 ${member.username} 状态`}
            isDisabled={member.role === 'owner' || pending}
            onPress={() => memberMutation.mutate({ id: member.id, patch: { enabled: !member.enabled } })}
          >
            {pending
              ? <Icons.LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
              : member.role === 'owner'
                ? <Icons.LockKeyhole size={16} aria-hidden="true" />
                : <Icons.Power size={16} aria-hidden="true" />}
          </Button>
          {member.role !== 'owner' && <Button
            size="sm"
            variant="tertiary"
            isIconOnly
            className="size-9 rounded-full"
            aria-label={`重置 ${member.username} 密码`}
            isDisabled={pending}
            onPress={() => {
              setResetError('')
              setResetTarget(member)
            }}
          >
            <Icons.KeyRound size={16} aria-hidden="true" />
          </Button>}
        </div>
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
      {!users.isLoading && !users.isError && <Table className="mt-5 overflow-hidden rounded-[22px] border border-separator bg-surface-secondary shadow-sm" variant="secondary">
        <Table.ScrollContainer className="max-w-full overflow-x-auto overscroll-x-contain rounded-[22px]">
          <Table.Content
            aria-label="成员列表"
            className="min-w-[820px]"
            sortDescriptor={sortDescriptor}
            onSortChange={setSortDescriptor}
          >
            <Table.Header className="bg-default/55">
              {memberColumns.map((column) => <Table.Column
                key={column.key}
                id={column.key}
                isRowHeader={'isRowHeader' in column && column.isRowHeader}
                allowsSorting={column.allowsSorting}
                className={`h-12 px-5 type-meta text-muted ${column.className}`}
              >
                {column.allowsSorting
                  ? ({ sortDirection }) => <Table.SortableColumnHeader sortDirection={sortDirection}>
                    {column.label}
                  </Table.SortableColumnHeader>
                  : column.label}
              </Table.Column>)}
            </Table.Header>
            <Table.Body>{sortedMembers.map((member) => <Table.Row
              key={member.id}
              id={member.id}
              className="border-b border-separator bg-surface-secondary transition-colors last:border-b-0 hover:bg-default/35"
            >
              {memberColumns.map((column) => <Table.Cell key={column.key} className="h-[76px] px-5 py-3">
                {renderMemberCell(member, column.key)}
              </Table.Cell>)}
            </Table.Row>)}</Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>}
    </AdminSection>}
  </PageFrame>
  <Modal isOpen={Boolean(resetTarget)} onOpenChange={(open) => !open && !resetPasswordMutation.isPending && setResetTarget(null)}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开重置成员密码</Modal.Trigger>
    <Modal.Backdrop isDismissable={!resetPasswordMutation.isPending} isKeyboardDismissDisabled={resetPasswordMutation.isPending}>
      <Modal.Container size="md">
        <Modal.Dialog>
          <Modal.Header><Modal.Heading>重置成员密码</Modal.Heading></Modal.Header>
          <Modal.Body>
            <p className="type-body mb-4 text-muted">为 {resetTarget?.display_name || resetTarget?.username} 设置新密码；保存后旧密码立即失效。</p>
            <form id="member-password-reset-form" className="grid gap-3" onSubmit={resetMemberPassword}>
              <TextField fullWidth name="password" isRequired><Label>新密码</Label><Input type="password" autoComplete="new-password" minLength={8} /></TextField>
              <TextField fullWidth name="confirmation" isRequired><Label>确认新密码</Label><Input type="password" autoComplete="new-password" minLength={8} /></TextField>
              {resetError && <HeroNotice title={resetError} />}
            </form>
          </Modal.Body>
          <Modal.Footer>
            <Button type="button" variant="ghost" isDisabled={resetPasswordMutation.isPending} onPress={() => setResetTarget(null)}>取消</Button>
            <Button type="submit" form="member-password-reset-form" isDisabled={resetPasswordMutation.isPending}>{resetPasswordMutation.isPending ? '重置中…' : '确认重置'}</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  </Modal>
  </div>
}
