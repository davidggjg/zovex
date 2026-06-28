import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  base: '/zovex/',
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Dev-only proxy: requests to /tg-proxy/* are forwarded to the Telegram stream bot,
    // bypassing CORS restrictions during local development.
    // In production, set VITE_TELEGRAM_PROXY to your deployed bot's base URL.
    proxy: {
      '/tg-proxy': {
        target: 'https://telegram-bot-8528.onrender.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/tg-proxy/, ''),
      },
    },
  },
})
