import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式：前端 5173，/api 代理到后端 8000（uvicorn app.main:app --reload）
// 生产模式：npm run build 后由后端 StaticFiles 托管，同源无跨域
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    rollupOptions: {
      output: {
        // ECharts 单独成 chunk，只随用到图表的页面（DataBoard / InsightCockpit）按需加载。
        // 注意：只提取 echarts 本身（含 zrender），不把 echarts-for-react 一并纳入——
        // 后者依赖 React，若纳入会把 React 也拖进 echarts chunk，反导致入口静态引用它。
        manualChunks: {
          echarts: ['echarts', 'zrender'],
        },
      },
    },
  },
})
