import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期把 /api 代理到后端，前端只写相对路径，免去 CORS 与地址切换。
// e2e 用 VITE_API_TARGET 指向独立的 e2e 后端，避免污染开发库。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
