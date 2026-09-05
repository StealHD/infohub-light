import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET?.trim() || 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [tailwindcss(), react(), {
    name: 'isolated-workbench-preview',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        if (request.url?.split('?')[0] === '/__preview/workbench-heroui') request.url = '/preview-workbench.html'
        next()
      })
    },
  }],
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
