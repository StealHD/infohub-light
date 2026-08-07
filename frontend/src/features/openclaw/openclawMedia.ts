export const OPENCLAW_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const
export type OpenClawImageMimeType = typeof OPENCLAW_IMAGE_MIME_TYPES[number]

export const OPENCLAW_MAX_IMAGES_PER_TURN = 4
export const OPENCLAW_MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const OPENCLAW_MAX_TOTAL_IMAGE_BYTES = 12 * 1024 * 1024
export const OPENCLAW_MAX_IMAGE_PIXELS = 40_000_000
export const OPENCLAW_MAX_IMAGE_EDGE = 2048
const OPENCLAW_MAX_SOURCE_IMAGE_BYTES = 20 * 1024 * 1024

export type OpenClawImageAttachment = {
  id: string
  mimeType: OpenClawImageMimeType
  fileName: string
  content: string
  previewUrl: string
  width: number
  height: number
  byteLength: number
}

export type OpenClawMediaReference = {
  messageId: string
  partIndex: number
}

export type OpenClawMessageImage = {
  id: string
  alt: string
  mimeType?: OpenClawImageMimeType
  width?: number
  height?: number
  reference?: OpenClawMediaReference
  /** In-memory only: a local object URL, a data URL validated by this module, or a ticket URL. */
  url?: string
}

export type OpenClawMediaTicket = {
  path: string
  mediaTicket: string
  expiresAt: string
  mimeType: OpenClawImageMimeType
  width?: number
  height?: number
}

function isImageMimeType(value: unknown): value is OpenClawImageMimeType {
  return typeof value === 'string' && (OPENCLAW_IMAGE_MIME_TYPES as readonly string[]).includes(value)
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : undefined
}

function base64ByteLength(value: string): number {
  const normalized = value.replace(/\s/g, '')
  const padding = normalized.endsWith('==') ? 2 : normalized.endsWith('=') ? 1 : 0
  return Math.max(0, Math.floor((normalized.length * 3) / 4) - padding)
}

function dataUrlMimeType(value: string): OpenClawImageMimeType | null {
  const match = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)$/u.exec(value)
  if (!match || !isImageMimeType(match[1]) || base64ByteLength(match[2]) > OPENCLAW_MAX_IMAGE_BYTES) return null
  return match[1]
}

export function isSafeOpenClawImageDataUrl(value: unknown): value is string {
  return typeof value === 'string' && Boolean(dataUrlMimeType(value))
}

export function normalizeOpenClawMediaOrigin(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const parsed = new URL(value.trim())
    if (
      (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')
      || !parsed.hostname
      || parsed.username
      || parsed.password
      || parsed.pathname !== '/'
      || parsed.search
      || parsed.hash
    ) return null
    const loopback = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost'
    if (parsed.protocol === 'http:' && !loopback) return null
    return parsed.origin
  } catch {
    return null
  }
}

function gatewayHttpOrigin(gatewayUrl: string): string | null {
  try {
    const parsed = new URL(gatewayUrl)
    if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') return null
    parsed.protocol = parsed.protocol === 'wss:' ? 'https:' : 'http:'
    parsed.pathname = '/'
    parsed.search = ''
    parsed.hash = ''
    return parsed.origin
  } catch {
    return null
  }
}

export function ticketUrlForOpenClawMedia(
  gatewayUrl: string,
  ticket: OpenClawMediaTicket,
  allowedOrigins: readonly string[],
): string | null {
  const origin = gatewayHttpOrigin(gatewayUrl)
  const normalizedOrigins = new Set(allowedOrigins.map(normalizeOpenClawMediaOrigin).filter((value): value is string => Boolean(value)))
  if (!origin || !normalizedOrigins.has(origin)) return null
  if (!ticket.path.startsWith('/') || ticket.path.startsWith('//') || ticket.path.includes('\\') || ticket.path.includes('?')) return null
  if (!ticket.mediaTicket || ticket.mediaTicket.length > 4096 || /\s/u.test(ticket.mediaTicket)) return null
  if (!isImageMimeType(ticket.mimeType) || !Number.isFinite(Date.parse(ticket.expiresAt))) return null
  try {
    const url = new URL(ticket.path, origin)
    if (url.origin !== origin) return null
    url.searchParams.set('mediaTicket', ticket.mediaTicket)
    return url.toString()
  } catch {
    return null
  }
}

export function parseOpenClawMediaTicket(value: unknown): OpenClawMediaTicket | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const source = value as Record<string, unknown>
  const mimeType = source.mimeType
  const path = source.path
  const mediaTicket = source.mediaTicket
  const expiresAt = source.expiresAt
  if (
    typeof path !== 'string'
    || typeof mediaTicket !== 'string'
    || typeof expiresAt !== 'string'
    || !isImageMimeType(mimeType)
  ) return null
  return {
    path,
    mediaTicket,
    expiresAt,
    mimeType,
    ...(positiveInteger(source.width) ? { width: positiveInteger(source.width) } : {}),
    ...(positiveInteger(source.height) ? { height: positiveInteger(source.height) } : {}),
  }
}

function fileToDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('无法读取图片文件。'))
    reader.onload = () => typeof reader.result === 'string'
      ? resolve(reader.result)
      : reject(new Error('无法读取图片文件。'))
    reader.readAsDataURL(file)
  })
}

async function readImageSource(file: File): Promise<{
  source: CanvasImageSource
  width: number
  height: number
  release: () => void
}> {
  if (typeof globalThis.createImageBitmap === 'function') {
    const bitmap = await globalThis.createImageBitmap(file)
    return { source: bitmap, width: bitmap.width, height: bitmap.height, release: () => bitmap.close() }
  }
  const previewUrl = URL.createObjectURL(file)
  const image = new Image()
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('无法读取图片尺寸。'))
      image.src = previewUrl
    })
    return { source: image, width: image.naturalWidth, height: image.naturalHeight, release: () => URL.revokeObjectURL(previewUrl) }
  } catch (error) {
    URL.revokeObjectURL(previewUrl)
    throw error
  }
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('浏览器无法规范化此图片。')), 'image/webp', 0.9)
  })
}

export async function normalizeOpenClawImage(file: File, sequence: number): Promise<OpenClawImageAttachment> {
  if (!isImageMimeType(file.type)) throw new Error('仅支持 JPEG、PNG 或 WebP 图片。')
  if (file.size <= 0 || file.size > OPENCLAW_MAX_SOURCE_IMAGE_BYTES) throw new Error('图片原文件超过 20 MiB 限制。')
  const decoded = await readImageSource(file)
  try {
    if (!decoded.width || !decoded.height || decoded.width * decoded.height > OPENCLAW_MAX_IMAGE_PIXELS) {
      throw new Error('图片像素超过 4000 万限制。')
    }
    const ratio = Math.min(1, OPENCLAW_MAX_IMAGE_EDGE / Math.max(decoded.width, decoded.height))
    const width = Math.max(1, Math.round(decoded.width * ratio))
    const height = Math.max(1, Math.round(decoded.height * ratio))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d', { alpha: true })
    if (!context) throw new Error('浏览器无法处理此图片。')
    context.drawImage(decoded.source, 0, 0, width, height)
    const normalized = await canvasBlob(canvas)
    if (normalized.size > OPENCLAW_MAX_IMAGE_BYTES) throw new Error('图片规范化后超过 5 MiB 限制。')
    const encoded = await fileToDataUrl(normalized)
    const content = encoded.slice(encoded.indexOf(',') + 1)
    return {
      id: crypto.randomUUID(),
      mimeType: 'image/webp',
      fileName: `image-${sequence}.webp`,
      content,
      previewUrl: URL.createObjectURL(normalized),
      width,
      height,
      byteLength: normalized.size,
    }
  } finally {
    decoded.release()
  }
}

export function releaseOpenClawImageAttachment(image: Pick<OpenClawImageAttachment, 'previewUrl'>): void {
  releaseOpenClawImageUrl(image.previewUrl)
}

export function releaseOpenClawImageUrl(url: string | undefined): void {
  if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
}
