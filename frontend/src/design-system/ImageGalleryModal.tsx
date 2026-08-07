import { useEffect, useRef, useState } from 'react'

import { Button, Modal, Skeleton } from '@heroui/react'

import * as Icons from './icons'

export type ImageGalleryImage = {
  id?: string
  url: string
  alt?: string
  width?: number
  height?: number
}

export function ImageGalleryModal({
  isOpen,
  heading = '图片预览',
  images,
  index,
  onIndexChange,
  onOpenChange,
  onRefresh,
}: {
  isOpen: boolean
  heading?: string
  images: ImageGalleryImage[]
  index: number
  onIndexChange: (index: number) => void
  onOpenChange: (open: boolean) => void
  onRefresh?: (image: ImageGalleryImage) => void
}) {
  const active = images[index]
  useEffect(() => {
    if (!isOpen || images.length < 2) return
    const onKeyDown = (event: KeyboardEvent) => {
      const delta = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
      if (!delta) return
      event.preventDefault()
      onIndexChange((index + delta + images.length) % images.length)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [images.length, index, isOpen, onIndexChange])

  useEffect(() => {
    if (!isOpen || images.length < 2 || typeof Image === 'undefined') return
    for (const neighborIndex of [
      (index - 1 + images.length) % images.length,
      (index + 1) % images.length,
    ]) {
      const image = new Image()
      image.src = images[neighborIndex]?.url ?? ''
    }
  }, [images, index, isOpen])

  return <Modal isOpen={Boolean(isOpen && active)} onOpenChange={onOpenChange}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开图片预览</Modal.Trigger>
    <Modal.Backdrop variant="opaque" isDismissable>
      <Modal.Container size="cover" placement="center" className="p-3 sm:w-full sm:p-6">
        <Modal.Dialog className="h-full min-h-0 max-w-none overflow-hidden rounded-2xl bg-overlay p-0 text-foreground">
          <div className="relative flex h-full min-h-0 flex-col">
            <Modal.Header className="sr-only"><Modal.Heading>{heading}</Modal.Heading></Modal.Header>
            <Modal.CloseTrigger aria-label="关闭图片预览" className="z-20 size-11 rounded-full bg-background/80 text-foreground hover:bg-default" />
            <Modal.Body className="relative m-0 grid min-h-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden p-0 text-foreground">
              {active && <ImageGalleryStage
                key={`${active.id ?? active.url}:${index}`}
                image={active}
                index={index}
                total={images.length}
                onMove={(delta) => onIndexChange((index + delta + images.length) % images.length)}
                onRefresh={onRefresh}
              />}
              {images.length > 1 && <div
                data-testid="media-viewer-thumbnails"
                role="group"
                aria-label="图片缩略图"
                className="quiet-scroll-region overflow-x-auto border-t border-separator bg-overlay px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3"
              >
                <div className="flex w-max min-w-full justify-start gap-2 sm:justify-center">
                  {images.map((image, imageIndex) => <button
                    key={`${image.id ?? image.url}:${imageIndex}`}
                    type="button"
                    aria-label={`切换到第 ${imageIndex + 1} 张图片`}
                    aria-current={imageIndex === index ? 'true' : undefined}
                    aria-controls="media-viewer-stage"
                    className={`size-12 shrink-0 overflow-hidden rounded-lg border-2 bg-background/80 focus-visible:outline-2 focus-visible:outline-focus transition-[opacity,transform,box-shadow] motion-reduce:transition-none ${imageIndex === index ? 'border-transparent shadow-[0_0_0_2px_var(--accent)]' : 'border-transparent opacity-70 hover:opacity-100 active:scale-95'}`}
                    onClick={() => onIndexChange(imageIndex)}
                  ><img src={image.url} alt="" className="size-full object-cover" loading="eager" referrerPolicy="no-referrer" /></button>)}
                </div>
              </div>}
            </Modal.Body>
          </div>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

function ImageGalleryStage({
  image,
  index,
  total,
  onMove,
  onRefresh,
}: {
  image: ImageGalleryImage
  index: number
  total: number
  onMove: (delta: number) => void
  onRefresh?: (image: ImageGalleryImage) => void
}) {
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [retryKey, setRetryKey] = useState(0)
  const swipeStart = useRef<number | null>(null)
  return <div
    id="media-viewer-stage"
    data-testid="media-viewer-stage"
    className="relative grid min-h-0 min-w-0 touch-pan-y place-items-center overflow-hidden bg-default/40"
    onPointerDown={(event) => {
      if (event.pointerType === 'mouse' || (event.target instanceof Element && event.target.closest('button'))) return
      swipeStart.current = event.clientX
      event.currentTarget.setPointerCapture?.(event.pointerId)
    }}
    onPointerUp={(event) => {
      const start = swipeStart.current
      swipeStart.current = null
      if (start === null || total < 2) return
      const distance = event.clientX - start
      if (Math.abs(distance) >= 48) onMove(distance > 0 ? -1 : 1)
    }}
    onPointerCancel={() => { swipeStart.current = null }}
  >
    {loading && !failed && <Skeleton aria-label="正在加载图片" className="absolute inset-[10%] rounded-2xl" />}
    <img
      key={`${image.url}:${retryKey}`}
      data-testid="media-viewer-image"
      src={image.url}
      alt={image.alt || `图片 ${index + 1}`}
      className={`z-[1] block size-full min-h-0 min-w-0 object-contain transition-opacity motion-reduce:transition-none ${loading || failed ? 'opacity-0' : 'opacity-100'}`}
      width={image.width}
      height={image.height}
      referrerPolicy="no-referrer"
      onLoad={() => { setLoading(false); setFailed(false) }}
      onError={() => { setLoading(false); setFailed(true); onRefresh?.(image) }}
    />
    {failed && <div role="alert" className="absolute left-1/2 top-1/2 z-[2] grid -translate-x-1/2 -translate-y-1/2 justify-items-center gap-3 rounded-2xl bg-background/90 p-5 text-center">
      <Icons.ImageOff size={28} className="text-muted" aria-hidden="true" />
      <p className="type-control">图片加载失败</p>
      <Button size="sm" variant="secondary" onPress={() => {
        setFailed(false)
        setLoading(true)
        setRetryKey((value) => value + 1)
        onRefresh?.(image)
      }}>重试这张图片</Button>
    </div>}
    <p role="status" aria-live="polite" aria-atomic="true" className="type-control absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full bg-background/80 px-3 py-1.5 text-foreground">{index + 1} / {total}</p>
    {total > 1 && <>
      <Button isIconOnly variant="secondary" className="absolute left-3 top-1/2 z-10 size-11 -translate-y-1/2 rounded-full bg-background/80 text-foreground hover:bg-default sm:left-5" aria-label="上一张图片" onPress={() => onMove(-1)}><Icons.ChevronLeft size={22} aria-hidden="true" /></Button>
      <Button isIconOnly variant="secondary" className="absolute right-3 top-1/2 z-10 size-11 -translate-y-1/2 rounded-full bg-background/80 text-foreground hover:bg-default sm:right-5" aria-label="下一张图片" onPress={() => onMove(1)}><Icons.ChevronRight size={22} aria-hidden="true" /></Button>
    </>}
  </div>
}
