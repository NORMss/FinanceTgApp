import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: {
    // Mini App грузится по мобильному интернету: чем меньше и меньшим числом файлов, тем лучше
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 300,
  },
  server: {
    port: 5173,
    // Локально фронт живёт отдельно от бэкенда — проксируем, чтобы не возиться с CORS
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
