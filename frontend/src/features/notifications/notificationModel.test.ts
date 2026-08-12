import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import { safeNotificationError } from './notificationModel'

describe('notification model', () => {
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
    expect(safeNotificationError(new ApiError(409, {
      code: 'telegram_transport_token_unavailable',
      message: 'private binding detail',
    }), '测试通知发送失败，请稍后重试。')).toBe('Bot Token 缺失或已变化，请重新保存。')
  })

})
