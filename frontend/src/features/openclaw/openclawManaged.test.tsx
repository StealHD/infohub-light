import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { isManagedGateway, managedGatewayUrl } from './gateway/openclawManaged'
import { initialOpenClawGatewayUrl } from './lifecycle/useOpenClawConnection'
import { OpenClawGatewayClient, type GatewaySocket } from './openclawGateway'
import { OpenClawManagedSetup } from './ui/OpenClawManagedSetup'
import { setupIssue, MissingOpenClawCredentialError } from './chat/openclawSetupIssue'
import type { OpenClawChatController } from './openclawContracts'

class Socket implements GatewaySocket {
  readyState = 0
  sent: string[] = []
  listeners = new Map<string, ((event: unknown) => void)[]>()
  addEventListener(type: string, listener: (event: unknown) => void) { this.listeners.set(type, [...this.listeners.get(type) ?? [], listener]) }
  send(value: string) { this.sent.push(value) }
  close() { this.readyState = 3 }
  emit(type: string, event: unknown = {}) { if (type === 'open') this.readyState = 1; this.listeners.get(type)?.forEach((fn) => fn(event)) }
}

describe('managed OpenClaw', () => {
  it('uses same-origin server endpoint instead of saved browser gateway', () => {
    expect(initialOpenClawGatewayUrl('owner', '/api/me/openclaw/socket')).toBe(managedGatewayUrl())
    expect(isManagedGateway('wss://evil.test/api/me/openclaw/socket')).toBe(false)
  })
  it('never sends a Gateway credential or device signature to the browser transport', async () => {
    const socket = new Socket()
    const client = new OpenClawGatewayClient({url: managedGatewayUrl(), socketFactory: () => socket,
      deviceIdentity: {deviceId:'unused', publicKey:'unused', privateKey:{} as CryptoKey}, bootstrapToken:'must-not-be-sent'})
    const ready = client.connect()
    socket.emit('open')
    socket.emit('message', {data: JSON.stringify({type:'event',event:'connect.challenge',payload:{nonce:'infohub-session'}})})
    await waitFor(() => expect(socket.sent).toHaveLength(1))
    const frame = JSON.parse(socket.sent[0])
    expect(frame.method).toBe('connect')
    expect(frame.params).toEqual({})
    expect(socket.sent.join('')).not.toContain('must-not-be-sent')
    socket.emit('message',{data:JSON.stringify({type:'res',id:frame.id,ok:true,payload:{protocol:4,auth:{role:'operator',scopes:['operator.read','operator.write']}}})})
    await ready
    client.close()
  })
  it('shows a server connect action without a credential field', () => {
    render(<OpenClawManagedSetup chat={{status:'idle',connect:vi.fn()} as unknown as OpenClawChatController} />)
    expect(screen.getByRole('button',{name:'连接'})).toBeVisible()
    expect(screen.queryByLabelText('OpenClaw Gateway token')).toBeNull()
  })
  it('does not call a missing input an invalid token', () => {
    expect(setupIssue(new MissingOpenClawCredentialError()).message).toContain('尚未配对')
  })
})
