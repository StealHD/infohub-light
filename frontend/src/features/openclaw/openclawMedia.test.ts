import { describe, expect, it } from 'vitest'

import {
  isSafeOpenClawImageDataUrl,
  normalizeOpenClawMediaOrigin,
  parseOpenClawMediaTicket,
  ticketUrlForOpenClawMedia,
} from './openclawMedia'

describe('OpenClaw image media boundary', () => {
  it('accepts only bounded image data URLs', () => {
    expect(isSafeOpenClawImageDataUrl('data:image/webp;base64,AAAA')).toBe(true)
    expect(isSafeOpenClawImageDataUrl('data:image/svg+xml;base64,AAAA')).toBe(false)
    expect(isSafeOpenClawImageDataUrl('https://untrusted.example/image.webp')).toBe(false)
  })

  it('renders only a ticket path from an allowlisted Gateway origin', () => {
    const ticket = parseOpenClawMediaTicket({
      path: '/api/chat/media/outgoing/session-a/attachment/full',
      mediaTicket: 'v1.ticket-value',
      expiresAt: '2026-08-07T12:00:00.000Z',
      mimeType: 'image/webp',
      width: 1024,
      height: 768,
    })
    expect(ticket).not.toBeNull()
    expect(ticketUrlForOpenClawMedia(
      'wss://openclaw.example.com/gateway',
      ticket!,
      ['https://openclaw.example.com'],
    )).toBe('https://openclaw.example.com/api/chat/media/outgoing/session-a/attachment/full?mediaTicket=v1.ticket-value')
    expect(ticketUrlForOpenClawMedia(
      'wss://openclaw.example.com/gateway',
      ticket!,
      ['https://other.example.com'],
    )).toBeNull()
    expect(ticketUrlForOpenClawMedia(
      'wss://openclaw.example.com/gateway',
      { ...ticket!, path: '//untrusted.example/image.webp' },
      ['https://openclaw.example.com'],
    )).toBeNull()
  })

  it('keeps plain HTTP media origins loopback-only', () => {
    expect(normalizeOpenClawMediaOrigin('http://127.0.0.1:18789')).toBe('http://127.0.0.1:18789')
    expect(normalizeOpenClawMediaOrigin('http://openclaw.example.com')).toBeNull()
    expect(normalizeOpenClawMediaOrigin('https://openclaw.example.com/path')).toBeNull()
  })
})
