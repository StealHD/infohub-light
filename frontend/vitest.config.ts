import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    restoreMocks: true,
    maxWorkers: 2,
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**'],
  },
})
