import { useEffect, useRef, useState } from 'react'

import {
  OPENCLAW_MAX_IMAGES_PER_TURN,
  OPENCLAW_MAX_TOTAL_IMAGE_BYTES,
  normalizeOpenClawImage,
  releaseOpenClawImageAttachment,
  type OpenClawImageAttachment,
} from '../openclawMedia'

export function useOpenClawAttachments(imageInputAvailable: boolean) {
  const draftRef = useRef<OpenClawImageAttachment[]>([])
  const [attachments, setAttachments] = useState<OpenClawImageAttachment[]>([])
  const [issue, setIssue] = useState<string | null>(null)

  useEffect(() => { draftRef.current = attachments }, [attachments])
  useEffect(() => () => { draftRef.current.forEach(releaseOpenClawImageAttachment) }, [])

  async function append(files: File[]) {
    if (!files.length || !imageInputAvailable) return
    let next = [...attachments]
    const errors: string[] = []
    for (const file of files) {
      if (next.length >= OPENCLAW_MAX_IMAGES_PER_TURN) {
        errors.push(`每次最多添加 ${OPENCLAW_MAX_IMAGES_PER_TURN} 张图片。`)
        break
      }
      try {
        const image = await normalizeOpenClawImage(file, next.length + 1)
        const totalBytes = next.reduce((total, candidate) => total + candidate.byteLength, 0) + image.byteLength
        if (totalBytes > OPENCLAW_MAX_TOTAL_IMAGE_BYTES) {
          releaseOpenClawImageAttachment(image)
          errors.push('本次图片总大小超过 12 MiB 限制。')
          continue
        }
        next = [...next, image]
      } catch (error) {
        errors.push(error instanceof Error ? error.message : '无法添加图片。')
      }
    }
    setAttachments(next)
    setIssue(errors[0] ?? null)
  }

  function remove(id: string) {
    setAttachments((current) => {
      const removed = current.find((attachment) => attachment.id === id)
      if (removed) releaseOpenClawImageAttachment(removed)
      return current.filter((attachment) => attachment.id !== id)
    })
    setIssue(null)
  }

  function markSent() {
    setAttachments([])
    setIssue(null)
  }

  return { attachments, issue, append, remove, markSent }
}
