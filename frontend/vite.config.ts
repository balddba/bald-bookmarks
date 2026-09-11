import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const documentPolicyHeaders = {
  'Document-Policy': 'js-profiling',
}

export default defineConfig({
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
