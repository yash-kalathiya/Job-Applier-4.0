import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const api = 'http://127.0.0.1:4747'
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: '../web', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { '/api': api, '/preview': api, '/file': api } },
})
