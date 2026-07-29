import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import {
  notificationChannelConfigured,
  notificationDestinationError,
  notificationTestLabel,
  safeNotificationError,
} from './notificationModel'

describe('notification model', () => {
  it('selects only the configured state for the active channel', () => {
    const settings = { email_configured: true, webhook_configured: false }
    expect(notificationChannelConfigured(settings, 'email')).toBe(true)
    expect(notificationChannelConfigured(settings, 'webhook')).toBe(false)
  })

  it('requires a destination only when enabling an unconfigured channel', () => {
    expect(notificationDestinationError({
      channel: 'email',
      destination: '',
      configured: false,
      enabled: true,
    })).toBe('启用邮件通知前，请填写收件邮箱。')
    expect(notificationDestinationError({
      channel: 'email',
      destination: '',
      configured: false,
      enabled: false,
    })).toBe('')
    expect(notificationDestinationError({
      channel: 'webhook',
      destination: 'http://example.invalid/hook',
      configured: false,
      enabled: true,
    })).toBe('Webhook 地址必须使用 HTTPS。')
  })

  it('never repeats an unsafe server message in user-facing notification errors', () => {
    const caught = new ApiError(502, {
      code: 'upstream_rejected',
      message: 'unsafe destination and raw upstream response',
    })
    expect(safeNotificationError(caught, '测试通知发送失败，请稍后重试。')).toBe('测试通知发送失败，请稍后重试。')
    expect(safeNotificationError(caught, '测试通知发送失败，请稍后重试。')).not.toContain('unsafe')
    expect(safeNotificationError(new ApiError(429, {
      code: 'notification_test_rate_limited',
      message: 'internal cooldown detail',
    }), '测试通知发送失败，请稍后重试。')).toBe('测试通知发送过于频繁，请稍后再试。')
    expect(safeNotificationError(new ApiError(502, {
      code: 'notification_test_outcome_unknown',
      message: 'raw upstream response must stay private',
    }), '测试通知发送失败，请稍后重试。')).toBe('测试通知结果未知，请勿重复发送；请先确认接收端。')
  })

  it('normalizes safe last-test labels without exposing backend detail', () => {
    expect(notificationTestLabel(null)).toBe('尚未发送测试通知')
    expect(notificationTestLabel('succeeded')).toBe('最近一次测试请求已发送，请确认接收端')
    expect(notificationTestLabel('sent', {
      channel: 'email',
      verificationMode: 'http_status',
    })).toBe('最近一次测试邮件已发送，请确认收件箱')
    expect(notificationTestLabel('sent', {
      channel: 'webhook',
      verificationMode: 'provider_response',
    })).toBe('最近一次测试已获平台接受，请确认接收端')
    expect(notificationTestLabel('failed')).toBe('最近一次测试发送失败')
    expect(notificationTestLabel('unknown')).toBe('最近一次测试结果未知，不会自动重发')
    expect(notificationTestLabel('provider-specific-detail')).toBe('最近一次测试状态未知')
  })
})
