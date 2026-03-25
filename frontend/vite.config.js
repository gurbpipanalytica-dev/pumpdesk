import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/status': 'http://localhost:8766',
      '/positions': 'http://localhost:8766',
      '/trades': 'http://localhost:8766',
      '/hot-tokens': 'http://localhost:8766',
      '/assessment': 'http://localhost:8766',
      '/bots': 'http://localhost:8766',
      '/launched-tokens': 'http://localhost:8766',
      '/config': 'http://localhost:8766',
      '/blacklist': 'http://localhost:8766',
      '/health': 'http://localhost:8766',
      '/ws': { target: 'ws://localhost:8766', ws: true },
    },
  },
});

