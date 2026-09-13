import type { NotificationEmailProvider } from '../../api/types'
import { Input, Label, TextField } from '../../design-system'
import { HeroSelect } from '../admin-heroui/HeroAdminControls'
import type { EmailDraft } from './notificationServiceModel'

export function EmailCredentialFields({
  draft,
  onChange,
  providers,
  credentialConfigured,
}: {
  draft: EmailDraft
  onChange: (draft: EmailDraft) => void
  providers: Array<{
    provider: NotificationEmailProvider
    label: string
    credential_label: string
  }>
  credentialConfigured: boolean
}) {
  const preset = providers.find((option) => option.provider === draft.provider)
  const usesSes = draft.provider === 'amazon_ses'
  return <>
    <HeroSelect label="邮件服务商" value={draft.provider} className="w-full" options={providers.map((option) => ({ id: option.provider, label: option.label }))} onChange={(value) => onChange({ ...draft, provider: value as NotificationEmailProvider, credential: '' })} />
    <TextField fullWidth value={draft.senderEmail} onChange={(value) => onChange({ ...draft, senderEmail: value })}>
      <Label>发件邮箱</Label>
      <Input type="email" autoComplete="email" />
    </TextField>
    <TextField fullWidth value={draft.senderName} onChange={(value) => onChange({ ...draft, senderName: value })}>
      <Label>发件名称</Label>
      <Input maxLength={80} />
    </TextField>
    <TextField fullWidth value={draft.credential} onChange={(value) => onChange({ ...draft, credential: value })}>
      <Label>{preset?.credential_label ?? '授权码或 API Key'}{credentialConfigured ? '（可留空复用）' : ''}</Label>
      <Input type="password" autoComplete="new-password" placeholder={credentialConfigured ? '留空复用已配置凭据' : '保存后不会回显'} />
    </TextField>
    {usesSes && <>
      <TextField fullWidth value={draft.region} onChange={(value) => onChange({ ...draft, region: value })}>
        <Label>Amazon SES Region</Label>
        <Input placeholder="例如：ap-northeast-1" />
      </TextField>
      <TextField fullWidth value={draft.smtpUsername} onChange={(value) => onChange({ ...draft, smtpUsername: value })}>
        <Label>SES SMTP 用户名</Label>
        <Input autoComplete="off" />
      </TextField>
    </>}
  </>
}
