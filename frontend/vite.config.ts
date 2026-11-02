import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Python API runs on :8000 (API_URL overrides it, e.g. for a test server); the phone
// talks to Vite, which forwards these.
const api = process.env.API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // reachable from a phone on the same Wi-Fi
    proxy: {
      '/api': api,
      '/images': api,
      '/tryon': api,
    },
  },
})
