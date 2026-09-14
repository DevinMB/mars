import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev` talks to a backend running on 8080.
    proxy: {
      '/api': 'http://localhost:8080',
      '/healthz': 'http://localhost:8080',
      '/metrics': 'http://localhost:8080',
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
