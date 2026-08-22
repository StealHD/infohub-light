import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  actionToast,
  Button,
  FieldError,
  Icons,
  Input,
  Label,
  Modal,
  StatusIndicator,
  TextField,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'
import { OpenClawCredentialVault } from '../openclaw/openclawCredentialVault'
import { forgetOpenClawBrowser } from '../openclaw/openclawDevice'
import { validateGatewayUrl } from '../openclaw/openclawGateway'
import { clearOpenClawTranscript, readSavedGatewayUrl, saveGatewayUrl } from '../openclaw/useOpenClawChat'
import { AdminSection, HeroNotice } from './HeroAdminControls'

function DialogFrame({ title, children, footer, dismissable = true }: {
  title: string
  children: ReactNode
  footer: ReactNode
  dismissable?: boolean
}) {
  return <Modal.Backdrop isDismissable={dismissable} isKeyboardDismissDisabled={!dismissable}>
    <Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header>
      <Modal.Body>{children}</Modal.Body><Modal.Footer>{footer}</Modal.Footer>
    </Modal.Dialog></Modal.Container>
  </Modal.Backdrop>
}

export function OpenClawBrowserSettings({
  userId,
  enabled,
  defaultUrl,
  targetVersion,
  vault: providedVault,
  forgetBrowser = forgetOpenClawBrowser,
}: {
  userId: string
  enabled: boolean
  defaultUrl: string
  targetVersion: string
  vault?: OpenClawCredentialVault
  forgetBrowser?: typeof forgetOpenClawBrowser
}) {
  const [url, setUrl] = useState(() => readSavedGatewayUrl(userId, defaultUrl))
  const [paired, setPaired] = useState<boolean | null>(null)
  const [urlError, setUrlError] = useState('')
  const [forgetError, setForgetError] = useState('')
  const [forgetOpen, setForgetOpen] = useState(false)
  const [forgetPending, setForgetPending] = useState(false)
  const saveAddressRef = useRef<HTMLButtonElement>(null)
  const forgetTriggerRef = useRef<HTMLButtonElement>(null)
  const defaultVault = useMemo(() => new OpenClawCredentialVault(), [])
  const vault = providedVault ?? defaultVault

  useEffect(() => {
    let cancelled = false
    void vault.load(userId, url).then((credential) => {
      if (!cancelled) setPaired(Boolean(credential))
    }).catch(() => {
      if (!cancelled) setPaired(false)
    })
    return () => { cancelled = true }
  }, [url, userId, vault])

  function saveUrl() {
    try {
      const normalized = validateGatewayUrl(url)
      saveGatewayUrl(userId, normalized)
      setUrl(normalized)
      setUrlError('')
      actionToast.success('Gateway 地址已保存')
    } catch (error) {
      setUrlError(error instanceof Error ? error.message : 'Gateway 地址无效。')
    }
  }

  function closeForgetDialog() {
    setForgetOpen(false)
    setForgetError('')
    window.requestAnimationFrame(() => {
      ;(forgetTriggerRef.current ?? saveAddressRef.current)?.focus()
    })
  }

  async function confirmForget() {
    setForgetPending(true)
    setForgetError('')
    try {
      const gatewayUrl = validateGatewayUrl(url)
      const result = await forgetBrowser({
        userId,
        gatewayUrl,
        vault,
        clearTranscripts: clearOpenClawTranscript,
      })
      setPaired(false)
      closeForgetDialog()
      actionToast.success(result === 'not-paired'
        ? '当前浏览器已无可删除的 OpenClaw 配对'
        : 'OpenClaw 服务端设备和当前浏览器配对已删除')
    } catch (error) {
      setForgetError(error instanceof Error ? error.message : '无法移除 OpenClaw 浏览器配对；本地凭据已保留。')
    } finally {
      setForgetPending(false)
    }
  }

  return <>
    <AdminSection
      title="OpenClaw 对话连接"
      description={`浏览器直连你的 OpenClaw Gateway；目标版本 ${targetVersion}。Gateway token 不会发送到 Inscope 服务器。`}
    >
      {!enabled && <HeroNotice title="管理员尚未启用站内 OpenClaw 对话；信息流仍提供复制交接模式。" status="warning" role="status" />}
      <div className="mt-3 grid gap-3 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end">
        <TextField fullWidth value={url} onChange={(value) => { setUrl(value); setUrlError('') }} isInvalid={Boolean(urlError)}>
          <Label>OpenClaw Gateway URL</Label>
          <Input aria-label="OpenClaw Gateway URL" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
          {urlError && <FieldError>{urlError}</FieldError>}
        </TextField>
        <div className="flex flex-wrap items-center gap-2">
          <Button ref={saveAddressRef} size="sm" variant="ghost" onPress={saveUrl}>保存地址</Button>
          {paired && <Tooltip delay={250}>
            <TooltipTriggerButton
              ref={forgetTriggerRef}
              aria-label="忘记此浏览器"
              disabled={forgetPending}
              className="size-8 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
              onClick={() => { setForgetError(''); setForgetOpen(true) }}
            ><Icons.Unplug size={16} aria-hidden="true" /></TooltipTriggerButton>
            <Tooltip.Content {...topAnchoredTooltipProps}>忘记此浏览器</Tooltip.Content>
          </Tooltip>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusIndicator
          iconOnly
          label={paired === null ? '正在检查配对' : paired ? '此浏览器已配对' : '此浏览器未配对'}
          tone={paired === null ? 'accent' : paired ? 'success' : 'neutral'}
          icon={paired === null
            ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            : paired
              ? <Icons.CircleCheck size={13} aria-hidden="true" />
              : <Icons.CircleDashed size={13} aria-hidden="true" />}
        />
        {enabled && <a className="type-control text-accent" href="/feed">打开信息流对话面板</a>}
      </div>
      <p className="type-meta mt-2 text-muted">确认忘记后会先从 OpenClaw Gateway 移除当前设备；只有服务端成功或设备已不存在时，才会清除本地对话和配对凭据。</p>
      <p className="type-meta mt-3 text-muted">本地只允许 ws://127.0.0.1 或 ws://localhost；远程 Gateway 必须使用 wss://。首次 token 只在对话面板输入。</p>
    </AdminSection>
    <Modal isOpen={forgetOpen} onOpenChange={(open) => {
      if (forgetPending) return
      if (open) setForgetOpen(true)
      else closeForgetDialog()
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开移除浏览器配对</Modal.Trigger>
      <DialogFrame
        title="移除 OpenClaw 浏览器配对"
        dismissable={!forgetPending}
        footer={<>
          <Button variant="ghost" isDisabled={forgetPending} onPress={closeForgetDialog}>取消</Button>
          <Button variant="danger" isDisabled={forgetPending} onPress={() => void confirmForget()}>
            {forgetPending ? '正在移除…' : '确认移除并忘记'}
          </Button>
        </>}
      >
        <p className="type-body text-muted">这会让当前浏览器设备失去 OpenClaw 访问权限，并删除此用户在该 Gateway 下的本地对话与配对凭据。服务端拒绝时，本地恢复材料会保留。</p>
        {forgetError && <div className="mt-4"><HeroNotice title={forgetError} /></div>}
      </DialogFrame>
    </Modal>
  </>
}
