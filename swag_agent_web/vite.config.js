import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端通过 /api 前缀调用后端，开发环境由 Vite 代理转发到 Python 的 8081 端口。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      // 本地直连 Zipkin；生产是 nginx 反代 + 管理员鉴权，不经过 Vite
      '/zipkin': {
        target: 'http://localhost:9411',
        changeOrigin: true
      }
    }
  }
})
