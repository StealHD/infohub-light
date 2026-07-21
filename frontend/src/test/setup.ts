import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

if (!Element.prototype.getAnimations) {
  Object.defineProperty(Element.prototype, 'getAnimations', { configurable: true, value: () => [] })
}

if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  })
}

if (typeof globalThis.ResizeObserver !== 'function') {
  class TestResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: TestResizeObserver })
  Object.defineProperty(window, 'ResizeObserver', { configurable: true, value: TestResizeObserver })
}

afterEach(cleanup)
