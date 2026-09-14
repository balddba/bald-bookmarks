import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const documentPolicyHeaders = {
  'Document-Policy': 'js-profiling',
}

const frontendDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  envDir: path.resolve(frontendDir, '..'),
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    headers: documentPolicyHeaders,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/media': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    headers: documentPolicyHeaders,
  },
})
