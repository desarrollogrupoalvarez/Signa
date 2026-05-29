import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers && String(proxyRes.req?.path || '').match(/^\/api\/(documentos|firmados)/)) {
              proxyRes.headers['cache-control'] = 'no-store, no-cache, must-revalidate'
              proxyRes.headers['pragma'] = 'no-cache'
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
