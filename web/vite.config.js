import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端通过 /api 前缀调用后端，开发环境由 Vite 代理转发到 Spring Boot，
// 从而避免跨域（CORS）问题，无需修改 Java 后端。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
