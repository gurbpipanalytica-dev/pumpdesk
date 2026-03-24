import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://localhost:8765',
      '/status': 'http://localhost:8765',
      '/positions': 'http://localhost:8765',
      '/trades': 'http://localhost:8765',
      '/assessment': 'http://localhost:8765',
      '/hot-tokens': 'http://localhost:8765',
      '/blacklist': 'http://localhost:8765',
      '/ws': { target: 'ws://localhost:8765', ws: true },
    },
  },
})

