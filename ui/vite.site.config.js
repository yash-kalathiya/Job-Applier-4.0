import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// the public site (apply.twinly.tech): landing page + installer, built separately from the local app
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: '../site', emptyOutDir: true, chunkSizeWarningLimit: 900, rollupOptions: { input: ['site.html', 'app.html'] } },
})
