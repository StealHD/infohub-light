import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

if (!Element.prototype.getAnimations) {
  Object.defineProperty(Element.prototype, 'getAnimations', { configurable: true, value: () => [] })
}

afterEach(cleanup)
