import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET?.trim() || 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 5173,
    proxy: {
      '/api': apiProxyTarget,
    },
  },
  build: {
    outDir: '../src/ui/service_static',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
})
