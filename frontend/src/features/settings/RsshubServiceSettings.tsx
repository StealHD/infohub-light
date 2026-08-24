import { useRef, useState, type FormEvent, type RefObject } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { useAppContext } from '../../app/AppContext'
import { SettingsDisclosure, SettingsGroup, SettingsSection } from '../../components/settings'
import { actionToast, Button, Icons, Input, Label, Modal, StatusIndicator, StatusNotice, TextField } from '../../design-system'

type RsshubServiceSettingsProps = {
  baseUrl: string
  formRef: RefObject<HTMLFormElement | null>
  isSaving: boolean
  onFormChange: () => void
  onSave: (event: FormEvent<HTMLFormElement>) => void
}

function accessKeyError(caught: unknown, fallback: string) {
  if (caught instanceof ApiError) return caught.message
  if (caught instanceof Error && caught.message) return caught.message
  return fallback
}

function AccessKeyStatus({ source, configured }: { source: 'secret_store' | 'environment' | 'none'; configured: boolean }) {
  if (source === 'environment') return <StatusIndicator label="环境托管" tone="warning" />
  return <StatusIndicator label={configured ? '已配置' : '未配置'} tone={configured ? 'success' : 'neutral'} />
}

export function RsshubServiceSettings({ baseUrl, formRef, isSaving, onFormChange, onSave }: RsshubServiceSettingsProps) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const manageTriggerRef = useRef<HTMLButtonElement>(null)
  const [accessKeyOpen, setAccessKeyOpen] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const accessKey = useQuery({
    queryKey: queryKeys.rsshubAccessKey(user.id),
    queryFn: ({ signal }) => api.rsshubAccessKey(signal),
    staleTime: queryStaleTime.settings,
  })
  const saveAccessKey = useMutation({
    mutationFn: (nextValue: string) => api.saveRsshubAccessKey(nextValue),
    onSuccess: async () => {
      setValue('')
      setError('')
      setAccessKeyOpen(false)
      actionToast.success('RSSHub 访问密钥已保存')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.rsshubAccessKey(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }),
      ])
      queueMicrotask(() => manageTriggerRef.current?.focus())
    },
    onError: (caught) => setError(accessKeyError(caught, '保存访问密钥失败，请稍后重试。')),
  })
  const removeAccessKey = useMutation({
    mutationFn: () => api.deleteRsshubAccessKey(),
    onSuccess: async () => {
      setError('')
      setRemoveOpen(false)
      actionToast.success('RSSHub 访问密钥已移除')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.rsshubAccessKey(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }),
      ])
      queueMicrotask(() => manageTriggerRef.current?.focus())
    },
    onError: (caught) => setError(accessKeyError(caught, '移除访问密钥失败，请稍后重试。')),
  })

  const source = accessKey.data?.management_source ?? 'none'
  const configured = accessKey.data?.configured ?? false
  const busy = saveAccessKey.isPending || removeAccessKey.isPending

  function closeAccessKey() {
    if (busy) return
    setAccessKeyOpen(false)
    setValue('')
    setError('')
    queueMicrotask(() => manageTriggerRef.current?.focus())
  }

  function closeRemove() {
    if (busy) return
    setRemoveOpen(false)
    setError('')
    queueMicrotask(() => manageTriggerRef.current?.focus())
  }

  function submitAccessKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    if (!value) {
      setError('访问密钥不能为空。')
      return
    }
    saveAccessKey.mutate(value)
  }

  const accessKeyAction = accessKey.isPending
    ? <StatusIndicator label="正在检查访问密钥" tone="neutral" />
    : accessKey.isError
      ? <div className="flex flex-wrap items-center gap-2"><StatusIndicator label="状态读取失败" tone="warning" /><Button size="sm" variant="ghost" onPress={() => void accessKey.refetch()}>重试</Button></div>
      : <div className="flex flex-wrap items-center gap-2">
          <AccessKeyStatus source={source} configured={configured} />
          {source === 'environment'
            ? <span className="type-meta text-muted">由部署环境管理</span>
            : <Button ref={manageTriggerRef} size="sm" variant="secondary" onPress={() => { setError(''); setAccessKeyOpen(true) }}><Icons.KeyRound size={15} aria-hidden="true" />{configured ? '更新访问密钥' : '配置访问密钥'}</Button>}
        </div>

  return <SettingsSection title="RSSHub 服务" description="受控来源在运行时通过此服务地址访问，不会向浏览器暴露访问密钥。">
    <SettingsGroup ariaLabel="RSSHub 服务">
      <div data-settings-item className="grid gap-4 p-4 min-[768px]:p-5">
        <div className="flex min-w-0 flex-col gap-3 min-[768px]:flex-row min-[768px]:items-start min-[768px]:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-default text-muted"><Icons.Rss size={17} aria-hidden="true" /></span>
            <div className="min-w-0"><p className="type-control text-foreground">连接地址</p><p className="type-body mt-0.5 text-muted">可使用自建、反向代理前缀或第三方 RSSHub。</p></div>
          </div>
          <div className="min-w-0 shrink-0">{accessKeyAction}</div>
        </div>
        {source === 'environment' && <p className="type-meta text-muted">访问密钥由部署环境注入；如需由页面管理，请先在部署环境移除该变量。</p>}
        <form ref={formRef} className="grid gap-3 min-[640px]:grid-cols-[minmax(0,1fr)_auto] min-[640px]:items-end" onChange={onFormChange} onSubmit={onSave}>
          <TextField fullWidth name="base_url" defaultValue={baseUrl} isRequired><Label>RSSHub Base URL</Label><Input type="url" /></TextField>
          <Button className="w-full min-[640px]:w-auto" type="submit" isDisabled={isSaving}>{isSaving ? '保存中…' : '保存 RSSHub 地址'}</Button>
        </form>
        <SettingsDisclosure title="连接说明" description="了解访问密钥和服务端边界。">
          <p className="type-body text-muted">自建公网实例可使用访问密钥保护；Worker 只发送路由级 code，助手不接收地址或密钥。</p>
        </SettingsDisclosure>
      </div>
    </SettingsGroup>
    <Modal isOpen={accessKeyOpen} onOpenChange={(open) => open ? setAccessKeyOpen(true) : closeAccessKey()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">管理 RSSHub 访问密钥</Modal.Trigger>
      <Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{configured ? '更新 RSSHub 访问密钥' : '配置 RSSHub 访问密钥'}</Modal.Heading></Modal.Header>
        <Modal.Body><form id="rsshub-access-key" className="grid gap-3" onSubmit={submitAccessKey}>
          <TextField fullWidth value={value} onChange={setValue} isRequired><Label>访问密钥</Label><Input type="password" autoComplete="new-password" placeholder="仅提交一次，不会回显" /></TextField>
          <p className="type-meta text-muted">密钥仅写入 SecretStore；保存后 Worker 会在下一次周期读取新值。</p>
          {configured && source === 'secret_store' && <Button size="sm" variant="ghost" className="justify-start text-danger" isDisabled={busy} onPress={() => { setAccessKeyOpen(false); setRemoveOpen(true) }}><Icons.Trash2 size={14} aria-hidden="true" />移除访问密钥</Button>}
          {error && <StatusNotice title={error} status="warning" />}
        </form></Modal.Body>
        <Modal.Footer><Button type="button" variant="ghost" isDisabled={busy} onPress={closeAccessKey}>取消</Button><Button type="submit" form="rsshub-access-key" isDisabled={busy}>{saveAccessKey.isPending ? '保存中…' : '保存访问密钥'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
    <Modal isOpen={removeOpen} onOpenChange={(open) => open ? setRemoveOpen(true) : closeRemove()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">确认移除 RSSHub 访问密钥</Modal.Trigger>
      <Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>移除 RSSHub 访问密钥？</Modal.Heading></Modal.Header>
        <Modal.Body><StatusNotice title="移除后，仍要求访问码的 RSSHub 来源会抓取失败。" status="warning">RSSHub 地址和现有订阅不会被删除。</StatusNotice>{error && <div className="mt-3"><StatusNotice title={error} status="warning" /></div>}</Modal.Body>
        <Modal.Footer><Button type="button" variant="ghost" isDisabled={busy} onPress={closeRemove}>取消</Button><Button type="button" variant="danger" isDisabled={busy} onPress={() => removeAccessKey.mutate()}>{removeAccessKey.isPending ? '移除中…' : '确认移除'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </SettingsSection>
}
