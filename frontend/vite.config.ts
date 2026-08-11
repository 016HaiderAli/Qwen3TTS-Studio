import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend serves the same-origin API under /api and /auth via the Vite
// dev-server proxy (single exposed port preview). See the frontend reverse
// proxy rule.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    allowedHosts: ['.monkeycode-ai.live'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
