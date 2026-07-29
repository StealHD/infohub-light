import type { WebhookProvider, WebhookProviderOption } from '../../api/types'
import {
  Description,
  FieldError,
  Input,
  Label,
  Switch,
  TextField,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'

export function WebhookProviderFields({
  idPrefix,
  provider,
  options,
  destination,
  configured,
  providerExplicit,
  signingEnabled,
  signingSecret,
  signingConfigured,
  destinationRequired,
  destinationLabel = 'Webhook 地址',
  fieldError,
  signingError,
  readOnly = false,
  onProviderChange,
  onDestinationChange,
  onSigningEnabledChange,
  onSigningSecretChange,
}: {
  idPrefix: string
  provider: WebhookProvider
  options: WebhookProviderOption[]
  destination: string
  configured: boolean
  providerExplicit: boolean
  signingEnabled: boolean
  signingSecret: string
  signingConfigured: boolean
  destinationRequired: boolean
  destinationLabel?: string
  fieldError: string
  signingError: string
  readOnly?: boolean
  onProviderChange: (provider: WebhookProvider) => void
  onDestinationChange: (value: string) => void
  onSigningEnabledChange: (value: boolean) => void
  onSigningSecretChange: (value: string) => void
}) {
  const safeOptions = Array.isArray(options) ? options : []
  const selected = safeOptions.find((option) => option.provider === provider)
  const supportsSigning = selected?.signing === 'optional'

  return <fieldset className="grid gap-4 min-[720px]:col-span-2" aria-describedby={`${idPrefix}-help`}>
    <legend className="type-control">Webhook 接收端</legend>
    {!providerExplicit && configured && <HeroNotice
      title="这是升级前保存的 Webhook 配置"
      status="warning"
      role="status"
    >
      当前仍按兼容模式发送。下次修改时，请选择类型并重新输入 Webhook 地址。
    </HeroNotice>}
    <div className="grid gap-4 min-[720px]:grid-cols-2">
      <HeroSelect
        label="Webhook 类型"
        value={provider}
        isDisabled={readOnly}
        onChange={(value) => onProviderChange(value as WebhookProvider)}
        options={safeOptions.map((option) => ({
          id: option.provider,
          label: option.label,
        }))}
      />
      <TextField
        fullWidth
        value={destination}
        onChange={onDestinationChange}
        isDisabled={readOnly}
        isInvalid={Boolean(fieldError)}
        isRequired={!readOnly && destinationRequired}
      >
        <Label>{destinationLabel}</Label>
        <Input
          type="password"
          autoComplete="new-password"
          placeholder={configured ? '留空保持当前配置' : selected?.url_hint || '输入 HTTPS 地址'}
        />
        <Description>
          {configured
            ? '已配置；真实地址不会回显，留空不会覆盖。'
            : '保存前需要输入与所选类型匹配的 HTTPS 地址。'}
        </Description>
        {fieldError && <FieldError>{fieldError}</FieldError>}
      </TextField>
    </div>
    {supportsSigning && <div className="grid gap-3 min-[720px]:grid-cols-2">
      <div className="grid content-start gap-1">
        <Switch
          isSelected={signingEnabled}
          isDisabled={readOnly}
          aria-describedby={`${idPrefix}-signing-help`}
          onChange={onSigningEnabledChange}
        >
          <Switch.Content>
            <Switch.Control><Switch.Thumb /></Switch.Control>
            启用机器人签名校验
          </Switch.Content>
        </Switch>
        <Description id={`${idPrefix}-signing-help`}>
          仅在接收端机器人已启用签名校验时填写对应 Secret。
        </Description>
      </div>
      {signingEnabled && <TextField
        fullWidth
        value={signingSecret}
        onChange={onSigningSecretChange}
        isDisabled={readOnly}
        isInvalid={Boolean(signingError)}
        isRequired={!readOnly && !signingConfigured}
      >
        <Label>签名 Secret</Label>
        <Input
          type="password"
          autoComplete="new-password"
          placeholder={signingConfigured ? '留空保持当前 Secret' : '输入机器人签名 Secret'}
        />
        <Description>
          {signingConfigured
            ? '已配置；Secret 不会回显。关闭签名会清除当前 Secret。'
            : 'Secret 只写入安全存储，不会出现在响应或日志中。'}
        </Description>
        {signingError && <FieldError>{signingError}</FieldError>}
      </TextField>}
    </div>}
    <Description id={`${idPrefix}-help`}>
      {selected?.description || '选择接收端类型后，系统会使用对应请求格式。'}
    </Description>
  </fieldset>
}
