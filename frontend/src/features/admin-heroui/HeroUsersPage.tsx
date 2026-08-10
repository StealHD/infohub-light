import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type { User } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
  AvatarFallback,
  AvatarRoot,
  Button,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  StatusIndicator,
  Table,
  TextField,
  type SortDescriptor,
} from '../../design-system'
import { canAdministerWorkspace } from '../settings/settingsModel'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'

const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
const messageOf = (caught: unknown, fallback: string) => caught instanceof ApiError || caught instanceof Error ? caught.message : fallback

const memberColumns = [
  { key: 'identity', label: '成员', isRowHeader: true, allowsSorting: true, className: 'min-w-[280px] w-[32%]' },
  { key: 'role', label: '角色', allowsSorting: true, className: 'min-w-[200px] w-[25%]' },
  { key: 'status', label: '账户状态', allowsSorting: true, className: 'min-w-[130px] w-[15%]' },
  { key: 'actions', label: '操作', allowsSorting: false, className: 'min-w-[240px] w-[28%] text-end' },
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
      actionToast.success('密码已更新', { description: '下次登录请使用新密码。' })
    } catch (caught) {
      const message = messageOf(caught, '密码修改失败。')
      setError(message)
      actionToast.danger('密码修改失败', { description: message })
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
  const users = useQuery({ queryKey: queryKeys.users(user.id), queryFn: ({ signal }) => api.users(signal), enabled: admin, staleTime: queryStaleTime.settings })
  const [newUserRole, setNewUserRole] = useState('member')
  const [createError, setCreateError] = useState('')
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetError, setResetError] = useState('')
  const [renameTarget, setRenameTarget] = useState<User | null>(null)
  const [renameUsername, setRenameUsername] = useState('')
  const [renameError, setRenameError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deleteError, setDeleteError] = useState('')
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
      feedback.clear('member-update', id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) }),
        id === user.id
          ? queryClient.invalidateQueries({ queryKey: queryKeys.auth })
          : Promise.resolve(),
      ])
      actionToast.success('成员设置已保存')
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '成员更新失败。')
      feedback.clear('member-update', id)
      actionToast.danger('成员更新失败', { description: message })
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
      actionToast.success('成员密码已重置', { description: '新密码已生效。' })
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '密码重置失败。')
      setResetError(message)
      feedback.fail('member-password-reset', id, message)
      actionToast.danger('密码重置失败', { description: message })
    },
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, username }: { id: string; username: string }) => api.updateUser(id, { username }),
    onMutate: ({ id }) => feedback.begin('member-rename', id),
    onSuccess: async (_result, { id }) => {
      feedback.clear('member-rename', id)
      setRenameTarget(null)
      setRenameUsername('')
      setRenameError('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) }),
        id === user.id
          ? queryClient.invalidateQueries({ queryKey: queryKeys.auth })
          : Promise.resolve(),
      ])
      actionToast.success('成员用户名已修改')
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '用户名修改失败。')
      feedback.clear('member-rename', id)
      setRenameError(message)
      actionToast.danger('用户名修改失败', { description: message })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id }: { id: string }) => api.deleteUser(id),
    onMutate: ({ id }) => feedback.begin('member-delete', id),
    onSuccess: async (_result, { id }) => {
      feedback.clear('member-delete', id)
      setDeleteTarget(null)
      setDeleteConfirmation('')
      setDeleteError('')
      await queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) })
      actionToast.success('成员账号已删除')
    },
    onError: (caught, { id }) => {
      const message = messageOf(caught, '账号删除失败。')
      feedback.clear('member-delete', id)
      setDeleteError(message)
      actionToast.danger('账号删除失败', { description: message })
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

  async function renameMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!renameTarget) return
    const username = renameUsername.trim()
    if (!username) {
      setRenameError('用户名不能为空。')
      return
    }
    setRenameError('')
    try {
      await renameMutation.mutateAsync({ id: renameTarget.id, username })
    } catch {
      // Mutation feedback remains in the dialog so the user can correct and retry.
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
      setCreateError('')
      feedback.clear('member-create', 'new')
      await queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) })
      actionToast.success('成员已创建')
    } catch (caught) {
      const message = messageOf(caught, '成员创建失败。')
      setCreateError(message)
      feedback.clear('member-create', 'new')
      actionToast.danger('成员创建失败', { description: message })
    }
  }

  function renderMemberCell(member: User, columnKey: MemberColumnKey) {
    const pending = feedback.isPending('member-update', member.id)
      || feedback.isPending('member-password-reset', member.id)
      || feedback.isPending('member-rename', member.id)
      || feedback.isPending('member-delete', member.id)

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
          ? <span className="type-meta inline-flex items-center gap-1.5 text-muted">
            <Icons.ShieldCheck size={13} aria-hidden="true" />所有者 · 受保护
          </span>
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
        return <StatusIndicator
          label={member.enabled ? '已启用' : '已停用'}
          tone={member.enabled ? 'success' : 'danger'}
          icon={member.enabled
            ? <Icons.CircleCheck size={13} aria-hidden="true" />
            : <Icons.CircleX size={13} aria-hidden="true" />}
        />
      case 'actions':
        return <div className="flex items-center justify-end gap-2">
          {member.role !== 'owner' && <Button
            size="sm"
            variant="tertiary"
            isIconOnly
            className="size-9 rounded-full"
            aria-label={`修改 ${member.username} 用户名`}
            isDisabled={pending}
            onPress={() => {
              setRenameTarget(member)
              setRenameUsername(member.username)
              setRenameError('')
            }}
          >
            <Icons.Pencil size={16} aria-hidden="true" />
          </Button>}
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
          {member.role !== 'owner' && member.id !== user.id && <Button
            size="sm"
            variant="danger-soft"
            isIconOnly
            className="size-9 rounded-full"
            aria-label={`删除 ${member.username} 账号`}
            isDisabled={pending}
            onPress={() => {
              setDeleteTarget(member)
              setDeleteConfirmation('')
              setDeleteError('')
            }}
          >
            <Icons.Trash2 size={16} aria-hidden="true" />
          </Button>}
        </div>
    }
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username}`} />
    <AccountPasswordSection />
    {admin && <AdminSection title="成员管理" description="创建成员，并管理用户名、角色与账户可用状态。">
      <form className="grid gap-3 min-[760px]:grid-cols-5" onSubmit={createUser}>
        <TextField fullWidth name="username" isRequired><Label>用户名</Label><Input /></TextField>
        <TextField fullWidth name="display_name"><Label>显示名</Label><Input /></TextField>
        <TextField fullWidth name="password" isRequired><Label>初始密码</Label><Input type="password" autoComplete="new-password" /></TextField>
        <HeroSelect label="角色" value={newUserRole} onChange={setNewUserRole} options={[{ id: 'admin', label: '管理员' }, { id: 'member', label: '成员' }, { id: 'viewer', label: '只读成员' }]} />
        <Button className="self-end" type="submit" isDisabled={feedback.isPending('member-create', 'new')}><Icons.UserPlus size={15} />{feedback.isPending('member-create', 'new') ? '创建中…' : '新增成员'}</Button>
        {createError && <div className="min-[760px]:col-span-5"><HeroNotice title={createError} /></div>}
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
  <Modal isOpen={Boolean(renameTarget)} onOpenChange={(open) => {
    if (!open && !renameMutation.isPending) {
      setRenameTarget(null)
      setRenameUsername('')
      setRenameError('')
    }
  }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开修改用户名</Modal.Trigger>
    <Modal.Backdrop isDismissable={!renameMutation.isPending} isKeyboardDismissDisabled={renameMutation.isPending}>
      <Modal.Container size="sm">
        <Modal.Dialog>
          <Modal.Header><Modal.Heading>修改成员用户名</Modal.Heading></Modal.Header>
          <Modal.Body>
            <p className="type-body mb-4 text-muted">修改后，{renameTarget?.display_name || renameTarget?.username} 下次登录需要使用新用户名；现有登录会话保持有效。</p>
            <form id="member-username-form" onSubmit={renameMember}>
              <TextField fullWidth isRequired value={renameUsername} onChange={setRenameUsername}>
                <Label>新用户名</Label>
                <Input autoFocus autoComplete="username" maxLength={80} />
              </TextField>
              {renameError && <div className="mt-3"><HeroNotice title={renameError} /></div>}
            </form>
          </Modal.Body>
          <Modal.Footer>
            <Button type="button" variant="ghost" isDisabled={renameMutation.isPending} onPress={() => {
              setRenameTarget(null)
              setRenameUsername('')
              setRenameError('')
            }}>取消</Button>
            <Button type="submit" form="member-username-form" isDisabled={!renameUsername.trim() || renameMutation.isPending}>
              {renameMutation.isPending ? '保存中…' : '保存用户名'}
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  </Modal>
  <Modal isOpen={Boolean(deleteTarget)} onOpenChange={(open) => {
    if (!open && !deleteMutation.isPending) {
      setDeleteTarget(null)
      setDeleteConfirmation('')
      setDeleteError('')
    }
  }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开删除成员账号</Modal.Trigger>
    <Modal.Backdrop isDismissable={!deleteMutation.isPending} isKeyboardDismissDisabled={deleteMutation.isPending}>
      <Modal.Container size="sm">
        <Modal.Dialog>
          <Modal.Header><Modal.Heading>删除成员账号</Modal.Heading></Modal.Header>
          <Modal.Body>
            <p className="type-body mb-4 text-muted">删除“{deleteTarget?.display_name || deleteTarget?.username}”后，登录会话和用户数据会被移除，私人来源配置会被清除。此操作无法恢复。</p>
            <TextField fullWidth isRequired value={deleteConfirmation} onChange={setDeleteConfirmation}>
              <Label>输入用户名 {deleteTarget?.username ?? ''} 以确认</Label>
              <Input autoFocus autoComplete="off" />
            </TextField>
            {deleteError && <div className="mt-3"><HeroNotice title={deleteError} /></div>}
          </Modal.Body>
          <Modal.Footer>
            <Button type="button" variant="ghost" isDisabled={deleteMutation.isPending} onPress={() => {
              setDeleteTarget(null)
              setDeleteConfirmation('')
              setDeleteError('')
            }}>取消</Button>
            <Button
              type="button"
              variant="danger"
              isDisabled={deleteConfirmation !== deleteTarget?.username || deleteMutation.isPending}
              onPress={() => deleteTarget && deleteMutation.mutate({ id: deleteTarget.id })}
            >
              {deleteMutation.isPending ? '删除中…' : '确认删除账号'}
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  </Modal>
  </div>
}
