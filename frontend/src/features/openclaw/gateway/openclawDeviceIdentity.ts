import type { OpenClawDeviceIdentity } from './openclawGatewayTypes'

function toBase64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function generateDeviceIdentity(): Promise<OpenClawDeviceIdentity> {
  const generated = await crypto.subtle.generateKey(
    { name: 'Ed25519' },
    true,
    ['sign', 'verify'],
  ) as CryptoKeyPair
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey('raw', generated.publicKey))
  const privateBytes = new Uint8Array(await crypto.subtle.exportKey('pkcs8', generated.privateKey))
  const privateKey = await crypto.subtle.importKey(
    'pkcs8',
    privateBytes,
    { name: 'Ed25519' },
    false,
    ['sign'],
  )
  privateBytes.fill(0)
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', publicBytes))
  return { deviceId: toHex(digest), publicKey: toBase64Url(publicBytes), privateKey }
}

export async function signDevicePayload(privateKey: CryptoKey, payload: string): Promise<string> {
  const signature = await crypto.subtle.sign(
    { name: 'Ed25519' },
    privateKey,
    new TextEncoder().encode(payload),
  )
  return toBase64Url(new Uint8Array(signature))
}
